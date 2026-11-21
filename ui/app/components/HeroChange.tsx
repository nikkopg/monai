import { tokens } from "../styles";

// Change line under a dark hero total (Cashflow net worth, Investments value):
// "▲ 6.8%  +9,712,000 · since Dec 2025". `from`/`to` are the first and last
// points of the chart under it, so the line always matches the selected range.
// No % when the start is zero or negative, when it would pass 1000% (a tiny
// first balance, e.g. net worth on All), or when `showPct` is off (P&L): a
// percentage of that means nothing, so only the signed amount shows.
// The arrow is decorative: the amount's sign carries the direction.
// The amount carries .amt, so hide amounts blurs it; the percentage stays.
export default function HeroChange({
  from,
  to,
  since,
  showPct = true,
}: {
  from: number;
  to: number;
  since: string;
  showPct?: boolean;
}) {
  const delta = to - from;
  const up = delta >= 0;
  const color = up ? tokens.color.chipGreenText : "#e6a99c";
  const amount = new Intl.NumberFormat("en-US", { signDisplay: "always" }).format(Math.round(delta));
  const ratio = from > 0 ? Math.abs(delta / from) : Infinity;
  const pct = showPct && ratio <= 10 ? `${(ratio * 100).toFixed(1)}%` : null;

  return (
    <div
      data-testid="hero-change"
      style={{
        display: "flex",
        alignItems: "center",
        flexWrap: "wrap",
        gap: 8,
        marginTop: 10,
        fontSize: "var(--fs-pill, 13px)",
        fontVariantNumeric: "tabular-nums",
      }}
    >
      {pct && (
        <span
          style={{
            display: "inline-flex",
            gap: 4,
            padding: "3px 10px",
            borderRadius: 999,
            fontWeight: 600,
            color,
            background: up ? "rgba(159,217,184,.12)" : "rgba(230,169,156,.12)",
          }}
        >
          <span aria-hidden="true">{up ? "▲" : "▼"}</span>
          {pct}
        </span>
      )}
      <span style={{ color: pct ? tokens.color.inkTextMuted : color }}>
        <span className="amt">{amount}</span> · since {since}
      </span>
    </div>
  );
}
