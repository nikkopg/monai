// ---------------------------------------------------------------------------
// Shared design tokens + inline style objects — "paper" aesthetic (v1.1
// redesign). CLAUDE.md convention: inline React.CSSProperties only, no CSS
// framework. `tokens` below is the SINGLE SOURCE OF TRUTH for palette, type,
// radii, and spacing — pages reference these instead of hard-coding hex/px.
//
// Design source: .planning/design/monai-redesign.dc.html
// Fonts are wired as CSS variables (--font-serif / --font-sans) in layout.tsx
// via next/font, so token font families point at those vars.
// ---------------------------------------------------------------------------

export const tokens = {
  color: {
    // surfaces
    page: "#ece8e1", // app background (cream)
    panel: "#f7f5f1", // centered app panel
    sidebar: "#f2efe8", // left sidebar
    card: "#fff", // content cards
    inputBg: "#faf8f4", // form field background
    // ink / inverse
    ink: "#23201b", // primary text + dark hero cards
    inkText: "#f2efe8", // text on dark surfaces
    inkTextMuted: "#b6ae9d", // muted text on dark surfaces
    // brand + semantic
    green: "#2f6f4f", // accent / income / positive
    greenDark: "#23543c", // hover
    terracotta: "#b5503f", // expenses / negative / destructive
    gold: "#d8b26a",
    sage: "#5a8f73",
    sageLight: "#8fae9c",
    // text
    text: "#23201b",
    textSoft: "#34302a",
    muted: "#8b8474",
    muted2: "#a49c8c",
    muted3: "#6f6857",
    // hairlines / borders
    border: "#e7e1d5",
    border2: "#e2dccf",
    borderInner: "#f0ece3",
    // accent chips
    chipGreenBg: "rgba(129,196,158,.16)",
    chipGreenText: "#9fdcb6",
    // transaction / icon tints
    tintWarm: "#f4ede0",
    tintGreen: "#e6efe9",
    tintNeutral: "#eef1ec",
    // sidebar footer card
    footerCard: "#eae5db",
  },
  font: {
    serif: "var(--font-serif), 'Instrument Serif', Georgia, serif",
    sans: "var(--font-sans), 'Hanken Grotesk', system-ui, sans-serif",
  },
  radius: {
    sm: 10,
    md: 14,
    lg: 18,
    xl: 22,
    pill: 999,
  },
  space: {
    xs: 6,
    sm: 8,
    md: 14,
    lg: 18,
    xl: 24,
  },
  shadow: {
    panel:
      "0 1px 2px rgba(40,34,24,.05), 0 30px 60px -30px rgba(40,34,24,.28)",
    card: "0 1px 2px rgba(40,34,24,.05)",
  },
} as const;

// ---------------------------------------------------------------------------
// Shared style objects — re-skinned to the paper palette. Export names are
// unchanged from the v1.0 baseline so every page/modal that imports them keeps
// compiling; only the values changed.
// ---------------------------------------------------------------------------

export const card: React.CSSProperties = {
  background: tokens.color.card,
  border: `1px solid ${tokens.color.border}`,
  borderRadius: tokens.radius.lg,
  padding: "22px 24px",
  marginBottom: tokens.space.lg,
};

export const input: React.CSSProperties = {
  background: tokens.color.inputBg,
  border: `1px solid ${tokens.color.border2}`,
  borderRadius: tokens.radius.sm,
  color: tokens.color.text,
  padding: "11px 14px",
  fontSize: 14,
  width: "100%",
  boxSizing: "border-box",
};

// Primary action button — green (Save / Approve in the mockup).
export const btn: React.CSSProperties = {
  background: tokens.color.green,
  color: "#fff",
  border: "none",
  borderRadius: tokens.radius.sm,
  padding: "10px 22px",
  fontSize: 14,
  cursor: "pointer",
  fontWeight: 600,
};

// Dark call-to-action button — ink (Add transaction / Ask in the mockup).
export const btnDark: React.CSSProperties = {
  ...btn,
  background: tokens.color.ink,
  color: tokens.color.inkText,
  borderRadius: tokens.radius.pill,
  padding: "8px 16px",
  fontSize: 13,
};

// Secondary / neutral button (Reject in the mockup).
export const btnGhost: React.CSSProperties = {
  ...btn,
  background: tokens.color.sidebar,
  color: tokens.color.muted3,
  border: `1px solid ${tokens.color.border2}`,
};

export const label: React.CSSProperties = {
  fontSize: 12,
  color: tokens.color.muted2,
  marginBottom: 7,
  display: "block",
};

// Destructive variant of `btn` — delete/merge-confirm buttons. Spreads `btn`;
// only the background changes to the terracotta token.
export const dangerBtn: React.CSSProperties = {
  ...btn,
  background: tokens.color.terracotta,
};

// Fixed categorical palette for the spending-by-category donut and any other
// categorical chart. Cycle via chartColors[i % chartColors.length] for >6
// categories. From the mockup's donut colors.
export const chartColors = [
  tokens.color.green,
  tokens.color.sage,
  tokens.color.gold,
  tokens.color.sageLight,
  tokens.color.terracotta,
  "#c8c1b5",
];
