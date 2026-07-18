"use client";

import { useCallback, useEffect, useState } from "react";

import { tokens, card, btn, btnDark } from "../styles";
import PlatformManager, { type Platform } from "./PlatformManager";
import HoldingModal from "./HoldingModal";
import HoldingOverrideModal from "./HoldingOverrideModal";
import PriceOverrideDialog from "./PriceOverrideDialog";
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

export type PlatformOption = { id: number; name: string };

export type HoldingRow = {
  id: number;
  ticker: string;
  asset_type: string | null;
  quantity: number;
  avg_cost: number;
  current_price: number | null;
  current_value: number | null;
  unrealized_pnl: number | null;
  realized_pnl: number;
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

const muted = tokens.color.muted;

export default function InvestmentsPage() {
  const [platforms, setPlatforms] = useState<Platform[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
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
          label: g.asset_type ?? "Other",
          value: Number(g.total_value),
        }))
      : activeGroups
          .filter((g) => g.holdings.length > 0)
          .map((g) => ({
            label: g.platform_id === null ? "Unassigned" : g.platform_name,
            value: Number(g.subtotal),
          }));

  const costBasis = summary
    ? summary.total_value - summary.total_unrealized_pnl
    : 0;

  return (
    <div className="tab-in" style={{ padding: "40px 44px 60px" }}>
      <div style={{ marginBottom: 28 }}>
        <div
          style={{
            fontSize: 12,
            letterSpacing: ".12em",
            textTransform: "uppercase",
            color: tokens.color.muted2,
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
            {/* Hero: total value + allocation */}
            <div
              style={{
                display: "grid",
                gridTemplateColumns:
                  "repeat(auto-fit, minmax(min(100%, 300px), 1fr))",
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
                }}
              >
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
                    fontSize: 52,
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
                        summary.total_unrealized_pnl < 0
                          ? "#e6a99c"
                          : tokens.color.chipGreenText,
                      fontSize: 13,
                      fontWeight: 600,
                      padding: "4px 10px",
                      borderRadius: 999,
                      fontVariantNumeric: "tabular-nums",
                    }}
                  >
                    {summary.total_unrealized_pnl < 0 ? "▼" : "▲"}{" "}
                    {fmtSigned(summary.total_unrealized_pnl)}
                  </span>
                  <span
                    style={{ fontSize: 13, color: tokens.color.inkTextMuted }}
                  >
                    unrealized ({pct(summary.total_unrealized_pnl, costBasis)})
                  </span>
                </div>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    marginTop: 20,
                    fontSize: 12,
                    color: tokens.color.inkTextMuted,
                  }}
                >
                  <span>as of {new Date(summary.as_of).toLocaleString()}</span>
                  <button
                    type="button"
                    onClick={refreshPrices}
                    disabled={refreshing}
                    style={{
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
              </div>

              <div style={{ ...card, marginBottom: 0 }}>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    marginBottom: 14,
                  }}
                >
                  <div style={{ fontSize: 14, fontWeight: 600 }}>Allocation</div>
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
                          style={{
                            padding: "5px 12px",
                            borderRadius: 999,
                            fontSize: 12,
                            fontWeight: active ? 600 : 500,
                            border: "none",
                            cursor: "pointer",
                            background: active ? tokens.color.ink : "transparent",
                            color: active
                              ? tokens.color.inkText
                              : tokens.color.muted,
                          }}
                        >
                          {opt.label}
                        </button>
                      );
                    })}
                  </div>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 22 }}>
                  <AllocationPieChart data={allocationData} />
                  <div
                    style={{
                      flex: 1,
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
                              background: BADGE_COLORS[i % BADGE_COLORS.length],
                              flexShrink: 0,
                            }}
                          />
                          <span style={{ flex: 1, fontWeight: 500 }}>
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
              </div>
            </div>

            {/* Unrealized / Realized P&L */}
            <div
              style={{
                display: "grid",
                gridTemplateColumns:
                  "repeat(auto-fit, minmax(min(100%, 220px), 1fr))",
                gap: 18,
                marginBottom: 18,
              }}
            >
              <div style={statCard}>
                <div style={statLabel}>Unrealized P&amp;L</div>
                <div
                  style={{
                    ...statValue,
                    color: pnlColor(summary.total_unrealized_pnl),
                  }}
                >
                  {fmtSigned(summary.total_unrealized_pnl)}
                </div>
              </div>
              <div style={statCard}>
                <div style={statLabel}>Realized P&amp;L</div>
                <div
                  style={{
                    ...statValue,
                    color: pnlColor(summary.total_realized_pnl),
                  }}
                >
                  {fmtSigned(summary.total_realized_pnl)}
                </div>
              </div>
            </div>

            <div style={{ ...card, marginBottom: 18 }}>
              <ValueHistoryChart
                data={history}
                range={historyRange}
                onRangeChange={setHistoryRange}
              />
            </div>

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
                style={{
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
                      <span
                        style={{
                          fontSize: 14,
                          fontWeight: 600,
                          color: isUnassigned ? muted : tokens.color.ink,
                        }}
                      >
                        {isUnassigned ? "Unassigned" : g.platform_name}
                      </span>
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
                        style={{
                          display: "flex",
                          fontSize: 12,
                          color: tokens.color.muted2,
                          padding: "8px 0",
                          borderBottom: `1px solid ${tokens.color.borderInner}`,
                        }}
                      >
                        <span style={{ flex: 2 }}>Asset</span>
                        <span style={{ flex: 1, textAlign: "right" }}>Units</span>
                        <span style={{ flex: 1.2, textAlign: "right" }}>Price</span>
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
                                style={{
                                  width: 32,
                                  height: 32,
                                  borderRadius: 9,
                                  background: badgeColor(h.ticker),
                                  color: "#fff",
                                  display: "inline-flex",
                                  alignItems: "center",
                                  justifyContent: "center",
                                  fontSize: 11,
                                  fontWeight: 700,
                                  flexShrink: 0,
                                }}
                              >
                                {h.ticker.slice(0, 4)}
                              </span>
                              <span style={{ minWidth: 0 }}>
                                <span
                                  style={{ fontWeight: 500, display: "block" }}
                                >
                                  {h.ticker}
                                </span>
                                <StalenessBadge
                                  fetchedAt={h.price_fetched_at}
                                  source={h.price_source}
                                  isStale={h.is_stale}
                                />
                              </span>
                            </span>
                            <span
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
                              style={{
                                flex: 1.2,
                                textAlign: "right",
                                fontVariantNumeric: "tabular-nums",
                                color: tokens.color.muted3,
                              }}
                            >
                              {h.current_price != null
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
                              {h.current_value != null
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
                              {upnl != null ? pct(upnl, basis) : "—"}
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
                              <button
                                type="button"
                                onClick={() => setPriceHolding(h)}
                                style={rowAction}
                              >
                                Set price
                              </button>
                              <button
                                type="button"
                                onClick={() => {
                                  setEditingHolding(h);
                                  setOverrideOpen(true);
                                }}
                                style={rowAction}
                              >
                                Edit
                              </button>
                              <button
                                type="button"
                                onClick={async () => {
                                  if (
                                    !confirm(
                                      `Delete holding ${h.ticker}? This removes the position (its event history is kept).`
                                    )
                                  )
                                    return;
                                  const r = await fetch(`/api/holdings/${h.id}`, {
                                    method: "DELETE",
                                  });
                                  if (r.ok) load();
                                  else
                                    setError(
                                      `Couldn't delete ${h.ticker} — please try again.`
                                    );
                                }}
                                style={{
                                  ...rowAction,
                                  color: tokens.color.terracotta,
                                }}
                              >
                                Delete
                              </button>
                            </span>
                          </div>
                        );
                      })}
                    </>
                  )}
                </div>
              );
            })}

            <PlatformManager platforms={platforms} onChanged={load} />
          </>
        )
      )}

      {showEvent && (
        <HoldingModal
          platforms={platformOptions}
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
  fontSize: 24,
  fontWeight: 600,
  fontVariantNumeric: "tabular-nums",
};
const rowAction: React.CSSProperties = {
  background: "transparent",
  color: tokens.color.muted2,
  border: "none",
  cursor: "pointer",
  fontSize: 12,
  padding: 0,
};
