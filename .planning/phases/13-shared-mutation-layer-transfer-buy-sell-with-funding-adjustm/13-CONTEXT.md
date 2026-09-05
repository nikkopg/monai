# Phase 13: Shared Mutation Layer — Transfer, Buy/Sell-with-Funding, Adjustment Writes - Context

**Gathered:** 2026-07-26
**Status:** Ready for planning

<domain>
## Phase Boundary

Add atomic, pair-aware `apply_*` functions to `backend/writes.py` for every new
money-movement type — **liquid→liquid transfer**, **liquid→investment transfer**,
**funded buy/sell**, **balance adjustment**, and (already present) **category
edit** — plus a one-time **retro-pairing migration** for historical imported
transfers. Every new write goes through the single trusted mutation layer so the
agent confirm-path (`_execute_proposal_payload`) and the direct REST endpoints
(Phase 14) can never diverge on audit-logging, Decimal handling, or atomicity.

Requirements: ACCT-02, XFER-01, XFER-02, XFER-03, XFER-04, XFER-05.

**Backend mutation layer + one migration only.** OUT of this phase: REST
endpoints, agent/MCP tool registration, and the confirm-before-write proposal
wiring for these new operations (all Phase 14); net-worth aggregation (Phase 15);
all UI (Phases 16–17). This phase produces the `apply_*` functions and their
tests; nothing calls them from an endpoint or a tool yet.

</domain>

<decisions>
## Implementation Decisions

> All decisions below are the **recommended option**, locked at the user's
> instruction ("go with all recs"). Any can be vetoed before planning.

### Atomicity / transaction boundary
- **D-01:** New multi-row writes **compose the existing single-entity `apply_*`
  primitives inside one new `apply_*` function** and, like every function in
  `writes.py`, **never commit** — the single caller-owned commit (one confirm →
  one `db.commit()`) is what makes both legs atomic. This is the seam the module
  already documents ("the caller owns the transaction boundary"); no new
  transaction-management machinery is introduced. A partial write is impossible
  because nothing between the two `apply_*` calls commits.
- **D-02:** Each new operation writes its **own AuditLog rows** (one per entity
  mutated), consistent with the existing one-mutation-one-audit-row rule. A
  transfer therefore audits both legs; a funded buy/sell audits the cash leg and
  the holding/portfolio-event update.

### Pairing + leg-protection (SC #1)
- **D-03:** A liquid→liquid transfer writes **two paired `Transaction` rows**
  sharing a `transfer_pair_id`, both `is_transfer = true`, in one commit. The
  pair id links them (self-referential or shared-group-id — planner's call per
  Phase 12's locked column role).
- **D-04:** "Editing/deleting one leg is blocked outside pair-aware functions" is
  enforced at the **application layer**: `apply_edit_transaction` /
  `apply_delete_transaction` **raise `ValueError` when the target row has a
  non-NULL `transfer_pair_id`** unless called through the pair-aware transfer
  function (which passes an explicit override/flag). Chosen over a DB trigger to
  stay consistent with correctness-by-construction and the repo's LLM-never-emits-SQL,
  no-triggers precedent. Failure mode is a loud raise, not silent corruption.

### Liquid→investment transfer (SC #2, XFER-02)
- **D-05:** Writes **one `Transaction` on the liquid source account**
  (`is_transfer = true`) **linked to a new `PortfolioEvent` deposit** via
  `portfolio_events.source_account_id`, composed in one function that reuses the
  existing `apply_add_portfolio_event`. Investment money is **never** turned into
  a synthetic `accounts` row (locked prior decision — that is how the double-count
  bug returns by construction).

### Funded buy/sell (SC #3, XFER-03)
- **D-06:** A funded buy/sell writes the **cash-leg `Transaction`** (debits the
  chosen liquid source, e.g. Stockbit RDN cash) **and the holding/portfolio-event
  update together in one function, one commit** — never two round trips. Reuses
  `apply_add_portfolio_event` + `recompute_holding_from_events` so holding
  recomputation stays the single source of truth for positions.

### Balance adjustment (SC #4, ACCT-02)
- **D-07:** Setting an account balance writes a **normal `Transaction` row whose
  amount is the delta** (`target − current_derived_balance`) on that account,
  tagged as an **"Adjustment"** record. The account balance itself stays
  **derived** (sum of transactions), never a stored column — the adjustment row
  is the only thing written. The delta is computed against the live derived
  balance at write time.
- **D-08:** Adjustment rows are **excluded from spending/income/net cashflow
  totals** (an adjustment is neither spending nor income). Recommended mechanism:
  mark them so they fall out of the existing `is_transfer = false` cashflow
  filter (either `is_transfer = true`, or a dedicated adjustment flag/category the
  cashflow view also excludes). **Planner's discretion on the exact tag**, with the
  hard constraint that adjustments (a) DO affect the derived account balance and
  (b) do NOT appear in cashflow spending/income totals. Note the Records-tab
  labeling tradeoff if `is_transfer` is reused (it would read as "transfer").

### Cross-currency / dual amounts (SC #5, XFER-04)
- **D-09:** Dual amounts (sent + received, each with its own currency) are carried
  by the **two paired rows themselves** — leg A has the sent amount+currency, leg
  B has the received amount+currency. **No new `received_amount`/`received_currency`
  columns.** For a funded cross-currency buy, the cash-leg `Transaction.currency`
  and the `PortfolioEvent.currency` are the two sides. This reuses the existing
  per-row `amount`/`currency` and needs no schema change.
- **D-10:** **No write path forces a live-only FX rate.** When an IDR-value is
  needed for a foreign leg, it comes from the existing historical FX cache
  (`backend/fx.py` `get_rate()` keyed by `(rate_date, base, quote)`), re-fetched
  by the entry's date — reproducible, never the moving "latest" rate. Writes
  accept both amounts as given; FX is a read-time valuation concern, not a
  write-time requirement.

### Retro-pairing migration (SC #6, XFER-05)
- **D-11:** A **one-time migration pass** (next revision after `010`) matches
  historical imported transfer rows and backfills `transfer_pair_id`. Match
  predicate (recommended, strict): **same date + equal absolute amount + opposite
  sign + two distinct accounts**, both already `is_transfer = true` (or the
  importer's transfer heuristic). A row that matches **exactly one** counterpart
  is paired; **zero or multiple** candidates → **left unpaired and flagged**
  (logged + a recoverable marker), **never guessed**. Non-destructive and
  idempotent, per the project's migration mandate.

### Claude's Discretion
- Exact `apply_*` function names/signatures and how far to decompose vs inline the
  composed legs — follow the existing `writes.py` idiom.
- `transfer_pair_id` shape (self-referential id vs shared group id) and the FK/index
  details — planner's call, consistent with Phase 12's locked column roles.
- The exact adjustment exclusion tag (D-08) and Records-labeling tradeoff.
- Retro-pairing migration internals: exact flag/marker for unmatched rows, whether
  a same-day tie-window is allowed, revision structure — follow the `010` /
  `009_category_hierarchy.py` non-destructive, idempotent, parity-checked precedent.
- Whether new functions live in `writes.py` directly or a submodule — default:
  same file, matching the 26-function precedent, unless size forces a split.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & roadmap
- `.planning/ROADMAP.md` §"Phase 13: Shared Mutation Layer" — goal + 6 success
  criteria (paired-leg atomicity & leg-protection, liquid→investment link, funded
  buy/sell one-commit, derived-balance adjustment, dual-amount cross-currency,
  historical retro-pairing).
- `.planning/REQUIREMENTS.md` §"Connection layer (XFER)" + ACCT-02 — the six
  requirements this phase closes (ACCT-02, XFER-01..05); defines why
  `transfer_pair_id` (Tx↔Tx) and `source_account_id` (Tx↔PortfolioEvent) exist.
- `.planning/PROJECT.md` §"Key Decisions" — never-fabricate, non-destructive
  migration, confirm-before-write, and the pairing model (investment money never
  becomes an `accounts` row).

### Prior phase context (do NOT reopen)
- `.planning/phases/12-typed-accounts-transfer-funding-schema-foundations/12-CONTEXT.md`
  — the columns this phase writes were **created** in Phase 12: `transfer_pair_id`,
  `source_account_id`, constrained `accounts.type`. D-02/D-03 there lock the
  account audit: **Stockbit is liquid broker cash** (valid funded-buy source);
  "Investments" (id 3) is the investment account excluded from cashflow.

### Code to read before implementing
- `backend/writes.py` — the mutation layer being extended. Note the module
  contract (L10–14): one mutation + one AuditLog row per `apply_*`, **never
  commit**. `apply_add_transaction` (L54), `apply_add_portfolio_event` (L247),
  `apply_edit_transaction`/`apply_delete_transaction` (L79/L98, get the pair guard).
- `backend/main.py` `_execute_proposal_payload` + the REST endpoints (`db.commit()`
  at L221/239/294/315/333/384…) — the caller side that owns the commit boundary;
  shows the one-confirm-one-commit pattern the new functions rely on.
- `backend/portfolio.py` `recompute_holding_from_events` — reuse for the funded
  buy/sell holding update (single source of truth for positions).
- `backend/fx.py` `get_rate()` + `models.py` `fx_rate_cache` (L321) — historical,
  date-keyed FX for cross-currency valuation (D-10). Never live-only.
- `alembic/versions/` — migrations `001`–`010` at **repo root**; retro-pairing
  is the next revision. `009_category_hierarchy.py` and `010` are the analogs for
  a backfill-on-live-financial-data migration.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `backend/writes.py` `apply_*` primitives (26 functions) — compose these; the
  never-commit contract gives multi-row atomicity for free under one caller commit.
- `apply_add_portfolio_event` (writes.py:247) — reused by both liquid→investment
  transfer and funded buy/sell.
- `recompute_holding_from_events` (backend/portfolio.py) — holding recomputation
  for funded buy/sell.
- `_get_or_create_account` (backend/importer.py:110) — account resolution already
  used inside `apply_add_transaction`.
- `get_rate()` (backend/fx.py) + `fx_rate_cache` — date-keyed historical FX.

### Established Patterns
- **Caller owns the transaction boundary** (`writes.py` docstring L10–14): every
  `apply_*` mutates one entity + writes one AuditLog row and does NOT commit.
  Atomicity for transfers/funded trades = compose + one caller `db.commit()`.
- **Dual call-path convergence**: agent confirm (`main.py:_execute_proposal_payload`)
  and REST endpoints BOTH route through `writes.py` (why the layer exists). Phase 13
  only adds functions; Phase 14 wires callers.
- **Money type**: `Numeric(18,2)` / `Decimal`; `str()` before `Decimal()` is
  LOAD-BEARING (avoids float artifacts) — see writes.py:62,90.
- **Per-row `amount` + `currency`** already exist on `Transaction` and
  `PortfolioEvent` — dual amounts need no new columns (D-09).
- Migrations non-destructive + idempotent on live data (PROJECT.md mandate).

### Integration Points
- Live DB has 4 accounts (ids 1,2,3,559). Retro-pairing runs against real imported
  history — must flag-not-guess unmatched rows.
- **Dual/triple registration gotcha does NOT bite this phase** (no new agent tools
  or endpoints here — that's Phase 14). Keep it in mind for the handoff.
- Deploy note: committed code ≠ running container; `docker compose up -d --build`
  before any live verification (prior-phase lesson, in memory).

</code_context>

<specifics>
## Specific Ideas

- The `writes.py` never-commit contract is the load-bearing design fact for this
  whole phase: it is *why* "one confirmation, one commit, never two round trips"
  (SC #3) is achievable without new transaction machinery.
- Stockbit-as-liquid-broker-cash (Phase 12 D-03) is the concrete funded-buy source:
  liquid Stockbit → buy → holding, all in one commit.
- The `-45.9M "Investments"` account (Phase 12) is why investment money stays a
  `PortfolioEvent` linked via `source_account_id`, never a synthetic `accounts` row.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope. Category-edit writes already exist in
`writes.py` (`apply_edit_category`/`apply_rename_category`/`apply_merge_category`)
and are only *reused* here, not rebuilt. REST/agent/MCP registration for all new
writes is explicitly Phase 14; net-worth aggregation is Phase 15; UI is Phases 16–17.

</deferred>

---

*Phase: 13-Shared Mutation Layer — Transfer, Buy/Sell-with-Funding, Adjustment Writes*
*Context gathered: 2026-07-26*
