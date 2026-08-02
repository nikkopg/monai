# Roadmap: monai

**Project:** Self-hosted agentic personal-finance app (cashflow + investments + MCP server)

## Milestones

- ✅ **v1.0 — Agentic Chat + Investments + Multi-page UI + MCP** — Phases 1-7, 30 plans (shipped 2026-07-17). See [milestones/v1.0-ROADMAP.md](milestones/v1.0-ROADMAP.md).
- ✅ **v1.1 — UI Redesign ("Paper" Aesthetic)** — Phases 8-10, 3 plans (shipped 2026-07-18). See [milestones/v1.1-ROADMAP.md](milestones/v1.1-ROADMAP.md).
- 🚧 **v1.2 — Connected Ledger — Liquids ↔ Investments** — Phases 11-17 (in progress).

## Phases

<details>
<summary>✅ v1.0 (Phases 1-7) — SHIPPED 2026-07-17</summary>

- [x] Phase 1: Schema Foundation + Auth (3/3 plans) — completed 2026-06-21
- [x] Phase 2: Agentic Loop + Confirm-Before-Write (3/3 plans) — completed 2026-07-16
- [x] Phase 3: Multi-Page UI Shell + Settings (3/3 plans) — completed 2026-07-04
- [x] Phase 4: Cashflow Dashboard + CRUD (7/7 plans) — completed 2026-07-06
- [x] Phase 5: Investment Subsystem (6/6 plans) — completed 2026-07-11
- [x] Phase 6: MCP Server (2/2 plans) — completed 2026-07-15
- [x] Phase 7: Investment Subsystem v2 — multi-platform, multi-currency, cash, gold, viz (5/5 plans) — completed 2026-07-13

Full phase detail: [milestones/v1.0-ROADMAP.md](milestones/v1.0-ROADMAP.md)

</details>

<details>
<summary>✅ v1.1 UI Redesign — "Paper" Aesthetic (Phases 8-10) — SHIPPED 2026-07-18</summary>

- [x] Phase 8: Design Foundation + App Shell (1/1 plan) — completed 2026-07-18
- [x] Phase 9: Cashflow + Chat Restyle (1/1 plan) — completed 2026-07-18
- [x] Phase 10: Investments + Settings + Consistency Sweep (1/1 plan) — completed 2026-07-18

Full phase detail: [milestones/v1.1-ROADMAP.md](milestones/v1.1-ROADMAP.md)

</details>

### 🚧 v1.2 Connected Ledger — Liquids ↔ Investments (In Progress)

**Milestone Goal:** Restructure monai around a single trustworthy net worth: liquids and
investments as two connected subsystems that never double-count, linked by real
transfer/buy-sell mechanics, with BudgetBakers-grade record and category management.

- [x] **Phase 11: Category Hierarchy — Schema, Audit, Migration** - First-class 3-level categories replace free-string `category`, migrated via human-reviewed mapping with parity checks (completed 2026-07-19)
- [x] **Phase 12: Typed Accounts + Transfer/Funding Schema Foundations** - `accounts.type` audited + constrained to liquid/investment; additive columns for transfer pairing and funded portfolio events (completed 2026-07-25)
- [x] **Phase 13: Shared Mutation Layer — Transfer, Buy/Sell-with-Funding, Adjustment Writes** - `writes.py` gains atomic, pair-aware `apply_*` functions for every new money-movement type (completed 2026-07-30)
- [x] **Phase 14: REST Endpoints + Agent/MCP Tool Registration** - New endpoints wired to Phase 13's writes; write tools registered on the agent and kept off the MCP read-only surface (completed 2026-07-30)
- [x] **Phase 15: Net Worth Aggregation + Dashboard** - Main dashboard shows net worth as liquid + investment sums that never overlap (completed 2026-07-31)
- [x] **Phase 16: UI — Extend Existing Components** - Account manager, platform detail, and the record modal grow to cover typed accounts, PnL/buy-sell history, and Expense/Income/Transfer entry (completed 2026-08-01)
- [ ] **Phase 17: UI — New Surfaces (Records Tab, Categories Manager)** - Date-grouped Records ledger with filters/bulk actions; category tree manager in Settings

## Phase Details

### Phase 11: Category Hierarchy — Schema, Audit, Migration

**Goal**: Categories exist as first-class, hierarchical entities that every existing transaction is correctly mapped onto, with zero data loss
**Depends on**: Nothing (first phase of v1.2; builds on v1.1's shipped schema)
**Requirements**: CAT-01, CAT-02, CAT-03, CAT-04
**Success Criteria** (what must be TRUE):

  1. Every one of the 74 existing category strings maps to a reviewed category in a 3-level hierarchy (name, color, icon, parent) — no transaction silently loses its category
  2. Row-count and sum-of-amount parity holds between pre- and post-migration category totals (verified, not assumed)
  3. User can add, edit, and delete categories in Settings; deleting a category with records in use is blocked until reassigned (no orphaned records)
  4. Record forms, filters, and dashboard charts read from the new category hierarchy (not the free-string column)

**Plans**: 7 plans

Plans:
**Wave 1**

- [x] 11-01-PLAN.md — Category schema + migration 009 with TDD'd mapping/parity helpers (CAT-01, CAT-03)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 11-02-PLAN.md — Draft 74-string mapping CSV, human review checkpoint (D-06), run migration with parity + idempotency proof (CAT-03)

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 11-03-PLAN.md — Category write layer + REST CRUD with depth cap and block-or-reassign guard (CAT-01, CAT-02)
- [x] 11-04-PLAN.md — Hierarchy-aware agent tools (rollup, descendants, tree) + dual registration (CAT-04)

**Wave 4** *(blocked on Wave 3 completion)*

- [x] 11-05-PLAN.md — Dual-write category_id + Uncategorized fallback on all transaction write paths (CAT-03)
- [x] 11-06-PLAN.md — Settings expandable tree manager + 13-swatch palette, moved from Cashflow (CAT-02, CAT-04)

**Wave 5** *(blocked on Wave 4 completion)*

- [x] 11-07-PLAN.md — Cashflow summary rollup shape + CategoryDonut drill-down (CAT-04)

**Research**: true — category migration mechanics (idempotent, re-runnable, parity-asserting Alembic data migration) need a focused pass; the 74-string mapping itself is a human-review task, not automatable

### Phase 12: Typed Accounts + Transfer/Funding Schema Foundations

**Goal**: The schema can distinguish liquid from investment accounts with certainty, and has the columns needed to pair transfers and funded portfolio events
**Depends on**: Phase 11 (schema-first sequencing; independent data but shares migration discipline)
**Requirements**: ACCT-03
**Success Criteria** (what must be TRUE):

  1. All 4 live accounts are manually audited and classified liquid/investment — none left NULL or auto-inferred
  2. `accounts.type` is DB-enforced (closed set, CHECK constraint) and investment-typed accounts are excluded from every cashflow total (spending/income/net) — the double-count bug is structurally impossible, not just avoided by convention
  3. `transactions.transfer_pair_id` and `portfolio_events.source_account_id` exist (nullable, indexed) so later phases can pair records without further migrations

**Plans**: 3/3 plans complete

- [x] 12-01-PLAN.md — Wave 0 validation scaffold: test_typed_accounts.py + test_cashflow_view.py encoding all 3 success criteria (RED-first)
- [x] 12-02-PLAN.md — Migration 010 (backfill→assert→constrain accounts.type, add pairing columns, NOT EXISTS view) + models.py ORM match
- [x] 12-03-PLAN.md — Switch every cashflow total in tools.py to FROM cashflow_transactions (application-layer exclusion)

**Research**: true — FX precision and account-type audit both carry data-quality risk on live financial data; confirm the Alembic nullable→backfill→constrain idiom before writing DDL

### Phase 13: Shared Mutation Layer — Transfer, Buy/Sell-with-Funding, Adjustment Writes

**Goal**: Every new kind of money movement (transfer, funded buy/sell, balance adjustment, category edit) can be written atomically through one trusted layer
**Depends on**: Phase 12 (needs `transfer_pair_id`, `source_account_id`, constrained `accounts.type`)
**Requirements**: ACCT-02, XFER-01, XFER-02, XFER-03, XFER-04, XFER-05
**Success Criteria** (what must be TRUE):

  1. A liquid→liquid transfer writes two paired transaction rows (via `transfer_pair_id`) in one DB transaction; editing or deleting one leg is blocked outside pair-aware functions
  2. A liquid→investment transfer writes a transaction row linked to a portfolio deposit event (via `source_account_id`) in one DB transaction
  3. A funded buy/sell writes the cash-leg transaction and the holding/portfolio-event update together, in one confirmation and one commit — never as two round trips
  4. Setting an account's balance produces a visible "Adjustment" record reflecting the delta; the account balance itself stays derived, never stored
  5. Cross-currency transfer/buy-sell entries accept dual amounts (sent + received, each with its own currency); no write path forces a live-only FX rate
  6. Historical imported transfer rows are retro-paired by a migration pass (matched by date+amount); unmatched rows are flagged and left as-is, not guessed

**Plans**: 5/5 plans complete

Plans:
**Wave 1**

- [x] 13-01-PLAN.md — RED test scaffold for all 5 writes.py apply_* functions + leg guard + D-08 exclusion (ACCT-02, XFER-01..04)
- [x] 13-02-PLAN.md — Retro-pairing migration 011 + standalone matching-logic test (XFER-05)

**Wave 2** *(blocked on 13-01)*

- [x] 13-03-PLAN.md — apply_add_transfer (paired liquid→liquid) + allow_paired leg-protection guard (XFER-01)

**Wave 3** *(blocked on 13-03 — shared writes.py)*

- [x] 13-04-PLAN.md — apply_add_investment_transfer + apply_add_funded_buy/sell (XFER-02, XFER-03, XFER-04)

**Wave 4** *(blocked on 13-04 — shared writes.py)*

- [x] 13-05-PLAN.md — apply_add_balance_adjustment (unfiltered derived-balance delta) (ACCT-02)

### Phase 14: REST Endpoints + Agent/MCP Tool Registration

**Goal**: Every new write from Phase 13 is reachable from the REST API and from agentic chat, with write tools correctly excluded from the external MCP read-only surface
**Depends on**: Phase 13
**Requirements**: CHAT-09
**Success Criteria** (what must be TRUE):

  1. User can trigger a transfer, funded buy/sell, balance adjustment, or category change via chat, going through the existing confirm-before-write proposal flow
  2. Each new write tool is registered in both `tools.py`'s TOOLS dict and `query.py`'s FunctionTool list (no dual-registration gap)
  3. New write tools do not appear on the MCP read-only surface exposed to external clients (correct position relative to `READ_TOOL_NAMES`)
  4. REST endpoints for the new operations exist and route through Phase 13's `apply_*` functions, not ad-hoc SQL

**Plans**: 3/3 plans complete

Plans:
**Wave 1**

- [x] 14-01-PLAN.md — Wave-0 RED validation scaffold: 5 propose→confirm tests + 5 direct-REST tests + named-tool MCP-exclusion assertions (CHAT-09)

**Wave 2** *(blocked on 14-01)*

- [x] 14-02-PLAN.md — Agent path: 5 propose_* tools (exact apply_* payload shapes), dual registration, confirm dispatch + KeyError→422 guard (CHAT-09)

**Wave 3** *(blocked on 14-02 — shared main.py)*

- [x] 14-03-PLAN.md — Direct REST path: 5 *Create schemas + 5 require_api_key routes through apply_* with 422/401 validation (CHAT-09)

### Phase 15: Net Worth Aggregation + Dashboard

**Goal**: The user has one trustworthy number for their entire financial life, with visibility into how it splits
**Depends on**: Phase 12 (needs `accounts.type` constrained and reconciled), Phase 13 (needs transfer/funding writes so balances reflect reality)
**Requirements**: NW-01, NW-02
**Success Criteria** (what must be TRUE):

  1. User sees a main dashboard where net worth = liquid accounts + investment platforms, with each real account/holding counted exactly once
  2. User sees the liquid vs investment split with a per-side breakdown (not just the combined total)
  3. The net-worth query's account-type filter is asserted to cover 100% of accounts — no silently dropped or double-included row

**Plans**: 2 plans

- [x] 15-01-PLAN.md — Backend `net_worth` composed read (+ `GET /net-worth`), coverage assertion, dual read-tool registration, tests
- [x] 15-02-PLAN.md — `/cashflow` dashboard: server-sourced net-worth hero (fix double-count) + liquid/investment split + per-side breakdowns

**UI hint**: yes

### Phase 16: UI — Extend Existing Components

**Goal**: The account manager, platform manager, and transaction entry modal cover the full set of new record types without being rebuilt
**Depends on**: Phase 14 (needs stable REST/agent contract for the new writes)
**Requirements**: ACCT-01, PLAT-02, REC-04
**Success Criteria** (what must be TRUE):

  1. User can add, edit, and remove liquid accounts in the account manager
  2. Platform manager reaches CRUD parity with the account manager (add/edit/remove platforms)
  3. User can add a record via a modal with an Expense / Income / Transfer segmented form (amount + currency, account, category picker, date-time, note, "add another")

**Plans**: 3/3 plans complete

- [x] 16-01-PLAN.md — Wave 0 e2e test scaffolds (record-modal, platform-crud, account type:liquid) — RED baseline for REC-04/PLAT-02/ACCT-01
- [x] 16-02-PLAN.md — Extend TransactionModal: Expense/Income/Transfer segmented form, sign derivation, currency, save-&-add-another, edit-leg lock (REC-04)
- [x] 16-03-PLAN.md — AccountManager type:liquid on create + PlatformManager kind-editable edit row (ACCT-01, PLAT-02)

**UI hint**: yes

### Phase 17: UI — New Surfaces (Records Tab, Categories Manager)

**Goal**: The user can browse, filter, and bulk-manage their full transaction history, and drill into a platform's performance, on new purpose-built screens
**Depends on**: Phase 16 (reuses the extended modals/managers), Phase 15 (Records tab surfaces transfer pairs and dashboard-consistent data)
**Requirements**: REC-01, REC-02, REC-03, REC-05, PLAT-01
**Success Criteria** (what must be TRUE):

  1. User can browse all records in a date-grouped ledger showing a daily net per group
  2. User can filter records by search, account, category, record type, amount range, and transfer visibility
  3. User can select multiple records and bulk delete or bulk recategorize
  4. Transfer pairs display as one logical unit; editing or deleting affects both legs atomically (single-leg edits blocked in the UI, matching the Phase 13 backend guarantee)
  5. User can open a platform detail view with a PnL tab and a buy/sell history tab

**Plans**: 5 plans

Plans:
**Wave 1** *(RED test scaffolds — parallel)*

- [ ] 17-01-PLAN.md — Backend RED test scaffolds: filters/paging, bulk, pair-aware delete, platform reads (REC-01, REC-02, REC-03, REC-05, PLAT-01)
- [ ] 17-02-PLAN.md — Frontend e2e RED scaffolds: records ledger + platform detail (REC-01, REC-02, REC-03, REC-05, PLAT-01)

**Wave 2** *(blocked on 17-01)*

- [ ] 17-03-PLAN.md — Backend: GET /transactions filters + transfer_pair_id + bulk endpoints + pair-aware delete retrofit + platform-detail reads (REC-01, REC-02, REC-03, REC-05, PLAT-01)

**Wave 3** *(blocked on 17-02 + 17-03 — parallel)*

- [ ] 17-04-PLAN.md — Records surface: date-grouped ledger, filter bar, transfer-pair collapse, multi-select bulk actions (REC-01, REC-02, REC-03, REC-05)
- [ ] 17-05-PLAN.md — Platform detail surface: PnL + Buy/Sell segmented tabs, Investments link-out (PLAT-01)

**UI hint**: yes

## Backlog

Deferred to v2 (see next milestone's requirements):

- QRY-01: Recurring-charge / subscription detection
- QRY-02: Compare two arbitrary periods side by side
- QRY-03: Token-by-token streaming of agent responses
- INVX-02: Automated reksadana NAV feed
- REC-F1: Labels on records (free-form multi-tags separate from categories)
- CAT-F1: Nature-of-Spending (Need/Want) classification per category
- CAT-F2: Hide toggle for categories

## Progress

**Execution Order:**
Phases execute in numeric order: 11 → 12 → 13 → 14 → 15 → 16 → 17

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|-----------------|--------|-----------|
| 1. Schema Foundation + Auth | v1.0 | 3/3 | Complete | 2026-06-21 |
| 2. Agentic Loop + Confirm-Before-Write | v1.0 | 3/3 | Complete | 2026-07-16 |
| 3. Multi-Page UI Shell + Settings | v1.0 | 3/3 | Complete | 2026-07-04 |
| 4. Cashflow Dashboard + CRUD | v1.0 | 7/7 | Complete | 2026-07-06 |
| 5. Investment Subsystem | v1.0 | 6/6 | Complete | 2026-07-11 |
| 6. MCP Server | v1.0 | 2/2 | Complete | 2026-07-15 |
| 7. Investment Subsystem v2 | v1.0 | 5/5 | Complete | 2026-07-13 |
| 8. Design Foundation + App Shell | v1.1 | 1/1 | Complete | 2026-07-18 |
| 9. Cashflow + Chat Restyle | v1.1 | 1/1 | Complete | 2026-07-18 |
| 10. Investments + Settings + Consistency Sweep | v1.1 | 1/1 | Complete | 2026-07-18 |
| 11. Category Hierarchy | v1.2 | 7/7 | Complete    | 2026-07-20 |
| 12. Typed Accounts + Transfer Schema | v1.2 | 3/3 | Complete    | 2026-07-25 |
| 13. Shared Mutation Layer | v1.2 | 5/5 | Complete   | 2026-07-30 |
| 14. REST + Agent/MCP Tools | v1.2 | 3/3 | Complete    | 2026-07-31 |
| 15. Net Worth Dashboard | v1.2 | 2/2 | Complete   | 2026-07-31 |
| 16. UI — Extend Existing | v1.2 | 3/3 | Complete   | 2026-08-01 |
| 17. UI — New Surfaces | v1.2 | 0/5 | Planned | - |

---
*Roadmap created: 2026-06-21 · v1.0 archived 2026-07-17 · v1.1 archived 2026-07-18 · v1.2 roadmap added 2026-07-18*
