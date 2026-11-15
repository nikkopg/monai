"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

import { tokens, card, btn, btnDark, chartColors, notice } from "../styles";
import { sectionTitle, columnHeader } from "./sectionStyles";
import PlatformManager, { type Platform } from "./PlatformManager";
import ClosedPositions, { type ClosedPosition } from "./ClosedPositions";
import { extractDetail } from "../lib/api";
import { fmtAmount, fmtUsdPrice, rateHover } from "../lib/money";
import { assetLabel } from "../cashflow/holdings";
import HoldingModal from "./HoldingModal";
import HoldingOverrideModal from "./HoldingOverrideModal";
import PriceOverrideDialog from "./PriceOverrideDialog";
import RowMenu from "../components/RowMenu";
import StalenessBadge from "./StalenessBadge";
import ValueHistoryChart, { type HistoryPoint } from "./ValueHistoryChart";
import AllocationPieChart, { type AllocationSlice } from "./AllocationPieChart";

// ---------------------------------------------------------------------------
// Investments page — v1.1 "paper" redesign of the keystone portfolio view.
// Same data (GET /api/platforms + /api/investments/summary + /history) and the
// full feature set (price refresh, P&L, allocation asset-type/platform toggle,
// value history, platform-grouped holdings, set-price/edit/delete, modals,
// PlatformManager). Only presentation changed.
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
  const [allocationGroupBy, setAllocationGroupBy] = useState<
    "asset_type" | "platform"
  >("asset_type");

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

  const allocationData: AllocationSlice[] =
    allocationGroupBy === "asset_type"
      ? (summary?.asset_type_groups ?? []).map((g) => ({
          label: assetLabel(g.asset_type),
          value: Number(g.total_value),
        }))
      : activeGroups
          .filter((g) => g.holdings.length > 0)
          .map((g) => ({
            label: g.platform_id === null ? "Unassigned" : g.platform_name,
            value: Number(g.subtotal),
          }));

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
        <div style={card}>
          <p style={{ color: muted, fontSize: 14, margin: 0 }}>
            Loading your portfolio…
          </p>
        </div>
      ) : error ? (
        <div style={{ ...card, color: tokens.color.terracotta }}>{error}</div>
      ) : (
        summary && (
          <>
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
                        {fmtPlain(summary.total_value)}
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
                            {fmtSigned(summary.total_unrealized_pnl)}
                          </b>{" "}
                          ({pct(summary.total_unrealized_pnl, costBasis)})
                        </span>
                        <span>
                          Realized{" "}
                          <b style={heroFigure(summary.total_realized_pnl)}>
                            {fmtSigned(summary.total_realized_pnl)}
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
                  <div
                    style={{
                      display: "flex",
                      gap: 4,
                      background: "#efece4",
                      border: `1px solid ${tokens.color.border2}`,
                      borderRadius: 999,
                      padding: 3,
                    }}
                  >
                    {(
                      [
                        { key: "asset_type", label: "Asset type" },
                        { key: "platform", label: "Platform" },
                      ] as const
                    ).map((opt) => {
                      const active = allocationGroupBy === opt.key;
                      return (
                        <button
                          key={opt.key}
                          type="button"
                          onClick={() => setAllocationGroupBy(opt.key)}
                          className="coarse-tap"
                          style={{
                            minHeight: 32,
                            padding: "5px 12px",
                            borderRadius: 999,
                            fontSize: 12,
                            fontWeight: active ? 600 : 500,
                            border: "none",
                            cursor: "pointer",
                            background: active ? tokens.color.ink : "transparent",
                            color: active
                              ? tokens.color.inkText
                              : tokens.color.muted3,
                          }}
                        >
                          {opt.label}
                        </button>
                      );
                    })}
                  </div>
                </div>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    flexWrap: "wrap",
                    gap: 22,
                  }}
                >
                  <div style={{ flex: "1 1 160px", minWidth: 0 }}>
                    <AllocationPieChart data={allocationData} />
                  </div>
                  <div
                    style={{
                      flex: "0 0 auto",
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
                              background: chartColors[i % chartColors.length],
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

            {/* CTAs */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 14,
                marginBottom: 18,
              }}
            >
              <button style={btnDark} type="button" onClick={() => setShowEvent(true)}>
                + Log event
              </button>
              <button
                type="button"
                onClick={() => {
                  setEditingHolding(null);
                  setOverrideOpen(true);
                }}
                className="coarse-tap"
                style={{
                  minHeight: 32,
                  background: "transparent",
                  color: muted,
                  border: "none",
                  fontSize: 13,
                  cursor: "pointer",
                  textDecoration: "underline",
                  padding: 0,
                }}
              >
                Add holding directly
              </button>
            </div>

            {!hasAnyHolding && (
              <div style={card}>
                <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 6 }}>
                  No holdings yet.
                </div>
                <p style={{ fontSize: 14, color: muted, margin: 0 }}>
                  Log your first buy to start tracking a position, or add a
                  platform first if you hold assets across more than one app.
                </p>
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

            {/* Platform-grouped holdings */}
            {activeGroups.map((g) => {
              const isUnassigned = g.platform_id === null;
              return (
                <div key={String(g.platform_id)} style={{ ...card, marginBottom: 18 }}>
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "baseline",
                      marginBottom: 8,
                    }}
                  >
                    <div>
                      {isUnassigned ? (
                        <span
                          style={{
                            fontSize: 14,
                            fontWeight: 600,
                            color: muted,
                          }}
                        >
                          Unassigned
                        </span>
                      ) : (
                        <Link
                          href={`/investments/${g.platform_id}`}
                          className="coarse-tap"
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            minHeight: 32,
                            fontSize: 14,
                            fontWeight: 600,
                            color: tokens.color.ink,
                            cursor: "pointer",
                            textDecoration: "none",
                          }}
                          onMouseEnter={(e) =>
                            (e.currentTarget.style.textDecoration = "underline")
                          }
                          onMouseLeave={(e) =>
                            (e.currentTarget.style.textDecoration = "none")
                          }
                        >
                          {g.platform_name}
                        </Link>
                      )}
                      {g.kind && (
                        <span
                          style={{ fontSize: 12, color: muted, marginLeft: 8 }}
                        >
                          {g.kind}
                        </span>
                      )}
                    </div>
                    <span
                      style={{
                        fontSize: 14,
                        fontWeight: 600,
                        fontVariantNumeric: "tabular-nums",
                      }}
                    >
                      {fmtPlain(g.subtotal)}
                    </span>
                  </div>

                  {g.holdings.length === 0 ? (
                    <p style={{ fontSize: 14, color: muted, margin: 0 }}>
                      No holdings in this platform yet.
                    </p>
                  ) : (
                    <>
                      <div
                        className="inv-wide"
                        style={{ display: "flex", ...columnHeader }}
                      >
                        <span style={{ flex: 2 }}>Asset</span>
                        <span className="inv-wide" style={{ flex: 1, textAlign: "right" }}>Units</span>
                        <span className="inv-wide" style={{ flex: 1.2, textAlign: "right" }}>Price</span>
                        <span style={{ flex: 1.2, textAlign: "right" }}>Value</span>
                        <span style={{ flex: 1.2, textAlign: "right" }}>Return</span>
                        <span style={{ flex: 1.4, textAlign: "right" }} />
                      </div>
                      {g.holdings.map((h) => {
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
                    </>
                  )}
                </div>
              );
            })}

            <ClosedPositions rows={closed} load={load} />

            <PlatformManager platforms={platforms} onChanged={load} />
          </>
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
