---
phase: 8
name: Design Foundation + App Shell
requirements: [UIR-01, UIR-02, UIR-03]
wave: 1
depends_on: [7]
autonomous: true
files_modified:
  - ui/app/styles.ts
  - ui/app/layout.tsx
  - ui/app/components/Nav.tsx
  - ui/app/page.tsx
---

# Phase 8 — Design Foundation + App Shell

**Goal:** A single source-of-truth "paper" design-token layer exists, the
Instrument Serif + Hanken Grotesk fonts load app-wide, and the app shell is
converted from the old dark top-nav to the mockup's centered rounded panel with
a left sidebar — so every later page restyle has tokens + a shell to build on.

Design source: `.planning/design/monai-redesign.dc.html`.

## Tasks

### T1 — Paper token layer (UIR-01)
Rewrite `ui/app/styles.ts`: export a `tokens` object (palette, font-family vars,
radii, spacing) as the single source of truth, and re-skin the existing shared
constants (`card`, `input`, `btn`, `label`, `dangerBtn`, `chartColors`) to the
paper palette **keeping the same export names** so downstream pages keep compiling.

- read_first: ui/app/styles.ts
- Palette (from mockup): page `#ece8e1`, panel `#f7f5f1`, sidebar `#f2efe8`,
  card `#fff`, ink `#23201b`, ink-text `#f2efe8`, green `#2f6f4f`,
  terracotta `#b5503f`, gold `#d8b26a`, sage `#5a8f73`, muted `#8b8474`/`#a49c8c`,
  borders `#e7e1d5`/`#e2dccf`/`#f0ece3`.
- Fonts referenced via CSS vars `--font-serif` / `--font-sans`.
- chartColors → paper categorical `[#2f6f4f,#5a8f73,#d8b26a,#8fae9c,#b5503f,#c8c1b5]`.
- acceptance: styles.ts exports `tokens`; `btn.background` is a token value not
  `#3b82f6`; `card.background` is `#fff`; tsc passes.

### T2 — Load fonts + paper page shell (UIR-02, UIR-03 partial)
Rewrite `ui/app/layout.tsx`: load Instrument Serif + Hanken Grotesk via
`next/font/google` (self-hosted, privacy-aligned), expose them as
`--font-serif`/`--font-sans` CSS vars, set body background to cream `#ece8e1` and
default font to Hanken Grotesk, and wrap `<Nav/>` + `{children}` in a centered
rounded panel (`#f7f5f1`, hairline border, soft shadow) with the sidebar and a
scrolling `<main>`.

- read_first: ui/app/layout.tsx, ui/app/styles.ts
- acceptance: body bg is cream; panel is a rounded bordered `#f7f5f1` container;
  fonts load (no system fallback); dev server compiles.

### T3 — Sidebar nav (UIR-03)
Rewrite `ui/app/components/Nav.tsx` from a sticky top bar into the mockup's left
sidebar: 236px, serif "monai" wordmark + green dot, uppercase "Menu" label,
icon+label nav items (Cashflow/Chat/Investments/Settings) with a dark active pill
and inactive styling, and a "synced" status footer card. Inline the mockup's SVG
icons.

- read_first: ui/app/components/Nav.tsx, ui/app/styles.ts
- acceptance: sidebar renders wordmark + 4 icon nav items + footer card; active
  route shows the dark pill; usePathname still drives active state.

### T4 — Default route (UIR-03)
Point `ui/app/page.tsx` root redirect to `/cashflow` (the mockup's default tab)
instead of `/chat`.

- read_first: ui/app/page.tsx
- acceptance: `/` redirects to `/cashflow`.

## must_haves
- Paper tokens are the single source of truth in styles.ts (UIR-01).
- Both fonts render app-wide (UIR-02).
- Sidebar shell matches the mockup on all four routes; cream bg + rounded panel (UIR-03).
- No routing/nav regressions; existing Playwright specs pass.

## Verification
- `npx tsc --noEmit` clean in ui/.
- Dev server compiles; `/cashflow`, `/chat`, `/investments`, `/settings` all render
  inside the sidebar shell (preview screenshot).
- `npx playwright test` — existing specs pass (or unchanged pass/skip baseline).
