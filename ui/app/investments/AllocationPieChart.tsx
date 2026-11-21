import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from "recharts";

import { tokens } from "../styles";
import RollingNumber from "../components/RollingNumber";
import { GOLDS, fmtShort } from "../overview/holdings";

// ---------------------------------------------------------------------------
// VZ-01 allocation pie (Phase 7 Plan 03) — structural clone of the Phase-4
// CategoryDonut.tsx. Value basis is current IDR market value per group,
// switching between asset-type and platform groupings — both already on the
// GET /investments/summary payload (Plan 02's asset_type_groups + the
// existing platform groups). Pure renderer: the parent (page.tsx) resolves
// which grouping's {label, value}[] array to pass in via groupBy state; this
// component has no fetch and no knowledge of "asset_type vs platform".
// Radii are percentages of the box, so the donut cannot clip (261115-dcq);
// the legend sits below it in page.tsx.
// Slices use GOLDS, the Holdings card's investment palette, so terracotta (the loss
// colour) never colours a slice (261115-dlc).
// The centre total rolls via RollingNumber like the Cashflow Holdings centre; legend amounts stay static (261115-dvn).
// Explicit-height wrapper is load-bearing — see Pitfall 3, 04-RESEARCH.md:
// ResponsiveContainer renders blank inside a grid/flex parent with no
// resolvable height. Placement/toggle chrome polish deferred to
// /gsd-ui-phase 7 per 07-03-PLAN.md.
// ---------------------------------------------------------------------------

export type AllocationSlice = { label: string; value: number };

const muted = tokens.color.muted3;

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
      <p style={{ fontSize: "var(--fs-body, 14px)", color: muted, margin: 0 }}>
        Add a holding to see your allocation.
      </p>
    );
  }

  const total = data.reduce((a, b) => a + b.value, 0);

  return (
    <div style={{ position: "relative", width: "100%", height: 200 }}>
      {/* Before the chart in the DOM so the recharts wrapper (and its hover
          Tooltip) paints above it; the text shows through the donut hole. */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          pointerEvents: "none",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        <span style={{ fontSize: "var(--fs-xs, 12px)", color: muted }}>Total</span>
        <span style={{ fontSize: 17, fontWeight: 600 }}>
          <RollingNumber value={total} format={(n) => fmtShort(n, "IDR")} />
        </span>
      </div>
      <ResponsiveContainer>
        <PieChart>
          <Pie
            data={data}
            dataKey="value"
            nameKey="label"
            innerRadius="62%"
            outerRadius="92%"
            paddingAngle={2}
            // recharts 3.x animates the entrance from zero-width sectors on a
            // requestAnimationFrame clock. Animation stays on (restored in
            // 59f0bd5): a visible tab always paints the finished pie; only a
            // hidden tab, such as the automated browser pane, never gets a
            // frame and shows no slices.
          >
            {data.map((_, i) => (
              <Cell key={i} fill={GOLDS[i % GOLDS.length]} />
            ))}
          </Pie>
          <Tooltip
            wrapperClassName="amt"
            formatter={(value) => fmt(value)}
            contentStyle={{
              background: "#ffffff",
              border: "1px solid #e7e1d5",
              borderRadius: 8,
              fontSize: "var(--fs-xs, 12px)",
              color: "#23201b",
            }}
          />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}
