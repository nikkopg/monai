import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from "recharts";

import { chartColors } from "../styles";

// ---------------------------------------------------------------------------
// VZ-01 allocation pie (Phase 7 Plan 03) — structural clone of the Phase-4
// CategoryDonut.tsx. Value basis is current IDR market value per group,
// switching between asset-type and platform groupings — both already on the
// GET /investments/summary payload (Plan 02's asset_type_groups + the
// existing platform groups). Pure renderer: the parent (page.tsx) resolves
// which grouping's {label, value}[] array to pass in via groupBy state; this
// component has no fetch and no knowledge of "asset_type vs platform".
// Explicit-height wrapper is load-bearing — see Pitfall 3, 04-RESEARCH.md:
// ResponsiveContainer renders blank inside a grid/flex parent with no
// resolvable height. Placement/toggle chrome polish deferred to
// /gsd-ui-phase 7 per 07-03-PLAN.md.
// ---------------------------------------------------------------------------

export type AllocationSlice = { label: string; value: number };

const muted = "#8b8474";

export default function AllocationPieChart({
  data,
}: {
  data: AllocationSlice[];
}) {
  const fmt = (
    v: number | string | ReadonlyArray<number | string> | undefined
  ) => (typeof v === "number" ? new Intl.NumberFormat("en-US").format(v) : v);

  if (data.length === 0) {
    return (
      <p style={{ fontSize: 14, color: muted, margin: 0 }}>
        Add a holding to see your allocation.
      </p>
    );
  }

  return (
    <div style={{ width: "100%", height: 280 }}>
      <ResponsiveContainer>
        <PieChart>
          <Pie
            data={data}
            dataKey="value"
            nameKey="label"
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
              background: "#ffffff",
              border: "1px solid #e7e1d5",
              borderRadius: 8,
              fontSize: 12,
              color: "#23201b",
            }}
          />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}
