---
phase: 07-investment-subsystem-v2-multi-platform-multi-currency-cash-g
plan: 03
subsystem: ui
tags: [recharts, nextjs, react, investments, data-viz]

# Dependency graph
requires:
  - phase: 07-02
    provides: asset_type_groups on PortfolioSummary (VZ-01 pie data contract, current IDR market value per asset_type)
provides:
  - AllocationPieChart.tsx — Recharts PieChart clone of CategoryDonut.tsx, pure renderer of {label, value}[]
  - Investments page allocation card with asset-type/platform toggle, fed by the existing summary fetch
affects: [07-ui-phase (placement/chrome polish), investment-subsystem visualization]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Recharts fixed-height wrapper (width 100% / height 280) around ResponsiveContainer — load-bearing, avoids blank-render pitfall"
    - "Pure-renderer chart component: parent resolves grouping/data, component only draws"

key-files:
  created: [ui/app/investments/AllocationPieChart.tsx]
  modified: [ui/app/investments/page.tsx]

key-decisions:
  - "Platform grouping for the pie derives client-side from the existing activeGroups (platform_name/subtotal) rather than a separate backend array — Plan 02 only added asset_type_groups; platform totals were already computed for the platform-grouped holdings cards"
  - "Toggle pill styling/placement implemented directly per 07-UI-SPEC.md (already-approved contract) rather than deferring to a later UI pass, since the spec was already finalized with exact placement/copy/color rules"

patterns-established:
  - "AllocationSlice {label, value} is the normalized shape both asset_type and platform groupings map to before hitting the chart component"

requirements-completed: [INV-06]

# Metrics
duration: 5min
completed: 2026-07-12
---

# Phase 07 Plan 03: Allocation Pie Chart Summary

**VZ-01 allocation pie shipped as AllocationPieChart.tsx (Recharts clone of CategoryDonut.tsx) wired into the investments page with an asset-type/platform toggle, reading current IDR market value from the existing /investments/summary fetch — no new backend endpoint.**

## Performance

- **Duration:** 5 min
- **Started:** 2026-07-12T11:44:33Z
- **Completed:** 2026-07-12T11:49:01Z
- **Tasks:** 2 completed
- **Files modified:** 2 (1 created, 1 modified)

## Accomplishments
- `AllocationPieChart.tsx` created as a structural clone of `CategoryDonut.tsx` (PieChart/Pie/Cell/Tooltip/ResponsiveContainer), pure renderer over a normalized `{label, value}[]` prop
- Explicit-height wrapper (`width: 100%, height: 280`) preserved — load-bearing per the documented Recharts blank-render pitfall
- Wired into `page.tsx`: new allocation card between the P&L summary grid and `ValueHistoryChart`, per the approved `07-UI-SPEC.md` placement contract
- Asset-type↔platform toggle pill group implemented per spec (Accent active state, muted inactive, no new color/spacing tokens)
- Empty state ("Add a holding to see your allocation.") when the resolved grouping array is empty

## Task Commits

Each task was committed atomically:

1. **Task 1: AllocationPieChart component (clone CategoryDonut) with asset-type↔platform toggle** - `77aaa14` (feat)
2. **Task 2: Wire AllocationPieChart into the investments page** - `fe9c0f4` (feat)

_Note: no TDD tasks in this plan; each task is a single feat commit._

## Files Created/Modified
- `ui/app/investments/AllocationPieChart.tsx` - Recharts pie chart, pure renderer of `{label, value}[]`, explicit-height wrapper, empty state
- `ui/app/investments/page.tsx` - imports/renders `AllocationPieChart`, adds `allocationGroupBy` state + toggle pills, derives `allocationData` from `summary.asset_type_groups` (asset_type mode) or `activeGroups` (platform mode) — no new fetch

## Decisions Made
- Platform-grouping data for the pie is derived client-side from the already-fetched `activeGroups` (`platform_name`/`subtotal`), not a new backend array, since Plan 02 only added `asset_type_groups` to the summary payload and the platform totals were already present for the existing platform-grouped holdings cards. This satisfies the plan's "no new backend endpoint" constraint by construction.
- Since `07-UI-SPEC.md` was already approved with exact placement/copy/color specifics for this chart (card position, header row shape, toggle pill styling), those specifics were implemented directly in this plan rather than deferred to a later `/gsd-ui-phase 7` pass — the plan's own deferral language predates the UI-SPEC's approval.

## Deviations from Plan

**1. [Rule 1 - Bug] Fixed relative import path for `chartColors`**
- **Found during:** Task 1 (typecheck after creating `AllocationPieChart.tsx`)
- **Issue:** Cloned `CategoryDonut.tsx`'s import verbatim (`../../styles`), but `ui/app/investments/` is one directory level shallower than `ui/app/cashflow/charts/`, so the two-level-up path resolved outside `ui/app/`.
- **Fix:** Changed to `../styles`, matching every other file in `ui/app/investments/` (`page.tsx`, `HoldingModal.tsx`, etc.).
- **Files modified:** `ui/app/investments/AllocationPieChart.tsx`
- **Verification:** `cd ui && npx tsc --noEmit` — clean.
- **Committed in:** `77aaa14` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Trivial path fix caught immediately by tsc; no scope creep.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- VZ-01 (allocation at a glance) is shipped and reads live data — no stub.
- Visual QA of the chart against real portfolio data is a good candidate for `/gsd-ui-phase 7` or manual verification once the phase's other plans (07-02 backend, already done; 07-04 history chart, already done) are all live.
- No blockers for remaining Phase 7 plans.

---
*Phase: 07-investment-subsystem-v2-multi-platform-multi-currency-cash-g*
*Completed: 2026-07-12*
