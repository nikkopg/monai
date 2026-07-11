"use client";

// ---------------------------------------------------------------------------
// StalenessBadge (INV-05) — renders a price's freshness. The staleness flag is
// SERVER-computed (GET /investments/summary → per-holding is_stale); this
// component NEVER computes a TTL. It only formats the "as of" time and swaps a
// dot colour + adds a "· stale" pill when the server says the price is stale.
// ---------------------------------------------------------------------------

type Props = {
  fetchedAt: string | null;
  source: string | null;
  isStale: boolean;
};

const FRESH_DOT = "#9aa0a6"; // muted
const STALE_DOT = "#f87171"; // destructive
const BORDER = "#2a2e37";

// Hand-rolled relative-time helper (~15 lines, no npm dep). Coarse buckets are
// plenty for an "as of" label.
function relativeTime(iso: string | null): string {
  if (!iso) return "never";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "unknown";
  const secs = Math.floor((Date.now() - then) / 1000);
  if (secs < 60) return "just now";
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

export default function StalenessBadge({ fetchedAt, source, isStale }: Props) {
  const label = `Price as of ${relativeTime(fetchedAt)}`;
  const dot = (
    <span
      aria-hidden
      style={{
        display: "inline-block",
        width: 6,
        height: 6,
        borderRadius: "50%",
        background: isStale ? STALE_DOT : FRESH_DOT,
        marginRight: 5,
      }}
    />
  );

  if (!isStale) {
    return (
      <span style={{ fontSize: 11, color: FRESH_DOT, whiteSpace: "nowrap" }}>
        {dot}
        {label}
        {source ? ` · ${source}` : ""}
      </span>
    );
  }

  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        fontSize: 11,
        color: STALE_DOT,
        border: `1px solid ${BORDER}`,
        borderRadius: 999,
        padding: "1px 6px",
        whiteSpace: "nowrap",
      }}
    >
      {dot}
      {label} · stale
    </span>
  );
}
