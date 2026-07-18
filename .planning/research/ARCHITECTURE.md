# Architecture Research

**Domain:** Personal-finance web app — v1.2 "Connected Ledger" integration onto an existing FastAPI + PostgreSQL + Next.js vertical slice
**Researched:** 2026-07-18
**Confidence:** HIGH (all findings verified against live source: `backend/models.py`, `backend/tools.py`, `backend/writes.py`, `backend/main.py`, `backend/mcp_server.py`, `backend/query.py`, `ui/app/`, `alembic/versions/`)

## System Overview — Existing Layered Architecture (Unchanged Shape)

```
┌──────────────────────────────────────────────────────────────────────┐
│  UI (Next.js App Router)   ui/app/{cashflow,investments,chat,settings}│
│  inline React.CSSProperties + token-driven styles.ts, no CSS framework│
├──────────────────────────────────────────────────────────────────────┤
│  Proxy   ui/app/api/[...proxy]/route.ts  →  MONAI_API (backend:8001)  │
├──────────────────────────────────────────────────────────────────────┤
│  HTTP/API   backend/main.py — REST endpoints + FastMCP co-mount       │
│    - direct REST writes (require_api_key)                            │
│    - /query, /query-stream — agent entry points                      │
│    - /proposals/{id}/confirm — SINGLE atomic-apply chokepoint         │
├──────────────────────────────────────────────────────────────────────┤
│  AI query   backend/query.py — LlamaIndex FunctionAgent               │
│    FunctionTool.from_defaults(fn=...) wraps every TOOLS callable      │
├──────────────────────────────────────────────────────────────────────┤
│  Tools (domain)  backend/tools.py — TOOLS registry (dict[str,callable]│
│    15 read tools + 11 propose_* write tools = 26 after module load    │
│    READ_TOOL_NAMES = frozenset snapshot BEFORE write tools merged in  │
├──────────────────────────────────────────────────────────────────────┤
│  Writes (shared mutation layer)  backend/writes.py — apply_* funcs    │
│    called by BOTH _execute_proposal_payload AND direct REST endpoints │
│    one entity mutation + one AuditLog row each; never commits itself  │
├──────────────────────────────────────────────────────────────────────┤
│  Persistence  backend/models.py (SQLAlchemy) + alembic/versions/ (008)│
└──────────────────────────────────────────────────────────────────────┘
```

**Critical existing seam:** `backend/writes.py` docstring — "single source of truth for every data-mutating operation... called by BOTH the agent propose→confirm path AND the direct REST endpoints so audit-log writes and Decimal handling can never diverge." Every new mutation (transfers, buy/sell-with-funding, balance adjustments) MUST add an `apply_*` function here and route both the REST endpoint and the `propose_*` tool through it. This is the load-bearing pattern for the whole milestone — do not special-case any new write path around it.

## Integration Point 1 — Liquid/Investment Boundary for Net Worth

**Where it lives:** `accounts.type` (String(64), nullable, already exists, all NULL in live DB — confirmed in `backend/models.py:49` and `AccountCreate`/`AccountUpdate` schemas already accept `type`). This column is the discriminator; no new column needed.

**Why net worth currently can't be computed correctly:** there is no `/net-worth` or net-worth aggregation anywhere in `backend/main.py` or `backend/tools.py` today (grep confirms zero hits for "net_worth"/"net worth" outside docstrings). `account_balances()` in `tools.py` sums ALL accounts undifferentiated — if investment cash sits in an `accounts` row (as it will once liquid↔investment transfers exist), summing that alongside `investments_summary()`'s holdings value double-counts.

**Recommended integration:**
1. Backfill migration sets `accounts.type` to `'liquid'` for all existing rows (5608 transactions' accounts are all liquid today — no investment-typed accounts exist pre-migration). New "investment platform cash" is NOT an `accounts` row — platforms stay a separate table (`platforms`, no `type` column needed there since ALL platforms are investment by definition).
2. A new `GET /net-worth` (or extend `GET /cashflow/summary`) endpoint sums `SUM(transactions.amount) WHERE is_transfer=false GROUP BY account.type` for liquid, plus `investments_summary()`'s existing portfolio value for investment — two independently-computed, non-overlapping totals added together. **The exclusion boundary is `accounts.type='liquid'` on one side and the `holdings`/`portfolio_events` tables on the other — they are physically different tables, so double-counting is structurally impossible as long as investment cash is never modeled as an `accounts` row.**
3. Because `is_transfer` already excludes transfers from every liquid-side sum (see Integration Point 2), a liquid→investment transfer transaction won't inflate the liquid total once it's marked transfer — and it funds a `portfolio_events` write on the other side (Integration Point 3), so the money "appears" exactly once total.
4. `account_balances()` and `cashflow_summary()` need a `type` filter added (or a `WHERE a.type = 'liquid'`) once investment-type accounts could exist — otherwise a future investment-typed account with stray transactions would leak into cashflow's spending/income tools. Given the milestone's design (investment money lives in `holdings`/`portfolio_events`, not `accounts`), this is a defensive filter, not a hard blocker for v1.2, but should be added in the same phase as the `type` backfill to avoid a silent regression window.

## Integration Point 2 — Paired Transfer Records vs. `is_transfer` + Transfer-Exclusion

**Existing mechanics (verified in `backend/tools.py`):** `is_transfer: Mapped[bool]` on `Transaction` (indexed). Every read tool (`spending_total`, `income_total`, `net_total`, `spending_by_category`, `spending_in_category`, `transaction_count`, `largest_transactions`, `average_daily_spending`, `monthly_trend`, `account_balances`, `find_transactions`, `list_categories`) filters `WHERE is_transfer = false` (or joins with that predicate). This is a hard-coded per-query clause, not a view or shared helper — 10+ call sites repeat the literal string.

**Design for liquid→investment transfers and liquid↔liquid transfers:**
- Model as **two `Transaction` rows**, both `is_transfer = true`, linked by a shared identifier. The schema comment in `models.py` explicitly says `transfer_pair_id` was "intentionally omitted from v1" — this milestone is the trigger to add it back. Add `transactions.transfer_pair_id: Mapped[uuid.UUID | None]` (nullable UUID, indexed) in a new migration. Two paired rows share the same `transfer_pair_id`; a single-account balance-adjustment or non-transfer expense has it NULL.
- One row is the debit (negative amount, source account), one is the credit (positive amount, destination account) — mirrors how `is_transfer` transactions already work for existing liquid↔liquid Wallet-import data (the CSV importer already produces `is_transfer=true` pairs; this pattern is proven, just not yet linked by ID).
- For a **liquid→investment transfer**, the destination "account" isn't an `accounts` row — it's the funding leg of a `PortfolioEvent` (see Integration Point 3). So the pattern is: ONE `Transaction` row (`is_transfer=true`, debit from the liquid account) paired (via `portfolio_events.source_account_id`, not `transfer_pair_id`) to the `PortfolioEvent` it funded, not to a second `Transaction` row. This is an asymmetric pairing — liquid↔liquid transfers pair Transaction↔Transaction; liquid↔investment transfers pair Transaction↔PortfolioEvent. This avoids inventing a phantom "investment account" transaction.
- Because all pairs keep `is_transfer=true`, **zero changes are required to the 10+ existing `WHERE is_transfer = false` call sites** — the exclusion boundary already does the right thing. This is a major point in favor of the design: the safety property ("spending/income tools never see transfers") is preserved for free.
- The Records tab (new UI) is the one place that DOES want to see transfer rows (to render them as paired/linked entries) — it needs a new read tool/endpoint that does NOT filter `is_transfer=false`, e.g. `list_records()` or extend `find_transactions()` with an `include_transfers` flag defaulting false (safe default preserves existing agent behavior) that the Records UI passes `true`.

## Integration Point 3 — `portfolio_events` Gains a Funding-Account Link, Written Atomically

**Existing mechanics (verified in `backend/writes.py:apply_add_portfolio_event` and `backend/portfolio.py:recompute_holding_from_events`):** `PortfolioEvent` already carries `platform_id`, `ticker`, `event_type`, `quantity`, `price`, `currency`. `apply_add_portfolio_event()` inserts the event, flushes for the audit-log FK, then calls `recompute_holding_from_events()` which rebuilds the `holdings` row from the full event ledger for that `(ticker, platform_id)` — this recompute pattern (source-of-truth ledger → derived position) is exactly the same shape needed for the transfer's paired liquid-side write.

**Schema change:** add `portfolio_events.source_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True, index=True)`. Nullable because existing/manual events (dividends, seeded positions via `propose_add_holding`'s direct-override path) have no funding account. New migration; no backfill needed (existing rows stay NULL — they predate this feature and have no funding account to infer).

**Atomic dual-write — where it goes:** Add `apply_buy_with_funding(db, after)` (or extend `apply_add_portfolio_event` with an optional `source_account_id` param) to `backend/writes.py`. It must, within the SAME session/transaction (writes.py's existing convention — "never commits itself, caller owns the transaction boundary"):
1. Insert the `Transaction` row (`is_transfer=true`, debit, `account_id=source_account_id`, amount = -(quantity × price, converted to the account's currency if the event is USD-denominated — reuse `backend/fx.py:get_rate()`, the exact pattern `recompute_holding_from_events` already uses for FX-04 historical-at-purchase conversion).
2. Insert the `PortfolioEvent` row with `source_account_id` set, exactly as `apply_add_portfolio_event` does today.
3. Call `recompute_holding_from_events()` (unchanged — it doesn't need to know about funding).
4. Write ONE `AuditLog` row per mutated entity (matches the existing one-audit-row-per-entity convention; two entities mutated = two audit rows, both inside the same DB transaction so they're atomic together).
5. Caller (`_execute_proposal_payload` for the agent path, or a new `POST /portfolio-events` REST variant for the UI buy/sell modal) still owns `db.commit()` — this preserves the existing "commit boundary belongs to the endpoint, not the write helper" rule and gets atomicity for free from the wrapping transaction.

**Sell events** (liquid gets credited) mirror this: `apply_sell_with_funding` inserts a credit `Transaction` (`is_transfer=true`, positive amount into the destination liquid account) instead of a debit. Both buy and sell reuse `recompute_holding_from_events` unchanged.

**Proposal-flow wiring:** `_execute_proposal_payload` in `main.py` (currently an `if/elif` chain on `operation` string, lines 802-841) needs a new branch: `elif operation == "add_portfolio_event_funded": apply_buy_with_funding(db, after)` (or `apply_sell_with_funding` depending on event_type). Given the existing pattern strongly favors one `operation` string per distinct effect (10 existing operations, each one apply_* call), add a new operation string rather than overloading `add_holding`'s branch with conditional behavior on payload shape — matches convention and keeps `_execute_proposal_payload` a flat dispatch table.

## Integration Point 4 — Categories Table + Migration from 5608 Rows

**Current state:** `transactions.category: Mapped[str | None] = mapped_column(String(255), nullable=True)` — free string, no FK, no hierarchy. `raw_category` also exists (stores the original Wallet CSV label; `category` may have been renamed/merged via `propose_rename_category`/`propose_merge_category`, which do plain `UPDATE transactions SET category = :new WHERE category = :old`). No `categories` table exists anywhere in `models.py` today (confirmed by grep).

**New table:** `categories(id, name, parent_id FK→categories.id nullable, color, icon, nature, hidden)` — a self-referencing FK gives the 3-level hierarchy (parent_id NULL = top-level; grandchild = parent_id → a row whose own parent_id is non-NULL). Add via new Alembic migration following the `008_fx_rate_cache.py` pattern (revision/down_revision chain, `op.create_table`, explicit `op.create_index` on lookup columns).

**Migration sequencing (dependency-ordered, this must be the FIRST schema change in the milestone since almost everything else is additive/independent but categories touches every existing transaction row):**
1. **Migration N: create `categories` table** (empty, no FK from `transactions` yet). Populate it programmatically (data migration, not pure DDL) by `SELECT DISTINCT category FROM transactions` (verified pattern: existing categories are free strings with no hierarchy info) and inserting each as a flat top-level category (`parent_id=NULL`, sensible default `nature`, no color/icon — user assigns those later in the Settings UI). This is a **data migration inside the Alembic script** (`op.execute` or bulk insert via `sa.table`/`bind.execute`), not just DDL — Alembic supports this in the same `upgrade()` function.
2. **Migration N+1: add `transactions.category_id` (nullable FK → categories.id)** alongside the existing `category` string column (do NOT drop `category` yet — dual-write period). Backfill `category_id` by joining `transactions.category = categories.name` in a single `UPDATE ... FROM` statement (5608 rows — trivial for a single UPDATE, no batching needed). Any transaction whose `category` is NULL, `category_id` stays NULL — matches "uncategorized."
3. **Backend cutover (same phase, not a separate migration):** `tools.py`/`writes.py` start reading/writing `category_id` (joined to `categories.name` for display) while keeping `category` string writes in sync for one release (or immediately retire it — given single-user self-hosted with no external consumers of the raw column, retiring immediately after the backfill is the lazier, safer choice; no need for a dual-write transition period nobody else observes).
4. **Migration N+2 (can ship same phase or deferred): drop `transactions.category` string column** once `category_id` is verified correct (`raw_category` may be worth keeping as historical provenance of the original Wallet CSV label — it's not part of "category" management, it's import metadata; recommend keeping it, only drop `category`).

**Risk on live data:** 5608 rows is trivial (no batching/streaming needed, single `UPDATE` completes in milliseconds). The real risk is the **free-string category values may have inconsistent casing/whitespace** (never validated before) — `SELECT DISTINCT category` could produce near-duplicate categories ("Food", "food ") that should collapse to one. Recommend a `TRIM()`/case-normalization pass in the population step, and a manual review checkpoint (list the distinct categories to the user) before finalizing — this is a one-time data-quality decision, not an automatable one.

## Integration Point 5 — Read Tools / MCP Tools / Agent Tools Needing Updates

Three registration points must be updated **together** for every new/changed tool (per the "Chat tool dual registration" gotcha already known to this project):

| Tool change | `backend/tools.py` (`TOOLS` dict) | `backend/query.py` (`FunctionTool.from_defaults`) | `backend/mcp_server.py` (`MCP_DESCRIPTIONS` + `READ_TOOL_NAMES` inclusion) |
|---|---|---|---|
| **New: `list_records`** (date-grouped ledger incl. transfers, for Records tab data + agent queries like "show me last week's transactions including transfers") | Add to `TOOLS` (read) | Add `FunctionTool.from_defaults(fn=list_records)` to the read-tools block | Add description; included automatically since `READ_TOOL_NAMES` is captured as a snapshot of `TOOLS` BEFORE write tools are merged — as long as it's added before the `TOOLS.update({propose_*...})` call at the bottom of `tools.py`, it's read-only-surfaced for free |
| **New: `propose_add_transfer`** (paired liquid↔liquid or liquid→investment) | Add to `TOOLS` write section, included in the `TOOLS.update({...})` block at the bottom | Add to the write-tools `FunctionTool` block in `query.py` | **Do NOT add** — write tools are deliberately excluded from MCP (`D-03/MCP-03`); `READ_TOOL_NAMES` snapshot already protects this by construction, no action needed beyond correct placement |
| **New: `propose_buy_with_funding` / `propose_sell_with_funding`** (extends portfolio-event creation — note `propose_add_holding` is a *direct holding override*, D-05, distinct from an *event*; there is currently no `propose_add_portfolio_event` write-tool exposed to the agent at all — portfolio events are only created via the direct REST endpoint `POST /portfolio-events`, not through the agent) | Add new `propose_*` fn, register in `TOOLS.update()` | Add to write-tools `FunctionTool` block | Excluded (write tool) |
| **Changed: `account_balances`, `find_accounts`** — must reflect `type` once liquid/investment split exists, and likely gain a `type` filter param | Edit existing fn in place | No registration change needed (same fn reference, signature change is transparent as long as `FunctionTool.from_defaults` re-introspects the docstring/signature — safe) | Update `MCP_DESCRIPTIONS["account_balances"]`/`["find_accounts"]` text to mention the new `type` field so external LLM clients understand it |
| **New: `list_categories` behavior change** — must switch from `SELECT category, SUM(-amount)...` (string GROUP BY) to join through `categories` table, and probably needs a new `find_categories(name)` tool mirroring `find_platforms`/`find_accounts` so the agent can resolve a category name to an id before proposing category-scoped writes | Edit `list_categories`, add `find_categories` | Update/add corresponding `FunctionTool` entries | Update `MCP_DESCRIPTIONS`, add new entry for `find_categories` |
| **New: `propose_add_category` / `propose_edit_category` / `propose_delete_category`** (Settings > Categories management, mirrors the existing `propose_rename_category`/`propose_merge_category` pattern but now operates on `categories` rows, not string UPDATE) | Add fns + register in `TOOLS.update()` | Add to write-tools block | Excluded (write tool) |

**MCP read-only safety net stays intact automatically** as long as new read tools are defined and inserted into `TOOLS` *before* the `TOOLS.update({propose_*...})` call at the bottom of `tools.py` (the file's physical ordering IS the security boundary — `READ_TOOL_NAMES = frozenset(TOOLS)` is evaluated at that line, before the update, tools.py line 517). This is a sharp edge worth flagging explicitly in the phase plan: **a new read tool added below the `TOOLS.update()` call would silently NOT appear anywhere (breaks the agent too, not just MCP) but a new write tool added ABOVE the `READ_TOOL_NAMES` snapshot line would silently leak onto the MCP read-only surface** — the ordering must be preserved, not just "add near similar tools."

## Integration Point 6 — UI Routing for New Tabs

**Existing routing convention (verified in `ui/app/components/Nav.tsx` and directory structure):** flat top-level routes under `ui/app/{cashflow,investments,chat,settings}/page.tsx`, each a Next.js App Router segment; `NAV_LINKS` is a static array of `{href, label, icon}` rendered by the shared `Nav` sidebar component (236px sidebar, `usePathname()`-based active-state, `isActive()` does prefix match so nested routes under a section highlight the parent). Sub-pages/detail views are NOT separate route segments today — e.g. there's no `investments/[platform]/page.tsx`; everything is client-side state within `investments/page.tsx` (798 lines) rendering sub-components (`PlatformManager.tsx`, `HoldingModal.tsx`, etc. as siblings, not routed pages).

**Recommended additions:**
1. **Records tab** — new nav entry. Two viable placements: (a) `ui/app/records/page.tsx` as a new top-level route + `NAV_LINKS` entry (5th sidebar item, matches the flat-route convention exactly), or (b) a tab/sub-view inside `cashflow/page.tsx` (since PROJECT.md scopes it under "Liquids: ... Records tab"). **Recommend (a), new top-level route** — the existing convention is "one route per major surface," Records is described as having its own filters/bulk-actions/date-grouping (substantial standalone surface, not a footnote inside Cashflow), and a flat route keeps `Nav.tsx`'s existing pattern (`NAV_LINKS` array + `Icon` switch) trivially extensible — add one entry, one icon case, done.
2. **Account manager UI** — `AccountManager.tsx` ALREADY EXISTS (308 lines, full add/edit/delete + reassign-on-delete flow), mounted inside `cashflow/page.tsx`. This is a **modify, not build**: add a `type` selector (liquid/investment — though per Point 1, investment-typed `accounts` rows likely shouldn't exist; more likely this becomes a display-only badge or the type field is simply hidden/fixed to "liquid" for anything created here, since investment money lives in `platforms`, not `accounts`). Confirm this UX decision during phase planning — it affects whether `AccountManager.tsx` needs a type dropdown at all.
3. **Platform detail view (PnL + buy/sell history tabs)** — `PlatformManager.tsx` (341 lines) exists for CRUD (add/edit/delete platform) but there is no per-platform detail/drill-down view today; `investments/page.tsx` aggregates across all platforms. New: either a client-side "detail panel" state within `investments/page.tsx` (matching the existing non-routed-subpage convention) showing PnL + buy/sell history for a selected platform, OR a genuinely new route `investments/[id]/page.tsx` if deep-linking to a specific platform's detail is wanted. **Recommend client-side detail panel** (matches existing convention, avoids introducing the app's first dynamic route segment for a v1.2 feature that doesn't obviously need a shareable URL) — flag as an open decision for phase planning if deep-linking turns out to matter.
4. **Record input modal (Expense/Income/Transfer segmented control)** — extends the existing `TransactionModal.tsx` pattern (already exists in `cashflow/`) rather than a new component from scratch; add a segmented Expense/Income/Transfer control that toggles which fields render (Transfer needs a destination-account picker, wiring to the new paired-transfer write tool from Point 2).
5. **Categories management UI** — new section within `ui/app/settings/page.tsx` (already the single settings surface), likely a new sibling component `CategoryTreeManager.tsx` next to the existing `cashflow/CategoryManager.tsx` (which today only does rename/merge on the flat string — this is superseded/extended, not duplicated, by the new hierarchy-aware manager).

## Suggested Build Order (Dependency-Ordered)

1. **Schema: categories table + migration + backfill** (Integration Point 4) — foundational, touches every transaction row, must land before any UI/tool work references `category_id`.
2. **Schema: `accounts.type` backfill migration** (`'liquid'` for all existing rows) + **`transactions.transfer_pair_id`** + **`portfolio_events.source_account_id`** — can be one combined migration or three small ones; all are additive/nullable, low risk, no data-quality judgment calls (unlike categories).
3. **Backend: `backend/writes.py` — new `apply_*` functions** (`apply_add_transfer`, `apply_buy_with_funding`, `apply_sell_with_funding`, `apply_add_category`/`apply_edit_category`/`apply_delete_category`, `apply_add_balance_adjustment`) — the shared mutation layer must exist before either REST endpoints or propose_* tools can call it.
4. **Backend: `main.py` REST endpoints + `_execute_proposal_payload` dispatch branches** + **`backend/tools.py` new `propose_*`/read tools** + **`backend/query.py` FunctionTool registration** + **`backend/mcp_server.py` description updates** — do these together per Point 5's dual/triple-registration requirement; easy to forget one.
5. **Backend: net-worth aggregation endpoint** (Point 1) — depends on step 2's `accounts.type` backfill being live.
6. **UI: extend existing components** (`AccountManager.tsx` type field, `PlatformManager.tsx` detail view, `TransactionModal.tsx` transfer segment) — depends on steps 3-4 being callable.
7. **UI: new surfaces** (Records route + nav entry, net-worth dashboard section, Categories settings manager) — last, since they're purely additive routes consuming the now-stable backend surface.

**Rationale for this order:** schema-first (categories' data-quality risk needs to be resolved and settled before anything builds on `category_id`), then the shared write layer (writes.py is the single choke point everything else calls through — building it before the endpoints/tools avoids rework), then the dual-registered tool surfaces together (minimizes the "forgot to register in query.py" class of bug this project has hit before), then UI last since it's the most mechanical/lowest-risk layer once the API contract is stable.

## Anti-Patterns to Avoid (Specific to This Codebase)

### Anti-Pattern 1: Bypassing `backend/writes.py` for the new atomic dual-write
**What people do:** implement the transfer/buy-with-funding logic inline in `_execute_proposal_payload` or directly in a new REST endpoint handler, since "it's just two inserts."
**Why it's wrong:** breaks the documented invariant that `writes.py` is "the single source of truth for every data-mutating operation... so audit-log writes and Decimal handling can never diverge between the two call paths" (agent-confirm vs. direct-REST). A new mutation implemented ad hoc in `main.py` means the direct-REST buy/sell path and the agent-proposal buy/sell path can silently drift.
**Instead:** every new mutation gets one `apply_*` function in `writes.py`, called identically from both `_execute_proposal_payload`'s new branch and any new direct REST endpoint.

### Anti-Pattern 2: Registering a new write tool above the `READ_TOOL_NAMES` snapshot line
**What people do:** add a new `propose_*` function near a related read tool for readability, without checking whether it lands before or after `READ_TOOL_NAMES: frozenset[str] = frozenset(TOOLS)` (tools.py line 517) and the subsequent `TOOLS.update({propose_*...})` block.
**Why it's wrong:** `READ_TOOL_NAMES` is a physical-ordering security boundary, not a name-based filter. A write tool merged into `TOOLS` before that snapshot line would leak onto the MCP external read-only surface (MCP-03 violation) with no error or warning.
**Instead:** always add new read tools to the first `TOOLS = {...}` dict (before line 494-510) and new write tools only to the later `TOOLS.update({...})` call (after line 517).

### Anti-Pattern 3: Modeling investment cash as an `accounts` row
**What people do:** to make a liquid→investment transfer "symmetric" like liquid↔liquid transfers, create a synthetic `accounts` row per platform (e.g. "Bibit Cash") and post two `Transaction` rows.
**Why it's wrong:** reintroduces the exact double-count risk this milestone exists to fix — that synthetic account's balance would be summed by `account_balances()`/net-worth's liquid side AND the platform's holdings value would be summed by `investments_summary()`, double-counting the same money.
**Instead:** liquid→investment transfers are Transaction↔PortfolioEvent pairs (via `portfolio_events.source_account_id`), not Transaction↔Transaction pairs. Only liquid↔liquid transfers use two paired `Transaction` rows.

### Anti-Pattern 4: Dropping `transactions.category` before validating the `category_id` backfill
**What people do:** combine the "add category_id" and "drop category" migrations into one script to minimize migration count.
**Why it's wrong:** removes the rollback safety net and the ability to spot-check `category_id` correctness against the original string on the live 5608-row dataset before the string is gone.
**Instead:** two migrations minimum, with a manual verification checkpoint between them (matches the project's existing "Holdings double-unique gotcha" lesson — verify against the live DB with `\d transactions` / a row-count reconciliation query before the destructive step).

## Sources

- `backend/models.py` (read in full) — schema, existing nullable `accounts.type`, `is_transfer`, `PortfolioEvent`, comment confirming `transfer_pair_id` was deliberately deferred from v1
- `backend/tools.py` (read in full) — `TOOLS`/`READ_TOOL_NAMES` registry mechanics, every read tool's `is_transfer = false` exclusion, `_make_proposal` helper
- `backend/writes.py` (read in full) — `apply_*` shared-mutation-layer pattern, `apply_add_portfolio_event`'s FX/recompute handling as the template for the new funded-buy/sell writes
- `backend/main.py` (targeted reads: routes list, `_execute_proposal_payload`, `confirm_proposal`) — proposal dispatch chokepoint, existing REST surface
- `backend/mcp_server.py` (read in full) — MCP read-only-by-construction mechanism and its physical-ordering dependency on `tools.py`
- `backend/query.py` (grep) — dual-registration requirement (FunctionTool list) confirmed
- `backend/portfolio.py` (targeted reads) — `recompute_holding_from_events` ledger-recompute pattern, FX-aware cost-basis conversion pattern to reuse for funded events
- `backend/schemas.py` (grep) — `AccountCreate`/`AccountUpdate` already expose `type`; no `Category` schema exists yet
- `alembic/versions/008_fx_rate_cache.py` (read in full) — migration authoring convention to follow for new migrations
- `ui/app/components/Nav.tsx` (read in full) — flat-route + static `NAV_LINKS` sidebar convention
- `ui/app/cashflow/AccountManager.tsx` (partial read) — existing account CRUD pattern already covers most of "account manager," confirms this is a modify not a build
- Directory listings of `ui/app/{cashflow,investments,settings}` — confirmed `PlatformManager.tsx`, `TransactionModal.tsx`, `CategoryManager.tsx` already exist as extension points
- `.planning/PROJECT.md` — milestone scope, constraints, prior decisions (D-01 through D-17 referenced throughout the codebase)
- graphify knowledge graph (`graphify-out/graph.json`) — used for initial orientation; direct-source reads were required for exact line-level mechanics since the indexed graph is coarser-grained (phase-doc and symbol nodes) than the implementation detail this question needed

---
*Architecture research for: monai v1.2 Connected Ledger integration*
*Researched: 2026-07-18*
