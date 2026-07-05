"use client";

import { useEffect, useState } from "react";

import { card, input, btn, label } from "../styles";
import CategoryDonut from "./charts/CategoryDonut";
import IncomeExpenseBar from "./charts/IncomeExpenseBar";
import TrendChart from "./charts/TrendChart";

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

type AccountBalance = {
  id: number;
  name: string;
  current_balance: number;
  period_net: number;
};

type TrendPoint = { month: string; income: number; expense: number };

// GET /cashflow/summary (backend/schemas.py:CashflowSummary, D-08). Note:
// by_category rows arrive as [category, total] tuples (spending_by_category's
// existing tools.py shape, not objects) — mapped to {category,total} below
// before being handed to CategoryDonut.
type CashflowSummary = {
  totals: { income: number; expense: number; net: number };
  by_category: [string, number][];
  accounts: AccountBalance[];
  trend: TrendPoint[];
};

type Period = "this_week" | "this_month" | "last_month" | "this_year";

const PERIOD_OPTIONS: { value: Period; label: string }[] = [
  { value: "this_week", label: "This week" },
  { value: "this_month", label: "This month" },
  { value: "last_month", label: "Last month" },
  { value: "this_year", label: "This year" },
];

// ---------------------------------------------------------------------------
// Cashflow page — dashboard (totals, per-account balances, charts, trend)
// plus the interim manual transaction entry + recent transactions list from
// Phase 3. CRUD (edit/delete, account/category management, CSV upload) ships
// in Plan 05, which refactors the entry form into a modal on this same page.
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
  // Dashboard state
  const [period, setPeriod] = useState<Period>("this_month");
  const [summary, setSummary] = useState<CashflowSummary | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);

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

  async function loadSummary(p: Period) {
    try {
      const r = await fetch(`/api/cashflow/summary?period=${p}`);
      if (r.ok) {
        setSummary(await r.json());
        setSummaryError(null);
      } else {
        setSummaryError(
          "Couldn't load the dashboard — check the backend is running and reload the page."
        );
      }
    } catch {
      setSummaryError(
        "Couldn't load the dashboard — check the backend is running and reload the page."
      );
    }
  }

  async function loadTxs() {
    const r = await fetch("/api/transactions?limit=10");
    if (r.ok) setTxs(await r.json());
  }

  useEffect(() => {
    loadTxs();
  }, []);

  useEffect(() => {
    loadSummary(period);
  }, [period]);

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
        loadSummary(period);
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

  const signColor = (n: number) => (n < 0 ? "#f87171" : "#4ade80");

  // ---------------------------------------------------------------------------
  // Derived chart data
  // ---------------------------------------------------------------------------

  const categoryData = (summary?.by_category ?? []).map(([category, total]) => ({
    category,
    total,
  }));
  const incomeExpenseData = summary
    ? [
        {
          label: "This period",
          income: summary.totals.income,
          expense: summary.totals.expense,
        },
      ]
    : [];
  const trendData = summary?.trend ?? [];
  const hasActivity =
    !!summary &&
    (summary.totals.income !== 0 ||
      summary.totals.expense !== 0 ||
      categoryData.length > 0);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <main style={{ maxWidth: 960, margin: "0 auto", padding: "48px 24px" }}>
      {/* Page heading + period selector */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 32,
        }}
      >
        <h1 style={{ fontSize: 28, fontWeight: 600, margin: 0 }}>Cashflow</h1>
        <div style={{ display: "flex", gap: 8 }}>
          {PERIOD_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => setPeriod(opt.value)}
              style={{
                background: period === opt.value ? "#3b82f6" : "transparent",
                color: period === opt.value ? "white" : "#9aa0a6",
                border: "1px solid #2a2e37",
                borderRadius: 999,
                padding: "6px 14px",
                fontSize: 13,
                cursor: "pointer",
              }}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {summaryError && (
        <div style={{ ...card, color: "#f87171" }}>{summaryError}</div>
      )}

      {summary && !summaryError && (
        <>
          {/* Summary row */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(3, 1fr)",
              gap: 16,
              marginBottom: 24,
            }}
          >
            <div style={{ ...card, marginBottom: 0 }}>
              <label style={label}>Total Income</label>
              <div
                style={{ fontSize: 20, fontWeight: 600, color: "#4ade80" }}
              >
                {fmt(summary.totals.income)}
              </div>
            </div>
            <div style={{ ...card, marginBottom: 0 }}>
              <label style={label}>Total Expenses</label>
              <div
                style={{ fontSize: 20, fontWeight: 600, color: "#f87171" }}
              >
                {fmt(-Math.abs(summary.totals.expense))}
              </div>
            </div>
            <div style={{ ...card, marginBottom: 0 }}>
              <label style={label}>Net</label>
              <div
                style={{
                  fontSize: 20,
                  fontWeight: 600,
                  color: signColor(summary.totals.net),
                }}
              >
                {fmt(summary.totals.net)}
              </div>
            </div>
          </div>

          {!hasActivity ? (
            <section style={card}>
              <div style={{ fontSize: 20, fontWeight: 600, marginBottom: 8 }}>
                Nothing here for this period.
              </div>
              <div style={{ color: "#9aa0a6", fontSize: 14 }}>
                Try a different period, or add a transaction to see it
                reflected here.
              </div>
            </section>
          ) : (
            <>
              {/* Per-account balances row */}
              <section style={card}>
                <label style={label}>Accounts</label>
                <table
                  style={{
                    width: "100%",
                    borderCollapse: "collapse",
                    fontSize: 13,
                  }}
                >
                  <thead>
                    <tr>
                      <th style={{ textAlign: "left", padding: "4px 4px" }} />
                      <th
                        style={{
                          textAlign: "right",
                          padding: "4px 4px",
                          color: "#9aa0a6",
                          fontWeight: 400,
                        }}
                      >
                        Balance
                      </th>
                      <th
                        style={{
                          textAlign: "right",
                          padding: "4px 4px",
                          color: "#9aa0a6",
                          fontWeight: 400,
                        }}
                      >
                        This period
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {summary.accounts.map((a) => (
                      <tr key={a.id} style={{ borderTop: "1px solid #2a2e37" }}>
                        <td style={{ padding: "8px 4px" }}>{a.name}</td>
                        <td
                          style={{
                            padding: "8px 4px",
                            textAlign: "right",
                            fontWeight: 600,
                            fontVariantNumeric: "tabular-nums",
                          }}
                        >
                          {fmt(a.current_balance)}
                        </td>
                        <td
                          style={{
                            padding: "8px 4px",
                            textAlign: "right",
                            fontWeight: 600,
                            fontVariantNumeric: "tabular-nums",
                            color: signColor(a.period_net),
                          }}
                        >
                          {fmt(a.period_net)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>

              {/* Charts row */}
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(2, 1fr)",
                  gap: 16,
                  marginBottom: 24,
                }}
              >
                <div style={card}>
                  <label style={label}>Spending by Category</label>
                  <CategoryDonut data={categoryData} />
                </div>
                <div style={card}>
                  <label style={label}>Income vs Expense</label>
                  <IncomeExpenseBar data={incomeExpenseData} />
                </div>
              </div>

              {/* Trend row */}
              <section style={card}>
                <label style={label}>6-Month Trend</label>
                <TrendChart data={trendData} />
              </section>
            </>
          )}
        </>
      )}

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
