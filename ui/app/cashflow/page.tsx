"use client";

import { useEffect, useState } from "react";

import { tokens, card, btnDark } from "../styles";
import CategoryDonut from "./charts/CategoryDonut";
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

// GET /cashflow/summary (backend/schemas.py:CashflowSummary, D-08). by_category
// rows arrive as [category, total] tuples — mapped to {category,total} below.
type CashflowSummary = {
  totals: { income: number; expense: number; net: number };
  by_category: [string, number][];
  accounts: AccountBalance[];
  trend: TrendPoint[];
};

type Period = "this_week" | "this_month" | "last_month" | "this_year";

const PERIOD_OPTIONS: { value: Period; label: string; phrase: string }[] = [
  { value: "this_week", label: "Week", phrase: "this week" },
  { value: "this_month", label: "Month", phrase: "this month" },
  { value: "last_month", label: "Last", phrase: "last month" },
  { value: "this_year", label: "Year", phrase: "this year" },
];

// ---------------------------------------------------------------------------
// Cashflow page — v1.1 "paper" redesign of the Phase 4 dashboard. Same data
// (GET /cashflow/summary + /transactions) and same full CRUD (TransactionModal,
// ConfirmDialog, AccountManager, CategoryManager, CsvUpload); every write still
// refetches list + summary via refreshAll (Pattern 5) so nothing needs a reload.
// ---------------------------------------------------------------------------

export default function CashflowPage() {
  const [period, setPeriod] = useState<Period>("this_month");
  const [summary, setSummary] = useState<CashflowSummary | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);

  const [txs, setTxs] = useState<Tx[]>([]);

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
  // the recent-transactions list AND the dashboard update with no page reload.
  async function refreshAll() {
    await Promise.all([loadTxs(), loadSummary(period)]);
  }

  useEffect(() => {
    loadTxs();
  }, []);

  useEffect(() => {
    loadSummary(period);
  }, [period]);

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
        setDeleteError(
          `Couldn't save transaction: ${detail}. Nothing was changed.`
        );
      }
    } catch (e) {
      setDeleteError(
        `Couldn't save transaction: ${
          e instanceof Error ? e.message : "Network error"
        }. Nothing was changed.`
      );
    }
  }

  // ---- formatting ----------------------------------------------------------
  // Data is IDR (single-currency); no currency symbol is invented — plain
  // grouped digits, matching v1.0. `signed` adds an explicit +/- for deltas.
  const money = (n: number) =>
    new Intl.NumberFormat("en-US").format(Math.round(n));
  const signed = (n: number) =>
    new Intl.NumberFormat("en-US", { signDisplay: "always" }).format(
      Math.round(n)
    );
  const initials = (name: string) =>
    name
      .split(/\s+/)
      .map((w) => w[0])
      .filter(Boolean)
      .slice(0, 2)
      .join("")
      .toUpperCase();

  // ---- derived -------------------------------------------------------------
  const categoryData = (summary?.by_category ?? []).map(([category, total]) => ({
    category,
    total,
  }));
  const trendData = summary?.trend ?? [];
  const hasActivity =
    !!summary &&
    (summary.totals.income !== 0 ||
      summary.totals.expense !== 0 ||
      categoryData.length > 0);
  const netWorth = (summary?.accounts ?? []).reduce(
    (s, a) => s + a.current_balance,
    0
  );
  const netWorthDelta = (summary?.accounts ?? []).reduce(
    (s, a) => s + a.period_net,
    0
  );
  const periodPhrase =
    PERIOD_OPTIONS.find((o) => o.value === period)?.phrase ?? "this period";

  const catColor = (i: number) =>
    ["#2f6f4f", "#5a8f73", "#d8b26a", "#8fae9c", "#b5503f", "#c8c1b5"][i % 6];

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="tab-in" style={{ padding: "40px 44px 60px" }}>
      {/* Header + period control */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-end",
          marginBottom: 30,
        }}
      >
        <div>
          <div
            style={{
              fontSize: 12,
              letterSpacing: ".12em",
              textTransform: "uppercase",
              color: tokens.color.muted2,
              marginBottom: 6,
            }}
          >
            Overview
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
            Cashflow
          </h1>
        </div>
        <div
          style={{
            display: "flex",
            gap: 6,
            background: "#efece4",
            border: `1px solid ${tokens.color.border2}`,
            borderRadius: 999,
            padding: 4,
          }}
        >
          {PERIOD_OPTIONS.map((opt) => {
            const active = period === opt.value;
            return (
              <button
                key={opt.value}
                type="button"
                onClick={() => setPeriod(opt.value)}
                style={{
                  border: "none",
                  borderRadius: 999,
                  padding: "7px 15px",
                  fontSize: 13,
                  fontWeight: active ? 600 : 500,
                  cursor: "pointer",
                  color: active ? tokens.color.inkText : tokens.color.muted,
                  background: active ? tokens.color.ink : "transparent",
                  transition: "all .2s ease",
                }}
              >
                {opt.label}
              </button>
            );
          })}
        </div>
      </div>

      {summaryError && (
        <div style={{ ...card, color: tokens.color.terracotta }}>
          {summaryError}
        </div>
      )}

      {summary && !summaryError && (
        <>
          {/* Hero: net worth + trend */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns:
                "repeat(auto-fit, minmax(min(100%, 320px), 1fr))",
              gap: 18,
              marginBottom: 18,
            }}
          >
            <div
              style={{
                background: tokens.color.ink,
                color: tokens.color.inkText,
                borderRadius: 18,
                padding: "26px 28px",
                display: "flex",
                flexDirection: "column",
                justifyContent: "space-between",
              }}
            >
              <div>
                <div
                  style={{
                    fontSize: 13,
                    color: tokens.color.inkTextMuted,
                    marginBottom: 10,
                  }}
                >
                  Net worth
                </div>
                <div
                  style={{
                    fontFamily: tokens.font.serif,
                    fontSize: 52,
                    lineHeight: 1,
                    letterSpacing: "-1px",
                    fontVariantNumeric: "tabular-nums",
                  }}
                >
                  {money(netWorth)}
                </div>
              </div>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  marginTop: 22,
                }}
              >
                <span
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 5,
                    background: tokens.color.chipGreenBg,
                    color:
                      netWorthDelta < 0
                        ? "#e6a99c"
                        : tokens.color.chipGreenText,
                    fontSize: 13,
                    fontWeight: 600,
                    padding: "4px 10px",
                    borderRadius: 999,
                    fontVariantNumeric: "tabular-nums",
                  }}
                >
                  {netWorthDelta < 0 ? "▼" : "▲"} {signed(netWorthDelta)}
                </span>
                <span
                  style={{ fontSize: 13, color: tokens.color.inkTextMuted }}
                >
                  {periodPhrase}
                </span>
              </div>
            </div>

            <div
              style={{
                background: tokens.color.card,
                border: `1px solid ${tokens.color.border}`,
                borderRadius: 18,
                padding: "22px 24px",
              }}
            >
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  marginBottom: 6,
                }}
              >
                <div style={{ fontSize: 14, fontWeight: 600 }}>
                  6-month trend
                </div>
                <div
                  style={{
                    display: "flex",
                    gap: 16,
                    fontSize: 12,
                    color: tokens.color.muted,
                  }}
                >
                  <span
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 6,
                    }}
                  >
                    <span
                      style={{
                        width: 14,
                        height: 2,
                        background: tokens.color.green,
                        display: "inline-block",
                      }}
                    />
                    Income
                  </span>
                  <span
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 6,
                    }}
                  >
                    <span
                      style={{
                        width: 14,
                        height: 0,
                        borderTop: `2px dashed ${tokens.color.terracotta}`,
                        display: "inline-block",
                      }}
                    />
                    Expenses
                  </span>
                </div>
              </div>
              <TrendChart data={trendData} />
            </div>
          </div>

          {/* Stat cards */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns:
                "repeat(auto-fit, minmax(min(100%, 200px), 1fr))",
              gap: 18,
              marginBottom: 18,
            }}
          >
            <div style={statCard}>
              <div style={statLabel}>Income</div>
              <div style={{ ...statValue, color: tokens.color.green }}>
                {money(summary.totals.income)}
              </div>
            </div>
            <div style={statCard}>
              <div style={statLabel}>Expenses</div>
              <div style={{ ...statValue, color: tokens.color.terracotta }}>
                {money(summary.totals.expense)}
              </div>
            </div>
            <div style={statCard}>
              <div style={statLabel}>Net saved</div>
              <div style={{ ...statValue, color: tokens.color.ink }}>
                {signed(summary.totals.net)}
              </div>
            </div>
          </div>

          {hasActivity && (
            /* Category + accounts */
            <div
              style={{
                display: "grid",
                gridTemplateColumns:
                  "repeat(auto-fit, minmax(min(100%, 300px), 1fr))",
                gap: 18,
                marginBottom: 18,
              }}
            >
              <div style={{ ...card, marginBottom: 0 }}>
                <div
                  style={{ fontSize: 14, fontWeight: 600, marginBottom: 14 }}
                >
                  Spending by category
                </div>
                <div
                  style={{ display: "flex", alignItems: "center", gap: 22 }}
                >
                  <CategoryDonut data={categoryData} />
                  <div
                    style={{
                      flex: 1,
                      display: "flex",
                      flexDirection: "column",
                      gap: 9,
                    }}
                  >
                    {categoryData.map((c, i) => (
                      <div
                        key={c.category}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 10,
                          fontSize: 13,
                        }}
                      >
                        <span
                          style={{
                            width: 9,
                            height: 9,
                            borderRadius: 3,
                            background: catColor(i),
                            flexShrink: 0,
                          }}
                        />
                        <span style={{ flex: 1 }}>{c.category || "—"}</span>
                        <span
                          style={{
                            color: tokens.color.muted,
                            fontVariantNumeric: "tabular-nums",
                          }}
                        >
                          {money(c.total)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              <div style={{ ...card, marginBottom: 0 }}>
                <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>
                  Accounts
                </div>
                {summary.accounts.map((a) => (
                  <div
                    key={a.id}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 12,
                      padding: "11px 0",
                      borderTop: `1px solid ${tokens.color.borderInner}`,
                    }}
                  >
                    <span
                      style={{
                        width: 34,
                        height: 34,
                        borderRadius: 10,
                        background: tokens.color.sidebar,
                        display: "inline-flex",
                        alignItems: "center",
                        justifyContent: "center",
                        fontSize: 13,
                        fontWeight: 600,
                        color: tokens.color.muted3,
                      }}
                    >
                      {initials(a.name)}
                    </span>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 14, fontWeight: 500 }}>
                        {a.name}
                      </div>
                    </div>
                    <div style={{ textAlign: "right" }}>
                      <div
                        style={{
                          fontSize: 14,
                          fontWeight: 600,
                          fontVariantNumeric: "tabular-nums",
                          color:
                            a.current_balance < 0
                              ? tokens.color.terracotta
                              : tokens.color.ink,
                        }}
                      >
                        {money(a.current_balance)}
                      </div>
                      <div
                        style={{
                          fontSize: 12,
                          fontVariantNumeric: "tabular-nums",
                          color:
                            a.period_net < 0
                              ? tokens.color.terracotta
                              : tokens.color.green,
                        }}
                      >
                        {signed(a.period_net)}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}

      {/* Recent transactions */}
      <div style={{ ...card, marginBottom: 18 }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: 6,
          }}
        >
          <div style={{ fontSize: 14, fontWeight: 600 }}>
            Recent transactions
          </div>
          <button
            type="button"
            style={btnDark}
            onClick={() => {
              setEditingTx(null);
              setModalOpen(true);
            }}
          >
            + Add transaction
          </button>
        </div>

        {txs.length === 0 ? (
          <div style={{ paddingTop: 10 }}>
            <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 6 }}>
              No transactions yet.
            </div>
            <div style={{ color: tokens.color.muted, fontSize: 14 }}>
              Add your first transaction above, or upload a Wallet CSV export to
              get started.
            </div>
          </div>
        ) : (
          txs.map((t) => {
            const isIncome = t.amount >= 0 && !t.is_transfer;
            const tint = t.is_transfer
              ? tokens.color.tintNeutral
              : isIncome
              ? tokens.color.tintGreen
              : tokens.color.tintWarm;
            return (
              <div
                key={t.id}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 14,
                  padding: "12px 0",
                  borderTop: `1px solid ${tokens.color.borderInner}`,
                }}
              >
                <span
                  style={{
                    width: 38,
                    height: 38,
                    borderRadius: 11,
                    background: tint,
                    display: "inline-flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: 13,
                    fontWeight: 600,
                    color: tokens.color.muted3,
                    flexShrink: 0,
                  }}
                >
                  {(t.category || t.merchant || "?").slice(0, 1).toUpperCase()}
                </span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div
                    style={{
                      fontSize: 14,
                      fontWeight: 500,
                      whiteSpace: "nowrap",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                    }}
                  >
                    {t.merchant || t.category || "Transaction"}
                  </div>
                  <div style={{ fontSize: 12, color: tokens.color.muted2 }}>
                    {(t.category || "Uncategorized") +
                      (t.is_transfer ? " · transfer" : "")}{" "}
                    · {t.date.slice(0, 10)}
                  </div>
                </div>
                <div
                  style={{
                    fontSize: 14,
                    fontWeight: 600,
                    fontVariantNumeric: "tabular-nums",
                    color:
                      t.amount < 0
                        ? tokens.color.terracotta
                        : tokens.color.green,
                    whiteSpace: "nowrap",
                  }}
                >
                  {signed(t.amount)}
                </div>
                <div style={{ display: "flex", gap: 12, flexShrink: 0 }}>
                  <span
                    role="button"
                    onClick={() => {
                      setEditingTx(t);
                      setModalOpen(true);
                    }}
                    style={{
                      color: tokens.color.muted2,
                      cursor: "pointer",
                      fontSize: 12,
                    }}
                  >
                    Edit
                  </span>
                  <span
                    role="button"
                    onClick={() => setDeletingTx(t)}
                    style={{
                      color: tokens.color.terracotta,
                      cursor: "pointer",
                      fontSize: 12,
                    }}
                  >
                    Delete
                  </span>
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Secondary management surfaces (re-themed in Phase 10) */}
      <AccountManager accounts={summary?.accounts ?? []} onChanged={refreshAll} />
      <CategoryManager onChanged={refreshAll} />
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
        <div
          style={{ color: tokens.color.terracotta, fontSize: 12, marginTop: 8 }}
        >
          {deleteError}
        </div>
      )}
    </div>
  );
}

const statCard: React.CSSProperties = {
  background: tokens.color.card,
  border: `1px solid ${tokens.color.border}`,
  borderRadius: 16,
  padding: "20px 22px",
};
const statLabel: React.CSSProperties = {
  fontSize: 13,
  color: tokens.color.muted,
  marginBottom: 8,
};
const statValue: React.CSSProperties = {
  fontSize: 28,
  fontWeight: 600,
  fontVariantNumeric: "tabular-nums",
};
