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
import ThreadSidebar from "./ThreadSidebar";
import { useChatStream } from "./useChatStream";
import type { StreamOutcome } from "./useChatStream";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type TraceStep = {
  tool: string;
  args: Record<string, unknown>;
  result: Record<string, unknown>;
};

// Rehydrated steps carry no result (D-11: results are never stored).
type TraceView = {
  tool: string;
  args: Record<string, unknown>;
  result?: Record<string, unknown>;
};

type UserItem = { kind: "user"; id: string; text: string };

type AsstItem = {
  kind: "assistant";
  id: string;
  status: "running" | "complete" | "error" | "cancelled";
  text: string;
  steps: string[]; // live step lines while running
  trace: TraceView[];
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
    steps?: { tool: string; args?: Record<string, unknown> }[];
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
        steps: [],
        trace: (parts.steps ?? []).map((s) => ({ tool: s.tool, args: s.args ?? {} })),
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
    steps: [],
    trace: [],
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
  const [openTraces, setOpenTraces] = useState<Record<string, boolean>>({});
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
  const endRef = useRef<HTMLDivElement | null>(null);

  const nextId = (p: string) => `${p}-live-${++idCounter.current}`;

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
    updateLive((m) => ({
      ...m,
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
    } else if (msg.type === "step" && typeof msg.msg === "string") {
      const line = msg.msg;
      updateLive((m) => ({ ...m, steps: [...m.steps, line] }));
    } else if (msg.type === "tool_result" && msg.step) {
      traceRef.current = [...traceRef.current, msg.step as TraceStep];
      const t = traceRef.current;
      updateLive((m) => ({ ...m, trace: t }));
    } else if (msg.type === "answer") {
      terminalRef.current = true;
      if (Array.isArray(msg.trace)) traceRef.current = msg.trace as TraceStep[];
      const t = traceRef.current;
      updateLive((m) => ({
        ...m,
        status: "complete",
        text: typeof msg.text === "string" ? msg.text : "",
        trace: t.length ? t : m.trace,
        model: {
          name: typeof msg.model === "string" ? msg.model : null,
          provider: typeof msg.provider === "string" ? msg.provider : null,
        },
        proposals: proposals.map(toProposal),
        live: true,
      }));
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
  async function reconcile(tid: string, tries: number) {
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
        failLive({ code: "connection", model: null, idleSeconds: null, transport: true });
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
      await reconcile(tid, tries);
      return;
    }
    // No thread (streams without a thread event): the live block is all there is.
    if (!terminalRef.current) {
      failLive({ code: "stream_ended", model: null, idleSeconds: null });
    }
    endRun();
  }

  async function startAttach(tid: string, runId: string, base: Item[], tries: number) {
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

    const out = await stream.send(q, loadedRef.current, handleEvent);
    await afterStream(out, "send", 1);
    bumpSidebar(); // turn ended: updated_at / title moved
  }

  // Stop: the hook cancels on the server and aborts the fetch; the cancel reply
  // lists the proposals the server rejected so their cards show rejected-by-Stop.
  async function stop() {
    setStopping(true);
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
    stream.detach();
    loadedRef.current = null;
    endRun();
    setStopping(false);
    setLoading(false);
    setLoadError(false);
    setMessages([]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [param]);

  // After a load or a send, bring the newest message into view (no smooth scroll:
  // rAF never fires in the automated browser pane).
  useEffect(() => {
    if (!scrollNextRef.current || loading) return;
    scrollNextRef.current = false;
    endRef.current?.scrollIntoView?.({ behavior: "auto", block: "end" });
  }, [messages, loading]);

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
    const open = !!openTraces[m.id];
    return (
      <div key={m.id}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
          <span style={{ fontFamily: tokens.font.serif, fontSize: 18 }}>monai</span>
          {m.status !== "error" && (
            <span style={{ fontSize: 12, color: tokens.color.muted3 }}>
              ·{" "}
              {m.status === "cancelled"
                ? "stopped"
                : m.status === "complete"
                ? answeredLabel(m)
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

        {/* Progressive step indicator while streaming (D-08) */}
        {m.steps.length > 0 && m.status !== "complete" && (
          <div style={{ marginBottom: 6 }}>
            {m.steps.map((s, i) => (
              <div
                key={i}
                style={{
                  fontSize: 13,
                  color: tokens.color.muted,
                  padding: "2px 0",
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                }}
              >
                <span style={{ color: tokens.color.green }}>›</span>
                {s}
              </div>
            ))}
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
            style={{ fontSize: 14, color: tokens.color.muted3, lineHeight: 1.5, marginBottom: 14 }}
          >
            Stopped. No answer was kept.
            {m.stopRejected || m.proposals.length > 0
              ? " Proposals from this run were rejected."
              : ""}
          </div>
        )}

        {/* Answer (D-07): React text only, never injected HTML */}
        {m.status === "complete" && m.text && (
          <div
            style={{
              fontSize: 16,
              lineHeight: 1.6,
              margin: "0 0 14px",
              color: tokens.color.textSoft,
              whiteSpace: "pre-wrap",
            }}
          >
            {m.text}
          </div>
        )}

        {/* Collapsible tool-call trace (D-07) */}
        {m.trace.length > 0 && (
          <>
            <button
              onClick={() => setOpenTraces((o) => ({ ...o, [m.id]: !o[m.id] }))}
              style={{
                background: "none",
                border: "none",
                color: tokens.color.muted,
                cursor: "pointer",
                fontSize: 13,
                padding: 0,
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
              }}
            >
              {open ? "▴" : "▾"} how I got this ({m.trace.length} step
              {m.trace.length !== 1 ? "s" : ""})
            </button>
            {open && (
              <div
                style={{
                  marginTop: 10,
                  borderLeft: `2px solid ${tokens.color.border2}`,
                  paddingLeft: 14,
                  display: "flex",
                  flexDirection: "column",
                  gap: 8,
                }}
              >
                {m.trace.map((step, i) => (
                  <div
                    key={i}
                    style={{
                      fontSize: 12,
                      color: tokens.color.muted,
                      fontFamily: "ui-monospace, monospace",
                    }}
                  >
                    <span style={{ color: tokens.color.green, fontWeight: 600 }}>{step.tool}</span>
                    (
                    {Object.entries(step.args ?? {})
                      .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
                      .join(", ")}
                    )
                    {step.result && (
                      <>
                        {" "}
                        <span style={{ color: tokens.color.inkTextMuted }}>→</span>{" "}
                        {JSON.stringify(step.result).slice(0, 120)}
                      </>
                    )}
                  </div>
                ))}
              </div>
            )}
          </>
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
                color: tokens.color.muted2,
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
              <div role="presentation" style={{ display: "flex", flexDirection: "column", gap: 24 }}>
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
            <div ref={endRef} />
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
            <input
              ref={composerRef}
              style={{ ...input, borderRadius: 14, padding: "14px 18px", fontSize: 15 }}
              value={question}
              placeholder="Ask anything about your finances…"
              onChange={(e) => setQuestion(e.target.value)}
              aria-label="Ask monai a question"
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
