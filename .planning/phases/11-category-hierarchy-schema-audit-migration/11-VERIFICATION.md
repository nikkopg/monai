---
phase: 11-category-hierarchy-schema-audit-migration
verified: 2026-07-19T15:29:09Z
status: gaps_found
score: 3/4 roadmap truths verified (1 failed)
behavior_unverified: 0
overrides_applied: 0
gaps:
  - truth: "Record forms, filters, and dashboard charts read from the new category hierarchy (ROADMAP criterion 4 — record-forms clause)"
    status: failed
    reason: >
      TransactionModal.tsx (the live Add/Edit Transaction modal, mounted and used
      on the Cashflow page) still fetches GET /categories expecting the
      pre-phase-11 response shape `{ categories: string[] }`. Plan 11-03 changed
      this exact endpoint to `response_model=list[CategoryNode]` — a bare JSON
      array of tree nodes, not an object with a `categories` key. No plan in this
      phase touched TransactionModal.tsx (confirmed: zero matches for
      "TransactionModal" across all 7 PLAN/SUMMARY files). The result:
      `data.categories` is always `undefined`, so the category `<select>` in the
      transaction form is permanently empty of real categories (only
      "(no category)", "+ New category…", and — in edit mode only — the
      transaction's current legacy string survive). This is not merely "the
      improved hierarchy picker hasn't been built yet" (that full D-15/Phase-16
      picker build is legitimately out of this phase's scope, per
      11-RESEARCH.md's Architectural Responsibility Map) — it is a working
      feature from before this phase that this phase's own endpoint-contract
      change silently broke and never re-wired. Compounding this: `TransactionOut`
      (backend/schemas.py) still exposes only the legacy `category` string, not
      `category_id` or a hierarchy-derived name, so the transaction list also has
      no read path onto the new hierarchy. The "+ New category…" free-text
      affordance is now doubly misleading: typing a brand-new name does not
      create a Category row — `resolve_category_id` (plan 11-05) only exact-matches
      existing `categories.name` rows and silently resolves anything else to
      Uncategorized, so the transaction is filed as Uncategorized while the UI
      still shows the user's typed string via the legacy column.
    artifacts:
      - path: "ui/app/cashflow/TransactionModal.tsx"
        issue: >
          Line ~97: `const data: { categories: string[] } = await r.json();` —
          consumes a response shape that no longer exists after 11-03's
          `GET /categories` change (`response_model=list[CategoryNode]`, a bare
          array). `setCategories(data.categories ?? [])` always resolves to `[]`.
          File was never modified by any of the phase's 7 plans.
      - path: "backend/schemas.py"
        issue: >
          `TransactionOut` (line ~35) exposes `category: str | None` (the legacy
          free-text column) but no `category_id` or hierarchy-derived name —
          the transaction list has no read path onto the new hierarchy either.
    missing:
      - "Update TransactionModal.tsx to consume the actual list[CategoryNode] shape (flatten the tree into selectable name options, at minimum) so users can select an existing category when adding/editing a transaction — this restores parity with pre-phase behavior without requiring the full searchable grouped-list picker (D-15), which remains legitimately deferred to Phase 16."
      - "Decide and document what the '+ New category…' affordance should do now that categories are hierarchy rows, not implicit free strings (e.g., disable it, or route it through POST /categories at a chosen parent) — as currently wired it silently mis-files new-category attempts into Uncategorized while displaying the typed string, which contradicts the never-fabricate principle."
deferred:
  - truth: "Filters read from the new category hierarchy (ROADMAP criterion 4 — filters clause)"
    addressed_in: "Phase 17"
    evidence: "Phase 17 goal: 'The user can browse, filter, and bulk-manage their full transaction history...'; Success Criterion 2: 'User can filter records by search, account, category, record type, amount range, and transfer visibility.' No category filter UI exists anywhere in the codebase today (pre- or post-phase 11) — confirmed by grep across ui/app; this was never phase 11's job per 11-RESEARCH.md's Architectural Responsibility Map ('Category picker (record forms, filters) ... Out of full-build scope this phase ... record modal is Phase 16')."
human_verification:
  - test: "Settings > Categories: expand/collapse groups, add/edit/delete a category, trigger the block-or-reassign flow on a category with transactions and one with subcategories, confirm system-row (Transfer/Uncategorized) delete is disabled"
    expected: "Tree renders per 11-UI-SPEC Component 1; reassign flow shows both affected_count and child_count per the 422 payload; system rows show the exact copy 'System category — can't be deleted.'"
    why_human: "Visual layout, hover-reveal interactions, and modal flows require a live browser render; 11-06's own SUMMARY explicitly deferred this to phase UAT after docker compose up -d --build (shared host-network container stack, not rebuilt mid-wave)."
  - test: "Cashflow dashboard donut: confirm top-level slices use identity-stable swatch colors, click a slice with children to drill into its subcategories, confirm the '‹ Back' link returns to the rollup, and confirm no 'Transfer' slice ever appears"
    expected: "Rollup/drill-down/back per 11-UI-SPEC Component 3; Transfer absent at both levels"
    why_human: "11-07's own SUMMARY marks this coverage item `human_judgment: true` — tsc only proves the types compile, not that the chart looks/behaves right; deferred to phase UAT."
---

# Phase 11: Category Hierarchy — Schema, Audit, Migration Verification Report

**Phase Goal:** Categories exist as first-class, hierarchical entities that every existing transaction is correctly mapped onto, with zero data loss.
**Verified:** 2026-07-19T15:29:09Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Every one of the 74 existing category strings maps to a reviewed category in a 3-level hierarchy — no transaction silently loses its category | ✓ VERIFIED | `alembic/data/category_mapping.csv` has exactly 74 data rows across the 12 groups used (`Communication / PC, Financial Expenses, Food & Drinks, Housing, Income, Investments, Life & Entertainment, Others, Shopping, Transfer, Transportation, Vehicle`). Live DB: `alembic_version = e5f6a7b8c9d0` (head); `SELECT COUNT(*) FROM transactions WHERE category_id IS NULL` → **0** (independently re-queried, read-only). Migration file (`alembic/versions/009_category_hierarchy.py`) contains real `find_unmapped`/`RuntimeError` abort-on-unknown logic (not vestigial — confirmed by grep of the actual `upgrade()` body). |
| 2 | Row-count and sum-of-amount parity holds between pre- and post-migration category totals (verified, not assumed) | ✓ VERIFIED | Independently re-queried live DB (read-only, this session): `COUNT(*), SUM(amount)` = **5728, 194694800.00** — matches 11-02-SUMMARY's recorded pre-migration snapshot exactly. `assert_parity()` (raises `RuntimeError` naming the exact string + both count/sum pairs on mismatch) is present in the migration and covered by unit tests (`test_assert_parity_passes_when_equal`, `test_assert_parity_raises_on_mismatch...`). TRANSFER→Transfer count independently re-verified: **668** (matches). `raw_category IS NULL` count independently re-verified: **14** (matches, D-08 untouched). |
| 3 | User can add, edit, and delete categories in Settings; deleting a category with records in use is blocked until reassigned (no orphaned records) | ✓ VERIFIED | `ui/app/settings/page.tsx` imports and mounts `CategoryManager` (687 lines) inside a "Categories" card; old `ui/app/cashflow/CategoryManager.tsx` confirmed deleted. Backend: `POST/PUT/DELETE /categories` all carry `Depends(require_api_key)` + `reset_engine()` (grep-verified against the actual handler bodies, not just the SUMMARY's claim). Delete guard (`backend/main.py` ~L843-864): reads `child_count` and unconditionally blocks any category with subcategories (422), and `affected_count` for a childless category with transactions (422) — matches 28 tests in `test_category_hierarchy.py`. System rows (`is_system`) rejected on delete/rename in `writes.py` (`_category_depth`, `is_system` guard checks at L501, L560, L601, L635). Live visual walkthrough of the tree UI is deferred to human UAT (see Human Verification). |
| 4 | Record forms, filters, and dashboard charts read from the new category hierarchy (not the free-string column) | ✗ FAILED (partial) | **Dashboard charts: VERIFIED** — `CashflowSummary.by_category` is `list[CategoryRollup]` (`backend/schemas.py`), sourced from `spending_by_category`'s hierarchy join (Transfer/system excluded server-side, grep-confirmed at `tools.py` L241-242); `CategoryDonut.tsx` renders identity-stable colors + a "‹ Back" drill-down affordance (grep-confirmed). **Filters: legitimately DEFERRED** to Phase 17 (see Deferred Items) — no category-filter UI exists anywhere in the codebase, and this was never phase 11's job per 11-RESEARCH.md. **Record forms: FAILED** — see Gaps below. TransactionModal.tsx (the live Add/Edit Transaction modal) was never updated for 11-03's `GET /categories` contract change and is now functionally broken for category selection. |

**Score:** 3/4 roadmap truths verified (1 failed — see Gaps)

### Deferred Items

| # | Item | Addressed In | Evidence |
|---|------|-------------|----------|
| 1 | Filters read from the new category hierarchy | Phase 17 | Phase 17 success criterion 2: "User can filter records by search, account, category, record type, amount range, and transfer visibility." No filter UI exists today; 11-RESEARCH.md's Architectural Responsibility Map explicitly scopes the category picker (record forms, filters) build out of phase 11. |

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/models.py` | `Category` model + `Transaction.category_id` | ✓ VERIFIED | `class Category` present; import check confirms `Category.__tablename__ == "categories"`; pre-migration ORM shim (deferred/server_default/eager_defaults) confirmed removed per 11-05. |
| `alembic/versions/009_category_hierarchy.py` | Idempotent schema+data migration, testable helpers | ✓ VERIFIED | `load_mapping`, `find_unmapped`, `assert_parity`, `kind_for_group`, `GROUP_META` all present; `upgrade()` body contains real abort/parity/zero-NULL assertions (not stubs). |
| `alembic/data/category_mapping.csv` | 74-key human-reviewed mapping | ✓ VERIFIED | Exactly 74 data rows, keyed by exact raw strings, 12 groups used, matches live DB's distinct-category-string set. |
| `backend/writes.py` | Audited category write layer | ✓ VERIFIED | `apply_add_category`, `apply_edit_category`, `apply_delete_category`, reworked `apply_rename_category`/`apply_merge_category`, `resolve_category_id`, `_category_depth` all present and grep-confirmed. |
| `backend/main.py` | Category CRUD + hierarchy-aware summary | ✓ VERIFIED | `GET/POST/PUT/DELETE /categories`, `/categories/{name}/affected-count`, `/categories/rename`, `/categories/merge` all present with correct auth/cache-invalidation wiring. |
| `backend/schemas.py` | `CategoryNode`/`CategoryCreate`/`CategoryUpdate`/`CategoryRollup`/`CategoryRollupChild` | ✓ VERIFIED | All classes present (grep-confirmed at their declared line numbers). |
| `backend/tools.py` / `backend/query.py` | Hierarchy-aware agent tools, dual registration | ✓ VERIFIED | `registry OK 26` (15 read + 11 write, unchanged); `list_categories`/`spending_by_category` in `READ_TOOL_NAMES`; no `propose_*` leaked onto the read surface (executed the actual assertion script, not just trusted the SUMMARY). |
| `ui/app/settings/CategoryManager.tsx` | Recursive tree manager with CRUD + delete-guard flows | ✓ VERIFIED | 687 lines; fetches `/api/categories`; mounted in `ui/app/settings/page.tsx`. `ui/app/cashflow/CategoryManager.tsx` confirmed deleted (no dangling references). |
| `ui/app/cashflow/charts/CategoryDonut.tsx` | Rollup + drill-down donut, identity colors | ✓ VERIFIED | Contains `drilled` state, `‹ Back` text, click-to-drill logic (grep-confirmed). |
| `ui/app/cashflow/TransactionModal.tsx` | (not a phase-11 artifact, but a consumer of a phase-11-changed contract) | ✗ HOLLOW (regressed) | Fetches `GET /categories` expecting the old `{categories: string[]}` shape; now always resolves to an empty list. See Gaps. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `alembic/versions/009_category_hierarchy.py` | `alembic/data/category_mapping.csv` | `load_mapping` reads CSV relative to migration file | ✓ WIRED | Migration ran successfully against the live DB per 11-02-SUMMARY and independently re-verified DB state. |
| `backend/tests/test_category_migration.py` | `alembic/versions/009_category_hierarchy.py` | `importlib.util.spec_from_file_location` | ✓ WIRED | Full suite run this session: these tests pass as part of the 236-passed total. |
| `backend/main.py` | `backend/writes.py` | `apply_*_category` helpers, `ValueError` → 422 | ✓ WIRED | Grep-confirmed handler bodies call the helpers; guard tests pass. |
| `backend/main.py` | `backend/query.py` | `reset_engine()` after every category mutation commit | ✓ WIRED | Confirmed on all 5 mutating category endpoints. |
| `backend/tools.py` | `backend/query.py` | Dual registration (`FunctionTool.from_defaults`) | ✓ WIRED | Registry assertion executed directly: `registry OK 26`. |
| `ui/app/settings/CategoryManager.tsx` | `backend/main.py GET /categories` | fetch of the tree | ✓ WIRED | Correctly consumes `list[CategoryNode]` (built for this exact shape in 11-06). |
| `ui/app/cashflow/page.tsx` | `ui/app/cashflow/charts/CategoryDonut.tsx` | `summary.by_category` objects → donut | ✓ WIRED | `CategoryRollup[]` typed and passed through, grep-confirmed. |
| `ui/app/cashflow/TransactionModal.tsx` | `backend/main.py GET /categories` | fetch expecting `{categories: string[]}` | ✗ NOT_WIRED | Endpoint shape changed in 11-03 to `list[CategoryNode]`; consumer never updated. This is the core of the Gap below. |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full backend test suite | `pytest backend/tests -q` (run once, live) | `236 passed, 1 failed` (pre-existing `test_settings.py::test_put_settings_requires_key`, documented in `deferred-items.md`, verified failing at base commit before any phase-11 work) | ✓ PASS (no regression) |
| Category mapping CSV coverage | Python one-liner counting rows | `74 data rows` | ✓ PASS |
| Category registry invariants | `python -c "from backend.tools import TOOLS, READ_TOOL_NAMES; ..."` | `registry OK 26` | ✓ PASS |
| Frontend typecheck | `cd ui && npx tsc --noEmit` | clean, 0 errors | ✓ PASS (does not catch the runtime shape-mismatch bug below — `r.json()` is `any`) |
| Live DB zero-NULL / parity | `psql` read-only queries (independently re-run this session) | `category_id IS NULL` = 0; `COUNT/SUM` = 5728/194694800.00; Transfer rows = 668; `raw_category IS NULL` = 14 | ✓ PASS — all match the SUMMARY's claimed figures |

### Requirements Coverage

| Requirement | Source Plan(s) | Description | Status | Evidence |
|-------------|-----------------|-------------|--------|----------|
| CAT-01 | 11-01, 11-03 | Categories are first-class entities (name, color, icon, parent) with up to 3 hierarchy levels | ✓ SATISFIED | `Category` model + depth-cap enforcement (`_category_depth`, blocked at depth ≥ 3) verified in code. |
| CAT-02 | 11-03, 11-06 | User can manage categories in Settings — add, edit, delete with a block-or-reassign guard | ✓ SATISFIED | Settings tree manager + backend guard both verified; live visual walkthrough deferred to human UAT. |
| CAT-03 | 11-01, 11-02, 11-05 | 74 category strings migrate onto the hierarchy via human-reviewed mapping with row/sum parity checks | ✓ SATISFIED | Migration ran, parity independently re-verified this session, dual-write on all 4 write paths confirmed. |
| CAT-04 | 11-04, 11-06, 11-07 | Record forms, filters, and dashboard charts use the hierarchical category picker | ✗ BLOCKED | Dashboard charts and the agent/chat tool layer are hierarchy-backed (verified). Record forms are **regressed** (TransactionModal.tsx broken by the 11-03 contract change). Filters are deferred to Phase 17 (documented, not a phase-11 gap). |

No orphaned requirements found — all four CAT-0x IDs are claimed and accounted for across the phase's 7 plans.

### Anti-Patterns Found

No `TODO`/`FIXME`/`XXX`/`HACK`/placeholder debt markers found in any phase-11-modified backend or frontend file (scanned: `models.py`, `009_category_hierarchy.py`, `writes.py`, `schemas.py`, `main.py`, `tools.py`, `query.py`, `importer.py`, `styles.ts`, `CategoryManager.tsx`, `settings/page.tsx`, `cashflow/page.tsx`, `CategoryDonut.tsx`, `category_mapping.csv`). The `placeholder="..."` hits found are legitimate HTML input placeholder attributes, not stub markers.

**Live-DB housekeeping note (not a blocker):** the live dev database currently has **119** rows in `categories`, not the 76 the phase's summaries describe (13 roots + 63 subcategories). The extra 43 rows are leftover randomized-name fixtures from earlier `test_category_hierarchy.py` runs (e.g. `DepthRoot-67e4936e`, `DupParent-edc1dce1`) that were not cleaned up in some prior session. Re-running the full suite this session did **not** add further orphans (confirmed: count unchanged at 119 before/after), and zero transactions reference any of these 43 rows — so the "zero data loss" and parity claims for real transaction data are unaffected. However, these rows are real, visible nodes and would currently clutter the Settings > Categories tree for the actual user. Recommend a one-time manual cleanup (`DELETE FROM categories WHERE id > 76`, after confirming no legitimate categories were added above id 76) before/at milestone close.

## Gaps Summary

Phase 11 delivers a solid, well-tested backend and migration core: the Category model, the 009 migration (idempotent, parity-asserting, abort-on-unknown), the 74-string human-reviewed mapping, the Settings tree manager, the hierarchy-aware agent tools, universal dual-write, and the dashboard donut rollup/drill-down are all real, wired, and independently confirmed against the live database and codebase — not just SUMMARY claims. Truths 1-3 and the dashboard-charts portion of truth 4 hold up under adversarial re-checking.

The one confirmed gap is narrow but real: **plan 11-03 changed `GET /categories`'s response contract** (from `{"categories": [string, ...]}` to a bare `list[CategoryNode]` tree) **to serve the new Settings tree manager, but no plan in the phase noticed or updated the other live consumer of that same endpoint** — `ui/app/cashflow/TransactionModal.tsx`, the Add/Edit Transaction modal actually mounted and used on the Cashflow page today. The result is a silent regression: the category `<select>` in that modal is now always empty of real categories. This is distinct from the legitimately-deferred Phase 16/17 work (the fancy searchable grouped-list picker, and record filtering) — it is a currently-broken piece of previously-working functionality that this phase's own change caused, sitting on the phase's own touched surface (`GET /categories`), and it should be closed before the phase is considered complete rather than carried forward silently.

---

_Verified: 2026-07-19T15:29:09Z_
_Verifier: Claude (gsd-verifier)_
