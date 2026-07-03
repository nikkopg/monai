---
phase: quick-260703-gco
plan: 01
subsystem: api
tags: [sqlalchemy, postgres, llamaindex, function-agent, tool-router]

# Dependency graph
requires:
  - phase: 02-agentic-loop-confirm-before-write
    provides: FunctionAgent wiring in backend/query.py, propose_edit_transaction/propose_delete_transaction write tools
provides:
  - find_transactions read tool (backend/tools.py) that resolves merchant/category filters to concrete transaction ids
  - FunctionAgent tool visibility for find_transactions (backend/query.py)
  - Integration test coverage for find_transactions (backend/tests/test_tools.py)
affects: [chat-agent, mcp-server, tools-registry]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "find_transactions follows the same resolve_period/_date_clause/engine.connect()/parameterized-text() convention as the other 9 read tools"

key-files:
  created: []
  modified:
    - backend/tools.py
    - backend/query.py
    - backend/tests/test_tools.py

key-decisions:
  - "find_transactions excludes transfers (is_transfer = false) like every other read tool, since the recategorize/delete use case targets normal spend rows"
  - "amount is returned SIGNED (not ABS) so the agent can distinguish expense vs income before proposing an edit/delete"
  - "merchant uses ILIKE partial match with the wildcard in the bound parameter value (never string-interpolated into SQL); category uses exact match"

patterns-established:
  - "Read tools that need to hand a resolvable entity id to a write tool follow this shape: SELECT id, ... ORDER BY date DESC LIMIT :lim so rows[0] is the most-recent match"

requirements-completed: [CHAT-FIND-TX]

coverage:
  - id: D1
    description: "find_transactions tool implemented in backend/tools.py, registered in the read-tools TOOLS dict, using parameterized SQL (merchant ILIKE partial via bound param, category exact match, kind sign filter, resolve_period/_date_clause) and ordered most-recent-first"
    requirement: "CHAT-FIND-TX"
    verification:
      - kind: unit
        ref: "python -c import check: TOOLS['find_transactions'] is find_transactions, signature match"
        status: pass
      - kind: integration
        ref: "backend/tests/test_tools.py::TestToolSQL::test_find_transactions_rows_include_id"
        status: unknown
    human_judgment: false
  - id: D2
    description: "find_transactions is imported and wrapped in FunctionTool.from_defaults inside backend/query.py's read_tools list, making it visible to the FunctionAgent"
    requirement: "CHAT-FIND-TX"
    verification:
      - kind: unit
        ref: "python -c ast check: find_transactions imported + FunctionTool.from_defaults(fn=find_transactions) present; python -c import backend.query"
        status: pass
    human_judgment: false
  - id: D3
    description: "Integration tests cover id presence/type, DESC ordering, limit clamping, kind sign filter, exact category match, and case-insensitive merchant partial match, skipping cleanly when Postgres is unreachable"
    requirement: "CHAT-FIND-TX"
    verification:
      - kind: integration
        ref: "backend/tests/test_tools.py -q (9 passed, 12 skipped — DB unreachable in this sandbox)"
        status: unknown
    human_judgment: true
    rationale: "No live Postgres in the execution sandbox — new tests skip via the db_available fixture instead of running against real data. A human (or CI with DB access) must run pytest against a loaded database to confirm actual row-level behavior (id types, ordering, filters) beyond syntax/import correctness."

# Metrics
duration: 12min
completed: 2026-07-03
status: complete
---

# Quick Task 260703-gco: Add find_transactions Read Tool Summary

**New `find_transactions` read tool resolves merchant/category filters to transaction ids for the chat agent, wired into both the TOOLS registry and the FunctionAgent's read_tools list.**

## Performance

- **Duration:** 12 min
- **Started:** 2026-07-03T11:39:00Z
- **Completed:** 2026-07-03T11:51:29Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments
- Added `find_transactions(merchant, category, period, start_date, end_date, kind, limit)` to `backend/tools.py`, following the exact SQL/parameterization conventions of `largest_transactions`/`transaction_count` (resolve_period, `_date_clause`, `engine.connect()`, clamped limit, bound params for merchant/category)
- Registered `find_transactions` as the final entry in the read-tools `TOOLS` dict
- Wired `find_transactions` into `backend/query.py`'s FunctionAgent — imported in the read-tools import tuple and wrapped via `FunctionTool.from_defaults` in `read_tools`, so the agent can now actually call it
- Added 6 integration tests to `TestToolSQL` in `backend/tests/test_tools.py` covering id presence/type, most-recent-first ordering, limit clamping, kind sign filter, exact category match, and case-insensitive merchant partial match

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement and register find_transactions in backend/tools.py** - `616f080` (feat)
2. **Task 2: Wire find_transactions into the FunctionAgent in backend/query.py** - `b3577b7` (feat)
3. **Task 3: Add find_transactions integration tests to backend/tests/test_tools.py** - `076aae8` (test)

**Plan metadata:** committed separately by the orchestrator (docs commit not made by this executor per constraints)

## Files Created/Modified
- `backend/tools.py` - Added `find_transactions` read tool + registered in `TOOLS`
- `backend/query.py` - Imported and exposed `find_transactions` to the FunctionAgent via `read_tools`
- `backend/tests/test_tools.py` - Added 6 `TestToolSQL` tests for `find_transactions`

## Decisions Made
- Excluded transfers by default (`is_transfer = false`) to match every other read tool's convention — the recategorize/delete use case targets normal spend rows, not transfers.
- Returned `amount` signed (not `ABS()`-wrapped) so the agent can tell expense vs income apart before deciding what to propose.
- Merchant filter uses `ILIKE` with the `%...%` wildcard built into the bound parameter value (never string-interpolated into the SQL text) for case-insensitive partial match; category filter uses an exact `=` match per the plan's constraints.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- The sandbox's Python interpreter initially lacked `sqlalchemy` and other backend dependencies (not installed globally). Resolved by running `pip install -q -r backend/requirements.txt`, which is environment setup, not a code change, and required no deviation-rule fix to the plan's files.
- No live Postgres instance was reachable in this sandbox, so all new `TestToolSQL` tests (and the pre-existing ones) skip via the `db_available` fixture (`pytest.skip(f"Postgres not available: {e}")`). This is the plan's documented DB-skip-if-unreachable convention — `python -m pytest backend/tests/test_tools.py -q` reports `9 passed, 12 skipped`, zero failures. Row-level correctness (actual id values, ordering against real data, filter results) has NOT been verified against a live database; only import-level, signature-level, and SQL-construction correctness (parameterized queries, no f-string interpolation of merchant/category) has been confirmed.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- `find_transactions` is available to the FunctionAgent immediately; no further wiring needed.
- Recommend running `python -m pytest backend/tests/test_tools.py -q` against a loaded Postgres instance (e.g. via `docker compose up -d db` + Wallet CSV import) to get real pass/fail signal on the 6 new integration tests before relying on this tool in production chat flows.
- `find_transactions` closes the last piece of the "resolve merchant name → transaction id → propose_edit/delete" chain described in the Phase 2 tool-coverage gap.

---
*Phase: quick-260703-gco*
*Completed: 2026-07-03*

## Self-Check: PASSED

- FOUND: backend/tools.py
- FOUND: backend/query.py
- FOUND: backend/tests/test_tools.py
- FOUND: .planning/quick/260703-gco-add-find-transactions-read-tool-so-the-a/260703-gco-SUMMARY.md
- FOUND commit: 616f080 (Task 1: feat find_transactions in backend/tools.py)
- FOUND commit: b3577b7 (Task 2: feat wire find_transactions into query.py)
- FOUND commit: 076aae8 (Task 3: test find_transactions integration tests)
