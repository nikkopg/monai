---
phase: 11-category-hierarchy-schema-audit-migration
plan: 04
subsystem: ai-tools
tags: [tdd, category-hierarchy, tool-router, dual-registration, llamaindex]
requires:
  - Live DB migrated by 11-02 (categories seeded, transactions.category_id backfilled, zero NULLs)
  - Category model + category_id shim from 11-01
provides:
  - Hierarchy-aware spending_by_category (top-group rollup + children breakdown, D-09/D-12)
  - Descendant-inclusive spending_in_category (D-10)
  - Tree-shaped list_categories with effective (inherited) colors (D-14)
  - Categories-table-validated propose_rename_category / propose_merge_category (D-11)
affects: [11-05, 11-06, 11-07]
tech-stack:
  added: []
  patterns:
    - Two LEFT JOINs up the parent chain (depth cap 3) instead of a recursive CTE for rollup
    - In-Python tree walk for descendant-id resolution, bound via category_id = ANY(:ids)
key-files:
  created: []
  modified:
    - backend/tools.py
    - backend/query.py
    - backend/mcp_server.py
    - backend/tests/test_tools.py
    - backend/tests/test_period_scoping.py
    - backend/tests/test_write_tools.py
decisions:
  - "spending_in_category resolves names case-insensitively (exact first, then substring) and returns an honest error dict for unknown names instead of a fabricated 0"
  - "Rename affected_count = transactions directly on the node (only their displayed name changes); merge requires a childless source, mirroring 11-03's write-layer rule at propose time"
  - "format_answer gained a generic error-dict early return so tool errors render as their message, never a KeyError"
metrics:
  duration: "~1.5h wall (split across a session-limit reset)"
  completed: "2026-07-19"
status: complete
---

# Phase 11 Plan 04: Hierarchy-Aware Category Tools Summary

Category read tools rewritten from free-string matching onto the category_id
hierarchy — top-group rollup with per-group children, descendant-inclusive
parent queries, tree-shaped list_categories — plus categories-table validation
in propose rename/merge, with dual registration (tools.py + query.py) and the
MCP read-only invariant mechanically asserted.

## What was built

**Task 1 (RED, commit d65221a):** 7 new tests in `backend/tests/test_tools.py`
under a `category_tree` fixture (root → child → grandchild, each with a
directly-attached transaction; a system category; an is_transfer row on the
root). All seeded rows deliberately leave the legacy `category` string NULL so
only category_id-backed implementations can pass. Covers: 3-level rollup with
`children` drill-down, system/transfer exclusion, parent-subtree vs
child-subtree sums, tree shape with inherited color + Transfer/Uncategorized
presence, rename unknown-name error dict, merge count via category_id. All 7
failed against the string-matching implementations (RED verified).

**Task 2 (GREEN, commit 48eb5ca):**
- `backend/tools.py`:
  - `_category_tree()` — one SELECT over categories → nested nodes (id, name,
    kind, icon, effective color, is_system, children), NULL colors inherit the
    nearest ancestor's (D-14), alphabetical within a level.
  - `_find_category_node()` / `_descendant_ids()` — in-Python name resolution
    and subtree walk (RESEARCH Pattern 4's recommendation at ~100 rows).
  - `spending_by_category` — `JOIN categories c ON c.id = t.category_id` plus
    two LEFT JOINs up the parent chain (depth cap 3 → two joins reach the
    top); top node via COALESCE(p2, p1, c); `WHERE amount < 0 AND is_transfer
    = false AND COALESCE(p2.is_system, p1.is_system, c.is_system) = false`
    (D-12); keeps `{"tool","rows","period"}` shape (main.py's `["rows"]`
    consumer unaffected) and adds `children` {top_name: [(subcat, total)]}
    (D-09). All SQL text() + bound params.
  - `spending_in_category` — name → node → descendant ids →
    `category_id = ANY(:ids)`; unknown name returns an error dict (honest
    refusal), which `spending_before_after_purchase` now propagates.
  - `list_categories` — returns `{"tool","categories": [tree]}`.
  - `propose_rename_category` — old_name must exist; new_name must not collide
    under the same parent (`IS NOT DISTINCT FROM` for root NULLs); count via
    category_id.
  - `propose_merge_category` — both names must exist; source must be
    childless (fails fast at propose time, mirroring 11-03's write rules);
    count via category_id. Both remain in `TOOLS.update` AFTER the
    `READ_TOOL_NAMES` snapshot — nothing moved across that line.
  - `format_answer` — error-dict early return + tree renderer for the new
    list_categories shape.
- `backend/query.py`: explicit `description=` on the five rewritten
  FunctionTool registrations stating rollup-to-top-groups and
  descendant-inclusive semantics (the LLM routes on these descriptions).
- `backend/mcp_server.py`: external MCP descriptions for the three read tools
  updated to match (stale-description class of T-11-15).

## Verification

- `pytest backend/tests/test_tools.py -q` → 37 passed
- Registry assertion → `registry OK 26` (15 read + 11 write, counts
  unchanged; no propose_* in READ_TOOL_NAMES)
- `grep descendant backend/query.py` → 2 hits (spending_by_category,
  spending_in_category descriptions)
- Full suite `pytest backend/tests -q` → 208 passed, 1 failed — the failure
  (`test_settings.py::test_put_settings_requires_key`) is the documented
  pre-existing one (fails at base commit; not counted as a regression)
- TDD gate order: `test(11-04)` d65221a precedes `feat(11-04)` 48eb5ca

## TDD Gate Compliance

RED commit d65221a precedes GREEN commit 48eb5ca. No refactor commit needed.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Legacy-string-only test seeds broke against hierarchy tools**
- **Found during:** Task 2 full-suite verification
- **Issue:** `test_period_scoping.py` (2 tests), `test_write_tools.py::
  test_propose_merge_category_creates_proposal` ("Shopping" → nonexistent
  "Retail"), and `test_tools.py::test_find_transactions_category_exact_match`
  (consumed the old `list_categories()["rows"]`) seeded/queried by legacy
  category string only.
- **Fix:** Fixtures now create real categories rows and set category_id on
  seeded transactions (with cleanup); the find_transactions test pulls its
  filter value straight from transactions; the merge test seeds two throwaway
  leaf categories. Test intent unchanged in all four.
- **Files modified:** backend/tests/test_period_scoping.py,
  backend/tests/test_write_tools.py, backend/tests/test_tools.py
- **Commit:** 48eb5ca

**2. [Rule 1 - Bug] spending_before_after_purchase KeyError on unknown category**
- **Found during:** Task 2 GREEN run
- **Issue:** It chains `spending_in_category`, which now returns an error dict
  for an unknown name — the chained `["total"]` access raised KeyError.
- **Fix:** Propagate the error dict (`{"tool", "error"}`) instead of crashing
  or fabricating; `format_answer` renders error dicts as their message.
- **Files modified:** backend/tools.py
- **Commit:** 48eb5ca

**3. [Rule 2 - Missing critical] Stale MCP descriptions for rewritten tools**
- **Found during:** Task 2 (caller sweep before editing)
- **Issue:** `mcp_server.py`'s hand-authored external descriptions still said
  "substring match on category/raw_category" / "distinct expense categories
  with total spend" — the exact stale-registration-text hazard T-11-15 names,
  on the third registration surface the plan didn't list.
- **Fix:** Updated the three read-tool descriptions to rollup /
  descendant-inclusive / tree semantics. No tool names or counts changed.
- **Files modified:** backend/mcp_server.py
- **Commit:** 48eb5ca

### Deferred Issues

- Pre-existing `test_settings.py::test_put_settings_requires_key` failure —
  out of scope (fails at base; documented since 11-01).

## Known Stubs

None.

## Threat Flags

None beyond the plan's threat model. T-11-13: text() + bound params
everywhere incl. `ANY(:ids)` expanding list; T-11-14: registry assertion
passed (no propose_* in READ_TOOL_NAMES, snapshot line untouched); T-11-15:
all three registration/description surfaces updated + behavior pinned by
tests; T-11-16: is_transfer + system-top-node exclusion pinned by test;
T-11-SC: no packages installed.

## Self-Check: PASSED

- backend/tools.py contains "category_id" — FOUND
- backend/query.py contains "list_categories" FunctionTool with description — FOUND
- Commit d65221a (test(11-04)) — FOUND
- Commit 48eb5ca (feat(11-04)) — FOUND
- pytest backend/tests/test_tools.py -q → 37 passed — VERIFIED
- registry OK 26 — VERIFIED
