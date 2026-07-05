"use client";

import { useEffect, useState } from "react";

import { card, btn, label } from "../styles";
import CategoryDonut from "./charts/CategoryDonut";
import IncomeExpenseBar from "./charts/IncomeExpenseBar";
import TrendChart from "./charts/TrendChart";
import TransactionModal, { type Tx as ModalTx } from "./TransactionModal";
import ConfirmDialog from "./ConfirmDialog";
import AccountManager from "./AccountManager";
import CategoryManager from "./CategoryManager";
import CsvUpload from "./CsvUpload";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Tx = {
  id: number;
  date: string;
  amount: number;
  category: string | null;
  merchant: string | null;
  account_id: number | null;
  notes: string | null;
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
// plus full CRUD (Plan 05): TransactionModal (create/edit), ConfirmDialog
// (destructive confirmations), AccountManager, CategoryManager, and
// CsvUpload. Every write refetches both the transactions list and the
// summary (refreshAll, Pattern 5) so nothing requires a page reload.
// ---------------------------------------------------------------------------

export default function CashflowPage() {
  // Dashboard state
  const [period, setPeriod] = useState<Period>("this_month");
  const [summary, setSummary] = useState<CashflowSummary | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);

  const [txs, setTxs] = useState<Tx[]>([]);

  // Transaction modal (create/edit, D-10) + delete confirm state
  const [modalOpen, setModalOpen] = useState(false);
  const [editingTx, setEditingTx] = useState<ModalTx | null>(null);
  const [deletingTx, setDeletingTx] = useState<Tx | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

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

  // Refetch BOTH the transactions list and the summary after every write, so
  // the recent-transactions list AND the dashboard totals/per-account
  // balances update immediately with no page reload (Pattern 5, D-08).
  async function refreshAll() {
    await Promise.all([loadTxs(), loadSummary(period)]);
  }

  useEffect(() => {
    loadTxs();
  }, []);

  useEffect(() => {
    loadSummary(period);
  }, [period]);

  // ---------------------------------------------------------------------------
  // Transaction delete
  // ---------------------------------------------------------------------------

  async function confirmDeleteTx() {
    if (!deletingTx) return;
    setDeleteError(null);
    try {
      const r = await fetch(`/api/transactions/${deletingTx.id}`, {
        method: "DELETE",
      });
      if (r.ok) {
        setDeletingTx(null);
        await refreshAll();
      } else {
        let detail = `HTTP ${r.status}`;
        try {
          const errBody = await r.json();
          detail = errBody?.detail ?? detail;
        } catch {
          // keep the status-based detail
        }
        setDeleteError(`Couldn't save transaction: ${detail}. Nothing was changed.`);
      }
    } catch (e) {
      setDeleteError(
        `Couldn't save transaction: ${
          e instanceof Error ? e.message : "Network error"
        }. Nothing was changed.`
      );
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

      {/* Recent transactions */}
      <section style={card}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: 8,
          }}
        >
          <label style={{ ...label, marginBottom: 0 }}>Recent transactions</label>
          <button
            type="button"
            style={{ ...btn, padding: "4px 12px", fontSize: 12 }}
            onClick={() => {
              setEditingTx(null);
              setModalOpen(true);
            }}
          >
            Add transaction
          </button>
        </div>

        {txs.length === 0 ? (
          <div>
            <div style={{ fontSize: 20, fontWeight: 600, marginBottom: 8 }}>
              No transactions yet.
            </div>
            <div style={{ color: "#9aa0a6", fontSize: 14 }}>
              Add your first transaction above, or upload a Wallet CSV export
              to get started.
            </div>
          </div>
        ) : (
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
                  <td
                    style={{
                      padding: "8px 4px",
                      textAlign: "right",
                      whiteSpace: "nowrap",
                    }}
                  >
                    <span
                      role="button"
                      onClick={() => {
                        setEditingTx(t);
                        setModalOpen(true);
                      }}
                      style={{
                        color: "#9aa0a6",
                        cursor: "pointer",
                        marginRight: 12,
                        fontSize: 12,
                      }}
                    >
                      Edit
                    </span>
                    <span
                      role="button"
                      onClick={() => setDeletingTx(t)}
                      style={{ color: "#f87171", cursor: "pointer", fontSize: 12 }}
                    >
                      Delete
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {/* Account manager */}
      <AccountManager
        accounts={summary?.accounts ?? []}
        onChanged={refreshAll}
      />

      {/* Category manager */}
      <CategoryManager onChanged={refreshAll} />

      {/* CSV upload — last section per UI-SPEC page structure */}
      <CsvUpload onImported={refreshAll} />

      {modalOpen && (
        <TransactionModal
          editingTx={editingTx}
          accounts={summary?.accounts ?? []}
          onClose={() => {
            setModalOpen(false);
            setEditingTx(null);
          }}
          onSaved={refreshAll}
        />
      )}

      {deletingTx && (
        <ConfirmDialog
          message="Delete this transaction? This can't be undone."
          confirmLabel="Delete"
          onCancel={() => setDeletingTx(null)}
          onConfirm={confirmDeleteTx}
        />
      )}
      {deleteError && (
        <div style={{ color: "#f87171", fontSize: 12, marginTop: 8 }}>
          {deleteError}
        </div>
      )}
    </main>
  );
}
