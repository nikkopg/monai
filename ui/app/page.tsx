"use client";

import { useEffect, useRef, useState } from "react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Tx = {
  id: number;
  date: string;
  amount: number;
  category: string | null;
  merchant: string | null;
  is_transfer: boolean;
};

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
// Inline style objects — dark palette (CLAUDE.md: inline React.CSSProperties only)
// ---------------------------------------------------------------------------

const card: React.CSSProperties = {
  background: "#1a1d23",
  border: "1px solid #2a2e37",
  borderRadius: 12,
  padding: 20,
  marginBottom: 20,
};
const input: React.CSSProperties = {
  background: "#0f1115",
  border: "1px solid #2a2e37",
  borderRadius: 8,
  color: "#e6e8eb",
  padding: "10px 12px",
  fontSize: 14,
  width: "100%",
  boxSizing: "border-box",
};
const btn: React.CSSProperties = {
  background: "#3b82f6",
  color: "white",
  border: "none",
  borderRadius: 8,
  padding: "10px 18px",
  fontSize: 14,
  cursor: "pointer",
  fontWeight: 600,
};
const label: React.CSSProperties = {
  fontSize: 12,
  color: "#9aa0a6",
  marginBottom: 4,
  display: "block",
};

// ---------------------------------------------------------------------------
// ProposalCard — inline card with before→after diff + Approve/Reject + expiry
// (D-01, D-02, D-03, D-10)
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

  const cardStyle: React.CSSProperties = {
    ...card,
    opacity: expired && status === "pending" ? 0.55 : 1,
    border: `1px solid ${
      status === "applied"
        ? "#4ade80"
        : status === "rejected"
        ? "#f87171"
        : "#3b82f6"
    }`,
    marginTop: 16,
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

  // Render before→after diff rows (D-02)
  function renderDiff() {
    const { rows } = proposal.payload;
    if (!rows || rows.length === 0) return null;

    // Batch summary when > 1 rows (D-03)
    const batchSummary =
      rows.length > 1 ? (
        <div
          style={{
            fontSize: 12,
            color: "#9aa0a6",
            marginBottom: 10,
          }}
        >
          {rows.length} rows affected
        </div>
      ) : null;

    // Show at most 5 rows in the diff to keep the card compact; note remainder
    const displayRows = rows.slice(0, 5);
    const remainder = rows.length - displayRows.length;

    return (
      <div style={{ fontSize: 13 }}>
        {batchSummary}
        {displayRows.map((row, i) => {
          // rename_category / merge_category: use old_name/new_name etc.
          if (row.old_name !== undefined) {
            return (
              <div
                key={i}
                style={{
                  padding: "6px 0",
                  borderTop: i > 0 ? "1px solid #2a2e37" : undefined,
                }}
              >
                <span style={{ color: "#f87171" }}>{row.old_name}</span>
                {" → "}
                <span style={{ color: "#4ade80" }}>{row.new_name}</span>
                {row.affected_count !== undefined && (
                  <span style={{ color: "#9aa0a6" }}>
                    {" "}
                    ({row.affected_count} tx)
                  </span>
                )}
              </div>
            );
          }
          if (row.from_name !== undefined) {
            return (
              <div key={i} style={{ padding: "6px 0" }}>
                merge{" "}
                <span style={{ color: "#f87171" }}>{row.from_name}</span>
                {" → "}
                <span style={{ color: "#4ade80" }}>{row.into_name}</span>
              </div>
            );
          }

          // add: show after fields
          if (!row.before && row.after) {
            return (
              <div
                key={i}
                style={{
                  padding: "6px 0",
                  borderTop: i > 0 ? "1px solid #2a2e37" : undefined,
                }}
              >
                {Object.entries(row.after).map(([k, v]) => (
                  <div key={k}>
                    <span style={{ color: "#9aa0a6" }}>{k}: </span>
                    <span style={{ color: "#4ade80" }}>
                      {String(v ?? "—")}
                    </span>
                  </div>
                ))}
              </div>
            );
          }

          // delete: show before fields
          if (row.before && !row.after) {
            return (
              <div
                key={i}
                style={{
                  padding: "6px 0",
                  borderTop: i > 0 ? "1px solid #2a2e37" : undefined,
                }}
              >
                {Object.entries(row.before).map(([k, v]) => (
                  <div key={k}>
                    <span style={{ color: "#9aa0a6" }}>{k}: </span>
                    <span style={{ color: "#f87171" }}>
                      {String(v ?? "—")}
                    </span>
                  </div>
                ))}
              </div>
            );
          }

          // edit: show changed fields only (before → after)
          if (row.before && row.after) {
            const changedKeys = Object.keys(row.after).filter(
              (k) => String(row.after![k]) !== String(row.before![k])
            );
            if (changedKeys.length === 0) {
              return (
                <div key={i} style={{ color: "#9aa0a6", fontSize: 12 }}>
                  (no field changes detected)
                </div>
              );
            }
            return (
              <div
                key={i}
                style={{
                  padding: "6px 0",
                  borderTop: i > 0 ? "1px solid #2a2e37" : undefined,
                }}
              >
                {changedKeys.map((k) => (
                  <div key={k}>
                    <span style={{ color: "#9aa0a6" }}>{k}: </span>
                    <span style={{ color: "#f87171" }}>
                      {String(row.before![k] ?? "—")}
                    </span>
                    {" → "}
                    <span style={{ color: "#4ade80" }}>
                      {String(row.after![k] ?? "—")}
                    </span>
                  </div>
                ))}
              </div>
            );
          }

          return null;
        })}
        {remainder > 0 && (
          <div style={{ color: "#9aa0a6", fontSize: 12, marginTop: 6 }}>
            + {remainder} more row{remainder > 1 ? "s" : ""}
          </div>
        )}
      </div>
    );
  }

  return (
    <div style={cardStyle}>
      {/* Card header */}
      <div
        style={{
          fontSize: 11,
          fontWeight: 700,
          letterSpacing: "0.08em",
          color: "#3b82f6",
          marginBottom: 8,
          textTransform: "uppercase" as const,
        }}
      >
        PROPOSED {proposal.operation.replace(/_/g, " ")}
      </div>

      {/* Diff */}
      {renderDiff()}

      {/* Expiry notice */}
      {expired && status === "pending" && (
        <div style={{ color: "#9aa0a6", fontSize: 12, marginTop: 10 }}>
          Expired — ask again to redo this
        </div>
      )}

      {/* Status banners */}
      {status === "applied" && (
        <div style={{ color: "#4ade80", fontSize: 13, marginTop: 10 }}>
          Applied successfully.
        </div>
      )}
      {status === "rejected" && (
        <div style={{ color: "#9aa0a6", fontSize: 13, marginTop: 10 }}>
          Rejected — no changes made.
        </div>
      )}

      {/* Error */}
      {error && (
        <div style={{ color: "#f87171", fontSize: 12, marginTop: 8 }}>
          {error}
        </div>
      )}

      {/* Buttons */}
      {status === "pending" && (
        <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
          <button
            style={{
              ...btn,
              background: expired ? "#374151" : "#4ade80",
              color: expired ? "#9aa0a6" : "#0f1115",
              cursor: disabled ? "not-allowed" : "pointer",
            }}
            onClick={handleApprove}
            disabled={disabled}
          >
            {busy ? "…" : "Approve"}
          </button>
          <button
            style={{
              ...btn,
              background: expired ? "#374151" : "#f87171",
              color: expired ? "#9aa0a6" : "white",
              cursor: disabled ? "not-allowed" : "pointer",
            }}
            onClick={handleReject}
            disabled={disabled}
          >
            {busy ? "…" : "Reject"}
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function Home() {
  // Query / streaming state
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [asking, setAsking] = useState(false);
  const [steps, setSteps] = useState<string[]>([]);
  const [trace, setTrace] = useState<TraceStep[]>([]);
  const [traceOpen, setTraceOpen] = useState(false);
  const [proposal, setProposal] = useState<Proposal | null>(null);

  // Cancel ref — used to abort in-flight SSE reads on a new ask
  const cancelRef = useRef(false);

  // Entry form state
  const [form, setForm] = useState({
    date: new Date().toISOString().slice(0, 16),
    amount: "",
    category: "",
    merchant: "",
    account: "Cash",
    notes: "",
    is_transfer: false,
  });
  const [saving, setSaving] = useState(false);

  const [txs, setTxs] = useState<Tx[]>([]);

  async function loadTxs() {
    const r = await fetch("/api/transactions?limit=10");
    if (r.ok) setTxs(await r.json());
  }
  useEffect(() => {
    loadTxs();
  }, []);

  // ---------------------------------------------------------------------------
  // SSE-backed ask() — replaces the old blocking fetch("/api/query")
  // SSE is POST-based so we use fetch + ReadableStream reader, not EventSource
  // (EventSource only supports GET — RESEARCH.md Code Examples)
  // ---------------------------------------------------------------------------

  async function ask() {
    if (!question.trim()) return;

    // Reset state for new question
    setAsking(true);
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
        body: JSON.stringify({ question }),
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

        // SSE messages are delimited by double newlines
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
              // Build Proposal from SSE answer event; compute client-side expiry
              // (D-09/D-10: cosmetic — server enforces authoritatively on confirm)
              setProposal({
                id: msg.proposal_id,
                token: msg.proposal_token,
                operation: msg.trace?.find((s) =>
                  s.result?.proposal_id === msg.proposal_id
                )?.tool ?? "write",
                payload: (msg.trace?.find((s) =>
                  s.result?.proposal_id === msg.proposal_id
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

  // ---------------------------------------------------------------------------
  // Transaction form
  // ---------------------------------------------------------------------------

  async function addTx(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      const body = {
        date: new Date(form.date).toISOString(),
        amount: parseFloat(form.amount),
        category: form.category || null,
        merchant: form.merchant || null,
        account: form.account,
        notes: form.notes || null,
        is_transfer: form.is_transfer,
      };
      const r = await fetch("/api/transactions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (r.ok) {
        setForm({ ...form, amount: "", category: "", merchant: "", notes: "" });
        loadTxs();
      }
    } finally {
      setSaving(false);
    }
  }

  const fmt = (n: number) =>
    new Intl.NumberFormat("en-US", { signDisplay: "always" }).format(n);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <main style={{ maxWidth: 760, margin: "0 auto", padding: "40px 20px" }}>
      <h1 style={{ fontSize: 28, marginBottom: 4 }}>monai</h1>
      <p style={{ color: "#9aa0a6", marginTop: 0, marginBottom: 28 }}>
        personal wealth intelligence
      </p>

      {/* Ask — SSE streaming chat */}
      <section style={card}>
        <label style={label}>Ask about your finances</label>
        <div style={{ display: "flex", gap: 8 }}>
          <input
            style={input}
            value={question}
            placeholder="How much did I spend on food this year?"
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && ask()}
          />
          <button style={btn} onClick={ask} disabled={asking}>
            {asking ? "…" : "Ask"}
          </button>
        </div>

        {/* Progressive step indicator (D-08) */}
        {asking && steps.length > 0 && (
          <div style={{ marginTop: 12 }}>
            {steps.map((s, i) => (
              <div
                key={i}
                style={{
                  fontSize: 12,
                  color: "#9aa0a6",
                  padding: "2px 0",
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                }}
              >
                <span style={{ color: "#3b82f6" }}>›</span>
                {s}
              </div>
            ))}
            <div
              style={{
                fontSize: 12,
                color: "#9aa0a6",
                marginTop: 4,
                fontStyle: "italic",
              }}
            >
              thinking…
            </div>
          </div>
        )}

        {/* Answer (D-07: prominent) */}
        {answer && (
          <pre
            style={{
              whiteSpace: "pre-wrap",
              marginTop: 16,
              marginBottom: 0,
              fontFamily: "inherit",
              fontSize: 15,
              lineHeight: 1.5,
            }}
          >
            {answer}
          </pre>
        )}

        {/* Collapsible tool-call trace — "▾ how I got this (N steps)" (D-07) */}
        {trace.length > 0 && (
          <div style={{ marginTop: 12 }}>
            <button
              onClick={() => setTraceOpen((o) => !o)}
              style={{
                background: "none",
                border: "none",
                color: "#9aa0a6",
                cursor: "pointer",
                fontSize: 12,
                padding: 0,
              }}
            >
              {traceOpen ? "▴" : "▾"} how I got this ({trace.length} step
              {trace.length !== 1 ? "s" : ""})
            </button>
            {traceOpen && (
              <div
                style={{
                  marginTop: 8,
                  borderLeft: "2px solid #2a2e37",
                  paddingLeft: 12,
                }}
              >
                {trace.map((step, i) => (
                  <div
                    key={i}
                    style={{
                      marginBottom: 8,
                      fontSize: 12,
                      color: "#9aa0a6",
                    }}
                  >
                    <span style={{ color: "#3b82f6", fontWeight: 600 }}>
                      {step.tool}
                    </span>
                    (
                    {Object.entries(step.args ?? {})
                      .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
                      .join(", ")}
                    ){" "}
                    <span style={{ color: "#6b7280" }}>→</span>{" "}
                    <span style={{ color: "#e6e8eb" }}>
                      {JSON.stringify(step.result).slice(0, 120)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Inline ProposalCard (D-01) */}
        {proposal && (
          <ProposalCard
            proposal={proposal}
            onApplied={() => {
              loadTxs();
            }}
            onRejected={() => {
              // nothing extra needed
            }}
          />
        )}
      </section>

      {/* Add transaction */}
      <section style={card}>
        <label style={label}>Log a transaction</label>
        <form onSubmit={addTx}>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: 10,
              marginBottom: 10,
            }}
          >
            <div>
              <label style={label}>Date</label>
              <input
                style={input}
                type="datetime-local"
                value={form.date}
                onChange={(e) => setForm({ ...form, date: e.target.value })}
              />
            </div>
            <div>
              <label style={label}>Amount (negative = expense)</label>
              <input
                style={input}
                type="number"
                step="any"
                required
                value={form.amount}
                placeholder="-25000"
                onChange={(e) =>
                  setForm({ ...form, amount: e.target.value })
                }
              />
            </div>
            <div>
              <label style={label}>Category</label>
              <input
                style={input}
                value={form.category}
                placeholder="Food & Drinks"
                onChange={(e) =>
                  setForm({ ...form, category: e.target.value })
                }
              />
            </div>
            <div>
              <label style={label}>Merchant / note</label>
              <input
                style={input}
                value={form.merchant}
                placeholder="warung sate"
                onChange={(e) =>
                  setForm({ ...form, merchant: e.target.value })
                }
              />
            </div>
            <div>
              <label style={label}>Account</label>
              <input
                style={input}
                value={form.account}
                onChange={(e) =>
                  setForm({ ...form, account: e.target.value })
                }
              />
            </div>
            <div style={{ display: "flex", alignItems: "flex-end", gap: 8 }}>
              <label style={{ ...label, marginBottom: 10 }}>
                <input
                  type="checkbox"
                  checked={form.is_transfer}
                  onChange={(e) =>
                    setForm({ ...form, is_transfer: e.target.checked })
                  }
                  style={{ marginRight: 6 }}
                />
                Transfer
              </label>
            </div>
          </div>
          <button style={btn} type="submit" disabled={saving}>
            {saving ? "Saving…" : "Add transaction"}
          </button>
        </form>
      </section>

      {/* Recent transactions */}
      <section style={card}>
        <label style={label}>Recent transactions</label>
        <table
          style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}
        >
          <tbody>
            {txs.map((t) => (
              <tr key={t.id} style={{ borderTop: "1px solid #2a2e37" }}>
                <td
                  style={{
                    padding: "8px 4px",
                    color: "#9aa0a6",
                    whiteSpace: "nowrap",
                  }}
                >
                  {t.date.slice(0, 10)}
                </td>
                <td style={{ padding: "8px 4px" }}>
                  {t.category || "—"}
                  {t.is_transfer ? " (transfer)" : ""}
                  {t.merchant ? (
                    <span style={{ color: "#9aa0a6" }}> · {t.merchant}</span>
                  ) : null}
                </td>
                <td
                  style={{
                    padding: "8px 4px",
                    textAlign: "right",
                    color: t.amount < 0 ? "#f87171" : "#4ade80",
                    fontVariantNumeric: "tabular-nums",
                    whiteSpace: "nowrap",
                  }}
                >
                  {fmt(t.amount)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </main>
  );
}
