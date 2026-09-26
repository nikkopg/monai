"use client";

import { useEffect, useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
} from "recharts";

import { tokens, card } from "../../styles";
import {
  visibleRows,
  toPlotPoints,
  tooltipLines,
  seamMonth,
  RANGE_MONTHS,
  type Range,
  type Mode,
  type NetWorthRow,
  type PlotPoint,
} from "./netWorthTrendHelpers";

// ---------------------------------------------------------------------------
// Net worth trend card (Phase 23 Plan 02). A separate card from TrendChart
// (D-01) — TrendChart is a fixed 6-month income/expense view; this card owns
// a decades-scale range selector and a Total/Split toggle that don't compose
// with TrendChart's two hidden Y-axes, so it's built and mounted standalone.
//
// The Tooltip below sets `filterNull={false}`. recharts 3.9.2's
// TooltipBoundingBox sets `visibility: hidden` whenever the payload is empty
// after `filterNull`, and the default `filterNull` is true — so hovering a
// gapped (null-valued) month would otherwise hide the tooltip entirely.
// `filterNull={false}` keeps the null-valued payload entry, and its
// `.payload` is still the full plot point, so NetWorthTooltip can render the
// D-09 "No data — reason" text on a gap month (a planning correction to
// 23-RESEARCH.md Pitfall 1's mouse-index workaround, which doesn't hold on
// this installed version).
//
// Every Line below also sets `isAnimationActive={false}`. The automated
// browser pane reports `visibilityState: hidden` and never fires
// requestAnimationFrame, so a rAF-gated line-draw animation would look blank
// there (23-RESEARCH Pitfall 2) even though it renders fine on a real reload.
//
// Phase 23.1: the at-cost Lines (`totalAtCost`/`investmentAtCost`) render
// conditionally, only when at least one plot point has a non-null value for
// that dataKey — an always-empty series would still count toward recharts'
// line total, breaking the Phase 23 e2e line-count contract. The seam
// `ReferenceLine` implements 23.1 D-02: it marks the switch from money-deposited
// to market-value history instead of silently smoothing it. The explanatory
// captions were removed at 23.1 UAT (user request); the tooltip's "(at cost)"
// suffix still flags deposits-basis months.
// ---------------------------------------------------------------------------

const LOAD_ERROR =
  "Couldn't load net worth history — check the backend is running and reload the page.";

const RANGE_OPTIONS: { value: Range; label: string }[] = [
  { value: "1Y", label: "1Y" },
  { value: "3Y", label: "3Y" },
  { value: "All", label: "All" },
];

const MODE_OPTIONS: { value: Mode; label: string }[] = [
  { value: "total", label: "Total" },
  { value: "split", label: "Split" },
];

function Pills<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
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
      {options.map((opt) => {
        const active = value === opt.value;
        return (
          <button
            key={opt.value}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(opt.value)}
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
  );
}

function NetWorthTooltip({
  mode,
  newestMonth,
  active,
  payload,
}: {
  mode: Mode;
  newestMonth?: string;
  active?: boolean;
  payload?: ReadonlyArray<{ payload?: unknown }>;
}) {
  if (!active || !payload || payload.length === 0) return null;
  const point = payload[0]?.payload as PlotPoint | undefined;
  if (!point) return null;

  const lines = tooltipLines(point.row, mode, point.month === newestMonth);

  return (
    <div
      style={{
        background: tokens.color.card,
        border: `1px solid ${tokens.color.border2}`,
        borderRadius: 10,
        fontSize: 12,
        color: tokens.color.text,
        padding: "8px 10px",
        lineHeight: 1.5,
      }}
    >
      {lines.map((line, i) => (
        <div key={i} style={i === 0 ? { fontWeight: 600 } : undefined}>
          {line}
        </div>
      ))}
    </div>
  );
}

export default function NetWorthTrendChart() {
  const [range, setRange] = useState<Range>("1Y");
  const [mode, setMode] = useState<Mode>("total");
  const [cache, setCache] = useState<Partial<Record<Range, { rows: NetWorthRow[] }>>>({});
  const [error, setError] = useState<string | null>(null);

  // ponytail: this cache is never invalidated by writes elsewhere on the page
  // (e.g. a CSV import), only by a full page reload. Upgrade path: source a
  // refresh key from refreshAll if a write-then-see-it-here gap ever matters.
  useEffect(() => {
    if (cache[range]) return;
    setError(null);
    fetch(`/api/cashflow/networth-history?months=${RANGE_MONTHS[range]}`)
      .then(async (res) => {
        if (!res.ok) {
          setError(LOAD_ERROR);
          return;
        }
        const data = await res.json();
        setCache((c) => ({ ...c, [range]: { rows: data.rows } }));
      })
      .catch(() => setError(LOAD_ERROR));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [range]);

  const rows = cache[range]?.rows;
  const shown = rows ? visibleRows(rows, range) : [];
  const points = toPlotPoints(shown);
  const seam = rows ? seamMonth(rows) : null;
  const showSeam = seam !== null && shown.some((r) => r.month === seam);
  const hasTotalAtCost = points.some((p) => p.totalAtCost !== null);
  const hasInvestmentAtCost = points.some((p) => p.investmentAtCost !== null);
  const newestMonth = rows && rows.length > 0 ? rows[rows.length - 1].month : undefined;

  return (
    <section aria-label="Net worth trend" style={card}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 6,
        }}
      >
        <div style={{ fontSize: 14, fontWeight: 600 }}>Net worth trend</div>
        <div style={{ display: "flex", gap: 10 }}>
          <Pills options={RANGE_OPTIONS} value={range} onChange={setRange} />
          <Pills options={MODE_OPTIONS} value={mode} onChange={setMode} />
        </div>
      </div>

      {mode === "split" && (
        <div
          style={{
            display: "flex",
            gap: 16,
            fontSize: 12,
            color: tokens.color.muted,
            marginTop: 8,
          }}
        >
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            <span
              style={{
                width: 14,
                height: 2,
                background: tokens.color.green,
                display: "inline-block",
              }}
            />
            Liquid
          </span>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            <span
              style={{
                width: 14,
                height: 2,
                background: tokens.color.gold,
                display: "inline-block",
              }}
            />
            Investment
          </span>
        </div>
      )}

      {!rows && error ? (
        <div
          style={{
            fontSize: 12,
            lineHeight: 1.5,
            color: tokens.color.terracotta,
            marginTop: 8,
          }}
        >
          {error}
        </div>
      ) : !rows ? (
        <div
          style={{
            height: 170,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 12,
            color: tokens.color.muted,
          }}
        >
          Loading net worth history…
        </div>
      ) : (
        <>
          <div style={{ width: "100%", height: 170 }}>
            <ResponsiveContainer>
              <LineChart data={points} margin={{ top: 8, right: 6, left: 6, bottom: 0 }}>
                <XAxis
                  dataKey="month"
                  tick={{ fill: tokens.color.muted2, fontSize: 11 }}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  orientation="right"
                  tickFormatter={(v: number) => `${Math.round(v / 1_000_000)}M`}
                  tick={{ fill: tokens.color.muted2, fontSize: 11 }}
                  axisLine={false}
                  tickLine={false}
                  width={40}
                />
                <Tooltip
                  filterNull={false}
                  isAnimationActive={false}
                  content={<NetWorthTooltip mode={mode} newestMonth={newestMonth} />}
                />
                {mode === "total" ? (
                  <>
                    <Line
                      type="monotone"
                      dataKey="totalMarket"
                      name="Net worth"
                      stroke={tokens.color.ink}
                      strokeWidth={2.4}
                      dot={{ r: 2.5, fill: tokens.color.ink, strokeWidth: 0 }}
                      activeDot={{ r: 3.5 }}
                      connectNulls={false}
                      isAnimationActive={false}
                    />
                    {hasTotalAtCost && (
                      <Line
                        type="monotone"
                        dataKey="totalAtCost"
                        name="Net worth (at cost)"
                        stroke={tokens.color.ink}
                        strokeWidth={2.4}
                        strokeDasharray="5 5"
                        dot={{ r: 2.5, fill: tokens.color.ink, strokeWidth: 0 }}
                        activeDot={{ r: 3.5 }}
                        connectNulls={false}
                        isAnimationActive={false}
                      />
                    )}
                  </>
                ) : (
                  <>
                    <Line
                      type="monotone"
                      dataKey="liquidTotal"
                      name="Liquid"
                      stroke={tokens.color.green}
                      strokeWidth={2.4}
                      dot={{ r: 2.5, fill: tokens.color.green, strokeWidth: 0 }}
                      activeDot={{ r: 3.5 }}
                      connectNulls={false}
                      isAnimationActive={false}
                    />
                    <Line
                      type="monotone"
                      dataKey="investmentMarket"
                      name="Investment"
                      stroke={tokens.color.gold}
                      strokeWidth={2.4}
                      dot={{ r: 2.5, fill: tokens.color.gold, strokeWidth: 0 }}
                      activeDot={{ r: 3.5 }}
                      connectNulls={false}
                      isAnimationActive={false}
                    />
                    {hasInvestmentAtCost && (
                      <Line
                        type="monotone"
                        dataKey="investmentAtCost"
                        name="Investment (at cost)"
                        stroke={tokens.color.gold}
                        strokeWidth={2.4}
                        strokeDasharray="5 5"
                        dot={{ r: 2.5, fill: tokens.color.gold, strokeWidth: 0 }}
                        activeDot={{ r: 3.5 }}
                        connectNulls={false}
                        isAnimationActive={false}
                      />
                    )}
                  </>
                )}
                {showSeam && (
                  <ReferenceLine
                    x={seam}
                    stroke={tokens.color.border2}
                    strokeWidth={1}
                    label={{
                      value: "Market value →",
                      position: "insideTopRight",
                      fontSize: 11,
                      fill: tokens.color.muted2,
                    }}
                  />
                )}
              </LineChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </section>
  );
}
