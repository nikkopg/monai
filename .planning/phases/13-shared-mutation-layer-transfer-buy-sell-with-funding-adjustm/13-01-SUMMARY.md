---
phase: 13-shared-mutation-layer-transfer-buy-sell-with-funding-adjustm
plan: 01
subsystem: testing
tags: [pytest, sqlalchemy, postgres, writes.py, tdd, red-scaffold]

# Dependency graph
requires:
  - phase: 12-typed-accounts-transfer-funding-schema-foundations
    provides: transactions.transfer_pair_id + portfolio_events.source_account_id columns (migration 010)
provides:
  - Eight RED pytest tests pinning the exact contract for 5 new backend/writes.py apply_* functions and the leg-protection guard, ready as a fixed GREEN target for plans 13-03/04/05
affects: [13-03, 13-04, 13-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Function-local `from backend.writes import ...` inside each RED test body so collection succeeds while the target function is still absent"
    - "zz13test- account/platform name prefix for shared-live-DB test isolation (matches existing zz%/Test% purge patterns in conftest.py)"
    - "_cleanup_account(db, name) helper mirroring _cleanup_ticker's shape for the account side"

key-files:
  created: []
  modified:
    - backend/tests/test_write_tools.py
    - backend/tests/test_cashflow_summary.py

key-decisions:
  - "apply_add_transfer(db, leg_a_after, leg_b_after) takes two Transaction-shaped after dicts, one per leg — matches the composed-primitive idiom already established for apply_add_portfolio_event"
  - "apply_add_investment_transfer(db, cash_leg_after, event_after) — deposit event_type is a literal string 'deposit', not buy/sell/dividend; recompute_holding_from_events tolerates unknown event types (falls through with qty/cost untouched)"
  - "apply_add_funded_buy(db, after) takes ONE after dict per RESEARCH.md's illustrative Pattern 1 (source_account_name, cash_currency, cash_amount, ticker, quantity, price, platform_id, event_currency) and returns {'transaction':, 'portfolio_event':}"
  - "apply_add_balance_adjustment(db, account_id, target_balance) takes positional account_id + target_balance (not an after-dict) per the RESEARCH architecture diagram"
  - "Balance-adjustment row is tagged category='Adjustment' AND is_transfer=True — is_transfer=True is the only existing mechanism that excludes a row from spending_total/income_total/net_total (D-08), so the adjustment write must set it explicitly"

requirements-completed: [ACCT-02, XFER-01, XFER-02, XFER-03, XFER-04]

# Metrics
duration: 45min
completed: 2026-07-30
---

# Phase 13 Plan 01: RED-First Validation Scaffold for the Shared Mutation Layer Summary

**Eight pytest tests, all RED for the documented reason, locking the exact contract for 5 new `backend/writes.py` apply_* functions and the leg-protection guard before any implementation exists.**

## Performance

- **Duration:** 45 min
- **Tasks:** 2 completed
- **Files modified:** 2

## Accomplishments
- 5 RED tests targeting the five new `writes.py` functions this phase adds: `apply_add_transfer` (XFER-01), `apply_add_investment_transfer` (XFER-02), `apply_add_funded_buy` (XFER-03/04, run twice — once for the one-commit-boundary assertion, once for dual-currency legs), `apply_add_balance_adjustment` (ACCT-02)
- 2 RED tests targeting the leg-protection guard (D-04) on the *existing* `apply_edit_transaction`/`apply_delete_transaction` — both currently fail with `Failed: DID NOT RAISE ValueError` since the guard doesn't exist yet
- 1 RED integration test (`test_adjustment_excluded_from_cashflow`, D-08) in `test_cashflow_summary.py` pinning both halves of the exclusion contract: adjustment invisible to `spending_total`/`income_total`/`net_total`, still counted in the account's derived (unfiltered `SUM`) balance
- Verified via live run against the shared dev Postgres: exactly the 8 new tests fail RED (6 `ImportError`, 2 `DID NOT RAISE`), all 42 pre-existing tests in both files still pass, zero collection errors, zero leaked `zz13test-*`/`ZZ13*` rows after the run

## Task Commits

Each task was committed atomically:

1. **Task 1: RED tests for the five new writes.py apply_* functions** - `5014f8e` (test)
2. **Task 2: RED tests for the leg-protection guard (D-04) and adjustment cashflow exclusion (D-08)** - `f7f1ada` (test)

_Note: file-level Edit calls for both tasks landed in one pass; the two commits were split by exact line range (`test_write_tools.py:1-1526` for Task 1, the remainder + `test_cashflow_summary.py` for Task 2) so each commit maps 1:1 to its plan task, verified `diff` byte-identical to the fully-written file before committing._

## Files Created/Modified
- `backend/tests/test_write_tools.py` — +7 new tests (5 for the new apply_* functions, 2 for the leg-protection guard) + `_cleanup_account` helper
- `backend/tests/test_cashflow_summary.py` — +1 new test (`test_adjustment_excluded_from_cashflow`)

## Decisions Made
- See `key-decisions` in frontmatter for the locked function signatures (`apply_add_transfer(db, leg_a_after, leg_b_after)`, `apply_add_investment_transfer(db, cash_leg_after, event_after)`, `apply_add_funded_buy(db, after) -> dict`, `apply_add_balance_adjustment(db, account_id, target_balance)`) — these are now the FIXED contract plans 13-03/04/05 must implement to.
- Adjustment row tagging: `category="Adjustment"` (human-visible tag) + `is_transfer=True` (the mechanism that actually excludes it from `cashflow_transactions`-filtered totals). This was inferred from D-08's requirement since the schema has no dedicated "excluded" flag — `is_transfer` is the only lever the existing `spending_total`/`income_total`/`net_total` SQL respects.
- `test_apply_add_transfer_pairs_both_legs` deliberately uses two DIFFERENT currencies (IDR/USD) on the two legs to exercise D-09's dual-currency capability, even though a same-currency liquid↔liquid transfer is the more common real-world case.

## Deviations from Plan

None — plan executed exactly as written. No `apply_*` function was implemented (out of scope per the RED-first contract); only test code was added.

## Issues Encountered

None. The DB fixture (`db_available`) required a running `docker compose up db` — already up in this environment (`monai-db` container healthy on :5434) — so no skip/auth gate was hit.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

Plans 13-03 (transfer + leg-protection guard), 13-04 (investment transfer + funded buy/sell), and 13-05 (balance adjustment) each have a fixed, pre-written pytest target: implement `backend/writes.py` until `pytest backend/tests/test_write_tools.py backend/tests/test_cashflow_summary.py -k "transfer or funded or balance_adjustment or investment_transfer or paired_leg or adjustment_excluded"` goes fully GREEN. No blockers.

---
*Phase: 13-shared-mutation-layer-transfer-buy-sell-with-funding-adjustm*
*Completed: 2026-07-30*

## Self-Check: PASSED

- FOUND: backend/tests/test_write_tools.py
- FOUND: backend/tests/test_cashflow_summary.py
- FOUND: .planning/phases/13-shared-mutation-layer-transfer-buy-sell-with-funding-adjustm/13-01-SUMMARY.md
- FOUND commit: 5014f8e
- FOUND commit: f7f1ada
