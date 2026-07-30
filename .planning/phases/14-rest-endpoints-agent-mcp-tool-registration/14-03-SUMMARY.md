---
phase: 14-rest-endpoints-agent-mcp-tool-registration
plan: 03
subsystem: api
tags: [fastapi, pydantic, rest, direct-write, mutation-layer]

# Dependency graph
requires:
  - phase: 13-shared-mutation-layer
    provides: apply_add_transfer, apply_add_investment_transfer, apply_add_funded_buy, apply_add_funded_sell, apply_add_balance_adjustment in backend/writes.py
  - phase: 14-01
    provides: RED test_write_endpoints.py (8 tests) pinning the exact REST request/response contract for the 5 new operations
  - phase: 14-02
    provides: agent-path apply_* wiring + the abs(float(x)) JSON-safety convention for funded-buy/sell, reused here after discovering it also applies to the REST path
provides:
  - "5 *Create Pydantic schemas in backend/schemas.py (TransferCreate, InvestmentTransferCreate, FundedBuyCreate, FundedSellCreate, BalanceAdjustmentCreate)"
  - "5 REST route handlers in backend/main.py: POST /transactions/transfer, /transactions/investment-transfer, /portfolio-events/funded-buy, /portfolio-events/funded-sell, /accounts/{account_id}/adjust-balance"
  - "All 5 routes route through Phase-13 apply_*, require_api_key-gated, commit exactly once, reset_engine() after write, ValueError->422"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Direct (non-agent) REST write idiom: build after-dict(s) -> apply_*(db, ...) in try/except ValueError -> db.commit() -> db.refresh() -> reset_engine() -> return ids, mirroring create_account/create_transfer exactly"
    - "float(), not Decimal, for quantity/price/cash_amount flowing into apply_add_funded_buy/_sell — the primitive's inner after-dict is written straight into AuditLog.after (JSONB), so raw Decimal breaks serialization regardless of REST vs proposal path"

key-files:
  created: []
  modified:
    - backend/schemas.py
    - backend/main.py

key-decisions:
  - "Corrected the plan's load_bearing_constraints claim that funded-buy/sell REST bodies need no float coercion — apply_add_funded_buy/_sell build an inner after-dict that flows into AuditLog.after (JSONB) inside apply_add_transaction/apply_add_portfolio_event, so a raw Decimal there raises TypeError on write regardless of whether the caller is the REST path or the proposal-confirm path; fixed by coercing quantity/price/cash_amount to float(), matching 14-02's propose_add_funded_buy/_sell convention"
  - "adjust_account_balance route wraps apply_add_balance_adjustment in try/except ValueError for consistency with every other write route, even though the primitive doesn't currently raise ValueError for a nonexistent account_id (it falls back to an 'Unknown' account name, matching apply_add_transaction's existing account-by-name convention) — no test exercises this path in 14-01's RED suite"
  - "transfer and investment-transfer routes keep the str(Decimal) convention exactly as written in RESEARCH/PATTERNS.md (verified correct — apply_add_transfer/apply_add_investment_transfer compose apply_add_transaction directly with string amounts, no intermediate Decimal touches AuditLog.after)"

requirements-completed: [CHAT-09]

# Metrics
duration: 25min
completed: 2026-07-30
---

# Phase 14 Plan 03: Direct REST Endpoints for 5 New Writes Summary

**5 require_api_key-gated REST routes (transfer, investment-transfer, funded-buy, funded-sell, adjust-balance) route through Phase-13's apply_* primitives, giving external API-key-authenticated clients a confirm-free write path parallel to the chat proposal flow — completing CHAT-09.**

## Performance

- **Duration:** 25 min
- **Started:** 2026-07-30T22:35:00Z
- **Completed:** 2026-07-30T23:00:41Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Added 5 `*Create` Pydantic v2 request schemas to `backend/schemas.py` (`TransferCreate`, `InvestmentTransferCreate`, `FundedBuyCreate`, `FundedSellCreate`, `BalanceAdjustmentCreate`), every money field using `MoneyDecimal`, `Field(..., gt=0)` on every positive magnitude (transfer amount, funded cash_amount/quantity/price) — `BalanceAdjustmentCreate.target_balance` deliberately has no `gt=0` since a target balance may legitimately be zero or negative
- Added 5 REST route handlers to `backend/main.py`, each `dependencies=[Depends(require_api_key)]`, `status_code=201`, following the `create_account`/`create_transfer` idiom exactly: build after-dict(s) -> `apply_*(db, ...)` in `try/except ValueError as e: raise HTTPException(422, ...)` -> `db.commit()` -> `db.refresh(...)` -> `reset_engine()` -> return ids
- All 5 handlers route exclusively through the matching Phase-13 `apply_*` primitive — no raw SQL/ORM inserts, no double-commit (verified: zero `text(`/`db.add(Transaction`/`db.add(PortfolioEvent` occurrences in the 5 new handler bodies)
- Discovered and fixed a real bug (Rule 1) in the funded-buy/sell handlers: passing `MoneyDecimal` (a `Decimal`) straight into `apply_add_funded_buy`/`apply_add_funded_sell` raised `TypeError: Object of type Decimal is not JSON serializable` on `AuditLog.after` (JSONB) — the plan's `load_bearing_constraints` claim that "no float coercion needed here" was incorrect for this specific pair of primitives; fixed by coercing `quantity`/`price`/`cash_amount` to `float()` before building the after-dict, matching 14-02's `propose_add_funded_buy`/`_sell` convention
- All 8 tests in `test_write_endpoints.py` (5 happy-path + 3 validation/auth) GREEN; full suite 272 passed, 1 pre-existing documented failure (`test_settings.py::test_put_settings_requires_key`) — zero regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Add 5 *Create request schemas to schemas.py** - `f78ab67` (feat)
2. **Task 2: Add 5 direct REST route handlers to main.py routing through apply_*** - `74682c9` (feat)

_No TDD-style RED commit this plan — the RED tests already exist from Plan 14-01; this plan is the GREEN half._

## Files Created/Modified
- `backend/schemas.py` — +5 `*Create` request models (`TransferCreate`, `InvestmentTransferCreate`, `FundedBuyCreate`, `FundedSellCreate`, `BalanceAdjustmentCreate`), inserted after `PortfolioEventOut`
- `backend/main.py` — +5 schema imports, +5 REST route handlers: `create_transfer`/`create_investment_transfer` (after `delete_transaction`), `create_funded_buy`/`create_funded_sell` (after `create_portfolio_event`), `adjust_account_balance` (after `update_account`, before `delete_account`)

## Decisions Made
- Corrected the plan's `load_bearing_constraints` claim about funded-buy/sell float coercion (see key-decisions above) — this is a genuine bug the plan's RESEARCH/PATTERNS missed, not a scope change; fixed inline under deviation Rule 1
- Kept the `try/except ValueError` wrapper on `adjust_account_balance` for consistency with every other write route even though `apply_add_balance_adjustment` doesn't currently raise for a nonexistent `account_id` — matches the project-wide `ValueError -> HTTPException(422)` convention and costs nothing if never triggered
- Followed RESEARCH.md/PATTERNS.md's `str(-abs(payload.amount))` convention verbatim for transfer/investment-transfer (verified correct by test — no Decimal ever touches an inner `AuditLog.after` dict on that path, unlike funded-buy/sell)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Funded-buy/sell REST bodies broke AuditLog JSON serialization**
- **Found during:** Task 2 (running `test_write_endpoints.py` after writing the funded-buy/sell handlers)
- **Issue:** The plan's `load_bearing_constraints` stated "REST path passes MoneyDecimal straight through to apply_* after-dicts — abs(Decimal) and Decimal(str(Decimal)) both work, no JSONB round-trip so no float coercion needed here." This is true for `apply_add_transfer`/`apply_add_investment_transfer` but false for `apply_add_funded_buy`/`apply_add_funded_sell`: these primitives build an inner after-dict (containing the raw `cash_amount`/`quantity`/`price` value passed by the caller) that flows straight into `apply_add_transaction`'s/`apply_add_portfolio_event`'s own `AuditLog(after=after)` write — a JSONB column. A raw `Decimal` there raises `TypeError: Object of type Decimal is not JSON serializable` at `db.flush()`/`db.commit()` time — a 500, not a 422.
- **Fix:** Coerced `quantity`, `price`, `cash_amount` to `float()` before building the after-dict passed to `apply_add_funded_buy`/`apply_add_funded_sell`, matching the JSON-safety convention 14-02 already established for `propose_add_funded_buy`/`_sell`'s proposal-payload path. `float()` still supports the primitive's own `abs()`/negation and is JSON-serializable.
- **Files modified:** `backend/main.py` (`create_funded_buy`, `create_funded_sell`)
- **Verification:** `test_post_funded_buy`/`test_post_funded_sell` now pass; full suite green
- **Committed in:** `74682c9` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Necessary correctness fix — the plan's constraint text was simply wrong for this one code path. No scope creep; the fix is 6 lines (3 `float()` wraps x2 handlers) plus corrected comments.

## Issues Encountered
None beyond the auto-fixed bug above.

## User Setup Required

None - no external service configuration required. Tests ran against the existing live Postgres dev DB (`docker compose`, already running).

## Next Phase Readiness
- CHAT-09 is now fully satisfied across both paths: agent/chat (14-02, propose->confirm) and direct REST (14-03, immediate write behind `require_api_key`) — both route through the same 5 Phase-13 `apply_*` primitives, and write tools remain off the external MCP surface (verified: `test_mcp.py` unaffected, full suite green)
- Phase 14 is complete: all 3 plans (RED scaffold, agent wiring, REST wiring) executed; only the pre-existing, documented `test_settings.py::test_put_settings_requires_key` failure remains in the suite
- Live verification recommended per the plan's `<verification>` section before considering this "done" end-to-end: `docker compose up -d --build` then `curl -X POST .../transactions/transfer` with the api key, confirm 201 and both legs paired (per `deploy-requires-rebuild` project memory — committed code is not yet deployed)
- No blockers.

---
*Phase: 14-rest-endpoints-agent-mcp-tool-registration*
*Completed: 2026-07-30*

## Self-Check: PASSED

- FOUND: backend/schemas.py
- FOUND: backend/main.py
- FOUND: commit f78ab67
- FOUND: commit 74682c9
