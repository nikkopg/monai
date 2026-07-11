---
phase: 05-investment-subsystem
plan: 06
subsystem: infra
tags: [apscheduler, scheduler, fastapi-lifespan, portfolio, cron, background-job]

# Dependency graph
requires:
  - phase: 05-01
    provides: PortfolioValueHistory model + unique ix_portfolio_value_history_date_ticker index
  - phase: 05-03
    provides: portfolio.py recompute + portfolio_summary + _latest_price
  - phase: 05-04
    provides: prices.refresh_all_prices(db, force=True) with per-ticker try/except
provides:
  - In-process AsyncIOScheduler started in the FastAPI lifespan (D-14)
  - Daily job that refreshes prices then writes one portfolio_value_history row per holding (D-13)
  - snapshot_all_holdings — partial-failure tolerant, idempotent per day
affects: [v2 portfolio time-series chart (INVX-01/D-06), any future background-job work]

# Tech tracking
tech-stack:
  added: [apscheduler 3.11.3]
  patterns:
    - "FastAPI lifespan (@asynccontextmanager) owns background component start/stop — no @app.on_event"
    - "Sync APScheduler job reuses get_session_sync() thread-pool path — no second session path"
    - "Per-holding try/except inside the snapshot loop for partial-failure tolerance"

key-files:
  created:
    - backend/scheduler.py
  modified:
    - backend/portfolio.py
    - backend/main.py
    - backend/tests/test_scheduler.py

key-decisions:
  - "Snapshot job runs at 01:00 Asia/Jakarta (low-traffic window; D-14 left time to discretion)"
  - "refresh_all_prices called with force=True so the daily snapshot captures the freshest values"
  - "Dedup via query-then-skip on (snapshot_date, ticker) — idempotent re-runs without relying on an IntegrityError round-trip"
  - "Holdings without a current price row are skipped (market_value unknown; D-13 tolerates gaps, no backfill)"

patterns-established:
  - "build_scheduler() returns an un-started scheduler; the lifespan owns start()/shutdown(wait=False)"
  - "Single-uvicorn deploy assumption documented inline; multi-worker would need leader election"
---

# Phase 05 Plan 06: Daily Portfolio-Value History Collector Summary

In-process APScheduler daily job (started in a new FastAPI lifespan) refreshes all prices then writes one `portfolio_value_history` row per holding — the stack's first always-on background component, tolerant of per-ticker failure and idempotent per day.

## What Was Built

- **`backend/portfolio.py::snapshot_all_holdings(db)`** — for each holding: skip if a same-day `(snapshot_date, ticker)` row already exists (honors the Plan 01 unique index → idempotent), else read the current price from `price_cache` and write a row with `market_value = price × quantity`, `cost_basis = avg_cost × quantity` (all Decimal), `currency='IDR'`. Holdings with no price row are skipped. Per-holding `try/except` so one ticker's failure never aborts the loop (T-05-06-DEG). Does not commit — caller owns the transaction. Returns `{written, skipped, failed}`.
- **`backend/scheduler.py`** — `build_scheduler() -> AsyncIOScheduler` (timezone `Asia/Jakarta`) registering `daily_portfolio_snapshot_job` via `CronTrigger(hour=1, minute=0)` with `misfire_grace_time=3600`, `coalesce=True`, `max_instances=1`, `replace_existing=True` (T-05-06-DOS / RESEARCH Pattern 3 + Pitfall 3). The sync job opens `get_session_sync()` (no second session path), calls `refresh_all_prices(db, force=True)` then `snapshot_all_holdings(db)`, then commits.
- **`backend/main.py`** — new `@asynccontextmanager async def lifespan(app)` builds the scheduler, `start()` before yield, `shutdown(wait=False)` after; `app = FastAPI(title="monai", version="0.1.0", lifespan=lifespan)`. No `@app.on_event`. Inline comment flags the single-uvicorn assumption (multi-worker would need leader election). Existing routes unchanged.
- **`backend/tests/test_scheduler.py`** — filled the last Wave-0 red target plus coverage: `test_snapshot_writes_one_row_per_holding`, `test_snapshot_job_partial_failure_tolerant`, `test_snapshot_no_duplicate_same_day`, `test_build_scheduler_registers_daily_job`.

## TDD Flow

RED: 4 tests failed (`ModuleNotFoundError: backend.scheduler` / missing `snapshot_all_holdings`) against a live Postgres — real failures, not skips. GREEN: after implementing both files, 4/4 pass.

## Verification Results

- `pytest backend/tests/test_scheduler.py -x -q` → **4 passed** (partial-failure tolerance + no-duplicate-day + market_value/cost_basis + job hardening).
- `from backend.main import app; app.router.lifespan_context is not None` → **lifespan wired**.
- Full backend suite `pytest backend/tests/ -q` (rerun with `MONAI_API_KEY` set to match the container's configured key) → **136 passed, 0 failed**. The earlier 135/1 split was `test_settings.py::test_put_settings_requires_key` failing only because the local shell had no `MONAI_API_KEY` set (server fails closed with 503 when no key is configured — by design); confirmed unrelated to this plan.
- **Task 2 `<human-check>` — COMPLETED:** rebuilt `monai-backend` (`docker compose up -d --build backend`); boot log shows `apscheduler.scheduler: Added job "daily_portfolio_snapshot_job"` → `Scheduler started` → `Application startup complete`. `docker restart monai-backend` shows a clean `Scheduler has been shut down` on shutdown, no unhandled exception. Manually invoked `daily_portfolio_snapshot_job()` inside the running container — completed without error; `SELECT ... FROM portfolio_value_history` confirmed new rows were written with correct `market_value`/`cost_basis`.

## Deviations from Plan

None affecting behavior. The plan's Task 1 `<verify>` listed only the partial-failure test; two extra tests (row-per-holding correctness + no-duplicate-day) were added to cover the `<behavior>` clauses that had no explicit test line — in-scope test hardening, not a plan change.

## Self-Check: PASSED

- FOUND: backend/scheduler.py
- FOUND: backend/portfolio.py (snapshot_all_holdings)
- FOUND: backend/main.py (lifespan)
- FOUND commit 200f7c1 (Task 1), 30bd6e5 (Task 2)
- CONFIRMED live: scheduler start/stop in container logs, manual job run wrote portfolio_value_history rows
