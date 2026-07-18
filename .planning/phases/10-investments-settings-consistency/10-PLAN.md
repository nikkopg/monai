---
phase: 10
name: Investments + Settings + Consistency Sweep
requirements: [UIR-06, UIR-07, UIR-08, UIR-09, UIR-10]
wave: 1
depends_on: [8, 9]
autonomous: true
files_modified:
  - ui/app/investments/page.tsx
  - ui/app/settings/page.tsx
  - ui/app/globals.css
  - ui/app/layout.tsx
  - ui/app/components/Nav.tsx
  - ui/app/cashflow/page.tsx
  - ui/e2e/settings.spec.ts
  - "ui/app/**/(11 secondary components swept to paper)"
  - "deleted: ui/app/cashflow/charts/IncomeExpenseBar.tsx"
---

# Phase 10 — Investments + Settings + Consistency Sweep

**Goal:** The remaining two pages match the mockup, every secondary surface
adopts the paper tokens, the layout reflows on narrow viewports, and the full
v1.0 behavior surface is regression-free.

## Tasks

### T1 — Investments page (UIR-06)
Rewrite `investments/page.tsx` to the mockup, preserving the full feature set
(price refresh, unrealized/realized P&L, allocation asset-type/platform toggle,
value history, platform-grouped holdings, set-price/edit/delete, PlatformManager,
3 modals): "Portfolio" eyebrow + serif h1; dark total-value hero with unrealized
delta pill + all-time %; allocation donut + legend + toggle; P&L stat cards;
value-history card; holdings tables with mockup columns (Asset badge / Units /
Price / Value / Return%). All bound to real `/api/investments/*`.

### T2 — Settings page (UIR-07)
Rewrite `settings/page.tsx` to the mockup: eyebrow + serif h1; three paper cards
with subtitles; provider **segmented control** (ollama/claude/openai); model
input; API-key cards; preferences (base currency + price-source select). Kept the
exact card titles, Save-button labels, and helper text the e2e asserts. Omitted
the mockup's live-refresh toggle (no backend field; presentation-only scope; a
non-persisting toggle would be fake data).

### T3 — Consistency sweep (UIR-08)
Re-theme the 11 secondary components (cashflow AccountManager/CategoryManager/
ConfirmDialog/CsvUpload; investments AllocationPieChart/HoldingModal/
HoldingOverrideModal/PlatformManager/PriceOverrideDialog/StalenessBadge/
ValueHistoryChart) by remapping every remaining old dark-theme hex → paper token
values. They already inherit the paper `card`/`input`/`btn`. Deleted the now-dead
`IncomeExpenseBar.tsx`.

### T4 — Responsive (UIR-10)
Add `globals.css` + shell classNames: below 760px trim frame padding; below 560px
collapse the sidebar to an icon rail (hide labels/wordmark/footer). Convert the
Cashflow fixed grids and the Investments/Settings grids to
`repeat(auto-fit, minmax(min(100%, Npx), 1fr))` so multi-column rows stack on
narrow viewports with no horizontal overflow.

### T5 — Regression (UIR-09)
Update `settings.spec` for the provider segmented control; keep every behavioral
assertion. Full e2e suite green.

## must_haves
- Investments + Settings match the mockup, bound to real data (UIR-06/07).
- No secondary surface shows old-theme colors; behavior unchanged (UIR-08).
- No functional regressions; full e2e green (UIR-09).
- Narrow viewport reflows with no horizontal overflow (UIR-10).

## Verification
- `npx tsc --noEmit` clean; `npx playwright test` 27/27.
- Preview: investments (real portfolio) + settings (real config) render per mockup;
  375px reflow → sidebar icon-rail, scrollWidth == viewport (no overflow).
