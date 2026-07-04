"use client";

import { useEffect, useState } from "react";

import { card, input, btn, label } from "../styles";

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

// ---------------------------------------------------------------------------
// Cashflow page — manual transaction entry + recent transactions list.
// Interim content for Phase 3 (full dashboard ships in Phase 4).
// ---------------------------------------------------------------------------

// Format a Date as a `datetime-local`-compatible string using LOCAL wall-clock
// components. Using toISOString() here would emit UTC, which the input then
// re-parses as local time — shifting the value by the user's UTC offset (WR-06).
function toLocalDatetimeInputValue(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(
    d.getHours()
  )}:${pad(d.getMinutes())}`;
}

export default function CashflowPage() {
  // Entry form state
  const [form, setForm] = useState({
    date: toLocalDatetimeInputValue(new Date()),
    amount: "",
    category: "",
    merchant: "",
    account: "Cash",
    notes: "",
    is_transfer: false,
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [txs, setTxs] = useState<Tx[]>([]);

  async function loadTxs() {
    const r = await fetch("/api/transactions?limit=10");
    if (r.ok) setTxs(await r.json());
  }
  useEffect(() => {
    loadTxs();
  }, []);

  // ---------------------------------------------------------------------------
  // Transaction form
  // ---------------------------------------------------------------------------

  async function addTx(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
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
      } else {
        // Surface non-2xx responses instead of silently no-op'ing (WR-05).
        let detail = `HTTP ${r.status}`;
        try {
          const errBody = await r.json();
          detail = errBody?.detail ?? detail;
        } catch {
          // keep the status-based detail
        }
        setError(`Couldn't save transaction: ${detail}`);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Network error");
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
    <main style={{ maxWidth: 760, margin: "0 auto", padding: "48px 24px" }}>
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
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <button style={btn} type="submit" disabled={saving}>
              {saving ? "Saving…" : "Add transaction"}
            </button>
            {error && (
              <span style={{ color: "#f87171", fontSize: 12 }}>{error}</span>
            )}
          </div>
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
