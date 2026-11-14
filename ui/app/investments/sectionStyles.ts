import { tokens } from "../styles";

// One style for every Investments section title, matching Cashflow's 14px / 600 card titles.
export const sectionTitle: React.CSSProperties = {
  fontSize: 14,
  fontWeight: 600,
  margin: 0,
};

// Muted header row shared by the holdings and closed-positions tables.
export const columnHeader: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 400,
  color: tokens.color.muted3,
  padding: "8px 0",
  borderBottom: `1px solid ${tokens.color.borderInner}`,
};
