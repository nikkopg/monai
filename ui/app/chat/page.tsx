"use client";

import { Fragment, Suspense, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { tokens, input, btnDark, btnGhost } from "../styles";
import ConfirmDialog from "../cashflow/ConfirmDialog";
import type { DiffRow } from "../components/ProposalDiff";
import { hhmm } from "../lib/inbox";
import { errorCopy } from "./errors";
import type { ChatError } from "./errors";
import MessageActions from "./MessageActions";
import PlanBar from "./PlanBar";
import ProposalCard, {
  clearProposalToken,
  readProposalToken,
  saveProposalToken,
  toProposal,
} from "./ProposalCard";
import type { LiveStatus, Proposal, ServerProposal } from "./ProposalCard";
import Markdown from "./Markdown";
import { AttachPanel, AttachToggle, useAttachments } from "./AttachControl";
import { AttachmentTray, MessageAttachments } from "./AttachmentChip";
import UploadCard from "./UploadCard";
import { cardSentence, placeholderFor, type AttachChip } from "./attachLabels";
import { tooltipStyle } from "./MessageActions";
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

type UserItem = { kind: "user"; id: string; text: string; seq?: number; attachments?: AttachChip[] };

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
  seq?: number; // persisted position; live items have none and sit after any boundary
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

type ServerAttachment = {
  id: string;
  filename: string;
  kind: string;
  status: string;
  summary: string;
  row_count: number;
  message_id: string | null;
  purged_at: string | null;
};

type ThreadDetail = {
  id: string;
  active_run: { run_id: string } | null;
  messages: PersistedMessage[];
  summary_upto_seq?: number;
  has_summary?: boolean;
  attachments?: ServerAttachment[];
};

type Boundary = { upto: number; summarized: boolean };

// Where the model's context starts (D-24); null when nothing is summarized or cleared.
function boundaryOf(r: ThreadDetail): Boundary | null {
  return r.summary_upto_seq ? { upto: r.summary_upto_seq, summarized: !!r.has_summary } : null;
}

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

// A stored attachment as a read-only pill; the server status is ok | llm_read | refused.
const toChip = (a: ServerAttachment): AttachChip => ({
  localId: a.id,
  attachmentId: a.id,
  filename: a.filename,
  kind: a.kind,
  state: a.status === "ok" || a.status === "llm_read" ? a.status : "refused",
  summary: a.summary,
  rowCount: a.row_count,
  purgedAt: a.purged_at,
  messageId: a.message_id,
});

function mapMessages(list: PersistedMessage[], atts: ServerAttachment[] = []): Item[] {
  return [...list]
    .sort((a, b) => a.seq - b.seq)
    .map((m): Item => {
      if (m.role !== "assistant") {
        const attachments = atts.filter((a) => a.message_id === m.id).map(toChip);
        return { kind: "user", id: m.id, text: m.content, seq: m.seq, ...(attachments.length ? { attachments } : {}) };
      }
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
        seq: m.seq,
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

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const isUuid = (id: string) => UUID_RE.test(id);

type SendOpts = { retry?: boolean; replaceFrom?: string; mode?: "regenerate" | "edit" };

const WAIT_REASON = "Wait for the current answer to finish, or stop it first.";
const SLASH_REASON = "Wait for this chat to finish compacting or clearing.";
const APPLIED_REASON = "Can't redo this: a change made from here on was already applied.";

// Inline editor in place of a user bubble (D-20). Mounts focused, caret at the end.
function EditBox({
  text,
  busy,
  error,
  onChange,
  onSubmit,
  onCancel,
}: {
  text: string;
  busy: boolean;
  error: string | null;
  onChange: (t: string) => void;
  onSubmit: () => void;
  onCancel: () => void;
}) {
  const ref = useRef<HTMLTextAreaElement | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.focus();
    el.setSelectionRange(el.value.length, el.value.length);
  }, []);
  return (
    <div style={{ width: "80%", display: "flex", flexDirection: "column", gap: 8 }}>
      <label htmlFor="chat-edit-box" className="sr-only">
        Edit your question
      </label>
      <textarea
        id="chat-edit-box"
        ref={ref}
        value={text}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            e.preventDefault();
            onCancel();
            return;
          }
          if (e.key !== "Enter" || e.shiftKey || e.nativeEvent.isComposing || e.keyCode === 229)
            return;
          e.preventDefault();
          onSubmit();
        }}
        style={{
          background: tokens.color.inputBg,
          border: `1px solid ${tokens.color.border2}`,
          borderRadius: tokens.radius.md,
          color: tokens.color.ink,
          fontSize: 16,
          fontFamily: "inherit",
          padding: "12px 16px",
          minHeight: 80,
          width: "100%",
          boxSizing: "border-box",
          resize: "vertical",
        }}
      />
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
        <button
          type="button"
          style={{ ...btnDark, minHeight: 36, opacity: !text.trim() || busy ? 0.5 : 1 }}
          disabled={!text.trim() || busy}
          onClick={onSubmit}
        >
          Resend question
        </button>
        <button type="button" style={{ ...btnGhost, minHeight: 36 }} onClick={onCancel}>
          Discard edit
        </button>
      </div>
      {error && (
        <div role="alert" style={{ fontSize: 12, color: tokens.color.terracottaText }}>
          {error}
        </div>
      )}
    </div>
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
  // Context boundary + /compact, /clear state (38 D-23..D-26).
  const [boundary, setBoundary] = useState<Boundary | null>(null);
  const [slash, setSlash] = useState<"compacting" | "clearing" | null>(null);
  const [note, setNote] = useState<{ text: string; error: boolean } | null>(null);
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
  // Attachments (39): the page owns the panel, the thread id for uploads and focus.
  const att = useAttachments(announce);
  const [attachOpen, setAttachOpen] = useState(false);
  const newThreadRef = useRef<string | null>(null); // client id for a first upload (D-03)
  useEffect(() => {
    if (att.pendingPassword) setAttachOpen(true);
  }, [att.pendingPassword]);

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
  // Regenerate / edit (37-08). One editor at a time; refusals show inline.
  // Approve all in flight / last failure, scoped to one assistant message (38 D-17).
  const [bulk, setBulk] = useState<{
    msgId: string;
    running: boolean;
    failed: { id: string; text: string } | null;
  } | null>(null);
  // Cards with their own confirm/reject in flight: the plan bar hides meanwhile (D-17).
  const [busyCards, setBusyCards] = useState<Set<string>>(() => new Set());
  const [editing, setEditing] = useState<{ id: string; text: string } | null>(null);
  const [confirmEdit, setConfirmEdit] = useState<{ n: number; text: string } | null>(null);
  const [actionError, setActionError] = useState<{
    userId: string;
    mode: "regenerate" | "edit";
    text: string;
  } | null>(null);
  const liveUserIdRef = useRef<string | null>(null); // live user item of the run in view
  const editPendingRef = useRef(false); // edit sent, first event not yet seen
  const editBtnRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const refocusEditRef = useRef<string | null>(null);

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
    for (const p of ps ?? []) if (p.token && p.channel !== "upload") saveProposalToken(p.id, p.token);
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
      // The live user item gets its persisted id, so Ask again / Edit work even if
      // the reconcile fetch later fails.
      const from = liveUserIdRef.current;
      const to = msg.user_message_id;
      if (from && typeof to === "string") {
        liveUserIdRef.current = null;
        setMessages((ms) => ms.map((m) => (m.kind === "user" && m.id === from ? { ...m, id: to } : m)));
      }
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
    const next = mapMessages(r.messages, r.attachments);
    setBoundary(boundaryOf(r));
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
    liveUserIdRef.current = null;
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

  // A refused or failed replace (409 / 422 / other / no connection): restore the
  // view and show an inline error. The copy is chosen without reading the response
  // detail (34 D-02); a 409 re-reads the thread to tell "applied" from "running".
  async function refuseReplace(
    status: number | null,
    snapshot: Item[],
    userId: string,
    mode: "regenerate" | "edit"
  ) {
    const tid = loadedRef.current;
    let text = "Couldn't redo this. Try again.";
    let restore = snapshot;
    if (status === 409 && tid) {
      const r = await fetchThread(tid);
      if (typeof r !== "string") {
        const fresh = mapMessages(r.messages, r.attachments);
        setBoundary(boundaryOf(r));
        const at = fresh.findIndex((m) => m.id === userId);
        if (
          at >= 0 &&
          fresh.slice(at).some(
            (m) => m.kind === "assistant" && m.proposals.some((p) => p.liveStatus === "confirmed")
          )
        ) {
          text = "This answer's changes were already applied, so it can't be redone.";
          restore = fresh;
        } else {
          text = "This chat is still answering. Wait for it to finish.";
        }
      }
    }
    // Dropped connection or 5xx: the server may already have replaced the branch and
    // started a run, so the pre-replace snapshot can be stale. Trust the server.
    if ((status === null || status >= 500) && tid) {
      const r = await fetchThread(tid);
      if (typeof r !== "string") {
        restore = mapMessages(r.messages, r.attachments);
        setBoundary(boundaryOf(r));
        if (loadedRef.current === tid && r.active_run) {
          editPendingRef.current = false;
          setEditing(null);
          void startAttach(tid, r.active_run.run_id, restore, 2);
          return;
        }
      }
    }
    if (loadedRef.current !== tid) return; // the view moved on
    editPendingRef.current = false;
    setMessages(restore);
    setActionError({ userId, mode, text });
    endRun();
  }

  // `retry` (Ask again) keeps whatever is in the composer. `replaceFrom` (D-18) asks
  // the server to truncate the thread at that user message and run the question
  // again: regenerate truncates the view at once, edit when the server accepts.
  // /compact and /clear (D-26): exact trimmed match only, never a chat turn.
  async function runSlash(cmd: "/compact" | "/clear") {
    if (asking || loading || stream.busyRef.current || reconcilingRef.current || slash !== null) return;
    const tid = loadedRef.current;
    const verb = cmd.slice(1);
    if (!tid) {
      setNote({ text: `Nothing to ${verb} yet.`, error: false });
      return;
    }
    const generic = `Couldn't ${verb} this chat right now. Try again later.`;
    setSlash(cmd === "/compact" ? "compacting" : "clearing");
    setNote(null);
    try {
      const res = await fetch(`/api/threads/${tid}/${verb}`, { method: "POST" });
      if (res.ok) {
        setQuestion("");
        const r = await fetchThread(tid);
        if (typeof r !== "string" && loadedRef.current === tid) {
          setMessages(mapMessages(r.messages, r.attachments));
          setBoundary(boundaryOf(r));
        }
      } else {
        const d = await res.json().catch(() => ({}));
        setNote({
          text:
            res.status === 409
              ? "Wait for the current answer to finish, then try again."
              : res.status === 404
                ? "This chat no longer exists."
                : typeof d?.detail === "string" && d.detail
                  ? d.detail
                  : generic,
          error: true,
        });
      }
    } catch {
      setNote({ text: generic, error: true });
    } finally {
      setSlash(null);
    }
  }

  // A chat with no thread yet uploads into a client-made id; the returned thread is
  // adopted like the one a first /query-stream announces (URL replace, no refetch).
  async function submitAttach(file: File, accountId: number, password: string) {
    const tid = loadedRef.current ?? (newThreadRef.current ??= crypto.randomUUID());
    const res = await att.submit(tid, file, accountId, password);
    if (res.outcome === "done" && loadedRef.current === null) {
      newThreadRef.current = null;
      loadedRef.current = res.threadId;
      bumpSidebar();
      router.replace("/chat?thread=" + res.threadId);
    }
    return res;
  }

  function removeChip(localId: string) {
    const c = att.chips.find((x) => x.localId === localId);
    att.remove(localId);
    composerRef.current?.focus();
    if (c?.attachmentId) {
      const text = `Removed ${c.filename} from your question. It stays stored with this chat for 7 days.`;
      setNote({ text, error: false });
      setTimeout(() => setNote((n) => (n?.text === text ? null : n)), 5000);
    }
  }

  async function sendQuestion(text?: string, opts: SendOpts = {}) {
    const { retry = false, replaceFrom, mode = "regenerate" } = opts;
    if (text === undefined && !replaceFrom && !retry) {
      const cmd = question.trim();
      if (cmd === "/compact" || cmd === "/clear") {
        void runSlash(cmd);
        return;
      }
      if (att.anyUploading) return; // Ask is aria-disabled with the same reason
    }
    const q = (text ?? question).trim();
    // A turn during /compact or /clear would be clobbered by its refetch (WR-05).
    if (!q || loading || slash !== null || stream.busyRef.current || reconcilingRef.current) return;
    const target = replaceFrom
      ? messages.findIndex((m) => m.kind === "user" && m.id === replaceFrom)
      : -1;
    if (replaceFrom && (target < 0 || !loadedRef.current)) return;
    const replacing = replaceFrom !== undefined;
    // Only a fresh question carries chips; Ask again resends text (already bound server-side).
    const sent = retry || replacing ? { ids: [], sent: [] } : att.clearSent();

    tokenBuf.cancel();
    const aid = nextId("a");
    const uid = nextId("u");
    const replaceFailed = retry && !replacing && loadedRef.current === null; // unsaved pair
    const snapshot = messages;
    const before = replacing ? messages.slice(0, target) : [];
    const removedProposals = replacing
      ? messages.slice(target).flatMap((m) => (m.kind === "assistant" ? m.proposals.map((p) => p.id) : []))
      : [];
    liveIdRef.current = aid;
    liveUserIdRef.current = uid;
    askedRef.current = q;
    terminalRef.current = false;
    threadSeenRef.current = false;
    traceRef.current = [];
    setNotFound(false);
    setActionError(null);
    setAsking(true);
    setStopping(false);
    setReconnected(false);
    if (!retry && !replacing) setQuestion("");

    const truncate = () => {
      setOpenSteps((o) => Object.fromEntries(Object.entries(o).filter(([k]) => Number(k) < target)));
      setMessages([...before, { kind: "user", id: uid, text: q }, runningItem(aid)]);
      scrollNextRef.current = true;
      followingRef.current = true;
      setShowJump(false);
    };
    if (replacing) {
      if (mode === "regenerate") truncate();
      else editPendingRef.current = true;
    } else {
      setMessages((ms) => {
        const base =
          replaceFailed &&
          ms[ms.length - 1]?.kind === "assistant" &&
          ms[ms.length - 2]?.kind === "user"
            ? ms.slice(0, -2)
            : ms;
        return [
          ...base,
          { kind: "user", id: uid, text: q, ...(sent.sent.length ? { attachments: sent.sent } : {}) },
          runningItem(aid),
        ];
      });
      scrollNextRef.current = true;
      followingRef.current = true;
      setShowJump(false);
    }

    // The first event proves the server took the replace: supersede is done, so the
    // removed proposals' single-use tokens are cleared (D-20, 36 D-17).
    let accepted = !replacing;
    const onEvent = (m: Record<string, unknown>) => {
      if (!accepted) {
        accepted = true;
        editPendingRef.current = false;
        if (mode === "edit") truncate();
        removedProposals.forEach(clearProposalToken);
        setEditing(null);
        composerRef.current?.focus();
      }
      handleEvent(m);
    };

    const out = await stream.send(q, loadedRef.current, onEvent, replaceFrom, sent.ids);
    if (replacing && !accepted && (out.kind === "status" || out.kind === "error")) {
      await refuseReplace(out.kind === "status" ? out.status : null, snapshot, replaceFrom, mode);
      return;
    }
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
    if (editPendingRef.current) {
      // An edit the server never confirmed: nothing local to mark Stopped; re-read.
      editPendingRef.current = false;
      setStopping(false);
      endRun();
      const tid = loadedRef.current;
      if (tid) void reconcile(tid, 0);
      return;
    }

    const cards: Proposal[] = traceRef.current
      .filter(
        (s) =>
          s.tool !== "propose_statement_rows" && // an Inbox upload card has no Stop copy
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
    att.clear();
    setAttachOpen(false);
    loadedRef.current = id;
    endRun();
    setStopping(false);
    setLoading(true);
    setLoadError(false);
    setNotFound(false);
    setMessages([]);
    setBoundary(null);
    setNote(null);
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
    const next = mapMessages(r.messages, r.attachments);
    setBoundary(boundaryOf(r));
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
    att.clear();
    setAttachOpen(false);
    newThreadRef.current = null;
    loadedRef.current = null;
    endRun();
    setStopping(false);
    setLoading(false);
    setLoadError(false);
    setMessages([]);
    setBoundary(null);
    setNote(null);
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
        const cards = m.proposals.flatMap((p) => {
          const a = p.channel === "upload" ? p.payload?.attachment : undefined;
          const c = a && cardSentence(a.row_count, a.flagged_count, undefined);
          return c ? [c.lead + c.tail] : [];
        });
        if (cards.length) text = [text, ...cards].join(" ");
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

  const waitUpload = att.anyUploading && !asking; // Ask is aria-disabled, not disabled (37)
  const last = messages[messages.length - 1];
  const orphan = last?.kind === "user" && !asking && !loading && !loadError;
  // The divider goes after the last persisted message at or before the boundary (D-24).
  const dividerAt = boundary
    ? messages.reduce((at, m, i) => (m.seq !== undefined && m.seq <= boundary.upto ? i : at), -1)
    : -1;
  const dividerText = boundary?.summarized
    ? "Earlier messages summarized"
    : "Context cleared — earlier messages are not sent to the model";

  // Ask again is the same regenerate through replace_from whenever the question is
  // saved (D-18); an unsaved, thread-less pair is replaced locally instead.
  function retryUser(u: Item | undefined) {
    if (u?.kind !== "user") return;
    if (loadedRef.current && isUuid(u.id)) {
      void sendQuestion(u.text, { replaceFrom: u.id, mode: "regenerate", retry: true });
    } else {
      void sendQuestion(u.text, { retry: true });
    }
  }
  function askAgain(index: number) {
    retryUser(messages[index - 1]);
  }

  // Why Regenerate / Edit at user index `u` is unavailable (null = available).
  function redoDisabled(u: number): string | null {
    if (asking || loading) return WAIT_REASON;
    if (slash !== null) return SLASH_REASON;
    if (
      messages
        .slice(u)
        .some((m) => m.kind === "assistant" && m.proposals.some((p) => p.liveStatus === "confirmed"))
    )
      return APPLIED_REASON;
    if (!isUuid(messages[u].id)) return "Saving this chat…";
    return null;
  }

  function startEdit(m: UserItem) {
    setActionError(null);
    setEditing({ id: m.id, text: m.text });
  }
  function closeEdit() {
    if (editing) refocusEditRef.current = editing.id;
    setEditing(null);
    setConfirmEdit(null);
  }
  useEffect(() => {
    if (editing === null && refocusEditRef.current) {
      editBtnRefs.current[refocusEditRef.current]?.focus();
      refocusEditRef.current = null;
    }
  }, [editing]);

  // N = messages after the edited question other than its own answer (D-20).
  function submitEdit() {
    if (!editing || asking) return;
    const text = editing.text.trim();
    const u = messages.findIndex((m) => m.kind === "user" && m.id === editing.id);
    if (!text || u < 0) return;
    const n = messages.length - u - 1 - (messages[u + 1]?.kind === "assistant" ? 1 : 0);
    if (n > 0) setConfirmEdit({ n, text });
    else void sendQuestion(text, { replaceFrom: editing.id, mode: "edit" });
  }

  // /cashflow re-fetches its own list on mount. Mark the proposal applied here so
  // Regenerate / Edit lock for this point at once (D-19). Card and plan bar share it;
  // a card's own reject lands here too, so Approve all hides (D-17).
  function markStatus(msgId: string, pid: string, status: LiveStatus) {
    setMessages((ms) =>
      ms.map((x) =>
        x.kind === "assistant" && x.id === msgId
          ? {
              ...x,
              proposals: x.proposals.map((q) =>
                q.id === pid ? { ...q, liveStatus: status } : q
              ),
            }
          : x
      )
    );
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
    const prevUser = messages[index - 1]?.kind === "user" ? (messages[index - 1] as UserItem) : null;
    const lastAsst = messages.map((x) => x.kind).lastIndexOf("assistant") === index;
    const redoReason = prevUser ? redoDisabled(index - 1) : null;
    // Upload proposals are Inbox-only: never in PlanBar, Approve all or a token card (D-22).
    const uploads = m.proposals.filter((p) => p.channel === "upload");
    const chatPs = m.proposals.filter((p) => p.channel !== "upload");
    return (
      <div key={m.id} className="chat-msg">
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
              {isLast && !asking && !loading && !slash && (
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

        {/* Actions: Copy on a completed answer, Regenerate on the last (UI-SPEC section 5) */}
        <MessageActions
          copyText={m.status === "complete" ? m.text : undefined}
          onRegenerate={
            lastAsst && prevUser && (m.status === "complete" || m.status === "cancelled")
              ? () =>
                  void sendQuestion(prevUser.text, {
                    replaceFrom: prevUser.id,
                    mode: "regenerate",
                    retry: true,
                  })
              : undefined
          }
          alwaysVisible={lastAsst}
          onAnnounce={announce}
          disabledReason={redoReason}
          error={
            prevUser && actionError?.mode === "regenerate" && actionError.userId === prevUser.id
              ? actionError.text
              : null
          }
        />

        {/* Inline ProposalCards — one per proposal in this turn (D-01, AGENT-06) */}
        {chatPs.length >= 2 && (
          <PlanBar
            proposals={chatPs}
            locked={chatPs.some((p) => busyCards.has(p.id))}
            onApplied={(id) => markStatus(m.id, id, "confirmed")}
            onFailed={(id, text) => setBulk({ msgId: m.id, running: false, failed: { id, text } })}
            onRunning={(r) =>
              setBulk((b) => ({
                msgId: m.id,
                running: r,
                failed: r ? null : b?.msgId === m.id ? b.failed : null,
              }))
            }
          />
        )}
        {chatPs.map((p, i) => (
          <ProposalCard
            key={p.id}
            proposal={p}
            liveStatus={p.liveStatus}
            inCancelledMessage={m.status === "cancelled"}
            locked={bulk?.msgId === m.id && bulk.running}
            externalError={bulk?.msgId === m.id && bulk.failed?.id === p.id ? bulk.failed.text : null}
            step={chatPs.length >= 2 ? i + 1 : undefined}
            onApplied={() => markStatus(m.id, p.id, "confirmed")}
            onRejected={() => markStatus(m.id, p.id, "rejected")}
            onBusy={(b) =>
              setBusyCards((s) => {
                const next = new Set(s);
                if (b) next.add(p.id);
                else next.delete(p.id);
                return next;
              })
            }
          />
        ))}
        {uploads.map((p) => (
          <UploadCard key={p.id} proposal={p} status={p.liveStatus} />
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
                {messages.map((m, i) => (
                  <Fragment key={m.id}>
                  {m.kind === "user" ? (
                    <div
                      key={m.id}
                      className="chat-msg"
                      style={{ display: "flex", flexDirection: "column", alignItems: "flex-end" }}
                    >
                      {editing?.id === m.id ? (
                        <EditBox
                          text={editing.text}
                          busy={asking}
                          error={
                            actionError?.mode === "edit" && actionError.userId === m.id
                              ? actionError.text
                              : null
                          }
                          onChange={(t) => setEditing({ id: m.id, text: t })}
                          onSubmit={submitEdit}
                          onCancel={closeEdit}
                        />
                      ) : (
                        <>
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
                          <MessageAttachments items={m.attachments ?? []} />
                          <MessageActions
                            questionText={m.text}
                            onEdit={() => startEdit(m)}
                            disabledReason={redoDisabled(i)}
                            editRef={(el) => {
                              editBtnRefs.current[m.id] = el;
                            }}
                          />
                        </>
                      )}
                    </div>
                  ) : (
                    renderAssistant(m, i)
                  )}
                  {i === dividerAt && boundary && (
                    <div
                      role="separator"
                      aria-label={dividerText}
                      data-testid="context-divider"
                      style={{ display: "flex", alignItems: "center", gap: 12 }}
                    >
                      <span style={{ flex: 1, height: 1, background: tokens.color.border2 }} />
                      <span style={{ fontSize: 12, color: tokens.color.muted3 }}>{dividerText}</span>
                      <span style={{ flex: 1, height: 1, background: tokens.color.border2 }} />
                    </div>
                  )}
                  </Fragment>
                ))}
                {orphan && last?.kind === "user" && (
                  <ErrorBlock title={streamEnded.title} body={streamEnded.body}>
                    <button
                      type="button"
                      style={{ ...btnDark, minHeight: 36 }}
                      onClick={() => retryUser(last)}
                    >
                      Ask again
                    </button>
                  </ErrorBlock>
                )}
                {orphan && last?.kind === "user" && actionError?.userId === last.id && (
                  <div role="alert" style={{ fontSize: 12, color: tokens.color.terracottaText }}>
                    {actionError.text}
                  </div>
                )}
              </div>
            )}
          </div>

          {confirmEdit && (
            <ConfirmDialog
              message={`Edit and resend? The ${confirmEdit.n} later ${
                confirmEdit.n === 1 ? "message" : "messages"
              } in this chat will be removed, and any pending proposals from ${
                confirmEdit.n === 1 ? "it" : "them"
              } will be cancelled.`}
              confirmLabel="Remove and resend"
              cancelLabel="Keep chat"
              onCancel={() => setConfirmEdit(null)}
              onConfirm={() => {
                const c = confirmEdit;
                setConfirmEdit(null);
                if (editing) void sendQuestion(c.text, { replaceFrom: editing.id, mode: "edit" });
              }}
            />
          )}

          {/* Composer — sticky at the bottom of the scroll area */}
          <div
            style={{
              position: "sticky",
              bottom: 0,
              display: "flex",
              flexDirection: "column",
              gap: 8,
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
            {(slash || note) && (
              <div
                role="status"
                data-testid="composer-note"
                style={{
                  position: "absolute",
                  bottom: "calc(100% + 4px)",
                  left: 0,
                  fontSize: 13,
                  color: !slash && note?.error ? tokens.color.terracottaText : tokens.color.muted3,
                }}
              >
                {slash ? (slash === "compacting" ? "Compacting…" : "Clearing…") : note?.text}
              </div>
            )}
            <AttachmentTray chips={att.chips} onRemove={removeChip} />
            <AttachPanel
              open={attachOpen}
              onClose={(sentOk) => {
                setAttachOpen(false);
                if (sentOk) composerRef.current?.focus();
              }}
              onSubmit={submitAttach}
              pendingPassword={att.pendingPassword}
            />
            <div style={{ display: "flex", gap: 10 }}>
            <AttachToggle
              expanded={attachOpen}
              onToggle={() => setAttachOpen((o) => !o)}
              disabledReason={
                asking
                  ? WAIT_REASON
                  : loading
                  ? "Wait for the chat to finish loading."
                  : slash !== null
                  ? "Wait for the command to finish."
                  : null
              }
            />
            <label htmlFor="chat-composer" className="sr-only">
              Ask monai a question
            </label>
            <input
              id="chat-composer"
              ref={composerRef}
              style={{ ...input, borderRadius: 14, padding: "14px 18px", fontSize: 15 }}
              value={question}
              disabled={slash !== null}
              placeholder={placeholderFor(att.chips.length) ?? "Ask anything about your finances…"}
              onChange={(e) => {
                setQuestion(e.target.value);
                setNote(null);
              }}
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
            <span className="action-wrap" style={{ position: "relative", display: "flex" }}>
            <button
              type="button"
              {...(waitUpload ? { "aria-disabled": true as const, "aria-describedby": "ask-wait" } : {})}
              style={{
                background: asking ? tokens.color.sidebar : tokens.color.ink,
                color: asking ? tokens.color.ink : tokens.color.inkText,
                border: asking ? `1px solid ${tokens.color.border2}` : "none",
                borderRadius: 14,
                padding: "0 24px",
                fontSize: 15,
                fontWeight: 600,
                cursor: stopping || (loading && !asking) || slash || waitUpload ? "not-allowed" : "pointer",
                opacity: stopping || (loading && !asking) || slash || waitUpload ? 0.5 : 1,
              }}
              onClick={asking ? stop : () => void sendQuestion()}
              disabled={stopping || (loading && !asking) || slash !== null}
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
            {waitUpload && (
              <span role="tooltip" id="ask-wait" className="action-tooltip" style={{ ...tooltipStyle, left: "auto", right: 0 }}>
                Wait for the file to finish uploading.
              </span>
            )}
            </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
