---
phase: 07-investment-subsystem-v2-multi-platform-multi-currency-cash-g
plan: 02
subsystem: investments-valuation
tags: [fx, currency, cash, gold, average-cost, decimal, portfolio]

# Dependency graph
requires:
  - phase: 07-01
    provides: backend/fx.py::get_rate, backend/models.py::FxRateCache, backend/models.py::PortfolioEvent.currency
provides:
  - FX-aware recompute_holding_from_events (native cost -> IDR at trade-date rate, FX-03/FX-04)
  - portfolio_summary cash special-case (aggregate + per-row, CG-01/INV-05)
  - snapshot_all_holdings cash special-case (writes history rows for cash, CG-01)
  - gold pass-through via the existing ledger (CG-02/CG-03)
  - event-currency-vs-holding-currency validation at write time (T-07-02-CUR)
  - asset_type_groups on portfolio_summary (VZ-01 pie data contract)
affects: [07-03, 07-04, 07-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "FX conversion injected at the two total_cost mutation sites in recompute_holding_from_events, not a restructure — preserves the D-02 avg_cost invariant exactly"
    - "Cash special-cased BEFORE the price_cache read in both portfolio_summary and snapshot_all_holdings — two symmetric branches, same CG-01 semantics"
    - "None-propagation for FX failures mirrors unrealized_pnl's existing None contract — never rate=1.0"

key-files:
  created: []
  modified:
    - backend/portfolio.py
    - backend/writes.py
    - backend/schemas.py
    - backend/tests/test_portfolio.py
    - backend/tests/test_write_tools.py

key-decisions:
  - "A brand-new position's currency is seeded from its FIRST event's own currency (if stamped), not hardcoded to IDR — otherwise a USD-only position's opening buy would silently mis-resolve to IDR and every later same-currency buy would then fail the mismatch check"
  - "recompute_holding_from_events returns quantity=None/avg_cost=None/realized_pnl=None/dividend_total=None (not a partial result) when any event's FX rate is unresolvable — the position's state is genuinely unknown until the rate resolves, not partially computed"
  - "Cash's per-row current_price is populated with the FX rate itself (price of 1 unit of cash in IDR), not left null, so its unrealized_pnl calculation degrades gracefully through the same unrealized_pnl(current_price, avg_cost, qty) function every other asset type uses"

requirements-completed: [INV-01, INV-06, INV-07]

# Metrics
duration: ~35min
completed: 2026-07-12
---

# Phase 7 Plan 2: FX-Aware Valuation + Cash/Gold First-Class Positions Summary

**Currency-aware average-cost P&L (trade-date cost basis, today's-rate current value) plus cash and gold as first-class positions that skip and ride the price_cache path respectively, with one-currency-per-position enforced at write time.**

## Performance

- **Duration:** ~35 min
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

- `recompute_holding_from_events` converts every buy/sell/dividend's native `price × quantity` to IDR via `fx.get_rate(ev.currency, "IDR", ev.date, db)` at the event's own trade date before it touches `total_cost` — cost basis is historical-at-purchase, `portfolio_summary`'s current value uses today's rate, so unrealized P&L now includes FX drift (FX-03/FX-04). The D-02 sell invariant (avg_cost unchanged by a sell) is preserved exactly — only a multiply was injected at the two existing mutation sites, no restructuring.
- `portfolio_summary` special-cases `asset_type == "cash"` **before** the `_latest_price` read, for both the aggregate total and the per-holding dict: value = `quantity × fx.get_rate(currency, "IDR", today, db)`, `is_stale=False`, `price_source="fx"` — no price_cache row involved, and no false "stale" badge (CG-01/INV-05).
- `snapshot_all_holdings` gets the identical cash special-case before its `price_row is None -> skip` gate, so a cash holding writes a `portfolio_value_history` row today instead of being skipped forever (which would have permanently excluded cash from Plan 04's VZ-02 line chart).
- Gold takes no special-case branch at all — it flows through the same average-cost ledger and price_cache path as crypto/stocks (CG-02), with its per-gram manual price landing as a normal `price_cache source='manual'` row (CG-03).
- `apply_add_portfolio_event` validates a new event's currency against its parent holding's currency; a mismatch raises `ValueError` → 422 at the API boundary (one currency per position, no cross-currency averaging, T-07-02-CUR). `PortfolioEventCreate` gained an optional `currency` field so callers can actually supply one.
- `portfolio_summary` now returns `asset_type_groups: [{asset_type, total_value}]` alongside the existing platform grouping — the VZ-01 pie's data contract. `PortfolioSummary` schema carries the new field.
- A failed FX lookup (adapter/vendor outage, cache miss) makes `recompute_holding_from_events` return `quantity=None`/`avg_cost=None`/`realized_pnl=None`/`dividend_total=None` — never a fabricated `rate=1.0`.

## Task Commits

1. **Task 1: FX-aware average-cost + cash special-case + asset-type grouping (portfolio.py)** - `839c772` (feat)
2. **Task 2: Event-currency validation + cash/gold write pass-through (writes.py)** - `93be103` (feat)

_TDD tasks: RED/GREEN folded into a single commit per task per the plan's `tdd="true"` frontmatter — tests and implementation were developed together and verified green before each commit, no separate red-target scaffolding existed to preserve._

## Files Created/Modified

- `backend/portfolio.py` - FX conversion in `recompute_holding_from_events`; cash special-case in `portfolio_summary` (aggregate + per-row) and `snapshot_all_holdings`; `asset_type_groups` aggregation
- `backend/writes.py` - currency validation + default-currency resolution in `apply_add_portfolio_event`
- `backend/schemas.py` - `PortfolioEventCreate.currency` field; `PortfolioSummary.asset_type_groups` field
- `backend/tests/test_portfolio.py` - 8 new tests: FX conversion exactness, D-02 invariant under FX, None-propagation, cash valuation (no price_cache row), cash snapshot (writes not skipped), gold full-ledger parity, asset-type grouping
- `backend/tests/test_write_tools.py` - 4 new tests: matching-currency success, currency-mismatch ValueError, currency-mismatch 422 at the API boundary, cash/gold `apply_add_holding` pass-through with audit-trail verification

## Decisions Made

- A brand-new position's currency is seeded from its first event's own currency when present, not hardcoded to `"IDR"` — see key-decisions above; this was necessary for the currency-validation tests to pass (a USD-denominated position's first buy must not silently become an "IDR position" that then rejects its own second USD buy as a mismatch).
- `recompute_holding_from_events` returns a fully-None result (not a partially-computed one) on any FX failure within the ledger scan — simpler contract for callers, matches the "never fabricate" principle applied consistently rather than partially.
- Cash's `current_price` field is populated with the raw FX rate (not left null) so it reuses the existing `unrealized_pnl` calculator unchanged rather than needing a cash-specific P&L formula.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] New USD-denominated position defaulted to IDR currency, breaking its own second same-currency buy**
- **Found during:** Task 2 (writing the currency-mismatch validation tests)
- **Issue:** `recompute_holding_from_events`'s original fallback (`holding.currency if holding else "IDR"`) meant a brand-new position's very first buy — which carries its own `ev.currency` (e.g. `"USD"`) — still created the `Holding` row with `currency="IDR"`, because at that point no holding existed yet to inherit from. A second buy in the same USD currency then failed the new mismatch check against the wrongly-seeded `"IDR"` holding.
- **Fix:** For a brand-new position, `default_currency` now falls back to the first event's own `currency` (if stamped) before falling back to `"IDR"`.
- **Files modified:** `backend/portfolio.py`
- **Verification:** `test_apply_add_portfolio_event_matching_currency_succeeds` (two same-currency buys on a new position) passes; full `test_portfolio.py` + `test_write_tools.py` suites green (46 tests)
- **Committed in:** `93be103` (Task 2 commit — discovered and fixed while testing Task 2's currency validation, landed alongside it since it's the same currency-resolution code path)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Necessary correctness fix for the currency-validation feature to work as specified; no scope creep.

## Issues Encountered

None beyond the deviation above.

## User Setup Required

None — no external service configuration required (frankfurter.dev, already wired in Plan 01, needs no key).

## Next Phase Readiness

- `portfolio.py`'s FX-aware valuation and cash/gold special-cases are in place for Plan 03 (multi-platform/API surface work depending on this) and Plan 04 (VZ-02 history chart, which now receives cash rows via `snapshot_all_holdings`).
- `asset_type_groups` is available on `GET /investments/summary` for the frontend pie chart (VZ-01) whenever that UI plan lands.
- One pre-existing, unrelated test failure (`tests/test_settings.py::test_put_settings_requires_key`, asserts 503) exists on `main` independent of this plan's changes — confirmed via untouched-file check before and after this plan's commits. Not introduced by this work; flagged for awareness, not fixed here (out of scope per the deviation-rules scope boundary).

---
*Phase: 07-investment-subsystem-v2-multi-platform-multi-currency-cash-g*
*Completed: 2026-07-12*

## Self-Check: PASSED

- FOUND: backend/portfolio.py
- FOUND: backend/writes.py
- FOUND: backend/schemas.py
- FOUND: backend/tests/test_portfolio.py
- FOUND: backend/tests/test_write_tools.py
- FOUND: .planning/phases/07-investment-subsystem-v2-multi-platform-multi-currency-cash-g/07-02-SUMMARY.md
- FOUND commit: 839c772 (Task 1)
- FOUND commit: 93be103 (Task 2)
- FOUND commit: e3b709e (docs: summary)
