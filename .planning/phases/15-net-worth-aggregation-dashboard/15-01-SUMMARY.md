---
phase: 15-net-worth-aggregation-dashboard
plan: 01
subsystem: api
tags: [fastapi, sqlalchemy, pydantic, llamaindex, fastmcp, pytest]

# Dependency graph
requires:
  - phase: 12-typed-accounts-liquid-investment-partition-reconciliation
    provides: "accounts.type NOT NULL + ck_accounts_type CHECK IN ('liquid','investment') — the DB-enforced partition net_worth relies on"
  - phase: 13-shared-mutation-layer-transfer-buy-sell-with-funding-adjustm
    provides: "liquid<->investment transfer/funded-buy/sell writes that keep investment money OFF the accounts table (why the investment side reads portfolio_summary, never account balances)"
provides:
  - "net_worth() read tool composing liquid (account_balances filtered type='liquid') + investment (portfolio_summary.total_value)"
  - "GET /net-worth endpoint (open read, 422-safe coverage assertion)"
  - "account_balances() additive `type` field (backward compatible)"
  - "NetWorth Pydantic schema"
  - "net_worth dual-registered on TOOLS/READ_TOOL_NAMES + query.py agent read_tools + MCP description"
affects: [15-02, 16-liquids-and-investments-ui-extend-existing-components]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Composed-read endpoint (mirrors cashflow_summary/investments_summary): resolve/compose tools.py+portfolio.py, try/except ValueError -> HTTPException(422)"
    - "Session-optional read tool: net_worth(db=None) opens/closes its own SessionLocal when called with zero args (agent/MCP path), matching portfolio_summary's Session-based signature when db is passed explicitly"
    - "Source-grep regression guard (inspect.getsource) for testing manual dual-registration surfaces that aren't module-level importable"

key-files:
  created:
    - backend/tests/test_net_worth.py
  modified:
    - backend/tools.py
    - backend/schemas.py
    - backend/main.py
    - backend/query.py
    - backend/mcp_server.py
    - backend/tests/test_mcp.py

key-decisions:
  - "net_worth(db=None) lives in tools.py (not a new module) despite needing a Session, for import-path consistency with the rest of the TOOLS registry (RESEARCH.md A2)"
  - "Liquid filter is strictly accounts.type == 'liquid' in Python over account_balances() rows — never by name/id, never a new SQL WHERE clause"
  - "Coverage assertion raises before calling portfolio_summary, so a stubbed classification gap never triggers a real investment-side query"

requirements-completed: [NW-01, NW-02]

# Metrics
duration: ~50min (session interrupted by a limit mid-Task-2-commit; resumed same worktree, no rework needed)
completed: 2026-07-31
---

# Phase 15 Plan 01: Net Worth Aggregation (Backend) Summary

**`net_worth()` read tool + `GET /net-worth` composing liquid (type='liquid' account balances) + investment (portfolio_summary.total_value) into one coverage-asserted, dual-registered payload — fixes the root cause of the live client-side net-worth double-count.**

## Performance

- **Duration:** ~50 min across two sessions (interrupted by a session limit right after Task 2's verification, resumed in the same worktree with zero rework — Task 2's uncommitted diff was verified green then committed as-is)
- **Completed:** 2026-07-31
- **Tasks:** 3/3
- **Files modified:** 6 (1 created, 5 modified)

## Accomplishments
- `net_worth()` composes the two existing single-source reads (`account_balances` filtered to `type='liquid'`, `portfolio_summary(db).total_value`) with a loud `ValueError` coverage assertion (D-05) — no re-derivation, no double-counting by construction
- `account_balances()` extended additively with `a.type` (existing consumers — `CashflowSummary.accounts`, frontend `AccountBalance` — unaffected; regression-tested)
- `GET /net-worth` live, open read, coverage-gap `ValueError` mapped to HTTP 422 (never a raw 500 — T-14-07 precedent)
- `net_worth` dual-registered: `TOOLS`/`READ_TOOL_NAMES` (MCP auto-flow) AND `query.py`'s explicit agent `read_tools` list (the exact gap `chat-tool-dual-registration` memory warns about)
- `backend/tests/test_net_worth.py` — 6/6 green, including the coverage-assertion raise and a source-grep regression guard on the agent registration line

## Task Commits

Each task was committed atomically:

1. **Task 1: create backend/tests/test_net_worth.py (RED)** - `1fbced3` (test)
2. **Task 2: net_worth() + extend account_balances + NetWorth schema + TOOLS registration** - `4332a23` (feat)
3. **Task 3: GET /net-worth endpoint + query.py agent registration + MCP description** - `a276ffe` (feat)

**Plan metadata:** commit pending (this SUMMARY.md, staged next)

_Note: Task 2 was TDD-flavored (tdd="true" in the plan) but landed as a single feat commit since Task 1 already shipped the full RED suite — Task 2's job was turning those 4 unit-level cases green, verified before commit._

## Files Created/Modified
- `backend/tests/test_net_worth.py` - 6 test cases: counted-once partition, split-reconciles-to-total, coverage-gap ValueError (stubbed), read-only registry membership, agent dual-registration (source-grep), GET /net-worth endpoint
- `backend/tools.py` - `account_balances()` gains additive `a.type`; new `net_worth(db=None)`; registered in `TOOLS` before the `READ_TOOL_NAMES` freeze; comments updated (16 read / 27 total TOOLS entries)
- `backend/schemas.py` - `NetWorth(BaseModel)` mirroring `CashflowSummary`'s loose-list style
- `backend/main.py` - `GET /net-worth` (open read, `try/except ValueError -> HTTPException(422)`); imports added to existing `backend.schemas`/`backend.tools` blocks
- `backend/query.py` - `net_worth` added to `_get_agent_workflow`'s import block and `read_tools` `FunctionTool` list
- `backend/mcp_server.py` - `MCP_DESCRIPTIONS["net_worth"]` entry; docstring counts updated (build_mcp() itself needed no code change — it loops `READ_TOOL_NAMES` automatically)
- `backend/tests/test_mcp.py` - hardcoded read-tool-count assertions bumped 15→16 (direct, required consequence of registering the 16th read tool)

## Decisions Made
- `net_worth` stays in `tools.py` (RESEARCH.md A2) rather than a new module, despite being the first `TOOLS`-registry function that needs a `Session` — keeps the import surface (`query.py`'s single `from backend.tools import (...)`) consistent
- Liquid/investment partition is `accounts.type` only, reusing the exact discriminator `cashflow_transactions` already uses (never name/id filtering)
- Investment total is never re-derived — always `portfolio_summary(db).total_value`, which already folds in the CASH sentinel holding (Pitfall 4)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Plan's literal `test_net_worth_registered_for_agent` spec was unimplementable as written**
- **Found during:** Task 1 (writing the RED test suite)
- **Issue:** The plan and PATTERNS.md both specify `from backend.query import read_tools` to assert agent dual-registration. Inspection of `backend/query.py` showed `read_tools` is a local variable inside `_get_agent_workflow()`, not a module-level export — that import always raises `ImportError`, regardless of whether `net_worth` is registered. As literally specified the test would stay RED forever even after Task 3 shipped the registration, i.e. it wasn't a valid regression guard.
- **Fix:** Rewrote the test to use `inspect.getsource(_get_agent_workflow)` + string assertions for `"net_worth"` and `"FunctionTool.from_defaults(fn=net_worth)"` — the same source-grep-guard style already established in this file's sibling (`test_cashflow_summary_resolve_period_called_once`). Achieves the plan's stated intent (RED if the FunctionTool line is ever removed) without an invasive refactor of `query.py`'s lazy-import structure (which exists intentionally to defer heavy `llama_index` imports).
- **Files modified:** backend/tests/test_net_worth.py
- **Verification:** Test is RED before Task 3 (assertion fails, not ImportError) and GREEN after Task 3's registration lands
- **Committed in:** 1fbced3 (Task 1), confirmed passing in a276ffe (Task 3)

**2. [Rule 3 - Blocking] test_mcp.py's hardcoded read-tool-count assertions broke as a direct, intended consequence of Task 3**
- **Found during:** Task 3 full-suite verification
- **Issue:** `test_mcp_read_parity` and `test_agent_read_tools_count` hardcoded `15` (the pre-Phase-15 read-tool count). Registering the 16th read tool (`net_worth`) is exactly what the plan requires, so these assertions were now correctly failing — not a bug in the new code, but a stale pin that must move with it (same pattern as the `TOOLS registry mutates to 26` memory).
- **Fix:** Bumped both assertions and their docstrings to `16`; updated matching comments in `backend/tools.py` (27 total / 16 read) and `backend/mcp_server.py` (16 read callables) for consistency.
- **Files modified:** backend/tests/test_mcp.py, backend/tools.py, backend/mcp_server.py
- **Verification:** `pytest backend/tests/ -q` — only the pre-existing, previously-logged-unrelated `test_put_settings_requires_key` failure remains (503 vs 401, confirmed unrelated to this or prior phases per STATE.md)
- **Committed in:** a276ffe (Task 3 commit)

---

**Total deviations:** 2 auto-fixed (1 bug in the plan's test spec, 1 blocking/expected regression from the intended registry change)
**Impact on plan:** Both fixes were required to make the plan's own stated intent (a real, working dual-registration regression guard; a fully green backend suite) actually true. No scope creep — no production behavior changed beyond what Tasks 2/3 specify.

## Issues Encountered
- Session was interrupted by a platform session limit immediately after Task 2's verification passed, before the commit landed. Resumed in the same worktree; re-ran Task 2's verification (still green, no drift) before committing — no rework needed.
- None else.

## User Setup Required
None - no external service configuration required. No new dependencies (composition of existing first-party code only, per RESEARCH.md's Package Legitimacy Audit = N/A).

## Next Phase Readiness
- Backend contract for NW-01/NW-02/SC#3 is fully shipped and tested: `GET /net-worth` returns `{total, liquid_total, investment_total, liquid_accounts, investment_groups, accounts_covered, accounts_total}`, with `total == liquid_total + investment_total` verified both by unit test and live smoke test against the real dataset (`total: 310,474,634.28`, `accounts_covered/accounts_total: 9/9`, no coverage gap).
- Plan 15-02 (frontend dashboard rescope, D-07/D-08) is unblocked — the exact payload shape it needs is live and stable.
- No blockers or concerns carried forward.

---
*Phase: 15-net-worth-aggregation-dashboard*
*Completed: 2026-07-31*
