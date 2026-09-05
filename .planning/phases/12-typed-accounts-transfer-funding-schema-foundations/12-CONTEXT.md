# Phase 12: Typed Accounts + Transfer/Funding Schema Foundations - Context

**Gathered:** 2026-07-25
**Status:** Ready for planning

<domain>
## Phase Boundary

Make `accounts.type` a DB-enforced `liquid`/`investment` discriminator — every one of the 4 live accounts manually audited and classified (no auto-inference) — and make investment-typed accounts excluded from every cashflow total (`spending_total`, `income_total`, `net_total`, `spending_by_category`, and the other transaction aggregates in `backend/tools.py`) *by construction*, not convention. Additionally add nullable, indexed `transactions.transfer_pair_id` and `portfolio_events.source_account_id` so Phase 13 can pair transfer/funding records without another migration. Requirement: ACCT-03.

**Additive schema only.** Out of this phase: the write mechanics that populate the new columns (transfers, funded buy/sell, adjustments — Phase 13), REST/agent/MCP registration (Phase 14), net-worth aggregation using the typed split (Phase 15), and all UI (Phases 16–17). This phase lays the schema + the exclusion invariant; nothing writes a `transfer_pair_id` or `source_account_id` yet.

</domain>

<decisions>
## Implementation Decisions

### Type taxonomy
- **D-01:** `accounts.type` is a **binary** closed set: `liquid` | `investment`, enforced by a CHECK constraint. The constraint gates exactly the cashflow rule (`type='investment'` → excluded). No richer subtype set (no cash/bank/e-wallet split) — finer labels, if ever wanted, are a separate cosmetic concern for a later phase, not this discriminator.

### Account audit (the manual classification — locked, feeds the migration backfill)
- **D-02:** The 4 live accounts classify as:
  - `liquid`: **BCA** (id 2, bank, +297,591,000 IDR), **Cash** (id 1, −61,404,700 IDR), **Stockbit** (id 559, 0 non-transfer balance)
  - `investment`: **Investments** (id 3, −45,879,000 IDR)
- **D-03:** **Stockbit is liquid, deliberately** — it is the broker *cash* account (RDN balance that funds buys), distinct from the stock positions tracked in `holdings`/`platforms`. This makes Stockbit a valid liquid `source_account_id` when Phase 13 funds a buy. Do NOT re-infer it as investment from its name.
- **D-04:** The "Investments" account (id 3) is the real double-count: its −45.9M of non-transfer transactions are investment contributions booked as expenses, depressing net cashflow. Typing it `investment` + the exclusion view removes that phantom spending from every cashflow total.

### Future-account policy
- **D-05:** After backfill, `accounts.type` becomes **NOT NULL** + CHECK(`liquid`,`investment`) + `server_default 'liquid'`. New/imported accounts (incl. the CSV importer's `_get_or_create_account`) auto-get `liquid` — the safe, included, common case; the rare investment account is re-typed by hand. This makes success-criterion #1 ("none left NULL / none auto-inferred") permanent, not merely true at migration time.
- **D-06:** The exclusion predicate keys on `type = 'investment'` (exclude only explicit investment), NOT `type != 'liquid'`. Failure mode of a mis-typed/new account is therefore "shows up in cashflow" (visible, catchable) rather than "silently vanishes from totals" (invisible). Aligns with the project's never-fabricate / honest-failure philosophy.

### Structural exclusion mechanism
- **D-07:** The migration creates a **`cashflow_transactions` DB view** = transactions minus investment-account rows. Every cashflow total in `backend/tools.py` reads `FROM cashflow_transactions` instead of `FROM transactions`. The exclusion lives in the schema, so any query — including future or ad-hoc ones — inherits it. This is the "structurally impossible to forget" mechanism the roadmap's success-criterion #2 demands (chosen over an app-level shared helper, which stays convention).

### Claude's Discretion
- **Exact DDL / Alembic revision structure** for migration `010` (next after `009`): column-type change to NOT NULL, CHECK constraint syntax, index choices for `transfer_pair_id` / `source_account_id`, FK naming. Follow the established repo-root `alembic/versions/` idiom and Phase 11's non-destructive, idempotent, parity-checked precedent.
- **View internals for `cashflow_transactions`:** (a) it MUST keep NULL-`account_id` rows IN (they aren't investment — use `LEFT JOIN` or `NOT EXISTS`/`account_id NOT IN (investment ids)`, never an inner join that drops them); (b) whether the view also bakes in `is_transfer = false` or leaves that clause in the per-query SQL. Pick whichever is cleanest — but the NULL-account_id inclusion is a hard requirement, not discretion.
- **Column semantics for the pairing columns** (roles already locked below): `transfer_pair_id` self-referential vs shared-group-id, `source_account_id` FK target/index — planner's call, consistent with the locked roles.
- **Whether the investment account is also removed from / shown separately in `account_balances`** (a per-account list, not a total). Criterion #2 targets the spending/income/net *totals*; `account_balances` is out of the strict criterion but worth a consistency note.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & roadmap
- `.planning/ROADMAP.md` §"Phase 12: Typed Accounts + Transfer/Funding Schema Foundations" — goal, 3 success criteria (4-account audit, DB-enforced type + structural cashflow exclusion, additive pairing columns), research flag (confirm Alembic nullable→backfill→constrain idiom).
- `.planning/REQUIREMENTS.md` §"Connection layer (XFER)" — XFER-01/02 define why `transfer_pair_id` (Tx↔Tx) and `source_account_id` (Tx↔PortfolioEvent) exist; ACCT-03 is the phase requirement. These columns are *created* here, *written* in Phase 13.
- `.planning/PROJECT.md` §"Key Decisions" — the two pre-roadmap v1.2 decisions that lock the pairing model and the no-auto-infer audit (see below); never-fabricate + non-destructive-migration constraints.

### Migration precedent
- `alembic/versions/` — migrations `001`–`009` at **repo root** (NOT `backend/`); latest is `009_category_hierarchy.py`. Phase 12's migration is `010`. Follow the established revision idiom.
- `.planning/phases/11-category-hierarchy-schema-audit-migration/11-CONTEXT.md` — the "shared migration discipline" Phase 12 inherits: human-reviewed classification (here it's only 4 accounts, done live in this discussion — see D-02), abort-loudly/idempotent migration, parity assertions, dual-write-until-drop where a column transition applies.

### Locked prior decisions (from STATE.md / PROJECT.md — do NOT reopen)
- Liquid↔liquid transfers pair via `transactions.transfer_pair_id`; liquid→investment via `portfolio_events.source_account_id`. Investment money must NEVER become a synthetic `accounts` row (that's how the double-count bug returns by construction).
- `accounts.type` promoted from decorative to DB-enforced discriminator ONLY after manual audit of the live accounts — no auto-inference.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `backend/models.py:46` `Account.type` — currently `String(64), nullable=True`, all 4 rows NULL. This phase tightens it (D-05).
- `backend/models.py` `Transaction` (has `account_id` nullable FK, `is_transfer`) and `PortfolioEvent` (has `platform_id`, no account link) — the two tables getting the additive columns.
- `backend/tools.py` cashflow aggregates that must switch to the view (D-07): `spending_total` (L117), `income_total` (L135), `net_total` (L152), `spending_by_category` (L246, shared CTE at L234–245), `average_daily_spending`/`largest_transactions`/`transaction_count`/`monthly_trend` (all `FROM transactions ... is_transfer = false`), `account_balances` (L472, already joins accounts), `find_transactions` (L536).
- `alembic/versions/009_category_hierarchy.py` — closest migration analog (audit + backfill + constraint on live financial data).

### Established Patterns
- Schema is fully Alembic-managed (`backend/db.py` docstring): bootstrap via `alembic upgrade head` in the Docker entrypoint; no `init_db()`. Migrations are non-destructive on live data (PROJECT.md mandate).
- Correctness-by-construction: LLM never emits SQL; all cashflow reads are parameterized `text()` queries in `tools.py`. The view keeps that intact — it just changes the `FROM`.
- Money type: `Numeric(18,2)` / Python `Decimal` throughout (psycopg3 returns Decimal). Amounts negative = expense, positive = income; `SUM(-amount)` for spending.

### Integration Points
- Live DB has exactly 4 accounts (ids 1,2,3,559) — verified this session via `find_accounts`/`account_balances`. The migration backfill hard-codes D-02's classification.
- `backend/importer.py` `_get_or_create_account` (L110) auto-creates accounts from CSV — with D-05's NOT NULL, it relies on the `server_default 'liquid'` (or must pass a type). Confirm the importer still works post-migration.
- Deploy note: committed code ≠ running container; `docker compose up -d --build` before any live verification (prior-phase lesson, in memory).
- Dual/triple tool-registration gotcha is NOT triggered this phase (no new agent tools) — but keep it in mind; changing a read tool's SQL doesn't change its registration.

</code_context>

<specifics>
## Specific Ideas

- The −45.9M "Investments" account balance is the concrete artifact of the double-count bug — the user recognized it immediately. The success test for this phase is that after the view lands, that −45.9M no longer appears in `spending_total`/`net_total`.
- "Stockbit = broker cash account, not the stock positions" is the user's explicit mental model — it justifies keeping Stockbit liquid and previews the Phase 13 funded-buy flow (liquid Stockbit → buy → holding).

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope. (Richer account subtypes were considered and explicitly rejected for this phase, D-01. Reconciling the "Investments" account's historical −45.9M against the holdings/portfolio subsystem is Phase 13/15 territory, not a new idea.)

</deferred>

---

*Phase: 12-Typed Accounts + Transfer/Funding Schema Foundations*
*Context gathered: 2026-07-25*
