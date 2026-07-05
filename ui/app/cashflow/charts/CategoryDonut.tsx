import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from "recharts";

import { chartColors } from "../../styles";

// ---------------------------------------------------------------------------
// Spending-by-category donut (Phase 4 dashboard). Cycles the shared
// chartColors palette for >6 categories (04-UI-SPEC.md § Color).
// Explicit-height wrapper is load-bearing — see Pitfall 3, 04-RESEARCH.md:
// ResponsiveContainer renders blank inside a grid/flex parent with no
// resolvable height.
// ---------------------------------------------------------------------------

type CategorySlice = { category: string; total: number };

export default function CategoryDonut({ data }: { data: CategorySlice[] }) {
  const fmt = (
    v: number | string | ReadonlyArray<number | string> | undefined
  ) => (typeof v === "number" ? new Intl.NumberFormat("en-US").format(v) : v);

  return (
    <div style={{ width: "100%", height: 280 }}>
      <ResponsiveContainer>
        <PieChart>
          <Pie
            data={data}
            dataKey="total"
            nameKey="category"
            innerRadius={60}
            outerRadius={100}
            paddingAngle={2}
          >
            {data.map((_, i) => (
              <Cell key={i} fill={chartColors[i % chartColors.length]} />
            ))}
          </Pie>
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
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}
