// ---------------------------------------------------------------------------
// Shared inline style objects — dark palette (CLAUDE.md: inline
// React.CSSProperties only, no CSS framework).
//
// Extracted from the original single-page ui/app/page.tsx so /chat,
// /cashflow, /investments, /settings, and the shared Nav all import the same
// constants instead of redefining them (Phase 3, 03-CONTEXT.md).
//
// Spacing values normalized to the 8-point scale (03-UI-SPEC.md § Spacing
// Scale) on extraction: card padding/marginBottom 20 -> 24, input padding
// "10px 12px" -> "8px 12px", btn padding "10px 18px" -> "8px 16px". Colors,
// typography, and layout are otherwise unchanged from the shipped baseline.
// ---------------------------------------------------------------------------

export const card: React.CSSProperties = {
  background: "#1a1d23",
  border: "1px solid #2a2e37",
  borderRadius: 12,
  padding: 24,
  marginBottom: 24,
};

export const input: React.CSSProperties = {
  background: "#0f1115",
  border: "1px solid #2a2e37",
  borderRadius: 8,
  color: "#e6e8eb",
  padding: "8px 12px",
  fontSize: 14,
  width: "100%",
  boxSizing: "border-box",
};

export const btn: React.CSSProperties = {
  background: "#3b82f6",
  color: "white",
  border: "none",
  borderRadius: 8,
  padding: "8px 16px",
  fontSize: 14,
  cursor: "pointer",
  fontWeight: 600,
};

export const label: React.CSSProperties = {
  fontSize: 12,
  color: "#9aa0a6",
  marginBottom: 4,
  display: "block",
};
