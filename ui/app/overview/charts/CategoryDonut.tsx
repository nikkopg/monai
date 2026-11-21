import { useState } from "react";

import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from "recharts";

import { tokens } from "../../styles";
import { fmtAmount } from "../../lib/money";
import { topCategories } from "../periodCard";

// ---------------------------------------------------------------------------
// "Where it went": the spending-by-category donut plus its legend (Phase 4
// dashboard; 11-07 hierarchy rewire). Default view rolls up to top-level groups,
// each slice colored by that category's own identity swatch (D-14) — no more
// positional chartColors cycle. The ring and the legend rows both come from
// topCategories: the five largest plus a grey "Others", each with its share.
// Clicking a slice that has subcategories drills into that group's breakdown
// (same ring and legend, children inherit the parent swatch by default — a
// monochrome drilled ring is expected, not a bug, per UI-SPEC Component 3);
// "Others" and child slices never drill, and a "‹ Back" text link returns to
// the rollup. Transfer never appears here — excluded server-side (D-12),
// nothing to filter client-side.
// Explicit-height wrapper is load-bearing — ResponsiveContainer renders blank
// inside a flex/grid parent with no resolvable height (Pitfall 3).
// ---------------------------------------------------------------------------

type CategorySlice = { id: number; name: string; color: string | null; icon: string | null; total: number };
type CategoryGroup = CategorySlice & { children: CategorySlice[] };

const RING = 88;

export default function CategoryDonut({ data }: { data: CategoryGroup[] }) {
  const [drilled, setDrilled] = useState<CategoryGroup | null>(null);

  const fmt = (
    v: number | string | ReadonlyArray<number | string> | undefined
  ) => (typeof v === "number" ? new Intl.NumberFormat("en-US").format(v) : v);

  const rows: (CategorySlice & { share: number; children?: CategorySlice[] })[] = topCategories(
    drilled ? drilled.children : data
  );

  if (rows.length === 0) {
    return <div style={{ fontSize: "var(--fs-xs, 12px)", color: tokens.color.muted }}>No spending in this period.</div>;
  }

  return (
    <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 14 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {drilled && (
          <button
            onClick={() => setDrilled(null)}
            style={{
              alignSelf: "flex-start",
              fontSize: "var(--fs-xs, 12px)",
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
        <div style={{ width: RING, height: RING, flexShrink: 0 }}>
          <ResponsiveContainer>
            <PieChart>
              <Pie
                data={rows}
                dataKey="total"
                nameKey="name"
                innerRadius={27}
                outerRadius={42}
                paddingAngle={2}
                stroke="none"
              >
                {rows.map((r) => {
                  const canDrill = !drilled && !!r.children?.length;
                  return (
                    <Cell
                      key={r.id}
                      fill={r.color ?? "#c8c1b5"}
                      cursor={canDrill ? "pointer" : "default"}
                      onClick={() => {
                        if (canDrill) setDrilled(data.find((g) => g.id === r.id) ?? null);
                      }}
                    />
                  );
                })}
              </Pie>
              <Tooltip
                wrapperClassName="amt"
                formatter={(value) => fmt(value)}
                contentStyle={{
                  background: tokens.color.card,
                  border: `1px solid ${tokens.color.border2}`,
                  borderRadius: 10,
                  fontSize: "var(--fs-xs, 12px)",
                  color: tokens.color.text,
                }}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>
      <ul
        aria-label="Where it went"
        style={{
          listStyle: "none",
          margin: 0,
          padding: 0,
          flex: "1 1 150px",
          minWidth: 0,
          display: "flex",
          flexDirection: "column",
          gap: 7,
          fontSize: "var(--fs-xs, 12px)",
        }}
      >
        {rows.map((r) => (
          <li key={r.id} style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: "50%",
                background: r.color ?? "#c8c1b5",
                flexShrink: 0,
              }}
            />
            {/* Wrap at spaces; a single word too long for the line ends in an
                ellipsis instead of splitting mid-word (hyphens:auto has no
                dictionary in headless Chromium). Full name stays in the tooltip. */}
            <span
              title={r.name || undefined}
              style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }}
            >
              {r.name || "–"}
            </span>
            <span className="amt" style={{ fontWeight: 500, fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" }}>
              {fmtAmount(r.total, "IDR")}
            </span>
            <span
              style={{
                color: tokens.color.muted3,
                width: 30,
                textAlign: "right",
                whiteSpace: "nowrap",
              }}
            >
              {r.share}%
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
