---
phase: 04-cashflow-dashboard-crud
plan: 02
subsystem: api
tags: [fastapi, sqlalchemy, pydantic, postgres, tools-registry]
status: complete

# Dependency graph
requires: []
provides:
  - "monthly_trend(months=6) read aggregation in backend/tools.py — rolling >=6-month window (CASH-02)"
  - "account_balances(period_start, period_end) read aggregation in backend/tools.py — dual per-account balances (CASH-03/D-04)"
  - "CashflowSummary, TransactionUpdate, AccountCreate, AccountUpdate, CategoryRenameRequest, CategoryMergeRequest, AffectedCountResponse DTOs in backend/schemas.py"
  - "backend/tests/test_cashflow_summary.py pinning CASH-01/02/03 aggregation-layer behavior"
affects: [04-03-cashflow-summary-endpoint, 04-01-write-endpoints]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Read aggregations follow engine.connect()+text()+float() boundary convention (no Decimal on read path)"
    - "account_balances() accepts pre-resolved (start,end) tuple; does not call resolve_period itself — caller resolves once"
    - "TransactionUpdate/AccountUpdate use all-Optional partial-update schema shape, reusing shared MoneyDecimal type"

key-files:
  created:
    - backend/tests/test_cashflow_summary.py
  modified:
    - backend/tools.py
    - backend/schemas.py

key-decisions:
  - "monthly_trend uses date_trunc('month', CURRENT_DATE) - INTERVAL rolling window, not date_trunc('year') — verified via grep acceptance criterion"
  - "account_balances period predicate built inline (t.date >= :period_start / t.date < :period_end) rather than reusing _date_clause verbatim, since _date_clause hardcodes the unqualified 'date' column name and account_balances needs the 't.' table alias inside a FILTER clause"
  - "TransactionUpdate.amount reuses MoneyDecimal (Annotated[Decimal, PlainSerializer]) rather than redeclaring — verified via import and no-Decimal-in-tools.py acceptance checks"

patterns-established:
  - "New tools.py read aggregations register themselves in the module-level TOOLS dict alongside existing entries"

requirements-completed: [CASH-01, CASH-02, CASH-03]

# Metrics
duration: 25min
completed: 2026-07-05
---

# Phase 04 Plan 02: Cashflow Read Aggregations + DTOs Summary

**Added monthly_trend() (rolling >=6-month window) and account_balances() (dual per-account current/period balances) to tools.py, plus seven new Pydantic DTOs in schemas.py, backed by a passing test_cashflow_summary.py.**

## Performance

- **Duration:** 25 min
- **Started:** 2026-07-05T00:20:00Z (approx)
- **Completed:** 2026-07-05T00:46:20Z
- **Tasks:** 3 completed
- **Files modified:** 3 (2 modified, 1 created)

## Accomplishments
- `monthly_trend(months=6)` — rolling window (`date_trunc('month', CURRENT_DATE) - INTERVAL`), NOT calendar-year bound, clamps to >=6 months, excludes transfers
- `account_balances(period_start, period_end)` — LEFT JOIN accounts→transactions giving `current_balance` (all-time) and `period_net` (scoped), zero-transaction accounts appear as 0/0
- Seven new DTOs in `backend/schemas.py`: `CashflowSummary`, `TransactionUpdate` (partial, `MoneyDecimal` amount), `AccountCreate`/`AccountUpdate`, `CategoryRenameRequest`/`CategoryMergeRequest`, `AffectedCountResponse`
- `backend/tests/test_cashflow_summary.py` — 4 tests (3 required + 1 extra LEFT JOIN coverage test), all pass against live Postgres

## Task Commits

Each task was committed atomically:

1. **Task 1: Add monthly_trend() and account_balances() read aggregations to backend/tools.py** - `c10fbcb` (feat)
2. **Task 2: Declare new Pydantic DTOs in backend/schemas.py** - `82f8da5` (feat)
3. **Task 3: Create Wave-0 test scaffold backend/tests/test_cashflow_summary.py** - `6389b13` (test)

**Plan metadata:** (this commit, see below)

## Files Created/Modified
- `backend/tools.py` — added `monthly_trend()`, `account_balances()`, registered both in `TOOLS` dict
- `backend/schemas.py` — added `CashflowSummary`, `TransactionUpdate`, `AccountCreate`, `AccountUpdate`, `CategoryRenameRequest`, `CategoryMergeRequest`, `AffectedCountResponse`
- `backend/tests/test_cashflow_summary.py` — new test file, reuses `db_available`/`db_session` fixture pattern and `_make_account`/`_make_transaction` helper style from `test_write_tools.py`

## Decisions Made
- `account_balances()` builds its period predicate inline (`t.date >= :period_start AND t.date < :period_end`) rather than calling the existing `_date_clause()` helper verbatim, because `_date_clause()` hardcodes the unqualified `date` column name and this query needs the `t.` table-alias qualifier inside a `FILTER (WHERE ...)` clause against a `LEFT JOIN`. Same bound-parameter, same semantics, same rolling behavior — just avoids a string-replace hack on the helper's output.
- Added one test beyond the plan's required three (`test_account_balances_zero_transactions`) to explicitly pin the LEFT JOIN "0/0 for zero-transaction accounts" behavior called out in the plan's `<behavior>` block, since none of the three required tests directly exercised it.

## Deviations from Plan

None — plan executed exactly as written. No architectural changes, no new packages, no scope creep.

## Issues Encountered

One pre-existing, unrelated test failure was observed during full-suite verification: `backend/tests/test_settings.py::test_put_settings_requires_key` fails with `503` instead of the expected `401` in this environment (an `MONAI_API_KEY`/settings-availability configuration issue, not touched by this plan — confirmed present on the base commit before any changes in this plan, and unrelated to `tools.py`/`schemas.py`/`test_cashflow_summary.py`). Logged here per the scope-boundary rule; not fixed as it is out of scope for Plan 02.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- `monthly_trend()` and `account_balances()` are ready for Plan 03's `GET /cashflow/summary` endpoint to compose alongside existing `spending_total`/`income_total`/`net_total`/`spending_by_category`.
- All seven new DTOs are ready for Plan 01 (write endpoints) and Plan 03 (summary endpoint) to import.
- No blockers for downstream plans in this phase.

---
*Phase: 04-cashflow-dashboard-crud*
*Completed: 2026-07-05*
