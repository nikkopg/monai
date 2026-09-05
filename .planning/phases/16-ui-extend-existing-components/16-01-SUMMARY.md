---
phase: 16-ui-extend-existing-components
plan: 01
subsystem: testing
tags: [playwright, e2e, route-mock, ui, cashflow, investments]

requires:
  - phase: 13-shared-mutation-layer
    provides: apply_add_transfer / POST /transactions/transfer atomic pair endpoint
  - phase: 14-mutation-registration
    provides: REST registration of transaction/account/platform CRUD endpoints these specs mock
provides:
  - ui/e2e/record-modal.spec.ts pinning REC-04 (segmented Expense/Income/Transfer, sign derivation, currency, "Save & add another", transfer pair-endpoint body whitelist, same-account guard, edit-leg lock)
  - ui/e2e/platform-crud.spec.ts pinning PLAT-02 (add/edit-incl-kind/delete-reassign parity)
  - ui/e2e/cashflow-crud.spec.ts extended with ACCT-01 (account create posts type:liquid)
affects: [16-02-PLAN.md (TransactionModal Wave 1), 16-03-PLAN.md (AccountManager/PlatformManager Wave 1)]

tech-stack:
  added: []
  patterns:
    - "Wave 0 test-scaffolding: e2e specs written and committed RED before the UI they pin exists, matching cashflow-crud.spec.ts's existing route-mock idiom (page.route(...) intercepts, no live backend)"

key-files:
  created:
    - ui/e2e/record-modal.spec.ts
    - ui/e2e/platform-crud.spec.ts
  modified:
    - ui/e2e/cashflow-crud.spec.ts

key-decisions:
  - "Task 1 and Task 2 (both extending record-modal.spec.ts) landed in a single commit — no independent verification checkpoint separates them, and the plan's own file_modified list treats the file as one unit"
  - "platform-crud.spec.ts mounts at /investments and mocks GET /api/platforms + /api/investments/summary + /api/investments/history (the real page's load() dependencies), not a synthetic endpoint, so the spec exercises the actual PlatformManager mount point"

requirements-completed: [ACCT-01, PLAT-02, REC-04]

duration: 45min
completed: 2026-08-01
status: complete
---

# Phase 16 Plan 01: Wave 0 e2e Test Scaffolds Summary

**Three Playwright specs (21 scenarios total) pinning the REC-04 segmented-control, PLAT-02 CRUD-parity, and ACCT-01 type:liquid contracts as route-mocked RED baselines ahead of Wave 1 implementation.**

## Performance

- **Duration:** ~45 min
- **Completed:** 2026-08-01T10:58:17Z
- **Tasks:** 3 (Task 1+2 combined into one commit — see Decisions)
- **Files modified:** 3 (2 created, 1 extended)

## Accomplishments
- `ui/e2e/record-modal.spec.ts` (new, 8 tests): default-Expense segment order/styling, Expense→negative/Income→positive sign derivation with currency IDR in the POST body, "Save & add another" stays-open + resets amount/category/notes, edit-mode reverse-map (negative amount → Expense + absolute magnitude → PUT), Transfer branch posts an explicit field whitelist to `/api/transactions/transfer` (never `/api/transactions`), same-account client-side guard, and the edit-leg transfer lock (disabled segment, legacy Account select, muted caption, PUT never routes to the pair endpoint) — REC-04.
- `ui/e2e/platform-crud.spec.ts` (new, 3 tests): add posts `name`+`kind`, edit-row PUT posts both `name` AND `kind` (the D-08 gap), delete-with-422→reassign — structural mirror of `cashflow-crud.spec.ts`'s existing account reassign-delete test, mounted at `/investments` against the real `PlatformManager` — PLAT-02.
- `ui/e2e/cashflow-crud.spec.ts` extended (+1 test, existing 10 unchanged): account create asserts `POST /api/accounts` body includes `type: "liquid"` — ACCT-01.

## Task Commits

Each task was committed atomically:

1. **Task 1+2: record-modal.spec.ts (Expense/Income + Transfer branches)** - `274d5c0` (test)
2. **Task 3: platform-crud.spec.ts + cashflow-crud.spec.ts type:liquid** - `0b5edeb` (test)

**Plan metadata:** pending (this commit)

## Files Created/Modified
- `ui/e2e/record-modal.spec.ts` - REC-04 scaffold: 8 tests across Expense/Income and Transfer describe blocks
- `ui/e2e/platform-crud.spec.ts` - PLAT-02 scaffold: 3 tests (add/edit-kind/delete-reassign)
- `ui/e2e/cashflow-crud.spec.ts` - +1 test in a new `account create (ACCT-01)` describe block; existing 10 tests untouched

## Decisions Made
- Combined Task 1 and Task 2 into one commit (both build `record-modal.spec.ts` incrementally with no automated checkpoint between them) — documented as a deviation below, not a rule violation, just a scope note.
- `platform-crud.spec.ts` fixtures match the real `investments/page.tsx` `Summary` shape (`groups`, `asset_type_groups`, `total_value`, `total_unrealized_pnl`) and mock `/api/investments/history` too, discovered by reading `page.tsx`'s `load()`/`loadHistory()` — required so the page doesn't crash before `PlatformManager` mounts.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] platform-crud.spec.ts needed the real investments/page.tsx data contract, not a synthetic one**
- **Found during:** Task 3
- **Issue:** An initial fixture shape (`{ platforms, holdings, totals }`) for `/api/investments/summary` didn't match `Summary`'s actual TypeScript shape used by `investments/page.tsx`, which would make the mounted page inert/crash-prone under a real render.
- **Fix:** Read `ui/app/investments/page.tsx`'s `load()`/`loadHistory()` and `Summary`/`Group`/`AssetTypeGroup` types directly; fixture now returns `{ groups: [], asset_type_groups: [], total_value: 0, total_unrealized_pnl: 0 }` and a `/api/investments/history**` route mock was added.
- **Files modified:** ui/e2e/platform-crud.spec.ts
- **Verification:** `npx playwright test e2e/platform-crud.spec.ts --list` exits 0, 3 tests discovered.
- **Committed in:** 0b5edeb (Task 3 commit)

**2. [Task-grouping, not a rule] Task 1 + Task 2 combined into one commit**
- **Found during:** Task 1
- **Issue:** Task 2's scope is "extend ui/e2e/record-modal.spec.ts" (the file Task 1 creates) — no independent build/verify checkpoint exists between the two beyond the same `--list` command, so writing them as two sequential edits with two commits would have split one coherent spec file's authorship artificially.
- **Fix:** Wrote the full 8-scenario file in one pass, ran `--list` once, committed once under a message covering both tasks' scope.
- **Files modified:** ui/e2e/record-modal.spec.ts
- **Verification:** `npx playwright test e2e/record-modal.spec.ts --list` exits 0, 8 tests discovered (5 from Task 1's 6-scenario list, folding "Currency default+wired" into scenarios 2/3 per the plan's own instruction; 3 from Task 2).
- **Committed in:** 274d5c0

---

**Total deviations:** 2 (1 blocking auto-fix, 1 task-grouping scope note)
**Impact on plan:** No scope creep — both were necessary for the specs to compile/mount correctly and reflect the plan's own instructions (fold currency assertion into 2/3; mirror the real page).

## Issues Encountered
None beyond the two items above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All three specs compile and discover their full scenario set (`--list` exits 0, 21 tests total across the three files) — the RED baseline Wave 1 (Plans 02/03) must turn GREEN.
- Specs were NOT run to completion (not `--list`) against current code per the plan's explicit instruction — they are expected RED (segmented control / currency field / Transfer branch / kind-edit-input do not exist yet in `TransactionModal.tsx` / `PlatformManager.tsx`). Wave 1 plans should run these specs for real after each implementation task as their Nyquist verification signal.
- No blockers.

---
*Phase: 16-ui-extend-existing-components*
*Completed: 2026-08-01*

## Self-Check: PASSED

All created/modified files found on disk; all task commit hashes (274d5c0, 0b5edeb) and the summary commit (45a2bd2) found in git log.
