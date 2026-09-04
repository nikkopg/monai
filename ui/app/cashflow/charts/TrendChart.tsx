import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

import { tokens } from "../../styles";

// ---------------------------------------------------------------------------
// >=6-month trend (CASH-02). v1.1 "paper" redesign: income solid green,
// expense dashed terracotta (mockup). Plus a net-worth line (solid ink) on a
// SEPARATE hidden Y-axis — net worth is ~100x the monthly income/expense, so a
// shared scale would flatten the cashflow lines. net_worth is null for months
// with no investment snapshot (see backend net_worth_trend); connectNulls=false
// leaves a gap so the line only appears where the value is real. Explicit-height
// wrapper is load-bearing (Recharts blank-render pitfall, 04-RESEARCH.md).
// ---------------------------------------------------------------------------

type TrendPoint = {
  month: string;
  income: number;
  expense: number;
  net_worth?: number | null;
};

const tickStyle = { fill: tokens.color.muted2, fontSize: 11 };

export default function TrendChart({ data }: { data: TrendPoint[] }) {
  const fmt = (
    v: number | string | ReadonlyArray<number | string> | undefined
  ) => (typeof v === "number" ? new Intl.NumberFormat("en-US").format(v) : v);

  return (
    <div style={{ width: "100%", height: 170 }}>
      <ResponsiveContainer>
        <LineChart data={data} margin={{ top: 8, right: 6, left: 6, bottom: 0 }}>
          <XAxis
            dataKey="month"
            tick={tickStyle}
            axisLine={false}
            tickLine={false}
          />
          {/* Two hidden scales: cashflow (income/expense) and net worth. */}
          <YAxis yAxisId="cash" hide />
          <YAxis yAxisId="nw" orientation="right" hide domain={["auto", "auto"]} />
          <Tooltip
            formatter={(value) => fmt(value)}
            contentStyle={{
              background: tokens.color.card,
              border: `1px solid ${tokens.color.border2}`,
              borderRadius: 10,
              fontSize: 12,
              color: tokens.color.text,
            }}
          />
          <Line
            yAxisId="cash"
            type="monotone"
            dataKey="income"
            name="Income"
            stroke={tokens.color.green}
            strokeWidth={2.4}
            dot={false}
            activeDot={{ r: 3.5 }}
          />
          <Line
            yAxisId="cash"
            type="monotone"
            dataKey="expense"
            name="Expenses"
            stroke={tokens.color.terracotta}
            strokeWidth={2}
            strokeDasharray="5 5"
            dot={false}
            activeDot={{ r: 3.5 }}
          />
          <Line
            yAxisId="nw"
            type="monotone"
            dataKey="net_worth"
            name="Net worth"
            stroke={tokens.color.ink}
            strokeWidth={2.4}
            // Dots shown (not false): reliable net-worth points can be sparse —
            // often a single current-month point until more months reconcile —
            // and a lone point on a dotless line would be invisible.
            dot={{ r: 2.5, fill: tokens.color.ink, strokeWidth: 0 }}
            connectNulls={false}
            activeDot={{ r: 3.5 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
