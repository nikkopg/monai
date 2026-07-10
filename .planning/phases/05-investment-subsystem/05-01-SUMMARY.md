---
phase: 05-investment-subsystem
plan: 01
subsystem: investment-schema-foundation
tags: [alembic, sqlalchemy, migration, dependencies, test-scaffold, wave-1]
requires: []
provides:
  - platforms table + Platform ORM model
  - portfolio_value_history table + PortfolioValueHistory ORM model
  - holdings.platform_id nullable FK
  - yfinance + apscheduler backend dependencies
  - three Wave-0 red-target pytest files (test_portfolio, test_prices, test_scheduler)
affects:
  - backend/models.py
  - backend/requirements.txt
  - alembic migration chain (head is now b2e6d4a19f73)
tech-stack:
  added:
    - yfinance>=1.5.1
    - apscheduler>=3.11.3
  patterns:
    - Nullable FK for additive schema change (existing rows stay valid)
    - Per-file db_available skip fixture (mirrors test_write_tools.py)
    - ADD-only migration (no drops/renames of existing objects)
key-files:
  created:
    - alembic/versions/004_investment_platforms.py
    - backend/tests/test_portfolio.py
    - backend/tests/test_prices.py
    - backend/tests/test_scheduler.py
  modified:
    - backend/requirements.txt
    - backend/models.py
decisions:
  - "Migration 004 chains onto 9c1a4f7d2b8e (003) with fresh revision b2e6d4a19f73"
  - "holdings.platform_id is nullable so existing/unassigned holdings survive (T-05-01-MIG)"
  - "Unique index on portfolio_value_history(snapshot_date, ticker) enforces one row per holding per day (D-13)"
  - "pycoingecko omitted — CoinGecko reached via raw httpx (already pinned)"
  - "Wave-0 test bodies use pytest.fail (real red targets), not skip"
metrics:
  duration: ~7m
  completed: 2026-07-10
  tasks: 4
  files: 6
status: complete
---

# Phase 5 Plan 01: Investment Schema Foundation Summary

Shared Phase-5 schema substrate landed: Alembic migration 004 (D-17) creating `platforms` + `portfolio_value_history` + a nullable `holdings.platform_id` FK, matching SQLAlchemy models, the `yfinance`/`apscheduler` backend deps, and three Wave-0 red-target pytest files so downstream slices (02–06) have build targets.

## What Was Built

- **backend/requirements.txt** — added `yfinance>=1.5.1` and `apscheduler>=3.11.3`; `httpx` remains pinned exactly once; `pycoingecko` deliberately not added.
- **backend/models.py** — new `Platform` (`platforms`: id, name String(128) unique/indexed, kind String(32) nullable) mirroring `Account`; new `PortfolioValueHistory` (`portfolio_value_history`: snapshot_date Date, ticker String(32) indexed, quantity Numeric(28,8), market_value/cost_basis Numeric(18,2), currency String(8) default IDR) mirroring `PriceCache` conventions; `Holding.platform_id` nullable indexed FK to `platforms.id`. Existing Holding/PortfolioEvent/PriceCache columns untouched.
- **alembic/versions/004_investment_platforms.py** — revision `b2e6d4a19f73`, down_revision `9c1a4f7d2b8e`. `upgrade()` creates `platforms`, adds `holdings.platform_id` (nullable FK), creates `portfolio_value_history` with a unique index on `(snapshot_date, ticker)`. `downgrade()` reverses in strict reverse order. ADD-only — never drops/renames existing tables.
- **backend/tests/{test_portfolio,test_prices,test_scheduler}.py** — three import-clean pytest files declaring the seven Wave-0 red targets; each body is `pytest.fail(...)` (visible RED, not skip). DB-touching stubs reuse the per-file `db_available` fixture pattern.

## Verification Results

All plan `<automated>` verifies run under the repo's uv venv (`.venv`, dependencies synced via `uv pip install -r backend/requirements.txt`):

| Task | Verify | Result |
|------|--------|--------|
| 2 | `uv pip install -r backend/requirements.txt --dry-run` lists both | PASS — Resolved 117 pkgs; `+ apscheduler==3.11.3`, `+ yfinance==1.5.1` |
| 3 | `python -c "from backend.models import Platform, PortfolioValueHistory, Holding; assert ...; print('OK')"` | PASS — `OK`; deep column-shape assertions also PASS |
| 4 | module import + `down_revision=='9c1a4f7d2b8e'` + upgrade/downgrade present | PASS — `OK`; `alembic history` shows clean linear chain, single head `b2e6d4a19f73` |
| 5 | `pytest ... --collect-only` collects the seven named tests | PASS — 7 tests collected; full run shows `7 failed` (genuine red targets) |

**Note on the alembic import verify:** running the plan's literal one-liner from the repo root fails with `ImportError: cannot import name 'op' from 'alembic'` because the repo's `alembic/` migrations directory shadows the installed `alembic` package on `sys.path[0]`. Running the identical import from any other cwd (scratch dir) yields `OK`, and the `alembic` CLI itself (which resolves its own package correctly) loads migration 004 without error. The migration is correct — the shadowing is a cwd artifact, not a code defect. This mirrors how 002/003 also `from alembic import op`.

## Task 4 Human-Check — COMPLETED (opportunistic, not deferred)

The plan marked the DB round-trip as a deferred human smoke-test "only if Postgres is readily available." Postgres **was** live on `localhost:5434` at `9c1a4f7d2b8e`, so the full round-trip was executed automatically:

- `alembic upgrade head` → created `platforms` + `portfolio_value_history`, added `holdings.platform_id`, unique index `ix_portfolio_value_history_date_ticker` present; **5710 existing transaction rows intact**.
- `alembic downgrade -1` → all new objects reversed; `platform_id` dropped; **5710 rows still intact**; DB restored to `9c1a4f7d2b8e` (its original state before this test).

No outstanding manual smoke-test remains. (A production-image smoke via `docker compose up -d --build` on the Docker DB is still the normal deploy path, since `entrypoint.sh` runs `alembic upgrade head` — but the migration logic itself is verified against a live PostgreSQL 16 dev DB.)

## Deviations from Plan

**None affecting scope.** All four executed tasks (2–5) match the plan's `files_modified` and column specs exactly. Two non-code environment notes:

1. **[Rule 3 - Blocking issue] uv venv had no pip / no backend deps.** The repo `.venv` is uv-managed (no `pip`, and initially lacked alembic/sqlalchemy for the import checks). Resolved per the environment note by syncing deps with `uv pip install -r backend/requirements.txt` into `.venv` — the idiomatic uv path. No system-Python install. This also concretely confirmed `yfinance==1.5.1` and `apscheduler==3.11.3` are installable (must-have satisfied).
2. **alembic-shadowing verify caveat** documented above — verify run from a non-repo-root cwd; no code change needed.
3. **[Rule 1 - Traceability correctness] Reverted premature INV-01..07 completion.** The plan frontmatter listed the full phase requirement set (`INV-01..INV-07`), and the state handler marked all seven Complete. But these are end-user capabilities (add/edit holdings, fetch prices, show P&L) delivered by downstream Plans 02–06 — Plan 01 only lays the schema/dep/test foundation. Marking them Complete after Plan 01 over-claims and corrupts traceability. Reverted REQUIREMENTS.md checkboxes to `[ ]` and status to `In Progress` so the phase completes them as the real work lands.

## Package Legitimacy Gate

Task 1 (blocking-human package-legitimacy gate) was **APPROVED by the user** before this execution: `yfinance>=1.5.1` and `apscheduler>=3.11.3` approved; `pycoingecko` not added. No auth gates encountered.

## Known Stubs

The three new test files are **intentional red-target stubs** (7 `pytest.fail` bodies) per the plan's Wave-0 design — they are not defects. Downstream plans fill them:
- `test_portfolio.py` (4 tests) → Plan 03/04
- `test_prices.py` (2 tests) → Plan 04
- `test_scheduler.py` (1 test) → Plan 06

These do not block Plan 01's goal (provide red targets); they *are* the goal.

## Commits

- `0991799` chore(05-01): add yfinance and apscheduler pins
- `23e8ebf` feat(05-01): add Platform and PortfolioValueHistory models, holdings.platform_id (D-17)
- `89e61da` feat(05-01): alembic 004 — platforms, holdings.platform_id, portfolio_value_history (D-17)
- `85a8223` test(05-01): Wave-0 red-target scaffolds for portfolio, prices, scheduler

## Self-Check: PASSED

All created files present on disk; all four task commits found in git; `yfinance==1.5.1` and `apscheduler==3.11.3` import cleanly from the uv venv.
