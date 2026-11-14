import {
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  ReferenceLine,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

import { tokens } from "../../styles";

// ---------------------------------------------------------------------------
// The Cashflow card's cash flow chart (CASH-02). One column per period around a
// zero line: income goes up in green, expenses go down in terracotta, both at
// real size on one shared scale, and an ink dot marks the net (above the line =
// saved). stackOffset="sign" stacks the positive and the negative bar on
// opposite sides of zero. Explicit-height wrapper is load-bearing: recharts
// ResponsiveContainer renders blank inside a flex/grid parent with no
// resolvable height (Pitfall 3, 04-RESEARCH.md). The label row under the chart
// is one native button per period: Enter / Space, focus and aria-pressed come
// free, and the chart's own axis is hidden so the bands line up with the row.
// ---------------------------------------------------------------------------

export type ChartPoint = {
  offset: number;
  title: string;
  short: string;
  income: number;
  expense: number;
};
type FlowPoint = ChartPoint & { out: number; net: number };

const fmt = (n: number) => new Intl.NumberFormat("en-US").format(n);
const signed = (n: number) => `${n < 0 ? "−" : "+"}${fmt(Math.abs(n))}`;

function CashFlowTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: ReadonlyArray<{ payload?: unknown }>;
}) {
  const p = payload?.[0]?.payload as FlowPoint | undefined;
  if (!active || !p) return null;
  return (
    <div
      style={{
        background: tokens.color.card,
        border: `1px solid ${tokens.color.border2}`,
        borderRadius: 10,
        fontSize: 12,
        color: tokens.color.text,
        padding: "8px 10px",
        lineHeight: 1.5,
        fontVariantNumeric: "tabular-nums",
      }}
    >
      <div style={{ fontWeight: 600 }}>{p.title}</div>
      <div style={{ color: tokens.color.green }}>Income {fmt(p.income)}</div>
      <div style={{ color: tokens.color.terracottaText }}>Expenses {fmt(p.expense)}</div>
      <div>Net {signed(p.net)}</div>
    </div>
  );
}

export default function TrendChart({
  points,
  selected,
  onSelect,
  label,
}: {
  points: ChartPoint[];
  selected: number;
  onSelect: (offset: number) => void;
  label: string;
}) {
  const data: FlowPoint[] = points.map((d) => ({
    ...d,
    out: -d.expense,
    net: d.income - d.expense,
  }));

  return (
    <div>
      <div style={{ width: "100%", height: 85 }}>
        <ResponsiveContainer>
          <ComposedChart
            data={data}
            stackOffset="sign"
            barCategoryGap="30%"
            margin={{ top: 4, right: 0, left: 0, bottom: 0 }}
          >
            <XAxis dataKey="title" hide />
            <YAxis hide domain={["dataMin", "dataMax"]} />
            <Tooltip cursor={{ fill: tokens.color.borderInner }} content={<CashFlowTooltip />} />
            <ReferenceLine y={0} stroke={tokens.color.border2} />
            {/* Both bars use [5, 5, 0, 0]: recharts draws a negative bar flipped,
                so those corners land on the bottom end of the expense bar. */}
            <Bar dataKey="income" name="Income" stackId="flow" fill={tokens.color.green} radius={[5, 5, 0, 0]} maxBarSize={18} />
            <Bar dataKey="out" name="Expenses" stackId="flow" fill={tokens.color.terracotta} radius={[5, 5, 0, 0]} maxBarSize={18} />
            <Line
              dataKey="net"
              name="Net"
              stroke="none"
              dot={{ r: 4, fill: tokens.color.ink, stroke: tokens.color.card, strokeWidth: 2 }}
              activeDot={{ r: 5 }}
              legendType="none"
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div role="group" aria-label={label} style={{ display: "flex" }}>
        {points.map((p) => (
          <button
            key={p.offset}
            type="button"
            aria-label={p.title}
            title={p.title}
            aria-pressed={p.offset === selected}
            onClick={() => onSelect(p.offset)}
            style={{
              flex: 1,
              minWidth: 0,
              border: "none",
              background: "none",
              padding: "4px 0 0",
              fontSize: 11,
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
              cursor: "pointer",
              color: tokens.color.muted3,
            }}
          >
            {p.short}
          </button>
        ))}
      </div>
    </div>
  );
}
