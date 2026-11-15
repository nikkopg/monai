import type { CSSProperties, ReactNode } from "react";

// ---------------------------------------------------------------------------
// Skeleton — loading placeholders (quick 261115-hfb). One role="status" wrapper
// per page/section named by its old loading copy; Bone and DrawLine are dumb
// shapes whose colour and motion come from globals.css via the ancestor class
// (.pulse on Investments/Cashflow, .shimmer elsewhere, .bone-dark on an ink
// hero). Skeletons render no text or figures. No aria-live: the inbox spec
// counts explicit live regions.
// ---------------------------------------------------------------------------

export default function Skeleton({
  label,
  pulse,
  style,
  children,
}: {
  label: string;
  pulse?: boolean;
  style?: CSSProperties;
  children?: ReactNode;
}) {
  return (
    <div
      role="status"
      aria-label={label}
      aria-busy="true"
      className={pulse ? "pulse" : "shimmer"}
      style={style}
    >
      {children}
    </div>
  );
}

export function Bone({
  w,
  h,
  r = 8,
}: {
  w: number | string;
  h: number;
  r?: number | string;
}) {
  return <div className="bone" style={{ width: w, height: h, borderRadius: r }} />;
}

// The hero history line drawing itself (globals.css .draw-line path).
export function DrawLine({ height }: { height: number }) {
  return (
    <svg
      className="draw-line"
      viewBox="0 0 1000 140"
      preserveAspectRatio="none"
      width="100%"
      height={height}
      aria-hidden="true"
    >
      <path d="M0,100 C80,96 120,70 200,72 S320,60 400,64 S520,58 600,66 S740,74 820,70 S940,64 1000,40" />
    </svg>
  );
}
