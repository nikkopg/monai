"use client";

import { useEffect, useRef, useState } from "react";

import { tokens, input, btn, btnGhost, btnDark } from "../styles";
import ProposalDiff from "../components/ProposalDiff";
import type { DiffRow } from "../components/ProposalDiff";
import { hhmm } from "../lib/inbox";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type TraceStep = {
  tool: string;
  args: Record<string, unknown>;
  result: Record<string, unknown>;
};

// Shape of one entry in the SSE answer event's proposals[] (server contract).
type ServerProposal = {
  id: string;
  token: string;
  operation?: string | null;
  payload?: { operation: string; rows: DiffRow[] } | null;
  expires_at?: string | null;
};

type Proposal = {
  id: string;
  token: string | null;
  operation: string | null;
  payload: { operation: string; rows: DiffRow[] } | null;
  expiresAt: Date | null;
  rejectedByStop?: boolean;
};

function toProposal(p: ServerProposal): Proposal {
  const ms =
    typeof p.expires_at === "string" && p.expires_at !== ""
      ? Date.parse(p.expires_at)
      : NaN;
  return {
    id: p.id,
    token: p.token,
    operation: p.operation ?? null,
    payload: p.payload ?? null,
    expiresAt: Number.isNaN(ms) ? null : new Date(ms),
  };
}

// ---------------------------------------------------------------------------
// ProposalCard — inline card with before→after diff + Approve/Reject + expiry
// (D-01, D-02, D-03, D-10). v1.1 "paper" redesign: green-accented card.
// ---------------------------------------------------------------------------

function ProposalCard({
  proposal,
  onApplied,
  onRejected,
}: {
  proposal: Proposal;
  onApplied: () => void;
  onRejected: () => void;
}) {
  const [status, setStatus] = useState<"pending" | "applied" | "rejected">(
    "pending"
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(new Date());

  // Tick every 10 s to update expiry display
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 10_000);
    return () => clearInterval(id);
  }, []);

  const expiresAt = proposal.expiresAt;
  const expired = expiresAt !== null && now > expiresAt;
  const rows = proposal.payload?.rows ?? [];
  const unapprovableReason: string | null =
    rows.length === 0
      ? "Nothing to review: this proposal has no details, so it can't be approved. Reject it and ask again."
      : expiresAt === null
      ? "No expiry came with this proposal, so it can't be approved. Reject it and ask again."
      : null;
  const effectiveStatus = proposal.rejectedByStop ? "rejected" : status;
  const noticeId = `unapprovable-${proposal.id}`;
  const rejectDisabled = busy || effectiveStatus !== "pending" || expired;
  const approveDisabled =
    rejectDisabled || unapprovableReason !== null || !proposal.token;
  const remMs = expiresAt ? expiresAt.getTime() - now.getTime() : 0;

  const cardStyle: React.CSSProperties = {
    background: tokens.color.card,
    border: `1px solid ${
      effectiveStatus === "applied"
        ? tokens.color.green
        : effectiveStatus === "rejected"
        ? tokens.color.border2
        : "#cfe0d6"
    }`,
    borderLeft: `3px solid ${
      effectiveStatus === "rejected" ? tokens.color.terracotta : tokens.color.green
    }`,
    borderRadius: 14,
    padding: "18px 20px",
    marginTop: 16,
    marginBottom: 26,
    opacity: expired && effectiveStatus === "pending" ? 0.6 : 1,
  };

  async function handleApprove() {
    setBusy(true);
    setError(null);
    try {
      const r = await fetch(`/api/proposals/${proposal.id}/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: proposal.token }),
      });
      if (r.ok) {
        setStatus("applied");
        onApplied();
      } else {
        const d = await r.json().catch(() => ({}));
        if (r.status === 410) {
          setError("Expired — ask again to redo this");
        } else {
          setError(d.detail || `Error ${r.status}`);
        }
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Network error");
    } finally {
      setBusy(false);
    }
  }

  async function handleReject() {
    setBusy(true);
    setError(null);
    try {
      const r = await fetch(`/api/proposals/${proposal.id}/reject`, {
        method: "POST",
      });
      if (r.ok) {
        setStatus("rejected");
        onRejected();
      } else {
        const d = await r.json().catch(() => ({}));
        setError(d.detail || `Error ${r.status}`);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Network error");
    } finally {
      setBusy(false);
    }
  }

  const small: React.CSSProperties = {
    color: tokens.color.muted3,
    fontSize: 14,
    lineHeight: 1.5,
  };

  return (
    <div style={cardStyle}>
      <div
        style={{
          fontSize: 11,
          letterSpacing: ".1em",
          textTransform: "uppercase",
          color: tokens.color.green,
          fontWeight: 700,
          marginBottom: 10,
        }}
      >
        Proposed {(proposal.operation ?? "write").replace(/_/g, " ")}
      </div>

      {rows.length > 0 && <ProposalDiff rows={rows} />}

      {effectiveStatus === "pending" && unapprovableReason && (
        <div id={noticeId} style={{ ...small, marginTop: 8 }}>
          {unapprovableReason}
        </div>
      )}
      {expired && effectiveStatus === "pending" && (
        <div style={{ ...small, marginTop: 10 }}>
          Expired — ask again to redo this
        </div>
      )}
      {effectiveStatus === "applied" && (
        <div style={{ color: tokens.color.green, fontSize: 14, marginTop: 10 }}>
          Applied successfully.
        </div>
      )}
      {effectiveStatus === "rejected" && (
        <div style={{ ...small, marginTop: 10 }}>
          {proposal.rejectedByStop
            ? "Rejected — the run was stopped. No changes made."
            : "Rejected — no changes made."}
        </div>
      )}
      {error && (
        <div
          style={{ color: tokens.color.terracotta, fontSize: 12, marginTop: 8 }}
        >
          {error}
        </div>
      )}

      {effectiveStatus === "pending" && (
        <div
          style={{ display: "flex", gap: 10, marginTop: 16, alignItems: "center" }}
        >
          <button
            style={{
              ...btn,
              opacity: approveDisabled ? 0.5 : 1,
              cursor: approveDisabled ? "not-allowed" : "pointer",
            }}
            onClick={handleApprove}
            disabled={approveDisabled}
            aria-describedby={unapprovableReason ? noticeId : undefined}
          >
            {busy ? "…" : "Approve"}
          </button>
          <button
            style={{
              ...btnGhost,
              cursor: rejectDisabled ? "not-allowed" : "pointer",
            }}
            onClick={handleReject}
            disabled={rejectDisabled}
          >
            {busy ? "…" : "Reject"}
          </button>
          {!expired && expiresAt && (
            <span
              style={{
                marginLeft: "auto",
                fontSize: 12,
                color: tokens.color.muted3,
              }}
            >
              expires {hhmm(expiresAt.getTime())} · in{" "}
              {remMs < 60000 ? "under 1" : Math.floor(remMs / 60000)} min
            </span>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Error copy (34-UI-SPEC §2). Only these fixed strings are ever rendered for a
// failure; response `detail` and exception text never reach the DOM (D-02).
// ---------------------------------------------------------------------------

const ERROR_COPY: Record<string, { title: string; body: string }> = {
  rate_limit: {
    title: "The model is rate-limited",
    body: "The provider asked monai to slow down. Wait a few seconds, then retry. Nothing was changed.",
  },
  provider_unavailable: {
    title: "The model provider is having trouble",
    body: "The provider returned a server error. Retry in a moment. Nothing was changed.",
  },
  timeout: {
    title: "The model took too long to answer",
    body: "The provider did not respond in time. Retry, or ask a narrower question. Nothing was changed.",
  },
  idle_timeout: {
    title: "The answer stalled",
    body: "No activity, so monai ended the run. Nothing was changed.",
  },
  auth: {
    title: "The model rejected monai's credentials",
    body: "The provider key is missing or invalid. Fix the key in the server settings, then retry.",
  },
  connection: {
    title: "monai can't reach the model",
    body: "The connection to the model provider failed. If you use Ollama, check that it is running, then retry.",
  },
  empty: {
    title: "The model returned no answer",
    body: "It replied with nothing and ran no tools. Retry or rephrase the question.",
  },
  stream_ended: {
    title: "The answer stopped early",
    body: "The connection closed before the answer finished. Nothing was changed.",
  },
  conflict: {
    title: "Another answer is already running",
    body: "This conversation already has a run in progress, possibly in another tab. Wait for it to finish, then ask again.",
  },
  unauthorized: {
    title: "Chat isn't authorized",
    body: "monai has no API key configured for this page. Set the server key, reload, and ask again.",
  },
  unknown: {
    title: "Something went wrong",
    body: "monai hit an unexpected error. Nothing was changed. Retry, and if it keeps happening check the server log.",
  },
};

// Upper bound on the Stop cancel request (WR-02).
const CANCEL_TIMEOUT_MS = 10_000;

const TRANSPORT_BODY =
  "The connection to monai failed. Check that the server is running, then retry.";

type ChatError = {
  code: string;
  model: string | null;
  idleSeconds: number | null;
  transport?: boolean;
};

function errorCopy(err: ChatError): { title: string; body: string } {
  const c = ERROR_COPY[err.code] ?? ERROR_COPY.unknown;
  if (err.transport) return { title: c.title, body: TRANSPORT_BODY };
  if (err.code === "idle_timeout" && err.idleSeconds !== null) {
    return {
      title: c.title,
      body: `No activity for ${Math.round(err.idleSeconds)} seconds, so monai ended the run. Nothing was changed.`,
    };
  }
  return c;
}

// ---------------------------------------------------------------------------
// Chat page — v1.1 "paper" redesign. Same single-turn SSE flow
// (/api/query-stream), tool-trace, and confirm-before-write ProposalCard;
// re-laid-out as user bubble + assistant answer block + sticky composer.
// ---------------------------------------------------------------------------

export default function ChatPage() {
  const [question, setQuestion] = useState("");
  const [askedQuestion, setAskedQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [answered, setAnswered] = useState(false);
  const [asking, setAsking] = useState(false);
  const [steps, setSteps] = useState<string[]>([]);
  const [trace, setTrace] = useState<TraceStep[]>([]);
  const [traceOpen, setTraceOpen] = useState(false);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [error, setError] = useState<ChatError | null>(null);
  const [stopping, setStopping] = useState(false);
  const [stopped, setStopped] = useState(false);
  const [stopRejected, setStopRejected] = useState(false);
  const [model, setModel] = useState<{
    name: string | null;
    provider: string | null;
  } | null>(null);

  const busyRef = useRef(false); // synchronous double-submit guard
  const abortRef = useRef<AbortController | null>(null);
  const runIdRef = useRef<string | null>(null);
  const stoppedRef = useRef(false);
  const traceRef = useRef<TraceStep[]>([]);

  // SSE-backed sendQuestion() — POST /api/query-stream (EventSource is GET-only).
  // `retry` (Ask again) keeps the restored question in the input.
  async function sendQuestion(text?: string, retry = false) {
    const q = (text ?? question).trim();
    if (!q || busyRef.current) return;
    busyRef.current = true;

    setAsking(true);
    setAskedQuestion(q);
    if (!retry) setQuestion("");
    setAnswer("");
    setAnswered(false);
    setSteps([]);
    setTrace([]);
    setTraceOpen(false);
    setProposals([]);
    setError(null);
    setStopping(false);
    setStopped(false);
    setStopRejected(false);
    setModel(null);
    stoppedRef.current = false;
    runIdRef.current = null;
    traceRef.current = [];

    const ac = new AbortController();
    abortRef.current = ac;
    let terminal = false;
    const fail = (e: ChatError) => {
      terminal = true;
      setError(e);
      setQuestion(q); // REL-01: the question is never lost
    };

    try {
      const resp = await fetch("/api/query-stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q }),
        signal: ac.signal,
      });

      if (!resp.ok || !resp.body) {
        // Never read or show `detail` (D-02): the status alone picks the copy.
        fail({
          code:
            resp.status === 409
              ? "conflict"
              : resp.status === 401 || resp.status === 403 || resp.status === 503
              ? "unauthorized"
              : resp.status === 502 || resp.status === 504
              ? "connection"
              : "unknown",
          model: null,
          idleSeconds: null,
          // The proxy answers 502 when the backend is unreachable: a transport
          // failure, so the "connection to monai failed" copy applies.
          transport: resp.status === 502 || resp.status === 504,
        });
        return;
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      let done = false;

      while (!done && !stoppedRef.current) {
        const { done: eof, value } = await reader.read();
        if (eof) break;

        buf += decoder.decode(value, { stream: true });

        const messages = buf.split("\n\n");
        buf = messages.pop() ?? "";

        for (const message of messages) {
          if (stoppedRef.current) break; // late events after Stop are dropped
          if (message.startsWith(":")) continue; // keep-alive ping: invisible
          const dataLine = message.replace(/^data: /, "").trim();
          if (dataLine === "[DONE]") {
            done = true;
            break;
          }
          if (!dataLine) continue;

          let msg: {
            type: string;
            msg?: string;
            step?: TraceStep;
            text?: string;
            trace?: TraceStep[];
            proposals?: ServerProposal[];
            run_id?: string;
            code?: string;
            model?: string | null;
            provider?: string | null;
            idle_seconds?: number;
          };
          try {
            msg = JSON.parse(dataLine);
          } catch {
            continue;
          }

          if (msg.type === "run" && msg.run_id) {
            runIdRef.current = msg.run_id;
          } else if (msg.type === "step" && msg.msg) {
            setSteps((prev) => [...prev, msg.msg!]);
          } else if (msg.type === "tool_result" && msg.step) {
            traceRef.current = [...traceRef.current, msg.step];
            setTrace(traceRef.current);
          } else if (msg.type === "answer") {
            terminal = true;
            setAnswered(true);
            setAnswer(msg.text ?? "");
            if (msg.trace) {
              traceRef.current = msg.trace;
              setTrace(msg.trace);
            }
            setModel({ name: msg.model ?? null, provider: msg.provider ?? null });
            setProposals((msg.proposals ?? []).map(toProposal));
          } else if (msg.type === "error") {
            fail({
              code: msg.code ?? "unknown",
              model: msg.model ?? null,
              idleSeconds:
                typeof msg.idle_seconds === "number" ? msg.idle_seconds : null,
            });
            // Proposals created before the failure stay actionable (D-05).
            setProposals((msg.proposals ?? []).map(toProposal));
          }
        }
      }

      if (!terminal && !stoppedRef.current) {
        fail({ code: "stream_ended", model: null, idleSeconds: null });
      }
    } catch {
      if (!stoppedRef.current) {
        fail({ code: "connection", model: null, idleSeconds: null, transport: true });
      }
    } finally {
      // Only the invocation that still owns the shared refs may clear them.
      if (abortRef.current === ac) {
        abortRef.current = null;
        busyRef.current = false;
        if (!stoppedRef.current) setAsking(false); // stop() clears it otherwise
      }
    }
  }

  // Stop: tell the server to cancel (deterministic) and abort the fetch.
  // The two are not ordered (Pitfall 2); the cancel reply lists the proposals
  // the server rejected so their cards can show rejected-by-Stop (D-08).
  async function stop() {
    if (stoppedRef.current) return;
    stoppedRef.current = true;
    setStopping(true);

    const runId = runIdRef.current;
    // Bounded: a hung DB behind the cancel route must not pin "Stopping…" for ever.
    const cancelAc = new AbortController();
    const cancelTimer = setTimeout(() => cancelAc.abort(), CANCEL_TIMEOUT_MS);
    const cancel: Promise<string[]> = runId
      ? fetch(`/api/query-stream/${runId}/cancel`, {
          method: "POST",
          signal: cancelAc.signal,
        })
          .then((r) => (r.ok ? r.json() : { rejected: [] }))
          .then((d) => (Array.isArray(d.rejected) ? (d.rejected as string[]) : []))
          .catch(() => [])
          .finally(() => clearTimeout(cancelTimer))
      : Promise.resolve([]);
    abortRef.current?.abort();
    const rejected = await cancel;

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
                  {
                    before: s.result.before ?? null,
                    after: s.result.after ?? null,
                  } as DiffRow,
                ],
              }
            : null,
          expiresAt: null,
          rejectedByStop: true,
        };
      });
    setProposals(cards);
    setStopRejected(rejected.length > 0);
    // A terminal event may have landed just before Stop; Stop wins (UI-SPEC §3).
    setAnswered(false);
    setAnswer("");
    setModel(null);
    setError(null);
    setStopped(true);
    setStopping(false);
    setAsking(false);
    setQuestion(askedQuestion);
  }

  const conversationStarted = !!askedQuestion;
  const errCopy = error ? errorCopy(error) : null;

  return (
    <div
      className="tab-in"
      style={{
        maxWidth: 760,
        margin: "0 auto",
        padding: "40px 44px 60px",
        minHeight: "100%",
        display: "flex",
        flexDirection: "column",
      }}
    >
      <div style={{ marginBottom: 26 }}>
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
        {conversationStarted && (
          <div
            style={{
              display: "flex",
              justifyContent: "flex-end",
              marginBottom: 18,
            }}
          >
            <div
              style={{
                background: tokens.color.ink,
                color: tokens.color.inkText,
                padding: "12px 18px",
                borderRadius: "16px 16px 4px 16px",
                fontSize: 15,
                maxWidth: "80%",
              }}
            >
              {askedQuestion}
            </div>
          </div>
        )}

        {(asking || answered || error || stopped) && (
          <div style={{ marginBottom: 16 }}>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                marginBottom: 10,
              }}
            >
              <span style={{ fontFamily: tokens.font.serif, fontSize: 18 }}>
                monai
              </span>
              {(asking || answered || stopped) && (
                <span style={{ fontSize: 12, color: tokens.color.muted3 }}>
                  ·{" "}
                  {stopped
                    ? "stopped"
                    : answered
                    ? "answered just now"
                    : "thinking…"}
                </span>
              )}
              {answered && (
                <span
                  title={model?.provider ?? undefined}
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
                  {model?.name ?? "model unknown"}
                </span>
              )}
            </div>

            {/* Progressive step indicator while streaming (D-08) */}
            {steps.length > 0 && !answered && (
              <div style={{ marginBottom: 6 }}>
                {steps.map((s, i) => (
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

            {/* Typed error block (REL-01/02/06, UI-SPEC §2) */}
            {error && errCopy && (
              <div
                role="alert"
                style={{
                  background: tokens.color.tintWarm,
                  border: `1px solid ${tokens.color.border2}`,
                  borderLeft: `3px solid ${tokens.color.terracotta}`,
                  borderRadius: 14,
                  padding: 16,
                  marginBottom: 16,
                }}
              >
                <div
                  style={{ fontSize: 16, fontWeight: 600, color: tokens.color.ink }}
                >
                  {errCopy.title}
                </div>
                <div
                  style={{
                    fontSize: 14,
                    fontWeight: 400,
                    color: tokens.color.muted3,
                    marginTop: 8,
                    lineHeight: 1.5,
                  }}
                >
                  {errCopy.body}
                </div>
                {error.model && (
                  <div
                    style={{
                      fontSize: 12,
                      color: tokens.color.muted3,
                      marginTop: 8,
                    }}
                  >
                    Model: {error.model}
                  </div>
                )}
                <div
                  style={{
                    display: "flex",
                    gap: 16,
                    flexWrap: "wrap",
                    marginTop: 16,
                  }}
                >
                  {!asking && (
                    <button
                      type="button"
                      style={{ ...btnDark, minHeight: 36 }}
                      onClick={() => sendQuestion(askedQuestion, true)}
                    >
                      Ask again
                    </button>
                  )}
                </div>
              </div>
            )}

            {/* Stopped run (REL-03, UI-SPEC §3) */}
            {stopped && (
              <div
                role="status"
                style={{
                  fontSize: 14,
                  color: tokens.color.muted3,
                  lineHeight: 1.5,
                  marginBottom: 14,
                }}
              >
                Stopped. No answer was kept.
                {stopRejected ? " Proposals from this run were rejected." : ""}
              </div>
            )}

            {/* Answer (D-07) */}
            {answered && answer && (
              <div
                style={{
                  fontSize: 16,
                  lineHeight: 1.6,
                  margin: "0 0 14px",
                  color: tokens.color.textSoft,
                  whiteSpace: "pre-wrap",
                }}
              >
                {answer}
              </div>
            )}

            {/* Collapsible tool-call trace (D-07) */}
            {trace.length > 0 && (
              <>
                <button
                  onClick={() => setTraceOpen((o) => !o)}
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
                  {traceOpen ? "▴" : "▾"} how I got this ({trace.length} step
                  {trace.length !== 1 ? "s" : ""})
                </button>
                {traceOpen && (
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
                    {trace.map((step, i) => (
                      <div
                        key={i}
                        style={{
                          fontSize: 12,
                          color: tokens.color.muted,
                          fontFamily: "ui-monospace, monospace",
                        }}
                      >
                        <span
                          style={{ color: tokens.color.green, fontWeight: 600 }}
                        >
                          {step.tool}
                        </span>
                        (
                        {Object.entries(step.args ?? {})
                          .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
                          .join(", ")}
                        ){" "}
                        <span style={{ color: tokens.color.inkTextMuted }}>
                          →
                        </span>{" "}
                        {JSON.stringify(step.result).slice(0, 120)}
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}

            {/* Inline ProposalCards — one per proposal in this turn (D-01, AGENT-06) */}
            {proposals.map((p) => (
              <ProposalCard
                key={p.id}
                proposal={p}
                onApplied={() => {
                  // /cashflow re-fetches its own list on mount; nothing local.
                }}
                onRejected={() => {
                  // nothing extra needed
                }}
              />
            ))}
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
        <input
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
            if (asking || busyRef.current) return; // swallowed while running
            sendQuestion();
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
            cursor: stopping ? "not-allowed" : "pointer",
            opacity: stopping ? 0.5 : 1,
          }}
          onClick={asking ? stop : () => sendQuestion()}
          disabled={stopping}
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
  );
}
