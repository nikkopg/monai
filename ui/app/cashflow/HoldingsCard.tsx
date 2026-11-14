"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { PieChart, Pie, Cell } from "recharts";

import { tokens, card } from "../styles";
import Pills from "../components/Pills";
import RollingNumber from "../components/RollingNumber";
import {
  fmtShort,
  liquidRows,
  categoryRows,
  mainRows,
  platformRows,
  type Ccy,
  type HoldingRow,
  type HoldingsData,
} from "./holdings";

// ---------------------------------------------------------------------------
// The Cashflow page's "Holdings" card: one portrait donut with three views.
// Main splits net worth into Liquid and Investment; each drills into its own
// breakdown (Liquid in IDR or USD, Investment by platform or asset type). A row
// or a ring slice drills in. Built to .planning/design/holdings-card-mock.html.
// Every displayed string comes from ./holdings. The pill choices live at card
// level, so they survive drilling out and back in.
// ---------------------------------------------------------------------------

type View = "main" | "liquid" | "investment";

const SIZE = 170;
const CCY_OPTIONS = [
  { value: "IDR" as const, label: "IDR" },
  { value: "USD" as const, label: "USD" },
];

const BY_OPTIONS = [
  { value: "platform" as const, label: "Platform" },
  { value: "category" as const, label: "Category" },
];

const crumb: React.CSSProperties = {
  border: "none",
  background: "none",
  padding: 0,
  font: "inherit",
  fontWeight: 500,
  color: tokens.color.muted3,
  cursor: "pointer",
};

export default function HoldingsCard({ data }: { data: HoldingsData }) {
  const [view, setView] = useState<View>("main");
  const [ccy, setCcy] = useState<Ccy>("IDR");
  const [by, setBy] = useState<"platform" | "category">("platform");
  const router = useRouter();
  const [hovered, setHovered] = useState<string | null>(null);

  const go = (v: View) => {
    setView(v);
    setHovered(null);
  };

  let rows: HoldingRow[];
  let centreLabel = "Total";
  let centre: number | null = data.total;
  let centreCcy: Ccy = "IDR";
  let empty: [string, string] | null = null;
  if (view === "main") {
    rows = mainRows(data);
  } else if (view === "liquid") {
    const l = liquidRows(data.liquid_accounts, ccy, data.liquid_total);
    rows = l.rows;
    centreLabel = "Liquid";
    centre = l.centre;
    centreCcy = ccy;
    if (rows.length === 0) empty = ["No liquid accounts yet.", "Add one in Settings › Accounts."];
  } else {
    rows = by === "platform" ? platformRows(data.investment_groups) : categoryRows(data.investment_groups);
    centreLabel = "Investment";
    centre = data.investment_total;
    if (data.investment_groups.length === 0) {
      empty = [
        "No investment platforms yet.",
        "Add a platform and a holding on the Investments page to see it here.",
      ];
    }
  }

  const centreText = fmtShort(centre, centreCcy);
  const slices = rows.filter((r) => r.value != null && r.value > 0);
  const onSlice = (r: HoldingRow) => {
    if (r.drill) go(r.drill);
    else if (r.href) router.push(r.href);
  };

  // Gated like NetWorthTrendChart: the automated pane is "hidden" and never fires
  // rAF, so an animated Pie would stay blank there. Gate the animation, not the render.
  const animate =
    typeof window !== "undefined" &&
    document.visibilityState !== "hidden" &&
    !window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  return (
    <section
      aria-label="Holdings"
      style={{
        ...card,
        marginBottom: 0,
        display: "flex",
        flexDirection: "column",
        alignSelf: "stretch",
        // contain:size stops this card from growing the row, so the Cashflow
        // card sets the height; 520 is the height when the cards stack.
        contain: "size",
        boxSizing: "border-box", // so minHeight counts the padding
        minHeight: 520,
      }}
    >
      <div style={{ fontSize: 14, fontWeight: 600, minHeight: 30, marginBottom: 12, display: "flex", alignItems: "center" }}>
        {view === "main" ? (
          "Holdings"
        ) : (
          <span>
            <button type="button" onClick={() => go("main")} style={crumb}>
              ‹ Holdings
            </button>
            <span style={{ color: tokens.color.muted2, margin: "0 4px" }}>/</span>
            {view === "liquid" ? "Liquid" : "Investment"}
          </span>
        )}
      </div>

      {view === "liquid" && (
        <div style={{ display: "flex", justifyContent: "center", margin: "-4px 0 6px" }}>
          <Pills small label="Liquid currency" options={CCY_OPTIONS} value={ccy} onChange={setCcy} />
        </div>
      )}

      {view === "investment" && (
        <div style={{ display: "flex", justifyContent: "center", margin: "-4px 0 6px" }}>
          <Pills small label="Investment grouping" options={BY_OPTIONS} value={by} onChange={setBy} />
        </div>
      )}

      <div
        role="img"
        aria-label={`${centreLabel} ${centreText}`}
        style={{ position: "relative", width: SIZE, height: SIZE, margin: "4px auto 14px", flexShrink: 0 }}
      >
        <PieChart width={SIZE} height={SIZE} accessibilityLayer={false}>
          <Pie
            key={`${view}:${ccy}:${by}`}
            data={slices.length ? slices : [{ key: "none", value: 1, color: tokens.color.border2 }]}
            dataKey="value"
            nameKey="name"
            innerRadius={54}
            outerRadius={74}
            startAngle={90}
            endAngle={-270}
            paddingAngle={slices.length > 1 ? 1.5 : 0}
            stroke="none"
            isAnimationActive={animate}
            animationDuration={600}
          >
            {(slices.length ? slices : [null]).map((r) =>
              r ? (
                <Cell
                  key={r.key}
                  fill={r.color}
                  fillOpacity={hovered && hovered !== r.key ? 0.35 : 1}
                  cursor={r.drill || r.href ? "pointer" : "default"}
                  onMouseEnter={() => setHovered(r.key)}
                  onMouseLeave={() => setHovered(null)}
                  onClick={() => onSlice(r)}
                />
              ) : (
                <Cell key="none" fill={tokens.color.border2} />
              )
            )}
          </Pie>
        </PieChart>
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
          <span style={{ fontSize: 11, color: tokens.color.muted3 }}>{centreLabel}</span>
          <span style={{ fontSize: 17, fontWeight: 600 }}>
            {centre == null ? "—" : <RollingNumber value={centre} format={(n) => fmtShort(n, centreCcy)} />}
          </span>
        </div>
      </div>

      <div style={{ flex: 1, minHeight: 0, overflowY: "auto" }}>
        {empty && (
          <div style={{ paddingTop: 10 }}>
            <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 6 }}>{empty[0]}</div>
            <div style={{ color: tokens.color.muted, fontSize: 14 }}>{empty[1]}</div>
          </div>
        )}
        {rows.map((r, i) => (
          <Row
            key={r.key}
            row={r}
            first={i === 0}
            hot={hovered === r.key}
            setHovered={setHovered}
            onDrill={onSlice}
          />
        ))}
      </div>
    </section>
  );
}

function Row({
  row,
  first,
  hot,
  setHovered,
  onDrill,
}: {
  row: HoldingRow;
  first: boolean;
  hot: boolean;
  setHovered: (k: string | null) => void;
  onDrill: (r: HoldingRow) => void;
}) {
  const interactive = !!(row.drill || row.href);
  const style: React.CSSProperties = {
    width: "100%",
    display: "flex",
    alignItems: "center",
    // Wraps in a very narrow card, so a long amount drops below the name
    // instead of squeezing the name to nothing.
    flexWrap: "wrap",
    gap: "2px 10px",
    padding: "10px 0",
    border: "none",
    borderTop: first ? "none" : `1px solid ${tokens.color.borderInner}`,
    background: hot && interactive ? tokens.color.inputBg : "none",
    textAlign: "left",
    font: "inherit",
    fontSize: 13,
    color: tokens.color.ink,
    fontVariantNumeric: "tabular-nums",
    cursor: interactive ? "pointer" : "default",
  };
  const body = (
    <>
      <i
        aria-hidden="true"
        style={{ width: 10, height: 10, borderRadius: 3, flexShrink: 0, background: row.color }}
      />
      <span style={{ display: "flex", flexDirection: "column", flex: "1 1 80px", minWidth: 0 }}>
        <span title={row.name} style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          {row.name}
        </span>
        {row.sub && (
          <small
            title={row.sub}
            style={{ fontSize: 11, color: tokens.color.muted3, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}
          >
            {row.sub}
          </small>
        )}
        {row.stale && (
          <small style={{ fontSize: 11, color: tokens.color.muted3 }}>{row.stale}</small>
        )}
      </span>
      <b
        title={row.title}
        style={{
          marginLeft: "auto",
          fontWeight: 600,
          whiteSpace: "nowrap",
          color: row.negative ? tokens.color.terracotta : undefined,
        }}
      >
        {row.amount}
      </b>
      <em
        style={{
          fontStyle: "normal",
          color: tokens.color.muted3,
          width: 32,
          textAlign: "right",
          fontSize: 12,
          flexShrink: 0,
        }}
      >
        {row.share}
      </em>
      {interactive && (
        <span aria-hidden="true" style={{ color: tokens.color.muted3, fontSize: 16, width: 8 }}>
          ›
        </span>
      )}
    </>
  );
  const hover = { onMouseEnter: () => setHovered(row.key), onMouseLeave: () => setHovered(null) };
  // A platform row navigates, so it is a real link; drill rows are buttons.
  if (row.href) {
    return (
      <Link href={row.href} style={{ ...style, textDecoration: "none" }} {...hover}>
        {body}
      </Link>
    );
  }
  return interactive ? (
    <button type="button" onClick={() => onDrill(row)} style={style} {...hover}>
      {body}
    </button>
  ) : (
    <div style={style} {...hover}>
      {body}
    </div>
  );
}
