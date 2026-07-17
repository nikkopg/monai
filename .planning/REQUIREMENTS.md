# Requirements — Milestone v1.1: UI Redesign ("Paper" Aesthetic)

Scope: a **visual-only** re-skin of the existing four-page app to the Claude Design
mockup at `.planning/design/monai-redesign.dc.html` (reference screenshot:
`.planning/design/screenshots/cashflow.png`). No backend, schema, API, or data-shape
changes. Every existing v1.0 behavior must survive unchanged. The mockup's USD/fake
numbers are illustrative — real data stays IDR and wired to the live endpoints.

Design language (from the mockup, authoritative):
- Palette: page `#ece8e1`, panel `#f7f5f1`, sidebar `#f2efe8`, ink `#23201b`,
  green accent `#2f6f4f`, terracotta (expenses) `#b5503f`, muted text `#8b8474`/`#a49c8c`,
  hairline borders `#e7e1d5`/`#e2dccf`/`#f0ece3`.
- Type: Instrument Serif (headings, wordmark, hero numbers), Hanken Grotesk (body/UI).
- Shape: 14–22px radii, soft shadows, `font-variant-numeric: tabular-nums` on money.

## v1.1 Requirements

### Foundation

- [ ] **UIR-01**: A shared design-token layer (palette, type families, radii, spacing) lives in `ui/app/styles.ts` as the single source of truth; page components reference tokens, not hard-coded hex.
- [ ] **UIR-02**: Instrument Serif + Hanken Grotesk are loaded and applied app-wide — serif for headings/wordmark/hero figures, grotesk for body and controls.
- [ ] **UIR-03**: The app shell matches the mockup — cream page background, centered rounded panel, and a left sidebar with the serif "monai" wordmark, uppercase "Menu" label, icon+label nav items with active (dark pill) / inactive states, and a "synced" status footer card.

### Pages

- [ ] **UIR-04**: The Cashflow page is restyled to the mockup — dark net-worth hero with delta pill, period segmented control, 6-month income/expense trend, three stat cards (income / expenses / net), spending-by-category donut + legend, accounts list, and recent-transactions list — all bound to real data.
- [ ] **UIR-05**: The Chat page is restyled to the mockup — right-aligned user bubbles, assistant answer block with the monai wordmark, collapsible "how I got this" tool-trace, a confirm-before-write proposal card (approve/reject), and a sticky composer — bound to the real chat and proposal flow.
- [ ] **UIR-06**: The Investments page is restyled to the mockup — dark total-value hero with all-time delta, allocation donut + legend, and a holdings table (asset badge / units / price / value / return) — bound to real holdings.
- [ ] **UIR-07**: The Settings page is restyled to the mockup — provider segmented control, model input, API-key cards, preferences (base currency, price source), and a live-refresh toggle with save actions — bound to the real settings endpoints.

### Consistency & Safety

- [ ] **UIR-08**: Secondary UI surfaces not drawn in the mockup (CRUD modals, CSV upload, managers, override dialogs, staleness badges, charts) adopt the new tokens so nothing looks like the old theme; each keeps its exact behavior.
- [ ] **UIR-09**: No functional regressions — all v1.0 flows (transaction/account/category CRUD, CSV import, holdings CRUD + price overrides, provider/key/preferences save, agent confirm-before-write) work identically after the restyle; existing Playwright e2e specs pass.
- [ ] **UIR-10**: The fixed 1240×820 mockup adapts gracefully to a real browser — max-width container, internal scrolling, and a usable narrow-viewport layout — without clipping or overflow.

## Future Requirements (deferred)

- QRY-01 recurring-charge / subscription detection
- QRY-02 arbitrary two-period comparison
- QRY-03 token-by-token streaming
- INVX-02 automated reksadana NAV feed

## Out of Scope

- Any backend, schema, API, or data-model change — this milestone is presentation-only.
- New pages or features beyond the four existing tabs shown in the mockup.
- Multi-currency for *spending* (stays IDR); currency switching in the redesign is visual only.
- A component-library / CSS framework migration (Tailwind, MUI, etc.) — keep the existing inline-style + `styles.ts` approach, just token-driven.
- Dark mode / theme switching — the mockup defines one "paper" theme.

## Traceability

<!-- Filled by the roadmapper: REQ-ID → Phase. -->
