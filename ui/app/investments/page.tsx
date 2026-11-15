"use client";

import { Fragment, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { tokens, card, btnDark, notice } from "../styles";
import { sectionTitle, columnHeader, groupRow } from "./sectionStyles";
import { type Platform } from "./PlatformManager";
import ClosedPositions, { type ClosedPosition } from "./ClosedPositions";
import { extractDetail } from "../lib/api";
import { fmtAmount, fmtUsdPrice, rateHover } from "../lib/money";
import { GOLDS, assetLabel, fmtShort } from "../cashflow/holdings";
import HoldingModal from "./HoldingModal";
import HoldingOverrideModal from "./HoldingOverrideModal";
import PriceOverrideDialog from "./PriceOverrideDialog";
import Pills from "../components/Pills";
import RollingNumber from "../components/RollingNumber";
import Skeleton, { Bone, DrawLine } from "../components/Skeleton";
import RowMenu from "../components/RowMenu";
import StalenessBadge from "./StalenessBadge";
import ValueHistoryChart, { type HistoryPoint } from "./ValueHistoryChart";
import AllocationPieChart, { type AllocationSlice } from "./AllocationPieChart";

// ---------------------------------------------------------------------------
// Investments page — v1.1 "paper" redesign of the keystone portfolio view.
// Same data (GET /api/platforms + /api/investments/summary + /history) and the
// full feature set (price refresh, P&L, allocation asset-type/platform toggle,
// set-price/edit/delete, modals). Layout (quick 261115-bi5): a dark hero that
// holds the value history, Allocation, a rate/stale note strip, and one
// Holdings card (Open/Closed views, grouped by the grouping shared with
// Allocation). The PlatformManager now lives on Settings (#platforms).
// ---------------------------------------------------------------------------

export type PlatformOption = { id: number; name: string; currency?: string };

export type HoldingRow = {
  id: number;
  ticker: string;
  currency?: string | null; // absent means IDR
  asset_type: string | null;
  quantity: number;
  avg_cost: number;
  current_price: number | null;
  current_value: number | null;
  unrealized_pnl: number | null;
  realized_pnl: number;
  // USD positions only (quick 261108-d2c); all null when no USD rate exists.
  usd_avg_cost?: number | null;
  usd_current_price?: number | null;
  usd_current_value?: number | null;
  usd_unrealized_pnl?: number | null;
  usd_rate?: number | null;
  usd_rate_date?: string | null;
  platform_id: number | null;
  coingecko_id?: string | null;
  price_source: string | null;
  price_fetched_at: string | null;
  is_stale: boolean;
};

type Group = {
  platform_id: number | null;
  platform_name: string;
  kind: string | null;
  subtotal: number;
  holdings: HoldingRow[];
};

type GroupBy = "platform" | "asset_type";
const GROUP_OPTIONS: { value: GroupBy; label: string }[] = [
  { value: "platform", label: "Platform" },
  { value: "asset_type", label: "Asset type" },
];
const VIEW_OPTIONS: { value: "open" | "closed"; label: string }[] = [
  { value: "open", label: "Open" },
  { value: "closed", label: "Closed" },
];

// One group row of the Holdings table plus the holding rows under it.
type TableGroup = {
  key: string;
  name: string;
  platformId: number | null; // set only for platform groups (the "Open ›" link)
  subtotal: number;
  rows: { h: HoldingRow; platformName: string }[];
};

function tableGroupsOf(groups: Group[], by: GroupBy): TableGroup[] {
  const platformName = (g: Group) =>
    g.platform_id === null ? "Unassigned" : g.platform_name;
  if (by === "platform") {
    return groups.map((g) => ({
      key: String(g.platform_id),
      name: platformName(g),
      platformId: g.platform_id,
      subtotal: Number(g.subtotal),
      rows: g.holdings.map((h) => ({ h, platformName: platformName(g) })),
    }));
  }
  const byType = new Map<string, TableGroup>();
  for (const g of groups) {
    for (const h of g.holdings) {
      const key = String(h.asset_type);
      const tg = byType.get(key) ?? {
        key,
        name: assetLabel(h.asset_type),
        platformId: null,
        subtotal: 0,
        rows: [],
      };
      // The same IDR figure the row shows; an unpriced row counts 0.
      tg.subtotal += h.current_value ?? 0;
      tg.rows.push({ h, platformName: platformName(g) });
      byType.set(key, tg);
    }
  }
  return Array.from(byType.values()).sort((a, b) => b.subtotal - a.subtotal);
}

type AssetTypeGroup = { asset_type: string | null; total_value: number };

type Summary = {
  groups: Group[];
  asset_type_groups: AssetTypeGroup[];
  total_value: number;
  total_unrealized_pnl: number;
  total_realized_pnl: number;
  as_of: string;
};

const fmtPlain = (n: number) =>
  new Intl.NumberFormat("en-US").format(Math.round(n));
const fmtSigned = (n: number) =>
  new Intl.NumberFormat("en-US", { signDisplay: "always" }).format(
    Math.round(n)
  );
const pct = (n: number, base: number) =>
  base > 0 ? `${n >= 0 ? "+" : ""}${((n / base) * 100).toFixed(1)}%` : "—";

// Green for gains, terracotta for losses (paired with the +/- sign — WCAG 1.4.1).
const pnlColor = (n: number) =>
  n >= 0 ? tokens.color.green : tokens.color.terracotta;

// Quantity precision: up to 8 dp for crypto, 2 for stocks/funds, trim zeros.
function fmtQty(n: number, assetType: string | null): string {
  const dp = assetType === "crypto" ? 8 : 2;
  return n
    .toLocaleString("en-US", { maximumFractionDigits: dp })
    .replace(/\.?0+$/, (m) => (m.includes(".") ? "" : m));
}

// Deterministic badge color per ticker, from the paper categorical palette.
const BADGE_COLORS = ["#d8b26a", "#5a8f73", "#2f6f4f", "#8fae9c", "#b5503f"];
const badgeColor = (t: string) => {
  let h = 0;
  for (let i = 0; i < t.length; i++) h = (h * 31 + t.charCodeAt(i)) >>> 0;
  return BADGE_COLORS[h % BADGE_COLORS.length];
};
// Fills where ink text out-contrasts white.
const BADGE_INK = new Set<string>([tokens.color.gold, tokens.color.sage, tokens.color.sageLight]);

const muted = tokens.color.muted3;

// Hero P&L figure: bold, red-tinted below zero, on-ink green otherwise.
const heroFigure = (n: number): React.CSSProperties => ({
  fontWeight: 600,
  fontVariantNumeric: "tabular-nums",
  color: n < 0 ? "#e6a99c" : tokens.color.chipGreenText,
});

// USD figure on top, the IDR figure in small muted text underneath (copied
// from the platform page, like the other helpers above).
const withIdr = (primary: string, idrText: string, title?: string) => (
  <>
    <span style={{ display: "block" }}>{primary}</span>
    <span style={{ display: "block", fontSize: 12, color: muted }} title={title}>
      {idrText}
    </span>
  </>
);

export default function InvestmentsPage() {
  const router = useRouter();
  const [platforms, setPlatforms] = useState<Platform[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [closed, setClosed] = useState<ClosedPosition[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [history, setHistory] = useState<HistoryPoint[]>([]);
  const [historyRange, setHistoryRange] = useState<"1M" | "3M" | "6M" | "All">(
    "3M"
  );
  // One grouping for the Allocation card and the Holdings table.
  const [groupBy, setGroupBy] = useState<GroupBy>("platform");
  const [view, setView] = useState<"open" | "closed">("open");

  const [showEvent, setShowEvent] = useState(false);
  const [overrideOpen, setOverrideOpen] = useState(false);
  const [editingHolding, setEditingHolding] = useState<HoldingRow | null>(null);
  const [priceHolding, setPriceHolding] = useState<HoldingRow | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [pRes, sRes] = await Promise.all([
        fetch("/api/platforms"),
        fetch("/api/investments/summary"),
      ]);
      if (!pRes.ok || !sRes.ok) throw new Error("fetch failed");
      setPlatforms(await pRes.json());
      setSummary(await sRes.json());
      // Best-effort: a failed closed list leaves it empty, never the page error.
      try {
        const cRes = await fetch("/api/closed-positions");
        setClosed(cRes.ok ? await cRes.json() : []);
      } catch {
        setClosed([]);
      }
    } catch {
      setError(
        "Couldn't load your portfolio — check the backend is running and reload the page."
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const loadHistory = useCallback(async (range: "1M" | "3M" | "6M" | "All") => {
    try {
      const res = await fetch(`/api/investments/history?range=${range}`);
      if (!res.ok) throw new Error("fetch failed");
      const body = await res.json();
      setHistory(body.points ?? []);
    } catch {
      setHistory([]);
    }
  }, []);

  useEffect(() => {
    loadHistory(historyRange);
  }, [loadHistory, historyRange]);

  const refreshPrices = useCallback(async () => {
    setRefreshing(true);
    try {
      await fetch("/api/prices/refresh", { method: "POST" });
    } catch {
      // network error surfaces as unchanged/stale prices below
    } finally {
      await load();
      setRefreshing(false);
    }
  }, [load]);

  const platformOptions: PlatformOption[] = platforms.map((p) => ({
    id: p.id,
    name: p.name,
    currency: p.currency,
  }));

  // Active holdings only (D-04: zero-qty drops off the active list).
  const activeGroups =
    summary?.groups
      .map((g) => ({
        ...g,
        holdings: g.holdings.filter((h) => h.quantity !== 0),
      }))
      .filter((g) => g.holdings.length > 0 || g.platform_id !== null) ?? [];

  const hasAnyHolding = activeGroups.some((g) => g.holdings.length > 0);
  const tableGroups = tableGroupsOf(activeGroups, groupBy);

  // Largest first, like finish(..., GOLDS, true) on the Cashflow Holdings card,
  // so a group gets the same colour on both pages.
  const allocationData: AllocationSlice[] = (
    groupBy === "asset_type"
      ? (summary?.asset_type_groups ?? []).map((g) => ({
          label: assetLabel(g.asset_type),
          value: Number(g.total_value),
        }))
      : activeGroups
          .filter((g) => g.holdings.length > 0)
          .map((g) => ({
            label: g.platform_id === null ? "Unassigned" : g.platform_name,
            value: Number(g.subtotal),
          }))
  ).sort((a, b) => b.value - a.value);

  // Note strip under the top row: the one USD rate (every USD holding carries
  // the same one per summary) and how many held prices are stale.
  const heldRows = activeGroups.flatMap((g) => g.holdings);
  const rated = heldRows.find((h) => h.usd_rate != null);
  const rateText = rated && rateHover(rated.usd_rate, rated.usd_rate_date);
  const staleCount = heldRows.filter((h) => h.is_stale).length;
  const noteParts = [
    rateText && `USD positions converted at ${rateText}`,
    staleCount > 0 &&
      (staleCount === 1 ? "1 price is stale" : `${staleCount} prices are stale`),
  ].filter(Boolean) as string[];

  const costBasis = summary
    ? summary.total_value - summary.total_unrealized_pnl
    : 0;

  return (
    <div className="tab-in inv-page" style={{ padding: "40px 44px 60px" }}>
      <div style={{ marginBottom: 28 }}>
        <div
          style={{
            fontSize: 12,
            letterSpacing: ".12em",
            textTransform: "uppercase",
            color: tokens.color.muted3,
            marginBottom: 6,
          }}
        >
          Portfolio
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
          Investments
        </h1>
      </div>

      {loading ? (
        <Skeleton pulse label="Loading your portfolio">
          <div style={{ display: "flex", flexWrap: "wrap", gap: 18, marginBottom: 18 }}>
            <div
              className="bone-dark"
              style={{
                flex: "2 1 560px",
                minWidth: 0,
                boxSizing: "border-box",
                background: tokens.color.ink,
                borderRadius: 18,
                padding: "22px 28px 18px",
                display: "flex",
                flexDirection: "column",
                gap: 12,
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  <Bone w={80} h={12} />
                  <Bone w={260} h={46} />
                  <Bone w={220} h={12} />
                </div>
                <div style={{ display: "flex", gap: 8 }}>
                  <Bone w={150} h={32} r={999} />
                  <Bone w={96} h={32} r={999} />
                </div>
              </div>
              <DrawLine height={130} />
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <Bone w={170} h={12} />
                <Bone w={110} h={32} r={999} />
              </div>
            </div>
            <div
              style={{
                ...card,
                marginBottom: 0,
                flex: "1 1 280px",
                minWidth: 0,
                boxSizing: "border-box",
                display: "flex",
                flexDirection: "column",
                gap: 14,
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <Bone w={80} h={14} />
                <Bone w={150} h={32} r={999} />
              </div>
              <div
                className="bone"
                style={{
                  width: 170,
                  height: 170,
                  borderRadius: "50%",
                  margin: "6px auto",
                  background: "none",
                  border: `26px solid ${tokens.color.borderInner}`,
                }}
              />
              {[
                [70, 70],
                [90, 60],
                [60, 66],
              ].map(([lw, vw], i) => (
                <div
                  key={i}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 14,
                    padding: "10px 0",
                    borderTop: i === 0 ? "none" : `1px solid ${tokens.color.borderInner}`,
                  }}
                >
                  <Bone w={10} h={10} />
                  <Bone w={lw} h={12} />
                  <div style={{ marginLeft: "auto" }}>
                    <Bone w={vw} h={12} />
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div style={{ marginBottom: 18 }}>
            <Bone w="100%" h={36} r={12} />
          </div>
          <div
            style={{
              ...card,
              marginBottom: 18,
              display: "flex",
              flexDirection: "column",
              gap: 14,
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 10 }}>
              <Bone w={80} h={14} />
              <div style={{ display: "flex", gap: 8 }}>
                <Bone w={120} h={32} r={999} />
                <Bone w={150} h={32} r={999} />
                <Bone w={110} h={32} r={999} />
              </div>
            </div>
            {[0, 1, 2, 3, 4, 5].map((i) =>
              i % 3 === 0 ? (
                <div
                  key={i}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    background: tokens.color.inputBg,
                    padding: "12px 8px",
                    borderRadius: 6,
                  }}
                >
                  <Bone w={70 + i * 6} h={13} />
                  <Bone w={90} h={13} />
                </div>
              ) : (
                <div
                  key={i}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 14,
                    padding: "10px 0",
                    borderTop: `1px solid ${tokens.color.borderInner}`,
                  }}
                >
                  <Bone w={30} h={30} />
                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    <Bone w={60 + i * 9} h={12} />
                    <Bone w={150} h={10} />
                  </div>
                  <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 14 }}>
                    <Bone w={70} h={12} />
                    <Bone w={52} h={12} />
                    <Bone w={18} h={12} />
                  </div>
                </div>
              ),
            )}
          </div>
        </Skeleton>
      ) : error ? (
        <div style={{ ...card, color: tokens.color.terracotta }}>{error}</div>
      ) : (
        summary && (
          <div className="fade-in">
            {/* Hero (total, P&L, history chart, price footer) + Allocation */}
            <div
              style={{
                display: "flex",
                flexWrap: "wrap",
                gap: 18,
                marginBottom: 18,
              }}
            >
              <section
                aria-label="Portfolio value"
                style={{
                  flex: "2 1 560px",
                  minWidth: 0,
                  boxSizing: "border-box",
                  background: tokens.color.ink,
                  color: tokens.color.inkText,
                  borderRadius: 18,
                  padding: "22px 28px 18px",
                  display: "flex",
                  flexDirection: "column",
                }}
              >
                <ValueHistoryChart
                  data={history}
                  range={historyRange}
                  onRangeChange={setHistoryRange}
                  header={
                    <div>
                      <div
                        style={{
                          fontSize: 13,
                          color: tokens.color.inkTextMuted,
                          marginBottom: 10,
                        }}
                      >
                        Total value
                      </div>
                      <div
                        style={{
                          fontFamily: tokens.font.serif,
                          fontSize: "clamp(28px, 8vw, 52px)",
                          lineHeight: 1,
                          letterSpacing: "-1px",
                          fontVariantNumeric: "tabular-nums",
                        }}
                      >
                        <RollingNumber value={summary.total_value} format={fmtPlain} />
                      </div>
                      <div
                        style={{
                          display: "flex",
                          flexWrap: "wrap",
                          gap: 14,
                          marginTop: 8,
                          fontSize: 13,
                          color: tokens.color.inkTextMuted,
                        }}
                      >
                        <span>
                          Unrealized{" "}
                          <b style={heroFigure(summary.total_unrealized_pnl)}>
                            <RollingNumber value={summary.total_unrealized_pnl} format={fmtSigned} />
                          </b>{" "}
                          ({pct(summary.total_unrealized_pnl, costBasis)})
                        </span>
                        <span>
                          Realized{" "}
                          <b style={heroFigure(summary.total_realized_pnl)}>
                            <RollingNumber value={summary.total_realized_pnl} format={fmtSigned} />
                          </b>
                        </span>
                      </div>
                    </div>
                  }
                />
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    paddingTop: 10,
                    fontSize: 12,
                    color: tokens.color.inkTextMuted,
                  }}
                >
                  <span>as of {new Date(summary.as_of).toLocaleString()}</span>
                  <button
                    type="button"
                    onClick={refreshPrices}
                    disabled={refreshing}
                    className="coarse-tap"
                    style={{
                      minHeight: 32,
                      background: "rgba(242,239,232,.1)",
                      color: tokens.color.inkText,
                      border: "none",
                      borderRadius: 999,
                      padding: "5px 12px",
                      fontSize: 12,
                      fontWeight: 600,
                      cursor: refreshing ? "not-allowed" : "pointer",
                    }}
                  >
                    {refreshing ? "Refreshing…" : "Refresh prices"}
                  </button>
                </div>
              </section>

              <section
                aria-labelledby="allocation-title"
                style={{
                  ...card,
                  marginBottom: 0,
                  flex: "1 1 280px",
                  minWidth: 0,
                  boxSizing: "border-box",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    flexWrap: "wrap",
                    gap: 8,
                    marginBottom: 14,
                  }}
                >
                  <h2 id="allocation-title" style={sectionTitle}>
                    Allocation
                  </h2>
                  <Pills
                    small
                    tap
                    label="Allocation grouping"
                    options={GROUP_OPTIONS}
                    value={groupBy}
                    onChange={setGroupBy}
                  />
                </div>
                <div
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    gap: 14,
                  }}
                >
                  <AllocationPieChart data={allocationData} />
                  <div
                    style={{
                      display: "flex",
                      flexDirection: "column",
                      gap: 10,
                    }}
                  >
                    {allocationData.map((s, i) => {
                      const total = allocationData.reduce(
                        (a, b) => a + b.value,
                        0
                      );
                      return (
                        <div
                          key={s.label}
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
                              background: GOLDS[i % GOLDS.length],
                              flexShrink: 0,
                            }}
                          />
                          <span
                            style={{
                              flex: 1,
                              fontWeight: 500,
                              whiteSpace: "nowrap",
                            }}
                          >
                            {s.label}
                          </span>
                          <span style={{ fontVariantNumeric: "tabular-nums" }}>
                            {fmtShort(s.value, "IDR")}
                          </span>
                          <span style={{ color: muted }}>
                            {total > 0
                              ? `${Math.round((s.value / total) * 100)}%`
                              : "—"}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </section>
            </div>

            {noteParts.length > 0 && (
              <div style={{ ...notice, marginBottom: 18, color: tokens.color.muted3 }}>
                {noteParts.join(" · ")}
              </div>
            )}

            {/* Refused delete: viewport-anchored so it's seen from deep in the list */}
            {deleteError && (
              <div
                role="alert"
                style={{
                  ...card,
                  position: "fixed",
                  bottom: 24,
                  left: "50%",
                  transform: "translateX(-50%)",
                  zIndex: 90, // below modals (100) and ConfirmDialog (200)
                  margin: 0,
                  maxWidth: 480,
                  width: "calc(100% - 48px)",
                  display: "flex",
                  alignItems: "flex-start",
                  gap: 12,
                  fontSize: 14,
                  color: tokens.color.terracotta,
                }}
              >
                <span style={{ flex: 1 }}>{deleteError}</span>
                <button
                  type="button"
                  onClick={() => setDeleteError(null)}
                  style={rowAction}
                >
                  Dismiss
                </button>
              </div>
            )}

            {/* One Holdings card: Open / Closed views, grouped by the shared grouping */}
            <section
              className="inv-holdings"
              aria-labelledby="holdings-title"
              style={{ ...card, marginBottom: 18 }}
            >
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  flexWrap: "wrap",
                  gap: 8,
                  marginBottom: 10,
                }}
              >
                <h2 id="holdings-title" style={sectionTitle}>
                  Holdings
                </h2>
                <div
                  style={{
                    display: "flex",
                    flexWrap: "wrap",
                    alignItems: "center",
                    gap: 8,
                  }}
                >
                  <Pills
                    small
                    tap
                    label="Holdings view"
                    options={VIEW_OPTIONS}
                    value={view}
                    onChange={setView}
                  />
                  {/* Closed records carry no asset type, so grouping only applies to Open. */}
                  {view === "open" && (
                    <Pills
                      small
                      tap
                      label="Holdings grouping"
                      options={GROUP_OPTIONS}
                      value={groupBy}
                      onChange={setGroupBy}
                    />
                  )}
                  <button
                    style={btnDark}
                    type="button"
                    onClick={() => setShowEvent(true)}
                  >
                    + Log event
                  </button>
                  <RowMenu
                    label="Holdings options"
                    items={[
                      {
                        label: "Add holding directly",
                        onSelect: () => {
                          setEditingHolding(null);
                          setOverrideOpen(true);
                        },
                      },
                      {
                        label: "Manage platforms",
                        onSelect: () => router.push("/settings#platforms"),
                      },
                    ]}
                  />
                </div>
              </div>

              {view === "closed" ? (
                <ClosedPositions rows={closed} load={load} />
              ) : !hasAnyHolding ? (
                <div>
                  <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 6 }}>
                    No holdings yet.
                  </div>
                  <p style={{ fontSize: 14, color: muted, margin: 0 }}>
                    Log your first buy to start tracking a position, or add a
                    platform in Settings first if you hold assets across more than one app.
                  </p>
                </div>
              ) : (
                <>
                  <div
                    className="inv-head"
                    style={{ display: "flex", ...columnHeader }}
                  >
                    <span style={{ flex: 2 }}>Asset</span>
                    <span className="inv-wide" style={{ flex: 1, textAlign: "right" }}>Units</span>
                    <span className="inv-wide" style={{ flex: 1.2, textAlign: "right" }}>Price</span>
                    <span style={{ flex: 1.2, textAlign: "right" }}>Value</span>
                    <span style={{ flex: 1.2, textAlign: "right" }}>Return</span>
                    <span style={{ flex: 1.4, textAlign: "right" }} />
                  </div>
                  {tableGroups.map((tg) => (
                    <Fragment key={tg.key}>
                      <div
                        style={{
                          display: "flex",
                          alignItems: "center",
                          ...groupRow,
                          padding: "6px 8px",
                          borderTop: `1px solid ${tokens.color.borderInner}`,
                        }}
                      >
                        <span
                          style={{
                            flex: 4.2,
                            minWidth: 0,
                            display: "flex",
                            flexWrap: "wrap",
                            alignItems: "center",
                            columnGap: 8,
                          }}
                        >
                          <span>{tg.name}</span>
                          <span style={{ fontSize: 12, fontWeight: 400, color: muted }}>
                            {tg.rows.length} {tg.rows.length === 1 ? "position" : "positions"}
                          </span>
                          {groupBy === "platform" && tg.platformId !== null && (
                            <Link
                              href={`/investments/${tg.platformId}`}
                              aria-label={`Open ${tg.name}`}
                              className="coarse-tap"
                              style={{
                                minHeight: 32,
                                display: "inline-flex",
                                alignItems: "center",
                                fontSize: 12,
                                fontWeight: 500,
                                color: muted,
                                textDecoration: "none",
                              }}
                            >
                              Open ›
                            </Link>
                          )}
                        </span>
                        <span style={{ flex: 1.2, textAlign: "right", whiteSpace: "nowrap" }}>
                          {fmtPlain(tg.subtotal)}
                        </span>
                        <span className="inv-wide" style={{ flex: 2.6 }} />
                      </div>
                      {tg.rows.map(({ h, platformName }) => {
                      const upnl = h.unrealized_pnl;
                      const basis = h.avg_cost * h.quantity;
                      return (
                        <div
                          key={h.id}
                          className="inv-row"
                          style={{
                            display: "flex",
                            alignItems: "center",
                            fontSize: 14,
                            padding: "13px 0",
                            borderTop: `1px solid ${tokens.color.borderInner}`,
                          }}
                        >
                          <span
                            style={{
                              flex: 2,
                              display: "flex",
                              alignItems: "center",
                              gap: 11,
                              minWidth: 0,
                            }}
                          >
                            <span
                              className="inv-wide"
                              style={{
                                width: 32,
                                height: 32,
                                borderRadius: 9,
                                background: badgeColor(h.ticker),
                                color: BADGE_INK.has(badgeColor(h.ticker)) ? tokens.color.ink : "#fff",
                                display: "inline-flex",
                                alignItems: "center",
                                justifyContent: "center",
                                fontSize: 12,
                                fontWeight: 700,
                                flexShrink: 0,
                              }}
                            >
                              {h.ticker.slice(0, 4)}
                            </span>
                            <span style={{ minWidth: 0 }}>
                              <span
                                style={{
                                  fontWeight: 500,
                                  display: "block",
                                  overflow: "hidden",
                                  textOverflow: "ellipsis",
                                  whiteSpace: "nowrap",
                                }}
                              >
                                {h.ticker}
                              </span>
                              {groupBy === "asset_type" && (
                                <span style={{ display: "block", fontSize: 12, color: muted }}>
                                  {platformName}
                                </span>
                              )}
                              <StalenessBadge
                                fetchedAt={h.price_fetched_at}
                                source={h.price_source}
                                isStale={h.is_stale}
                              />
                              {h.currency === "USD" && h.usd_rate == null && (
                                <span style={{ display: "block", fontSize: 12, color: muted }}>
                                  No USD rate, shown in IDR
                                </span>
                              )}
                            </span>
                          </span>
                          <span
                            className="inv-wide"
                            style={{
                              flex: 1,
                              textAlign: "right",
                              fontVariantNumeric: "tabular-nums",
                              color: tokens.color.muted3,
                            }}
                          >
                            {fmtQty(h.quantity, h.asset_type)}
                          </span>
                          <span
                            className="inv-wide"
                            style={{
                              flex: 1.2,
                              textAlign: "right",
                              fontVariantNumeric: "tabular-nums",
                              color: tokens.color.muted3,
                            }}
                          >
                            {h.usd_current_price != null
                              ? withIdr(
                                  fmtUsdPrice(h.usd_current_price, 8),
                                  `${fmtPlain(h.current_price ?? 0)} IDR`,
                                  rateHover(h.usd_rate, h.usd_rate_date)
                                )
                              : h.current_price != null
                                ? fmtPlain(h.current_price)
                                : "—"}
                          </span>
                          <span
                            style={{
                              flex: 1.2,
                              textAlign: "right",
                              fontVariantNumeric: "tabular-nums",
                              fontWeight: 600,
                            }}
                          >
                            {h.usd_current_value != null
                              ? withIdr(
                                  fmtAmount(h.usd_current_value, "USD"),
                                  `${fmtPlain(h.current_value ?? 0)} IDR`,
                                  rateHover(h.usd_rate, h.usd_rate_date)
                                )
                              : h.current_value != null
                                ? fmtPlain(h.current_value)
                                : "—"}
                          </span>
                          <span
                            style={{
                              flex: 1.2,
                              textAlign: "right",
                              fontVariantNumeric: "tabular-nums",
                              fontWeight: 600,
                              color: upnl != null ? pnlColor(upnl) : muted,
                            }}
                          >
                            {upnl != null && h.usd_unrealized_pnl != null && h.usd_avg_cost != null
                              ? withIdr(
                                  `${pct(h.usd_unrealized_pnl, h.usd_avg_cost * h.quantity)} USD`,
                                  `${pct(upnl, basis)} IDR`
                                )
                              : upnl != null
                                ? pct(upnl, basis)
                                : "—"}
                          </span>
                          <span
                            style={{
                              flex: 1.4,
                              display: "flex",
                              gap: 10,
                              justifyContent: "flex-end",
                              fontSize: 12,
                            }}
                          >
                            <RowMenu
                              label={`Holding options: ${h.ticker}`}
                              items={[
                                { label: "Set price", onSelect: () => setPriceHolding(h) },
                                {
                                  label: "Edit",
                                  onSelect: () => {
                                    setEditingHolding(h);
                                    setOverrideOpen(true);
                                  },
                                },
                                {
                                  label: "Delete",
                                  destructive: true,
                                  onSelect: async () => {
                                    if (
                                      !confirm(
                                        `Delete holding ${h.ticker}? Holdings with buy/sell history can't be deleted — record a sell to close them instead.`
                                      )
                                    )
                                      return;
                                    setDeleteError(null);
                                    try {
                                      const r = await fetch(`/api/holdings/${h.id}`, {
                                        method: "DELETE",
                                      });
                                      if (r.ok) load();
                                      else
                                        setDeleteError(
                                          `Couldn't delete ${h.ticker}: ${await extractDetail(r)}`
                                        );
                                    } catch (e) {
                                      setDeleteError(
                                        `Couldn't delete ${h.ticker}: ${e instanceof Error ? e.message : "Network error"}`
                                      );
                                    }
                                  },
                                },
                              ]}
                            />
                          </span>
                          <span
                            className="inv-sub"
                            style={{
                              flexBasis: "100%",
                              fontSize: 12,
                              color: muted,
                              fontVariantNumeric: "tabular-nums",
                            }}
                          >
                            {`${fmtQty(h.quantity, h.asset_type)} × ${
                              h.usd_current_price != null
                                ? fmtUsdPrice(h.usd_current_price, 8)
                                : h.current_price != null
                                  ? fmtPlain(h.current_price)
                                  : "—"
                            }`}
                          </span>
                        </div>
                      );
                      })}
                    </Fragment>
                  ))}
                </>
              )}
            </section>
          </div>
        )
      )}

      {showEvent && (
        <HoldingModal
          platforms={platformOptions}
          positions={(summary?.groups ?? []).flatMap((g) =>
            g.platform_id === null
              ? []
              : g.holdings.map((h) => ({
                  ticker: h.ticker,
                  platformId: g.platform_id as number,
                  currency: h.currency ?? "IDR",
                  quantity: h.quantity,
                }))
          )}
          onClose={() => setShowEvent(false)}
          onSaved={load}
        />
      )}
      {overrideOpen && (
        <HoldingOverrideModal
          editingHolding={editingHolding}
          platforms={platformOptions}
          onClose={() => setOverrideOpen(false)}
          onSaved={load}
        />
      )}
      {priceHolding && (
        <PriceOverrideDialog
          holding={priceHolding}
          onClose={() => setPriceHolding(null)}
          onSaved={load}
        />
      )}
    </div>
  );
}

const rowAction: React.CSSProperties = {
  background: "transparent",
  color: tokens.color.muted3,
  border: "none",
  cursor: "pointer",
  fontSize: 12,
  padding: 0,
};
