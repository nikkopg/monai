"use client";

import { useState } from "react";
import {
  LineChart,
  Line,
  CartesianGrid,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

// ---------------------------------------------------------------------------
// Portfolio value / P&L history (VZ-02, INVX-01). Clone of
// ui/app/cashflow/charts/TrendChart.tsx with Bar→Line and a date x-axis.
// Fetches GET /api/investments/history (open read, no key injection needed —
// mirrors the existing proxy fetch pattern). Two mutually-exclusive views
// (value / P&L, one Line at a time) + a 1M/3M/6M/All range selector that
// re-fetches. Range-preset chrome and toggle polish are kept minimal here per
// --skip-ui — precise interaction design is deferred to /gsd-ui-phase 7
// (07-UI-SPEC.md's placement/color/copy contract is followed for what ships).
// Explicit-height wrapper (width 100% / height 280) is load-bearing (Recharts
// blank-render pitfall, 04-RESEARCH.md).
// ---------------------------------------------------------------------------

export type HistoryPoint = {
  date: string;
  total_market_value: number;
  total_pnl: number;
};

type Range = "1M" | "3M" | "6M" | "All";
type View = "value" | "pnl";

const RANGES: Range[] = ["1M", "3M", "6M", "All"];
const tickStyle = { fill: "#8b8474", fontSize: 12 };
const muted = "#8b8474";

const fmtPlain = (n: number) => new Intl.NumberFormat("en-US").format(n);
const fmtSigned = (n: number) =>
  new Intl.NumberFormat("en-US", { signDisplay: "always" }).format(n);

function pillStyle(active: boolean): React.CSSProperties {
  return {
    padding: "4px 12px",
    borderRadius: 6,
    fontSize: 12,
    border: "1px solid #e7e1d5",
    background: active ? "#2f6f4f" : "transparent",
    color: active ? "white" : muted,
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
  const pnlColor = latestPnl >= 0 ? "#2f6f4f" : "#b5503f";

  return (
    <section
      style={{
        background: "#ffffff",
        border: "1px solid #e7e1d5",
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
        <p style={{ fontSize: 14, color: muted, margin: 0 }}>
          Not enough history yet — check back after a few days of price
          snapshots.
        </p>
      ) : (
        <div style={{ width: "100%", height: 280 }}>
          <ResponsiveContainer>
            <LineChart data={data}>
              <CartesianGrid stroke="#e7e1d5" strokeDasharray="3 3" />
              <XAxis dataKey="date" tick={tickStyle} />
              <YAxis tick={tickStyle} />
              <Tooltip
                formatter={(value) =>
                  typeof value === "number"
                    ? view === "pnl"
                      ? fmtSigned(value)
                      : fmtPlain(value)
                    : value
                }
                contentStyle={{
                  background: "#ffffff",
                  border: "1px solid #e7e1d5",
                  borderRadius: 8,
                  fontSize: 12,
                  color: "#23201b",
                }}
              />
              {view === "value" ? (
                <Line
                  dataKey="total_market_value"
                  stroke="#2f6f4f"
                  name="Portfolio value"
                  dot={false}
                />
              ) : (
                <Line
                  dataKey="total_pnl"
                  stroke={pnlColor}
                  name="Unrealized P&L"
                  dot={false}
                />
              )}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  );
}
