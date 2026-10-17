"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { tokens, input, btnDark } from "../styles";
import type { DiffRow } from "../components/ProposalDiff";
import { hhmm } from "../lib/inbox";
import { errorCopy } from "./errors";
import type { ChatError } from "./errors";
import ProposalCard, {
  readProposalToken,
  saveProposalToken,
  toProposal,
} from "./ProposalCard";
import type { LiveStatus, Proposal, ServerProposal } from "./ProposalCard";
import Markdown from "./Markdown";
import ThreadSidebar from "./ThreadSidebar";
import ToolSteps from "./ToolSteps";
import SourceChips, { dedupeSources } from "./SourceChips";
import type { Source } from "./labels";
import {
  EMPTY_LANE,
  laneAppend,
  laneToolResult,
  laneToolStart,
  stepsFromParts,
  useChatStream,
  useTokenBuffer,
} from "./useChatStream";
import type { Lane, StreamOutcome } from "./useChatStream";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type TraceStep = {
  tool: string;
  args: Record<string, unknown>;
  result: Record<string, unknown>;
};

type UserItem = { kind: "user"; id: string; text: string };

type AsstItem = {
  kind: "assistant";
  id: string;
  status: "running" | "complete" | "error" | "cancelled";
  text: string;
  lane: Lane; // streamed draft + steps / working notes (D-24)
  stoppedPartial?: string; // live view only: the partial text kept after Stop (D-03a)
  proposals: Proposal[];
  error: ChatError | null;
  model: { name: string | null; provider: string | null } | null;
  createdAt: string | null;
  live: boolean; // answered in this view (state text "just now")
  stopRejected?: boolean;
};

type Item = UserItem | AsstItem;

// D-21: five static, synthetic example questions for an empty thread.
const EXAMPLES = [
  { caption: "Read", question: "How much did I spend this month?" },
  { caption: "Breakdown", question: "What were my top spending categories last month?" },
  { caption: "Compare", question: "Compare my spending last month against this month" },
  { caption: "Recurring", question: "What are my recurring charges?" },
  { caption: "Propose a change", question: "Add coffee 25000 to my Cash account" },
];

type PersistedMessage = {
  id: string;
  seq: number;
  role: string;
  content: string;
  status: string;
  created_at: string;
  parts?: {
    steps?: { tool: string; args?: Record<string, unknown>; ms?: number; sources?: Source[] }[];
    proposals?: (ServerProposal & { status?: string })[];
    error?: { code?: string } | null;
    provider?: { name?: string | null; model?: string | null } | null;
  };
};

type ThreadDetail = {
  id: string;
  active_run: { run_id: string } | null;
  messages: PersistedMessage[];
};

const NOT_FOUND = "404";

async function fetchThread(id: string): Promise<ThreadDetail | typeof NOT_FOUND | "error"> {
  try {
    const r = await fetch(`/api/threads/${id}`);
    if (r.status === 404) return NOT_FOUND;
    if (!r.ok) return "error";
    const d = await r.json();
    return Array.isArray(d?.messages) ? (d as ThreadDetail) : "error";
  } catch {
    return "error";
  }
}

function mapMessages(list: PersistedMessage[]): Item[] {
  return [...list]
    .sort((a, b) => a.seq - b.seq)
    .map((m): Item => {
      if (m.role !== "assistant") return { kind: "user", id: m.id, text: m.content };
      const parts = m.parts ?? {};
      const status: AsstItem["status"] =
        m.status === "error" || m.status === "cancelled" ? m.status : "complete";
      return {
        kind: "assistant",
        id: m.id,
        status,
        text: m.content,
        lane: { ...EMPTY_LANE, timeline: stepsFromParts(parts.steps) },
        proposals: (parts.proposals ?? []).map((p) => ({
          ...toProposal({ ...p, token: null }),
          liveStatus: (p.status ?? "missing") as LiveStatus,
        })),
        error:
          status === "error"
            ? {
                code: parts.error?.code ?? "unknown",
                model: parts.provider?.model ?? null,
                idleSeconds: null,
              }
            : null,
        model: parts.provider
          ? { name: parts.provider.model ?? null, provider: parts.provider.name ?? null }
          : null,
        createdAt: m.created_at,
        live: false,
      };
    });
}

function runningItem(id: string): AsstItem {
  return {
    kind: "assistant",
    id,
    status: "running",
    text: "",
    lane: EMPTY_LANE,
    proposals: [],
    error: null,
    model: null,
    createdAt: null,
    live: true,
  };
}

// "answered just now" for the turn answered in this view, else an absolute time.
function answeredLabel(m: AsstItem): string {
  const ms = m.createdAt ? Date.parse(m.createdAt) : NaN;
  if (m.live || Number.isNaN(ms)) return "answered just now";
  const d = new Date(ms);
  const t = new Date();
  const sameDay =
    d.getFullYear() === t.getFullYear() &&
    d.getMonth() === t.getMonth() &&
    d.getDate() === t.getDate();
  return sameDay
    ? `answered ${hhmm(ms)}`
    : `answered ${d.toLocaleDateString(undefined, { day: "numeric", month: "short" })}, ${hhmm(ms)}`;
}

// The Stopped status line, rendered and announced from one place (D-21).
function stoppedLine(m: AsstItem): string {
  return (
    (m.stoppedPartial?.trim()
      ? "Stopped. This partial answer was not saved."
      : "Stopped. No answer was kept.") +
    (m.stopRejected || m.proposals.length > 0 ? " Proposals from this run were rejected." : "")
  );
}

const FOLLOW_PX = 80; // D-22: "at the bottom" means within about 80 px of it

// ---------------------------------------------------------------------------
// Typed error block (REL-01/02/06, 34-UI-SPEC section 2)
// ---------------------------------------------------------------------------

function ErrorBlock({
  title,
  body,
  model,
  children,
}: {
  title: string;
  body: string;
  model?: string | null;
  children?: React.ReactNode;
}) {
  return (
    <div
      role="alert"
      style={{
        background: tokens.color.tintWarm,
        border: `1px solid ${tokens.color.border2}`,
        borderLeft: `3px solid ${tokens.color.terracotta}`,
        borderRadius: 14,
        padding: 16,
      }}
    >
      <div style={{ fontSize: 16, fontWeight: 600, color: tokens.color.ink }}>{title}</div>
      <div
        style={{
          fontSize: 14,
          fontWeight: 400,
          color: tokens.color.muted3,
          marginTop: 8,
          lineHeight: 1.5,
        }}
      >
        {body}
      </div>
      {model && (
        <div style={{ fontSize: 12, color: tokens.color.muted3, marginTop: 8 }}>
          Model: {model}
        </div>
      )}
      {children && (
        <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginTop: 16 }}>
          {children}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Chat page. One client page; the open thread lives in the URL
// (/chat?thread=<uuid>) so a reload restores it (D-19). useSearchParams needs a
// Suspense boundary for the production build.
// ---------------------------------------------------------------------------

export default function ChatPage() {
  return (
    <Suspense fallback={null}>
      <ChatInner />
    </Suspense>
  );
}

function ChatInner() {
  const router = useRouter();
  const param = useSearchParams().get("thread");
  const paramRef = useRef(param);
  paramRef.current = param;

  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<Item[]>([]);
  const [asking, setAsking] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const [reconnected, setReconnected] = useState(false);
  // Open tool-step panels per message, keyed by the message's index (stable across
  // the post-answer reconcile swap of live ids for persisted ids).
  const [openSteps, setOpenSteps] = useState<Record<number, Record<string, boolean>>>({});
  const [sidebarKey, setSidebarKey] = useState(0);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const toggleRef = useRef<HTMLButtonElement | null>(null);
  const composerRef = useRef<HTMLInputElement | null>(null);
  const focusComposerRef = useRef(false);
  const bumpSidebar = () => setSidebarKey((k) => k + 1);

  const stream = useChatStream();
  const loadedRef = useRef<string | null>(null); // thread this view shows or is loading
  const loadSeqRef = useRef(0);
  const liveIdRef = useRef<string | null>(null); // assistant item of the run in view
  const askedRef = useRef(""); // question of the run in view (REL-01 restore)
  const traceRef = useRef<TraceStep[]>([]);
  const terminalRef = useRef(false);
  const threadSeenRef = useRef(false);
  const reconcilingRef = useRef(false);
  const idCounter = useRef(0);
  const scrollNextRef = useRef(false);
  const followingRef = useRef(true); // within ~80 px of the bottom (D-22)
  const announcedRef = useRef<Set<string>>(new Set());
  const [announcement, setAnnouncement] = useState("");
  const [showJump, setShowJump] = useState(false);

  // One polite, atomic region: set once per completed answer, error, Incomplete or
  // stop notice (D-21). Cleared first so identical consecutive text is re-announced.
  function announce(text: string) {
    setAnnouncement("");
    setTimeout(() => setAnnouncement(text), 0);
  }

  const nextId = (p: string) => `${p}-live-${++idCounter.current}`;

  // D-05: deltas flush at most every 50 ms (setTimeout; rAF never fires in a hidden tab).
  const tokenBuf = useTokenBuffer((text, iteration) =>
    updateLive((m) => ({ ...m, lane: laneAppend(m.lane, text, iteration) }))
  );

  // D-17: a delivered single-use token is kept for this tab only.
  function keepTokens(ps?: ServerProposal[]) {
    for (const p of ps ?? []) if (p.token) saveProposalToken(p.id, p.token);
  }

  function updateLive(fn: (m: AsstItem) => AsstItem) {
    const id = liveIdRef.current;
    setMessages((ms) => ms.map((m) => (m.kind === "assistant" && m.id === id ? fn(m) : m)));
  }

  function endRun() {
    setAsking(false);
    setReconnected(false);
  }

  function failLive(err: ChatError, proposals: ServerProposal[] = []) {
    terminalRef.current = true;
    tokenBuf.cancel(); // a draft is never shown on an error
    updateLive((m) => ({
      ...m,
      lane: { ...m.lane, draft: "", draftIteration: null },
      status: "error",
      error: err,
      proposals: proposals.map(toProposal),
      live: true,
    }));
    keepTokens(proposals);
    // REL-01: the question is never lost (a newer draft is kept).
    setQuestion((prev) => prev || askedRef.current);
  }

  // Shared by send and attach (the re-attach replay speaks the same events).
  function handleEvent(msg: Record<string, unknown>) {
    const proposals = (msg.proposals as ServerProposal[] | undefined) ?? [];
    if (msg.type === "thread" && typeof msg.thread_id === "string") {
      threadSeenRef.current = true;
      if (loadedRef.current !== msg.thread_id) bumpSidebar(); // new thread: list it
      loadedRef.current = msg.thread_id; // own thread: the URL effect skips its fetch
      if (paramRef.current !== msg.thread_id) {
        router.replace("/chat?thread=" + msg.thread_id);
      }
    } else if (
      msg.type === "token" &&
      typeof msg.delta === "string" &&
      typeof msg.iteration === "number"
    ) {
      tokenBuf.push(msg.delta, msg.iteration);
    } else if (msg.type === "tool_start" && typeof msg.tool === "string") {
      // The narration so far becomes a working note, never the answer (lane rule).
      const pending = tokenBuf.take();
      const ev = {
        call_id: typeof msg.call_id === "string" ? msg.call_id : `t${Date.now()}`,
        tool: msg.tool,
        args: (msg.args as Record<string, unknown> | undefined) ?? {},
        iteration: typeof msg.iteration === "number" ? msg.iteration : 0,
      };
      updateLive((m) => {
        const lane = pending.text
          ? laneAppend(m.lane, pending.text, pending.iteration ?? ev.iteration)
          : m.lane;
        return { ...m, lane: laneToolStart(lane, ev, Date.now()) };
      });
    } else if (msg.type === "tool_result" && msg.step) {
      traceRef.current = [...traceRef.current, msg.step as TraceStep];
      const ev = {
        call_id: typeof msg.call_id === "string" ? msg.call_id : null,
        step: msg.step as TraceStep,
        ms: typeof msg.ms === "number" ? msg.ms : null,
        sources: Array.isArray(msg.sources) ? (msg.sources as Source[]) : [],
      };
      updateLive((m) => ({ ...m, lane: laneToolResult(m.lane, ev) }));
    } else if (msg.type === "answer") {
      terminalRef.current = true;
      tokenBuf.cancel();
      const trace = Array.isArray(msg.trace) ? (msg.trace as TraceStep[]) : [];
      if (trace.length) traceRef.current = trace;
      updateLive((m) => {
        // answer.text is authoritative: it replaces the streamed draft.
        let lane: Lane = { ...m.lane, draft: "", draftIteration: null };
        if (!lane.timeline.some((e) => e.kind === "step")) {
          lane = trace.reduce((l, s) => laneToolResult(l, { step: s }), lane);
        }
        return {
          ...m,
          lane,
          status: "complete",
          text: typeof msg.text === "string" ? msg.text : "",
          model: {
            name: typeof msg.model === "string" ? msg.model : null,
            provider: typeof msg.provider === "string" ? msg.provider : null,
          },
          proposals: proposals.map(toProposal),
          live: true,
        };
      });
      keepTokens(proposals);
    } else if (msg.type === "error") {
      // Proposals created before the failure stay actionable (D-05).
      failLive(
        {
          code: typeof msg.code === "string" ? msg.code : "unknown",
          model: typeof msg.model === "string" ? msg.model : null,
          idleSeconds: typeof msg.idle_seconds === "number" ? msg.idle_seconds : null,
        },
        proposals
      );
    }
  }

  // Re-read the thread; keep the live block until the response arrives, then swap
  // the persisted messages in place (no flicker). Re-attach if a run is still going.
  async function reconcile(tid: string, tries: number, cleanEnd = false) {
    reconcilingRef.current = true;
    let r: Awaited<ReturnType<typeof fetchThread>>;
    try {
      r = await fetchThread(tid);
    } finally {
      reconcilingRef.current = false;
    }
    if (loadedRef.current !== tid) return; // the view moved on
    if (typeof r === "string") {
      // Keep what is on screen; a live block that never finished reads as a failure.
      if (!terminalRef.current) {
        // A stream that closed cleanly with no answer or error is Incomplete,
        // not a connection failure (D-03a).
        failLive(
          cleanEnd
            ? { code: "stream_ended", model: null, idleSeconds: null }
            : { code: "connection", model: null, idleSeconds: null, transport: true }
        );
      }
      endRun();
      return;
    }
    const next = mapMessages(r.messages);
    if (r.active_run && tries > 0) {
      void startAttach(tid, r.active_run.run_id, next, tries);
      return;
    }
    // Never swap a delivered answer for a history that lacks it.
    if (!(terminalRef.current && next[next.length - 1]?.kind === "user")) setMessages(next);
    endRun();
  }

  async function afterStream(out: StreamOutcome, source: "send" | "attach", tries: number) {
    if (out.kind === "stale" || out.kind === "stopped") return;
    if (out.kind === "status") {
      // Never read or show `detail` (D-02): the status alone picks the copy.
      const s = out.status;
      failLive({
        code:
          s === 409
            ? "conflict"
            : s === 401 || s === 403 || s === 503
            ? "unauthorized"
            : s === 502 || s === 504
            ? "connection"
            : "unknown",
        model: null,
        idleSeconds: null,
        // The proxy answers 502 when the backend is unreachable: a transport failure.
        transport: s === 502 || s === 504,
      });
      endRun();
      return;
    }
    // WR-06: once the thread event arrived the server owns the run, so a dropped
    // connection reconciles (and re-attaches) instead of reporting a failure.
    if (out.kind === "error" && source === "send" && !threadSeenRef.current) {
      failLive({ code: "connection", model: null, idleSeconds: null, transport: true });
      endRun();
      return;
    }
    const tid = loadedRef.current;
    if (tid && (source === "attach" || threadSeenRef.current)) {
      await reconcile(tid, tries, out.kind === "done" || out.kind === "ended");
      return;
    }
    // No thread (streams without a thread event): the live block is all there is.
    if (!terminalRef.current) {
      failLive({ code: "stream_ended", model: null, idleSeconds: null });
    }
    endRun();
  }

  async function startAttach(tid: string, runId: string, base: Item[], tries: number) {
    tokenBuf.cancel();
    const aid = nextId("a");
    liveIdRef.current = aid;
    terminalRef.current = false;
    threadSeenRef.current = true;
    traceRef.current = [];
    askedRef.current = [...base].reverse().find((m) => m.kind === "user")?.text ?? "";
    stream.runIdRef.current = runId;
    setMessages([...base, runningItem(aid)]);
    setAsking(true);
    setStopping(false);
    setReconnected(true);
    const out = await stream.attach(tid, handleEvent);
    await afterStream(out, "attach", tries - 1);
    bumpSidebar();
  }

  // `retry` (Ask again) keeps whatever is in the composer.
  async function sendQuestion(text?: string, retry = false) {
    const q = (text ?? question).trim();
    if (!q || loading || stream.busyRef.current || reconcilingRef.current) return;

    tokenBuf.cancel();
    const aid = nextId("a");
    const replaceFailed = retry && loadedRef.current === null; // unsaved pair: replace it
    liveIdRef.current = aid;
    askedRef.current = q;
    terminalRef.current = false;
    threadSeenRef.current = false;
    traceRef.current = [];
    setNotFound(false);
    setAsking(true);
    setStopping(false);
    setReconnected(false);
    if (!retry) setQuestion("");
    setMessages((ms) => {
      const base =
        replaceFailed &&
        ms[ms.length - 1]?.kind === "assistant" &&
        ms[ms.length - 2]?.kind === "user"
          ? ms.slice(0, -2)
          : ms;
      return [...base, { kind: "user", id: nextId("u"), text: q }, runningItem(aid)];
    });
    scrollNextRef.current = true;
    followingRef.current = true;
    setShowJump(false);

    const out = await stream.send(q, loadedRef.current, handleEvent);
    await afterStream(out, "send", 1);
    bumpSidebar(); // turn ended: updated_at / title moved
  }

  // Stop: the hook cancels on the server and aborts the fetch; the cancel reply
  // lists the proposals the server rejected so their cards show rejected-by-Stop.
  async function stop() {
    setStopping(true);
    const pending = tokenBuf.take(); // flushed text not yet in the draft
    const rejected = await stream.stop();
    if (rejected === null) return;

    const cards: Proposal[] = traceRef.current
      .filter(
        (s) =>
          typeof s.result?.proposal_id === "string" &&
          rejected.includes(s.result.proposal_id as string)
      )
      .map((s) => {
        const operation = s.tool.replace(/^propose_/, "");
        const hasPayload = "before" in s.result || "after" in s.result;
        return {
          id: s.result.proposal_id as string,
          token: null,
          operation,
          payload: hasPayload
            ? {
                operation,
                rows: [
                  { before: s.result.before ?? null, after: s.result.after ?? null } as DiffRow,
                ],
              }
            : null,
          expiresAt: null,
          rejectedByStop: true,
        };
      });
    // A terminal event may have landed just before Stop; Stop wins (34 section 3).
    updateLive((m) => ({
      ...m,
      lane: { ...m.lane, draft: "", draftIteration: null },
      // Live view only (D-03a): the partial is never persisted, a reload loses it.
      stoppedPartial: m.status === "running" ? m.lane.draft + pending.text : "",
      status: "cancelled",
      text: "",
      error: null,
      model: null,
      proposals: cards,
      stopRejected: rejected.length > 0,
      live: true,
    }));
    setQuestion((prev) => prev || askedRef.current);
    setStopping(false);
    endRun();
    bumpSidebar();
  }

  async function openThread(id: string) {
    const seq = ++loadSeqRef.current;
    tokenBuf.cancel();
    setOpenSteps({});
    stream.detach(); // client-side only; never cancels the run (D-06)
    loadedRef.current = id;
    endRun();
    setStopping(false);
    setLoading(true);
    setLoadError(false);
    setNotFound(false);
    setMessages([]);
    const r = await fetchThread(id);
    if (seq !== loadSeqRef.current) return;
    setLoading(false);
    if (r === NOT_FOUND) {
      loadedRef.current = null;
      setNotFound(true);
      router.replace("/chat");
      return;
    }
    if (r === "error") {
      loadedRef.current = null;
      setLoadError(true);
      return;
    }
    scrollNextRef.current = true;
    followingRef.current = true;
    setShowJump(false);
    const next = mapMessages(r.messages);
    if (r.active_run) void startAttach(id, r.active_run.run_id, next, 2);
    else setMessages(next);
  }

  // The open thread follows the URL; the page's own new thread is not refetched.
  useEffect(() => {
    if (param === loadedRef.current) return;
    if (param) {
      void openThread(param);
      return;
    }
    loadSeqRef.current++;
    tokenBuf.cancel();
    setOpenSteps({});
    stream.detach();
    loadedRef.current = null;
    endRun();
    setStopping(false);
    setLoading(false);
    setLoadError(false);
    setMessages([]);
    followingRef.current = true;
    setShowJump(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [param]);

  // Follow the bottom (D-22, D-22a). The window is the scroll container; measuring
  // measures with getBoundingClientRect. No smooth scroll, animation frames or
  // observer APIs: the automated browser pane is hidden and never fires them.
  // The true document bottom, so the last message ends above the sticky composer.
  function scrollToLatest() {
    window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "auto" });
  }

  useEffect(() => {
    const onScroll = () => {
      // Pixels left to scroll: the document's bottom edge minus the viewport's.
      const left = document.documentElement.getBoundingClientRect().bottom - window.innerHeight;
      followingRef.current = left < FOLLOW_PX;
      if (followingRef.current) setShowJump(false);
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // After a load or a send (or while following), bring the newest message into view;
  // otherwise growing content raises the Jump to latest pill.
  useEffect(() => {
    if (loading) return;
    if (scrollNextRef.current || followingRef.current) {
      scrollNextRef.current = false;
      scrollToLatest();
    } else if (messages.length > 0) {
      setShowJump(true);
    }
  }, [messages, loading]);

  // Announce each live completed answer, error, Incomplete or stop notice once; never
  // tokens, steps or working notes (D-21). The answer text is read from the rendered node.
  useEffect(() => {
    for (const m of messages) {
      if (m.kind !== "assistant" || !m.live || m.status === "running") continue;
      const key = `${m.id}:${m.status}`;
      if (announcedRef.current.has(key)) continue;
      announcedRef.current.add(key);
      let text = "";
      if (m.status === "complete") {
        const t = document.querySelector(`[data-mid="${m.id}"]`)?.textContent?.trim();
        if (t) text = `monai: ${t}`;
      } else if (m.status === "error" && m.error) {
        const c = errorCopy(m.error);
        text = `${c.title}. ${c.body}`;
      } else if (m.status === "cancelled") {
        text = stoppedLine(m);
      }
      if (text) announce(text);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages]);

  function jumpToLatest() {
    followingRef.current = true;
    setShowJump(false);
    scrollToLatest();
    composerRef.current?.focus();
  }

  // A card approved in the Inbox flips status when the tab comes back (no polling).
  useEffect(() => {
    const onVisible = () => {
      const tid = loadedRef.current;
      if (document.visibilityState !== "visible" || !tid || asking || loading) return;
      const stale = messages.some(
        (m) =>
          m.kind === "assistant" &&
          m.proposals.some((p) => p.liveStatus === "pending" && readProposalToken(p.id) === null)
      );
      if (stale) void reconcile(tid, 0);
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages, asking, loading]);

  // Mobile drawer: Escape closes it and focus returns to the toggle (36-UI-SPEC 2).
  function closeDrawer() {
    if (!drawerOpen) return;
    setDrawerOpen(false);
    toggleRef.current?.focus();
  }
  useEffect(() => {
    if (!drawerOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setDrawerOpen(false);
        toggleRef.current?.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [drawerOpen]);

  // Example click: fill the composer (never send), focus it, cursor at the end.
  useEffect(() => {
    if (!focusComposerRef.current) return;
    focusComposerRef.current = false;
    const el = composerRef.current;
    if (!el) return;
    el.focus();
    el.setSelectionRange(el.value.length, el.value.length);
  }, [question]);

  const last = messages[messages.length - 1];
  const orphan = last?.kind === "user" && !asking && !loading && !loadError;

  function askAgain(index: number) {
    const prev = messages[index - 1];
    if (prev?.kind === "user") void sendQuestion(prev.text, true);
  }

  function renderAssistant(m: AsstItem, index: number) {
    const isLast = index === messages.length - 1;
    const errCopy = m.error ? errorCopy(m.error) : null;
    const draft = m.lane.draft.trim() ? m.lane.draft : "";
    const partial = m.stoppedPartial?.trim() ? m.stoppedPartial : "";
    const answerBox: React.CSSProperties = {
      color: tokens.color.ink,
      fontSize: 16,
      lineHeight: 1.6,
      overflowWrap: "anywhere",
      marginBottom: 16,
    };
    return (
      <div key={m.id}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 16 }}>
          <span style={{ fontFamily: tokens.font.serif, fontSize: 18 }}>monai</span>
          {m.status !== "error" && (
            <span style={{ fontSize: 12, color: tokens.color.muted3 }}>
              ·{" "}
              {m.status === "cancelled"
                ? "stopped"
                : m.status === "complete"
                ? answeredLabel(m)
                : draft
                ? "answering…"
                : "thinking…"}
            </span>
          )}
          {m.status === "complete" && (
            <span
              title={m.model?.provider ?? undefined}
              style={{
                fontSize: 12,
                lineHeight: 1.5,
                color: tokens.color.muted3,
                background: tokens.color.tintNeutral,
                border: `1px solid ${tokens.color.border2}`,
                borderRadius: tokens.radius.pill,
                padding: "4px 8px",
              }}
            >
              {m.model?.name ?? "model unknown"}
            </span>
          )}
        </div>

        <ToolSteps
          timeline={m.lane.timeline}
          running={m.status === "running"}
          open={openSteps[index] ?? {}}
          onToggle={(key) =>
            setOpenSteps((o) => ({ ...o, [index]: { ...o[index], [key]: !o[index]?.[key] } }))
          }
        />

        {/* Answer lane: the streaming draft, the final text, or a dimmed Stopped
            partial. All through the safe Markdown component (D-10). */}
        {m.status === "running" && draft && (
          <div data-testid="answer" aria-busy="true" style={answerBox}>
            <Markdown>{draft}</Markdown>
          </div>
        )}
        {m.status === "complete" && m.text && (
          <div data-testid="answer" data-mid={m.id} style={answerBox}>
            <Markdown>{m.text}</Markdown>
          </div>
        )}
        {m.status === "cancelled" && partial && (
          <div
            data-testid="answer"
            style={{
              ...answerBox,
              borderLeft: `3px solid ${tokens.color.border2}`,
              paddingLeft: 16,
            }}
          >
            <Markdown dimmed>{partial}</Markdown>
          </div>
        )}

        {m.status === "error" && m.error && errCopy && (
          <div style={{ marginBottom: 16 }}>
            <ErrorBlock title={errCopy.title} body={errCopy.body} model={m.error.model}>
              {isLast && !asking && !loading && (
                <button
                  type="button"
                  style={{ ...btnDark, minHeight: 36 }}
                  onClick={() => askAgain(index)}
                >
                  Ask again
                </button>
              )}
            </ErrorBlock>
          </div>
        )}

        {/* Stopped run (REL-03, 34-UI-SPEC section 3) */}
        {m.status === "cancelled" && (
          <div
            role="status"
            style={{ fontSize: 14, color: tokens.color.muted3, lineHeight: 1.5, marginBottom: 16 }}
          >
            {stoppedLine(m)}
          </div>
        )}

        {/* Sources: only on a completed answer (D-12) */}
        {m.status === "complete" && (
          <SourceChips
            sources={dedupeSources(
              m.lane.timeline.flatMap((e) => (e.kind === "step" ? e.sources : []))
            )}
          />
        )}

        {/* Inline ProposalCards — one per proposal in this turn (D-01, AGENT-06) */}
        {m.proposals.map((p) => (
          <ProposalCard
            key={p.id}
            proposal={p}
            liveStatus={p.liveStatus}
            inCancelledMessage={m.status === "cancelled"}
            onApplied={() => {
              // /cashflow re-fetches its own list on mount; nothing local.
            }}
            onRejected={() => {
              // nothing extra needed
            }}
          />
        ))}
      </div>
    );
  }

  const skeleton = (right: boolean): React.CSSProperties => ({
    height: 44,
    width: right ? "50%" : "70%",
    alignSelf: right ? "flex-end" : "flex-start",
    borderRadius: right ? "16px 16px 4px 16px" : "16px 16px 16px 4px",
    background: right ? "rgba(35,32,27,.12)" : tokens.color.borderInner,
  });

  const streamEnded = errorCopy({ code: "stream_ended", model: null, idleSeconds: null });

  return (
    <div
      className="chat-shell"
      style={{ position: "relative", minHeight: "100%", display: "flex", flexDirection: "column" }}
    >
      <ThreadSidebar
        activeId={param}
        refreshKey={sidebarKey}
        open={drawerOpen}
        onClose={closeDrawer}
      />
      {drawerOpen && (
        <div
          className="threads-scrim"
          data-testid="threads-scrim"
          onClick={closeDrawer}
          style={{ position: "absolute", inset: 0, zIndex: 10, background: "rgba(35,32,27,.4)" }}
        />
      )}
      <div
        className="chat-column"
        style={{ marginLeft: 240, flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}
      >
        <div
          className="tab-in chat-column-inner"
          style={{
            // 760px content + 2*44px padding (the old content-box 760 max), now border-box
            maxWidth: 848,
            width: "100%",
            boxSizing: "border-box",
            margin: "0 auto",
            padding: "40px 44px 60px",
            flex: 1,
            display: "flex",
            flexDirection: "column",
          }}
        >
          <div style={{ marginBottom: 26 }}>
            <button
              ref={toggleRef}
              type="button"
              className="threads-toggle"
              data-testid="threads-toggle"
              aria-expanded={drawerOpen}
              aria-controls="chat-threads"
              onClick={() => setDrawerOpen((o) => !o)}
              style={{
                alignItems: "center",
                gap: 6,
                minHeight: 44,
                padding: "0 16px",
                marginBottom: 16,
                background: tokens.color.sidebar,
                border: `1px solid ${tokens.color.border2}`,
                borderRadius: tokens.radius.pill,
                color: tokens.color.ink,
                fontSize: 14,
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              Chats <span aria-hidden="true">{drawerOpen ? "▴" : "▾"}</span>
            </button>
            <div
              style={{
                fontSize: 12,
                letterSpacing: ".12em",
                textTransform: "uppercase",
                color: tokens.color.muted3,
                marginBottom: 6,
              }}
            >
              Assistant
            </div>
            <h1
              style={{
                fontFamily: tokens.font.serif,
                fontWeight: 400,
                fontSize: 40,
                margin: 0,
                letterSpacing: "-.5px",
              }}
            >
              Ask about your money
            </h1>
          </div>

          {/* Conversation */}
          <div style={{ flex: 1 }}>
            {notFound && (
              <div
                role="status"
                style={{
                  background: tokens.color.tintNeutral,
                  border: `1px solid ${tokens.color.border2}`,
                  borderRadius: tokens.radius.md,
                  padding: 16,
                  marginBottom: 24,
                }}
              >
                <div style={{ fontSize: 16, fontWeight: 600, color: tokens.color.ink }}>
                  {"That chat isn't available"}
                </div>
                <div style={{ fontSize: 14, color: tokens.color.muted3, marginTop: 4, lineHeight: 1.5 }}>
                  It may have been deleted. Start a new chat or pick one from the list.
                </div>
              </div>
            )}

            <div aria-live="polite" aria-atomic="true" className="sr-only" data-testid="chat-announcer">
              {announcement}
            </div>

            {reconnected && (
              <span role="status" className="sr-only">
                Reconnected to the answer in progress.
              </span>
            )}

            {!loading && !loadError && !asking && messages.length === 0 && (
              <div>
                <p style={{ fontSize: 14, color: tokens.color.muted3, margin: "0 0 12px", lineHeight: 1.5 }}>
                  Try one of these, or ask your own.
                </p>
                <div
                  role="group"
                  aria-label="Example questions"
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
                    gap: 8,
                  }}
                >
                  {EXAMPLES.map((ex) => (
                    <button
                      key={ex.caption}
                      type="button"
                      data-testid="example-question"
                      onClick={() => {
                        focusComposerRef.current = true;
                        setQuestion(ex.question);
                        // same text re-clicked: no state change, so focus directly too
                        composerRef.current?.focus();
                      }}
                      style={{
                        background: tokens.color.card,
                        border: `1px solid ${tokens.color.border2}`,
                        borderRadius: tokens.radius.md,
                        padding: 16,
                        minHeight: 44,
                        textAlign: "left",
                        cursor: "pointer",
                        fontFamily: "inherit",
                        color: tokens.color.ink,
                      }}
                    >
                      <div style={{ fontSize: 12, color: tokens.color.muted3, lineHeight: 1.5 }}>
                        {ex.caption}
                      </div>
                      <div style={{ fontSize: 14, color: tokens.color.ink, lineHeight: 1.5 }}>
                        {ex.question}
                      </div>
                      {ex.caption === "Propose a change" && (
                        <div style={{ fontSize: 12, color: tokens.color.muted3, marginTop: 4, lineHeight: 1.5 }}>
                          You approve it before anything changes.
                        </div>
                      )}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {loading && (
              <div aria-busy="true" style={{ display: "flex", flexDirection: "column", gap: 24 }}>
                <span role="status" className="sr-only">
                  Loading chat…
                </span>
                <div style={skeleton(true)} />
                <div style={skeleton(false)} />
              </div>
            )}

            {loadError && (
              <ErrorBlock
                title="Couldn't open this chat"
                body="monai couldn't load the messages. Check that the server is running, then try again."
              >
                <button
                  type="button"
                  style={{ ...btnDark, minHeight: 36 }}
                  onClick={() => param && void openThread(param)}
                >
                  Try again
                </button>
              </ErrorBlock>
            )}

            {!loading && messages.length > 0 && (
              <div
                role="log"
                aria-label="Conversation"
                aria-live="off"
                style={{ display: "flex", flexDirection: "column", gap: 24 }}
              >
                {messages.map((m, i) =>
                  m.kind === "user" ? (
                    <div key={m.id} style={{ display: "flex", justifyContent: "flex-end" }}>
                      <div
                        style={{
                          background: tokens.color.ink,
                          color: tokens.color.inkText,
                          padding: "12px 18px",
                          borderRadius: "16px 16px 4px 16px",
                          fontSize: 15,
                          maxWidth: "80%",
                          overflowWrap: "anywhere",
                        }}
                      >
                        {m.text}
                      </div>
                    </div>
                  ) : (
                    renderAssistant(m, i)
                  )
                )}
                {orphan && last?.kind === "user" && (
                  <ErrorBlock title={streamEnded.title} body={streamEnded.body}>
                    <button
                      type="button"
                      style={{ ...btnDark, minHeight: 36 }}
                      onClick={() => void sendQuestion(last.text, true)}
                    >
                      Ask again
                    </button>
                  </ErrorBlock>
                )}
              </div>
            )}
          </div>

          {/* Composer — sticky at the bottom of the scroll area */}
          <div
            style={{
              position: "sticky",
              bottom: 0,
              display: "flex",
              gap: 10,
              background: tokens.color.panel,
              paddingTop: 8,
              paddingBottom: 2,
            }}
          >
            {showJump && (
              <div
                style={{
                  position: "absolute",
                  bottom: "calc(100% + 8px)",
                  left: "50%",
                  transform: "translateX(-50%)",
                  zIndex: 10,
                }}
              >
                <button
                  type="button"
                  data-testid="jump-to-latest"
                  className="coarse-tap"
                  onClick={jumpToLatest}
                  style={{
                    background: tokens.color.card,
                    border: `1px solid ${tokens.color.border2}`,
                    borderRadius: tokens.radius.pill,
                    boxShadow: tokens.shadow.card,
                    color: tokens.color.ink,
                    fontSize: 14,
                    fontWeight: 600,
                    padding: "0 16px",
                    minHeight: 36,
                    cursor: "pointer",
                    whiteSpace: "nowrap",
                  }}
                >
                  Jump to latest <span aria-hidden="true">↓</span>
                </button>
              </div>
            )}
            <label htmlFor="chat-composer" className="sr-only">
              Ask monai a question
            </label>
            <input
              id="chat-composer"
              ref={composerRef}
              style={{ ...input, borderRadius: 14, padding: "14px 18px", fontSize: 15 }}
              value={question}
              placeholder="Ask anything about your finances…"
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                if (
                  e.key !== "Enter" ||
                  e.shiftKey ||
                  e.nativeEvent.isComposing ||
                  e.keyCode === 229
                )
                  return;
                e.preventDefault();
                // swallowed while running or while a thread is loading
                if (asking || loading || stream.busyRef.current) return;
                void sendQuestion();
              }}
            />
            <button
              type="button"
              style={{
                background: asking ? tokens.color.sidebar : tokens.color.ink,
                color: asking ? tokens.color.ink : tokens.color.inkText,
                border: asking ? `1px solid ${tokens.color.border2}` : "none",
                borderRadius: 14,
                padding: "0 24px",
                fontSize: 15,
                fontWeight: 600,
                cursor: stopping || (loading && !asking) ? "not-allowed" : "pointer",
                opacity: stopping || (loading && !asking) ? 0.5 : 1,
              }}
              onClick={asking ? stop : () => void sendQuestion()}
              disabled={stopping || (loading && !asking)}
            >
              {stopping ? (
                "Stopping…"
              ) : asking ? (
                <>
                  <span aria-hidden="true">■</span> Stop
                </>
              ) : (
                "Ask"
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
