import {
  LineChart,
  Line,
  XAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

import { tokens } from "../../styles";

// ---------------------------------------------------------------------------
// >=6-month income/expense trend (CASH-02). v1.1 "paper" redesign: two lines
// — income solid green, expense dashed terracotta (mockup). Net is not plotted
// (read from the stat cards). Explicit-height wrapper is load-bearing: recharts
// ResponsiveContainer renders blank inside a flex/grid parent with no resolvable
// height (Pitfall 3, 04-RESEARCH.md).
// ---------------------------------------------------------------------------

type TrendPoint = { month: string; income: number; expense: number };

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
            type="monotone"
            dataKey="income"
            name="Income"
            stroke={tokens.color.green}
            strokeWidth={2.4}
            dot={false}
            activeDot={{ r: 3.5 }}
          />
          <Line
            type="monotone"
            dataKey="expense"
            name="Expenses"
            stroke={tokens.color.terracotta}
            strokeWidth={2}
            strokeDasharray="5 5"
            dot={false}
            activeDot={{ r: 3.5 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
