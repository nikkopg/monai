"use client";

import { useCallback, useEffect, useState } from "react";

import { card, btn } from "../styles";
import PlatformManager, { type Platform } from "./PlatformManager";
import HoldingModal from "./HoldingModal";
import HoldingOverrideModal from "./HoldingOverrideModal";
import PriceOverrideDialog from "./PriceOverrideDialog";
import StalenessBadge from "./StalenessBadge";
import ValueHistoryChart, { type HistoryPoint } from "./ValueHistoryChart";
import AllocationPieChart, { type AllocationSlice } from "./AllocationPieChart";

// ---------------------------------------------------------------------------
// Investments page — grown into the keystone portfolio view (Plan 05-03).
// Fetches GET /api/investments/summary and renders: a portfolio-total banner,
// a 2-column unrealized/realized P&L summary, and platform-grouped holding
// cards (one per platform + "Unassigned"), plus the Platforms manager from
// Plan 02. Zero-qty holdings are filtered out per D-04.
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

// Unsigned magnitude formatter (portfolio total, avg cost, current value).
const fmtPlain = (n: number) => new Intl.NumberFormat("en-US").format(n);
// Signed formatter for P&L figures (verbatim pattern from cashflow/page.tsx).
const fmtSigned = (n: number) =>
  new Intl.NumberFormat("en-US", { signDisplay: "always" }).format(n);

// Green for gains, red for losses (paired with the +/- sign — WCAG 1.4.1).
const pnlColor = (n: number) => (n >= 0 ? "#4ade80" : "#f87171");

// Quantity precision: up to 8 dp for crypto, 2 for stocks/funds, trim zeros.
function fmtQty(n: number, assetType: string | null): string {
  const dp = assetType === "crypto" ? 8 : 2;
  return n
    .toLocaleString("en-US", { maximumFractionDigits: dp })
    .replace(/\.?0+$/, (m) => (m.includes(".") ? "" : m));
}

const muted = "#9aa0a6";

export default function InvestmentsPage() {
  const [platforms, setPlatforms] = useState<Platform[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<HistoryPoint[]>([]);
  const [historyRange, setHistoryRange] = useState<
    "1M" | "3M" | "6M" | "All"
  >("3M");
  const [allocationGroupBy, setAllocationGroupBy] = useState<
    "asset_type" | "platform"
  >("asset_type");

  // Modal state.
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

  // History is fetched separately from the summary — re-fetch only when the
  // range selector changes, not on every summary/price refresh (07-UI-SPEC.md
  // page.tsx wiring note).
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

  // Refresh prices (INV-02/03): force-fetch every ticker server-side, then
  // refetch the summary. Per-ticker failures are swallowed backend-side; a stale
  // row after refresh surfaces the per-row "couldn't refresh" note below.
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

  // VZ-01: both groupings already live on the one summary payload — the
  // toggle only switches which array is passed to AllocationPieChart, no
  // new fetch (07-UI-SPEC.md page.tsx wiring note).
  const allocationData: AllocationSlice[] =
    allocationGroupBy === "asset_type"
      ? (summary?.asset_type_groups ?? []).map((g) => ({
          label: g.asset_type ?? "Other",
          value: g.total_value,
        }))
      : activeGroups
          .filter((g) => g.holdings.length > 0)
          .map((g) => ({
            label: g.platform_id === null ? "Unassigned" : g.platform_name,
            value: g.subtotal,
          }));

  return (
    <main style={{ maxWidth: 760, margin: "0 auto", padding: "48px 24px" }}>
      <h1 style={{ fontSize: 28, fontWeight: 600, marginTop: 0, marginBottom: 32 }}>
        Investments
      </h1>

      {loading ? (
        <section style={card}>
          <p style={{ color: muted, fontSize: 14, margin: 0 }}>
            Loading your portfolio…
          </p>
        </section>
      ) : error ? (
        <section style={card}>
          <p style={{ color: "#f87171", fontSize: 14, margin: 0 }}>{error}</p>
        </section>
      ) : (
        summary && (
          <>
            {/* Portfolio total banner */}
            <section
              style={{
                ...card,
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }}
            >
              <div>
                <p style={{ fontSize: 12, color: muted, margin: "0 0 4px" }}>
                  Total portfolio value
                </p>
                <div style={{ fontSize: 28, fontWeight: 600 }}>
                  {fmtPlain(summary.total_value)}
                </div>
                <p style={{ fontSize: 12, color: muted, margin: "4px 0 0" }}>
                  as of {new Date(summary.as_of).toLocaleString()}
                </p>
              </div>
              <button
                style={btn}
                type="button"
                onClick={refreshPrices}
                disabled={refreshing}
              >
                {refreshing ? "Refreshing…" : "Refresh prices"}
              </button>
            </section>

            {/* Unrealized / Realized P&L summary */}
            <section
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(2, 1fr)",
                gap: 16,
                marginBottom: 24,
              }}
            >
              <div style={card}>
                <p style={{ fontSize: 12, color: muted, margin: "0 0 4px" }}>
                  Unrealized P&amp;L
                </p>
                <div
                  style={{
                    fontSize: 20,
                    fontWeight: 600,
                    color: pnlColor(summary.total_unrealized_pnl),
                  }}
                >
                  {fmtSigned(summary.total_unrealized_pnl)}
                </div>
              </div>
              <div style={card}>
                <p style={{ fontSize: 12, color: muted, margin: "0 0 4px" }}>
                  Realized P&amp;L
                </p>
                <div
                  style={{
                    fontSize: 20,
                    fontWeight: 600,
                    color: pnlColor(summary.total_realized_pnl),
                  }}
                >
                  {fmtSigned(summary.total_realized_pnl)}
                </div>
              </div>
            </section>

            {/* Allocation pie (VZ-01) — asset-type/platform toggle, no new fetch */}
            <section style={{ ...card, marginBottom: 24 }}>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  marginBottom: 16,
                }}
              >
                <span style={{ fontSize: 20, fontWeight: 600 }}>Allocation</span>
                <div style={{ display: "flex", gap: 4 }}>
                  {(
                    [
                      { key: "asset_type", label: "Asset type" },
                      { key: "platform", label: "Platform" },
                    ] as const
                  ).map((opt) => (
                    <button
                      key={opt.key}
                      type="button"
                      onClick={() => setAllocationGroupBy(opt.key)}
                      style={{
                        padding: "4px 12px",
                        borderRadius: 6,
                        fontSize: 12,
                        border: "1px solid #2a2e37",
                        cursor: "pointer",
                        background:
                          allocationGroupBy === opt.key ? "#3b82f6" : "transparent",
                        color: allocationGroupBy === opt.key ? "white" : muted,
                      }}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>
              <AllocationPieChart data={allocationData} />
            </section>

            <ValueHistoryChart
              data={history}
              range={historyRange}
              onRangeChange={setHistoryRange}
            />

            {/* Log-event primary CTA + de-emphasized direct-override link */}
            <div
              style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 24 }}
            >
              <button style={btn} type="button" onClick={() => setShowEvent(true)}>
                Log event
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
                  fontSize: 12,
                  cursor: "pointer",
                  textDecoration: "underline",
                  padding: 0,
                }}
              >
                Add holding directly
              </button>
            </div>

            {/* Empty state — no holdings yet */}
            {!hasAnyHolding && (
              <section style={card}>
                <h2 style={{ fontSize: 20, fontWeight: 600, margin: "0 0 8px" }}>
                  No holdings yet.
                </h2>
                <p style={{ fontSize: 14, color: muted, margin: 0 }}>
                  Log your first buy to start tracking a position, or add a
                  platform first if you hold assets across more than one app.
                </p>
              </section>
            )}

            {/* Platform-grouped holding cards */}
            {activeGroups.map((g) => {
              const isUnassigned = g.platform_id === null;
              return (
                <section key={String(g.platform_id)} style={card}>
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "baseline",
                      marginBottom: 12,
                    }}
                  >
                    <div>
                      <span
                        style={{
                          fontSize: 20,
                          fontWeight: 600,
                          color: isUnassigned ? muted : "#e6e8eb",
                        }}
                      >
                        {isUnassigned ? "Unassigned" : g.platform_name}
                      </span>
                      {g.kind && (
                        <span style={{ fontSize: 12, color: muted, marginLeft: 8 }}>
                          {g.kind}
                        </span>
                      )}
                    </div>
                    <span style={{ fontSize: 20, fontWeight: 600 }}>
                      {fmtPlain(g.subtotal)}
                    </span>
                  </div>

                  {g.holdings.length === 0 ? (
                    <p style={{ fontSize: 14, color: muted, margin: 0 }}>
                      No holdings in this platform yet.
                    </p>
                  ) : (
                    <table style={{ width: "100%", borderCollapse: "collapse" }}>
                      <tbody>
                        {g.holdings.map((h) => {
                          const upnl = h.unrealized_pnl;
                          return (
                            <tr key={h.id} style={{ borderTop: "1px solid #2a2e37" }}>
                              <td style={{ padding: "8px 8px 8px 0", verticalAlign: "top" }}>
                                <div style={{ fontSize: 14 }}>{h.ticker}</div>
                                <div style={{ fontSize: 12, color: muted }}>
                                  {h.asset_type ?? "—"}
                                </div>
                                <div style={{ marginTop: 4 }}>
                                  <StalenessBadge
                                    fetchedAt={h.price_fetched_at}
                                    source={h.price_source}
                                    isStale={h.is_stale}
                                  />
                                </div>
                                {h.is_stale && (
                                  <div
                                    style={{
                                      fontSize: 11,
                                      color: muted,
                                      marginTop: 2,
                                    }}
                                  >
                                    Couldn&apos;t refresh — showing last known price.
                                  </div>
                                )}
                              </td>
                              <td style={{ padding: 8, fontSize: 14, textAlign: "right" }}>
                                {fmtQty(h.quantity, h.asset_type)}
                              </td>
                              <td style={{ padding: 8, fontSize: 14, textAlign: "right" }}>
                                {fmtPlain(h.avg_cost)}
                              </td>
                              <td style={{ padding: 8, fontSize: 14, textAlign: "right" }}>
                                {h.current_price != null ? fmtPlain(h.current_price) : "—"}
                              </td>
                              <td
                                style={{
                                  padding: 8,
                                  fontSize: 14,
                                  fontWeight: 600,
                                  textAlign: "right",
                                }}
                              >
                                {h.current_value != null ? fmtPlain(h.current_value) : "—"}
                              </td>
                              <td
                                style={{
                                  padding: 8,
                                  fontSize: 14,
                                  fontWeight: 600,
                                  textAlign: "right",
                                  color: upnl != null ? pnlColor(upnl) : muted,
                                }}
                              >
                                {upnl != null ? fmtSigned(upnl) : "—"}
                              </td>
                              <td
                                style={{
                                  padding: "8px 0 8px 8px",
                                  fontSize: 12,
                                  textAlign: "right",
                                }}
                              >
                                <div
                                  style={{
                                    display: "flex",
                                    gap: 10,
                                    justifyContent: "flex-end",
                                  }}
                                >
                                  <button
                                    type="button"
                                    onClick={() => setPriceHolding(h)}
                                    style={{
                                      background: "transparent",
                                      color: muted,
                                      border: "none",
                                      cursor: "pointer",
                                      fontSize: 12,
                                      padding: 0,
                                    }}
                                  >
                                    Set price
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() => {
                                      setEditingHolding(h);
                                      setOverrideOpen(true);
                                    }}
                                    style={{
                                      background: "transparent",
                                      color: muted,
                                      border: "none",
                                      cursor: "pointer",
                                      fontSize: 12,
                                      padding: 0,
                                    }}
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
                                      const r = await fetch(
                                        `/api/holdings/${h.id}`,
                                        { method: "DELETE" }
                                      );
                                      if (r.ok) load();
                                      else
                                        setError(
                                          `Couldn't delete ${h.ticker} — please try again.`
                                        );
                                    }}
                                    style={{
                                      background: "transparent",
                                      color: "#f87171",
                                      border: "none",
                                      cursor: "pointer",
                                      fontSize: 12,
                                      padding: 0,
                                    }}
                                  >
                                    Delete
                                  </button>
                                </div>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  )}
                </section>
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
    </main>
  );
}
