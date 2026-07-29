# Phase 13: Shared Mutation Layer — Transfer, Buy/Sell-with-Funding, Adjustment Writes - Research

**Researched:** 2026-07-30
**Domain:** Backend mutation-layer composition (SQLAlchemy ORM writes + one Alembic data-migration) in an existing FastAPI/Postgres app — no new libraries, no new architecture, pure extension of an established pattern.
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** New multi-row writes compose the existing single-entity `apply_*` primitives inside one new `apply_*` function and, like every function in `writes.py`, never commit — the single caller-owned commit (one confirm → one `db.commit()`) is what makes both legs atomic.
- **D-02:** Each new operation writes its own AuditLog rows (one per entity mutated). A transfer therefore audits both legs; a funded buy/sell audits the cash leg and the holding/portfolio-event update.
- **D-03:** A liquid→liquid transfer writes two paired `Transaction` rows sharing a `transfer_pair_id`, both `is_transfer = true`, in one commit. The pair id links them (self-referential or shared-group-id — planner's call per Phase 12's locked column role).
- **D-04:** "Editing/deleting one leg is blocked outside pair-aware functions" is enforced at the application layer: `apply_edit_transaction`/`apply_delete_transaction` raise `ValueError` when the target row has a non-NULL `transfer_pair_id` unless called through the pair-aware transfer function (which passes an explicit override/flag). Chosen over a DB trigger to stay consistent with correctness-by-construction and the repo's LLM-never-emits-SQL, no-triggers precedent.
- **D-05:** Liquid→investment transfer writes one `Transaction` on the liquid source account (`is_transfer = true`) linked to a new `PortfolioEvent` deposit via `portfolio_events.source_account_id`, composed in one function that reuses `apply_add_portfolio_event`. Investment money is never turned into a synthetic `accounts` row.
- **D-06:** A funded buy/sell writes the cash-leg `Transaction` (debits the chosen liquid source) and the holding/portfolio-event update together in one function, one commit — never two round trips. Reuses `apply_add_portfolio_event` + `recompute_holding_from_events`.
- **D-07:** Setting an account balance writes a normal `Transaction` row whose amount is the delta (`target − current_derived_balance`) on that account, tagged as an "Adjustment" record. The account balance stays derived (sum of transactions), never a stored column. The delta is computed against the live derived balance at write time.
- **D-08:** Adjustment rows are excluded from spending/income/net cashflow totals (an adjustment is neither spending nor income). Recommended mechanism: mark them so they fall out of the existing `is_transfer = false` cashflow filter. **Planner's discretion on the exact tag**, with the hard constraint that adjustments (a) DO affect the derived account balance and (b) do NOT appear in cashflow spending/income totals. Note the Records-tab labeling tradeoff if `is_transfer` is reused.
- **D-09:** Dual amounts (sent + received, each with its own currency) are carried by the two paired rows themselves — leg A has the sent amount+currency, leg B has the received amount+currency. No new `received_amount`/`received_currency` columns.
- **D-10:** No write path forces a live-only FX rate. When an IDR-value is needed for a foreign leg, it comes from the existing historical FX cache (`backend/fx.py` `get_rate()` keyed by `(rate_date, base, quote)`), re-fetched by the entry's date. Writes accept both amounts as given; FX is a read-time valuation concern, not a write-time requirement.
- **D-11:** A one-time migration pass (next revision after `010`) matches historical imported transfer rows and backfills `transfer_pair_id`. Match predicate (recommended, strict): same date + equal absolute amount + opposite sign + two distinct accounts, both already `is_transfer = true`. A row that matches exactly one counterpart is paired; zero or multiple candidates → left unpaired and flagged (logged + a recoverable marker), never guessed. Non-destructive and idempotent.

### Claude's Discretion

- Exact `apply_*` function names/signatures and how far to decompose vs inline the composed legs — follow the existing `writes.py` idiom.
- `transfer_pair_id` shape (self-referential id vs shared group id) and the FK/index details — planner's call, consistent with Phase 12's locked column roles.
- The exact adjustment exclusion tag (D-08) and Records-labeling tradeoff.
- Retro-pairing migration internals: exact flag/marker for unmatched rows, whether a same-day tie-window is allowed, revision structure — follow the `010`/`009_category_hierarchy.py` non-destructive, idempotent, parity-checked precedent.
- Whether new functions live in `writes.py` directly or a submodule — default: same file, matching the 26-function precedent, unless size forces a split.

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope. Category-edit writes already exist in `writes.py` (`apply_edit_category`/`apply_rename_category`/`apply_merge_category`) and are only reused here, not rebuilt. REST/agent/MCP registration for all new writes is explicitly Phase 14; net-worth aggregation is Phase 15; UI is Phases 16–17.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ACCT-02 | User can set an account's balance; the delta is stored as a visible "Adjustment" record (balances stay derived, never a stored field) | Pattern 2 (`Derived Balance Must Include Transfers`), Pitfall 1, Code Examples — defines the exact derived-balance SQL and delta formula; Validation Architecture maps to `test_apply_add_balance_adjustment_delta` |
| XFER-01 | User can transfer between liquid accounts; stored as paired records via `transfer_pair_id` | `transfer_pair_id` Shape section (shared-group-id recommendation), Pattern 1, Code Examples (leg-protection guard); Validation Architecture maps to `test_apply_add_transfer_pairs_both_legs` + `test_paired_leg_edit_blocked` |
| XFER-02 | User can transfer liquid → investment platform (transaction linked to a portfolio deposit event via `source_account_id`) | Architecture Diagram (`apply_add_investment_transfer`), Don't Hand-Roll (`recompute_holding_from_events`); Validation Architecture maps to `test_apply_add_investment_transfer` |
| XFER-03 | Buy/sell requires choosing a liquid source/destination account; one confirmation writes both entries in one DB transaction | Pattern 1 (illustrative `apply_add_funded_buy`), Pitfall 3 (never two commits); Validation Architecture maps to `test_apply_add_funded_buy_one_commit_boundary` |
| XFER-04 | Cross-currency entry uses dual amounts (sent + received, each with currency); USD assets valued in IDR via existing FX cache | D-09/D-10 constraints reproduced verbatim in User Constraints; Don't Hand-Roll (`fx.get_rate`); Validation Architecture maps to `test_funded_buy_dual_currency_legs` + the D-10 static grep check |
| XFER-05 | Historical imported transfer rows are retro-paired by migration (matched by date+amount; unmatched flagged, left as-is) | Runtime State Inventory (652/16 live match audit), Code Examples (retro-pairing SQL), Pitfall 4, Open Question 1; Validation Architecture maps to `test_transfer_retro_pairing.py` |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- **Correctness-by-construction:** "the LLM selects/chains parameterized tools; it never emits SQL." Every new `apply_*` function must use SQLAlchemy `text()` with bound `:param` placeholders exactly like all 26 existing functions — no string-formatted SQL, ever.
- **Safety:** "All agent writes require explicit user confirmation before applying; validated; audit-logged." This phase doesn't wire the confirm path (Phase 14), but the never-commit contract this phase must preserve is the mechanism that makes that safety guarantee possible — a function that commits internally would break the confirm-before-write invariant for whichever caller uses it next.
- **Schema:** CLAUDE.md's Constraints section states "no Alembic today" for migrations — this is **stale**; this session confirmed Alembic is fully wired (`alembic/versions/001`–`010`, `alembic.ini` at repo root, `backend/entrypoint.sh` runs `alembic upgrade head` on every container start). The planner should treat CLAUDE.md's "no Alembic today" line as outdated and follow the actual `009`/`010` precedent instead.
- **Currency:** "Single-currency (IDR) assumption holds for spending; investments may span instruments/currencies." Consistent with D-09/D-10 — transfer legs carry their own `amount`/`currency`, no forced single-currency conversion at write time.
- **Patterns already established and binding on new code:** `_get_or_create_account` helper reuse (not a new lookup), parameterized SQL only, `Decimal(str(x))` before every `Decimal()` construction (money correctness — see writes.py:62,90 inline "LOAD-BEARING" comments).
- **Logging:** standard-library `logging`, module-level loggers — if the retro-pairing migration logs flagged/unmatched rows (Pitfall 4), use `print`/module logging consistent with `009`'s reporting style, not a new logging framework.

## Summary

This phase adds five new `apply_*` functions to `backend/writes.py` (liquid↔liquid
transfer, liquid→investment transfer, funded buy, funded sell, balance
adjustment) plus one Alembic migration (`011`, retro-pairing). Every fact
needed to plan this correctly is already verifiable in the live codebase and
live database — there is no external-library research here, only close
reading of the existing 26-function `writes.py` idiom, the two schema columns
Phase 12 created, and a live-DB audit that surfaced two load-bearing findings
the planner MUST account for.

**Finding 1 (schema drift, blocking):** Phase 12's CONTEXT.md and migration
`010`'s hard-coded `ACCOUNT_TYPE` map assume account ids `{1, 2, 3, 559}` with
"Investments" at id **3**. The **live** database no longer matches: id `3`
does not exist, "Investments" is now id **994**, and five leftover test
accounts (`ResolveAddDualAcct` id 1015, `ResolveAddNoneAcct` id 1016,
`ResolveEditAcct` id 1017, `zzscopetest-account` id 1018, `ZZ Test BCA` id
1019 — all `type=liquid`, all zero-transaction) exist from Phase 12's
UAT/test runs writing directly against the shared live Postgres. **No code in
this phase may hard-code account ids.** The retro-pairing migration and any
funded-buy/transfer helper that needs "the Investments account" or "the
Stockbit account" must resolve by `name`/`type` at run time, never by a
literal id.

**Finding 2 (derived-balance definition, blocking for D-07):**
`backend/tools.py:account_balances` computes `current_balance` with `LEFT
JOIN transactions t ON t.account_id = a.id AND t.is_transfer = false` —
it **deliberately excludes transfer rows**. Live-DB proof: account 1 (Cash)
has `-61,404,700` non-transfer sum and a separate `+60,663,500` transfer sum
— nearly double the magnitude. This exclusion is correct for
`account_balances` (a spending-focused read tool, matches its own docstring
"Transfers excluded from both sums") but is the **wrong** definition for
D-07's "current_derived_balance" — a balance adjustment must reconcile
against the account's *actual* cash position, which includes money that
physically moved via transfers. Reusing `account_balances`'s SQL for the
adjustment delta would produce silently wrong deltas the moment transfers
exist. The adjustment write needs its own `SELECT COALESCE(SUM(amount), 0)
FROM transactions WHERE account_id = :id` — **no `is_transfer` filter at
all** — computed inline in the new `apply_add_balance_adjustment` function
(or a small dedicated helper), not borrowed from `tools.py`.

**Primary recommendation:** Follow the existing `writes.py` idiom exactly —
compose existing `apply_add_transaction` / `apply_add_portfolio_event`
primitives inside five new top-level `apply_*` functions, each still
never-commits, each still writes its own `AuditLog` row(s) per mutated
entity, all money via `Decimal(str(x))`. Add a `transfer_pair_id` self-group
convention (below) since the column is a bare nullable `Integer` with no FK.
Guard `apply_edit_transaction`/`apply_delete_transaction` with a
`transfer_pair_id IS NOT NULL` raise unless an explicit `allow_paired=True`
override is passed by the new pair-aware functions themselves.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Paired transfer write (2 rows, 1 commit) | Persistence (SQLAlchemy ORM, `writes.py`) | — | `writes.py` is the sole mutation layer; no API/agent tier exists yet (Phase 14) |
| Liquid→investment funding link | Persistence (`writes.py` composing `apply_add_transaction` + `apply_add_portfolio_event`) | — | Reuses existing portfolio-event primitive; no new domain logic beyond composition |
| Funded buy/sell holding recompute | Persistence (`backend/portfolio.py:recompute_holding_from_events`) | Persistence (`writes.py` calls it) | Position derivation is already isolated in `portfolio.py`; `writes.py` never re-derives holdings itself |
| Balance-adjustment delta computation | Persistence (`writes.py`, fresh SQL) | — | Must NOT reuse `tools.py:account_balances` (excludes transfers, Finding 2) — a new inline query is required |
| Leg-protection guard (block single-leg edit/delete) | Persistence (`writes.py:apply_edit_transaction`/`apply_delete_transaction`) | — | Application-layer raise, not a DB trigger (repo's LLM-never-emits-SQL / no-triggers precedent, D-04) |
| Retro-pairing backfill | Persistence (Alembic migration `011`) | — | One-time data migration, follows `009`/`010` idiom exactly |
| Historical FX valuation for cross-currency legs | Persistence (`backend/fx.py:get_rate`) | — | Read-time concern (D-10) — writes never call it; only future read/valuation code (Phase 15+) will |

## Package Legitimacy Audit

**Not applicable.** This phase installs no new packages. It extends
`backend/writes.py` (already imports `sqlalchemy`, `backend.models`,
`backend.portfolio`, `backend.importer` — all existing) and adds one Alembic
migration file using the same `sqlalchemy`/`alembic` imports every prior
migration (001–010) already uses. No `pip install` / `requirements.txt`
change is expected for this phase.

## Standard Stack

### Core
No new libraries. This phase is 100% composition of existing project code:

| Component | Location | Purpose | Why reuse (not rebuild) |
|-----------|----------|---------|--------------------------|
| `apply_add_transaction` | `backend/writes.py:54` | Insert one `Transaction` row, resolve/create account, resolve category, one `AuditLog` row | Already handles `Decimal(str(x))`, category resolution (D-08), account get-or-create |
| `apply_add_portfolio_event` | `backend/writes.py:247` | Insert one `PortfolioEvent` row + call `recompute_holding_from_events` | Already handles currency-mismatch validation, FX-aware recompute trigger |
| `recompute_holding_from_events` | `backend/portfolio.py:41` | Rebuild `holdings.quantity`/`avg_cost` from the full event ledger for `(ticker, platform_id)` | Single source of truth for positions (D-01/D-02); funded buy/sell must NOT hand-roll a holding update |
| `_get_or_create_account` | `backend/importer.py:110` | Resolve an account by exact name, create with `server_default 'liquid'` if missing | Already the account-resolution idiom `apply_add_transaction` itself delegates to |
| `get_rate` | `backend/fx.py:85` | Historical, date-keyed FX rate, cache-first, INSERT-only, never fabricates | D-10 hard constraint: writes never force live-only FX; if a valuation is ever needed at write time (not required by any locked decision), this is the only sanctioned path |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Composing existing `apply_*` primitives | A new `TransferService` class / dedicated submodule | Rejected — CONTEXT.md's "Claude's Discretion" defaults to same-file, matching the 26-function precedent; no size pressure yet (writes.py is 662 lines, five more functions ≈ +200 lines, no split needed) |
| Application-layer leg-protection guard (D-04) | A Postgres trigger or `CHECK` constraint blocking single-leg deletes | Rejected by locked decision D-04 — violates the repo's LLM-never-emits-SQL / no-triggers-precedent (correctness-by-construction is enforced in Python, not opaque DB triggers) |
| `transfer_pair_id` self-group convention (below) | A separate `transfer_groups` table with its own PK | Rejected — the column is already a bare nullable `Integer` with no FK (locked by migration 010); adding a new table is schema churn Phase 12 explicitly deferred to Phase 13's discretion, and the group-id-in-place-of-a-shared-table pattern needs zero new DDL |

**Installation:** None required.

**Version verification:** Not applicable — no new dependencies.

## `transfer_pair_id` Shape — Recommended Convention (Claude's Discretion, D-03/D-11)

The column (`transactions.transfer_pair_id: Integer, nullable=True, index=True,
NO FK` — confirmed live via `\d transactions` and `models.py:154-159`) supports
either a self-referential "points at the other leg's id" scheme or a
shared-group-id scheme. **Recommend shared-group-id, seeded from leg A's own
id:**

1. Insert leg A via `apply_add_transaction` (flush → `leg_a.id` populated).
2. Insert leg B via `apply_add_transaction` (flush → `leg_b.id` populated).
3. Set `leg_a.transfer_pair_id = leg_a.id` and `leg_b.transfer_pair_id =
   leg_a.id` (both point at leg A's id — the "group id" is simply leg A's own
   primary key).

**Why this over mutual self-reference (`leg_a.transfer_pair_id = leg_b.id`,
vice versa):** a single `WHERE transfer_pair_id = :group_id` query returns
**both** legs of a pair uniformly (including leg A itself, since
`leg_a.transfer_pair_id = leg_a.id`), with no special-casing for "am I leg A
or leg B" in read code (Phase 14/17). Mutual self-reference requires `WHERE id
= :x OR transfer_pair_id = :x` — a slightly more error-prone query shape a
future read path (REC-05, Phase 17) is more likely to get wrong. This also
gives the retro-pairing migration (D-11) an unambiguous backfill target: for
each matched pair `(row_x, row_y)` with `x.id < y.id`, set both rows'
`transfer_pair_id = x.id`.

**Leg-protection guard (D-04) implementation shape:**

```python
def apply_edit_transaction(db, tx_id, after, before, allow_paired=False):
    tx = db.get(Transaction, tx_id)
    if tx is None:
        raise ValueError(f"Transaction {tx_id} not found during confirm")
    if tx.transfer_pair_id is not None and not allow_paired:
        raise ValueError(
            f"Transaction {tx_id} is one leg of a paired transfer "
            f"(transfer_pair_id={tx.transfer_pair_id}) — edit both legs via "
            "the pair-aware transfer function, not a single-row edit."
        )
    ...  # existing body unchanged
```

Same shape for `apply_delete_transaction`. The new
`apply_edit_transfer_pair`/`apply_delete_transfer_pair` functions (if the
plan adds edit/delete for existing pairs — not explicitly required by
XFER-01..05, REC-05's full edit/delete UI is Phase 17) call the two
underlying `apply_edit_transaction(..., allow_paired=True)` /
`apply_delete_transaction` calls on both legs. **This phase only needs the
guard to exist and raise correctly** — full pair edit/delete composition is
optional here since XFER-01..05 only requires the *write* (create) path;
REC-05 (pair display + atomic edit/delete) is Phase 17.

## Architecture Patterns

### System Architecture Diagram

```
Phase 14 (NOT this phase) — REST endpoint / agent confirm path
        │
        │  calls (both paths converge here)
        ▼
┌─────────────────────────────────────────────────────────────┐
│ backend/writes.py  (THIS PHASE adds 5 new apply_* here)      │
│                                                                │
│  apply_add_transfer(db, leg_a_after, leg_b_after)             │
│    ├─> apply_add_transaction(db, leg_a_after)  ─┐             │
│    ├─> apply_add_transaction(db, leg_b_after)  ─┤ flush both  │
│    └─> set both legs' transfer_pair_id = leg_a.id             │
│                                                                │
│  apply_add_investment_transfer(db, cash_leg_after, event_after)│
│    ├─> apply_add_transaction(db, cash_leg_after, is_transfer) │
│    ├─> apply_add_portfolio_event(db, event_after)             │
│    │       └─> recompute_holding_from_events(db, ticker, pid) │
│    └─> set event.source_account_id = cash_leg account id      │
│                                                                │
│  apply_add_funded_buy / apply_add_funded_sell(db, ...)         │
│    ├─> apply_add_transaction(db, cash_leg_after)  # debit/credit│
│    ├─> apply_add_portfolio_event(db, event_after) # buy/sell   │
│    │       └─> recompute_holding_from_events(...)              │
│    └─> event.source_account_id = cash leg account id           │
│                                                                │
│  apply_add_balance_adjustment(db, account_id, target_balance)  │
│    ├─> SELECT COALESCE(SUM(amount),0) FROM transactions        │
│    │     WHERE account_id = :id   # NO is_transfer filter!     │
│    ├─> delta = target − current_derived_balance                │
│    └─> apply_add_transaction(db, {amount: delta, tag: adjust}) │
│                                                                │
│  apply_edit_transaction / apply_delete_transaction              │
│    └─> NEW: raise ValueError if transfer_pair_id IS NOT NULL   │
│              unless allow_paired=True                          │
│                                                                │
│  (never commits — caller owns db.commit(), same as all 26      │
│   existing functions)                                          │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
   ONE db.commit() by the caller (Phase 14's endpoint/confirm code)
        = atomicity for both legs, free, no new transaction machinery


alembic/versions/011_retro_pair_transfers.py  (THIS PHASE, standalone)
        │
        ▼
  SELECT candidate pairs: same date, amount = -amount, distinct
  account_id, both is_transfer = true
        │
   ┌────┴────┐
   │ exactly  │  UPDATE both rows: transfer_pair_id = min(id)
   │ 1 match  │
   └─────────┘
   ┌─────────┐
   │ 0 or >1  │  leave transfer_pair_id NULL; log to a recoverable
   │ matches  │  marker (see Common Pitfalls #4)
   └─────────┘
```

### Recommended Project Structure
No new files/folders. All five functions land in the existing
`backend/writes.py` (currently 662 lines, 26 functions); the migration lands
in the existing `alembic/versions/` directory as `011_retro_pair_transfers.py`
(or similarly named — confirm the actual next revision id by checking
`010`'s `down_revision` chain at plan time, since `f1a2b3c4d5e6` is `010`'s
own revision id and the new migration's `down_revision` must equal it).

```
backend/
├── writes.py            # +5 apply_* functions, +guard in 2 existing ones
alembic/
└── versions/
    └── 011_retro_pair_transfers.py   # new, down_revision="f1a2b3c4d5e6"
backend/tests/
└── test_write_tools.py  # extend with 5 new test groups (or a new test file
                          # test_transfer_writes.py if size warrants — planner's call)
```

### Pattern 1: Compose, Don't Commit
**What:** Every new `apply_*` function calls one or more existing `apply_*`
primitives and/or does a single parameterized `text()` UPDATE/SELECT, adds
its own `AuditLog` row(s), and returns without calling `db.commit()`.
**When to use:** Every function in this phase, no exceptions — this is the
whole point of D-01.
**Example (funded buy, illustrative shape):**
```python
# Source: backend/writes.py idiom, extrapolated from apply_add_portfolio_event (L247)
def apply_add_funded_buy(db: Session, after: dict) -> dict:
    """Debit a liquid source account and record a buy event, one commit (D-06)."""
    cash_leg_after = {
        "account": after["source_account_name"],   # or resolve by id — planner's call
        "currency": after["cash_currency"],
        "amount": -abs(Decimal(str(after["cash_amount"]))),  # debit
        "category": "Investment",                  # or a dedicated tag — align with D-08 for cashflow exclusion
        "is_transfer": True,                        # excludes from spending/income totals (mirrors D-08 pattern)
        "notes": f"Funded buy: {after['ticker']}",
    }
    tx = apply_add_transaction(db, cash_leg_after)
    event_after = {
        "ticker": after["ticker"],
        "event_type": "buy",
        "quantity": after["quantity"],
        "price": after["price"],
        "platform_id": after["platform_id"],
        "currency": after.get("event_currency"),
    }
    ev = apply_add_portfolio_event(db, event_after)
    ev.source_account_id = tx.account_id
    return {"transaction": tx, "portfolio_event": ev}
```
This is illustrative, not prescriptive on field names — the plan should
define the exact `after`-dict contract per new operation, matching how
`apply_add_transaction`'s `after: dict` is shaped today.

### Pattern 2: Derived Balance Must Include Transfers (Finding 2)
**What:** Any "current account balance" computed as part of a *write* (D-07's
adjustment delta) must be `SUM(amount)` over ALL `transactions` rows for that
`account_id` — no `is_transfer` filter.
**When to use:** `apply_add_balance_adjustment` only. Do not reuse
`tools.py:account_balances`'s SQL (it exists for a different purpose —
spending display — and structurally excludes transfers).
**Example:**
```python
# Source: this phase's own derivation, NOT tools.py:account_balances (Finding 2)
current = db.execute(
    text("SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE account_id = :id"),
    {"id": account_id},
).scalar()
delta = Decimal(str(target_balance)) - Decimal(str(current))
```

### Anti-Patterns to Avoid
- **Hard-coding account ids** (e.g. `INVESTMENTS_ACCOUNT_ID = 3`): the live DB
  proves ids drift (Finding 1). Resolve by `name`/`type='investment'` lookup,
  same idiom as `_get_or_create_account`.
- **Reusing `tools.py:account_balances`'s SQL for the adjustment delta:**
  produces silently wrong deltas (Finding 2) — see Pattern 2.
- **A DB trigger for leg-protection:** explicitly rejected by D-04 (repo's
  no-triggers, LLM-never-emits-SQL precedent).
- **Two `db.commit()` calls for one transfer:** breaks D-01's atomicity
  guarantee by construction — always compose inside one `apply_*`, let the
  caller commit once.
- **Turning investment money into a synthetic `accounts` row:** explicitly
  the double-count bug Phase 12 just fixed (D-05, PROJECT.md Key Decisions)
  — liquid→investment funding is ALWAYS `Transaction` + `PortfolioEvent` via
  `source_account_id`, never a new `Account`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Position quantity/avg-cost after a funded buy/sell | A custom holding-update in the new function | `recompute_holding_from_events` (`backend/portfolio.py:41`) | Already handles avg-cost-unchanged-on-sell (D-02 invariant), FX-aware cost basis, zero-qty row retention — a hand-rolled version WILL diverge from the existing invariant and corrupt PnL |
| Account resolution / auto-create | A new lookup helper | `_get_or_create_account` (`backend/importer.py:110`) — already used inside `apply_add_transaction` | Ensures new accounts get the migration-010 `server_default 'liquid'` behavior automatically; a separate lookup risks bypassing that |
| Historical FX conversion for a dual-currency leg | An inline `httpx` call or a "current rate" shortcut | `backend/fx.py:get_rate(base, quote, as_of, db)` | Cache-first, immutable, date-keyed — anything else violates D-10 (no write path forces live-only FX) and risks the FX precision/conflation class of bug already flagged in STATE.md blockers |
| Audit trail for a multi-row operation | A single combined `AuditLog` row for both legs | One `AuditLog` row per mutated entity (existing `apply_add_transaction`/`apply_add_portfolio_event` each already write their own) | D-02 requires one-row-per-entity; a combined row breaks the existing audit-log query/read shape other tools may assume |

**Key insight:** every "hard" part of this phase (position math, FX, account
resolution, audit logging) is already solved code one directory away. The
actual net-new logic is thin: two `apply_add_transaction`/`apply_add_portfolio_event`
calls in sequence, plus a `transfer_pair_id`/`source_account_id` assignment
after both flush. Resist the urge to re-derive anything `portfolio.py` or
`fx.py` already owns.

## Runtime State Inventory

**Trigger:** This phase's retro-pairing migration (D-11/XFER-05) operates on
historical *stored data* (transaction rows) — Runtime State Inventory applies.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | 668 live `transactions` rows have `is_transfer = true`. Strict-match audit (same date, amount = -amount, distinct `account_id`, both `is_transfer = true`) finds **652 rows with exactly one candidate match** (326 clean pairs) and **16 rows with zero matches** (sample ids: 4977, 5480, 5489, 6284, 6286, 6287, 6292, 6295, 6296, 6297, 6300, 6305, 6319, 6320, 6322, 6325 — all on accounts 1/2). **Data migration**: UPDATE `transfer_pair_id` on the 652 matched rows (326 pairs); leave the 16 unmatched rows NULL + flagged per D-11 (never guessed). Zero rows had >1 candidate match in this audit, so the "multiple candidates" branch of D-11 is currently untested against real data — the migration must still implement it defensively. |
| Live service config | None — no external services (n8n, Datadog, etc.) are part of this stack. |
| OS-registered state | None — no OS-level task scheduling or process registration involved. |
| Secrets/env vars | None — this phase touches no env vars or secret keys. |
| Build artifacts / installed packages | None — no new packages, no build-artifact drift. |
| **Schema/account-id drift (not in the standard 5 categories, but load-bearing)** | Live `accounts` table has **9 rows**, not the 4 assumed by Phase 12's CONTEXT.md: `1=Cash(liquid)`, `2=BCA(liquid)`, `559=Stockbit(liquid)`, `994=Investments(investment)` — id **3 no longer exists** — plus 5 leftover zero-transaction test accounts from Phase 12 UAT (ids 1015–1019: `ResolveAddDualAcct`, `ResolveAddNoneAcct`, `ResolveEditAcct`, `zzscopetest-account`, `ZZ Test BCA`, all `type=liquid`). | **Code edit, not data migration**: any code in this phase that needs "the Investments account" or "the Stockbit account" must resolve by `name` + `type`, never a hard-coded id. The retro-pairing migration must NOT assume any specific account id set (unlike migration `010`'s `ACCOUNT_TYPE` dict, which hard-coded `{1,2,3,559}` and would abort-loudly if re-run today against the live 9-account table — that migration already ran once and won't re-run, but it is the cautionary precedent this phase must not repeat). |

## Common Pitfalls

### Pitfall 1: Reusing `account_balances`'s exclude-transfers SQL for the adjustment delta
**What goes wrong:** `apply_add_balance_adjustment` computes `target −
current_derived_balance` using a query that filters `is_transfer = false`,
producing a delta that's off by the account's entire transfer volume (proven
live: account 1's transfer sum is `+60,663,500`, nearly as large as its
non-transfer sum of `-61,404,700`).
**Why it happens:** `tools.py:account_balances` is the only existing
"balance" query in the codebase, and its docstring even says "current
balance" — tempting to reuse without reading the `is_transfer = false` join
clause closely.
**How to avoid:** Write a fresh, dedicated `SUM(amount)` query with no
`is_transfer` filter, scoped inline to the adjustment function (Pattern 2
above).
**Warning signs:** A UAT/test comparing the adjustment-produced balance
against a manual sum of `SELECT amount FROM transactions WHERE account_id=X`
(no filter) diverges by roughly the account's transfer total.

### Pitfall 2: Hard-coding account ids anywhere in this phase's code
**What goes wrong:** A funded-buy helper or the retro-pairing migration
assumes `Investments = id 3` (per Phase 12 docs) and either silently no-ops
or errors against the live DB where Investments is id 994.
**Why it happens:** Phase 12's CONTEXT.md and migration `010`'s
`ACCOUNT_TYPE` dict are both frozen documentation of a `{1,2,3,559}` account
set that has since drifted (test-account creation during Phase 12
UAT/execution mutated the live `accounts` sequence).
**How to avoid:** Resolve accounts by `name` (e.g. `WHERE name =
'Stockbit'`) or `type` (`WHERE type = 'investment'`) at run time, exactly
like `_get_or_create_account` already does for the importer.
**Warning signs:** Any literal integer account id appearing in new
`writes.py` code or the `011` migration outside of a test fixture.

### Pitfall 3: Two commits for one transfer
**What goes wrong:** A plan task writes `apply_add_transfer` such that it
calls `db.commit()` internally (e.g. "for safety") or the plan splits the two
legs across two separate confirm/endpoint calls in Phase 14's design,
reintroducing the "two round trips" failure mode SC #3 explicitly forbids.
**Why it happens:** Habit from simpler CRUD endpoints, or a misreading of
"atomic" as "needs its own transaction."
**How to avoid:** `apply_add_transfer`/`apply_add_investment_transfer`/
`apply_add_funded_buy`/`apply_add_funded_sell` must never call
`db.commit()` — verify by grep: `grep -n "db.commit" backend/writes.py`
should show zero new matches after this phase (it currently shows zero at
all — writes.py has never called commit, and this phase must preserve that).
**Warning signs:** Any `db.commit()` inside `writes.py`.

### Pitfall 4: Silently guessing on ambiguous retro-pair matches
**What goes wrong:** The retro-pairing migration finds 2+ same-date,
opposite-amount candidates for a row (this audit found 0 such cases live,
but the migration code must not assume that stays true) and picks one
arbitrarily (e.g. lowest id), producing an incorrect pairing that's hard to
detect later.
**Why it happens:** "Just pick the first match" is the path of least
resistance when writing the SQL.
**How to avoid:** D-11 is explicit: exactly-one-match → pair; zero or
multiple → leave `transfer_pair_id` NULL and record a flag. Recommend a
migration-scoped temp table or a printed/logged list of flagged ids (mirrors
`009`'s `assert_parity`-style loud reporting, not a raise — unmatched rows
are an expected, non-fatal outcome per D-11, unlike `009`'s hard-abort on
unmapped categories).
**Warning signs:** A migration with a `LIMIT 1` on the candidate-match query
without a preceding `COUNT(*) = 1` guard.

### Pitfall 5: Forgetting the `is_transfer` tag on new legs
**What goes wrong:** A funded buy's cash-leg `Transaction` or a plain
liquid↔liquid transfer leg is inserted without `is_transfer=True`, so it
leaks into `spending_total`/`income_total`/`net_total` as fabricated
spending/income (recreating a variant of the exact double-count bug Phase 12
fixed for investment accounts).
**Why it happens:** `apply_add_transaction`'s `after` dict defaults
`is_transfer` to `False` (`writes.py:70`) — a caller must explicitly pass
`True`.
**How to avoid:** Every new composed function must explicitly set
`is_transfer: True` on every `Transaction` leg it creates via
`apply_add_transaction` (transfer legs, funded-buy/sell cash legs) — and
resolve D-08's adjustment tag question (below) for the adjustment leg
specifically.
**Warning signs:** A UAT check on `spending_total`/`net_total` before/after a
test transfer shows a nonzero delta.

## Code Examples

### Leg-protection guard (D-04) — recommended shape
```python
# Source: extends backend/writes.py:79 (apply_edit_transaction) in place
def apply_edit_transaction(
    db: Session, tx_id: int, after: dict, before: dict | None, allow_paired: bool = False
) -> Transaction:
    tx = db.get(Transaction, tx_id)
    if tx is None:
        raise ValueError(f"Transaction {tx_id} not found during confirm")
    if tx.transfer_pair_id is not None and not allow_paired:
        raise ValueError(
            f"Transaction {tx_id} is one leg of a paired transfer "
            f"(transfer_pair_id={tx.transfer_pair_id}); use the pair-aware "
            "transfer function to edit both legs together."
        )
    # ... existing body unchanged (writes.py:84-95)
```

### Retro-pairing candidate query (migration 011)
```sql
-- Source: this session's live-DB audit (verified against Postgres 16, 668 is_transfer rows)
-- Strict match: same calendar date, exactly opposite amount, two distinct accounts.
SELECT a.id AS leg_a_id, b.id AS leg_b_id
FROM transactions a
JOIN transactions b
  ON a.date::date = b.date::date
 AND a.amount = -b.amount
 AND a.account_id <> b.account_id
 AND a.id < b.id
WHERE a.is_transfer = true AND b.is_transfer = true;
-- 652 of 668 is_transfer rows (326 pairs) match exactly once; 16 match zero times.
-- Migration must COUNT(*) per row before pairing — do not assume uniqueness holds forever.
```

## State of the Art

Not applicable — no external library/API landscape changed here. The only
"state of the art" question was whether Alembic is actually wired in this
repo (confirmed: yes, `alembic/versions/001`–`010` exist, `alembic.ini` at
repo root, `backend/entrypoint.sh` runs `alembic upgrade head` before
`uvicorn` on every container start, idempotent by design).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Recommended `transfer_pair_id` shared-group-id convention (leg A's own id used as both legs' value) is presented as a recommendation, not a locked decision — CONTEXT.md explicitly leaves this to "Claude's Discretion." | `transfer_pair_id` Shape section | Low — if the planner or a reviewer prefers mutual self-reference instead, the change is confined to one function's internals; no schema change needed either way (column is untyped `Integer`) |
| A2 | Illustrative `apply_add_funded_buy` field names (`source_account_name`, `cash_amount`, `event_currency`, etc.) are invented for this research, not sourced from any schema file — the actual `after`-dict contract is a planning decision. | Pattern 1 | Low — explicitly marked illustrative; planner must define the real contract, consistent with `PortfolioEventCreate`/`TransactionCreate` schemas in `backend/schemas.py` |
| A3 | "Investment" category tag / `is_transfer=True` used as the cashflow-exclusion mechanism for funded-buy cash legs mirrors D-08's adjustment-tag pattern, but D-08 explicitly leaves the *exact* tag mechanism to the planner's discretion — this research assumed reusing `is_transfer=True` is consistent, not necessarily the only correct choice. | Pattern 1, Pitfall 5 | Medium — if the planner picks a different exclusion tag (e.g. a dedicated `category`), the illustrative code snippet's `is_transfer: True` line would need to change; the underlying requirement (exclude from spending/income totals) does not change |

**Assessment:** All schema facts (column types, live account ids, live
transfer-match counts, migration/Alembic wiring, existing function
signatures) are `[VERIFIED]` via direct DB queries and source reads this
session. The three items above are software-design recommendations
explicitly delegated to the planner by CONTEXT.md's "Claude's Discretion"
section — they are not risk-bearing unknowns, they are open discretion
points this research narrows but does not close.

## Open Questions

1. **Should the retro-pairing migration's "flagged" marker be a DB column or
   a log-only report?**
   - What we know: D-11 requires unmatched rows be "flagged (logged +
     a recoverable marker), never guessed." 16 live rows currently qualify.
   - What's unclear: whether "recoverable marker" means a new nullable
     boolean/text column (e.g. `transfer_match_status`) or simply a printed
     migration-run report (matching `009`'s `assert_parity` loud-reporting
     style, which uses no new column).
   - Recommendation: no new column — `009`'s precedent is report-only
     (raises/prints on mismatch, adds no schema). A flagged row is simply
     "is_transfer=true AND transfer_pair_id IS NULL" — that's already a
     fully queryable, recoverable state with zero new DDL. Print the 16
     flagged ids during `upgrade()` (mirrors `009`'s per-group summary).

2. **Does the funded-buy/sell cash leg need its own distinguishing tag
   beyond `is_transfer=True`, so Records-tab UI (Phase 17) can later tell a
   "plain transfer" apart from a "funded buy's cash leg"?**
   - What we know: D-09 says dual amounts live on the two paired rows
     themselves, no new columns; D-08 flags the same Records-labeling
     tradeoff for adjustments ("if `is_transfer` is reused, it would read as
     'transfer'").
   - What's unclear: whether a funded buy's cash leg should carry a
     `category` like "Investment" (already used informally in this
     research's illustrative example) as the human-readable disambiguator,
     since `is_transfer` alone can't distinguish transfer-type from
     funded-buy-type for UI display.
   - Recommendation: use `category` (existing free-text + `category_id`
     fields, already present on `Transaction`) as the disambiguator — no
     schema change, and it's exactly what `category` already exists for.
     Concrete planning decision, not blocking for this phase (Phase 13 ships
     no UI).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| PostgreSQL | All writes + migration | ✓ | 16 (via `docker-compose.yml`, verified live via `psql` on port 5434) | — |
| Alembic | Migration `011` | ✓ | Already wired (`001`–`010` exist, `entrypoint.sh` runs `alembic upgrade head`) | — |
| Python 3.12 / SQLAlchemy 2.0 / psycopg3 | `writes.py` extension | ✓ | Matches existing `backend/requirements.txt` pins, no change needed | — |

No missing dependencies — this phase runs entirely on infrastructure already
proven live in the repo.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest >=8.0.0 (`pyproject.toml`) |
| Config file | `pyproject.toml` (no separate `pytest.ini`) |
| Quick run command | `pytest backend/tests/test_write_tools.py -x` |
| Full suite command | `pytest backend/tests/ -x` |

Existing idiom (`backend/tests/test_write_tools.py`): tests require a live
Postgres (`docker compose up db`), skip cleanly if unavailable
(`db_available` fixture), use a real `SessionLocal()` session that callers
must roll back/clean up themselves (no transactional-rollback fixture, no
mocking) — matches `test_tools.py`'s idiom per STATE.md. New tests for this
phase should follow the same pattern: seed rows, call the new `apply_*`
function directly (not through an endpoint — there isn't one yet), assert on
DB state, clean up seeded rows explicitly.

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| XFER-01 | Liquid→liquid transfer writes 2 paired rows, same `transfer_pair_id`, both `is_transfer=true`, one commit boundary (no internal `db.commit()`) | unit | `pytest backend/tests/test_write_tools.py::test_apply_add_transfer_pairs_both_legs -x` | ❌ Wave 0 |
| XFER-01 (D-04) | Editing/deleting one leg without `allow_paired` raises `ValueError` | unit | `pytest backend/tests/test_write_tools.py::test_paired_leg_edit_blocked -x` | ❌ Wave 0 |
| XFER-02 | Liquid→investment transfer: one `Transaction` (`is_transfer=true`) + one `PortfolioEvent` with `source_account_id` set to the liquid account's id; no synthetic `accounts` row created | unit | `pytest backend/tests/test_write_tools.py::test_apply_add_investment_transfer -x` | ❌ Wave 0 |
| XFER-03 | Funded buy/sell: cash-leg `Transaction` + `PortfolioEvent` + holding recompute, all inserted with zero commits inside the function | unit | `pytest backend/tests/test_write_tools.py::test_apply_add_funded_buy_one_commit_boundary -x` | ❌ Wave 0 |
| XFER-04 | Cross-currency funded buy: cash-leg `Transaction.currency` and `PortfolioEvent.currency` independently set (dual amounts), no new columns touched | unit | `pytest backend/tests/test_write_tools.py::test_funded_buy_dual_currency_legs -x` | ❌ Wave 0 |
| XFER-04 (D-10) | No write path calls `fx.get_rate` — grep-based structural check, not a runtime assertion | unit (static) | `grep -n "fx\.\|get_rate" backend/writes.py` returns no matches inside the new functions | ❌ Wave 0 (add as a documented manual/CI check, not a pytest) |
| ACCT-02 | Balance adjustment: delta = target − SUM(ALL transactions for account, no `is_transfer` filter); resulting derived balance equals target | unit | `pytest backend/tests/test_write_tools.py::test_apply_add_balance_adjustment_delta -x` | ❌ Wave 0 |
| ACCT-02 (D-08) | Adjustment row excluded from `spending_total`/`income_total`/`net_total` | integration | `pytest backend/tests/test_cashflow_summary.py::test_adjustment_excluded_from_cashflow -x` | ❌ Wave 0 (extends existing file) |
| XFER-05 | Retro-pairing migration: 652 of 668 live `is_transfer` rows get `transfer_pair_id` backfilled in exactly 326 pairs; 16 remain NULL/flagged; migration is idempotent (re-running `upgrade()` produces no changes) | integration (migration test, mirrors `test_category_migration.py`'s standalone-import idiom) | `pytest backend/tests/test_transfer_retro_pairing.py -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest backend/tests/test_write_tools.py -x`
- **Per wave merge:** `pytest backend/tests/ -x`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] New/extended `backend/tests/test_write_tools.py` test groups for all 5
      new `apply_*` functions (transfer, investment-transfer, funded buy,
      funded sell, balance adjustment) + the leg-protection guard.
- [ ] `backend/tests/test_transfer_retro_pairing.py` — new file, following
      `test_category_migration.py`'s pattern of importing the migration
      module standalone via `importlib` (bypassing the repo's own
      `alembic/` scaffold) to unit-test the migration's pure matching logic
      before it's run against live data.
- [ ] Extend `backend/tests/test_cashflow_summary.py` with an
      adjustment-exclusion assertion (D-08).
- [ ] No new fixtures/conftest needed — existing `db_available`/`db_session`
      fixtures in `test_write_tools.py` cover the need.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | Not touched this phase — auth is handled at the API-key layer in `main.py`, which this phase doesn't call |
| V3 Session Management | No | N/A — no session/cookie logic in `writes.py` |
| V4 Access Control | No | Single-user app, no per-user access control (documented project constraint) |
| V5 Input Validation | Yes | Existing pattern: money via `Decimal(str(x))` (never raw float), account/ticker resolution via bound-parameter `text()` queries only — every new function must follow this exactly, no string interpolation into SQL |
| V6 Cryptography | No | Not touched — no secrets/tokens generated in this phase |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection via account/category name lookups | Tampering | Every existing `writes.py` query uses SQLAlchemy `text()` with bound `:param` placeholders — the new functions must follow the exact same idiom (confirmed: zero string-formatted SQL anywhere in `writes.py` today) |
| Float-precision money corruption | Tampering (data integrity) | `Decimal(str(x))` before every `Decimal()` construction — LOAD-BEARING per existing inline comments at `writes.py:62,90` — the new functions must repeat this exact idiom for every new money field (transfer amounts, adjustment deltas) |
| Silent double-counting via missed `is_transfer` tagging | Repudiation (financial data integrity, not classic security) | Every new `Transaction` leg created by this phase's composed functions must explicitly pass `is_transfer=True` — see Pitfall 5 |
| Migration partial-failure leaving inconsistent pairing state | Tampering / Denial of Service (data integrity) | Follow `009`/`010`'s idempotent, guarded-`if`-per-step pattern; Alembic's single-transaction online-migration model (per `009`'s docstring) gives a clean rollback on any `RuntimeError` |

## Sources

### Primary (HIGH confidence)
- `backend/writes.py` (full read, this session) — mutation-layer contract, all 26 existing `apply_*` signatures
- `backend/models.py` (full read, this session) — `Transaction.transfer_pair_id`, `PortfolioEvent.source_account_id`, all Numeric precisions
- `backend/portfolio.py:41-100` (`recompute_holding_from_events`, this session)
- `backend/fx.py` (full read, this session) — `get_rate` cache-first/immutable contract
- `backend/main.py:1014-1133` (`_execute_proposal_payload`, `confirm_proposal`, this session) — one-confirm-one-commit boundary, error-mapping idiom
- `alembic/versions/010_typed_accounts.py` (full read, this session) — abort-loudly/idempotent migration idiom, the `ACCOUNT_TYPE` hard-coded-id precedent this phase must NOT repeat
- `alembic/versions/009_category_hierarchy.py:1-60,124-136` (this session) — `assert_parity` loud-reporting idiom, the closest analog for retro-pairing's flag-not-guess requirement
- `backend/entrypoint.sh` (this session) — confirms `alembic upgrade head` runs on every container start, idempotent by design
- `backend/importer.py:110-157` (`_get_or_create_account`, `insert_rows`, this session)
- `backend/tools.py:1-30,474-510` (this session) — `account_balances` exclude-transfers finding (Finding 2), cashflow filter idiom (`is_transfer = false`)
- Live PostgreSQL query, this session (`psql -h localhost -p 5434 -U monai -d monai`) — account table drift (Finding 1), 652/16 retro-pair match cardinality, transfer-vs-non-transfer sum comparison (Finding 2's proof)
- `.planning/phases/13-.../13-CONTEXT.md` — all 11 locked decisions (D-01..D-11)
- `.planning/phases/12-.../12-CONTEXT.md` — prior-phase account audit (now partially stale per Finding 1)
- `.planning/REQUIREMENTS.md` §"Connection layer (XFER)" + ACCT-02
- `.planning/STATE.md` — FX precision flag ("BTC price_cache USD/IDR conflation class of bug"), Phase 12 sequencing notes

### Secondary (MEDIUM confidence)
None — no external documentation lookups were needed for this phase (pure internal-codebase research).

### Tertiary (LOW confidence)
None.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new libraries; every reused function read in full this session
- Architecture: HIGH — composition pattern is the existing, unambiguous `writes.py` idiom; verified against 26 existing examples
- Pitfalls: HIGH — both blocking findings (account-id drift, derived-balance definition) are proven via live-DB queries this session, not inferred

**Research date:** 2026-07-30
**Valid until:** Effectively indefinite for the architectural guidance (internal codebase, not a moving external target) — but the live-DB facts (Finding 1's account ids, the 652/16 retro-pair counts) are a point-in-time snapshot. If Phase 13 planning/execution is delayed and more test-account creation or transaction imports occur in the interim, re-run the live-DB queries in this document (Common Pitfalls #2, Runtime State Inventory) before finalizing the retro-pairing migration's expected-outcome assertions.
