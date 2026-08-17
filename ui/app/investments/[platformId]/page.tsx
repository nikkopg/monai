"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { tokens, card, btn, btnDark } from "../../styles";
import DepositCashModal from "../DepositCashModal";
import HoldingModal from "../HoldingModal";
import type { PlatformOption } from "../page";

// ---------------------------------------------------------------------------
// Platform detail — drill into one platform's PnL and buy/sell history
// (PLAT-01, D-08). Composition only: reuses the money/qty/badge/pnl helpers
// and segmented-control + stat-card markup already established in
// investments/page.tsx and TransactionModal.tsx (those helpers aren't
// exported, so they're copied verbatim here rather than imported).
// Fetches GET /api/platforms/{id}/detail + GET /api/portfolio-events?platform_id=
// in parallel on mount, mirroring investments/page.tsx's load().
// ---------------------------------------------------------------------------

type PlatformDetailHolding = {
  id: number;
  ticker: string;
  asset_type: string | null;
  quantity: number;
  avg_cost: number;
  current_price: number | null;
  current_value: number | null;
  unrealized_pnl: number | null;
  realized_pnl: number;
};

type PlatformDetail = {
  platform_id: number;
  platform_name: string;
  kind: string | null;
  subtotal: number;
  holdings: PlatformDetailHolding[];
};

type PortfolioEvent = {
  id: number;
  date: string;
  ticker: string;
  event_type: string;
  quantity: number;
  price: number;
};

const fmtPlain = (n: number) =>
  new Intl.NumberFormat("en-US").format(Math.round(n));
const fmtSigned = (n: number) =>
  new Intl.NumberFormat("en-US", { signDisplay: "always" }).format(
    Math.round(n)
  );

// Green for gains, terracotta for losses — copied verbatim from
// investments/page.tsx's pnlColor().
const pnlColor = (n: number) =>
  n >= 0 ? tokens.color.green : tokens.color.terracotta;

// Quantity precision: up to 8dp for crypto, 2 for stocks/funds, trim zeros —
// copied verbatim from investments/page.tsx's fmtQty().
function fmtQty(n: number, assetType: string | null): string {
  const dp = assetType === "crypto" ? 8 : 2;
  return n
    .toLocaleString("en-US", { maximumFractionDigits: dp })
    .replace(/\.?0+$/, (m) => (m.includes(".") ? "" : m));
}

// Deterministic badge color per ticker — copied verbatim from
// investments/page.tsx's badgeColor().
const BADGE_COLORS = ["#d8b26a", "#5a8f73", "#2f6f4f", "#8fae9c", "#b5503f"];
const badgeColor = (t: string) => {
  let h = 0;
  for (let i = 0; i < t.length; i++) h = (h * 31 + t.charCodeAt(i)) >>> 0;
  return BADGE_COLORS[h % BADGE_COLORS.length];
};

// event_type -> Title-cased label + Color-table-mapped hue (green
// buy/deposit, terracotta sell/withdrawal, ink otherwise).
const SIDE_LABELS: Record<string, string> = {
  buy: "Buy",
  sell: "Sell",
  deposit: "Deposit",
  withdrawal: "Withdrawal",
  dividend: "Dividend",
};
function sideLabel(eventType: string): string {
  return (
    SIDE_LABELS[eventType] ??
    eventType.charAt(0).toUpperCase() + eventType.slice(1)
  );
}
function sideColor(eventType: string): string {
  if (eventType === "buy" || eventType === "deposit") return tokens.color.green;
  if (eventType === "sell" || eventType === "withdrawal")
    return tokens.color.terracotta;
  return tokens.color.ink;
}

const muted = tokens.color.muted;

type Tab = "pnl" | "buysell";
const TABS: { key: Tab; label: string }[] = [
  { key: "pnl", label: "PnL" },
  { key: "buysell", label: "Buy & Sell" },
];

export default function PlatformDetailPage() {
  const params = useParams();
  const platformId = params.platformId as string;

  const [detail, setDetail] = useState<PlatformDetail | null>(null);
  const [events, setEvents] = useState<PortfolioEvent[]>([]);
  const [platformOptions, setPlatformOptions] = useState<PlatformOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("pnl");
  const [showDeposit, setShowDeposit] = useState(false);
  const [showLogEvent, setShowLogEvent] = useState(false);
  const cancelledRef = useRef(false);

  async function load() {
    setLoading(true);
    setNotFound(false);
    setError(null);
    try {
      const [dRes, eRes] = await Promise.all([
        fetch(`/api/platforms/${platformId}/detail`),
        fetch(`/api/portfolio-events?platform_id=${platformId}`),
      ]);
      if (dRes.status === 404) {
        if (!cancelledRef.current) setNotFound(true);
        return;
      }
      if (!dRes.ok || !eRes.ok) throw new Error("fetch failed");
      const d = await dRes.json();
      const e = await eRes.json();
      if (!cancelledRef.current) {
        setDetail(d);
        setEvents(e);
      }
    } catch {
      if (!cancelledRef.current)
        setError(
          "Couldn't load this platform — check the backend is running and reload the page."
        );
    } finally {
      if (!cancelledRef.current) setLoading(false);
    }

    // Platform list for HoldingModal's Platform <select> (Task 3) — kept out
    // of the required Promise.all above so an unrelated failure here never
    // blocks/breaks the platform detail view itself.
    try {
      const pRes = await fetch(`/api/platforms`);
      if (pRes.ok) {
        const p: { id: number; name: string }[] = await pRes.json();
        if (!cancelledRef.current) {
          setPlatformOptions(p.map((pl) => ({ id: pl.id, name: pl.name })));
        }
      }
    } catch {
      // HoldingModal just shows an empty Platform select; not a blocking error.
    }
  }

  useEffect(() => {
    cancelledRef.current = false;
    load();
    return () => {
      cancelledRef.current = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [platformId]);

  // Platform-wide totals — sum of each holding's own realized/unrealized.
  const totalRealized =
    detail?.holdings.reduce((a, h) => a + h.realized_pnl, 0) ?? 0;
  const totalUnrealized =
    detail?.holdings.reduce((a, h) => a + (h.unrealized_pnl ?? 0), 0) ?? 0;

  const backLink = (
    <Link
      href="/investments"
      style={{
        fontSize: 12,
        color: tokens.color.muted2,
        marginBottom: 12,
        display: "inline-block",
        textDecoration: "none",
      }}
    >
      ← Investments
    </Link>
  );

  return (
    <div className="tab-in" style={{ padding: "40px 44px 60px" }}>
      {backLink}

      {loading ? (
        <div style={card}>
          <p style={{ color: muted, fontSize: 14, margin: 0 }}>
            Loading platform…
          </p>
        </div>
      ) : notFound ? (
        <div style={{ ...card, color: tokens.color.terracotta }}>
          Platform not found. It may have been deleted.
        </div>
      ) : error || !detail ? (
        <div style={{ ...card, color: tokens.color.terracotta }}>
          {error ??
            "Couldn't load this platform — check the backend is running and reload the page."}
        </div>
      ) : (
        <>
          <div
            style={{
              display: "flex",
              alignItems: "flex-start",
              justifyContent: "space-between",
              gap: 16,
              marginBottom: 28,
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
                Platform
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
                {detail.platform_name}
                {detail.kind && (
                  <span
                    style={{
                      fontSize: 12,
                      color: muted,
                      marginLeft: 8,
                      fontFamily: tokens.font.sans,
                    }}
                  >
                    {detail.kind}
                  </span>
                )}
              </h1>
            </div>
            <button
              type="button"
              style={btn}
              onClick={() => setShowDeposit(true)}
            >
              Deposit cash
            </button>
          </div>

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
              <div style={statLabel}>Subtotal</div>
              <div style={statValue}>{fmtPlain(detail.subtotal)}</div>
            </div>
            <div style={statCard}>
              <div style={statLabel}>Realized</div>
              <div style={{ ...statValue, color: pnlColor(totalRealized) }}>
                {fmtSigned(totalRealized)}
              </div>
            </div>
            <div style={statCard}>
              <div style={statLabel}>Unrealized</div>
              <div style={{ ...statValue, color: pnlColor(totalUnrealized) }}>
                {fmtSigned(totalUnrealized)}
              </div>
            </div>
          </div>

          {/* Segmented control (Component 10) — copied verbatim from
              TransactionModal.tsx's segmented control markup. */}
          <div
            style={{
              display: "inline-flex",
              background: tokens.color.sidebar,
              border: `1px solid ${tokens.color.border2}`,
              borderRadius: 12,
              padding: 4,
              marginBottom: 18,
            }}
          >
            {TABS.map((t) => {
              const active = tab === t.key;
              return (
                <button
                  key={t.key}
                  type="button"
                  onClick={() => setTab(t.key)}
                  style={{
                    border: "none",
                    borderRadius: 9,
                    padding: "8px 18px",
                    fontSize: 14,
                    fontWeight: active ? 600 : 500,
                    cursor: "pointer",
                    color: active ? tokens.color.ink : tokens.color.muted,
                    background: active ? "#fff" : "transparent",
                    boxShadow: active ? "0 1px 2px rgba(40,34,24,.12)" : "none",
                    transition: "all .2s ease",
                  }}
                >
                  {t.label}
                </button>
              );
            })}
          </div>

          {tab === "buysell" && (
            <div style={{ marginBottom: 14 }}>
              <button
                type="button"
                style={btnDark}
                onClick={() => setShowLogEvent(true)}
              >
                + Log event
              </button>
            </div>
          )}

          <div style={card}>
            {tab === "pnl" ? (
              detail.holdings.length === 0 ? (
                <p style={{ fontSize: 14, color: muted, margin: 0 }}>
                  No holdings on this platform yet.
                </p>
              ) : (
                <>
                  <div style={tableHeaderRow}>
                    <span style={{ flex: 1.4 }}>Ticker</span>
                    <span style={{ flex: 1, textAlign: "right" }}>Qty</span>
                    <span style={{ flex: 1.2, textAlign: "right" }}>
                      Avg cost
                    </span>
                    <span style={{ flex: 1.2, textAlign: "right" }}>Price</span>
                    <span style={{ flex: 1.2, textAlign: "right" }}>Value</span>
                    <span style={{ flex: 1, textAlign: "right" }}>
                      Realized
                    </span>
                    <span style={{ flex: 1, textAlign: "right" }}>
                      Unrealized
                    </span>
                  </div>
                  {detail.holdings.map((h) => (
                    <div key={h.id} style={tableRow}>
                      <span
                        style={{
                          flex: 1.4,
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
                        <span style={{ fontWeight: 500 }}>{h.ticker}</span>
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
                        {fmtPlain(h.avg_cost)}
                      </span>
                      <span
                        style={{
                          flex: 1.2,
                          textAlign: "right",
                          fontVariantNumeric: "tabular-nums",
                          color: tokens.color.muted3,
                        }}
                      >
                        {h.current_price != null ? fmtPlain(h.current_price) : "—"}
                      </span>
                      <span
                        style={{
                          flex: 1.2,
                          textAlign: "right",
                          fontVariantNumeric: "tabular-nums",
                          fontWeight: 600,
                        }}
                      >
                        {h.current_value != null ? fmtPlain(h.current_value) : "—"}
                      </span>
                      <span
                        style={{
                          flex: 1,
                          textAlign: "right",
                          fontVariantNumeric: "tabular-nums",
                          fontWeight: 600,
                          color: pnlColor(h.realized_pnl),
                        }}
                      >
                        {fmtSigned(h.realized_pnl)}
                      </span>
                      <span
                        style={{
                          flex: 1,
                          textAlign: "right",
                          fontVariantNumeric: "tabular-nums",
                          fontWeight: 600,
                          color:
                            h.unrealized_pnl != null
                              ? pnlColor(h.unrealized_pnl)
                              : muted,
                        }}
                      >
                        {h.unrealized_pnl != null
                          ? fmtSigned(h.unrealized_pnl)
                          : "—"}
                      </span>
                    </div>
                  ))}
                </>
              )
            ) : events.length === 0 ? (
              <p style={{ fontSize: 14, color: muted, margin: 0 }}>
                No buy/sell history on this platform yet.
              </p>
            ) : (
              <>
                <div style={tableHeaderRow}>
                  <span style={{ flex: 1.2 }}>Date</span>
                  <span style={{ flex: 1 }}>Ticker</span>
                  <span style={{ flex: 1 }}>Side</span>
                  <span style={{ flex: 1, textAlign: "right" }}>Qty</span>
                  <span style={{ flex: 1.2, textAlign: "right" }}>Price</span>
                </div>
                {events.map((e) => (
                  <div key={e.id} style={tableRow}>
                    <span
                      style={{
                        flex: 1.2,
                        color: tokens.color.muted3,
                      }}
                    >
                      {new Date(e.date).toLocaleDateString()}
                    </span>
                    <span
                      style={{
                        flex: 1,
                        display: "flex",
                        alignItems: "center",
                        gap: 8,
                      }}
                    >
                      <span
                        style={{
                          width: 24,
                          height: 24,
                          borderRadius: 7,
                          background: badgeColor(e.ticker),
                          color: "#fff",
                          display: "inline-flex",
                          alignItems: "center",
                          justifyContent: "center",
                          fontSize: 9,
                          fontWeight: 700,
                          flexShrink: 0,
                        }}
                      >
                        {e.ticker.slice(0, 4)}
                      </span>
                      {e.ticker}
                    </span>
                    <span
                      style={{ flex: 1, fontWeight: 600, color: sideColor(e.event_type) }}
                    >
                      {sideLabel(e.event_type)}
                    </span>
                    <span
                      style={{
                        flex: 1,
                        textAlign: "right",
                        fontVariantNumeric: "tabular-nums",
                        color: tokens.color.muted3,
                      }}
                    >
                      {fmtQty(e.quantity, null)}
                    </span>
                    <span
                      style={{
                        flex: 1.2,
                        textAlign: "right",
                        fontVariantNumeric: "tabular-nums",
                      }}
                    >
                      {fmtPlain(e.price)}
                    </span>
                  </div>
                ))}
              </>
            )}
          </div>

          {showDeposit && (
            <DepositCashModal
              platformId={Number(platformId)}
              platformName={detail.platform_name}
              onClose={() => setShowDeposit(false)}
              onSaved={load}
            />
          )}
          {showLogEvent && (
            <HoldingModal
              platforms={platformOptions}
              defaultPlatformId={Number(platformId)}
              onClose={() => setShowLogEvent(false)}
              onSaved={load}
            />
          )}
        </>
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
const tableHeaderRow: React.CSSProperties = {
  display: "flex",
  fontSize: 12,
  color: tokens.color.muted2,
  padding: "8px 0",
  borderBottom: `1px solid ${tokens.color.borderInner}`,
};
const tableRow: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  fontSize: 14,
  padding: "13px 0",
  borderTop: `1px solid ${tokens.color.borderInner}`,
};
