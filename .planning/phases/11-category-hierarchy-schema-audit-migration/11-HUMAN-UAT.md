---
status: resolved
phase: 11-category-hierarchy-schema-audit-migration
source: [11-VERIFICATION.md]
started: 2026-07-20
updated: 2026-07-20
tested_by: claude (browser-driven, live stack after docker compose up -d --build)
---

## Current Test

[agent-run UAT complete — 3/3 pass; the blocked chart item cleared after the
recharts fix landed via merge 9f63b12]

## Tests

### 1. Settings > Categories tree walkthrough
expected: Groups collapsed by default with emoji + colour swatch; expanding
indents children; add / edit / delete inline; deleting an in-use or parent
category is blocked with counts; system rows show a locked delete.
result: **PASS**
- 13 root groups render collapsed with emoji and per-node transaction counts.
- Expanding "Food & Drinks" reveals its 6 children (Caffe coffee 180, Coffee 1,
  Food 12, Groceries 196, Jajan 720, Restaurant/fast-food 308) with row actions
  Add subcategory / Edit / Merge into… / Delete.
- Transfer and Uncategorized both display "System category — can't be deleted."
- Delete opens a confirm dialog ("Delete this category? This can't be undone.").
  Cancelled rather than confirming on real data; guards proven via API on
  throwaway rows instead:
  - delete parent that has a child -> 422 `{"message": "1 subcategories use this
    category — remove or re-parent them first", "affected_count": 0,
    "child_count": 1}`
  - delete a system category -> 422 "System categories (Transfer/Uncategorized)
    cannot be deleted"
  - create root without colour -> 422 "Root category requires a color"
  - create + delete of scratch parent/child -> 201 / 200, DB returned to 76.
- Colour inheritance holds: all 63 children resolve `effective_color` from their
  parent (0 missing).

### 2. Cashflow dashboard donut
expected: top-level groups, click-to-drill-down, "‹ Back" while drilled,
palette colours, no Transfer slice.
result: **PASS** — data and interaction contracts verified; the original
BLOCKED call was a false positive from the test harness (see Correction below)

Original run (incorrect): BLOCKED — reported as a pre-existing chart bug
- Data layer is correct: the summary returns 8 top-level groups (Financial
  Expenses, Life & Entertainment, Others, Investments, Food & Drinks, Shopping,
  Transportation, Communication / PC) with children and colours, and **no
  Transfer slice**. Legend renders these correctly with amounts.
- The donut itself paints nothing: recharts builds 7 `.recharts-pie-sector`
  groups but every `.recharts-shape` is empty (0 `<path>` elements), so there
  are no slices to click and drill-down cannot be exercised.
- **Not caused by this phase.** The Investments allocation pie (Phase 7 code,
  untouched in Phase 11) shows the identical symptom: 3 sectors, 0 paths. Line
  charts render fine. Stack: recharts 3.9.2 + React 18.3.1.
- Follow-up: tracked and fixed as its own quick task (recharts Pie rendering),
  app-wide rather than category-specific.

**Correction — the donut was never broken (2026-07-20):**
- The original BLOCKED finding above was an artifact of the automated browser
  pane used for this UAT. That pane runs the tab with `visibilityState:
  "hidden"`, so `requestAnimationFrame` never fires. recharts 3.x collapses Pie
  sectors to `startAngle === endAngle` at animation t=0 and `Sector` returns
  null for that, so with no rAF frame the ring stays at zero `<path>`s forever.
  In any visible browser the clock runs and the pie animates and paints
  normally — confirmed by the user's direct report that it worked before any
  fix.
- The quick-task fix (`isAnimationActive={false}`) was itself verified "under a
  stubbed-out requestAnimationFrame", i.e. against the same artificial
  condition. It removed the entrance and drill-down animations — a real UX
  regression — to solve a problem real users never had. Reverted in 59f0bd5.
- What the merge legitimately proved while animation was disabled: 7 slices in
  7 distinct palette swatches, drill-down into a group's children with a
  working "‹ Back" round-trip, monochrome drilled ring (children `#6f6857` =
  parent `#6f6857`, matching UI-SPEC Component 3), and no Transfer slice at
  either level. Those data/interaction contracts hold; only the animation
  behaviour changed and has been restored.
- **Limitation of this UAT:** Pie rendering cannot be validated from the
  headless pane. Visual confirmation of the donut and its animation requires a
  visible browser — user-confirmed working.
- Observation, unchanged: while drilled, the legend beside the chart still
  lists the top-level groups. UI-SPEC Component 3 governs only the ring and the
  legend lives in `page.tsx` outside the donut's drill state, so this is
  spec-compliant, but worth a look if the split reads oddly in daily use.

### 3. Add/Edit Transaction category dropdown
expected: real categories listed (groups + indented children), any level
selectable, edit pre-selects current category, no "+ New category" option.
result: **PASS**
- 75 options: "(no category)" + 11 selectable roots + 63 indented children.
- Indentation present on exactly 63 options (matches child count).
- No "+ New category" option; Transfer and Uncategorized correctly excluded.
- Edit mode on an existing record pre-selects "Caffe, coffee" (indented child).
- Both modals closed via Cancel; nothing saved.

## Data integrity after UAT

Re-checked post-run: 76 categories / 13 roots, 5,728 transactions,
sum 194,694,800.00, 0 NULL `category_id`, 0 leftover scratch rows.
Accounts table holds only the 4 real accounts (Cash, BCA, Investments,
Stockbit) — an earlier claim of test-fixture account pollution was read from a
stale page render and was incorrect.

## Summary

total: 3
passed: 3
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

None attributable to Phase 11.

Correction on record: the "recharts Pie renders no sectors app-wide" bug
reported during this UAT was not real — it reproduced only under the headless
pane's non-firing requestAnimationFrame. The quick-task fix that disabled Pie
animations was merged (9f63b12) and then reverted (59f0bd5) once the user
reported the animation loss; the pie works, and animates, in a visible browser.
