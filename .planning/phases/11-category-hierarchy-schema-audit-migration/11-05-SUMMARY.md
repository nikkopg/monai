---
phase: 11-category-hierarchy-schema-audit-migration
plan: 05
subsystem: api
tags: [sqlalchemy, fastapi, category-hierarchy, tdd, dual-write, csv-import]

requires:
  - phase: 11-category-hierarchy-schema-audit-migration (plans 01-03)
    provides: Category ORM model, transactions.category_id (migration 009 applied live, 76 categories, zero NULL), audited category write layer (apply_add/edit/delete_category, rename/merge)
provides:
  - "resolve_category_id(db, name) helper (backend/writes.py) — exact name match at any hierarchy level, lowest-id tie-break on ambiguous names, None/empty/unknown -> Uncategorized"
  - "Dual-write (D-08) on every transaction insert/edit path: agent apply_add/edit_transaction, REST POST/PUT /transactions, CSV import"
  - "Removal of the pre-migration Transaction.category_id ORM shim (deferred/server_default/eager_defaults) now that migration 009 has run everywhere"
affects: []

tech-stack:
  added: []
  patterns:
    - "resolve_category_id: single bound-parameter SELECT ORDER BY id ASC LIMIT 1 for exact-name resolution; ambiguous names resolve to the lowest id deterministically rather than raising"
    - "Bulk-import path (importer.py) builds one name->id dict from a single SELECT instead of calling resolve_category_id per row — avoids N+1 queries on large CSV imports"

key-files:
  created: []
  modified:
    - backend/writes.py
    - backend/models.py
    - backend/main.py
    - backend/importer.py
    - backend/tests/test_category_hierarchy.py

key-decisions:
  - "Ambiguous category names (same name under two different parents) resolve to the lowest id — a documented, deterministic tie-break, never a guess or a raise (unlike apply_rename_category/apply_merge_category, which correctly treat ambiguity as a hard error since those mutate the category itself)"
  - "Removed the three-knob pre-migration shim on Transaction.category_id (deferred=True, server_default=text('NULL'), eager_defaults=False mapper arg) — models.py and the 11-01 SUMMARY both documented this as 11-05's job now that migration 009 is live everywhere and every insert path resolves a category before writing"
  - "importer.py builds its own name->id map (one SELECT) rather than calling resolve_category_id per row — a deliberate divergence from the single-row resolver for bulk-import performance; behavior is otherwise identical (unknown strings -> Uncategorized)"

requirements-completed: [CAT-03]

duration: "~35min wall"
completed: "2026-07-19"
status: complete
---

# Phase 11 Plan 05: Category Write-Path Dual-Write Summary

`resolve_category_id` helper plus dual-write on all four transaction write paths (agent apply_add/edit_transaction, REST create/update, CSV import) so `category_id` is never NULL on a new row, closing the gap migration 009 left behind.

## Performance

- **Duration:** ~35 min
- **Tasks:** 2 (TDD RED/GREEN on Task 1, direct implementation on Task 2)
- **Files modified:** 5 (0 created, 5 modified)

## Accomplishments
- `resolve_category_id(db, name)` in `backend/writes.py`: exact match at any hierarchy level; ambiguous name -> lowest id (deterministic); None/empty/unknown name -> Uncategorized system row's id, never NULL, never raises (D-04/Pitfall 2)
- `apply_add_transaction` always resolves `category_id`; `apply_edit_transaction` re-resolves it whenever the category name changes in the same call
- `POST /transactions` (main.py `create_transaction`) resolves `category_id` before constructing the row; `PUT /transactions/{id}` already dual-writes via `apply_edit_transaction`
- `backend/importer.py`'s `insert_rows` resolves `category_id` per row from a single `name->id` map (one SELECT + Uncategorized fallback) built once per import call — no N+1 queries on large CSVs; `category`/`raw_category` assignments byte-for-byte unchanged
- Removed the pre-migration `Transaction.category_id` shim (`deferred=True`, `server_default=text("NULL")`, `eager_defaults=False`) from `backend/models.py` — migration 009 is live everywhere and every write path now resolves a category first
- 8 new tests in `backend/tests/test_category_hierarchy.py` pin the resolver's exact-match/None/empty/unknown/ambiguous cases plus apply_add/edit_transaction dual-write behavior

## Task Commits

1. **Task 1a: RED — failing tests for resolve_category_id + dual-write** - `4d475e4` (test)
2. **Task 1b: GREEN — resolve_category_id + dual-write in writes.py, shim removal** - `187a20c` (feat)
3. **Task 2: REST create/update + CSV import dual-write** - `f00ea9d` (feat)

_No refactor commit needed._

## Files Created/Modified
- `backend/tests/test_category_hierarchy.py` - 8 tests: resolve_category_id exact match, None, empty string, unknown name, ambiguous name (lowest-id tie-break), apply_add_transaction dual-write (with and without a category), apply_edit_transaction re-resolution
- `backend/writes.py` - `resolve_category_id`; `apply_add_transaction`/`apply_edit_transaction` now set `category_id` alongside the legacy `category` string
- `backend/models.py` - removed the 3-knob pre-migration shim on `Transaction.category_id` (deferred/server_default/eager_defaults)
- `backend/main.py` - `create_transaction` resolves `category_id` via `resolve_category_id`; imports it from `backend.writes`
- `backend/importer.py` - `_load_category_id_map` (one SELECT -> name->id dict + Uncategorized fallback); `insert_rows` sets `category_id` per row

## Decisions Made
- Ambiguous-name resolution in `resolve_category_id` picks the lowest id deterministically instead of raising — this is a *transaction write-path* resolver (best-effort attach), not a category-mutation guard like rename/merge, where ambiguity correctly stays a hard 422.
- Removed the pre-migration ORM shim on `Transaction.category_id` even though it wasn't in this plan's `files_modified` list — both `models.py`'s own comments and the 11-01 SUMMARY explicitly assign this cleanup to plan 11-05, and leaving it in place after every write path now resolves category_id would be stale, misleading documentation (Rule 2: the shim's removal is a completeness requirement of "dual-write is now durable everywhere", not scope creep).
- `importer.py` does not call `resolve_category_id` per row; it builds its own single-SELECT `name->id` dict for the whole batch. Same fallback semantics (unknown -> Uncategorized), different implementation for bulk-import performance — this matches the plan's Task 2 action text verbatim.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Removed pre-migration category_id shim from backend/models.py**
- **Found during:** Task 1 (writes.py implementation)
- **Issue:** `Transaction.category_id` still carried the 3-knob pre-migration shim (`deferred=True`, `server_default=text("NULL")`, `__mapper_args__={"eager_defaults": False}`) documented in both `models.py`'s own comment and the 11-01 SUMMARY as "removed by plan 11-05 after migration runs". Not removing it would leave stale documentation and an unnecessary deferred-column indirection now that every insert path resolves category_id explicitly.
- **Fix:** Removed all three knobs; `category_id` is now a plain nullable indexed FK column, matching every other column on the model.
- **Files modified:** backend/models.py
- **Commit:** 187a20c (part of Task 1/GREEN)

---

**Total deviations:** 1 auto-fixed (Rule 2 — documented cleanup completing prior-plan intent, not new scope)
**Impact on plan:** No functional scope creep — the shim removal is inert with respect to behavior (explicit category_id assignment already worked with the shim in place); it only removes now-dead pre-migration scaffolding that both models.py and 11-01-SUMMARY.md name this plan as responsible for.

## Issues Encountered
The plan's Task 2 verification probe script queried `transactions.note` (singular) which doesn't exist — the actual column is `notes`. Adapted the probe to the real column name per the plan's own instruction ("adapt the probe to the real parser signature... the assertion is the fixed requirement, the harness is not"). No production code affected.

## Next Phase Readiness
- All four transaction write paths (REST create, REST update, agent apply_add/edit_transaction, CSV import) now dual-write category_id; verified zero NULL category_id rows in the live DB after this plan's changes.
- The D-04 "no NULL categories remain" claim is now durable going forward, not just a one-time migration fact.
- No blockers for subsequent plans in this phase.

## Self-Check: PASSED

- backend/writes.py contains resolve_category_id, exported and used by apply_add/edit_transaction — FOUND
- backend/importer.py contains category_id (in insert_rows and _load_category_id_map) — FOUND
- backend/main.py create_transaction calls resolve_category_id — FOUND
- Commit 4d475e4 (test(11-05)) — FOUND
- Commit 187a20c (feat(11-05)) — FOUND
- Commit f00ea9d (feat(11-05)) — FOUND
- `pytest backend/tests/test_category_hierarchy.py -k resolve -q` → 8 passed — VERIFIED
- `pytest backend/tests -q` → 235 passed, 1 pre-existing failure (test_settings.py::test_put_settings_requires_key) — VERIFIED
- CSV import probe (adapted to `notes` column) → "import dual-write OK" — VERIFIED
- REST `POST /transactions` without a category -> category_id resolves to Uncategorized id — VERIFIED
- `SELECT COUNT(*) FROM transactions WHERE category_id IS NULL` -> 0 — VERIFIED

---
*Phase: 11-category-hierarchy-schema-audit-migration*
*Completed: 2026-07-19*
