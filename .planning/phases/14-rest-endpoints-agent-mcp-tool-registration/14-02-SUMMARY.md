---
phase: 14-rest-endpoints-agent-mcp-tool-registration
plan: 02
subsystem: backend-agent
tags: [llama-index, mcp, agentic-writes, proposals, dual-registration]

# Dependency graph
requires:
  - phase: 13-shared-mutation-layer
    provides: apply_add_transfer, apply_add_investment_transfer, apply_add_funded_buy, apply_add_funded_sell, apply_add_balance_adjustment in backend/writes.py
  - phase: 14-01
    provides: RED propose->confirm integration tests + named-tool MCP registration test pinning the exact target behavior
provides:
  - "5 propose_* functions in backend/tools.py (propose_add_transfer, propose_add_investment_transfer, propose_add_funded_buy, propose_add_funded_sell, propose_add_balance_adjustment), registered only in the trailing TOOLS.update() call"
  - "Dual registration of all 5 tools on the chat agent (backend/query.py write_tools list), so the LLM can see and call them"
  - "5 confirm-time dispatch branches in backend/main.py _execute_proposal_payload, wrapped in a KeyError/TypeError->ValueError guard"
affects: [14-03-rest-endpoints]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Grouped elif dispatch branch (single `elif operation in (...)` with a nested if/elif + try/except) for the 5 new operations, instead of 5 separate top-level elif branches — keeps the KeyError/TypeError->ValueError guard in one place rather than duplicated 5 times"
    - "Funded buy/sell propose_* functions coerce cash_amount/quantity/price through abs(float(x)) so the payload always carries a JSON number (never a string), because apply_add_funded_buy/_sell call abs()/negation on after[key] before any Decimal conversion happens"

key-files:
  created: []
  modified:
    - backend/tools.py
    - backend/query.py
    - backend/main.py

key-decisions:
  - "propose_add_balance_adjustment returns before:null / after:{account_id,target_balance} in the tool's own return dict for a consistent shape, even though the underlying Proposal.payload row (custom, non-before/after shape) mirrors propose_rename_category's convention exactly, per the plan's Analog B"
  - "Grouped the 5 new operations under one elif branch with a nested dispatch + single try/except (KeyError, TypeError) rather than repeating the guard in 5 separate elif blocks — smaller diff, same behavior, still appended after the existing add_holding/edit_holding/delete_holding branches and before the final else"

requirements-completed: []  # CHAT-09 fully completes across 14-02 (agent path, this plan) + 14-03 (REST path)

# Metrics
duration: 35min
completed: 2026-07-31
---

# Phase 14 Plan 02: Agent/MCP Tool Registration for 5 New Writes Summary

**Wired 5 Phase-13 `apply_*` primitives (transfer, investment-transfer, funded-buy, funded-sell, balance-adjustment) onto the chat agent path end-to-end — propose_* tool, dual-registration on the LLM's tool list, and a guarded confirm-dispatch branch — turning all 6 of Plan 14-01's RED agent-path tests GREEN with zero regressions.**

## Performance

- **Duration:** 35 min
- **Completed:** 2026-07-31
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Added 5 `propose_*` functions to `backend/tools.py` (`propose_add_transfer`, `propose_add_investment_transfer`, `propose_add_funded_buy`, `propose_add_funded_sell`, `propose_add_balance_adjustment`), each mirroring the existing `propose_add_transaction`/`propose_rename_category` shapes, registered only in the trailing `TOOLS.update()` call (after the `READ_TOOL_NAMES` snapshot at tools.py:628) — `READ_TOOL_NAMES` still holds exactly 15 names
- Dual-registered all 5 on the chat agent in `backend/query.py`: added to the `from backend.tools import (...)` block and to the `write_tools = [...]` list, with explicit `description=` overrides on `propose_add_investment_transfer`/`propose_add_funded_buy`/`propose_add_funded_sell` documenting the unsigned-magnitude and `platform_id`-is-an-int conventions
- Added the 5 new `apply_*` imports to `backend/main.py`'s `from backend.writes import (...)` block and one grouped `elif operation in (...)` dispatch branch in `_execute_proposal_payload`, wrapped in `try/except (KeyError, TypeError) as e: raise ValueError(...)` so a malformed payload maps to the confirm endpoint's existing `422`, never an unhandled `500`
- Confirmed all 5 propose→confirm integration tests + the named-tool MCP registration test from Plan 14-01 are GREEN (22/22 in `test_proposals.py` + `test_mcp.py`); full suite run shows zero regressions — only the pre-existing `test_settings.py::test_put_settings_requires_key` failure and the 8 `test_write_endpoints.py` REST-path tests (still deferred to Plan 14-03) remain red

## Task Commits

Each task was committed atomically:

1. **Task 1: Add 5 propose_* functions to tools.py + register in the trailing TOOLS.update()** - `61938b7` (feat)
2. **Task 2: Dual-register in query.py + add 5 confirm-dispatch branches (with 422 guard) to main.py** - `3d2d79f` (feat)

## Files Created/Modified
- `backend/tools.py` — +5 `propose_*` functions (transfer, investment-transfer, funded-buy, funded-sell, balance-adjustment) + 5 new entries in the trailing `TOOLS.update()` dict
- `backend/query.py` — +5 imports in the `from backend.tools import (...)` block + 5 `FunctionTool.from_defaults(...)` entries in `write_tools` (3 with explicit `description=` overrides)
- `backend/main.py` — +5 imports in the `from backend.writes import (...)` block + 1 grouped `elif` dispatch branch (5 operations, KeyError/TypeError→ValueError guard) in `_execute_proposal_payload`

## Decisions Made
- Followed the plan's exact payload shapes verbatim, reading `backend/writes.py`'s `apply_*` signatures directly rather than guessing key names from REST schema conventions (`source_account_name` not `account`, `cash_amount` not `amount`, `leg_a`/`leg_b` for transfer, `cash_leg`/`event` for investment-transfer)
- `propose_add_funded_buy`/`propose_add_funded_sell` coerce `cash_amount`/`quantity`/`price` through `abs(float(x))` so the stored `Proposal.payload` always carries a JSON number — matching the load-bearing constraint that `apply_add_funded_buy`/`_sell` call `abs()`/negation on `after[key]` *before* any `Decimal()` conversion, so a `str` there would raise `TypeError`
- `propose_add_investment_transfer`'s deposit event uses the documented sentinel (`ticker="CASH"`, `event_type="deposit"`, `asset_type="cash"`, `price="1"`, `quantity=abs(amount)`), consistent with the existing `asset_type=="cash"` 1:1 valuation convention in `portfolio.py`/`prices.py`
- Grouped all 5 new dispatch branches under one `elif operation in (...)` block with a nested if/elif + single `try/except (KeyError, TypeError)` guard, rather than repeating the guard 5 times — smaller diff, identical behavior, still appended after the existing `add_holding`/`edit_holding`/`delete_holding` branches and before the final `else: raise ValueError(...)`
- `propose_add_balance_adjustment` looks the account up via `get_session_sync()` + `db.get(Account, account_id)` for an early not-found signal and a human-readable summary, returning `{"tool": ..., "error": ...}` if missing — mirrors `propose_rename_category`'s not-found-error convention

## Deviations from Plan

None — plan executed exactly as written. All acceptance criteria met:
- `grep -c` for the 5 new function definitions in `tools.py` returns 5
- Dual-registration grep loop (tools.py + query.py, all 5 names) prints nothing missing
- `main.py` shows all 5 operations across the writes-import block and the dispatch branch (grep count 17)
- `len(READ_TOOL_NAMES) == 15` still holds; all 5 new names present in `TOOLS`, absent from `READ_TOOL_NAMES`
- `pytest backend/tests/test_proposals.py backend/tests/test_mcp.py -q` → 22 passed (5 propose→confirm tests + malformed-payload 422 guard + named-tool registration test, all green)
- `grep -c "db.commit(" backend/writes.py` → 0 (never-commit contract preserved; no double-commit introduced)

## Issues Encountered
None.

## User Setup Required

None — no external service configuration required. Tests ran against the existing live Postgres dev DB (`docker compose`, already running).

## Next Phase Readiness
- Plan 14-03 (REST endpoints) can now implement the 5 direct-write REST route handlers in `main.py` + matching Pydantic schemas in `schemas.py`, calling the same 5 already-tested `apply_*` primitives this plan's agent path already exercises — verified by `test_write_endpoints.py` turning GREEN
- CHAT-09's agent-side success criteria (tools present on the agent surface, absent from MCP, confirm-before-write flow works for all 5 new operations) are fully satisfied; only the direct-REST half of CHAT-09 remains, scoped entirely to Plan 14-03
- No blockers.

---
*Phase: 14-rest-endpoints-agent-mcp-tool-registration*
*Completed: 2026-07-31*

## Self-Check: PASSED

- FOUND: backend/tools.py (propose_add_transfer etc. present)
- FOUND: backend/query.py (dual-registered)
- FOUND: backend/main.py (dispatch branches)
- FOUND: commit 61938b7
- FOUND: commit 3d2d79f
