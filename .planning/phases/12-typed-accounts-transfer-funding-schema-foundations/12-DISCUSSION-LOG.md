# Phase 12: Typed Accounts + Transfer/Funding Schema Foundations - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-25
**Phase:** 12-Typed Accounts + Transfer/Funding Schema Foundations
**Areas discussed:** Type taxonomy, Classify the 4 accounts, Future-account policy, Structural exclusion

---

## Type taxonomy

| Option | Description | Selected |
|--------|-------------|----------|
| Binary: liquid / investment | CHECK gates exactly the cashflow rule; finer labels are a separate cosmetic concern later | ✓ |
| Richer closed set | cash/bank/e-wallet/investment — descriptive but extra values only matter for display, harder to extend | |
| Binary + is_liquid boolean | Free-ish label + DB-enforced boolean gate; decouples display from correctness at cost of two columns | |

**User's choice:** Binary: liquid / investment
**Notes:** Keeps the double-count exclusion logic trivial (`type='investment'` → excluded).

---

## Classify the 4 accounts

| Option | Description | Selected |
|--------|-------------|----------|
| Investments (id 3) | Placeholder, −45.9M in non-transfer txns = contributions booked as expenses | ✓ |
| Stockbit (id 559) | Indonesian brokerage, 0 non-transfer balance | (proposed, NOT selected) |
| BCA (id 2) | Bank, +297.6M | |
| Cash (id 1) | Physical cash, −61.4M | |

**User's choice:** Only Investments (id 3) is investment-typed. BCA, Cash, and **Stockbit** are liquid.
**Notes:** User deliberately kept Stockbit liquid — it's the broker *cash* account (RDN balance that funds buys), not the stock positions (those live in `holdings`/`platforms`). This makes Stockbit a valid liquid `source_account_id` for Phase 13 funded buys. Real-account names/balances pulled live via the monai MCP (`find_accounts`, `account_balances`).

---

## Future-account policy

| Option | Description | Selected |
|--------|-------------|----------|
| NOT NULL, default 'liquid' | NOT NULL + CHECK + server_default 'liquid'; importer/new accounts auto-liquid; makes "no NULLs" permanent | ✓ |
| NOT NULL, no default | Every create path must pass a type or fail; breaks CSV importer's auto-create unless taught | |
| Keep nullable | CHECK allows NULL, unset = liquid; least friction but lets NULLs creep back | |

**User's choice:** NOT NULL, default 'liquid'
**Notes:** Exclusion predicate keys on `type = 'investment'` (not `!= 'liquid'`) so a mis-typed account errs toward visible-in-cashflow, never silently dropped.

---

## Structural exclusion

| Option | Description | Selected |
|--------|-------------|----------|
| DB view (cashflow source) | Migration creates `cashflow_transactions` view; every total reads FROM it; exclusion lives in schema | ✓ |
| Shared Python clause/helper | One `_cashflow_from()` helper in tools.py; DRY but a new query can forget it | |
| You decide | Let research/planner pick the mechanism | |

**User's choice:** DB view (cashflow source)
**Notes:** Strongest "structurally impossible to forget" guarantee, per success-criterion #2. View must keep NULL-`account_id` rows in (they aren't investment); whether it also bakes in `is_transfer=false` is left to the planner.

---

## Claude's Discretion

- Exact DDL / Alembic revision `010` structure (NOT NULL change, CHECK syntax, index/FK choices).
- `cashflow_transactions` view internals — EXCEPT the hard requirement that NULL-`account_id` rows are kept in.
- Pairing-column semantics (`transfer_pair_id` shape, `source_account_id` FK/index), consistent with locked roles.
- Whether the investment account is also removed from / shown separately in `account_balances` (a per-account list, outside criterion #2's strict target).

## Deferred Ideas

None — discussion stayed within phase scope. Richer account subtypes were considered and explicitly rejected (D-01).
