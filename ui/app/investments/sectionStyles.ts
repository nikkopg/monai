import { tokens } from "../styles";

// One style for every Investments section title, matching Cashflow's 14px / 600 card titles.
export const sectionTitle: React.CSSProperties = {
  fontSize: "var(--fs-h3, 14px)",
  fontWeight: 600,
  margin: 0,
};

// Muted header row shared by the holdings and closed-positions tables, and the
// tinted platform / asset-type group rows under it (inputBg is the mock's tint).
export const columnHeader: React.CSSProperties = {
  fontSize: "var(--fs-xs, 12px)",
  fontWeight: 400,
  color: tokens.color.muted3,
  padding: "8px 0",
  borderBottom: `1px solid ${tokens.color.borderInner}`,
};

export const groupRow: React.CSSProperties = {
  background: tokens.color.inputBg,
  fontWeight: 600,
  fontSize: "var(--fs-body, 14px)",
  fontVariantNumeric: "tabular-nums",
};
