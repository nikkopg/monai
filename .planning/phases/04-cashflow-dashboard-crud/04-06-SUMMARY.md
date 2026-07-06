---
phase: 04-cashflow-dashboard-crud
plan: 06
subsystem: api
tags: [fastapi, periods, cashflow, error-handling, pytest, tdd]

# Dependency graph
requires:
  - phase: 04-cashflow-dashboard-crud (plan 03)
    provides: GET /cashflow/summary endpoint + resolve_period-driven aggregation
provides:
  - this_week and last_week named periods in the PERIODS registry (ISO-Monday half-open bounds)
  - GET /cashflow/summary now maps ValueError to HTTPException(422) like its sibling endpoints
  - regression tests pinning week-period bounds and the 200/422 endpoint contract
affects: [chat agent tool router (validates periods through the same PERIODS registry), cashflow dashboard UI period pills]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "ValueError->HTTPException(422) mapping now applied to every resolve_period caller, including GET reads"
    - "ISO-Monday half-open [monday, next_monday) week bounds, mirroring the this_month/last_month adjacency convention"

key-files:
  created: []
  modified:
    - backend/tools.py
    - backend/main.py
    - backend/tests/test_period_scoping.py
    - backend/tests/test_cashflow_summary.py

key-decisions:
  - "Added last_week alongside this_week (one tuple entry + one branch) for this/last symmetry with months/years and immediate chat-router availability"
  - "Named the except variable `exc` (not `e`) in cashflow_summary to avoid shadowing the end-bound `e` used later by account_balances(s, e)"
  - "Wrapped only the resolve_period call, not the downstream tool calls — they re-resolve identical args internally and cannot raise the same ValueError once the guarded call succeeds; keeps the single-resolve grep guard green"

patterns-established:
  - "Week periods use ISO Monday (weekday()==0) as the start; last_week's end == this_week's start (no gap/overlap)"
  - "Every /cashflow read now fails closed on bad input: unrecognized/malformed periods surface as structured 422, never a raw 500"

requirements-completed: [CASH-01, CASH-02, CASH-03]

coverage:
  - id: D1
    description: "resolve_period('this_week') returns ISO-Monday half-open [monday, next_monday) bounds containing today; last_week is the immediately-preceding week (its end == this_week's start)"
    requirement: "CASH-01"
    verification:
      - kind: unit
        ref: "backend/tests/test_period_scoping.py#test_this_week_is_iso_monday_half_open_and_contains_today"
        status: pass
      - kind: unit
        ref: "backend/tests/test_period_scoping.py#test_last_week_ends_where_this_week_starts"
        status: pass
      - kind: unit
        ref: "backend/tests/test_period_scoping.py#test_this_week_is_case_insensitive"
        status: pass
      - kind: unit
        ref: "backend/tests/test_period_scoping.py#test_unknown_period_still_raises_valueerror_naming_the_value"
        status: pass
    human_judgment: false
  - id: D2
    description: "GET /cashflow/summary?period=this_week and ?period=last_week return HTTP 200 with a full CashflowSummary payload (week pill loads end-to-end)"
    requirement: "CASH-02"
    verification:
      - kind: integration
        ref: "backend/tests/test_cashflow_summary.py#test_cashflow_summary_this_week_returns_200"
        status: pass
      - kind: integration
        ref: "backend/tests/test_cashflow_summary.py#test_cashflow_summary_last_week_returns_200"
        status: pass
    human_judgment: false
  - id: D3
    description: "GET /cashflow/summary with an unrecognized period returns HTTP 422 (never a raw 500), detail naming the offending value"
    requirement: "CASH-03"
    verification:
      - kind: integration
        ref: "backend/tests/test_cashflow_summary.py#test_cashflow_summary_unknown_period_returns_422_not_500"
        status: pass
    human_judgment: false
  - id: D4
    description: "The 'This week' pill on /cashflow loads week-scoped totals, per-account nets, and charts instead of the dashboard error state (UAT gap 1 truth)"
    requirement: "CASH-02"
    verification:
      - kind: manual_procedural
        ref: "Open /cashflow, click 'This week' — dashboard renders week-scoped figures, no error state"
        status: unknown
    human_judgment: true
    rationale: "End-to-end browser render of the dashboard through the pill is a visual/UX judgment the automated endpoint tests approximate but do not fully cover (frontend fetch + chart render)."

# Metrics
duration: 9min
completed: 2026-07-05
status: complete
---

# Phase 04 Plan 06: This-week period gap closure Summary

**Added `this_week`/`last_week` ISO-Monday half-open periods and mapped `GET /cashflow/summary` ValueErrors to 422, so the "This week" dashboard pill loads instead of crashing with a raw 500.**

## Performance

- **Duration:** 9 min
- **Started:** 2026-07-05T10:37:57Z
- **Completed:** 2026-07-05T10:47:19Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- `PERIODS` registry now includes `this_week` and `last_week`; `resolve_period` returns ISO-Monday half-open `[monday, next_monday)` bounds, with `last_week`'s end exactly equal to `this_week`'s start (mirrors the `last_month`/`this_month` adjacency).
- `GET /cashflow/summary` now wraps its single `resolve_period` call in the project-standard `try/except ValueError -> HTTPException(422)` — it was the only `resolve_period` caller missing this mapping, the root cause of the raw 500 behind UAT gap 1.
- Regression tests pin both halves: week-period bounds (weekday/duration/containment/adjacency invariants, no clock freezing) and the endpoint's 200 (this_week/last_week) vs 422 (unknown period) contract.

## Task Commits

Each task was committed atomically (TDD RED verified before each implementation):

1. **Task 1: Add this_week/last_week named periods + unit tests** - `bf4b7fc` (feat)
2. **Task 2: Map ValueError to 422 in GET /cashflow/summary + endpoint tests** - `4a872f2` (fix)

_Note: RED was confirmed for both tasks (week tests failed with the Unknown-period ValueError; the unknown-period endpoint test returned 500) before implementing GREEN._

## Files Created/Modified
- `backend/tools.py` - Added `this_week`/`last_week` to `PERIODS`; two new `resolve_period` branches computing ISO-Monday half-open bounds. ValueError fallthrough untouched (auto-updates the valid-values list).
- `backend/main.py` - Wrapped `cashflow_summary`'s `resolve_period` call in `try/except ValueError -> HTTPException(422)`; except var named `exc` to avoid shadowing the end-bound `e`.
- `backend/tests/test_period_scoping.py` - 4 unit tests: ISO-Monday start + 7-day span + today-containment for this_week, last_week/this_week adjacency, case-insensitivity, unknown-period ValueError.
- `backend/tests/test_cashflow_summary.py` - 3 endpoint tests: this_week/last_week -> 200, unknown period -> 422 with the offending value in detail.

## Decisions Made
- **Included `last_week`** (plan's optional sibling): one tuple entry + one two-line branch, gives weeks the same this/last symmetry as months/years, and is immediately usable by the chat agent's tool router (same PERIODS registry).
- **Guarded only the `resolve_period` call**, not the downstream `income_total`/`spending_total`/`net_total`/`spending_by_category` calls — they re-resolve identical arguments internally, so once the guarded call succeeds they cannot raise the same ValueError. This preserves the existing `test_cashflow_summary_resolve_period_called_once` grep guard.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Avoided exception-variable shadowing in cashflow_summary**
- **Found during:** Task 2 (ValueError->422 mapping)
- **Issue:** The plan's suggested mapping mirrors `update_account`, which uses `except ValueError as e`. In `cashflow_summary`, `e` is already bound to the period end-date (`s, e = resolve_period(...)`) and is used later as `account_balances(s, e)`. Reusing `e` as the exception name shadows the end-bound and (per Python `except ... as` semantics) deletes it on block exit — fragile and confusing even though the success path never enters the except block.
- **Fix:** Named the exception variable `exc` and added an intent comment explaining the non-shadowing choice.
- **Files modified:** backend/main.py
- **Verification:** Full cashflow_summary suite green including the this_week/last_week 200 paths that consume `e`; resolve-once grep guard still passes.
- **Committed in:** 4a872f2 (Task 2 commit)

**2. [Rule 3 - Blocking] Test-runner environment adaptation**
- **Found during:** Execution start (before Task 1)
- **Issue:** No `python` on PATH and system `python3` lacks the backend deps (pytest/fastapi/sqlalchemy). The plan's `cd backend && python -m pytest` form also breaks the `backend.*` package imports (rootdir must be the repo root).
- **Fix:** Ran the suites from the repo root via the project's documented dev runner: `uv run --python 3.12 --with-requirements backend/requirements.txt --with pytest-asyncio python -m pytest ...`. Equivalent verification; Postgres was reachable so endpoint 200-paths ran (not skipped).
- **Files modified:** `.gitignore` (added `uv.lock`, the ephemeral lockfile the uv runner emits; `.venv*/` was already ignored)
- **Verification:** Target suites and full backend regression executed successfully under this runner.
- **Committed in:** Included in the plan-metadata docs commit (not a task commit).

---

**Total deviations:** 2 auto-fixed (1 bug-prevention, 1 blocking/environment)
**Impact on plan:** Both necessary for correctness and to run the verification at all. No scope creep — source edits stayed exactly within the two planned handler/registry changes.

## Issues Encountered
- **Full-suite regression shows 1 pre-existing unrelated failure:** `backend/tests/test_settings.py::test_put_settings_requires_key` returns 503 instead of 401 (empty `MONAI_API_KEY` in this local environment). This is a `PUT /settings` auth-config issue with no relationship to periods or cashflow; it was already logged for plan 04-01 and is re-noted under a `## 04-06` heading in `deferred-items.md`. Out of scope per the executor scope boundary. Backend suite result: **109 passed, 1 pre-existing failure**; the two target suites (`test_period_scoping.py` + `test_cashflow_summary.py`) are **17/17 green**.

## User Setup Required
None - no external service configuration required (pure source edits, no new packages — T-04-SC satisfied).

## Next Phase Readiness
- UAT gap 1 backend fix is complete and regression-tested. The remaining verification is the manual/visual UAT truth (D4): open /cashflow, click "This week", confirm the dashboard renders week-scoped figures with no error state.
- `last_week` is now available to the chat agent's tool router for free (same PERIODS registry).

## Self-Check: PASSED

- Files verified present: backend/tools.py, backend/main.py, backend/tests/test_period_scoping.py, backend/tests/test_cashflow_summary.py, this SUMMARY.
- Commits verified in git history: `bf4b7fc` (Task 1), `4a872f2` (Task 2).

---
*Phase: 04-cashflow-dashboard-crud*
*Completed: 2026-07-05*
