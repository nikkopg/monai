---
phase: 11-category-hierarchy-schema-audit-migration
plan: 01
subsystem: database
tags: [alembic, sqlalchemy, category-hierarchy, tdd, data-migration]
requires: []
provides:
  - Category ORM model (self-referential, kind/color/icon/is_system)
  - Transaction.category_id nullable FK (with pre-migration ORM shim)
  - Migration 009 (e5f6a7b8c9d0) with unit-tested load_mapping/find_unmapped/assert_parity/kind_for_group helpers
affects: [11-02, 11-03, 11-05]
tech-stack:
  added: []
  patterns:
    - importlib.spec_from_file_location to unit-test Alembic migration helpers without a DB
    - deferred + server_default(NULL) + eager_defaults=False shim for ORM column ahead of DDL
key-files:
  created:
    - alembic/versions/009_category_hierarchy.py
    - backend/tests/test_category_migration.py
  modified:
    - backend/models.py
decisions:
  - "Migration revision id e5f6a7b8c9d0 (repo hex convention), down_revision d3e4f5a6b7c8"
  - "category_id ORM column shipped with a 3-knob pre-migration shim (deferred, server_default NULL, eager_defaults=False) — removed by plan 11-05 after migration runs"
  - "Root-name uniqueness via partial unique index uq_categories_name_root (Postgres treats NULL parent_id as distinct in the composite constraint)"
metrics:
  duration: "~2.5h wall (split across a session-limit reset)"
  completed: "2026-07-19"
status: complete
---

# Phase 11 Plan 01: Category Schema + Migration 009 Summary

Self-referential Category model + nullable transactions.category_id FK + Alembic
migration 009 whose mapping/abort/parity logic is pure, importable, and covered
by 11 DB-free unit tests (TDD RED then GREEN).

## What was built

**Task 1 (RED, commit c01eeb9):** `backend/tests/test_category_migration.py` —
11 pure-unit tests loading the (then nonexistent) migration module via
`importlib.util.spec_from_file_location`. Covers: exact-raw-string keying with
the whitespace-variant pair `"Active sport, fitness"` / `" Active sport, fitness"`
as distinct keys (Pitfall 1), empty-raw_category rejection (mapping-file
injection guard), unknown-group rejection, `find_unmapped` sorted/exact-match
semantics (trimmed variant still unmapped, D-07), `assert_parity` pass/mismatch
(names the string and both (count, sum) pairs), and `kind_for_group` for
income/expense/transfer (D-03). All 11 failed on FileNotFoundError (RED).

**Task 2 (GREEN, commit 7900a82):**
- `backend/models.py`: `Category` (tablename `categories`) — id, name(255),
  self-referential `parent_id` FK (no ondelete = RESTRICT, Pitfall 3),
  kind(16), color(16) nullable (NULL = inherit parent, D-14), icon(16)
  nullable (emoji, D-13), is_system bool (D-04). `UniqueConstraint(name,
  parent_id)` + partial unique index on name WHERE parent_id IS NULL.
  `Transaction.category_id` nullable FK, indexed, with a pre-migration shim
  (see Deviations).
- `alembic/versions/009_category_hierarchy.py`: revision `e5f6a7b8c9d0`,
  down_revision `d3e4f5a6b7c8`. Module-level pure helpers: `GROUP_META`
  (13 groups, UI-SPEC hex palette verbatim), `load_mapping`, `find_unmapped`,
  `assert_parity`, `kind_for_group`. `upgrade()` is fully idempotent
  (inspect guards + SELECT-before-INSERT seeding): create table → load CSV
  (path relative to migration file; FileNotFoundError names plan 11-02 if
  absent) → seed groups (+ Transfer/Uncategorized always) and subcategories
  (blank subcategory = raw string maps to the group node, D-01) → add
  category_id column/FK/index → abort-on-unknown (RuntimeError, D-07) →
  pre/post per-string (count, sum) parity around bound-parameter backfill
  (exact match, no TRIM/ILIKE) → zero-NULL + 74-key drift assertions →
  per-group summary print. `downgrade()` strict reverse, guarded.
  `raw_category` never touched (D-08); no string-interpolated SQL anywhere.

## Verification

- `pytest backend/tests/test_category_migration.py -q` → 11 passed
- `python -c "from backend.models import Category, Transaction; ..."` →
  `categories True`
- `alembic history` → e5f6a7b8c9d0 is head atop d3e4f5a6b7c8
- Full suite: 201 passed, 1 failed — the failure
  (`test_settings.py::test_put_settings_requires_key`) is pre-existing:
  verified failing at base commit 5bf88fa with all 11-01 changes stashed.
  Logged in `deferred-items.md`. No regression from this plan.
- Migration NOT run against any database (CSV does not exist yet — plan 11-02).

## TDD Gate Compliance

RED commit `c01eeb9` (test(11-01)) precedes GREEN commit `7900a82`
(feat(11-01)). No refactor commit needed.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Pre-migration ORM shim on Transaction.category_id**
- **Found during:** Task 2 full-suite verification
- **Issue:** The plan's plain `mapped_column(ForeignKey(...), nullable=True,
  index=True)` broke 32 DB-backed tests: SQLAlchemy puts every mapped column
  into ORM SELECTs and INSERTs, but the live dev DB (which the suite runs
  against) won't have the column until 11-02 runs the migration. Empirically
  confirmed: unset nullable columns without a server default ARE included in
  INSERT (as NULL), and server-default columns are eagerly RETURNING-fetched
  by SQLAlchemy 2.0.
- **Fix:** Three removable knobs: `deferred=True` (out of default SELECTs),
  `server_default=text("NULL")` (omitted from INSERT when unset),
  `__mapper_args__={"eager_defaults": False}` on Transaction (no RETURNING
  fetch; Transaction has no other server defaults so nothing else changes).
  Explicit assignment still writes normally once the column exists —
  empirically verified against a scratch table pre- and post-DDL. Plan 11-05
  (dual-write) removes all three knobs post-migration.
- **Files modified:** backend/models.py
- **Commit:** 7900a82

**2. [Rule 3 - Blocking] alembic package shadowing in tests**
- **Found during:** Task 2 GREEN run
- **Issue:** The repo's own `alembic/` scaffold dir (env.py + versions/)
  shares its top-level name with the pip-installed `alembic` package; with
  the repo root on sys.path, `from alembic import op` inside the migration
  module resolved to the local scaffold and raised ImportError.
- **Fix:** `_ensure_real_alembic_package()` in the test fixture temporarily
  strips the shadowing path entry and imports the real package before
  exec'ing the migration module. Test-only; `alembic` CLI is unaffected
  (it imports the real package before loading version files).
- **Files modified:** backend/tests/test_category_migration.py
- **Commit:** 7900a82

### Deferred Issues

- Pre-existing `test_settings.py::test_put_settings_requires_key` failure —
  out of scope (fails at base commit too); see deferred-items.md.

## Known Stubs

None — the migration intentionally raises FileNotFoundError until plan 11-02
creates `alembic/data/category_mapping.csv`; that is designed sequencing
(documented in the migration docstring), not a stub.

## Threat Flags

None beyond the plan's threat model. T-11-01/02/03 mitigations implemented as
specified: bound parameters only, empty-key/unknown-group ValueError before
any SQL, abort-on-unknown + parity assertions inside env.py's single
transaction. No new packages installed (T-11-SC).

## Self-Check: PASSED

- backend/tests/test_category_migration.py — FOUND
- alembic/versions/009_category_hierarchy.py — FOUND
- backend/models.py Category + category_id — FOUND (import check green)
- Commit c01eeb9 (test(11-01)) — FOUND
- Commit 7900a82 (feat(11-01)) — FOUND
