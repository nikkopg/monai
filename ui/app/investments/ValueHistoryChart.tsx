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
import Pills from "../components/Pills";

// ---------------------------------------------------------------------------
// Portfolio value / P&L history (VZ-02, INVX-01), drawn inside the dark
// "Portfolio value" hero on /investments. Same look as the Cashflow net worth
// hero (NetWorthTrendChart `hero`): `header` (label + total) sits left of the
// range and Value/P&L Pills, on-ink line and tick colours, no CartesianGrid /
// YAxis, borderless X-axis, monotone line at strokeWidth 2.4. The hero card
// chrome comes from page.tsx; this root is a plain flex column.
// The data is fetched by page.tsx (GET /api/investments/history, open read).
// Explicit-height wrapper is load-bearing (Recharts blank-render pitfall,
// 04-RESEARCH.md).
// ---------------------------------------------------------------------------

export type HistoryPoint = {
  date: string;
  total_market_value: number;
  total_pnl: number;
};

type Range = "1M" | "3M" | "All";
type View = "value" | "pnl";

const RANGE_OPTIONS: { value: Range; label: string }[] = (
  ["1M", "3M", "All"] as const
).map((r) => ({ value: r, label: r }));
const VIEW_OPTIONS: { value: View; label: string }[] = [
  { value: "value", label: "Value" },
  { value: "pnl", label: "P&L" },
];
const tickStyle = { fill: tokens.color.inkTextMuted, fontSize: 12 };

const fmtPlain = (n: number) => new Intl.NumberFormat("en-US").format(n);
const fmtSigned = (n: number) =>
  new Intl.NumberFormat("en-US", { signDisplay: "always" }).format(n);

export default function ValueHistoryChart({
  data,
  range,
  onRangeChange,
  header,
}: {
  data: HistoryPoint[];
  range: Range;
  onRangeChange: (r: Range) => void;
  header?: React.ReactNode;
}) {
  const [view, setView] = useState<View>("value");

  const latestPnl = data.length > 0 ? data[data.length - 1].total_pnl : 0;
  const pnlStroke = latestPnl >= 0 ? tokens.color.chipGreenText : "#e6a99c";

  return (
    <div style={{ display: "flex", flexDirection: "column", flex: 1, minWidth: 0 }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          // Wrap, so in a narrow hero the pills drop below the total.
          flexWrap: "wrap",
          gap: "10px 16px",
          marginBottom: 6,
        }}
      >
        {header}
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          <Pills
            options={RANGE_OPTIONS}
            value={range}
            onChange={onRangeChange}
            dark
            tap
            label="History range"
          />
          <Pills
            options={VIEW_OPTIONS}
            value={view}
            onChange={setView}
            dark
            tap
            label="History metric"
          />
        </div>
      </div>

      {data.length < 2 ? (
        <p
          style={{
            fontSize: "var(--fs-body, 14px)",
            color: tokens.color.inkTextMuted,
            margin: "auto 0 0",
          }}
        >
          Not enough history yet — check back after a few days of price
          snapshots.
        </p>
      ) : (
        <div style={{ width: "100%", height: 130, marginTop: "auto" }}>
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
                minTickGap={24}
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
                  fontSize: "var(--fs-xs, 12px)",
                  color: tokens.color.text,
                }}
              />
              {view === "value" ? (
                <Line
                  type="monotone"
                  dataKey="total_market_value"
                  stroke={tokens.color.chipGreenText}
                  name="Portfolio value"
                  strokeWidth={2.4}
                  dot={false}
                  activeDot={{ r: 3.5 }}
                />
              ) : (
                <Line
                  type="monotone"
                  dataKey="total_pnl"
                  stroke={pnlStroke}
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
    </div>
  );
}
