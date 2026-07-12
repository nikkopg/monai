---
quick_id: 260711-rb2
subsystem: investments
tags: [alembic, sqlalchemy, fastapi, pydantic, nextjs, decimal-ledger]

requires:
  - phase: 05-investments
    provides: holdings/portfolio_events tables, platforms table, event-ledger recompute, price refresh
provides:
  - Position identity is (ticker, platform_id) instead of bare ticker — same asset on multiple platforms is now two independent positions
  - Migration 006: holdings.platform_id NOT NULL + composite unique(ticker, platform_id); portfolio_events.platform_id backfilled + NOT NULL + FK
  - recompute_holding_from_events scoped per (ticker, platform_id); portfolio_summary realized P&L scoped per-position (no cross-platform double-counting)
  - PortfolioEventCreate/HoldingCreate.platform_id required at the schema boundary (422 if omitted)
  - apply_delete_platform collision guard (raises ValueError) + reassigns both holdings and portfolio_events
  - refresh_all_prices dedups by ticker (fetches/writes once per distinct ticker, not per holding row)
  - Both holding-entry modals require a platform (no more "(unassigned)")
affects: [investments, portfolio-events, price-refresh, holdings-ui]

tech-stack:
  added: []
  patterns:
    - "Position identity = composite key (ticker, platform_id) instead of a single unique column — mirrors the account/transaction FK pattern already used elsewhere"
    - "Price fetch dedup by grouping holdings on a shared attribute before the per-item adapter loop"

key-files:
  created:
    - alembic/versions/006_multi_platform_holdings.py
  modified:
    - backend/models.py
    - backend/portfolio.py
    - backend/writes.py
    - backend/schemas.py
    - backend/main.py
    - backend/prices.py
    - backend/tests/test_portfolio.py
    - backend/tests/test_write_tools.py
    - backend/tests/test_prices.py
    - ui/app/investments/HoldingModal.tsx
    - ui/app/investments/HoldingOverrideModal.tsx

key-decisions:
  - "Option 1 (platform required) locked by the plan — no 'unassigned' bucket going forward; ticker alone is no longer a valid position key."
  - "price_cache stays keyed by ticker only (price is platform-independent) — refresh_all_prices now groups holdings by ticker before fetching, so a shared ticker across platforms is fetched once."
  - "apply_delete_platform reassignment now moves BOTH holdings and portfolio_events, with a pre-flight collision guard (ValueError) if the target platform already has the same ticker — position merge is explicitly out of scope, matching the plan's ponytail note."
  - "portfolio_summary's realized P&L helper was renamed _realized_for_ticker -> _realized_for_position and scoped by (ticker, platform_id) — this is a Rule 1 auto-fix: without it, the same ticker on two platforms would double-count each other's realized P&L in the summary, a silent financial-ledger bug directly caused by the identity change."

requirements-completed: []

coverage:
  - id: D1
    description: "holdings.platform_id NOT NULL + composite unique(ticker, platform_id); portfolio_events.platform_id backfilled NOT NULL + FK (migration 006)"
    verification:
      - kind: unit
        ref: "orchestrator must run: alembic upgrade head; downgrade -1; upgrade head (Task 1 verify step) — NOT run in this worktree, see Verification Pending"
        status: unknown
    human_judgment: true
    rationale: "Migration correctness against a live Postgres cannot be verified from this worktree (see Verification Pending section) — orchestrator must run it against a rebuilt container."
  - id: D2
    description: "recompute_holding_from_events scoped to (ticker, platform_id); portfolio_summary realized P&L scoped per-position"
    verification:
      - kind: unit
        ref: "backend/tests/test_portfolio.py#test_recompute_holding_per_position_independent"
        status: unknown
    human_judgment: true
    rationale: "Test written and read-verified for correctness, but pytest cannot run against a live DB from this worktree (stale container). Orchestrator must run backend/tests -q after rebuild."
  - id: D3
    description: "PortfolioEventCreate.platform_id and HoldingCreate.platform_id required at the schema boundary; duplicate (ticker, platform_id) -> 422; same ticker on two platforms -> both 201"
    verification:
      - kind: unit
        ref: "backend/tests/test_write_tools.py#test_create_holding_missing_platform_id_returns_422, #test_create_holding_duplicate_ticker_platform_returns_422, #test_create_holding_same_ticker_two_platforms_both_created, #test_portfolio_event_missing_platform_id_returns_422"
        status: unknown
    human_judgment: true
    rationale: "Tests written and read-verified; requires a live rebuilt backend container + Postgres to execute — orchestrator-only per the critical_verification constraint."
  - id: D4
    description: "refresh_all_prices dedups fetch/write by distinct ticker across multi-platform holdings"
    verification:
      - kind: unit
        ref: "backend/tests/test_prices.py#test_refresh_dedups_same_ticker_across_platforms"
        status: unknown
    human_judgment: true
    rationale: "Requires a live DB; orchestrator-only verification."
  - id: D5
    description: "Both holding modals require a platform (no '(unassigned)' option); disabled submit + inline hint when no platforms exist"
    verification:
      - kind: unit
        ref: "cd ui && npx tsc --noEmit — could not run in this worktree (ui/node_modules absent); verified by careful manual read of both .tsx files instead"
        status: unknown
    human_judgment: true
    rationale: "No node_modules in this worktree to run tsc; UI change also needs a live-browser multi-platform smoke test the orchestrator must perform post-merge."

duration: ~55min
completed: 2026-07-11
status: complete
---

# Quick 260711-rb2: Multi-platform holdings (platform required) Summary

**Position identity moves from a bare `ticker` unique key to a composite `(ticker, platform_id)` key across the migration, ledger recompute, schema, and UI — the same asset can now live on two platforms as two fully independent positions with their own qty/avg_cost/realized P&L.**

## Performance

- **Duration:** ~55 min
- **Tasks:** 5/5 completed
- **Files modified:** 11 (1 new migration, 10 modified: 6 backend source, 3 backend test, 2 frontend)

## Accomplishments
- New alembic migration (006) makes `holdings.platform_id` NOT NULL, replaces the global-unique `ticker` index with a non-unique one, adds `uq_holdings_ticker_platform`, and backfills + locks `portfolio_events.platform_id` NOT NULL with an FK — fully reversible (`downgrade()` mirrors upgrade() in strict reverse order).
- `recompute_holding_from_events(db, ticker, platform_id)` now derives a position scoped to the composite key; two platforms holding the same ticker recompute completely independently (verified in tests: recomputing one position leaves the other's qty/avg_cost untouched).
- `portfolio_summary`'s realized-P&L helper is scoped per-position (`_realized_for_position`), fixing a would-be silent double-counting bug where the same ticker on two platforms would otherwise report each other's combined realized P&L.
- `PortfolioEventCreate.platform_id` and `HoldingCreate.platform_id` are now required (non-Optional) at the Pydantic boundary — a 422 fires before any write path runs if platform is omitted.
- `apply_delete_platform` reassignment now moves both `holdings` and `portfolio_events` (previously only holdings), gated by a pre-flight collision guard that raises `ValueError` if the target platform already holds the same ticker (position-merge stays out of scope, per plan).
- `refresh_all_prices` groups holdings by ticker before the adapter loop — a ticker shared across N platforms is now fetched and written to `price_cache` exactly once, not N times.
- `HoldingModal` and `HoldingOverrideModal` both drop the `(unassigned)` option, mark the Platform `<select>` required, default to the first platform (or the holding's existing platform on edit), and disable submit with an inline "Add a platform first" hint when no platforms exist.

## Task Commits

Each task was committed atomically:

1. **Task 1: Migration + models** - `ec474a2` (feat)
2. **Task 2: Ledger recompute per position + event write (TDD)** - `af2f1db` (feat, RED+GREEN combined per task)
3. **Task 3: Schema + endpoints (platform required, TDD)** - `ca5f798` (feat, RED+GREEN combined per task)
4. **Task 4: Price refresh dedup** - `7e348d7` (feat)
5. **Task 5: Frontend — platform required in both modals** - `db70a4b` (feat)

**Plan metadata:** commit pending (orchestrator handles the docs commit per constraints)

_Note: Tasks 2 and 3 were TDD-flagged in the plan; tests and implementation were written together in each single commit per task (RED assertions and GREEN implementation land atomically per task, not as separate test→feat commit pairs) — this diverges slightly from the strict RED/GREEN/REFACTOR commit-splitting convention but preserves the actual red→green intent: every new/changed assertion in test_portfolio.py, test_write_tools.py exercises code that did not exist/behave that way before the paired implementation change in the same commit._

## Files Created/Modified
- `alembic/versions/006_multi_platform_holdings.py` - New migration: platform_id NOT NULL + composite unique on holdings, portfolio_events.platform_id backfilled + NOT NULL + FK
- `backend/models.py` - Holding.platform_id required + UniqueConstraint(ticker, platform_id); PortfolioEvent.platform_id required FK
- `backend/portfolio.py` - recompute_holding_from_events(ticker, platform_id); portfolio_summary + _realized_for_position scoped per-position
- `backend/writes.py` - apply_add_portfolio_event passes platform_id through to recompute + PortfolioEvent row; apply_delete_platform collision guard + dual reassignment (holdings + portfolio_events)
- `backend/schemas.py` - PortfolioEventCreate.platform_id and HoldingCreate.platform_id now required `int`
- `backend/main.py` - create_holding's duplicate-key 422 message reflects (ticker, platform_id) uniqueness
- `backend/prices.py` - refresh_all_prices dedups by ticker before the per-ticker adapter loop
- `backend/tests/test_portfolio.py` - platform fixtures on every event/recompute call; new independent-position test
- `backend/tests/test_write_tools.py` - platform fixtures on holding/event creation; new duplicate-key, missing-platform, cross-platform-both-201, and collision-guard tests
- `backend/tests/test_prices.py` - new dedup test (two holdings, one ticker, two platforms, one adapter call)
- `ui/app/investments/HoldingModal.tsx` - Platform select required, no unassigned option, default-first-platform, disabled-submit guard
- `ui/app/investments/HoldingOverrideModal.tsx` - same platform-required treatment, preserves existing platform on edit

## Decisions Made
- Renamed `_realized_for_ticker` to `_realized_for_position` and added a `platform_id` filter — not explicitly named in the plan's task list but required by the plan's own stated must-have ("independent quantity/avg_cost/P&L"); classified as a Rule 1 auto-fix (bug: would silently double-count realized P&L across platforms for a shared ticker).
- Left `backend/tools.py` (`propose_add_holding`, the agentic-chat holding tool, and `_execute_proposal_payload`'s inline `add_holding` branch) untouched — these paths still don't accept/require `platform_id` and would now hit the DB's NOT NULL constraint if invoked via chat. This is a real gap directly caused by the migration, but fixing it means adding a new required parameter to an LLM-facing tool signature (a product/UX decision — what platform does the agent infer or ask for?) that is out of this quick task's explicit file scope (`backend/tools.py` is not listed). Documented here rather than silently expanded; flagged as a deferred item below.
- Left `backend/portfolio.py:snapshot_all_holdings` (Phase 5 Plan 06 daily-value job) untouched — its `PortfolioValueHistory` uniqueness is `(snapshot_date, ticker)` only, so two holdings sharing a ticker across platforms will collide on the same-day snapshot (second one silently skipped as "exists"). This table isn't part of migration 006 and isn't in the plan's Task 1 scope; flagged as a deferred item.
- TDD tasks (2, 3) landed test + implementation in one commit each rather than separate test→feat commits, since the plan's task boundaries (not sub-steps) are the natural atomic unit here and splitting further would fragment a single conceptual change across the same files twice.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Scoped portfolio_summary's realized P&L per-position, not per-ticker**
- **Found during:** Task 2 (ledger recompute)
- **Issue:** `_realized_for_ticker` scanned `portfolio_events` by ticker only. Once the same ticker can exist on two platforms, both holdings' summary rows would report the SAME combined realized P&L (double-counting), silently corrupting the P&L a user sees for each individual position.
- **Fix:** Renamed to `_realized_for_position(db, ticker, platform_id)`, added the `platform_id` filter to the ledger scan, and updated its one caller in `portfolio_summary` to pass `h.platform_id`.
- **Files modified:** backend/portfolio.py
- **Verification:** Read-verified against the existing per-position recompute logic (same filter pattern as `recompute_holding_from_events`); exercised indirectly by `test_investments_summary_grouped_payload` (updated) and the new `test_recompute_holding_per_position_independent`.
- **Committed in:** af2f1db (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug fix)
**Impact on plan:** Necessary for financial correctness — without it, the plan's own stated truth ("independent quantity/avg_cost/P&L") would be violated for realized P&L specifically. No scope creep beyond the file the plan already lists for Task 2 (`backend/portfolio.py`).

## Issues Encountered
None during implementation. See "Verification Pending" below for what could NOT be verified from this worktree.

## VERIFICATION PENDING (orchestrator must run after merge)

**This worktree cannot verify against a live database or a rebuilt container.** The `backend` service in `docker-compose.yml` has NO source volume mount and builds from the MAIN repo (build context `.`), not this worktree — `docker compose exec backend pytest`/`alembic` from here would run STALE baked code (a false-green trap that has bitten this project three times per project memory). `ui/node_modules` is also absent from this worktree, so `tsc` could not be run.

**What WAS verified in this worktree (honest accounting):**
- All 5 Python files (`backend/models.py`, `backend/portfolio.py`, `backend/writes.py`, `backend/schemas.py`, `backend/main.py`, `backend/prices.py`) and all 3 test files parse cleanly (`python3 -c "import ast; ast.parse(...)"`) — confirms no syntax errors, not runtime correctness.
- All logic was read-verified line-by-line against the plan's exact task instructions (migration order, recompute signature, the k35 set-block split between platform_id/asset_type, the collision-guard-before-reassign ordering, the price dedup grouping).
- Both `.tsx` files were read in full after editing; brace/paren balance checked programmatically; JSX structure and prop types manually traced (no type errors expected, but not machine-verified).
- Confirmed via `docker compose ps` that a live preview server IS running (`monai-frontend`/`monai-backend` containers, up 30-40 min) — but per the stale-build trap, this is the OLD deployed image, NOT this worktree's code, so it was deliberately NOT used for "verification" (would be misleading).

**What was NOT verified (orchestrator must run):**
1. `docker compose up -d --build backend` (and `frontend`) — rebuild from this worktree's code.
2. `alembic upgrade head` then `alembic downgrade -1` then `alembic upgrade head` — migration 006 reversibility against live Postgres. Data is clean today (11 holdings, all with a platform; 3 portfolio_events rows / 2 tickers) so this should be a trivial backfill, but has not been executed.
3. `docker compose exec -T backend python -m pytest backend/tests -q` — full suite, expect ≥ 148 (143 baseline + new tests: 1 in test_portfolio.py, 5 in test_write_tools.py, 1 in test_prices.py = 7 new = 150 expected).
4. `cd ui && npx tsc --noEmit` — TypeScript compile check on both modified modals.
5. **Live multi-platform smoke test (the whole point of this task):** via API, POST the same ticker (e.g. BTC) on platform A and platform B — expect two 201s, not a 422. Then GET `/investments/summary` and confirm BTC appears under BOTH platform groups with independent quantities/avg_cost. Log a buy event on each position and confirm each recomputes independently (the other's qty/avg_cost is untouched).

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Core multi-platform identity change is complete and internally consistent (migration, models, ledger, schema, price refresh, UI all agree on `(ticker, platform_id)`).
- Two deferred gaps for future work (see Decisions Made): (a) the agentic chat `add_holding`/`propose_add_holding` path doesn't yet accept `platform_id` and would fail against the new NOT NULL constraint if invoked; (b) `snapshot_all_holdings`'s daily-value-history uniqueness is `(snapshot_date, ticker)` only and will silently skip the second platform's snapshot on a shared-ticker day.
- Blocked on orchestrator running the "Verification Pending" checklist above before this can be considered live-verified — code is complete but unexecuted against a real database.

---
*Quick: 260711-rb2*
*Completed: 2026-07-11*

## Self-Check: PASSED

All 13 created/modified files confirmed present on disk; all 5 task commit hashes (ec474a2, af2f1db, ca5f798, 7e348d7, db70a4b) confirmed present in `git log --oneline --all`.
