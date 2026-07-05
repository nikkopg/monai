import {
  BarChart,
  Bar,
  CartesianGrid,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

// ---------------------------------------------------------------------------
// >=6-month income/expense trend (CASH-02). Grouped bars — income Success
// #4ade80, expense Destructive #f87171. Net is deliberately NOT plotted as a
// third series (04-UI-SPEC.md: net is read from the totals row above the
// charts, avoiding a 3rd chart color). Explicit height wrapper is
// load-bearing (Pitfall 3, 04-RESEARCH.md).
// ---------------------------------------------------------------------------

type TrendPoint = { month: string; income: number; expense: number };

const tickStyle = { fill: "#9aa0a6", fontSize: 12 };

export default function TrendChart({ data }: { data: TrendPoint[] }) {
  const fmt = (
    v: number | string | ReadonlyArray<number | string> | undefined
  ) => (typeof v === "number" ? new Intl.NumberFormat("en-US").format(v) : v);

  return (
    <div style={{ width: "100%", height: 280 }}>
      <ResponsiveContainer>
        <BarChart data={data}>
          <CartesianGrid stroke="#2a2e37" strokeDasharray="3 3" />
          <XAxis dataKey="month" tick={tickStyle} />
          <YAxis tick={tickStyle} />
          <Tooltip
            formatter={(value) => fmt(value)}
            contentStyle={{
              background: "#1a1d23",
              border: "1px solid #2a2e37",
              borderRadius: 8,
              fontSize: 12,
              color: "#e6e8eb",
            }}
          />
          <Bar dataKey="income" fill="#4ade80" name="Income" />
          <Bar dataKey="expense" fill="#f87171" name="Expense" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
