---
phase: 01-schema-foundation-auth
plan: "01"
subsystem: database/schema
tags: [alembic, migrations, orm, schema, docker]
dependency_graph:
  requires: []
  provides: [alembic-managed-schema, 5-new-orm-models, docker-entrypoint-migration]
  affects: [backend/models.py, backend/db.py, backend/main.py, alembic/, backend/Dockerfile, README.md]
tech_stack:
  added: [alembic>=1.13.0, httpx>=0.27.0]
  patterns: [two-migration-stamp-recipe, sqlalchemy-2.0-mapped-style, docker-entrypoint-migration]
key_files:
  created:
    - alembic/env.py
    - alembic/versions/001_baseline.py
    - alembic/versions/002_new_tables.py
    - alembic.ini
    - alembic/script.py.mako
    - backend/entrypoint.sh
  modified:
    - backend/models.py
    - backend/db.py
    - backend/main.py
    - backend/Dockerfile
    - backend/requirements.txt
    - README.md
decisions:
  - "D-01: Two migrations + stamp — baseline mirrors current accounts/transactions, stamped not run on live DB; migration 002 creates 5 new tables additively"
  - "D-02: date_helpers view moved from init_db() into migration 002 via op.execute()"
  - "D-03: pg_dump backup step documented in README runbook; BLOCKING checkpoint before live upgrade"
  - "D-04: Base.metadata.create_all() and init_db() removed from db.py; schema fully Alembic-managed"
  - "D-09: Numeric precision — quantity Numeric(28,8), money Numeric(18,2) across all new tables"
  - "D-10: audit_log before/after and proposals payload stored as JSONB columns"
  - "D-11: Proposal confirm token is a separate high-entropy String(64) column, not the UUID id"
  - "D-12: price_cache with source field (manual/coingecko/etc) as single price read path"
metrics:
  duration: "~45 min (continuation from prior session)"
  completed: "2026-06-21"
  tasks_completed: 4
  tasks_total: 4
  files_created: 6
  files_modified: 6
---

# Phase 1 Plan 01: Alembic Migration Foundation Summary

**One-liner:** Two-migration Alembic setup (stamp + new tables) with 5 new ORM models, create_all removed, and Docker entrypoint running migrations before uvicorn.

## What Was Built

All 4 tasks of plan 01-01 are complete. Tasks 1-3 built the Alembic foundation; Task 4 (the live-DB migration, a human-verify checkpoint) was applied and verified by the operator — see "Checkpoint — Task 4" below.

### Task 1 — Alembic env wiring and two migration files (commit c3edb14)

- `alembic/env.py` wired to `DATABASE_URL` env var and `Base.metadata`; sync engine_from_config with NullPool; configparser `%` escape applied
- `alembic/versions/001_baseline.py` hand-written to mirror current accounts + transactions schema exactly (4 named indexes); `down_revision = None`; prominent STAMP comment
- `alembic/versions/002_new_tables.py` chained to 001; creates date_helpers view via `op.execute()` then 5 tables (audit_log, proposals, holdings, portfolio_events, price_cache) with correct Numeric precision and JSONB columns
- `alembic>=1.13.0` and `httpx>=0.27.0` added to `backend/requirements.txt`

### Task 2 — 5 ORM models, Decimal annotation fix, create_all/init_db removal (commit 78b2c2d)

- `AuditLog`, `Proposal` (UUID PK + separate token secret), `Holding`, `PortfolioEvent`, `PriceCache` added to `backend/models.py` using SQLAlchemy 2.0 `Mapped[]` style
- `Transaction.amount` annotation corrected: `Mapped[float]` → `Mapped[Decimal]` (Pitfall 5)
- `Base.metadata.create_all()` and `init_db()` removed from `backend/db.py`
- `@app.on_event("startup")` block calling `init_db()` removed from `backend/main.py`
- All 26 existing tests remain green

### Task 3 — Docker entrypoint, Dockerfile CMD, README runbook (commit be477ab)

- `backend/entrypoint.sh`: `set -e`, `alembic upgrade head`, then `exec uvicorn backend.main:app`
- `backend/Dockerfile`: COPY entrypoint.sh, chmod +x, CMD replaced with `["./backend/entrypoint.sh"]`
- `README.md` "Database migrations" section: step-by-step one-time runbook (pg_dump backup → alembic stamp 3a1f8c2d9e04 → upgrade head → row-count verification), stamp-before-upgrade Pitfall 1 warning, MONAI_API_KEY key-gen command

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] create_all string in db.py docstring blocked verify command**
- **Found during:** Task 2 acceptance check
- **Issue:** The plan's verify command `! grep -q "create_all" db.py` would fail because the new docstring explaining the removal contained the string `Base.metadata.create_all()` as historical context
- **Fix:** Rephrased the docstring to say "the former init_db() function and the _DATE_HELPERS_VIEW SQL string have been removed" without referencing `create_all` directly
- **Files modified:** backend/db.py
- **Commit:** 78b2c2d (same task commit)

## Known Stubs

None — this plan creates schema/infrastructure only; no UI or data-rendering code was modified.

## Threat Flags

None beyond what is already in the plan's threat model. No new network endpoints, auth paths, or trust boundaries introduced in Tasks 1-3.

## Self-Check

- [x] `backend/entrypoint.sh` exists and contains `alembic upgrade head`
- [x] `backend/Dockerfile` references `entrypoint.sh`
- [x] `README.md` contains `pg_dump` and `alembic stamp`
- [x] `backend/models.py` contains `class Holding`
- [x] `grep create_all backend/db.py` returns nothing
- [x] `grep init_db backend/main.py` returns nothing
- [x] All 3 task commits exist: c3edb14, 78b2c2d, be477ab
- [x] 26 tests pass

## Self-Check: PASSED

## Checkpoint — Task 4 (human-verify): COMPLETE ✓

The operator applied the migration to the live monai_pgdata volume on 2026-06-21:
took a `pg_dump` backup (`backup_pre_alembic.sql`, 391K), then ran
`alembic stamp 3a1f8c2d9e04` (→ current = 3a1f8c2d9e04) and `alembic upgrade head`
(→ current = 7b4e9f1a6c52, head).

**Verified — no data loss:** `transactions` = 5609 (unchanged), `accounts` = 3
(unchanged), the 5 new tables created, and the `date_helpers` view present.
Success Criterion #1 satisfied.

**Follow-up:** rebuild the backend image so the running app picks up the new code
(`docker compose build backend && docker compose up -d backend`); the entrypoint's
`alembic upgrade head` is now a safe no-op (already at head).
