---
phase: 11-category-hierarchy-schema-audit-migration
plan: 07
subsystem: api
tags: [fastapi, pydantic, nextjs, react, recharts, typescript]

# Dependency graph
requires:
  - phase: 11-04
    provides: hierarchy-aware spending_by_category tool (rows + children rollup, Transfer/system exclusion)
  - phase: 11-06
    provides: categoryPalette tokens and Settings > Categories tree manager conventions
provides:
  - CashflowSummary.by_category as a rich CategoryRollup shape (id/name/color/icon/total/children)
  - _category_rollup() helper joining hierarchy id/color/icon onto tools.py's name-keyed rollup
  - CategoryDonut drill-down (top groups -> subcategories) with identity-stable colors and a Back affordance
affects: [phase-16-category-picker, phase-17-category-picker]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Backend join-by-name pattern: spending_by_category returns name-keyed rows/children; main.py's _category_rollup joins id/color/icon per-root (scoped to avoid cross-root name collisions) rather than teaching tools.py about IDs"
    - "Frontend local-useState drill-down (no routing, no library) for a two-level chart, mirroring the existing recursive-tree convention from 11-06"

key-files:
  created: []
  modified:
    - backend/schemas.py
    - backend/main.py
    - backend/tests/test_cashflow_summary.py
    - ui/app/cashflow/charts/CategoryDonut.tsx
    - ui/app/cashflow/page.tsx

key-decisions:
  - "Color/icon join happens in main.py (per-root descendant scan), not in tools.py — keeps tools.py's tuple-based chat/agent contract from 11-04 untouched"
  - "Donut legend stays at top-level always; only the ring itself drills down (per UI-SPEC Component 3, which specifies the Back affordance lives with the chart, not the legend)"
  - "Child swatch inherits root color when NULL, computed via the same nearest-ancestor rule as GET /categories' effective_color"

patterns-established:
  - "CategoryRollup/CategoryRollupChild Pydantic models: reusable shape for any future rich rollup payload beyond cashflow summary"

requirements-completed: [CAT-04]

coverage:
  - id: D1
    description: "GET /cashflow/summary by_category entries are objects {id, name, color, icon, total, children} sourced from the category hierarchy, ordered by total desc, with children inheriting the parent's effective color"
    requirement: "CAT-04"
    verification:
      - kind: unit
        ref: "backend/tests/test_cashflow_summary.py#test_cashflow_summary_by_category_is_hierarchy_rollup"
        status: pass
    human_judgment: false
  - id: D2
    description: "No rollup entry (root or child) is ever named Transfer (D-12) — filtered at the SQL layer, not hidden client-side"
    requirement: "CAT-04"
    verification:
      - kind: unit
        ref: "backend/tests/test_cashflow_summary.py#test_cashflow_summary_by_category_is_hierarchy_rollup"
        status: pass
    human_judgment: false
  - id: D3
    description: "CategoryDonut renders top-level slices colored by each category's own identity swatch (not a positional chartColors cycle); a slice with children is clickable and drills into that group's subcategory breakdown in the same 150x150 ring; a '‹ Back' text link appears only while drilled and returns to the rollup"
    verification:
      - kind: unit
        ref: "cd ui && npx tsc --noEmit"
        status: pass
    human_judgment: true
    rationale: "Visual/interaction correctness (slice colors, click-to-drill, Back link rendering) requires a live render — tsc only proves the types compile, not that the chart looks/behaves right. Live check deferred to phase UAT per the plan's own acceptance criteria (docker compose up -d --build)."

# Metrics
duration: 45min
completed: 2026-07-19
status: complete
---

# Phase 11 Plan 07: Dashboard category rollup + donut drill-down Summary

**CashflowSummary.by_category is now a hierarchy-sourced CategoryRollup (id/name/color/icon/total/children), and CategoryDonut drills top-level groups into subcategory breakdowns with identity-stable swatch colors.**

## Performance

- **Duration:** ~45 min
- **Completed:** 2026-07-19T15:17:00Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- `backend/schemas.py` gained `CategoryRollupChild` and `CategoryRollup`; `CashflowSummary.by_category` is `list[CategoryRollup]` (breaking change, only consumer is the cashflow page, updated in Task 2)
- `backend/main.py` gained `_category_rollup()`, joining category id/color/icon onto plan 11-04's `spending_by_category` rows+children by root name, with per-root descendant scoping (avoids cross-root name collisions) and nearest-ancestor color inheritance for children with a NULL own color
- `CategoryDonut.tsx` rewired: slice fills come from each entry's own color (identity-stable, D-14) instead of a positional `chartColors` cycle; clicking a slice with children drills into its subcategory ring; a "‹ Back" text link (12px, muted2) appears only while drilled
- `ui/app/cashflow/page.tsx`'s `CashflowSummary`/`categoryData`/legend updated to the new object shape; dead positional `catColor()` helper removed
- New test `test_cashflow_summary_by_category_is_hierarchy_rollup` pins the object shape, child color inheritance, and the no-Transfer guarantee

## Task Commits

1. **Task 1: Rich by_category rollup in CashflowSummary** - `dbc84b0` (feat)
2. **Task 2: CategoryDonut drill-down + identity colors** - `f36fde7` (feat)

**Plan metadata:** (this commit, docs: complete plan)

## Files Created/Modified
- `backend/schemas.py` - `CategoryRollupChild`/`CategoryRollup` models; `CashflowSummary.by_category` now `list[CategoryRollup]`
- `backend/main.py` - `_category_rollup()` helper; `cashflow_summary` consumes `spending_by_category`'s rows+children keys instead of `["rows"]` tuples
- `backend/tests/test_cashflow_summary.py` - new hierarchy-rollup shape/inheritance/no-Transfer test
- `ui/app/cashflow/charts/CategoryDonut.tsx` - drill-down + Back affordance, identity colors
- `ui/app/cashflow/page.tsx` - `CategoryRollup`/`CategoryRollupChild` types, `categoryData`/legend on the new shape, removed dead `catColor()`

## Decisions Made
- Kept the id/color/icon join in `main.py` rather than pushing IDs into `tools.py`'s `spending_by_category` — that tool's tuple-based `rows`/`children` contract is shared with the chat/agent read path (11-04) and stayed untouched, per the plan's explicit "do not edit tools.py" constraint.
- Legend (outside the donut) always shows the top-level rollup; only the ring inside `CategoryDonut` drills down, matching UI-SPEC Component 3's description of the Back affordance living with the chart itself.

## Deviations from Plan

None - plan executed exactly as written. The one design judgment call (legend stays top-level while only the ring drills) was already implied by UI-SPEC Component 3's wording and is documented above, not a deviation from any stated must-have.

## Issues Encountered
None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 11's last read-path surface (dashboard donut) is now hierarchy-backed; ROADMAP criterion 4 satisfied.
- `pytest backend/tests -q`: 236 passed, 1 pre-existing failure (`test_settings.py::test_put_settings_requires_key`, documented as not-mine-to-fix in this plan's execution notes).
- `cd ui && npx tsc --noEmit`: clean.
- Live/visual verification of the drill-down interaction (colors, click, Back) is deferred to phase UAT after `docker compose up -d --build`, per the plan's own acceptance criteria.

## Self-Check: PASSED

- FOUND: backend/schemas.py
- FOUND: backend/main.py
- FOUND: backend/tests/test_cashflow_summary.py
- FOUND: ui/app/cashflow/charts/CategoryDonut.tsx
- FOUND: ui/app/cashflow/page.tsx
- FOUND: dbc84b0
- FOUND: f36fde7

---
*Phase: 11-category-hierarchy-schema-audit-migration*
*Completed: 2026-07-19*
