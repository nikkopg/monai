"use client";

import { useEffect, useRef, useState } from "react";

import { tokens, card } from "../styles";
import Pills from "../components/Pills";
import RollingNumber from "../components/RollingNumber";
import CategoryDonut from "./charts/CategoryDonut";
import TrendChart, { type ChartPoint } from "./charts/TrendChart";
import NetWorthTrendChart from "./charts/NetWorthTrendChart";
import CsvUpload from "./CsvUpload";
import { fmtRowDate } from "../lib/inbox";
import { fmtAmount, fmtAmountSigned, rateHover } from "../lib/money";
import {
  PERIOD_KINDS,
  changeBadge,
  chartWindows,
  spendBar,
  type Badge,
  type PeriodKind,
} from "./periodCard";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type AccountBalance = {
  id: number;
  name: string;
  type: string;
  // Phase 43 payload: a USD row carries its native balance and rate; current_balance
  // (the IDR value) is null when no rate is within range.
  current_balance: number | null;
  period_net: number | null;
  currency?: string;
  native_balance?: number;
  fx_rate?: number | null;
  fx_as_of?: string | null;
  fx_stale?: boolean;
  fx_note?: string | null;
  period_net_unconverted?: boolean;
};

// GET /cashflow/summary (backend/schemas.py:CashflowSummary, D-08). by_category
// is a hierarchy rollup (CAT-04, 11-07): each top-level group carries its own
// identity color/icon plus a subcategory breakdown under children.
export type CategoryRollupChild = {
  id: number;
  name: string;
  color: string | null;
  icon: string | null;
  total: number;
};
export type CategoryRollup = CategoryRollupChild & {
  children: CategoryRollupChild[];
};
type CashflowSummary = {
  totals: { income: number; expense: number; net: number };
  by_category: CategoryRollup[];
  accounts: AccountBalance[];
  // Phase 43: USD rows with no usable rate are left out of the IDR totals.
  unconverted_count?: number;
  unconverted_usd?: number;
};

// GET /net-worth (backend/schemas.py:NetWorth, phase 15 D-01/D-08). Server-
// computed — liquid = account_balances() filtered to type='liquid', investment
// = portfolio_summary groups. Never re-derived client-side (fixes the old
// client-side double-count over ALL account rows).
type InvestmentGroup = {
  platform_id: number;
  platform_name: string;
  kind: string;
  subtotal: number;
  holdings: unknown[];
};
type NetWorth = {
  total: number;
  liquid_total: number;
  investment_total: number;
  liquid_accounts: AccountBalance[];
  investment_groups: InvestmentGroup[];
  accounts_covered: number;
  accounts_total: number;
  fx_excluded?: { name: string; native_balance: number; currency: string }[];
  notice?: string | null;
  fx_note?: string | null;
};

// ---------------------------------------------------------------------------
// Cashflow page — v1.1 "paper" redesign of the Phase 4 dashboard. Read-only
// dashboards (GET /cashflow/summary + /net-worth) plus management surfaces
// (AccountManager, CsvUpload). Adding/editing/deleting transactions now lives on
// the Records page; every write here still refetches summary + net worth via
// refreshAll (Pattern 5) so nothing needs a reload. The Week / Month / Year
// picker and its ‹ › stepper live in the "Cashflow" card, the only thing
// that follows them: the figures, the change badges and the six-period chart.
// ---------------------------------------------------------------------------

export default function CashflowPage() {
  const [kind, setKind] = useState<PeriodKind>("month");
  const [offset, setOffset] = useState(0);
  const [summary, setSummary] = useState<CashflowSummary | null>(null);
  const [prevTotals, setPrevTotals] = useState<CashflowSummary["totals"] | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  // Out-of-order guard: only the latest request may write state, so a slow
  // earlier period never shows under a later period's label.
  const latest = useRef(0);

  const frame = chartWindows(kind, offset, new Date());
  const win = frame.find((w) => w.offset === offset)!;
  const [chart, setChart] = useState<{ kind: PeriodKind; points: ChartPoint[] } | null>(null);

  // One cached load per selection feeds the figures, the change badges and the
  // six chart bars. The backend returns a full summary per window, so each bar
  // costs one call and the chart reads only its totals. The cache (key
  // "start..end", cleared on refreshAll, failures never kept) keeps a pill
  // switch to at most 7 calls (six frame windows + the same-elapsed comparison
  // window) and a step or bar click inside the frame to none.
  // ponytail: a backend totals-series query would make this one request.
  const cache = useRef(new Map<string, Promise<CashflowSummary | null>>());

  function get(a: string, b: string): Promise<CashflowSummary | null> {
    const key = `${a}..${b}`;
    let p = cache.current.get(key);
    if (!p) {
      p = (async () => {
        try {
          const r = await fetch(`/api/cashflow/summary?period=custom&start_date=${a}&end_date=${b}`);
          return r.ok ? ((await r.json()) as CashflowSummary) : null;
        } catch {
          return null;
        }
      })();
      const mine = p;
      cache.current.set(key, mine);
      mine.then((v) => {
        if (v === null && cache.current.get(key) === mine) cache.current.delete(key);
      });
    }
    return p;
  }

  async function loadSummary(w: typeof frame, sel: number, k: PeriodKind) {
    const id = ++latest.current;
    const cur = w.find((x) => x.offset === sel)!;
    const [prev, ...bodies] = await Promise.all([
      get(cur.prevStart, cur.prevEnd),
      ...w.map((x) => get(x.start, x.end)),
    ]);
    if (id !== latest.current) return;
    // A failed previous-period fetch only hides the badges.
    setPrevTotals(prev?.totals ?? null);
    const body = bodies[w.findIndex((x) => x.offset === sel)];
    // A failed window is never drawn as a zero bar: the chart goes, the figures stay.
    setChart(
      bodies.every(Boolean)
        ? {
            kind: k,
            points: w.map((x, i) => ({
              offset: x.offset,
              title: x.title,
              short: x.short,
              income: bodies[i]!.totals.income,
              expense: bodies[i]!.totals.expense,
            })),
          }
        : null
    );
    if (body) {
      setSummary(body);
      setSummaryError(null);
    } else {
      setSummaryError(
        "Couldn't load the dashboard — check the backend is running and reload the page."
      );
    }
  }

  const [netWorthData, setNetWorthData] = useState<NetWorth | null>(null);
  const [netWorthError, setNetWorthError] = useState<string | null>(null);

  // GET /net-worth — not period-scoped (a point-in-time snapshot), so it's
  // fetched once on mount and refreshed by refreshAll after writes, unlike
  // loadSummary which reruns per selected period.
  async function loadNetWorth() {
    try {
      const r = await fetch("/api/net-worth");
      if (r.ok) {
        setNetWorthData(await r.json());
        setNetWorthError(null);
      } else if (r.status === 422) {
        setNetWorthError(
          "Couldn't verify net worth — some accounts aren't classified as liquid or investment. Check Settings › Accounts."
        );
      } else {
        setNetWorthError(
          "Couldn't load the dashboard — check the backend is running and reload the page."
        );
      }
    } catch {
      setNetWorthError(
        "Couldn't load the dashboard — check the backend is running and reload the page."
      );
    }
  }

  // Refetch the summary and net worth after every write so the dashboard
  // updates with no page reload. (Adding/editing transactions now lives on the
  // Records page; the Cashflow page is read-only dashboards + management cards.)
  async function refreshAll() {
    cache.current.clear();
    await Promise.all([loadSummary(frame, offset, kind), loadNetWorth()]);
  }

  useEffect(() => {
    loadNetWorth();
  }, []);

  useEffect(() => {
    loadSummary(frame, offset, kind);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind, win.start, win.end]);

  // ---- formatting ----------------------------------------------------------
  // Money goes through ../lib/money (fmtAmount / fmtAmountSigned): IDR as plain
  // grouped digits, USD as two decimals plus a code.
  const initials = (name: string) =>
    name
      .split(/\s+/)
      .map((w) => w[0])
      .filter(Boolean)
      .slice(0, 2)
      .join("")
      .toUpperCase();

  // ---- derived -------------------------------------------------------------
  const categoryData = summary?.by_category ?? [];
  const bar = summary ? spendBar(summary.totals.income, summary.totals.expense) : null;
  // Change badge vs the previous period; none while that fetch is missing.
  const badge = (curr: number, prev: number | undefined, goodWhenUp: boolean) =>
    prev === undefined ? null : changeBadge(curr, prev, goodWhenUp, win.prevSpan);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="tab-in" style={{ padding: "28px 44px 44px" }}>
      {/* Header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-end",
          marginBottom: 20,
        }}
      >
        <div>
          <div
            style={{
              fontSize: 12,
              letterSpacing: ".12em",
              textTransform: "uppercase",
              color: tokens.color.muted2,
              marginBottom: 4,
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
      </div>

      {summaryError && (
        <div style={{ ...card, color: tokens.color.terracotta }}>
          {summaryError}
        </div>
      )}

      {summary && !summaryError && (
        <>
          {/* Net worth (with its trend) spans the whole top row. */}
          <div
            style={{
              background: tokens.color.ink,
              color: tokens.color.inkText,
              borderRadius: 18,
              padding: "22px 28px 18px",
              marginBottom: 18,
              display: "flex",
              flexDirection: "column",
            }}
          >
            <NetWorthTrendChart
              hero
              header={
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
              {netWorthError ? (
                <div style={{ fontSize: 14, color: "#e6a99c" }}>
                  {netWorthError}
                </div>
              ) : (
                <div
                  style={{
                    fontFamily: tokens.font.serif,
                    fontSize: 52,
                    lineHeight: 1,
                    letterSpacing: "-1px",
                    fontVariantNumeric: "tabular-nums",
                  }}
                >
                  <RollingNumber value={netWorthData?.total ?? 0} format={(n) => fmtAmount(n, "IDR")} />
                </div>
              )}
              {netWorthData && !netWorthError && (
                <div
                  style={{
                    marginTop: 12,
                    fontSize: 12,
                    color: tokens.color.inkTextMuted,
                    fontVariantNumeric: "tabular-nums",
                  }}
                >
                  Liquid {fmtAmount(netWorthData.liquid_total, "IDR")} ·
                  Investment {fmtAmount(netWorthData.investment_total, "IDR")}
                </div>
              )}
            </div>
              }
            />
          </div>

          {/* Net-worth notice — Phase 43 strings verbatim (D-14) */}
          {netWorthData &&
            !netWorthError &&
            (netWorthData.notice ||
              netWorthData.fx_note ||
              (netWorthData.fx_excluded?.length ?? 0) > 0) && (
              <div style={{ ...notice, marginBottom: 16 }}>
                {netWorthData.notice && (
                  <div style={{ color: tokens.color.terracottaText }}>
                    {netWorthData.notice}
                  </div>
                )}
                {netWorthData.fx_note && (
                  <div style={{ color: tokens.color.muted3 }}>
                    {netWorthData.fx_note}
                  </div>
                )}
                {netWorthData.fx_excluded?.map((e) => (
                  <div key={e.name}>
                    {e.name}: {fmtAmount(e.native_balance, e.currency)}
                  </div>
                ))}
              </div>
            )}

          {/* Unconverted USD rows are left out of the IDR totals below (D-15) */}
          {(summary.unconverted_count ?? 0) > 0 && (
            <div
              style={{
                ...notice,
                marginBottom: 16,
                color: tokens.color.terracottaText,
              }}
            >
              {summary.unconverted_count} USD row
              {summary.unconverted_count === 1 ? "" : "s"} unconverted (
              {fmtAmount(summary.unconverted_usd ?? 0, "USD")})
            </div>
          )}

          {/* Cashflow + liquid accounts + investment platforms.
              Columns in globals.css (.cf-lower): wrapping cards, three
              across on wide windows with the first wider. */}
          <div
            className="cf-lower"
            style={{
              display: "grid",
              gap: 18,
              marginBottom: 18,
              alignItems: "start",
            }}
          >
            <section
              aria-label="Cashflow"
              style={{ ...card, marginBottom: 0 }}
            >
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  flexWrap: "wrap",
                  gap: 8,
                  marginBottom: 12,
                }}
              >
                <div style={{ fontSize: 14, fontWeight: 600 }}>Cashflow</div>
                <Pills
                  small
                  label="Period"
                  options={PERIOD_KINDS}
                  value={kind}
                  onChange={(k) => {
                    setKind(k);
                    setOffset(0);
                  }}
                />
              </div>

              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  background: tokens.color.panel,
                  borderRadius: 12,
                  padding: 6,
                  marginBottom: 12,
                }}
              >
                <button
                  type="button"
                  aria-label={`Previous ${kind}`}
                  onClick={() => setOffset(offset - 1)}
                  style={stepBtn}
                >
                  ‹
                </button>
                <div style={{ textAlign: "center", lineHeight: 1.3 }}>
                  <div style={{ fontSize: 13, fontWeight: 700 }}>{win.title}</div>
                  <div style={{ fontSize: 11, color: tokens.color.muted3 }}>
                    {win.span} · vs {win.prevSpan}
                  </div>
                </div>
                <button
                  type="button"
                  aria-label={`Next ${kind}`}
                  disabled={offset === 0}
                  onClick={() => setOffset(offset + 1)}
                  style={stepBtn}
                >
                  ›
                </button>
              </div>

              {chart ? (
                <div style={{ marginBottom: 10 }}>
                  <TrendChart
                    points={chart.points}
                    selected={offset}
                    onSelect={setOffset}
                    label={`Cash flow by ${chart.kind}`}
                  />
                </div>
              ) : (
                <div style={{ marginBottom: 10, fontSize: 12, color: tokens.color.muted3 }}>
                  Couldn&apos;t load the chart.
                </div>
              )}

              <FigRow
                label="Income"
                badge={badge(summary.totals.income, prevTotals?.income, true)}
                value={<RollingNumber value={summary.totals.income} format={(n) => fmtAmount(n, "IDR")} />}
                color={tokens.color.green}
              />
              <FigRow
                label="Expenses"
                badge={badge(summary.totals.expense, prevTotals?.expense, false)}
                value={<RollingNumber value={summary.totals.expense} format={(n) => fmtAmount(n, "IDR")} />}
                color={tokens.color.terracotta}
              />
              {bar && (
                <>
                  <div
                    role="img"
                    aria-label={`Spent ${bar.spent}% of income`}
                    style={{
                      height: 8,
                      borderRadius: 999,
                      overflow: "hidden",
                      background: tokens.color.borderInner,
                      margin: "10px 0 4px",
                    }}
                  >
                    <div
                      style={{
                        width: `${bar.width}%`,
                        height: "100%",
                        background: tokens.color.terracotta,
                      }}
                    />
                  </div>
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      fontSize: 11,
                      color: tokens.color.muted3,
                    }}
                  >
                    <span>Spent {bar.spent}% of income</span>
                    <span
                      style={
                        bar.spent > 100
                          ? { color: tokens.color.terracottaText }
                          : undefined
                      }
                    >
                      {bar.kept}
                    </span>
                  </div>
                </>
              )}
              <FigRow
                net
                label="Net saved"
                badge={badge(summary.totals.net, prevTotals?.net, true)}
                value={<RollingNumber value={summary.totals.net} format={(n) => fmtAmountSigned(n, "IDR")} />}
                color={tokens.color.ink}
              />

              <div
                style={{
                  height: 1,
                  background: tokens.color.borderInner,
                  margin: "16px 0",
                }}
              />
              <div
                style={{ fontSize: 12, color: tokens.color.muted3, marginBottom: 10 }}
              >
                Where it went
              </div>
              <CategoryDonut
                key={`${kind}:${win.start}`}
                data={categoryData}
              />
            </section>

              <div style={{ ...card, marginBottom: 0 }}>
                <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>
                  Liquid accounts
                </div>
                {(netWorthData?.liquid_accounts.length ?? 0) === 0 ? (
                  <div style={{ paddingTop: 10 }}>
                    <div
                      style={{ fontSize: 16, fontWeight: 600, marginBottom: 6 }}
                    >
                      No liquid accounts yet.
                    </div>
                    <div style={{ color: tokens.color.muted, fontSize: 14 }}>
                      Add one below to start tracking cash balances.
                    </div>
                  </div>
                ) : (
                  netWorthData!.liquid_accounts.map((a) => (
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
                      {(a.currency ?? "IDR") === "IDR" ? (
                        <div style={{ textAlign: "right" }}>
                          <div
                            style={{
                              fontSize: 14,
                              fontWeight: 600,
                              fontVariantNumeric: "tabular-nums",
                              color:
                                (a.current_balance ?? 0) < 0
                                  ? tokens.color.terracotta
                                  : tokens.color.ink,
                            }}
                          >
                            {fmtAmount(a.current_balance, "IDR")}
                          </div>
                        </div>
                      ) : (
                        <div
                          style={{ textAlign: "right" }}
                          title={
                            a.current_balance === null
                              ? undefined
                              : rateHover(a.fx_rate, a.fx_as_of)
                          }
                        >
                          <div
                            style={{
                              fontSize: 14,
                              fontWeight: 600,
                              fontVariantNumeric: "tabular-nums",
                              color:
                                (a.native_balance ?? 0) < 0
                                  ? tokens.color.terracotta
                                  : tokens.color.ink,
                            }}
                          >
                            {fmtAmount(a.native_balance, "USD")}
                          </div>
                          <div
                            style={{
                              marginTop: 4,
                              fontSize: 12,
                              fontWeight: 400,
                              color: tokens.color.muted3,
                              fontVariantNumeric: "tabular-nums",
                            }}
                          >
                            {a.current_balance === null ? (
                              <span style={{ color: tokens.color.terracottaText }}>
                                IDR value unavailable
                              </span>
                            ) : (
                              <>≈ {fmtAmount(a.current_balance, "IDR")}</>
                            )}
                          </div>
                          {a.fx_stale && (
                            <div
                              style={{
                                marginTop: 4,
                                fontSize: 12,
                                color: tokens.color.muted3,
                              }}
                            >
                              stale, rate of {fmtRowDate(a.fx_as_of)}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  ))
                )}
              </div>

              <div style={{ ...card, marginBottom: 0 }}>
                <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>
                  Investment platforms
                </div>
                {(netWorthData?.investment_groups.length ?? 0) === 0 ? (
                  <div style={{ paddingTop: 10 }}>
                    <div
                      style={{ fontSize: 16, fontWeight: 600, marginBottom: 6 }}
                    >
                      No investment platforms yet.
                    </div>
                    <div style={{ color: tokens.color.muted, fontSize: 14 }}>
                      Add a platform and a holding on the Investments page to
                      see it here.
                    </div>
                  </div>
                ) : (
                  netWorthData!.investment_groups.map((g) => (
                    <div
                      key={g.platform_id}
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
                        {initials(g.platform_name)}
                      </span>
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: 14, fontWeight: 500 }}>
                          {g.platform_name}
                        </div>
                      </div>
                      <div
                        style={{
                          fontSize: 14,
                          fontWeight: 600,
                          fontVariantNumeric: "tabular-nums",
                          color: tokens.color.ink,
                        }}
                      >
                        {fmtAmount(g.subtotal, "IDR")}
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
        </>
      )}

      {/* Secondary management surfaces (re-themed in Phase 10). Category AND
          account management now live in Settings (D-16, plan 11-06 + this task). */}
      <CsvUpload onImported={refreshAll} />
    </div>
  );
}

const notice: React.CSSProperties = {
  background: tokens.color.tintWarm,
  borderRadius: tokens.radius.sm,
  padding: "8px 16px",
  fontSize: 12,
  lineHeight: 1.5,
};
const stepBtn: React.CSSProperties = {
  border: "none",
  background: tokens.color.card,
  width: 28,
  height: 28,
  borderRadius: 8,
  color: tokens.color.muted3,
  fontSize: 15,
  cursor: "pointer",
};

const badgeColor = {
  good: tokens.color.green,
  bad: tokens.color.terracottaText,
  flat: tokens.color.muted3,
};

// One Income / Expenses / Net saved line: label word, change badge, amount.
function FigRow({
  label,
  badge,
  value,
  color,
  net = false,
}: {
  label: string;
  badge: Badge | null;
  value: React.ReactNode;
  color: string;
  net?: boolean;
}) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "baseline",
        gap: 8,
        padding: "6px 0",
        fontVariantNumeric: "tabular-nums",
        ...(net
          ? {
              borderTop: `1px solid ${tokens.color.borderInner}`,
              marginTop: 4,
              paddingTop: 10,
            }
          : null),
      }}
    >
      <span
        style={{
          fontSize: 13,
          color: tokens.color.muted3,
          display: "inline-flex",
          alignItems: "center",
          gap: 8,
        }}
      >
        <span>{label}</span>
        {badge && (
          <span
            title={badge.title}
            style={{
              fontSize: 11,
              fontWeight: 600,
              display: "inline-flex",
              alignItems: "center",
              gap: 3,
              color: badgeColor[badge.tone],
            }}
          >
            {badge.dir && (
              <i
                aria-hidden="true"
                style={{
                  width: 0,
                  height: 0,
                  borderLeft: "4px solid transparent",
                  borderRight: "4px solid transparent",
                  [badge.dir === "up" ? "borderBottom" : "borderTop"]:
                    "6px solid currentColor",
                }}
              />
            )}
            {badge.text}
          </span>
        )}
      </span>
      <span style={{ fontSize: net ? 24 : 18, fontWeight: 600, color }}>{value}</span>
    </div>
  );
}
