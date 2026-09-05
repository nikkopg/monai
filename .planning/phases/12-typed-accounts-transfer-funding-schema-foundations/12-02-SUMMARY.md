---
phase: 12-typed-accounts-transfer-funding-schema-foundations
plan: 02
subsystem: schema
tags: [alembic, postgresql, sqlalchemy, migration]

# Dependency graph
requires:
  - phase: 12-typed-accounts-transfer-funding-schema-foundations
    plan: 01
    provides: RED pytest scaffold (test_typed_accounts.py, test_cashflow_view.py) encoding all three Phase 12 success criteria
provides:
  - accounts.type DB-enforced discriminator (CHECK ck_accounts_type + NOT NULL + server_default 'liquid'), backfilled from the D-02 audit map
  - transactions.transfer_pair_id and portfolio_events.source_account_id pairing columns for Phase 13's transfer/funding writes
  - cashflow_transactions exclusion view (NOT EXISTS keyed on type='investment', NULL-account_id-safe)
  - backend/models.py mirrors the migrated schema
affects: [12-03-PLAN, 13-transfer-funding-writes]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "sa.inspect()-guarded DDL idiom (idempotent, re-runnable upgrade()) copied verbatim from migration 009"
    - "abort-loudly RuntimeError on live-data drift before any constraining DDL runs — single env.py transaction gives a clean rollback"
    - "exclusion view via NOT EXISTS keyed on the discriminator column (never inner join / bare NOT IN) to guarantee NULL-FK rows are retained, not silently dropped"

key-files:
  created:
    - alembic/versions/010_typed_accounts.py
    - .planning/phases/12-typed-accounts-transfer-funding-schema-foundations/deferred-items.md
  modified:
    - backend/models.py
    - backend/tests/test_account_crud.py
    - backend/tests/test_cashflow_summary.py
    - backend/tests/test_write_tools.py
    - backend/tests/test_tools.py

key-decisions:
  - "Migration revision f1a2b3c4d5e6, down_revision=e5f6a7b8c9d0 (009) — verified against live alembic_version before writing"
  - "ACCOUNT_TYPE = {1: liquid, 2: liquid, 3: investment, 559: liquid} applied exactly per the locked D-02 audit map; no auto-inference logic added"
  - "transfer_pair_id carries NO foreign key (plain indexed Integer) — pairing semantics (self-ref vs. group) deliberately deferred to Phase 13 per RESEARCH Open Q2"
  - "cashflow_transactions created after the pairing columns so SELECT t.* is the full superset including transfer_pair_id"
  - "Rule 1 auto-fix: 6 test fixtures across 4 files used free-form account type strings (checking/savings/bank) that pre-date the CHECK constraint; swapped to 'liquid' since none of those tests assert on the type value itself"
  - "test_settings.py::test_put_settings_requires_key failure (503 instead of 401) reproduced identically with this plan's code changes reverted — confirmed pre-existing, logged to deferred-items.md, not fixed (scope boundary)"

requirements-completed: [ACCT-03]

coverage:
  - id: D1
    description: "Migration 010 applies cleanly against the live dev DB, backfills the 4 accounts from D-02, aborts loudly on drift, and DB-enforces the liquid/investment discriminator"
    requirement: "ACCT-03"
    verification:
      - kind: unit
        ref: "python -m pytest backend/tests/test_typed_accounts.py -q"
        status: pass
      - kind: manual
        ref: "psql \\d accounts shows NOT NULL, DEFAULT 'liquid', CHECK ck_accounts_type; SELECT id,type FROM accounts confirms 1,2,559=liquid, 3=investment, 0 NULL"
        status: pass
    human_judgment: false
  - id: D2
    description: "cashflow_transactions view excludes investment-account rows, retains NULL-account_id rows, and the raw-view delta equals the investment-account expense magnitude"
    requirement: "ACCT-03"
    verification:
      - kind: unit
        ref: "python -m pytest backend/tests/test_cashflow_view.py::test_view_excludes_investment backend/tests/test_cashflow_view.py::test_view_keeps_null_account backend/tests/test_cashflow_view.py::test_double_count_delta -q"
        status: pass
    human_judgment: false
  - id: D3
    description: "transactions.transfer_pair_id and portfolio_events.source_account_id exist, nullable, indexed, mapped in the ORM"
    requirement: "ACCT-03"
    verification:
      - kind: unit
        ref: "python -m pytest backend/tests/test_typed_accounts.py::test_pairing_columns -q"
        status: pass
    human_judgment: false

duration: 35min
completed: 2026-07-25
status: complete
---

# Phase 12 Plan 02: Typed Accounts Migration + ORM Mirror Summary

**Migration 010 applied to the live dev DB: `accounts.type` is now a DB-enforced liquid/investment discriminator backfilled from the locked D-02 audit map, plus the two additive transfer/funding pairing columns and the `cashflow_transactions` exclusion view — `backend/models.py` mirrors all of it.**

## Performance

- **Duration:** ~35 min
- **Tasks:** 2
- **Files modified:** 2 core (migration + models.py) + 4 test-fixture fixes + 1 deferred-items log

## Accomplishments

- `alembic/versions/010_typed_accounts.py` — backfills `accounts.type` from `ACCOUNT_TYPE = {1: liquid, 2: liquid, 3: investment, 559: liquid}` (bound params, idempotent), abort-loudly asserts the live account id set is exactly `{1,2,3,559}` and zero NULL types remain, adds `ck_accounts_type` CHECK constraint, tightens to `NOT NULL DEFAULT 'liquid'`, adds `transactions.transfer_pair_id` (nullable, indexed, no FK) and `portfolio_events.source_account_id` (nullable, indexed, FK→accounts.id), and creates `cashflow_transactions` via `NOT EXISTS (... a.type = 'investment')` — keeping NULL-`account_id` rows in the view. Guarded downgrade() strictly reverses all of it (values are left backfilled).
- Applied `alembic upgrade head` against the live dev DB (was at 009/`e5f6a7b8c9d0`, now at 010/`f1a2b3c4d5e6`); a second `alembic upgrade head` confirmed a clean no-op.
- Manual spot-checks on the live DB: `\d accounts` shows the CHECK + NOT NULL + DEFAULT; `SELECT id,type FROM accounts` shows 1,2,559→liquid, 3→investment, 0 NULL; `\d transactions`/`\d portfolio_events` show both new columns with the right nullability/index/FK; view excludes the 0 investment-account rows currently in `cashflow_transactions` and retains all 12 NULL-`account_id` rows.
- `backend/models.py`: `Account.type` → `Mapped[str]` nullable=False server_default="liquid"; `Transaction.transfer_pair_id` (plain indexed Integer, no FK) and `PortfolioEvent.source_account_id` (nullable indexed FK→accounts.id) mapped.
- Ran the plan's 7-test target subset (`test_typed_accounts.py` x4, `test_cashflow_view.py` x3) — all green. `test_tools_spending_excludes_investment` (Plan 03's target) stays RED as expected/documented in the plan.

## Task Commits

Each task was committed atomically:

1. **Task 1: Write and apply migration 010_typed_accounts.py** - `f7b6043` (feat)
2. **Task 2: Update backend/models.py + fix account-type test fixtures** - `de9f7fa` (feat)

**Plan metadata:** _pending — this commit_

## Files Created/Modified

- `alembic/versions/010_typed_accounts.py` - the migration (backfill → assert → CHECK → tighten → additive columns → view)
- `backend/models.py` - `Account.type`, `Transaction.transfer_pair_id`, `PortfolioEvent.source_account_id` mirror the migrated schema
- `backend/tests/test_account_crud.py`, `backend/tests/test_cashflow_summary.py`, `backend/tests/test_write_tools.py`, `backend/tests/test_tools.py` - fixture `type` values swapped from free-form strings ("checking"/"savings"/"bank") to "liquid" (deviation, see below)
- `.planning/phases/12-typed-accounts-transfer-funding-schema-foundations/deferred-items.md` - logs one pre-existing, out-of-scope test failure

## Decisions Made

See frontmatter `key-decisions`. The one requiring the most judgment: whether to expand this plan's scope beyond its locked `files_modified` (migration + models.py) to fix test fixtures broken by the new CHECK constraint. Treated as Rule 1 (auto-fix bug directly caused by this task's DDL change) since the failures were mechanical (free-form type strings, not the behavior under test) and reproducibly traced to this plan's CHECK constraint via `git stash` bisection — not left as a regression for a later plan to trip over.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test fixtures using free-form `accounts.type` values broke under the new CHECK constraint**
- **Found during:** Full-suite regression check after Task 1 (`pytest backend/tests/ -q`)
- **Issue:** 16 tests across `test_account_crud.py`, `test_cashflow_summary.py`, `test_write_tools.py`, `test_tools.py` failed with `IntegrityError: CheckViolation ck_accounts_type` — they construct `Account`/POST-account fixtures with type values like `"checking"`, `"savings"`, `"bank"`, which pre-date migration 010's `type IN ('liquid','investment')` constraint (D-01, binary closed set).
- **Fix:** Bisected with `git stash` to confirm each failure was caused by this plan's migration (not pre-existing); swapped all 6 occurrences to `"liquid"` — none of the affected tests assert on the `type` value itself, only on CRUD/audit/proposal/query behavior, so the change is inert to what they verify.
- **Files modified:** `backend/tests/test_account_crud.py`, `backend/tests/test_cashflow_summary.py`, `backend/tests/test_write_tools.py`, `backend/tests/test_tools.py`
- **Commit:** `de9f7fa`

### Deferred (out of scope, logged not fixed)

- `backend/tests/test_settings.py::test_put_settings_requires_key` fails (`503` instead of `401`). Bisected the same way (`git stash`) and confirmed it reproduces identically without this plan's changes — pre-existing, unrelated to `accounts.type`. Logged in `deferred-items.md`, not fixed (outside this plan's file scope).

## Issues Encountered

None beyond the deviation above. `alembic upgrade head` applied cleanly on the first attempt; no rollback was triggered.

## User Setup Required

None - migration applied directly to the live dev DB as part of this plan (per plan instructions); no external service configuration required.

## Next Phase Readiness

- **Plan 03** (tools.py view switch) can now target `test_tools_spending_excludes_investment` — the `cashflow_transactions` view it needs already exists and is verified correct (exclusion + NULL-retention + double-count delta all green).
- **Phase 13** (transfer/funding writes) has both pairing columns available: `transactions.transfer_pair_id` (liquid↔liquid, no FK — self-ref/group semantics still open) and `portfolio_events.source_account_id` (liquid→investment funding, FK→accounts.id).
- One pre-existing, unrelated test failure (`test_settings.py::test_put_settings_requires_key`) remains open — tracked in `deferred-items.md`, not a regression from this plan.

---
*Phase: 12-typed-accounts-transfer-funding-schema-foundations*
*Completed: 2026-07-25*

## Self-Check: PASSED

- FOUND: alembic/versions/010_typed_accounts.py
- FOUND: backend/models.py (modified)
- FOUND: f7b6043
- FOUND: de9f7fa
