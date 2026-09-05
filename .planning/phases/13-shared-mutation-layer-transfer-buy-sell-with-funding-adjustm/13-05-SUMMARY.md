---
phase: 13-shared-mutation-layer-transfer-buy-sell-with-funding-adjustm
plan: 05
subsystem: backend-writes
tags: [writes.py, decimal, derived-balance, cashflow-exclusion, audit-log]

# Dependency graph
requires:
  - phase: 13-shared-mutation-layer-transfer-buy-sell-with-funding-adjustm
    plan: 01
    provides: RED test contract for apply_add_balance_adjustment(db, account_id, target_balance)
provides:
  - apply_add_balance_adjustment(db, account_id, target_balance) in backend/writes.py
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Fresh, dedicated, unfiltered SUM(amount) query for derived-balance delta — never reuse tools.py:account_balances (Finding 2)"
    - "Pass str(delta) into the composed after dict, not the Decimal object — AuditLog JSON-serializes after and Decimal isn't serializable; apply_add_transaction re-applies Decimal(str(x)) itself"

key-files:
  created: []
  modified:
    - backend/writes.py

key-decisions:
  - "apply_add_balance_adjustment composes apply_add_transaction rather than hand-rolling an insert — gets the Decimal idiom, account resolution, and the one AuditLog row for free (D-02)"
  - "Account resolved via db.get(Account, account_id) to read name/currency for the composed after dict — no hard-coded account id anywhere (Finding 1)"

requirements-completed: [ACCT-02]

# Metrics
duration: 20min
completed: 2026-07-30
---

# Phase 13 Plan 05: Balance Adjustment (Derived-Balance Delta) Summary

**`apply_add_balance_adjustment` reconciles an account's derived balance to a target by writing one "Adjustment"-tagged, transfer-flagged Transaction whose amount is computed against a fresh, unfiltered SUM — never the transfer-excluding `tools.py:account_balances` — closing ACCT-02 and turning the last two 13-01 RED tests GREEN.**

## Performance

- **Duration:** 20 min
- **Tasks:** 1 completed
- **Files modified:** 1

## Accomplishments
- Added `apply_add_balance_adjustment(db, account_id, target_balance)` to `backend/writes.py`, matching the signature locked by plan 13-01's RED test
- Delta computed via a dedicated `SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE account_id = :id` with NO `is_transfer` filter (Finding 2) — deliberately does not reuse `tools.py:account_balances`, whose `is_transfer = false` join clause would produce a delta off by the account's entire transfer volume
- The single adjustment row is tagged `category="Adjustment"` (human-readable disambiguator) AND `is_transfer=True` (the actual mechanism, per D-08, that excludes it from `spending_total`/`income_total`/`net_total` while still counting toward the unfiltered derived-balance SUM)
- No stored balance column written anywhere — the account balance stays fully derived (D-07)
- Composes `apply_add_transaction` rather than inserting directly — inherits the `Decimal(str(x))` money idiom, account-name/currency lookup, flush-before-audit, and single `AuditLog` row (D-02) for free; the new function itself never commits (D-01)
- Fixed a Decimal/JSON-serialization gotcha inline: the computed `delta` is a `Decimal`, but `AuditLog.after` is JSON-serialized, so `str(delta)` (not the `Decimal` object) is passed into the composed `after` dict — `apply_add_transaction` re-applies `Decimal(str(x))` itself

## Task Commits

1. **Task 1: Add apply_add_balance_adjustment (derived-balance delta, D-07/D-08, Finding 2)** - `7d275b8` (feat)

## Files Created/Modified
- `backend/writes.py` — `+apply_add_balance_adjustment` (31 lines, inserted after `apply_add_transaction`)

## Decisions Made
- Account is resolved via `db.get(Account, account_id)` purely to read `name`/`currency` for the composed `after` dict handed to `apply_add_transaction` (which itself resolves/creates by name) — no literal account id anywhere in the function body, matching Finding 1's constraint.
- No new imports needed — `Account`, `Decimal`, `text`, and `apply_add_transaction` were already available in `writes.py`.

## Deviations from Plan

None — plan executed exactly as written. The Decimal-serialization fix was already flagged as a known gotcha in the plan's `<critical_constraints>` (carried over from plan 13-04) and was applied proactively, not discovered as a bug.

## Verification

- `pytest backend/tests/test_write_tools.py::test_apply_add_balance_adjustment_delta backend/tests/test_cashflow_summary.py::test_adjustment_excluded_from_cashflow -x` — 2 passed
- `pytest backend/tests/test_write_tools.py -x` — 38 passed (no regression to plans 03/04)
- `grep -vE '^\s*#' backend/writes.py | grep -c 'db.commit'` — 0
- No literal account id in the new function (verified by read)
- Live DB check: zero leaked `zz13test*`/`ZZ13*` accounts, zero leftover `category='Adjustment'` rows after the test run

## Final Suite Check (last plan of phase 13)

`pytest backend/tests/ -q` — **256 passed, 1 failed** (11.24s).

The one failure, `backend/tests/test_settings.py::test_put_settings_requires_key` (expects `401`, got `503 Service Unavailable`), is **pre-existing and out of scope**: this plan touched only `backend/writes.py`; the failure is unrelated to `apply_add_balance_adjustment`, `writes.py`, or account/transaction logic. Confirmed by stashing this plan's diff and re-running the test in isolation — it fails identically on the pre-plan tree. Root cause appears to be a missing/misconfigured `MONAI_API_KEY` (or equivalent) causing the settings-auth dependency to raise a 503 instead of evaluating to a 401 in this dev environment. Not fixed here per the deviation-rules scope boundary (out-of-scope, unrelated file `backend/main.py` / settings auth dependency, not caused by this task's changes).

All 8 of plan 13-01's originally-RED tests are now GREEN across plans 13-03/13-04/13-05:
- `apply_add_transfer` (13-03)
- leg-protection guard on `apply_edit_transaction`/`apply_delete_transaction` (13-03)
- `apply_add_investment_transfer` (13-04)
- `apply_add_funded_buy` (dual assertions) (13-04)
- `apply_add_balance_adjustment` (this plan)
- `test_adjustment_excluded_from_cashflow` (this plan)

## Issues Encountered

None beyond the pre-existing, out-of-scope `test_settings.py` failure documented above.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

Phase 13's shared mutation layer is complete: all 5 planned `apply_*` functions (`apply_add_transfer`, `apply_add_investment_transfer`, `apply_add_funded_buy`, `apply_add_balance_adjustment`) plus the leg-protection guard are implemented and GREEN. No blockers for phase closeout. The `test_settings.py` 503-vs-401 failure should be tracked separately (not a phase-13 scope item).

---
*Phase: 13-shared-mutation-layer-transfer-buy-sell-with-funding-adjustm*
*Completed: 2026-07-30*

## Self-Check: PASSED

- FOUND: backend/writes.py (apply_add_balance_adjustment present, line 79)
- FOUND commit: 7d275b8
