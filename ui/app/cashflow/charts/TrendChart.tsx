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
// >=6-month cash flow (CASH-02). One column per month around a zero line:
// income goes up in green, expenses go down in terracotta, both at real size
// on one shared scale, and an ink dot marks the net (above the line = saved).
// stackOffset="sign" stacks the positive and the negative bar on opposite
// sides of zero. Explicit-height wrapper is load-bearing: recharts
// ResponsiveContainer renders blank inside a flex/grid parent with no
// resolvable height (Pitfall 3, 04-RESEARCH.md).
// ---------------------------------------------------------------------------

type TrendPoint = { month: string; income: number; expense: number };
type FlowPoint = TrendPoint & { out: number; net: number };

const tickStyle = { fill: tokens.color.muted2, fontSize: 11 };
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
      <div style={{ fontWeight: 600 }}>{p.month}</div>
      <div style={{ color: tokens.color.green }}>Income {fmt(p.income)}</div>
      <div style={{ color: tokens.color.terracottaText }}>Expenses {fmt(p.expense)}</div>
      <div>Net {signed(p.net)}</div>
    </div>
  );
}

export default function TrendChart({ data }: { data: TrendPoint[] }) {
  const points: FlowPoint[] = data.map((d) => ({
    ...d,
    out: -d.expense,
    net: d.income - d.expense,
  }));

  return (
    <div style={{ width: "100%", height: 170, marginTop: "auto" }}>
      <ResponsiveContainer>
        <ComposedChart
          data={points}
          stackOffset="sign"
          barCategoryGap="30%"
          margin={{ top: 8, right: 6, left: 6, bottom: 0 }}
        >
          <XAxis
            dataKey="month"
            tick={tickStyle}
            axisLine={false}
            tickLine={false}
          />
          <YAxis hide domain={["dataMin", "dataMax"]} />
          <Tooltip cursor={{ fill: tokens.color.borderInner }} content={<CashFlowTooltip />} />
          <ReferenceLine y={0} stroke={tokens.color.border2} />
          {/* Both bars use [5, 5, 0, 0]: recharts draws a negative bar flipped,
              so those corners land on the bottom end of the expense bar. */}
          <Bar dataKey="income" name="Income" stackId="flow" fill={tokens.color.green} radius={[5, 5, 0, 0]} />
          <Bar dataKey="out" name="Expenses" stackId="flow" fill={tokens.color.terracotta} radius={[5, 5, 0, 0]} />
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
  );
}
