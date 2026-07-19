---
phase: 11-category-hierarchy-schema-audit-migration
plan: 03
subsystem: api
tags: [fastapi, sqlalchemy, category-hierarchy, tdd, crud, rest]

requires:
  - phase: 11-category-hierarchy-schema-audit-migration (plans 01-02)
    provides: Category ORM model, transactions.category_id (migration 009 applied to live DB, 76 rows seeded, zero NULL category_id)
provides:
  - "Audited category write layer: apply_add_category, apply_edit_category, apply_delete_category (backend/writes.py)"
  - "Rewritten apply_rename_category / apply_merge_category — single-row categories.name edits instead of bulk transactions.category UPDATEs (D-11)"
  - "REST CRUD: POST/PUT/DELETE /categories mirroring /accounts, tree-shaped GET /categories with tx_count + effective_color + ?kind= filter"
affects: [11-06]

tech-stack:
  added: []
  patterns:
    - "Depth-cap enforcement via Python parent_id-chain walk (_category_depth/_subtree_height/_root_kind in writes.py) rather than a recursive CTE — tree is tiny (max depth 3)"
    - "Recursive CTE (WITH RECURSIVE) for the one read path that needs a full descendant set: GET /categories/{name}/affected-count"
    - "CategoryUpdate read with model_dump(exclude_unset=True) (not exclude_none) so an explicit parent_id is distinguishable from not-provided"

key-files:
  created:
    - backend/tests/test_category_hierarchy.py
  modified:
    - backend/writes.py
    - backend/schemas.py
    - backend/main.py
    - backend/tests/test_category_management.py

key-decisions:
  - "A category with subcategories can NEVER be deleted via DELETE /categories/{id}, even with reassign_to — reassign_to only ever moves transactions, never subcategories, so any child_count > 0 short-circuits to 422 before reassign_to is even considered (Pitfall 3)"
  - "'reassign_to pointing at the deleted node's own descendant' collapses to the degenerate self-reference case for a childless leaf (a node with real children is already blocked outright above) — the guard still rejects reassign_to == the node's own id"
  - "apply_rename_category/apply_merge_category resolve old_name/from_name/into_name against categories.name; an ambiguous match (same leaf name under two different parents) raises ValueError rather than guessing"
  - "GET /categories/{name}/affected-count kept its pre-hierarchy 'unknown name -> 0, never 404' contract, now counting the node + all its descendants via a recursive CTE"

requirements-completed: [CAT-01, CAT-02]

duration: "~50min wall"
completed: "2026-07-19"
---

# Phase 11 Plan 03: Category Write Layer + CRUD Summary

Audited apply_add/edit/delete_category helpers enforcing the 3-level depth cap and a child-aware block-or-reassign delete guard, rewritten single-row rename/merge (D-11), and a tree-shaped GET /categories with per-node tx_count and inherited color — all proven by 20 TDD tests written before the implementation.

## Performance

- **Duration:** ~50 min wall
- **Tasks:** 2 (RED, GREEN)
- **Files modified:** 5 (1 created, 4 modified)

## Accomplishments
- `apply_add_category` / `apply_edit_category` / `apply_delete_category` in `backend/writes.py`: depth cap (CAT-01) on both create and re-parent, system-row protection (D-04), child-count-aware delete guard (CAT-02/Pitfall 3) that always blocks deleting a category with subcategories regardless of `reassign_to`
- `apply_rename_category` / `apply_merge_category` reworked from bulk `transactions.category` string UPDATEs to single-row `categories.name` edits (D-11) — transactions follow via the `category_id` FK, the legacy free-text `category` column is never touched by either operation
- `POST/PUT/DELETE /categories` in `backend/main.py` mirror the `/accounts` CRUD pattern verbatim (require_api_key + reset_engine on every mutation, ValueError → 422)
- `GET /categories` returns the full tree (`CategoryNode`, self-referential) with per-node `tx_count` (direct count only) and `effective_color` (inherited when the row's own color is NULL, D-14), filterable by `?kind=`
- `GET /categories/{name}/affected-count` reworked to be descendant-inclusive (recursive CTE) instead of a flat string count
- 20 new tests in `backend/tests/test_category_hierarchy.py` pin every guard (depth cap, uniqueness, child-aware delete, self-reassign, rename/merge collisions and system-row locks, tree shape)
- `backend/tests/test_category_management.py` reworked onto real `Category`/`category_id` fixtures (rename/merge tests no longer assert on the legacy string column, which the new write path never touches)

## Task Commits

1. **Task 1: RED — failing tests for category write layer + CRUD endpoints** - `9b495b7` (test)
2. **Task 2: GREEN — writes.py helpers, schemas, /categories endpoints** - `ae3de8c` (feat)

_No refactor commit needed._

## Files Created/Modified
- `backend/tests/test_category_hierarchy.py` - 20 tests: create/depth-cap, re-parent depth-cap, delete (leaf/blocked/parent-with-children/self-reassign/valid-reassign), rename/merge (D-11 + collisions + children-blocked), system-row locks, GET tree shape + kind filter
- `backend/writes.py` - `_category_depth`/`_subtree_height`/`_root_kind`/`_descendant_ids` helpers; `apply_add_category`, `apply_edit_category`, `apply_delete_category`; rewrote `apply_rename_category`, `apply_merge_category`
- `backend/schemas.py` - `CategoryCreate`, `CategoryUpdate` (exclude_unset semantics), `CategoryNode` (self-referential, `model_rebuild()`)
- `backend/main.py` - `POST/PUT/DELETE /categories`, reworked `GET /categories` (tree) and `GET /categories/{name}/affected-count` (recursive CTE), rename/merge wrapped with ValueError → 422
- `backend/tests/test_category_management.py` - rename/merge/affected-count tests reworked onto `Category`/`category_id` fixtures

## Decisions Made
- Delete-with-children is unconditionally blocked (never offered a reassign path) since `reassign_to` only moves transactions — subcategories would need their own merge/re-parent first. This is stricter than accounts (which have no analogous "children" concept) but matches the plan's Pitfall 3 note.
- Rename/merge name resolution treats an ambiguous match (same name under two different parents) as a hard error rather than picking one arbitrarily — surfaces as 422 with a clear message rather than silently renaming/merging the wrong node.
- Kept `GET /categories/{name}/affected-count`'s existing "unknown name → 0, never 404" contract for backward compatibility with existing callers, just made the count descendant-inclusive.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test cleanup helper batched multiple Category deletes into one non-ordered executemany**
- **Found during:** Task 1 RED verification (after Task 2 GREEN, running the new tests against real handlers)
- **Issue:** `Category` has no ORM `relationship()` for its self-reference (only a plain `parent_id` FK column). When a test's cleanup helper called `db.delete()` on several Category rows before a single `db.commit()`, SQLAlchemy's unit-of-work batched them into one `executemany` DELETE with no dependency-aware ordering — a child-before-parent intent silently became parent-first and tripped the FK RESTRICT constraint.
- **Fix:** `_cleanup()` in both test files now commits after each individual category delete, forcing DB-level sequential ordering.
- **Files modified:** backend/tests/test_category_hierarchy.py, backend/tests/test_category_management.py
- **Commit:** ae3de8c (part of Task 2/GREEN — test infra fix, not implementation)

**2. [Rule 1 - Bug] `db_session.get(...)` on a strongly-referenced deleted ORM object raised ObjectDeletedError instead of returning None**
- **Found during:** Task 1 RED verification
- **Issue:** Tests that kept a Python reference to a `Category` object (e.g. `cat = _make_category(...)`) and later accessed `cat.id` or called `db_session.get(Category, cat.id)` AFTER `db_session.expire_all()` — following an external delete via the API's own session — triggered a refresh-on-access of the now-missing row, raising `sqlalchemy.orm.exc.ObjectDeletedError` rather than cleanly resolving to "not found". The existing `test_account_crud.py` avoids this because its `_make_account` helper returns the bare int id, never the ORM object, so no strong reference survives in the identity map.
- **Fix:** Captured every id into a plain `int` BEFORE calling `expire_all()`, and added a `_category_exists(db, cat_id)` raw-SQL helper (`SELECT 1 FROM categories WHERE id = :id`) instead of `db.get(...) is None` for post-delete existence checks.
- **Files modified:** backend/tests/test_category_hierarchy.py, backend/tests/test_category_management.py
- **Commit:** ae3de8c

---

**Total deviations:** 2 auto-fixed (both Rule 1 — test-infrastructure bugs discovered while getting the new tests green, no production code affected)
**Impact on plan:** No scope creep — both fixes are testing-harness corrections needed to correctly observe the already-planned behavior; the write-layer/CRUD implementation itself matches the plan as written.

## Issues Encountered
None beyond the two auto-fixed test-infrastructure issues above.

## TDD Gate Compliance

RED commit `9b495b7` (test(11-03)) precedes GREEN commit `ae3de8c` (feat(11-03)). No refactor commit needed.

## Verification

- `pytest backend/tests/test_category_hierarchy.py backend/tests/test_category_management.py -q` → 25 passed
- `pytest backend/tests -q` → 227 passed, 1 failed — the failure (`test_settings.py::test_put_settings_requires_key`) is the documented pre-existing failure (fails at base commit too, logged since plan 11-01's deferred-items.md), not a regression from this plan
- Every mutating `/categories` handler in main.py (`POST`, `PUT`, `DELETE {id}`, `POST /rename`, `POST /merge`) verified by grep to contain both `Depends(require_api_key)` and a `reset_engine()` call after commit
- Rename test (`test_rename_updates_name_only_transactions_follow_via_fk`) proves a fixture transaction's legacy `category` string is unchanged after rename while `category_id` stays pointed at the (renamed) row — direct D-11 evidence

## Known Stubs

None. The old cashflow `CategoryManager.tsx` (a flat-string-list consumer of the pre-hierarchy `GET /categories` shape) now receives a tree instead of `{"categories": [...]}` and will render incorrectly until plan 11-06 replaces it — this is explicitly called out in the plan as expected transient breakage within this phase, not a stub introduced here.

## Threat Flags

None beyond the plan's threat model. T-11-08 (Depends(require_api_key) on every mutating route), T-11-09 (text() + bound params only, no string interpolation anywhere in writes.py/main.py's category SQL, including the recursive CTE), T-11-10 (block-or-reassign guard checks both tx count and child count; the parent_id FK has no ondelete and RESTRICTs as a DB-level backstop), T-11-11 (one AuditLog row per apply_* call — add/edit/delete/rename/merge each write exactly one), T-11-12 (reset_engine() after every category mutation commit) all implemented as specified. T-11-SC: no packages installed.

## Next Phase Readiness

- Direct REST category CRUD is complete and hierarchy-aware; `tools.py`/`query.py` (11-04) and this plan's endpoints now share the same `categories`/`category_id` source of truth.
- `ui/app/cashflow/CategoryManager.tsx` needs its own plan (11-06 per phase numbering) to consume the new tree-shaped `GET /categories` and the new CRUD endpoints — it is currently broken against the flat-list contract it was built for.
- No blockers for subsequent plans in this phase.

## Self-Check: PASSED

- backend/tests/test_category_hierarchy.py — FOUND (20 tests)
- backend/writes.py contains apply_add_category/apply_edit_category/apply_delete_category — FOUND
- backend/main.py contains POST/PUT/DELETE /categories — FOUND
- Commit 9b495b7 (test(11-03)) — FOUND
- Commit ae3de8c (feat(11-03)) — FOUND
- pytest backend/tests/test_category_hierarchy.py backend/tests/test_category_management.py -q → 25 passed — VERIFIED
- pytest backend/tests -q → 227 passed, 1 pre-existing failure — VERIFIED

---
*Phase: 11-category-hierarchy-schema-audit-migration*
*Completed: 2026-07-19*
