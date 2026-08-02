---
phase: 17-ui-new-surfaces-records-tab-categories-manager
plan: 02
subsystem: testing
tags: [playwright, e2e, route-mock, records, platform-detail, tdd-red]

# Dependency graph
requires:
  - phase: 16-ui-extend-existing-components
    provides: TransactionModal transfer-leg-locked edit mode, ConfirmDialog destructive-confirm shape, cashflow-crud.spec.ts / platform-crud.spec.ts route-mock conventions this plan mirrors
provides:
  - ui/e2e/records.spec.ts — RED baseline for the Records ledger (date-grouped, daily-net-excludes-transfers, filter bar, transfer-pair collapse, bulk select/delete/recategorize, Load-100-more)
  - ui/e2e/platform-detail.spec.ts — RED baseline for Platform detail (shell, stat cards, PnL/Buy&Sell segmented tabs, 404 state)
affects: [17-04 (Records page implementation), 17-05 (Platform detail page implementation)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Route-mocked Playwright spec per surface, mirroring cashflow-crud.spec.ts's page.route(\"**/api/...\") fulfill idiom — no live backend"
    - "Real <button> vs <span role=\"button\"> disambiguation via page.locator(\"button\").filter({hasText}) when a row-level action link and a bulk-bar/dialog button share the same visible text"
    - "Fixture dates computed relative to test run time (isoAt(daysAgo)) so Today/Yesterday/weekday-label assertions stay valid regardless of when the suite runs"

key-files:
  created:
    - ui/e2e/records.spec.ts
    - ui/e2e/platform-detail.spec.ts
  modified: []

key-decisions:
  - "records.spec.ts fixture pairs a normal expense row with an Adjustment row (is_transfer=true, transfer_pair_id=null) on the same day to pin the daily-net rule precisely: transfer_pair_id IS NULL rows are INCLUDED in the net (even Adjustment rows), only true transfer_pair_id-shared legs are excluded"
  - "Bulk-delete confirm click and bulk-bar Delete-button click both target real <button> tags via page.locator(\"button\").filter(...) — row-level Edit/Delete are <span role=\"button\">, so a role-based locator would have been ambiguous"
  - "'Realized'/'Unrealized' text assertions use .first() in platform-detail.spec.ts because the same words label both the stat cards (Component 9) and the PnL table column headers (Component 11), which render simultaneously since PnL is the default tab"

patterns-established:
  - "Pattern: RED e2e specs for not-yet-built pages compute expected copy/format values via the SAME Intl.NumberFormat convention as the app's own signed()/money() helpers (not hand-typed strings), so the assertion stays correct once the page is built without needing a second edit pass"

requirements-completed: [REC-01, REC-02, REC-03, REC-05, PLAT-01]

duration: 25min
completed: 2026-08-02
---

# Phase 17 Plan 02: RED e2e Baseline for Records + Platform Detail Summary

**Two route-mocked Playwright specs (7 + 4 tests) locking the 17-UI-SPEC.md copy and endpoint contract for the not-yet-built Records ledger and Platform detail pages — both confirmed RED against the current app.**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-08-02T06:06:48Z
- **Completed:** 2026-08-02T06:20:36Z
- **Tasks:** 2 completed
- **Files modified:** 2 (both new)

## Accomplishments

- `ui/e2e/records.spec.ts` — 7 tests covering: date-grouped ledger headers (Today/Yesterday/weekday form) with the daily-net calculation that excludes collapsed transfer-pair legs but includes Adjustment rows; the filter bar's locked fields/placeholders/defaults and its debounced-refetch query-param contract; the transfer-pair collapse into one "Transfer: From → To" row with an unsigned amount; multi-select bulk bar wired to `POST /transactions/bulk-delete` (via `ConfirmDialog`) and `POST /transactions/bulk-recategorize`; and the "Load 100 more" pagination visibility rule.
- `ui/e2e/platform-detail.spec.ts` — 4 tests covering: the page shell (back-link, name/kind, 3 stat cards); the PnL tab's default-active state and locked column headers with realized/unrealized values; the segmented-control switch to the Buy & Sell event table with Title-cased colored Side values; and the 404 "Platform not found" state with the back-link still present.
- Both suites run to completion under `PLAYWRIGHT_CHROMIUM_PATH=/usr/bin/google-chrome` and fail RED (records.spec.ts: 6/7 fail, the 1 pass is a trivial "element absent" assertion that holds vacuously pre-build; platform-detail.spec.ts: 4/4 fail) — confirming `/records` and `/investments/[platformId]` do not exist yet, matching the plan's expected RED baseline for 17-04/17-05.

## Task Commits

Each task was committed atomically:

1. **Task 1: RED e2e spec for the Records ledger** - `40a8beb` (test)
2. **Task 2: RED e2e spec for Platform detail** - `311ba23` (test)

**Plan metadata:** (this commit)

## Files Created/Modified

- `ui/e2e/records.spec.ts` - RED baseline: date-grouped ledger + daily net, filter bar, transfer-pair collapse, bulk select/delete/recategorize, Load-100-more pagination
- `ui/e2e/platform-detail.spec.ts` - RED baseline: platform detail shell, PnL/Buy&Sell segmented tabs, 404 state

## Decisions Made

- Daily-net fixture deliberately includes an Adjustment row (`is_transfer=true`, `transfer_pair_id=null`) alongside a true transfer pair, so the test locks the precise locked rule (exclude only `transfer_pair_id`-paired legs, not every `is_transfer=true` row) rather than a looser "exclude all transfers" interpretation that would contradict 17-UI-SPEC Component 3.
- Used `page.locator("button").filter({hasText: ...})` instead of `getByRole("button", {name: ...})` wherever a row-level `<span role="button">` action (Edit/Delete) and a real `<button>` (bulk-bar/dialog) could share the same visible text — avoids Playwright strict-mode multi-match errors once the page is built, matching the established idiom already used in `cashflow-crud.spec.ts`.
- Computed expected money-format strings (`Net +185,000`, etc.) via the same `Intl.NumberFormat` convention the app's own `signed()`/`money()` helpers use, rather than hand-typing formatted strings, so the assertions stay correct without a second edit once 17-04 is built.

## Deviations from Plan

None - plan executed exactly as written. Both files match the plan's per-task `<action>`/`<acceptance_criteria>` exactly; all `<verify><automated>` commands were run and confirmed RED before committing.

## Issues Encountered

- The worktree's `ui/` directory had no `node_modules` (not tracked, not present in this fresh worktree). Symlinked it to the main checkout's `ui/node_modules` (`/home/nikko/nikko/projects/monai/ui/node_modules`, which already has Playwright + the `google-chrome` fallback configured) purely to run the plan's `<verify>` commands locally, then removed the symlink before committing — it left no trace in git (node_modules/ is gitignored) and no files were added under it.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- 17-04 (Records page implementation) has a concrete GREEN target: `ui/e2e/records.spec.ts`'s 7 tests encode the exact filter-param names, bulk-endpoint payload shapes, transfer-pair-collapse row shape, and daily-net exclusion rule it must satisfy.
- 17-05 (Platform detail page implementation) has a concrete GREEN target: `ui/e2e/platform-detail.spec.ts`'s 4 tests encode the route shape (`/investments/[platformId]`), the `GET /platforms/{id}/detail` + `GET /portfolio-events?platform_id=` fixture contract, and the segmented-control/404 behavior.
- No blockers. Both specs are pure additions (new test files) with no backend or shared-component changes, so they carry zero risk to any other in-flight Phase 17 plan (17-01 backend, 17-03 backend endpoints).

---
*Phase: 17-ui-new-surfaces-records-tab-categories-manager*
*Completed: 2026-08-02*

## Self-Check: PASSED

- FOUND: ui/e2e/records.spec.ts
- FOUND: ui/e2e/platform-detail.spec.ts
- FOUND: 40a8beb (Task 1 commit)
- FOUND: 311ba23 (Task 2 commit)
