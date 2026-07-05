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
// Income vs expense bar chart (Phase 4 dashboard). Income uses Success
// #4ade80, expense uses Destructive #f87171 — NOT the accent blue
// (04-UI-SPEC.md § Color: "income/expense bar chart... NOT Accent"). Explicit
// height wrapper is load-bearing (Pitfall 3, 04-RESEARCH.md).
// ---------------------------------------------------------------------------

type IncomeExpensePoint = { income: number; expense: number };

const tickStyle = { fill: "#9aa0a6", fontSize: 12 };

export default function IncomeExpenseBar({
  data,
}: {
  data: IncomeExpensePoint[];
}) {
  const fmt = (
    v: number | string | ReadonlyArray<number | string> | undefined
  ) => (typeof v === "number" ? new Intl.NumberFormat("en-US").format(v) : v);

  return (
    <div style={{ width: "100%", height: 280 }}>
      <ResponsiveContainer>
        <BarChart data={data}>
          <CartesianGrid stroke="#2a2e37" strokeDasharray="3 3" />
          <XAxis dataKey="label" tick={tickStyle} />
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
