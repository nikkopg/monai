---
phase: 04-cashflow-dashboard-crud
plan: 05
subsystem: ui
tags: [nextjs, react, playwright, cashflow, crud]

# Dependency graph
requires:
  - phase: 04-cashflow-dashboard-crud (Plan 03)
    provides: PUT/DELETE /transactions/{id}, POST/PUT/DELETE /accounts (reassign-then-delete), GET /categories, GET /categories/{name}/affected-count, POST /categories/rename, POST /categories/merge, GET /cashflow/summary
  - phase: 04-cashflow-dashboard-crud (Plan 04)
    provides: ui/app/cashflow/page.tsx dashboard (summary row, per-account balances, charts, period selector), ui/app/styles.ts (card/input/btn/label/dangerBtn/chartColors)
provides:
  - TransactionModal (shared create/edit, D-10)
  - ConfirmDialog (reusable destructive-action confirm, D-03)
  - AccountManager (inline edit + reassign-then-delete, D-05/D-06)
  - CategoryManager (rename + merge with live affected-count, D-09)
  - CsvUpload (multipart POST /import wrapper, CASH-08)
  - page.tsx wired with all five components + refetch-after-write (Pattern 5)
  - ui/e2e/cashflow-crud.spec.ts (CRUD coverage, green)
affects: [04-cashflow-dashboard-crud (phase verification), any future phase touching ui/app/cashflow]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "refreshAll() = Promise.all([loadTxs(), loadSummary(period)]) passed as every CRUD component's onSaved/onChanged/onImported callback — no page reload, no state library"
    - "ConfirmDialog children slot lets a caller (AccountManager) swap the dialog's body content mid-flow (plain confirm -> destination <select>) without a second dialog component"
    - "Row-level actions are <span role=\"button\"> (matches existing codebase convention); dialog primary/cancel actions are real <button> elements"

key-files:
  created:
    - ui/app/cashflow/TransactionModal.tsx
    - ui/app/cashflow/ConfirmDialog.tsx
    - ui/app/cashflow/AccountManager.tsx
    - ui/app/cashflow/CategoryManager.tsx
    - ui/app/cashflow/CsvUpload.tsx
    - ui/e2e/cashflow-crud.spec.ts
  modified:
    - ui/app/cashflow/page.tsx

key-decisions:
  - "AccountManager's Account prop type narrowed to {id, name} (not the full AccountOut shape) so it accepts both GET /accounts rows and the richer per-account balance rows already loaded from GET /cashflow/summary — avoids a second accounts fetch"
  - "e2e spec mocks use a trailing wildcard on query-string routes (**/api/accounts/1* not **/api/accounts/1) — Playwright's route glob does not match a URL's query string unless the pattern ends with a wildcard; without it the reassign-then-delete request silently falls through to the real network and 404s"

patterns-established:
  - "Pattern 5 (refetch-after-write): every write path — transaction create/edit/delete, account create/edit/delete, category rename/merge, CSV import — calls the same refreshAll() to keep the dashboard figures and per-account balances in sync with no page reload"

requirements-completed: [CASH-04, CASH-05, CASH-06, CASH-07, CASH-08]

# Metrics
duration: ~55min
completed: 2026-07-05
---

# Phase 04 Plan 05: Cashflow CRUD (write half) Summary

**Five new client components (TransactionModal, ConfirmDialog, AccountManager, CategoryManager, CsvUpload) wired into the Phase-4 dashboard with a single refreshAll() refetch-after-write path, plus a green Playwright CRUD spec covering all five flows including the 422 reassign-then-delete branch.**

## Performance

- **Duration:** ~55 min
- **Started:** 2026-07-05T05:04Z (approx, first Read)
- **Completed:** 2026-07-05T06:04Z
- **Tasks:** 3
- **Files modified:** 7 (5 created, 1 modified for wiring, 1 e2e spec created)

## Accomplishments
- TransactionModal is one component that handles both create (POST) and edit (PUT), matching D-10.
- ConfirmDialog is reused verbatim across delete-transaction, delete-account (both branches), and merge-category, with a `children` slot enabling the account-reassign `<select>` to appear inline (D-03/D-06).
- AccountManager implements the full reassign-then-delete flow: plain delete, 422 detection, destination-account picker, re-issued DELETE with `?reassign_to=`.
- CategoryManager enumerates categories from the guaranteed `GET /categories` endpoint (no defensive "if tool exists" branching), shows a live affected-count pill per row, and gates merge (not rename) behind ConfirmDialog with the affected count in the copy.
- CsvUpload is a thin multipart wrapper over the existing `POST /import`, coloring the "Skipped" segment red only when >0.
- page.tsx now has zero inline entry form — "Add transaction" opens the modal, and every table row has Edit/Delete actions. All five components share one `refreshAll()` refetch (list + summary) so nothing needs a page reload.
- `ui/e2e/cashflow-crud.spec.ts` was written AND actually executed against a live Next.js dev server (not just typechecked) — all 7 tests pass, verified across 3 consecutive runs for stability.

## Task Commits

Each task was committed atomically:

1. **Task 1: TransactionModal + ConfirmDialog** - `4df52e8` (feat)
2. **Task 2: AccountManager, CategoryManager, CsvUpload** - `4804a8b` (feat)
3. **Task 3: Wire into page.tsx + Playwright CRUD spec** - `c892531` (feat)

**Plan metadata:** (this commit, docs)

## Files Created/Modified
- `ui/app/cashflow/TransactionModal.tsx` - shared create/edit transaction modal (D-10)
- `ui/app/cashflow/ConfirmDialog.tsx` - reusable destructive-confirm modal with children slot (D-03)
- `ui/app/cashflow/AccountManager.tsx` - account list, inline edit, reassign-then-delete (D-05/D-06)
- `ui/app/cashflow/CategoryManager.tsx` - category list, affected-count badge, rename/merge (D-09)
- `ui/app/cashflow/CsvUpload.tsx` - multipart CSV import wrapper (CASH-08)
- `ui/app/cashflow/page.tsx` - replaced inline entry form with modal-driven CRUD; mounted all five new sections; added `refreshAll()`
- `ui/e2e/cashflow-crud.spec.ts` - Playwright spec covering create/edit/delete transaction, account reassign-then-delete, category rename/merge, CSV upload

## Decisions Made
- Narrowed `AccountManager`'s `Account` type to `{id, name}` rather than reusing a full `AccountOut`-shaped type, so the component can take either the plain `/api/accounts` list or the per-account balance rows already available from `GET /cashflow/summary` on the dashboard — avoids adding a second accounts fetch just for this component.
- e2e mocks for endpoints that receive query strings (account delete's `?reassign_to=`) must use a trailing wildcard in the route glob (`**/api/accounts/1*`) — verified experimentally that Playwright's glob matcher does not match a request URL's query string against a pattern lacking a trailing `*`, causing the mock to silently miss and the real (unmocked) request to 404.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed AccountManager/page.tsx type mismatch surfaced by wiring**
- **Found during:** Task 3, `npx tsc --noEmit` after wiring `AccountManager` into `page.tsx`
- **Issue:** `AccountManager`'s `Account` type required `type`/`currency` fields; `page.tsx` passes `summary.accounts` (the `AccountBalance` shape from `GET /cashflow/summary`, which only has `id/name/current_balance/period_net`) — a real type error, not a plan gap.
- **Fix:** Narrowed `AccountManager`'s exported `Account` type to `{id, name}` (the only fields the component actually reads/renders).
- **Files modified:** `ui/app/cashflow/AccountManager.tsx`
- **Verification:** `npx tsc --noEmit -p tsconfig.json` clean; `npm run build` succeeds.
- **Committed in:** `c892531` (Task 3 commit)

**2. [Rule 3 - Blocking] Installed frontend dependencies in the worktree**
- **Found during:** Task 3, first `npx tsc`/`npm run build` attempt
- **Issue:** This git worktree had no `node_modules` at all (worktrees don't share `node_modules`, and it's gitignored) — every `npx` command silently failed with "This is not the tsc command you are looking for" and the plan's `verify` grep patterns fell through to their `|| echo` success fallback, giving a false pass.
- **Fix:** Ran `npm install` in `ui/` inside the worktree before trusting any typecheck/build result.
- **Files modified:** none (node_modules is gitignored, not committed)
- **Verification:** `npx tsc --noEmit` and `npm run build` both ran for real afterward and passed.
- **Committed in:** N/A (no source change — environment setup only)

---

**Total deviations:** 2 auto-fixed (1 bug, 1 blocking/environment)
**Impact on plan:** Both fixes were necessary to get a real (not false-positive) verification signal. No scope creep — no new features added beyond what the plan specified.

## Issues Encountered
- The plan's per-task `<verify>` commands pipe to `|| echo "... typecheck"`, which silently "passes" even when `npx tsc` itself fails to execute (e.g., missing `node_modules`). After installing dependencies, all three tasks' real typecheck output was confirmed clean.
- A stale `next-server` process (root-owned, unrelated to this worktree) was already listening on port 3001, the port `playwright.config.ts`'s `webServer`/`baseURL` hardcode and reuse via `reuseExistingServer: true`. This meant the first several live Playwright runs exercised an entirely different (much older) build of `page.tsx`, producing misleading "element not found" failures for sections that were, in fact, present in this worktree's code. Resolved by running a scratch dev server on port 3012 and temporarily pointing a local copy of `playwright.config.ts` at it for verification only; `playwright.config.ts` was restored to its original (unmodified, uncommitted-diff) state afterward — this file is not in the plan's `files_modified` and was never intended to change.
- Playwright's `page.route()` glob pattern does not match a request's query string unless the pattern itself ends in a wildcard (`**/api/accounts/1` does NOT match `.../accounts/1?reassign_to=2`; `**/api/accounts/1*` does). This was discovered via an isolated repro test and fixed in the merge/reassign-then-delete e2e case; documented as a comment in the spec so future specs touching query-string endpoints don't hit the same silent-miss.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- The full write half of Phase 4 (CASH-04 through CASH-08) is now implemented and wired into the dashboard shipped in Plan 04. A user can create/edit/delete transactions, manage accounts (including reassign-then-delete), rename/merge categories, and upload a CSV — all reflected live via `refreshAll()`.
- `ui/e2e/cashflow-crud.spec.ts` is green (verified 3x locally against a real dev server + mocked backend routes). The phase's overall `<verification>` step should still run `npm run e2e` (full suite: smoke + settings + dashboard + crud) with a real backend up for the final DB-round-trip confirmation — this plan's automated verification used route interception per the plan's own guidance ("if a full end-to-end DB round-trip is unavailable ... it's acceptable to ensure the spec compiles and document ... that live e2e was deferred"), but went further and actually executed the spec against a live dev server rather than only compiling it.
- No blockers for phase closeout from this plan's scope.

---
*Phase: 04-cashflow-dashboard-crud*
*Completed: 2026-07-05*

## Self-Check: PASSED

All 7 created/modified files verified present on disk; all 4 task/summary commit hashes (4df52e8, 4804a8b, c892531, 6388903) verified in git log.
