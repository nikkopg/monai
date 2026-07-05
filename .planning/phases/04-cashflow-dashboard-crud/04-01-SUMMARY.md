---
phase: 04-cashflow-dashboard-crud
plan: 01
subsystem: api
tags: [fastapi, sqlalchemy, refactor, audit-log, write-path]

# Dependency graph
requires:
  - phase: 02-agentic-loop-confirm-before-write
    provides: "_execute_proposal_payload agent propose->confirm write path + audit_log table"
provides:
  - "backend/writes.py: 8 apply_* functions (add/edit/delete transaction, add/edit/delete account, rename/merge category) — the single shared write implementation (D-02)"
  - "_execute_proposal_payload rewired as a thin dispatcher over backend/writes.py"
  - "apply_delete_account(reassign_to=...) — audited account-delete-with-reassign in one place, ready for Plan 03's direct DELETE /accounts endpoint"
affects: [04-02, 04-03, 04-04, 04-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "apply_* helper convention: (db, ...) -> entity|int, exactly one AuditLog row, no db.commit() — caller owns the transaction boundary"

key-files:
  created:
    - backend/writes.py
  modified:
    - backend/main.py

key-decisions:
  - "apply_add_transaction now wraps amount in Decimal(str(x)) (previously assigned the raw after[\"amount\"] value) — defense-in-depth consistency with apply_edit_transaction; Numeric(18,2) column coercion made this a no-op behaviorally, confirmed by the full regression suite staying green"
  - "apply_delete_account accepts reassign_to as an optional param; when set it performs the transactions reassignment via a single parameterized text() UPDATE and records the reassignment target+count in its one AuditLog row (WARNING 1 fix) — dispatcher call site in Task 2 passes no reassign_to, preserving today's plain-delete behavior exactly; Plan 03's direct endpoint will be the first caller to pass it"

patterns-established:
  - "Write mutations live only in backend/writes.py; both the agent propose->confirm path and future direct REST endpoints call the same apply_* functions — never duplicate ORM mutation logic in main.py"

requirements-completed: [CASH-04, CASH-05, CASH-06, CASH-07]

# Metrics
duration: 25min
completed: 2026-07-05
---

# Phase 04 Plan 01: Extract Shared Write Layer (backend/writes.py) Summary

**Extracted all 8 proposal-executor write branches into `backend/writes.py` and rewired `_execute_proposal_payload` into a thin dispatcher, with zero behavior change proven by the full Phase 2 regression suite staying green (19/19).**

## Performance

- **Duration:** 25 min
- **Started:** 2026-07-05T00:20:00Z
- **Completed:** 2026-07-05T00:45:43Z
- **Tasks:** 2
- **Files modified:** 2 (1 created, 1 modified)

## Accomplishments
- `backend/writes.py` created with 8 `apply_*` helpers, each a verbatim (plus one consistency fix) extraction of its `_execute_proposal_payload` branch — preserving flush-before-audit ordering, `Decimal(str(x))` wrapping, and parameterized `text()` SQL for rename/merge
- `apply_delete_account` gained an optional `reassign_to` param so the account-delete-with-reassign write path is fully audited in a single place (WARNING 1 fix from the threat model), ready for Plan 03's direct endpoint to call
- `_execute_proposal_payload` in `backend/main.py` rewritten as a thin dispatcher — 8 inline ORM branches replaced with 8 single calls into `backend/writes.py`; holdings branches (Phase 5 scope) left untouched
- Full regression suite (`test_proposals.py` + `test_write_tools.py`, 19 tests) passes unchanged; broader suite (75 tests) shows only one unrelated pre-existing failure (see Issues Encountered)

## Task Commits

Each task was committed atomically:

1. **Task 1: Copy-paste-then-rename each _execute_proposal_payload branch into backend/writes.py** - `74fee8b` (feat)
2. **Task 2: Rewire _execute_proposal_payload to dispatch into backend/writes.py and prove no regression** - `86414dc` (refactor)

## Files Created/Modified
- `backend/writes.py` - New module: 8 `apply_*` functions (`apply_add_transaction`, `apply_edit_transaction`, `apply_delete_transaction`, `apply_add_account`, `apply_edit_account`, `apply_delete_account`, `apply_rename_category`, `apply_merge_category`), single source of truth for write mutations shared by agent + future direct endpoints
- `backend/main.py` - `_execute_proposal_payload` transaction/account/category branches replaced with `apply_*` calls; import block extended with `backend.writes` names; holdings branches unchanged

## Decisions Made
- Wrapped `apply_add_transaction`'s amount assignment in `Decimal(str(x))` (the original inline branch assigned the raw `after["amount"]` value directly to the `Numeric(18,2)` column). This is a Rule 1 consistency fix — the column type already coerced correctly, so there's no observable behavior change (confirmed by the regression suite), but it satisfies the plan's own acceptance criteria (`Decimal(str(` count >= 2) and removes a subtle asymmetry between add/edit paths.
- `apply_delete_account`'s `reassign_to` parameter is exercised for the first time by Plan 03 (this plan's dispatcher call site passes no `reassign_to`, preserving current agent-path behavior exactly — a plain audited delete).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug/Consistency] Wrapped apply_add_transaction's amount in Decimal(str(x))**
- **Found during:** Task 1 (writing backend/writes.py)
- **Issue:** The original `add_transaction` branch in `_execute_proposal_payload` assigned `after["amount"]` directly (no `Decimal()` wrapping), while `edit_transaction` used `Decimal(str(after["amount"]))`. This asymmetry meant the plan's own acceptance criterion (`grep -c 'Decimal(str(' backend/writes.py` >= 2) could not be satisfied by a pure verbatim copy, and left a latent float-precision inconsistency between add and edit paths.
- **Fix:** Wrapped the amount assignment in `apply_add_transaction` as `Decimal(str(after["amount"]))`, matching `apply_edit_transaction`'s convention.
- **Files modified:** `backend/writes.py`
- **Verification:** Full regression suite (`test_proposals.py`, `test_write_tools.py`) stays green; acceptance-criteria greps (`Decimal(str(` count == 2) pass.
- **Committed in:** `74fee8b` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 bug/consistency fix)
**Impact on plan:** No observable behavior change (Numeric column coercion made both forms equivalent); closes a latent inconsistency and satisfies the plan's stated acceptance criteria. No scope creep.

## Issues Encountered
- Full backend suite (`pytest backend/tests/`) has one pre-existing failure unrelated to this plan's files: `test_settings.py::test_put_settings_requires_key` expects 401 but gets 503 in this environment (traced to `MONAI_API_KEY` env-config state, Phase 3 area, commit `cb80d8c`'s empty-key 503 guard). Out of scope for this plan (touches neither `backend/writes.py` nor `_execute_proposal_payload`) — logged to `.planning/phases/04-cashflow-dashboard-crud/deferred-items.md`, not fixed.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- `backend/writes.py`'s 8 `apply_*` functions are ready for Plan 03's direct REST endpoints (`PUT/DELETE /transactions/{id}`, `POST/PUT/DELETE /accounts`, `POST /categories/rename|merge`) to call directly — no duplicated write logic risk.
- `apply_delete_account(reassign_to=...)` is implemented and audited but not yet exercised by any caller; Plan 03 is expected to be its first real caller (the reassign-then-delete 422-with-count pattern, D-06).
- No blockers for Plan 02/03/04/05.

---
*Phase: 04-cashflow-dashboard-crud*
*Completed: 2026-07-05*

## Self-Check: PASSED

- FOUND: backend/writes.py
- FOUND: .planning/phases/04-cashflow-dashboard-crud/04-01-SUMMARY.md
- FOUND: 74fee8b (Task 1 commit)
- FOUND: 86414dc (Task 2 commit)
- FOUND: 2ed9ffc (docs/summary commit)
