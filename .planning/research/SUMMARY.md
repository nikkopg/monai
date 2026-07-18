# Project Research Summary

**Project:** monai — v1.2 "Connected Ledger — Liquids ↔ Investments"
**Domain:** Personal-finance web app; integrating typed accounts, paired transfers, atomic buy/sell, cross-currency entry, and a category hierarchy onto an existing live FastAPI + PostgreSQL + Next.js vertical slice
**Researched:** 2026-07-18
**Confidence:** HIGH

## Executive Summary

v1.2 is a schema-and-integration milestone, not a new-capability milestone. Every feature — net worth dashboard, account/platform managers, Records ledger, liquid↔investment transfers, atomic buy/sell, USD→IDR dual-amount entry, and first-class 3-level categories — is fully covered by the existing FastAPI + SQLAlchemy + Alembic + Next.js stack. Zero new dependencies are needed; the stack research is explicitly a "what NOT to add" defense (no virtualization libs, no table libs, no FX SDKs, no tree-view components, no state-management libs). The real work is disciplined data modeling and migration sequencing against a live 5-year, 5,608-row dataset with two known landmines confirmed today: 74 distinct category strings need a reviewed mapping (not an automatic one), and all 4 existing accounts have `type = NULL` and must be manually audited, not defaulted.

The architecture is already shaped for this: `backend/writes.py` is a proven single-choke-point mutation layer (`apply_*` functions, never self-committing), `_execute_proposal_payload` already loops multi-row payloads under one `db.commit()`, and `is_transfer` already excludes transfer rows from every spending/income read tool. The critical design insight from architecture research is that liquid→investment transfers should NOT be modeled as symmetric Transaction↔Transaction pairs (that would recreate a synthetic "platform cash account" and reintroduce the exact double-count bug this milestone fixes) — instead they're Transaction↔PortfolioEvent pairs via a new `portfolio_events.source_account_id` FK, while liquid↔liquid transfers keep the existing Transaction↔Transaction pairing via a new `transfer_pair_id` column (deliberately deferred from v1, now due).

The dominant risk category is silent correctness regression, not build complexity: promoting `accounts.type` from decorative to load-bearing without an audit + CHECK constraint reintroduces the double-count bug on day one of the headline feature; migrating 74 free-string categories without a human-reviewed mapping either explodes into near-duplicate leaves or silently drops transactions from category totals — both directly violate the project's "never fabricate a number" principle. Mitigation is uniform across all of these: audit live data before writing migration DDL, use closed-set constraints instead of free strings, run row/sum parity assertions inside the migration itself, and route every new mutation through the existing `writes.py` + dual-tool-registration conventions this project has already been burned by twice (memory: `chat-tool-dual-registration`, `TOOLS registry mutates to 26`).

## Key Findings

### Recommended Stack

No new dependencies. FastAPI, SQLAlchemy 2.0 + psycopg3, Alembic (migrations 009+), Next.js 14.2.15/React 18.3.1, and recharts cover every v1.2 feature via patterns already in the repo (`AccountManager.tsx`, `PlatformManager.tsx`, `TransactionModal.tsx`, `backend/fx.py`'s cache-first FX adapter). Explicitly rejected: virtualization libraries (dataset is 5,608 rows over 5 years; pagination caps rendered rows), table libraries (Records tab is a styled list, not a spreadsheet), FX/currency SDKs (`backend/fx.py` + `fx_rate_cache` already complete and tested), tree-view components (3 levels / ~100 category nodes fits a two-step `<select>`), icon libraries (app uses zero today), state-management libraries (existing fetch-on-mount + refetch-callback pattern suffices), and any Next.js/React major-version bump (pure risk, zero payoff this milestone).

**Core technologies:**
- FastAPI + SQLAlchemy/psycopg3 — new endpoints and writes follow existing route/ORM patterns, no new abstractions needed
- Alembic — migrations 009+ for categories table, `accounts.type` constraint, `transfer_pair_id`, `portfolio_events.source_account_id`
- Next.js/React + recharts — new tabs/modals are compositions of existing components (`AccountManager.tsx`, `TransactionModal.tsx`, chart patterns from v1.0 Phase 7)

### Expected Features

**Must have (table stakes, all P1 per FEATURES.md):**
- `accounts.type` liquid/investment discriminator — fixes double-count, everything else depends on it
- Account manager (liquid CRUD) + balance-adjustment records as a distinct, visible record type (not disguised as Expense)
- Records tab: date-grouped ledger, transfer pairs shown as one collapsed row, filters, bulk actions
- Record input modal (Expense/Income/Transfer segmented)
- Platform manager (mirrors account manager) + platform detail (PnL + buy/sell history)
- Liquid→investment transfers: paired, dual-amount cross-currency, user-overridable FX (never forced live-rate-only)
- Buy/sell atomic write: one confirmation moves cash and updates holdings together
- USD→IDR entry-time FX (dual-amount fields; existing FX cache for valuation only)
- Categories as first-class 3-level hierarchy + management UI + migration
- Category delete-reassignment guard: block-until-reassigned (matches BudgetBakers Wallet, the explicit reference product) — never silently orphan `category_id`

**Should have (differentiators, P2 — not required for v1.2 completeness):**
- Agentic chat can propose transfer/buy-sell/adjustment records (extends confirm-before-write pattern; depends on the write tools existing first)
- Natural-language "why did net worth change" answers chaining existing spending/portfolio tools

**Defer (v2+):**
- Bank sync / auto-transfer-detection — explicitly out of scope (no bank feeds, high false-positive risk on manual/CSV data)
- Bulk transfer-pair actions beyond delete (bulk re-date, bulk re-account)
- Recurring-charge detection, automated reksadana NAV feed — already deferred elsewhere in PROJECT.md

### Architecture Approach

Layered shape is unchanged; every new mutation must add one `apply_*` function to `backend/writes.py` (the single documented source of truth for both agent-proposal and direct-REST write paths) and route through the existing multi-row-payload/single-commit pattern in `_execute_proposal_payload`. The one architecturally load-bearing decision: liquid↔liquid transfers pair via `transactions.transfer_pair_id` (Transaction↔Transaction), while liquid→investment transfers pair via `portfolio_events.source_account_id` (Transaction↔PortfolioEvent) — investment money must never be modeled as a synthetic `accounts` row, or the double-count bug returns by construction. Because both transfer legs stay `is_transfer=true`, all 10+ existing `WHERE is_transfer=false` read-tool call sites need zero changes — a major point in the design's favor.

**Major components:**
1. `backend/writes.py` — gains `apply_add_transfer`, `apply_buy_with_funding`, `apply_sell_with_funding`, `apply_add_category`/`edit`/`delete`, `apply_add_balance_adjustment` — all following the existing never-self-commits convention
2. `categories` table (new) — self-referential `parent_id` adjacency list, 3-level cap, migrated from the free-string `category`/`raw_category` columns via a human-reviewed mapping pass
3. Tool registration triad — every new tool must land in `backend/tools.py` TOOLS dict, `backend/query.py` FunctionTool list, and (for reads only) stay correctly positioned relative to the `READ_TOOL_NAMES` snapshot line in `tools.py` (physical-ordering security boundary for MCP)
4. UI — Records tab as a new top-level route (matches flat-route convention); `AccountManager.tsx`/`PlatformManager.tsx`/`TransactionModal.tsx` extended, not rebuilt; Categories management as a new component in Settings

### Critical Pitfalls

1. **Transfer pairing drift** — editing/deleting one leg via existing single-row tools desyncs the pair. Avoid by adding `transfer_pair_id`, routing all transfer-leg mutations through pair-aware tools, and blocking plain `propose_edit_transaction`/`propose_delete_transaction` on any row where `transfer_pair_id IS NOT NULL`.
2. **Double-count regression via `accounts.type`** — the column is nullable free-text today with unknown values across live rows (confirmed: all 4 accounts are `NULL`). Promoting it to a discriminator without an audit + closed-set CHECK constraint reintroduces the exact bug this milestone fixes. Must audit live values, fail loudly on unclassifiable rows, and run cent-exact reconciliation between pre/post-migration sums.
3. **Category backfill mis-mapping** — 74 distinct category strings (confirmed today, `category == raw_category` in count) risk exploding into near-duplicate leaves or silently dropping transactions from totals. Requires a two-pass migration: human-reviewed mapping file first, then idempotent DDL/DML with row-count and sum-of-amount parity assertions baked into the migration, aborting on failure.
4. **Atomicity failure in two-entry writes** — transfer and buy/sell-with-funding must use one proposal payload / one `db.commit()`, never two round trips. The codebase already has the right primitive (`payload["rows"]` loop, `db.flush()` for intermediate IDs); the risk is a one-off new write path that bypasses it.
5. **`is_transfer` exclusion breakage** — any new write path that fails to set `is_transfer=true` on internal-money-movement legs silently pollutes `spending_total`/`income_total`/`monthly_trend`. Every new mutation needs an explicit regression test asserting spend/income totals are net-zero-affected by transfers and buy/sell funding legs.

## Implications for Roadmap

Based on combined research, suggested phase structure (7 phases, dependency-ordered per ARCHITECTURE.md's "Suggested Build Order"):

### Phase 1: Category Hierarchy — Schema, Audit, Migration
**Rationale:** Highest data-quality risk in the milestone (74 live category strings need human-reviewed mapping, touches every transaction row); must land first and in isolation so nothing else builds against an unstable `category_id`.
**Delivers:** `categories` table (self-referential `parent_id`, 3-level cap), reviewed string→hierarchy mapping, `transactions.category_id` backfilled with row/sum parity assertions, `raw_category` preserved untouched.
**Addresses:** FEATURES.md "Categories as first-class 3-level hierarchy," delete-reassignment guard groundwork.
**Avoids:** PITFALLS Critical #3 (category mis-mapping); PITFALLS Pitfall 4 anti-pattern (dropping `category` before validating backfill — keep as two+ migrations with a manual checkpoint between them).

### Phase 2: Typed Accounts + Transfer/Funding Schema Foundations
**Rationale:** Low-risk, additive/nullable schema changes that unblock everything downstream; grouped together because none requires a data-quality judgment call (unlike Phase 1).
**Delivers:** `accounts.type` audited (4 live accounts, all currently NULL) and normalized to a closed `'liquid'|'investment'` set with CHECK constraint; `transactions.transfer_pair_id` (nullable UUID/FK, indexed); `portfolio_events.source_account_id` (nullable FK, indexed).
**Addresses:** FEATURES.md net-worth "one row = one account" requirement.
**Avoids:** PITFALLS Critical #2 (double-count regression) — audit-before-constrain, fail loudly on unclassifiable rows, cent-exact reconciliation.

### Phase 3: Shared Mutation Layer — Transfer, Buy/Sell-with-Funding, Adjustment Writes
**Rationale:** `writes.py` is the single choke point every endpoint and agent tool calls through; building it before REST/tool surfaces avoids rework and enforces atomicity by construction.
**Delivers:** `apply_add_transfer`, `apply_edit_transfer` (pair-aware), `apply_buy_with_funding`, `apply_sell_with_funding`, `apply_add_balance_adjustment`, `apply_add_category`/`edit`/`delete` in `backend/writes.py`, all following the never-self-commits / single-transaction convention.
**Implements:** ARCHITECTURE.md Integration Points 2 & 3 (asymmetric pairing: Transaction↔Transaction for liquid↔liquid, Transaction↔PortfolioEvent for liquid→investment).
**Avoids:** PITFALLS Critical #1 (pairing drift), Critical #5 (atomicity failure), Moderate #6 (`is_transfer` exclusion breakage) — enforce `is_transfer=true` on every internal-movement leg as an explicit test.

### Phase 4: REST Endpoints + Agent/MCP Tool Registration
**Rationale:** Must happen together (dual/triple registration is a known project failure mode — memory: `chat-tool-dual-registration`, `TOOLS registry mutates to 26`); doing it as one phase makes the checklist enforceable.
**Delivers:** New REST endpoints wired to Phase 3's `apply_*` functions; new `_execute_proposal_payload` dispatch branches; `propose_*` tools registered in both `tools.py` TOOLS dict and `query.py` FunctionTool list, positioned correctly relative to the `READ_TOOL_NAMES` snapshot line; MCP description updates.
**Uses:** Existing proposal-confirm chokepoint (`/proposals/{id}/confirm`), existing `TOOLS`/`FunctionTool` registry pattern.
**Avoids:** PITFALLS Minor #1/#2 (dual-registration gaps, MCP read-surface drift) and Anti-Pattern 2 (write tool leaking above the `READ_TOOL_NAMES` snapshot).

### Phase 5: Net Worth Aggregation + Dashboard
**Rationale:** Depends on Phase 2's `accounts.type` backfill being live and constrained; this is the headline feature and the one most exposed to Phase 2 risk, so it must not start until Phase 2's reconciliation checks pass.
**Delivers:** `GET /net-worth` (or extended `/cashflow/summary`) summing liquid (`accounts.type='liquid'`, `is_transfer=false`) and investment (`holdings`/`portfolio_events`) totals as two structurally non-overlapping sums; dashboard UI cards/charts.
**Addresses:** FEATURES.md "net worth = sum of exactly one record per real account/holding."
**Avoids:** PITFALLS Critical #2 residual risk — dashboard SQL should assert its `type` filter matches 100% of accounts, never silently include/exclude ambiguous rows.

### Phase 6: UI — Extend Existing Components (Account/Platform/Record Modals)
**Rationale:** Depends on Phases 3–4 being callable; mechanical UI work layered on a stable backend contract.
**Delivers:** `AccountManager.tsx` type handling, `PlatformManager.tsx` detail panel (PnL + buy/sell history tabs), `TransactionModal.tsx` Expense/Income/Transfer segmented control with dual-amount cross-currency fields.
**Addresses:** FEATURES.md differentiator "Records ledger with transfer pairs visually distinguished."

### Phase 7: UI — New Surfaces (Records Tab, Categories Settings Manager)
**Rationale:** Lowest risk, purely additive routes consuming the now-stable API; last because it has no other phase depending on it.
**Delivers:** New `records/page.tsx` top-level route + nav entry (date-grouped, filters, bulk actions with server-side dependency-closure resolution); `CategoryTreeManager.tsx` in Settings with block-until-reassigned delete guard.
**Avoids:** PITFALLS Moderate #7 (bulk-action footguns) — bulk ops must resolve transfer/portfolio-event dependency closures server-side and reuse the atomic multi-row payload pattern, never client-side loops of single-row proposals.

### Phase Ordering Rationale

- Schema-first, and within schema, data-quality-risk-first: categories (74 strings needing human review) before typed accounts (mechanical audit-and-constrain) — both must be *audited against live data*, not assumed, per the orchestrator-confirmed facts (74 distinct categories, 4 NULL-typed accounts).
- Shared write layer before any endpoint/tool work, because `writes.py` is the proven atomicity primitive — building endpoints against it (not around it) prevents the "new one-off write path bypasses the convention" anti-pattern architecture research flagged explicitly.
- Tool registration is grouped as its own phase specifically because this project has hit the dual-registration gap twice before (project memory); treating it as a single multi-file checklist item rather than incidental to each feature phase reduces recurrence risk.
- Net worth dashboard is deliberately sequenced after typed-accounts reconciliation passes, not concurrently, because it's the feature the entire milestone is named for and the one most exposed to Pitfall 2 if sequenced too early.
- UI phases are last and split into "extend existing" vs. "new surfaces" because the former is a strict prerequisite dependency (needs the API contract stable) while the latter is purely additive and could theoretically be reordered or parallelized if needed.

### Research Flags

Needs deeper research during planning:
- **Phase 1 (Category migration):** the 74-string mapping is a human-judgment task, not a research gap — but the migration mechanics (idempotent, re-runnable, parity-asserting Alembic data migration) should get a `--research-phase` pass to nail the exact Alembic idiom before touching live data.
- **Phase 3 (Buy/sell-with-funding writes):** FX precision handling (authoritative-currency rule, avoiding the BTC price_cache USD/IDR conflation class of bug) is subtle enough to warrant a focused research/plan pass, even though the pattern to follow (`FxRateCache` insert-once) is already identified.

Standard patterns (skip research-phase):
- **Phase 2 (Schema foundations):** nullable→backfill→constrain is an established Alembic pattern already used in migration 008; no new research needed.
- **Phase 4 (Tool registration):** mechanical checklist against a documented, previously-hit gotcha; no research needed, just discipline.
- **Phase 6–7 (UI):** all identified as "extend, don't build" against existing components; standard React/Next.js patterns already proven in this codebase.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Verified against live `requirements.txt`/`package.json` and direct source reads; explicit "zero new dependencies" conclusion cross-checked against every feature |
| Features | MEDIUM | Cross-checked across 5 reference apps (Firefly III, Actual Budget, GnuCash, YNAB, BudgetBakers Wallet) via public docs/wikis, not primary source access to BudgetBakers' internals — UX behavior inferred, not confirmed from source |
| Architecture | HIGH | Every finding verified against live source reads (`models.py`, `tools.py`, `writes.py`, `main.py`, `mcp_server.py`, `query.py`, UI components, Alembic migration 008) |
| Pitfalls | HIGH | Grounded directly in monai's own schema/code and documented project incident history (memory), not generic best-practice guessing |

**Overall confidence:** HIGH

### Gaps to Address

- **Category mapping is not automatable:** the 74-distinct-string review (confirmed today) must be done by a human before Phase 1's migration DDL is written — flag this explicitly in Phase 1 planning as a blocking manual step, not a coding task.
- **Account type audit:** the 4 live accounts (all NULL) must be manually classified during Phase 2, not defaulted — with only 4 accounts this is trivial but must not be skipped or auto-inferred.
- **AccountManager.tsx type-field UX is an open decision:** architecture research flags that investment-typed `accounts` rows likely shouldn't exist at all (investment money lives in `platforms`), so whether the account manager UI needs a type dropdown or a fixed/hidden "liquid" field should be resolved during Phase 6 planning, not assumed.
- **Records tab platform-detail deep-linking:** architecture research recommends a client-side detail panel (no new dynamic route) but flags this as open if shareable URLs to a specific platform turn out to matter — confirm during Phase 6/7 planning.
- **BudgetBakers Wallet internal mechanics:** feature research is MEDIUM confidence specifically because Wallet's transfer/buy-sell/category-delete mechanics are inferred from public support docs, not source — if any Phase discovers the reference product actually behaves differently, prefer monai's own PROJECT.md decisions (already stated) over the inferred Wallet behavior.

## Sources

### Primary (HIGH confidence)
- `backend/models.py`, `backend/tools.py`, `backend/writes.py`, `backend/main.py`, `backend/mcp_server.py`, `backend/query.py`, `backend/portfolio.py`, `backend/schemas.py`, `backend/fx.py` — full or targeted reads, live source of truth
- `alembic/versions/008_fx_rate_cache.py` — migration authoring convention
- `ui/app/components/Nav.tsx`, `ui/app/cashflow/{AccountManager,TransactionModal,CategoryManager}.tsx`, `ui/app/investments/PlatformManager.tsx`, `ui/app/styles.ts` — existing UI extension points
- `.planning/PROJECT.md` — v1.2 scope, constraints, decisions D01–D17, FX-03/04/05 trail
- Live DB checks (orchestrator-confirmed 2026-07-18): 74 distinct category strings (`category == raw_category` in count); 4 accounts, all `type IS NULL`
- Project memory: BTC price_cache USD/IDR conflation incident, holdings.ticker double unique constraint+index, orphan NULL-platform_id holdings, chat-tool-dual-registration, TOOLS-registry-mutates-to-26

### Secondary (MEDIUM confidence)
- Firefly III docs (transactions, exchange rates, currencies, reconciliation) — transfer/FX pairing patterns
- Actual Budget docs + GitHub issue #5694 — split-transfer desync bug as a cautionary case study
- GnuCash guide (stock transaction assistant, buying/selling shares) — cash-leg-required convention for buy/sell
- YNAB support docs — balance-adjustment-as-named-record-type convention
- BudgetBakers Wallet support articles — 3-level category hierarchy and hard-block category delete (explicit reference product)

### Tertiary (LOW confidence)
- None flagged separately — the "net worth double-counting bug" framing as an industry-wide named failure mode is architectural inference (MEDIUM-HIGH per FEATURES.md), not a cited case study.

---
*Research completed: 2026-07-18*
*Ready for roadmap: yes*
