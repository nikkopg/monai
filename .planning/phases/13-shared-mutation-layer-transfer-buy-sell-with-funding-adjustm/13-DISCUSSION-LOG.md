# Phase 13: Shared Mutation Layer — Transfer, Buy/Sell-with-Funding, Adjustment Writes - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-26
**Phase:** 13-Shared Mutation Layer — Transfer, Buy/Sell-with-Funding, Adjustment Writes
**Mode:** "go with all recs" — recommended option locked for every gray area (no per-question interview).
**Areas discussed:** Atomicity mechanism, Leg-protection, Adjustment record shape, Dual-amount FX, Retro-pairing match strictness

---

## Atomicity / transaction boundary

| Option | Description | Selected |
|--------|-------------|----------|
| Compose existing `apply_*`, one caller commit | Reuse the never-commit contract; multi-row atomicity from a single `db.commit()` | ✓ |
| New transaction-manager wrapper in writes.py | Explicit begin/commit machinery inside the layer | |
| DB-level stored procedure | Push atomicity into Postgres | |

**Choice:** Compose existing primitives; caller owns the commit (D-01/D-02).
**Notes:** `writes.py` already documents "the caller owns the transaction boundary" — the seam exists; no new machinery.

---

## Leg-protection (block editing/deleting one paired leg)

| Option | Description | Selected |
|--------|-------------|----------|
| Application-layer guard | `apply_edit/delete_transaction` raise on non-NULL `transfer_pair_id` unless pair-aware caller overrides | ✓ |
| DB trigger | Postgres trigger blocks single-leg mutation | |
| Both | Trigger + app guard | |

**Choice:** Application-layer guard (D-04).
**Notes:** Consistent with correctness-by-construction, LLM-never-emits-SQL, and the repo's no-trigger precedent. Loud raise, not silent corruption.

---

## Balance adjustment record shape

| Option | Description | Selected |
|--------|-------------|----------|
| Transaction row = delta, tagged "Adjustment", excluded from cashflow | Balance stays derived; adjustment is the only write | ✓ |
| Dedicated adjustment entity/table | New model for adjustments | |
| Stored balance column | Persist balance directly | |

**Choice:** Delta transaction row; balance stays derived; excluded from spending/income totals (D-07/D-08).
**Notes:** Exact exclusion tag left to planner (is_transfer reuse vs dedicated flag) with the Records-labeling tradeoff noted.

---

## Dual-amount / cross-currency

| Option | Description | Selected |
|--------|-------------|----------|
| Two paired rows carry each leg's own amount+currency | No schema change; FX is read-time valuation via historical cache | ✓ |
| Add received_amount/received_currency columns | New columns on Transaction | |
| Store an FX rate on the write | Persist rate at write time | |

**Choice:** Two-row pairing carries dual amounts; no new columns; historical date-keyed FX via `fx.py` (D-09/D-10).
**Notes:** Directly satisfies "no write path forces a live-only FX rate."

---

## Retro-pairing migration match strictness

| Option | Description | Selected |
|--------|-------------|----------|
| Strict: same date + equal abs amount + opposite sign + distinct accounts; unique match only | Zero/multiple candidates → flag, leave as-is | ✓ |
| Loose: date-window + amount tolerance | Fuzzy matching | |
| Skip migration | Leave all historical transfers unpaired | |

**Choice:** Strict exact-match, unique-only; flag-not-guess for ambiguous/unmatched (D-11).
**Notes:** Non-destructive, idempotent, per project migration mandate. Next revision after `010`.

---

## Claude's Discretion

- Exact `apply_*` names/signatures and inline-vs-decompose of composed legs.
- `transfer_pair_id` shape (self-referential vs shared group id) + FK/index details.
- Exact adjustment exclusion tag and Records-labeling tradeoff.
- Retro-pairing migration internals (unmatched marker, tie-window, revision structure).
- Whether new functions live in `writes.py` or a submodule (default: same file).

## Deferred Ideas

None — discussion stayed within phase scope. Category-edit writes already exist and are only reused. REST/agent/MCP registration is Phase 14; net worth is Phase 15; UI is Phases 16–17.
