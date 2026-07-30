---
phase: 14-rest-endpoints-agent-mcp-tool-registration
plan: 01
subsystem: testing
tags: [pytest, fastapi, llama-index, mcp, red-green, wave-0]

# Dependency graph
requires:
  - phase: 13-shared-mutation-layer
    provides: apply_add_transfer, apply_add_investment_transfer, apply_add_funded_buy, apply_add_funded_sell, apply_add_balance_adjustment in backend/writes.py — fully tested, called from nowhere yet
provides:
  - "backend/tests/test_proposals.py: 6 new propose->confirm integration tests (5 operations + malformed-payload 422 guard), all RED except the guard"
  - "backend/tests/test_write_endpoints.py (new file): 5 happy-path direct-REST tests + 3 validation/auth tests, all RED (404/405)"
  - "backend/tests/test_mcp.py: 1 new named-tool registration/exclusion test, RED (TOOLS membership fails)"
  - "Nyquist-compliant RED baseline for Plans 14-02 (agent wiring) and 14-03 (REST wiring) to turn GREEN"
affects: [14-02-agent-tool-registration, 14-03-rest-endpoints]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Lazy in-body import RED idiom (from backend.tools import propose_X inside the test body) reused verbatim from Phase 13's writes.py scaffold — ImportError is the intended RED signal until the tool is registered"
    - "CASH-sentinel-scoped cleanup (never a global ticker purge) for the investment-transfer deposit event, since ticker='CASH' is now a shared production convention, not a disposable test placeholder"

key-files:
  created:
    - backend/tests/test_write_endpoints.py
  modified:
    - backend/tests/test_proposals.py
    - backend/tests/test_mcp.py

key-decisions:
  - "propose_add_funded_buy/_sell test calls omit a `notes` kwarg — the plan's literal signature list for these two tools has no notes param (unlike transfer/investment-transfer, which do)"
  - "test_confirm_malformed_funded_buy_returns_422 passes green today (unknown-operation -> ValueError -> 422 via the existing _execute_proposal_payload else-branch) by design — it becomes the KeyError regression guard once Plan 14-02 wires the add_funded_buy dispatch branch"
  - "REST route tests assert against whatever non-2xx status the router currently returns (404 for genuinely unmatched paths, 405 where an existing path-parameter route like DELETE /transactions/{id} collides with the not-yet-added POST) — both are valid 'route not wired' RED signals, not test bugs"

patterns-established:
  - "REST endpoint test file for Phase 14 follows test_account_crud.py's TestClient + require_api_key header idiom exactly, reusing conftest.py's session-scoped client/api_key fixtures with only local db_available/db_session fixtures"

requirements-completed: []  # CHAT-09 is delivered across Plans 14-02/14-03; this plan only scaffolds its test coverage

# Metrics
duration: 45min
completed: 2026-07-30
---

# Phase 14 Plan 01: Wave-0 RED Test Scaffold Summary

**14 new automated tests (6 propose->confirm, 8 direct-REST/MCP) pin the exact apply_* row/column contracts for Phase 14's 5 new write operations, all RED except a 422-guard that is green by construction — ready for Plans 14-02/14-03 to wire GREEN.**

## Performance

- **Duration:** 45 min
- **Started:** 2026-07-30T21:56:00Z
- **Completed:** 2026-07-30T22:41:36Z
- **Tasks:** 2
- **Files modified:** 3 (1 created, 2 modified)

## Accomplishments
- 5 propose->confirm integration tests in `test_proposals.py` covering transfer, investment-transfer, funded-buy, funded-sell, and balance-adjustment — each asserts real row outcomes (transfer_pair_id equality, source_account_id linkage, Decimal amount signs, category='Adjustment', deposit-event ticker=='CASH') via the lazy-import RED idiom
- 1 malformed-payload guard test (`test_confirm_malformed_funded_buy_returns_422`) that pins the Pitfall-3 KeyError->500 hazard as a permanent regression check
- New `backend/tests/test_write_endpoints.py` with 5 happy-path direct-REST tests + 3 input-validation/auth tests for the 5 proposed routes
- 1 new explicit named-tool assertion in `test_mcp.py` (`test_new_write_tools_registered_and_excluded`) checking TOOLS membership, READ_TOOL_NAMES exclusion, and live MCP tools/list exclusion for all 5 new propose_* names by literal string
- Confirmed 14/14 new tests fail for the RIGHT reason (ImportError, HTTP 404/405, or AssertionError on TOOLS membership) — never a collection/import error unrelated to the missing wiring
- Confirmed all 16 pre-existing tests across the 3 touched files remain green

## Task Commits

Each task was committed atomically:

1. **Task 1: Add 5 propose→confirm integration tests to test_proposals.py (RED)** - `2fc1474` (test)
2. **Task 2: Create test_write_endpoints.py + named-tool MCP assertions in test_mcp.py (RED)** - `773dc53` (test)

_No TDD tasks — this plan IS the RED half of the phase's own red/green cycle across Plans 14-02/14-03._

## Files Created/Modified
- `backend/tests/test_write_endpoints.py` - New file: 5 happy-path REST tests (transfer, investment-transfer, funded-buy, funded-sell, adjust-balance) + 3 validation/auth tests (negative amount, zero cash_amount, missing API key)
- `backend/tests/test_proposals.py` - +6 tests (5 propose->confirm operations + 1 malformed-payload 422 guard) + 4 local seed/cleanup helpers (`_make_account`, `_cleanup_account`, `_cleanup_ticker`, `_cleanup_platform`, `_make_platform_local`)
- `backend/tests/test_mcp.py` - +1 test (`test_new_write_tools_registered_and_excluded`) asserting the 5 new propose_* names by literal string

## Decisions Made
- Followed the plan's literal signature lists verbatim: `propose_add_transfer`/`propose_add_investment_transfer` calls include `notes`; `propose_add_funded_buy`/`propose_add_funded_sell` calls omit it (per the plan's Task-1 bullet list, not RESEARCH's earlier illustrative example)
- Scoped investment-transfer test cleanup to `(platform_id, ticker='CASH')` rather than a global `ticker='CASH'` purge, since RESEARCH's Q1 resolution makes CASH a real production sentinel other platforms may legitimately use — a global purge would risk deleting non-test data in a shared dev DB
- `test_confirm_malformed_funded_buy_returns_422` was written to be intentionally green today (per plan's explicit acceptance criterion: "stays green trivially pre-14-02") rather than RED — it functions purely as a forward-looking regression pin for Plan 14-02's dispatch-branch KeyError hazard

## Deviations from Plan

None - plan executed exactly as written. All acceptance criteria met:
- `grep -c` for the 6 named test functions in test_proposals.py returns 6
- `grep -c` for `test_new_write_tools_registered_and_excluded` in test_mcp.py returns 1
- 5 propose→confirm tests RED via ImportError; malformed-payload guard green; 10 pre-existing test_proposals.py tests unaffected
- test_write_endpoints.py exists with all 8 named tests, all RED (404/405 — no matching route)
- test_mcp.py's new test RED (TOOLS membership assertion fails); 5 pre-existing test_mcp.py tests unaffected
- No bare `Decimal(` placed into any payload/after dict literal — all money fields pass as plain numbers or are converted via `str()`/`float()` at the boundary, matching writes.py's own `Decimal(str(x))` idiom

## Issues Encountered
- Initial assumption (from RESEARCH.md) that unwired REST routes would uniformly 404 didn't hold: `POST /transactions/transfer` returns 405 (Method Not Allowed) because an existing route (e.g. `DELETE /transactions/{id}`) matches the same path pattern for a different HTTP verb. Both 404 and 405 are valid "route not wired for this operation" RED signals — no test logic change needed, just confirmed via full test-run output that every failure traces to a genuinely missing/mismatched route or tool, not a test bug.

## User Setup Required

None - no external service configuration required. Tests run against the existing live Postgres dev DB (`docker compose up db`, already running); verified no `zz14test-` rows leaked after this plan's own RED test run.

## Next Phase Readiness
- Plan 14-02 (agent tool registration) can now implement `propose_add_transfer`/`propose_add_investment_transfer`/`propose_add_funded_buy`/`propose_add_funded_sell`/`propose_add_balance_adjustment` in `tools.py` + `query.py` + the `_execute_proposal_payload` dispatch branches in `main.py`, and verify progress by watching the 5 propose→confirm tests + the MCP registration test turn GREEN
- Plan 14-03 (REST wiring) can implement the 5 route handlers in `main.py` + matching Pydantic schemas in `schemas.py`, verified by `test_write_endpoints.py` turning GREEN
- No blockers. The exact `after`-dict key shapes each `apply_*` function expects (documented in RESEARCH.md Pitfall 3) are now pinned by executable tests, not just prose — a payload-shape mismatch in either follow-on plan will fail loudly and specifically rather than surfacing as a vague chat probe failure

---
*Phase: 14-rest-endpoints-agent-mcp-tool-registration*
*Completed: 2026-07-30*

## Self-Check: PASSED

- FOUND: backend/tests/test_write_endpoints.py
- FOUND: 14-01-SUMMARY.md
- FOUND: commit 2fc1474
- FOUND: commit 773dc53
