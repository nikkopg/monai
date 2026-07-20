import { useState } from "react";

import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from "recharts";

import { tokens } from "../../styles";

// ---------------------------------------------------------------------------
// Spending-by-category donut (Phase 4 dashboard; 11-07 hierarchy rewire).
// Default view rolls up to top-level groups, each slice colored by that
// category's own identity swatch (D-14) — no more positional chartColors
// cycle. Clicking a slice drills into that group's subcategory breakdown
// (same ring, children inherit the parent swatch by default — a monochrome
// drilled ring is expected, not a bug, per UI-SPEC Component 3); a "‹ Back"
// text link returns to the rollup. Transfer never appears here — excluded
// server-side (D-12), nothing to filter client-side.
// Explicit-height wrapper is load-bearing — ResponsiveContainer renders blank
// inside a flex/grid parent with no resolvable height (Pitfall 3).
// ---------------------------------------------------------------------------

type CategorySlice = { id: number; name: string; color: string | null; icon: string | null; total: number };
type CategoryGroup = CategorySlice & { children: CategorySlice[] };

export default function CategoryDonut({ data }: { data: CategoryGroup[] }) {
  const [drilled, setDrilled] = useState<CategoryGroup | null>(null);

  const fmt = (
    v: number | string | ReadonlyArray<number | string> | undefined
  ) => (typeof v === "number" ? new Intl.NumberFormat("en-US").format(v) : v);

  const slices: CategorySlice[] = drilled ? drilled.children : data;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      {drilled && (
        <button
          onClick={() => setDrilled(null)}
          style={{
            alignSelf: "flex-start",
            fontSize: 12,
            color: tokens.color.muted2,
            background: "none",
            border: "none",
            padding: 0,
            cursor: "pointer",
          }}
        >
          ‹ Back
        </button>
      )}
      <div style={{ width: 150, height: 150, flexShrink: 0 }}>
        <ResponsiveContainer>
          <PieChart>
            <Pie
              data={slices}
              dataKey="total"
              nameKey="name"
              innerRadius={44}
              outerRadius={65}
              paddingAngle={2}
              stroke="none"
              // recharts 3.x collapses every sector to startAngle === endAngle
              // at animation t=0 and Sector returns null for that, so the pie is
              // zero <path>s until a frame lands. The clock is rAF-based, so a tab
              // that never gets a frame stays permanently blank and does not
              // self-heal. Render final geometry on first paint instead.
              isAnimationActive={false}
            >
              {slices.map((s, i) => (
                <Cell
                  key={s.id}
                  fill={s.color ?? "#c8c1b5"}
                  cursor={!drilled && data[i]?.children?.length ? "pointer" : "default"}
                  onClick={() => {
                    if (!drilled && data[i]?.children?.length) setDrilled(data[i]);
                  }}
                />
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
    </div>
  );
}
