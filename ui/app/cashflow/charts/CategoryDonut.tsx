import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from "recharts";

import { chartColors, tokens } from "../../styles";

// ---------------------------------------------------------------------------
// Spending-by-category donut (Phase 4 dashboard). v1.1 "paper" redesign: a
// compact ring in the paper categorical palette (mockup). The legend is
// rendered by the page beside the donut. Cycles chartColors for >6 categories.
// Explicit-height wrapper is load-bearing — ResponsiveContainer renders blank
// inside a flex/grid parent with no resolvable height (Pitfall 3).
// ---------------------------------------------------------------------------

type CategorySlice = { category: string; total: number };

export default function CategoryDonut({ data }: { data: CategorySlice[] }) {
  const fmt = (
    v: number | string | ReadonlyArray<number | string> | undefined
  ) => (typeof v === "number" ? new Intl.NumberFormat("en-US").format(v) : v);

  return (
    <div style={{ width: 150, height: 150, flexShrink: 0 }}>
      <ResponsiveContainer>
        <PieChart>
          <Pie
            data={data}
            dataKey="total"
            nameKey="category"
            innerRadius={44}
            outerRadius={65}
            paddingAngle={2}
            stroke="none"
          >
            {data.map((_, i) => (
              <Cell key={i} fill={chartColors[i % chartColors.length]} />
            ))}
          </Pie>
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
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}
