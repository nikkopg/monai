---
phase: 17-ui-new-surfaces-records-tab-categories-manager
plan: 01
subsystem: testing
tags: [pytest, backend, tdd-red, transactions, bulk-endpoints, platform-detail, pair-aware-delete]

# Dependency graph
requires:
  - phase: 16-ui-extend-existing-components
    provides: pair-aware delete (apply_delete_transaction_or_pair), transfer_pair_id column, account_balances transfer inclusion — the behaviors these RED tests pin at the endpoint layer
provides:
  - backend/tests/test_write_endpoints.py — RED coverage for extended GET /transactions (filters/paging/hierarchy/transfer_pair_id), POST /transactions/bulk-delete, POST /transactions/bulk-recategorize, endpoint-level pair-aware delete
  - backend/tests/test_portfolio.py — RED coverage for GET /platforms/{id}/detail and GET /portfolio-events?platform_id=
  - backend/tests/test_write_tools.py — RED coverage for bulk-recategorize transfer-leg skip semantics
affects: [17-03 (backend plumbing that turns these GREEN)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Live-Postgres + TestClient + rollback-probe-insert idiom (no mocking, never permanently mutate live data) reused from existing test_write_endpoints.py / test_write_tools.py"
    - "RED assertions pin the exact Plan 17-03 endpoint contract: extended GET /transactions params, POST /transactions/bulk-delete, POST /transactions/bulk-recategorize, GET /platforms/{id}/detail, GET /portfolio-events?platform_id="

key-files:
  created: []
  modified:
    - backend/tests/test_write_endpoints.py
    - backend/tests/test_portfolio.py
    - backend/tests/test_write_tools.py

key-decisions:
  - "Category-filter test asserts a parent category matches its descendant rows (hierarchy), not exact-string only — pins critical item #3"
  - "type=transfer filter test asserts the filter keys off transfer_pair_id IS NOT NULL; an Adjustment/Investment row (is_transfer=true, transfer_pair_id=null) is NOT returned by type=transfer — pins critical item #4"
  - "Pair-aware delete test asserts deleting ONE transfer leg (single AND bulk) removes BOTH rows with no orphan — pins critical item #1"
  - "Bulk-recategorize test asserts transfer legs are skipped (reported in skipped[], not mutated, not raised) — pins critical item #6"

patterns-established:
  - "Pattern: Wave-0 RED backend scaffold (matching 12-01/13-01/14-01/16-01) — every downstream endpoint gets an executable assertion that fails now (route 404 / missing field / unnarrowed result) and turns green when the implementation plan lands"

requirements-completed: [REC-01, REC-02, REC-03, REC-05, PLAT-01]

duration: ~15min
completed: 2026-08-02
---

# Phase 17 Plan 01: RED Backend Test Baseline Summary

**Three extended backend test files (+470 lines) that pin the four backend-side critical-correctness items — hierarchy category filter, transfer_pair_id semantics, pair-aware delete (single + bulk), and recategorize transfer-leg skip — plus the two platform-detail reads, as executable RED assertions before Plan 17-03 implements them.**

## Accomplishments

- **`backend/tests/test_write_endpoints.py` (+337):** RED tests for the extended `GET /transactions` surface (filters, paging, category hierarchy match, `transfer_pair_id` exposure, `type=transfer` narrowing), plus `POST /transactions/bulk-delete`, `POST /transactions/bulk-recategorize`, and endpoint-level pair-aware delete (single + bulk each remove both legs, no orphan).
- **`backend/tests/test_portfolio.py` (+69):** RED tests for `GET /platforms/{id}/detail` and `GET /portfolio-events?platform_id=` — the two reads the Platform detail surface (17-05) consumes.
- **`backend/tests/test_write_tools.py` (+64):** RED test asserting bulk-recategorize skips transfer legs (reported in `skipped[]`, not mutated, not raised).

## Task Commits

Each task was committed atomically:

1. **Task 1: extended GET /transactions filters/paging/hierarchy/transfer_pair_id** - `5aafa10` (test)
2. **Task 2: bulk-delete/bulk-recategorize + endpoint-level pair-aware delete** - `ed8fdb8` (test)
3. **Task 3: platform-detail and portfolio-events-by-platform reads** - `04a11a9` (test)

**Plan metadata:** (this commit)

## Notes / Recovery

The executor completed all 3 test tasks and their atomic commits, then was terminated by a session-limit API error while running the final aggregate `--collect-only`/verification pass — before writing this SUMMARY. The orchestrator wrote and committed this SUMMARY as a clean-tail recovery (all 3 task commits were already present with a clean working tree; no code work was lost). RED confirmation of the aggregate collection is deferred to Plan 17-03, which must turn these tests GREEN and will surface any collection error immediately.
