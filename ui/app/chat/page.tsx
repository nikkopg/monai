"use client";

import { useEffect, useRef, useState } from "react";

import { tokens, input, btn, btnGhost } from "../styles";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type TraceStep = {
  tool: string;
  args: Record<string, unknown>;
  result: Record<string, unknown>;
};

type Proposal = {
  id: string;
  token: string;
  operation: string;
  payload: {
    operation: string;
    rows: Array<{
      id?: number;
      before?: Record<string, unknown>;
      after?: Record<string, unknown>;
      old_name?: string;
      new_name?: string;
      from_name?: string;
      into_name?: string;
      affected_count?: number;
    }>;
  };
  // client-side expiry: computed as Date.now() + 15 min when answer event arrives
  expiresAt: Date;
};

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

  const expired = now > proposal.expiresAt;
  const disabled = busy || status !== "pending" || expired;
  const minsLeft = Math.max(
    0,
    Math.round((proposal.expiresAt.getTime() - now.getTime()) / 60000)
  );

  const cardStyle: React.CSSProperties = {
    background: tokens.color.card,
    border: `1px solid ${
      status === "applied"
        ? tokens.color.green
        : status === "rejected"
        ? tokens.color.border2
        : "#cfe0d6"
    }`,
    borderLeft: `3px solid ${
      status === "rejected" ? tokens.color.terracotta : tokens.color.green
    }`,
    borderRadius: 14,
    padding: "18px 20px",
    marginTop: 16,
    marginBottom: 26,
    opacity: expired && status === "pending" ? 0.6 : 1,
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

  const del = { color: tokens.color.terracotta };
  const add = { color: tokens.color.green };
  const dim = { color: tokens.color.muted2 };
  const rowBorder = (i: number) =>
    i > 0 ? `1px solid ${tokens.color.borderInner}` : undefined;

  // Render before→after diff rows (D-02)
  function renderDiff() {
    const { rows } = proposal.payload;
    if (!rows || rows.length === 0) return null;

    const batchSummary =
      rows.length > 1 ? (
        <div style={{ fontSize: 12, ...dim, marginBottom: 10 }}>
          {rows.length} rows affected
        </div>
      ) : null;

    const displayRows = rows.slice(0, 5);
    const remainder = rows.length - displayRows.length;

    return (
      <div style={{ fontSize: 14 }}>
        {batchSummary}
        {displayRows.map((row, i) => {
          if (row.old_name !== undefined) {
            return (
              <div key={i} style={{ padding: "6px 0", borderTop: rowBorder(i) }}>
                <span style={{ ...del, textDecoration: "line-through" }}>
                  {row.old_name}
                </span>
                {" → "}
                <span style={{ ...add, fontWeight: 600 }}>{row.new_name}</span>
                {row.affected_count !== undefined && (
                  <span style={dim}> ({row.affected_count} tx)</span>
                )}
              </div>
            );
          }
          if (row.from_name !== undefined) {
            return (
              <div key={i} style={{ padding: "6px 0" }}>
                merge <span style={del}>{row.from_name}</span>
                {" → "}
                <span style={{ ...add, fontWeight: 600 }}>{row.into_name}</span>
              </div>
            );
          }
          if (!row.before && row.after) {
            return (
              <div key={i} style={{ padding: "6px 0", borderTop: rowBorder(i) }}>
                {Object.entries(row.after).map(([k, v]) => (
                  <div key={k}>
                    <span style={dim}>{k}: </span>
                    <span style={add}>{String(v ?? "—")}</span>
                  </div>
                ))}
              </div>
            );
          }
          if (row.before && !row.after) {
            return (
              <div key={i} style={{ padding: "6px 0", borderTop: rowBorder(i) }}>
                {Object.entries(row.before).map(([k, v]) => (
                  <div key={k}>
                    <span style={dim}>{k}: </span>
                    <span style={del}>{String(v ?? "—")}</span>
                  </div>
                ))}
              </div>
            );
          }
          if (row.before && row.after) {
            const changedKeys = Object.keys(row.after).filter(
              (k) => String(row.after![k]) !== String(row.before![k])
            );
            if (changedKeys.length === 0) {
              return (
                <div key={i} style={{ ...dim, fontSize: 12 }}>
                  (no field changes detected)
                </div>
              );
            }
            return (
              <div key={i} style={{ padding: "6px 0", borderTop: rowBorder(i) }}>
                {changedKeys.map((k) => (
                  <div key={k}>
                    <span style={dim}>{k}: </span>
                    <span style={del}>{String(row.before![k] ?? "—")}</span>
                    {" → "}
                    <span style={add}>{String(row.after![k] ?? "—")}</span>
                  </div>
                ))}
              </div>
            );
          }
          return null;
        })}
        {remainder > 0 && (
          <div style={{ ...dim, fontSize: 12, marginTop: 6 }}>
            + {remainder} more row{remainder > 1 ? "s" : ""}
          </div>
        )}
      </div>
    );
  }

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
        Proposed {proposal.operation.replace(/_/g, " ")}
      </div>

      {renderDiff()}

      {expired && status === "pending" && (
        <div style={{ ...dim, fontSize: 12, marginTop: 10 }}>
          Expired — ask again to redo this
        </div>
      )}
      {status === "applied" && (
        <div style={{ color: tokens.color.green, fontSize: 13, marginTop: 10 }}>
          Applied successfully.
        </div>
      )}
      {status === "rejected" && (
        <div style={{ ...dim, fontSize: 13, marginTop: 10 }}>
          Rejected — no changes made.
        </div>
      )}
      {error && (
        <div
          style={{ color: tokens.color.terracotta, fontSize: 12, marginTop: 8 }}
        >
          {error}
        </div>
      )}

      {status === "pending" && (
        <div
          style={{ display: "flex", gap: 10, marginTop: 16, alignItems: "center" }}
        >
          <button
            style={{
              ...btn,
              opacity: disabled ? 0.5 : 1,
              cursor: disabled ? "not-allowed" : "pointer",
            }}
            onClick={handleApprove}
            disabled={disabled}
          >
            {busy ? "…" : "Approve"}
          </button>
          <button
            style={{
              ...btnGhost,
              cursor: disabled ? "not-allowed" : "pointer",
            }}
            onClick={handleReject}
            disabled={disabled}
          >
            {busy ? "…" : "Reject"}
          </button>
          {!expired && (
            <span
              style={{
                marginLeft: "auto",
                fontSize: 12,
                color: tokens.color.muted2,
              }}
            >
              expires in {minsLeft} min
            </span>
          )}
        </div>
      )}
    </div>
  );
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
  const [asking, setAsking] = useState(false);
  const [steps, setSteps] = useState<string[]>([]);
  const [trace, setTrace] = useState<TraceStep[]>([]);
  const [traceOpen, setTraceOpen] = useState(false);
  const [proposal, setProposal] = useState<Proposal | null>(null);

  const cancelRef = useRef(false);

  // SSE-backed ask() — POST /api/query-stream (EventSource is GET-only).
  async function ask() {
    const q = question.trim();
    if (!q) return;

    setAsking(true);
    setAskedQuestion(q);
    setQuestion("");
    setAnswer("");
    setSteps([]);
    setTrace([]);
    setTraceOpen(false);
    setProposal(null);
    cancelRef.current = false;

    try {
      const resp = await fetch("/api/query-stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q }),
      });

      if (!resp.ok || !resp.body) {
        const d = await resp.json().catch(() => ({}));
        setAnswer(`Error: ${d.detail || resp.statusText}`);
        return;
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";

      while (!cancelRef.current) {
        const { done, value } = await reader.read();
        if (done) break;

        buf += decoder.decode(value, { stream: true });

        const messages = buf.split("\n\n");
        buf = messages.pop() ?? "";

        for (const message of messages) {
          const dataLine = message.replace(/^data: /, "").trim();
          if (dataLine === "[DONE]") {
            cancelRef.current = true;
            break;
          }
          if (!dataLine) continue;

          let msg: {
            type: string;
            msg?: string;
            step?: TraceStep;
            text?: string;
            trace?: TraceStep[];
            proposal_id?: string | null;
            proposal_token?: string | null;
          };
          try {
            msg = JSON.parse(dataLine);
          } catch {
            continue;
          }

          if (msg.type === "step" && msg.msg) {
            setSteps((prev) => [...prev, msg.msg!]);
          } else if (msg.type === "tool_result" && msg.step) {
            setTrace((prev) => [...prev, msg.step!]);
          } else if (msg.type === "answer") {
            setAnswer(msg.text ?? "");
            if (msg.trace) setTrace(msg.trace);
            if (msg.proposal_id && msg.proposal_token) {
              // Build Proposal from SSE answer event; client-side expiry is
              // cosmetic — server enforces authoritatively on confirm (D-09/D-10).
              setProposal({
                id: msg.proposal_id,
                token: msg.proposal_token,
                operation:
                  msg.trace?.find(
                    (s) => s.result?.proposal_id === msg.proposal_id
                  )?.tool ?? "write",
                payload: (msg.trace?.find(
                  (s) => s.result?.proposal_id === msg.proposal_id
                )?.result?.payload as Proposal["payload"]) ?? {
                  operation: "write",
                  rows: [],
                },
                expiresAt: new Date(Date.now() + 15 * 60 * 1000),
              });
            }
          }
        }
      }
    } catch (e: unknown) {
      setAnswer(`Error: ${e instanceof Error ? e.message : "Network error"}`);
    } finally {
      setAsking(false);
    }
  }

  const conversationStarted = !!askedQuestion;

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

        {(asking || answer) && (
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
              <span style={{ fontSize: 12, color: tokens.color.muted2 }}>
                · {asking && !answer ? "thinking…" : "answered just now"}
              </span>
            </div>

            {/* Progressive step indicator while streaming (D-08) */}
            {asking && steps.length > 0 && !answer && (
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

            {/* Answer (D-07) */}
            {answer && (
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

            {/* Inline ProposalCard (D-01) */}
            {proposal && (
              <ProposalCard
                proposal={proposal}
                onApplied={() => {
                  // /cashflow re-fetches its own list on mount; nothing local.
                }}
                onRejected={() => {
                  // nothing extra needed
                }}
              />
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
        <input
          style={{ ...input, borderRadius: 14, padding: "14px 18px", fontSize: 15 }}
          value={question}
          placeholder="Ask anything about your finances…"
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && ask()}
        />
        <button
          style={{
            background: tokens.color.ink,
            color: tokens.color.inkText,
            border: "none",
            borderRadius: 14,
            padding: "0 24px",
            fontSize: 15,
            fontWeight: 600,
            cursor: asking ? "not-allowed" : "pointer",
          }}
          onClick={ask}
          disabled={asking}
        >
          {asking ? "…" : "Ask"}
        </button>
      </div>
    </div>
  );
}
