# Phase 11: Category Hierarchy — Schema, Audit, Migration - Research

**Researched:** 2026-07-18
**Domain:** Self-referential hierarchy schema + idempotent Alembic data migration (PostgreSQL/SQLAlchemy), Settings CRUD UI, agent tool hierarchy-awareness
**Confidence:** HIGH

## Summary

This phase has no exotic technology — it is 100% "use what's already in this repo, correctly." The
project already has the exact migration idiom needed (migration `006_multi_platform_holdings.py`:
nullable column → backfill via `op.execute(UPDATE...)` → NOT NULL → FK + index), the exact
block-or-reassign delete-guard pattern needed (`DELETE /accounts/{id}?reassign_to=`, 404/422/200
three-way branch, `apply_delete_account`-style audited helper), and the exact dual-registration
tool-surface convention needed (`TOOLS` dict + `query.py` `FunctionTool` list + `READ_TOOL_NAMES`
frozenset snapshot). Nothing here calls for a new dependency: emoji-as-text icons, a curated
palette already in `ui/app/styles.ts`, a self-referential FK for the hierarchy, and a ~100-row
tree that a plain recursive React component renders trivially.

The one genuinely new mechanic is the **data migration** itself: 5,728 live transactions across 74
distinct category strings must move onto a real `categories` table via a human-reviewed mapping,
with the migration aborting loudly on any unmapped string and asserting row-count + sum-of-amount
parity before it lets a `db.commit()` land. Live-DB inspection (see Runtime State Inventory) found
a real landmine for the mapping file: one of the 74 raw strings is a whitespace-variant duplicate
(`"Active sport, fitness"` at 133 rows vs `" Active sport, fitness"` with a leading space at 2 rows)
— the mapping must key by exact raw string (74 keys) even though two of them resolve to the same
category node. Also found: `category = 'TRANSFER'` aligns 1:1 with `is_transfer = true` (668/668
rows both ways) — the system "Transfer" category can absorb this string directly, no ambiguity.
There are currently zero NULL-category rows, so D-04's "Uncategorized" catch-all is forward-looking
insurance (future null-category inserts), not a backfill target today.

**Primary recommendation:** Reuse `006_multi_platform_holdings.py`'s nullable→backfill→NOT-NULL
idiom for the schema half of the migration; drive the data half from a checked-in CSV mapping file
(stdlib `csv`, no new dependency — the project has no YAML lib today) consumed by a Python-side
migration step that raises loudly on any transaction whose `category` string isn't a mapping key,
and asserts `COUNT(*)`/`SUM(amount)` parity per category before vs. after as its last step.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Category hierarchy storage (self-referential table) | Database / Storage | — | New `categories` table + FK; single source of truth |
| 74-string → hierarchy mapping (human review) | — (human/CLI artifact) | API/Backend consumes it | Not automatable per roadmap flag; lives as a checked-in file, read by the migration |
| Data migration (backfill `transactions.category_id`) | Database / Storage | API/Backend (Alembic runs via backend's Python env) | Alembic `op.execute` + Python-side row loop, executed against live Postgres |
| Category CRUD (add/edit/delete + block-or-reassign) | API/Backend | Browser/Client (Settings tree UI) | Mirrors existing `Account` CRUD precedent exactly (`main.py` L202-270) |
| Rename/merge (existing agent + REST surfaces) | API/Backend | Browser/Client, Agent tool | D-11: rework onto hierarchy, keep both REST and `propose_*` agent tools working |
| Dashboard rollup (top-group + drill-down) | API/Backend | Browser/Client (chart rendering) | Rollup aggregation belongs in SQL (`spending_by_category`), rendering in `CategoryDonut` |
| Category picker (record forms, filters) | Browser/Client | API/Backend (`GET /categories` tree endpoint) | Out of full-build scope this phase (record modal is Phase 16) — this phase only needs the *data source* to be hierarchy-shaped |
| Dual-write (`category_id` + legacy `category` string) | API/Backend | Database / Storage (constraint-free, app-enforced) | D-08: derived at write time from category name; no DB trigger needed at this scale |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| SQLAlchemy | >=2.0.0 (already pinned) | Self-referential `Category` ORM model, `parent_id` FK | Already the project's only ORM; no reason to add anything |
| Alembic | >=1.13.0 (already pinned) | Schema DDL + data migration, revision 009 | Established idiom in `alembic/versions/006_multi_platform_holdings.py` |
| psycopg[binary] | >=3.1.0 (already pinned) | Postgres driver | No change |
| Python stdlib `csv` | 3.12+ (stdlib) | Parse the 74-string mapping file | Zero new dependency; project has no YAML lib today `[VERIFIED: backend/requirements.txt has no pyyaml/ruamel entry]` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| None | — | — | This phase adds no new runtime dependency — everything is stdlib, existing SQLAlchemy/Alembic, and hand-rolled React |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| CSV mapping file | YAML mapping file | YAML reads slightly nicer for nested group/subcategory/emoji/color, but requires adding `pyyaml` as a new dependency for a single migration-time read — CSV with columns `raw_string,group,subcategory,emoji,color` does the same job with stdlib only. Recommend CSV unless the user strongly prefers YAML for hand-editing during the D-06 review checkpoint. |
| Recursive CTE for rollup queries | Materialized path / closure table | At ~100 rows and 3-level depth cap, a recursive CTE (or even a plain 2-join since depth ≤3) is simpler to write and index-free to maintain. Materialized path adds write-time bookkeeping (path string rebuilds on re-parent) that buys nothing at this scale. |
| Hand-rolled expand/collapse tree component | `react-arborist` / similar tree library | ~11 top groups × a handful of children each is a trivial recursive `<TreeNode>` component with local `useState` for expand/collapse — a tree library is justified at thousands of nodes, not ~100. `ui/package.json` has no tree lib installed today `[VERIFIED: grep of ui/package.json]`. |

**Installation:** None — no `pip install` / `npm install` needed for this phase.

**Version verification:** All versions above are already pinned and installed in this repo
(`backend/requirements.txt`, `ui/package-lock.json`); no new package versions to verify.

## Package Legitimacy Audit

**This phase installs no new external packages.** Every capability (self-referential FK, CSV
parsing, recursive tree rendering, curated color palette) is covered by dependencies already
present in `backend/requirements.txt` / `ui/package.json`, or by the language stdlib. The Package
Legitimacy Gate is not applicable — table omitted per the "no packages installed" condition.

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
                    ┌─────────────────────────────┐
                    │  74-string mapping.csv       │
                    │  (human-reviewed, checked in) │
                    └───────────────┬─────────────┘
                                    │ read at migration time
                                    ▼
  ┌──────────────┐     ┌────────────────────────────┐     ┌───────────────────┐
  │ transactions │────▶│ Alembic rev 009 upgrade()   │────▶│ categories (new)   │
  │ .category    │     │  1. create categories table │     │  id, name, parent_id│
  │ (74 strings) │     │  2. seed rows from CSV      │     │  color, icon, type  │
  │ 5,728 rows   │     │  3. add category_id (null)  │     └───────────────────┘
  └──────────────┘     │  4. backfill category_id     │
                        │     per raw string→node      │
                        │     ABORT if any string not   │
                        │     in mapping (D-07)          │
                        │  5. assert row+sum parity      │
                        │     per category (pre vs post) │
                        │  6. category_id -> NOT NULL     │
                        │     (or leave nullable + FK,    │
                        │      see Pitfall 2)              │
                        └────────────┬────────────────────┘
                                     │
                                     ▼
                   ┌───────────────────────────────────┐
                   │ backend/tools.py (hierarchy-aware) │
                   │  spending_by_category — rolls up   │
                   │  to top-group, excludes Transfer   │
                   │  list_categories — returns tree     │
                   └───────────────┬────────────────────┘
                                    │
                    ┌───────────────┼────────────────────┐
                    ▼               ▼                     ▼
        backend/main.py     ui/app/settings/       ui/app/cashflow/
        GET /categories      CategoryManager.tsx     CategoryDonut.tsx
        (tree, hierarchy-    (moved from cashflow,    (top-group rollup +
         backed)             tree CRUD + block-or-    drill-down)
                             reassign delete guard)
```

### Recommended Project Structure
```
alembic/versions/
└── 009_category_hierarchy.py     # schema + seeded rows + backfill + parity assert

backend/
├── models.py          # + Category ORM model (self-referential)
├── tools.py            # spending_by_category/spending_in_category/list_categories
│                        #   rewritten hierarchy-aware; propose_rename/merge_category
│                        #   rewritten onto hierarchy (D-11)
├── writes.py            # apply_rename_category / apply_merge_category rewritten;
│                        #   + apply_add_category / apply_edit_category /
│                        #   apply_delete_category (mirrors apply_delete_account)
└── main.py              # /categories endpoints extended: POST/PUT/DELETE
                          #   (direct CRUD, mirrors /accounts CRUD — see Pitfall 4)

data/ (or scripts/, project's choice — pick one location)
└── category_mapping.csv  # 74 rows: raw_category,group,subcategory,emoji,color
                           #   checked into git — the human-reviewed artifact (D-05/D-06)

ui/app/
├── settings/
│   └── CategoryManager.tsx   # moved from cashflow/, grows into expandable tree (D-16)
└── cashflow/
    └── charts/CategoryDonut.tsx  # rollup + drill-down (D-09)
```

### Pattern 1: Self-referential hierarchy with depth cap enforced at write time, not DDL
**What:** `Category` table with `parent_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True, index=True)`. The 3-level cap (D-01/CAT-01) is enforced in the `apply_add_category`/`apply_edit_category` write helpers (walk `parent_id` chain, reject if depth would exceed 3) — not as a CHECK constraint or trigger, because Postgres cannot cheaply enforce "no more than N levels of self-reference" declaratively without a recursive CHECK (not supported) or a trigger (more moving parts than a single Python guard for a single-user app).
**When to use:** Any small (~100-row), rarely-mutated hierarchy where the app is the only writer.
**Example:**
```python
# Source: pattern derived from existing backend/models.py conventions (Platform/Account shape)
class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # 'expense' | 'income'
    color: Mapped[str | None] = mapped_column(String(16), nullable=True)  # hex, nullable = inherit parent's
    icon: Mapped[str | None] = mapped_column(String(8), nullable=True)  # emoji as text
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)  # True for "Transfer", "Uncategorized"

    __table_args__ = (
        UniqueConstraint("name", "parent_id", name="uq_categories_name_parent"),
    )
```

### Pattern 2: Nullable → backfill → NOT NULL (established idiom, verified in this repo)
**What:** Add `transactions.category_id` as nullable, backfill via a single `op.execute(UPDATE...)` driven by a temp mapping table (or per-row Python loop for parity-checking), only then tighten to NOT NULL + FK + index — in that exact order.
**When to use:** Any migration adding a required FK to a table with existing live data (this is the project's only precedent and it matches this phase's shape exactly).
**Example:**
```python
# Source: alembic/versions/006_multi_platform_holdings.py (verified in this repo, lines 42-83)
def upgrade() -> None:
    # 1. Nullable first.
    op.add_column("transactions", sa.Column("category_id", sa.Integer(), nullable=True))
    # 2. Backfill (see Pitfall 1 for why this needs Python, not a single SQL UPDATE).
    # 3. Lock down.
    op.alter_column("transactions", "category_id", nullable=False)
    op.create_foreign_key(
        "fk_transactions_category", "transactions", "categories",
        ["category_id"], ["id"],
    )
    op.create_index("ix_transactions_category_id", "transactions", ["category_id"])
```

### Pattern 3: Block-or-reassign delete guard (established idiom, verified in this repo)
**What:** `DELETE /categories/{id}?reassign_to=<id>` — no `reassign_to` + records exist → `422` with `{"detail": {"affected_count": N}}`; `reassign_to` provided → reassign then delete in one audited helper call; no records → plain audited delete.
**When to use:** Exactly CAT-02's "block-or-reassign guard." This is not a new pattern to design — it is a direct copy of `DELETE /accounts/{account_id}` (`backend/main.py:236-270`) and `AccountManager.tsx`'s 422-handling reassign-picker UI flow (`ui/app/cashflow/AccountManager.tsx:100-131`).
**Example:**
```python
# Source: backend/main.py:236-270 (verified in this repo) — adapt account_id -> category_id,
# accounts -> categories, transactions.account_id -> transactions.category_id
@app.delete("/categories/{category_id}", dependencies=[Depends(require_api_key)])
def delete_category(category_id: int, reassign_to: int | None = None, db: Session = Depends(get_session)):
    cat = db.get(Category, category_id)
    if cat is None:
        raise HTTPException(status_code=404, detail=f"Category {category_id} not found")
    # also block if cat has CHILD categories (parent delete needs child reassignment too —
    # new consideration beyond the account precedent, see Common Pitfalls)
    tx_count = int(db.execute(text("SELECT COUNT(*) FROM transactions WHERE category_id = :cid"),
                               {"cid": category_id}).scalar() or 0)
    if tx_count and reassign_to is None:
        raise HTTPException(status_code=422, detail={"affected_count": tx_count})
    # ... apply_delete_category(db, category_id, reassign_to) — single audited helper
```

### Pattern 4: Hierarchy-aware read tools (parent name includes descendants)
**What:** `spending_by_category`/`spending_in_category`/`list_categories` currently do exact/substring string matching on the free-text `category` column. Rewritten versions join `transactions.category_id -> categories` and, for a parent-level query, must include all descendant category ids (recursive CTE or a precomputed id-list from an in-Python tree walk — at ~100 rows, either is fine; recommend the Python walk since `list_categories()` already needs to build the full tree for its own return shape, so descendant-id resolution is "free" reuse of that same tree).
**When to use:** Every read tool in `backend/tools.py` that currently filters by `category` string.
**Example:**
```python
# Source: pattern — adapts backend/tools.py:169-208 (verified shape) to hierarchy joins
def spending_by_category(period="all_time", ..., limit=5) -> dict:
    s, e = resolve_period(period, start_date, end_date)
    sql = (
        "SELECT COALESCE(c.parent_id, c.id) AS top_id, "
        "       COALESCE(p.name, c.name) AS top_name, "
        "       SUM(-t.amount) AS total "
        "FROM transactions t JOIN categories c ON c.id = t.category_id "
        "LEFT JOIN categories p ON p.id = c.parent_id "
        "WHERE t.amount < 0 AND t.is_transfer = false AND NOT c.is_system"
        + _date_clause(s, e, p) +
        " GROUP BY 1, 2 ORDER BY total DESC LIMIT :lim"
    )
```

### Anti-Patterns to Avoid
- **Bulk `UPDATE transactions SET category = new_name`-style rename:** D-11 explicitly retires this — rename now edits the `categories.name` row once; every transaction follows via FK with zero rows touched. Do not port `apply_rename_category`'s current `UPDATE transactions SET category = :new WHERE category = :old` pattern forward; it becomes a single-row `UPDATE categories SET name = :new WHERE id = :id`.
- **CHECK constraint or recursive trigger for the 3-level depth cap:** over-engineered for a single-user, app-only-writer table. Enforce in the Python write helper instead (see Pattern 1).
- **Materialized path / nested-set model for the hierarchy:** solves a scale problem (fast subtree queries on 100k+ rows) this phase doesn't have. A recursive CTE or a Python-side one-time tree walk is simpler to write, debug, and keep correct at ~100 rows.
- **Single monolithic `UPDATE ... FROM mapping_table` for the data backfill:** unlike migration 006 (whose backfill source, `holdings`, was already a clean 1:1 join), this migration's correctness claim is "row-count and sum-of-amount parity, verified not assumed" (Success Criterion 2). A single opaque SQL UPDATE makes that assertion hard to write and hard to explain if it fails. Prefer a Python loop (or per-category `UPDATE ... WHERE category = :raw_string` issued once per of the 74 mapping rows) so the parity check can run per-category and name exactly which string failed.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Block-or-reassign delete guard | A new bespoke 3-state delete flow | Copy `DELETE /accounts/{id}` + `AccountManager.tsx`'s 422-handler verbatim, adapted | Already built, already tested, already has a matching UI pattern — CAT-02 is not a new problem |
| Alembic backfill idiom | A novel nullable/backfill/lock sequence | Copy `006_multi_platform_holdings.py`'s exact upgrade()/downgrade() ordering | Same shape: add nullable FK column → backfill → NOT NULL → FK + index; downgrade in strict reverse |
| Dual tool registration | Trusting one registration point | Checklist: `tools.py TOOLS` dict + `query.py` `FunctionTool.from_defaults()` list, and confirm write tools stay OUT of `READ_TOOL_NAMES` (captured as a `frozenset` snapshot BEFORE `TOOLS.update({...})` runs at line 962) | Documented prior incident (`chat-tool-dual-registration`, `TOOLS registry mutates to 26`) — a rewritten `list_categories`/`spending_by_category` that isn't re-registered in `query.py` silently keeps serving the agent stale (pre-hierarchy) behavior |
| Category tree rendering | A tree-view library | Plain recursive React component (expand/collapse via local `useState`, ~11 top nodes) | Scale doesn't justify a dependency; `ui/package.json` has none installed |

**Key insight:** Every hard part of this phase (delete guard, migration idiom, dual registration) is
already solved elsewhere in this codebase. The actual net-new work is the hierarchy shape itself and
threading it through the existing surfaces without breaking any of them — not inventing new
mechanics.

## Runtime State Inventory

> Rename/migration phase — the `category` string moves to a `category_id` FK. All 5 categories checked.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | 5,728 live `transactions` rows, 74 distinct `category` string values (73 after trimming whitespace — see Pitfall 1). `raw_category` has 14 NULLs (import-time gaps) but `category` has 0 NULLs. `category = 'TRANSFER'` aligns 1:1 with `is_transfer = true` (668 rows both ways) `[VERIFIED: live psql query against postgresql://monai:monai@localhost:5434/monai, 2026-07-18]`. | Data migration (backfill `category_id` per the 74-key mapping); `raw_category` stays untouched forever (D-08) |
| Live service config | None — no external service (n8n/Datadog-style) holds category state outside this Postgres instance. | None |
| OS-registered state | None — no OS-level task/service registers category names. | None |
| Secrets/env vars | None — no env var or SOPS key references category strings by name. | None |
| Build artifacts | None — no compiled artifact embeds the category strings; `alembic/versions/__pycache__` is a stale-bytecode non-issue (rebuilt on migration run). | None |

**Nothing found in 3 of 5 categories** — verified by direct grep/psql inspection rather than assumed.

## Common Pitfalls

### Pitfall 1: Whitespace-variant duplicate string collapses the "74 keys" assumption
**What goes wrong:** The mapping file is keyed by the 74 distinct raw `category` strings, but two of
those "distinct" strings are actually the same category with a stray leading space
(`"Active sport, fitness"` — 133 rows — vs `" Active sport, fitness"` — 2 rows). A naive
`SELECT DISTINCT category` used to build the mapping-review list is correct (produces exactly the
74 the roadmap counts), but a migration author who "cleans up" by trimming whitespace before
matching against the mapping will silently merge these two into one lookup and break the abort-on-
unknown check (D-07) — or, if the mapping is instead keyed by the trimmed string (73 keys), the
untrimmed variant will trigger a false "unknown category" abort.
**Why it happens:** Wallet CSV export apparently has an inconsistent leading space on at least one
row across the import history.
**How to avoid:** Key the mapping file by the exact raw string (no trimming) — 74 rows, with the
two whitespace variants of "Active sport, fitness" both present as separate rows mapping to the
same target category node. Match `transactions.category = :raw_string` exactly (no `TRIM()`,
no `ILIKE`) during backfill.
**Warning signs:** Migration's parity/abort step reports either 73 or 75 "distinct categories seen"
instead of the expected 74 — a mismatch here means whitespace or casing normalization crept in
somewhere in the pipeline.

### Pitfall 2: NOT NULL on `category_id` forecloses D-04's stated Uncategorized safety net for zero benefit today
**What goes wrong:** Because today's live data has 0 NULL `category` rows, it's tempting to skip
the "map to Uncategorized" step and just make `category_id` NOT NULL immediately. But D-04 requires
a real "Uncategorized" node to exist specifically so *future* NULL-category inserts (e.g. a
transaction imported without a category, or a bug in a later phase) have somewhere safe to land
instead of failing a NOT NULL constraint at insert time. If `category_id` is NOT NULL, any code path
that tries to insert a transaction without resolving a category first (import edge case, a future
API caller) gets an opaque DB constraint violation instead of a clean "assigned to Uncategorized"
fallback.
**Why it happens:** Confusing "today's backfill has no NULLs to handle" with "the column should
therefore be NOT NULL forever."
**How to avoid:** Make `category_id` NOT NULL (matches the "no NULL categories remain" success
criterion) but ensure the *application write path* (`_get_or_create_account`-style helper for
categories, or the `TransactionCreate` handler) defaults to the "Uncategorized" category id when no
category is supplied — never leans on the DB to reject a NULL, always resolves one first.
**Warning signs:** A future `POST /transactions` without a `category` field starts throwing a raw
`IntegrityError` instead of defaulting cleanly.

### Pitfall 3: Parent-category deletion needs a *child* reassignment story the Account precedent doesn't have
**What goes wrong:** `DELETE /accounts/{id}` only ever guards against *transactions* referencing the
row being deleted — accounts have no child accounts. Categories do have children (up to 3 levels).
Copying the Account pattern verbatim only guards "transactions directly in this category"; deleting
a top-level group with subcategories underneath it (that themselves have transactions) needs an
additional guard: block (or cascade-reassign) the *subcategories*, not just the leaf transactions.
**Why it happens:** The most obvious reference implementation (Account CRUD) has no analogous
self-referential-child case to copy from.
**How to avoid:** `apply_delete_category` must check both (a) direct transaction count and (b)
child-category count before allowing an unconditional delete; the block-or-reassign guard's 422
payload should distinguish "N transactions" from "M subcategories" so the UI can present the right
reassignment target picker (a subcategory can't be reassigned to a transaction target and vice
versa).
**Warning signs:** Deleting a top-level group "succeeds" but leaves orphaned subcategory rows with
a `parent_id` pointing at a now-deleted row (should be impossible if the FK has no `ON DELETE
CASCADE`/`SET NULL` — confirm the FK is `RESTRICT` or absent an `ondelete` clause, matching the
account FK's default behavior, so Postgres itself would raise before the guard even needs to run
correctly, but the guard should still pre-empt with a clean 422 rather than surfacing a raw FK
violation).

### Pitfall 4: New category CRUD is not automatically an agent-facing `propose_*` tool
**What goes wrong:** D-11 says *existing* `propose_rename_category`/`propose_merge_category` get
reworked onto the hierarchy and must keep working. It's easy to over-scope this phase into also
building `propose_add_category`/`propose_edit_category`/`propose_delete_category` agent tools by
analogy with `propose_add_account`, etc. But CHAT-09 ("category changes via chat") is explicitly
scoped to Phase 14 per the requirements traceability table, and the Account CRUD precedent this
phase should copy (`POST/PUT/DELETE /accounts`) has **no** agent-facing `propose_add_account`-style
Settings-CRUD equivalent for its create/edit/delete either — those are direct, `require_api_key`-
gated REST endpoints only, distinct from the money-record `propose_*` write flow.
**Why it happens:** The dual-registration pitfall (agent tools need registering in two places) can
make it feel like *every* new write needs an agent tool, when the actual precedent is "structural
Settings CRUD (accounts, and now categories) is direct REST; money-record writes (transactions,
holdings, and category rename/merge which retarget money records) go through `propose_*`."
**How to avoid:** Scope Phase 11's category add/edit/delete as direct REST CRUD (mirroring
`/accounts`), not new agent tools. Only rename/merge need `propose_*` rework, because those already
exist as agent tools today and D-11 requires them to keep working.
**Warning signs:** Planner adds a `propose_add_category` task — check it against the Account CRUD
precedent before accepting it into this phase's scope.

### Pitfall 5: `reset_engine()` cache invalidation must be called after schema-changing endpoints, same as today
**What goes wrong:** `POST /categories/rename` and `POST /categories/merge` already call
`from backend.query import reset_engine; reset_engine()` after committing, because the LLM query
engine caches a module-level singleton (`backend/query.py`'s `_llm`) that could otherwise answer
against stale category data. Any *new* category-mutating endpoint (add/edit/delete) must remember
this same call — it's easy to copy the account CRUD handlers (which also call `reset_engine()`)
without noticing *why*, and then skip it on a new category endpoint that looks structurally similar
but was written from a different template.
**Why it happens:** The reset call isn't enforced by any type system or test that fails loudly if
omitted — it's a convention, not a constraint.
**How to avoid:** Grep all mutating `/categories/*` and `/accounts/*` handlers for `reset_engine()`
before considering a new category-mutating endpoint done; add a coverage test asserting the engine
cache is invalidated after category CRUD, mirroring `test_category_management.py`'s existing rename/
merge tests.
**Warning signs:** Chat answers reference a just-deleted or just-renamed category after the Settings
UI shows it gone.

## Code Examples

Verified patterns from this repo (no external docs needed — every pattern below is copied from
code already in the repo, confirmed by direct read in this research session):

### Nullable-backfill-lock idiom
```python
# Source: alembic/versions/006_multi_platform_holdings.py:42-83 (verified, read in full)
op.add_column("portfolio_events", sa.Column("platform_id", sa.Integer(), nullable=True))
op.execute(
    "UPDATE portfolio_events e SET platform_id = h.platform_id "
    "FROM holdings h WHERE h.ticker = e.ticker"
)
op.alter_column("portfolio_events", "platform_id", nullable=False)
op.create_foreign_key("fk_portfolio_events_platform", "portfolio_events", "platforms", ["platform_id"], ["id"])
op.create_index("ix_portfolio_events_platform_id", "portfolio_events", ["platform_id"])
```

### Block-or-reassign delete guard
```python
# Source: backend/main.py:236-270 (verified, read in full) — the exact shape to copy for
# DELETE /categories/{id}
tx_count = int(db.execute(
    text("SELECT COUNT(*) FROM transactions WHERE account_id = :aid"), {"aid": account_id}
).scalar() or 0)
if tx_count and reassign_to is None:
    raise HTTPException(status_code=422, detail={"affected_count": tx_count})
```

### Dual tool registration checklist (must both be updated together)
```python
# Source: backend/tools.py:493-517 (TOOLS dict + READ_TOOL_NAMES snapshot) and
# backend/query.py:117-146 (FunctionTool list) — both verified, read in full
# 1. tools.py: add/keep the function in the `TOOLS = {...}` dict (read tools) or the
#    `TOOLS.update({...})` block at line 962 (write/propose tools).
# 2. query.py: add/keep a matching `FunctionTool.from_defaults(fn=...)` entry.
# 3. tools.py: READ_TOOL_NAMES = frozenset(TOOLS) is captured BEFORE the write-tool
#    update() call — never move a propose_* function above that line.
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `transactions.category` free-text string, exact/substring matched | `transactions.category_id` FK into a `categories` hierarchy table | This phase (009) | Rename/merge become single-row edits instead of bulk `UPDATE`s; spending rollups become JOIN + GROUP BY instead of string GROUP BY |
| Flat category list (`GET /categories` → distinct strings) | Tree-shaped `GET /categories` response (or a new endpoint) consumed by `list_categories()` agent tool and the Settings tree UI | This phase | Every consumer of the old flat list (`CategoryManager.tsx`, the agent tool) needs updating in the same phase, or a compatibility shim |

**Deprecated/outdated:**
- `apply_rename_category`'s `UPDATE transactions SET category = :new WHERE category = :old` bulk
  pattern: replaced by a single-row `UPDATE categories SET name = :new WHERE id = :id` (D-11).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | CSV (not YAML) is the recommended mapping-file format, based on "no new dependency" reasoning rather than a locked user decision (D-05 leaves format at Claude's discretion) | Standard Stack / Alternatives Considered | Low — if the user prefers YAML during the D-06 review checkpoint, swapping formats mid-phase costs one dependency add + a parser swap, not a schema change |
| A2 | Recommendation to enforce the 3-level depth cap in application code (write-time guard) rather than a DB constraint | Architecture Patterns, Pattern 1 | Low — a future bug could insert a 4th-level category if the guard is missed in one write path; a follow-up CHECK-style safeguard (e.g. a periodic audit query) would catch it, not silent data loss |
| A3 | New category add/edit/delete should be direct REST CRUD (not agent `propose_*` tools) this phase, based on the Account CRUD precedent and CHAT-09's Phase-14 placement — not an explicit CONTEXT.md decision | Common Pitfalls, Pitfall 4 | Medium — if the user actually wants chat-driven category creation in Phase 11 (not just rename/merge), this scoping call would need revisiting; low likelihood given CHAT-09's explicit phase-14 traceability entry |

## Open Questions

1. **Mapping file location**
   - What we know: it must be a checked-in, human-reviewed file consumed by the migration (D-05/D-06).
   - What's unclear: exact path (`data/category_mapping.csv`? `alembic/data/`? `scripts/`?) — no existing convention in this repo for migration-adjacent data files.
   - Recommendation: planner picks a path under `alembic/` (co-located with the migration that consumes it) so it's obviously migration-scoped and not confused with app runtime config.

2. **Where does the migration's Python-side backfill loop actually run?**
   - What we know: `alembic/env.py` runs migrations inside a single `op.execute`/`context.begin_transaction()` block, standard Alembic online mode.
   - What's unclear: whether the CSV read + per-category `op.execute(UPDATE... WHERE category = :raw)` loop should live inline in the migration's `upgrade()` function (simplest, matches existing single-file migrations) or be factored into a helper module — no precedent for a migration this data-heavy exists yet in `alembic/versions/`.
   - Recommendation: inline in `upgrade()`, matching every existing migration's self-contained style; a helper module is unwarranted for a one-time 74-row loop (ponytail: don't build reusable migration-helper infrastructure for a single call site).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| PostgreSQL | Live migration target | Yes | 16.13 `[VERIFIED: psql SELECT version(), live query]` | — |
| Alembic | Migration runner | Yes | >=1.13.0, pinned in `backend/requirements.txt` `[VERIFIED: file read]` | — |
| Live monai DB reachable at localhost:5434 | Parity audit, dev verification | Yes | 5,728 transactions, 74 categories confirmed `[VERIFIED: live psql query]` | — |

**Missing dependencies with no fallback:** none
**Missing dependencies with fallback:** none

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest >=8.0.0 |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`, `testpaths = ["backend/tests"]`) |
| Quick run command | `pytest backend/tests/test_category_management.py -x` |
| Full suite command | `pytest backend/tests` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CAT-01 | Category hierarchy CRUD respects 3-level depth cap, parent-color inheritance | unit | `pytest backend/tests/test_category_hierarchy.py -x` | ❌ Wave 0 |
| CAT-02 | Delete blocks with 422+affected_count when in use; reassign-then-delete works; child-category guard (Pitfall 3) | unit/integration | `pytest backend/tests/test_category_hierarchy.py -k delete -x` | ❌ Wave 0 |
| CAT-03 | Migration: all 74 strings map, row/sum parity holds, abort on unknown string, idempotent re-run | migration/integration | `pytest backend/tests/test_category_migration.py -x` (or a standalone migration-verification script run against a scratch DB) | ❌ Wave 0 |
| CAT-04 | `spending_by_category`/`list_categories`/rollup endpoints read hierarchy, not free string | unit | `pytest backend/tests/test_tools.py -k category -x` (extend existing file) | ✅ existing file, extend |

Existing `backend/tests/test_category_management.py` (rename/merge/list/affected-count, all against
the free-string column today) will need rewriting once the hierarchy lands — its assertions
(`tx.category == new`) become `tx.category_id == new_id` or similar; treat it as "modify," not
"delete and forget."

### Sampling Rate
- **Per task commit:** `pytest backend/tests/test_category_hierarchy.py backend/tests/test_category_management.py -x`
- **Per wave merge:** `pytest backend/tests` (full suite — this phase touches shared tools/writes modules other phases depend on)
- **Phase gate:** Full suite green before `/gsd-verify-work`, plus a manual migration dry-run against a scratch copy of the live DB (5,728-row parity check is the phase's actual acceptance bar, not just unit tests)

### Wave 0 Gaps
- [ ] `backend/tests/test_category_hierarchy.py` — covers CAT-01 (hierarchy CRUD, depth cap) and CAT-02 (block-or-reassign incl. child-category case)
- [ ] `backend/tests/test_category_migration.py` — covers CAT-03 (mapping completeness, parity assertion, idempotent re-run, abort-on-unknown); needs a `db_available` fixture pattern matching `test_category_management.py`'s, plus a way to run the actual migration against a disposable schema (or assert the migration's Python helper functions directly if the parity-check logic is factored out of `upgrade()` for testability)
- [ ] Framework install: none — pytest already present

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No (new endpoints reuse existing `require_api_key`) | `Depends(require_api_key)` on all mutating `/categories/*` routes, matching `/accounts/*` |
| V3 Session Management | No | Single-user, API-key auth, no session state to add |
| V4 Access Control | Yes | Same `require_api_key` dependency gates category mutation as gates account mutation — no new access-control surface |
| V5 Input Validation | Yes | Category name/color/icon/parent_id validated via Pydantic schemas (`CategoryCreate`/`CategoryUpdate`-style, mirroring `AccountCreate`); `parent_id` must reference an existing category or be rejected (FK will catch this at the DB level too, but a clean 422 is better UX than a raw FK violation) |
| V6 Cryptography | No | No new secrets/crypto surface introduced |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection via category name in raw `text()` queries | Tampering | Parameterized queries only — `text(sql), {"cat": name}` pattern already used everywhere in `tools.py`; the migration's per-category `UPDATE ... WHERE category = :raw` must use bound parameters too, not string-formatted SQL, even though the mapping file is a trusted/reviewed input |
| Mapping-file injection (a malicious/malformed CSV row causing an unintended `UPDATE ... WHERE category = ''` matching unrelated rows) | Tampering | The migration should validate that every mapping-file row's `raw_category` value is non-empty and appears in the live `SELECT DISTINCT category` set before applying it — reject (abort loudly, per D-07) rather than silently apply a no-op or wildcard match |
| Orphaned transactions after a category delete (data-integrity failure, not classic STRIDE, but this phase's core "zero data loss" constraint) | Tampering / Repudiation (if audit log is skipped) | Block-or-reassign guard (Pattern 3) + `AuditLog` row on every category mutation, matching the existing `apply_delete_account` convention |

## Project Constraints (from CLAUDE.md)

- **Correctness-by-construction:** the LLM never emits SQL. All hierarchy-aware queries in
  `spending_by_category`/`spending_in_category`/`list_categories` must remain hand-written,
  parameterized SQL tools — no free-form SQL generation, even for the more complex rollup joins.
- **Parameterized SQL only:** every query (including the migration's backfill) uses SQLAlchemy
  `text()` with bound parameters — never string-interpolated category names.
- **Schema needs a migration story (no Alembic today** — superseded by current state: Alembic *is*
  now in place, migrations 001-008 exist; this phase's migration is 009, following the same idiom.
- **Dual-registration convention:** any new/changed agent tool goes in both `backend/tools.py`
  `TOOLS`/`TOOLS.update()` and `backend/query.py`'s `FunctionTool` list; write tools stay off
  `READ_TOOL_NAMES` (captured as a frozenset snapshot before the write-tool `update()` call).
- **Confirm-before-write:** all agent-driven writes require explicit user confirmation via the
  `Proposal` flow — applies to the reworked `propose_rename_category`/`propose_merge_category`,
  does NOT extend to the new direct-REST category add/edit/delete CRUD (see Pitfall 4).
  Category CRUD (add/edit/delete) is not itself agent-driven — it goes through Settings UI direct
  REST, matching the `/accounts` precedent, not the `propose_*` money-write flow.
- **Single-currency (IDR) assumption:** categories have no currency dimension — unaffected by this
  constraint, noted only to confirm no cross-currency category logic is needed.
- **Inline `React.CSSProperties`, no CSS framework:** the Settings tree UI (`CategoryManager.tsx`)
  must use `ui/app/styles.ts` tokens exactly like the existing component does — no new styling
  approach.
- **Snake_case Python / camelCase TypeScript / PascalCase classes and components:** `Category`
  ORM class, `category_id`/`parent_id` columns, `CategoryManager`/`CategoryTree` components.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CAT-01 | Categories are first-class entities (name, color, icon, parent) with up to 3 hierarchy levels | Pattern 1 (self-referential `Category` model, depth cap enforced in write helpers); Architecture Patterns / Project Structure |
| CAT-02 | User can manage categories in Settings — add, edit, delete with a block-or-reassign guard (no orphaned records) | Pattern 3 (copied from `DELETE /accounts/{id}` + `AccountManager.tsx`); Pitfall 3 (child-category reassignment gap the Account precedent doesn't cover) |
| CAT-03 | The 74 existing category strings migrate onto the hierarchy via a human-reviewed mapping with row/sum parity checks; destructive column drop is a separate later migration | Pattern 2 (nullable→backfill→NOT NULL idiom from migration 006); Runtime State Inventory (live 74-string / 5,728-row audit, whitespace-dupe and TRANSFER-alignment findings); Pitfall 1 (whitespace dupe); Validation Architecture (CAT-03 test row) |
| CAT-04 | Record forms, filters, and dashboard charts use the hierarchical category picker | Pattern 4 (hierarchy-aware read tools); Architectural Responsibility Map (notes record-modal picker itself is out of this phase's build scope — Phase 16 — only the data source needs to be hierarchy-shaped now) |
</phase_requirements>

## Sources

### Primary (HIGH confidence)
- `alembic/versions/006_multi_platform_holdings.py` (read in full) — the nullable-backfill-lock migration idiom
- `alembic/versions/008_fx_rate_cache.py` (read in full) — DDL-only migration idiom for comparison
- `alembic/env.py` (read in full) — confirms single-transaction online migration execution model
- `backend/models.py` (read in full) — existing ORM conventions (`Account`, `Platform`, `Holding` shapes) to mirror for `Category`
- `backend/tools.py` (relevant sections read: L1-60, L160-410, L460-517, L790-850) — existing category tool implementations and the `TOOLS`/`READ_TOOL_NAMES` registration pattern
- `backend/writes.py` (L330-382 read) — `apply_rename_category`/`apply_merge_category` current implementation
- `backend/main.py` (relevant sections read: L202-270, L585-704) — `/accounts` and `/categories` endpoint precedents
- `backend/query.py` (grep + relevant lines read) — `FunctionTool` registration list, dual-registration confirmation
- `backend/schemas.py` (grep) — `CategoryRenameRequest`/`CategoryMergeRequest` shapes
- `backend/tests/test_category_management.py` (read in full) — existing test coverage/conventions for category endpoints
- `ui/app/cashflow/CategoryManager.tsx` (read in full) — existing rename/merge UI to move + extend
- `ui/app/cashflow/AccountManager.tsx` (grep) — block-or-reassign delete-guard UI flow to copy
- `ui/app/cashflow/charts/CategoryDonut.tsx` (read in full) — existing donut chart to rewire for rollup
- `ui/app/styles.ts` (read in full) — token/palette source for D-14's curated category colors
- Live Postgres query against `postgresql://monai:monai@localhost:5434/monai` (2026-07-18) — 5,728 total transactions, 74 distinct categories, 0 NULL categories, whitespace-duplicate finding, `category='TRANSFER'` / `is_transfer` alignment, 15 `category`≠`raw_category` mismatches, 14 NULL `raw_category` rows
- `.planning/phases/11-category-hierarchy-schema-audit-migration/11-CONTEXT.md` (read in full) — locked decisions D-01 through D-16
- `.planning/REQUIREMENTS.md`, `.planning/STATE.md` (read in full) — CAT-01..04 definitions, prior-phase decisions, memory of prior incidents
- `backend/requirements.txt`, `ui/package.json` (grep) — confirmed no new dependency needed (no YAML lib, no tree-view lib)
- `.planning/config.json` (read in full) — `nyquist_validation: true`, no `security_enforcement: false` override

### Secondary (MEDIUM confidence)
- None used — all findings this phase were verified directly against this repository's code and live database, no external documentation lookup was needed for a project-internal migration/schema pattern

### Tertiary (LOW confidence)
- None

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — every tool is already installed and pinned in this repo; nothing new introduced
- Architecture: HIGH — every pattern (migration idiom, delete guard, dual registration) is copied from working code in this repo, verified by direct read
- Pitfalls: HIGH — Pitfall 1 (whitespace dupe) and the TRANSFER-alignment finding came from direct live-DB queries in this session, not inference; Pitfalls 2-5 are reasoned from the locked CONTEXT.md decisions plus existing code precedent

**Research date:** 2026-07-18
**Valid until:** 30 days (stable internal codebase pattern research; re-verify live category counts if significant new transactions are imported before planning executes)
