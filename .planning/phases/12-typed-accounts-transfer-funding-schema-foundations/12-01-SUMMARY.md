---
phase: 12-typed-accounts-transfer-funding-schema-foundations
plan: 01
subsystem: testing
tags: [pytest, sqlalchemy, alembic, postgres]

# Dependency graph
requires:
  - phase: 11-category-hierarchy-schema-audit-migration
    provides: importlib-migration-load idiom (test_category_migration.py) and the live-DB pytest idiom (test_tools.py) this plan mirrors
provides:
  - RED pytest scaffold encoding all three Phase 12 success criteria before any migration or code exists
  - Named node ids Plan 02 (migration 010) and Plan 03 (tools.py view switch) must turn GREEN
affects: [12-02-PLAN, 12-03-PLAN]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "importlib lazy-load of an alembic/versions/*.py module INSIDE a test body (not module scope) so collection succeeds before the migration file exists — mirrors test_category_migration.py's _ensure_real_alembic_package() shim"
    - "live-DB introspection via backend.db.engine singleton + sa.inspect(), no fresh-migrate fixture"

key-files:
  created:
    - backend/tests/test_typed_accounts.py
    - backend/tests/test_cashflow_view.py
  modified: []

key-decisions:
  - "Both test files query/introspect live Postgres directly (no mocking, no fresh-migrate fixture) — matches test_tools.py idiom already used across the suite"
  - "test_type_check_and_default explicitly rolls back both probe inserts (CHECK-violation attempt + default-value insert) via conn.begin()/trans.rollback() so the live accounts table is never mutated by the test suite"
  - "test_double_count_delta derives the investment-expense magnitude live via SQL, never hard-codes the ~45.9M figure from RESEARCH.md"

patterns-established:
  - "Distinct RED node ids per success criterion (test_account_type_map, test_account_classification, test_type_check_and_default, test_pairing_columns / test_view_excludes_investment, test_view_keeps_null_account, test_double_count_delta, test_tools_spending_excludes_investment) so Plan 02 and Plan 03 can each target their own green subset without needing all 8 tests to pass simultaneously"

requirements-completed: [ACCT-03]

coverage:
  - id: D1
    description: "test_typed_accounts.py encodes D-02 classification (Criterion 1), CHECK+default constraint enforcement, and pairing-column introspection (Criterion 3) as four RED, collectable tests"
    requirement: "ACCT-03"
    verification:
      - kind: unit
        ref: "python -m pytest backend/tests/test_typed_accounts.py --co -q"
        status: pass
    human_judgment: false
  - id: D2
    description: "test_cashflow_view.py encodes the view-exclusion, NULL-account_id-parity, and double-count-delta invariants (Criterion 2) plus a tools-level exclusion gate for Plan 03, as four RED, collectable tests"
    requirement: "ACCT-03"
    verification:
      - kind: unit
        ref: "python -m pytest backend/tests/test_cashflow_view.py --co -q"
        status: pass
    human_judgment: false

duration: 20min
completed: 2026-07-25
status: complete
---

# Phase 12 Plan 01: Nyquist RED Scaffold Summary

**Two pytest files (8 named tests) encoding all three Phase 12 success criteria as RED-before-migration, GREEN-after Plans 02/03 targets — no production code touched.**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-07-25T11:53:00Z
- **Completed:** 2026-07-25T18:53:45Z
- **Tasks:** 2
- **Files modified:** 2 (both created)

## Accomplishments
- `backend/tests/test_typed_accounts.py` — 4 tests: D-02 account-type map (lazy-loaded from `alembic/versions/010_typed_accounts.py` inside the test body), live D-02 classification with zero-NULL assertion, CHECK+server-default constraint probe (both branches rolled back), and pairing-column introspection (`transactions.transfer_pair_id`, `portfolio_events.source_account_id`)
- `backend/tests/test_cashflow_view.py` — 4 tests: view excludes investment-account rows, view preserves NULL-`account_id` rows (NOT EXISTS guarantee), the raw−view==investment double-count delta (derived live, not hard-coded), and a distinct tools-level `spending_total` exclusion gate for Plan 03
- Verified both files collect cleanly (`pytest --co -q` → 8 tests collected, exit 0) and are fully RED when actually run (8 failed, 0 errors) — confirmed each failure is the intended pre-migration RED reason (missing migration file, all-NULL account types, missing CHECK constraint, missing pairing columns, missing view) rather than a test bug

## Task Commits

Each task was committed atomically:

1. **Task 1: Create test_typed_accounts.py** - `611ba4a` (test)
2. **Task 2: Create test_cashflow_view.py** - `1cf8960` (test)

**Plan metadata:** _pending — this commit_

## Files Created/Modified
- `backend/tests/test_typed_accounts.py` - RED scaffold for Criterion 1 (D-02 classification) + Criterion 3 (pairing columns) + CHECK/default constraint enforcement
- `backend/tests/test_cashflow_view.py` - RED scaffold for Criterion 2 (view exclusion, NULL parity, double-count delta) + Plan 03's tools-level exclusion gate

## Decisions Made
None beyond what's captured in frontmatter `key-decisions` — plan executed exactly as written, following the `test_category_migration.py` / `test_tools.py` idioms named in the plan's `<read_first>` blocks.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. Verified with `uv run --with-requirements backend/requirements.txt --with pytest --with pytest-asyncio -- python -m pytest ... --co -q` since `python`/`pytest` are not directly on PATH in this environment (host uses `uv` per project CLAUDE.md); this is an execution-environment detail, not a deviation from the plan's code or test content.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Plan 02 (migration 010_typed_accounts.py) has 5 concrete RED tests to turn GREEN: `test_account_type_map`, `test_account_classification`, `test_type_check_and_default`, `test_pairing_columns`, `test_view_excludes_investment`, `test_view_keeps_null_account`, `test_double_count_delta` (7 of 8 — all except the tools-level one)
- Plan 03 (tools.py view switch) has exactly one target: `test_tools_spending_excludes_investment`
- No blockers. Both test files are self-contained (only `backend.db.engine`, `sqlalchemy`, and — for one test — `backend.tools`), so no additional Plan 02/03 setup is needed beyond the migration and tools.py edits themselves.

---
*Phase: 12-typed-accounts-transfer-funding-schema-foundations*
*Completed: 2026-07-25*

## Self-Check: PASSED

- FOUND: backend/tests/test_typed_accounts.py
- FOUND: backend/tests/test_cashflow_view.py
- FOUND: 611ba4a
- FOUND: 1cf8960
