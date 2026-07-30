---
phase: 13-shared-mutation-layer-transfer-buy-sell-with-funding-adjustm
plan: 04
subsystem: backend
tags: [writes.py, sqlalchemy, postgres, investment-transfer, funded-trade, dual-currency]

# Dependency graph
requires:
  - phase: 12-typed-accounts-transfer-funding-schema-foundations
    provides: portfolio_events.source_account_id column (nullable Integer, no FK)
  - phase: 13-shared-mutation-layer-transfer-buy-sell-with-funding-adjustm
    plan: 01
    provides: RED tests pinning apply_add_investment_transfer(db, cash_leg_after, event_after) and apply_add_funded_buy(db, after) -> dict
  - phase: 13-shared-mutation-layer-transfer-buy-sell-with-funding-adjustm
    plan: 03
    provides: apply_add_transfer/apply_add_transaction/apply_add_portfolio_event primitives this plan composes
provides:
  - "apply_add_investment_transfer(db, cash_leg_after, event_after) -> (tx, ev): liquid->investment funding link via PortfolioEvent.source_account_id (XFER-02)"
  - "apply_add_funded_buy(db, after) -> {'transaction':, 'portfolio_event':}: funded buy, one commit boundary (XFER-03/XFER-04)"
  - "apply_add_funded_sell(db, after) -> {'transaction':, 'portfolio_event':}: funded sell, near-mirror of funded_buy (XFER-03/XFER-04, not RED-pinned but implemented per plan action for symmetry)"
affects: [phase-14-confirm-endpoint, phase-17-records-tab]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Composition-then-mutate-in-place: call apply_add_transaction + apply_add_portfolio_event, then set ev.source_account_id = tx.account_id directly on the returned ORM object (both already flushed by their own primitive, no extra flush needed)"
    - "Raw (non-Decimal) amount passed into the composed after-dict — Decimal(str(x)) conversion happens exactly once, inside apply_add_transaction/apply_add_portfolio_event, so the AuditLog's JSON-serialized `after` snapshot never contains a Decimal"

key-files:
  created: []
  modified:
    - backend/writes.py

key-decisions:
  - "apply_add_funded_buy/_sell negate/abs the raw after['cash_amount'] (not a Decimal-wrapped value) before handing it to apply_add_transaction — wrapping in Decimal() before that point broke AuditLog's json.dumps() (Decimal is not JSON serializable); Decimal conversion is the primitive's job (D-09 idiom), the composer only fixes the sign"
  - "apply_add_funded_sell implemented alongside apply_add_funded_buy (plan's <action> names both explicitly, 'near-mirror') even though only funded_buy has a RED test — kept symmetric so phase 14's confirm endpoint has both sides of a funded trade ready"

requirements-completed: [XFER-02, XFER-03, XFER-04]

coverage:
  - id: D1
    description: "A liquid->investment transfer writes one is_transfer=true Transaction on the liquid source linked to a new deposit PortfolioEvent via source_account_id; no synthetic accounts row"
    requirement: "XFER-02"
    verification:
      - kind: unit
        ref: "backend/tests/test_write_tools.py::test_apply_add_investment_transfer"
        status: pass
    human_judgment: false
  - id: D2
    description: "A funded buy writes the cash-leg Transaction and the buy PortfolioEvent + holding recompute together under one caller commit, with .id populated on both entities before that commit"
    requirement: "XFER-03"
    verification:
      - kind: unit
        ref: "backend/tests/test_write_tools.py::test_apply_add_funded_buy_one_commit_boundary"
        status: pass
    human_judgment: false
  - id: D3
    description: "Funded-buy cash-leg Transaction.currency and PortfolioEvent.currency are stored independently (dual-currency, no forced conversion, no new columns)"
    requirement: "XFER-04"
    verification:
      - kind: unit
        ref: "backend/tests/test_write_tools.py::test_funded_buy_dual_currency_legs"
        status: pass
    human_judgment: false

# Metrics
duration: 25min
completed: 2026-07-30
status: complete
---

# Phase 13 Plan 04: Investment Transfer + Funded Buy/Sell Summary

**Added `apply_add_investment_transfer`, `apply_add_funded_buy`, and `apply_add_funded_sell` to `backend/writes.py` by composing the existing `apply_add_transaction` + `apply_add_portfolio_event` primitives — investment money is always a `PortfolioEvent` linked via `source_account_id`, never a synthetic `accounts` row, and every funded trade lands under one caller commit with no live FX call.**

## Performance

- **Duration:** 25 min
- **Tasks:** 2 completed
- **Files modified:** 1

## Accomplishments
- `apply_add_investment_transfer(db, cash_leg_after, event_after)`: debits the liquid source account (`is_transfer=True`) and links the new `deposit` `PortfolioEvent` back via `PortfolioEvent.source_account_id = tx.account_id` — no `accounts` row created for the investment side (D-05), confirmed by the RED test's `accounts_before == accounts_after` assertion.
- `apply_add_funded_buy(db, after) -> dict`: one `after` dict drives both the cash leg (debit, `category="Investment"`, `is_transfer=True`) and the `buy` `PortfolioEvent`; `apply_add_portfolio_event` already triggers `recompute_holding_from_events`, so the holding update is "free" — no hand-rolled position math anywhere in the new code.
- `apply_add_funded_sell(db, after) -> dict`: near-mirror of funded_buy (credits instead of debits, `sell` event type) — implemented per the plan's explicit `<action>` text even though only the buy path has a plan-01 RED test.
- Cross-currency (XFER-04/D-09): the cash-leg `Transaction.currency` and the `PortfolioEvent.currency` come from two independent `after` keys (`cash_currency` / `event_currency`) with zero forced conversion and zero new schema columns.
- No write path calls `fx.get_rate` or any live rate — `grep -nE "get_rate|fx\." backend/writes.py` returns no match; `recompute_holding_from_events` (in `portfolio.py`, not `writes.py`) resolves its own historical, date-keyed rate when it needs an IDR valuation, which is a read-time concern outside this plan's file.

## Task Commits

Each task was committed atomically:

1. **Task 1: apply_add_investment_transfer** — `f94959b` (feat)
2. **Task 2: apply_add_funded_buy + apply_add_funded_sell** — `00f5077` (feat)

## Files Created/Modified
- `backend/writes.py` — +99 lines (3 new `apply_*` functions)

## Decisions Made
- See `key-decisions` in frontmatter. The one non-obvious fix: the plan-01 test's `after["cash_amount"]` is a plain `int` (e.g. `1000000`); negating/abs-ing it as a raw number (not wrapping in `Decimal()` first) before handing it into the inner `after` dict for `apply_add_transaction` keeps `AuditLog.after`'s `json.dumps()` serializable — `Decimal` objects raise `TypeError: Object of type Decimal is not JSON serializable` when passed straight through to the audit-log dict. `apply_add_transaction` itself still does the `Decimal(str(x))` conversion for the actual `Transaction.amount` column (D-09's LOAD-BEARING idiom, untouched).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Decimal leaking into AuditLog JSON serialization**
- **Found during:** Task 2, first `pytest` run of `test_apply_add_funded_buy_one_commit_boundary`
- **Issue:** Initial implementation computed `cash_amount = -abs(Decimal(str(after["cash_amount"])))` before passing it into the inner `after` dict handed to `apply_add_transaction`. That inner dict becomes `AuditLog.after`, which psycopg serializes via `json.dumps()` — a `Decimal` there raises `TypeError: Object of type Decimal is not JSON serializable`.
- **Fix:** Compute the sign-adjusted amount as a raw number (`-abs(after["cash_amount"])` / `abs(after["cash_amount"])`), letting `apply_add_transaction`'s own `Decimal(str(x))` do the one-and-only Decimal conversion for the `Transaction.amount` column.
- **Files modified:** `backend/writes.py` (both `apply_add_funded_buy` and `apply_add_funded_sell`)
- **Commit:** `00f5077` (fixed before commit — never landed broken)

None else — plan executed as written.

## Issues Encountered

None blocking. The one bug above was caught and fixed within the same task before any commit.

## User Setup Required

None — no external service configuration required.

## Verification

- `pytest backend/tests/test_write_tools.py::test_apply_add_investment_transfer -x` → 1 passed
- `pytest backend/tests/test_write_tools.py::test_apply_add_funded_buy_one_commit_boundary backend/tests/test_write_tools.py::test_funded_buy_dual_currency_legs -x` → 2 passed
- `pytest backend/tests/test_write_tools.py backend/tests/test_portfolio.py -k "not balance_adjustment"` → 53 passed, 1 deselected (the deselected `test_apply_add_balance_adjustment_delta` is plan 13-05's scope, still RED as expected)
- `grep -vE '^\s*#' backend/writes.py | grep -c 'db.commit'` → `0`
- `grep -nE "get_rate|fx\." backend/writes.py` → no match
- `grep -n "recompute_holding_from_events" backend/writes.py` → only the import + doc-comment references + the one call site inside `apply_add_portfolio_event` (L428) — no hand-rolled Holding update in the new functions
- No literal integer account id anywhere in the three new functions (grep-checked)
- Live-DB leak check post-run: `accounts`/`platforms` named `zz13test-%` and `portfolio_events` ticker `ZZ13%` all `0` rows — no leaked test data

## Next Phase Readiness

Plan 13-05 (`apply_add_balance_adjustment`, ACCT-02) is the last plan-01 RED target remaining in this phase; its test is untouched and still RED. Phase 14 (confirm endpoint) can now call `apply_add_investment_transfer`, `apply_add_funded_buy`, and `apply_add_funded_sell` directly — all three compose cleanly under a single caller-owned commit with no internal `db.commit()`.

---
*Phase: 13-shared-mutation-layer-transfer-buy-sell-with-funding-adjustm*
*Completed: 2026-07-30*

## Self-Check: PASSED

- FOUND: backend/writes.py
- FOUND: .planning/phases/13-shared-mutation-layer-transfer-buy-sell-with-funding-adjustm/13-04-SUMMARY.md
- FOUND commit: f94959b
- FOUND commit: 00f5077
