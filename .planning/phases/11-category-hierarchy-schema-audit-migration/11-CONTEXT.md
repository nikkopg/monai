# Phase 11: Category Hierarchy — Schema, Audit, Migration - Context

**Gathered:** 2026-07-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Categories become first-class, hierarchical entities (name, color, icon, parent, expense/income type; ≤3 levels) with a management UI in Settings. Every one of the 74 existing free-string categories on 5,608 live transactions migrates onto the hierarchy via a human-reviewed mapping with row-count and sum-of-amount parity checks — zero data loss. Record forms, filters, and dashboard charts switch to reading the hierarchy. Requirements: CAT-01, CAT-02, CAT-03, CAT-04.

Out of this phase: transfer pairing mechanics (Phase 13 — but the system "Transfer" category node is created here), typed accounts (Phase 12), Records tab and full category-tree UI polish (Phase 17), Need/Want classification and hide toggle (deferred CAT-F1/F2), the destructive drop of the legacy `category` column (separate later migration).

</domain>

<decisions>
## Implementation Decisions

### Hierarchy shape & assignment
- **D-01:** Records are assignable to a category at ANY level (parent or leaf), BudgetBakers-style. No artificial "General" leaves.
- **D-02:** The 74 existing strings nest under BudgetBakers' standard top-level groups (Food & Drinks, Shopping, Housing, Transportation, Vehicle, Life & Entertainment, Communication/PC, Financial Expenses, Investments, Income, Others).
- **D-03:** Categories are typed expense vs income (carried at the top-level group, inherited down). Pickers filter by record type — the Income form shows only income categories.
- **D-04:** No NULL categories remain after migration: NULL-category records map to a real, visible "Uncategorized" category. A system "Transfer" category is created now so Phase 13's transfer legs have a home.

### Mapping review workflow
- **D-05:** Claude drafts a checked-in mapping file (YAML/CSV: 74 strings → group + subcategory + emoji + color) and additionally walks the user through ONLY the ambiguous strings in chat before finalizing.
- **D-06:** The review happens at an execution checkpoint — the executor drafts the mapping mid-phase, pauses for user review/edits, then runs the migration.
- **D-07:** Migration aborts loudly if it encounters any category string not in the reviewed mapping — unmatched strings listed, nothing partially migrated, re-runnable (idempotent).
- **D-08:** Dual-write until drop: after migration, new/edited records write BOTH `category_id` and the legacy `category` string (derived from category name). `raw_category` stays untouched forever as import provenance. The column drop is a separate later migration (per CAT-03).

### Chart & filter rollup behavior
- **D-09:** Dashboard category charts (donut, by-category totals) roll up to the ~11 top-level groups with drill-down into subcategories.
- **D-10:** Agent/chat tools become hierarchy-aware: `spending_by_category` / `spending_in_category` treat a parent name as including all descendants; `list_categories` returns the tree.
- **D-11:** Existing rename/merge surfaces are reworked onto the hierarchy — rename edits the category row (records follow via FK, no bulk UPDATE); merge reassigns records to the target then deletes the source row. Existing endpoints, agent propose_* tools, and UI keep working, now hierarchy-backed.
- **D-12:** The system "Transfer" category is excluded from spending/income totals and charts (moving money isn't spending); transfer records stay visible in record lists and filters.

### Colors, icons & picker style
- **D-13:** Icons are emoji stored as text — zero dependencies; Claude pre-assigns sensible defaults in the mapping draft.
- **D-14:** Colors come from a curated swatch palette derived from the paper token layer (`ui/app/styles.ts`); subcategories inherit the parent's color by default, individually overridable.
- **D-15:** The category picker in record forms and filters is a searchable grouped list — dropdown/popover with top-group headers, indented children, type-to-filter.
- **D-16:** Settings > Categories manager is an expandable tree (top groups collapsed by default, inline add/edit/delete per node). Delete triggers the block-or-reassign guard (CAT-02). The existing `CategoryManager` moves from Cashflow to Settings.

### Claude's Discretion
- Exact schema details (FK naming, index choices, depth enforcement mechanism for the 3-level cap, how expense/income typing is stored).
- Migration internals (Alembic revision structure, parity-report format, idempotency mechanism), consistent with the abort-loudly and parity-check decisions above.
- Which of the 74 strings count as "ambiguous" for the chat walkthrough.
- Emoji/color defaults in the mapping draft (user reviews them anyway).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & roadmap
- `.planning/REQUIREMENTS.md` — CAT-01..04 definitions, out-of-scope table (no live-FX, no labels), deferred CAT-F1/F2
- `.planning/ROADMAP.md` — Phase 11 goal, success criteria (74-string parity, block-or-reassign delete guard), research flag
- `.planning/PROJECT.md` — constraints (never-fabricate, migration story requirement, IDR-only spending)

### Migration precedent
- `alembic/versions/` — migrations 001–008 exist at repo root (NOT backend/); Phase 11's migration is 009. Follow the established revision idiom.

### Reference product behavior
- BudgetBakers Wallet web app (Settings > Categories, Add-record modal) — captured live 2026-07-18, per PROJECT.md/REQUIREMENTS.md header. Any-level assignment, parent-color inheritance, and transfer exclusion mirror this reference.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `transactions.raw_category` (`backend/models.py:84`) — original import string preserved on every row; the migration safety net. Never modified.
- `apply_rename_category` / `apply_merge_category` (`backend/writes.py:362,373`) — existing audit-logged write layer to rework onto the hierarchy (D-11).
- `ui/app/cashflow/CategoryManager.tsx` — existing rename/merge UI; moves to Settings and grows into the tree manager (D-16).
- `ui/app/cashflow/charts/CategoryDonut.tsx` — donut to rewire for top-level rollup + drill-down (D-09).
- `ui/app/styles.ts` — paper token layer; source for the curated category palette (D-14).

### Established Patterns
- Alembic migrations 001–008 at repo-root `alembic/versions/`; PROJECT.md mandates non-destructive migrations on live data.
- Correctness-by-construction: LLM never emits SQL; category tools are parameterized (`backend/tools.py`: `spending_by_category` L169, `spending_in_category` L188, `list_categories` L400, `propose_rename_category` L805, `propose_merge_category` L828).
- **Dual-registration gotcha:** any changed/new agent tool must be updated in BOTH `tools.py` TOOLS and `query.py`'s FunctionTool list; keep write tools off the MCP read-only surface (`READ_TOOL_NAMES`).
- Confirm-before-write proposal flow + audit log for all agent mutations.

### Integration Points
- `backend/main.py` — `GET /categories`, `GET /categories/{name}/affected-count`, `POST /categories/rename`, `POST /categories/merge` (L663–699) all query the free-string column today; they re-point at the hierarchy.
- `spending_by_category` feeds `CashflowSummary` (`backend/main.py:581`) — rollup change flows through here to the dashboard.
- Deploy note: committed code ≠ running container; `docker compose up -d --build` before any live verification (prior-phase lesson).

</code_context>

<specifics>
## Specific Ideas

- "Like BudgetBakers" is the recurring anchor: any-level assignment, standard top groups, subcategories inheriting parent color, transfers excluded from spending, Settings > Categories tree.
- User asked "migration from where to where?" — confirm the plan states plainly: in-database Alembic data migration (free-string `transactions.category` → `categories` table + `transactions.category_id` FK), nothing leaves PostgreSQL.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope. (CAT-F1 Need/Want and CAT-F2 hide toggle were already deferred at requirements time; nothing new emerged.)

</deferred>

---

*Phase: 11-Category Hierarchy — Schema, Audit, Migration*
*Context gathered: 2026-07-18*
