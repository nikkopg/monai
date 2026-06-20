"use client";

import { useEffect, useState } from "react";

type Tx = {
  id: number;
  date: string;
  amount: number;
  category: string | null;
  merchant: string | null;
  is_transfer: boolean;
};

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
const label: React.CSSProperties = { fontSize: 12, color: "#9aa0a6", marginBottom: 4, display: "block" };

export default function Home() {
  // Query state
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [asking, setAsking] = useState(false);

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

  async function ask() {
    if (!question.trim()) return;
    setAsking(true);
    setAnswer("");
    try {
      const r = await fetch("/api/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });
      const d = await r.json();
      setAnswer(r.ok ? d.answer : `Error: ${d.detail || r.statusText}`);
    } catch (e: any) {
      setAnswer(`Error: ${e.message}`);
    } finally {
      setAsking(false);
    }
  }

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

  return (
    <main style={{ maxWidth: 760, margin: "0 auto", padding: "40px 20px" }}>
      <h1 style={{ fontSize: 28, marginBottom: 4 }}>monai</h1>
      <p style={{ color: "#9aa0a6", marginTop: 0, marginBottom: 28 }}>
        personal wealth intelligence
      </p>

      {/* Ask */}
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
      </section>

      {/* Add transaction */}
      <section style={card}>
        <label style={label}>Log a transaction</label>
        <form onSubmit={addTx}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 10 }}>
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
                onChange={(e) => setForm({ ...form, amount: e.target.value })}
              />
            </div>
            <div>
              <label style={label}>Category</label>
              <input style={input} value={form.category} placeholder="Food & Drinks" onChange={(e) => setForm({ ...form, category: e.target.value })} />
            </div>
            <div>
              <label style={label}>Merchant / note</label>
              <input style={input} value={form.merchant} placeholder="warung sate" onChange={(e) => setForm({ ...form, merchant: e.target.value })} />
            </div>
            <div>
              <label style={label}>Account</label>
              <input style={input} value={form.account} onChange={(e) => setForm({ ...form, account: e.target.value })} />
            </div>
            <div style={{ display: "flex", alignItems: "flex-end", gap: 8 }}>
              <label style={{ ...label, marginBottom: 10 }}>
                <input
                  type="checkbox"
                  checked={form.is_transfer}
                  onChange={(e) => setForm({ ...form, is_transfer: e.target.checked })}
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

      {/* Recent */}
      <section style={card}>
        <label style={label}>Recent transactions</label>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <tbody>
            {txs.map((t) => (
              <tr key={t.id} style={{ borderTop: "1px solid #2a2e37" }}>
                <td style={{ padding: "8px 4px", color: "#9aa0a6", whiteSpace: "nowrap" }}>
                  {t.date.slice(0, 10)}
                </td>
                <td style={{ padding: "8px 4px" }}>
                  {t.category || "—"}
                  {t.is_transfer ? " (transfer)" : ""}
                  {t.merchant ? <span style={{ color: "#9aa0a6" }}> · {t.merchant}</span> : null}
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
