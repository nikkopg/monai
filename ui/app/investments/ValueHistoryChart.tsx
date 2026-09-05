"use client";

import { useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

import { tokens } from "../styles";

// ---------------------------------------------------------------------------
// Portfolio value / P&L history (VZ-02, INVX-01). Styled to match the cashflow
// TrendChart (ui/app/cashflow/charts/TrendChart.tsx): tokens (not hardcoded
// hex), no CartesianGrid / YAxis, borderless X-axis, monotone line at
// strokeWidth 2.4, matching tooltip, 170px height. Keeps its own card chrome +
// range/view controls (the trend chart's card + legend live in the cashflow
// page; this chart is self-contained on the investments page).
// Fetches GET /api/investments/history (open read). Explicit-height wrapper is
// load-bearing (Recharts blank-render pitfall, 04-RESEARCH.md).
// ---------------------------------------------------------------------------

export type HistoryPoint = {
  date: string;
  total_market_value: number;
  total_pnl: number;
};

type Range = "1M" | "3M" | "6M" | "All";
type View = "value" | "pnl";

const RANGES: Range[] = ["1M", "3M", "6M", "All"];
const tickStyle = { fill: tokens.color.muted2, fontSize: 11 };

const fmtPlain = (n: number) => new Intl.NumberFormat("en-US").format(n);
const fmtSigned = (n: number) =>
  new Intl.NumberFormat("en-US", { signDisplay: "always" }).format(n);

function pillStyle(active: boolean): React.CSSProperties {
  return {
    padding: "4px 12px",
    borderRadius: 6,
    fontSize: 12,
    border: `1px solid ${tokens.color.border}`,
    background: active ? tokens.color.green : "transparent",
    color: active ? "white" : tokens.color.muted,
    cursor: "pointer",
  };
}

export default function ValueHistoryChart({
  data,
  range,
  onRangeChange,
}: {
  data: HistoryPoint[];
  range: Range;
  onRangeChange: (r: Range) => void;
}) {
  const [view, setView] = useState<View>("value");

  const latestPnl = data.length > 0 ? data[data.length - 1].total_pnl : 0;
  const pnlColor = latestPnl >= 0 ? tokens.color.green : tokens.color.terracotta;

  return (
    <section
      style={{
        background: tokens.color.card,
        border: `1px solid ${tokens.color.border}`,
        borderRadius: 8,
        padding: 24,
        marginBottom: 24,
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 16,
        }}
      >
        <span style={{ fontSize: 20, fontWeight: 600 }}>Portfolio history</span>
        <div style={{ display: "flex", gap: 4 }}>
          {RANGES.map((r) => (
            <button
              key={r}
              type="button"
              style={pillStyle(range === r)}
              onClick={() => onRangeChange(r)}
            >
              {r}
            </button>
          ))}
        </div>
      </div>

      <div style={{ display: "flex", gap: 4, marginTop: 8, marginBottom: 16 }}>
        <button
          type="button"
          style={pillStyle(view === "value")}
          onClick={() => setView("value")}
        >
          Value
        </button>
        <button
          type="button"
          style={pillStyle(view === "pnl")}
          onClick={() => setView("pnl")}
        >
          P&amp;L
        </button>
      </div>

      {data.length < 2 ? (
        <p style={{ fontSize: 14, color: tokens.color.muted, margin: 0 }}>
          Not enough history yet — check back after a few days of price
          snapshots.
        </p>
      ) : (
        <div style={{ width: "100%", height: 170 }}>
          <ResponsiveContainer>
            <LineChart
              data={data}
              margin={{ top: 8, right: 6, left: 6, bottom: 0 }}
            >
              <XAxis
                dataKey="date"
                tick={tickStyle}
                axisLine={false}
                tickLine={false}
              />
              <Tooltip
                formatter={(value) =>
                  typeof value === "number"
                    ? view === "pnl"
                      ? fmtSigned(value)
                      : fmtPlain(value)
                    : value
                }
                contentStyle={{
                  background: tokens.color.card,
                  border: `1px solid ${tokens.color.border2}`,
                  borderRadius: 10,
                  fontSize: 12,
                  color: tokens.color.text,
                }}
              />
              {view === "value" ? (
                <Line
                  type="monotone"
                  dataKey="total_market_value"
                  stroke={tokens.color.green}
                  name="Portfolio value"
                  strokeWidth={2.4}
                  dot={false}
                  activeDot={{ r: 3.5 }}
                />
              ) : (
                <Line
                  type="monotone"
                  dataKey="total_pnl"
                  stroke={pnlColor}
                  name="Unrealized P&L"
                  strokeWidth={2.4}
                  dot={false}
                  activeDot={{ r: 3.5 }}
                />
              )}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  );
}
