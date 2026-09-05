---
phase: 12-typed-accounts-transfer-funding-schema-foundations
reviewed: 2026-07-25T00:00:00Z
depth: standard
files_reviewed: 9
files_reviewed_list:
  - alembic/versions/010_typed_accounts.py
  - backend/models.py
  - backend/tools.py
  - backend/tests/test_typed_accounts.py
  - backend/tests/test_cashflow_view.py
  - backend/tests/test_account_crud.py
  - backend/tests/test_cashflow_summary.py
  - backend/tests/test_tools.py
  - backend/tests/test_write_tools.py
findings:
  critical: 0
  warning: 3
  info: 1
  total: 4
status: issues_found
---

# Phase 12: Code Review Report

**Reviewed:** 2026-07-25T00:00:00Z
**Depth:** standard
**Files Reviewed:** 9
**Status:** issues_found

## Summary

Reviewed the typed-accounts additive migration (`010_typed_accounts.py`), the corresponding ORM changes (`models.py`), the `cashflow_transactions`-view switch-over in `tools.py`, and the test suite pinning both.

The core structural guarantees the phase set out to build are correct: the migration backfills before tightening to `NOT NULL`, the abort-loudly guard fires on any account-id drift from the D-02 audit map, the CHECK constraint is idempotent, the `cashflow_transactions` view is created only after the pairing columns exist (so `t.*` is the full superset), and its `NOT EXISTS`-keyed predicate correctly keeps `NULL account_id` rows in the view while excluding `type='investment'` rows. I traced every read tool in `tools.py`: all genuine cashflow *totals* (`spending_total`, `income_total`, `net_total`, `spending_by_category`, `spending_in_category`, `transaction_count`, `largest_transactions`, the total half of `average_daily_spending`, `monthly_trend`) were switched to `cashflow_transactions`, while the currency probe, the date-span query, `account_balances`, and every delete/reassign COUNT guard were correctly left on the base `transactions` table. No double-count or wrongly-switched instance found. All SQL is parameterized `text()`; no string-interpolated user input into SQL anywhere in these files.

Four gaps are worth fixing, none of which corrupt data today, but two of them are latent robustness gaps introduced by this phase's own new FK/CHECK constraints that will bite the next phase (or a manual edit) if not addressed.

## Warnings

### WR-01: `propose_delete_account`'s orphan-delete guard doesn't count `portfolio_events.source_account_id` dependents

**File:** `backend/tools.py:885-897`
**Issue:** Migration 010 adds `portfolio_events.source_account_id` as a real FK to `accounts.id` (no `ondelete`, so Postgres default `RESTRICT`/`NO ACTION`). `propose_delete_account`'s D-06 orphan-delete guard only counts dependent rows in `transactions`:
```python
count_sql = "SELECT COUNT(*) FROM transactions WHERE account_id = :aid"
```
A liquid account that funds an investment purchase (once Phase 13 starts populating `source_account_id`) but has zero rows of its own in `transactions` would pass this guard with `tx_count == 0`, and the proposal would be allowed to proceed. Applying the delete would then hit the FK constraint at the DB layer and raise an uncaught `IntegrityError` instead of the intended clean, user-facing block message — turning a should-be-422 into a raw 500. Currently unreachable (no writer in the reviewed files populates `source_account_id` yet), but the guard is already incomplete relative to the FK this same phase introduced.
**Fix:**
```python
count_sql = (
    "SELECT "
    "(SELECT COUNT(*) FROM transactions WHERE account_id = :aid) + "
    "(SELECT COUNT(*) FROM portfolio_events WHERE source_account_id = :aid)"
)
```
Also confirm the direct `/accounts/{id}` DELETE endpoint's block/reassign logic (`backend/main.py`, out of this review's scope) has the same gap.

### WR-02: Abort-loudly guard doesn't verify pre-existing (non-NULL) `type` values actually match the D-02 map

**File:** `alembic/versions/010_typed_accounts.py:60-84`
**Issue:** The backfill only sets `type` `WHERE type IS NULL` (line 63), so any of the four audited accounts that already had a non-NULL, non-`{liquid,investment}` value (plausible — the column was previously "decorative, no constraint") is left untouched. The abort-loudly checks only verify (a) the live account-id set equals `set(ACCOUNT_TYPE)` and (b) zero rows have `type IS NULL` — neither check catches a stray junk value like `'savings'` sitting on account id 2. Such a row would sail past both guards and only fail later, at CHECK-constraint creation (step 3), as a raw Postgres `IntegrityError` rather than the descriptive `RuntimeError` the migration is designed to raise. The migration still fails safe (no partial/silent corruption, single-transaction rollback), but the "abort-loudly correctness" contract this file's docstring promises isn't fully met.
**Fix:** After the backfill, assert the final values actually equal the map, not just that they're non-NULL:
```python
final_types = {r[0]: r[1] for r in conn.execute(sa.text("SELECT id, type FROM accounts"))}
mismatched = {i: final_types[i] for i in ACCOUNT_TYPE if final_types.get(i) != ACCOUNT_TYPE[i]}
if mismatched:
    raise RuntimeError(
        f"Typed-accounts migration abort — accounts.type diverges from D-02: {mismatched}"
    )
```

### WR-03: `propose_add_account` / `propose_edit_account` don't validate `type` against the new closed set before creating a proposal

**File:** `backend/tools.py:813-871`
**Issue:** `type` now has a DB-enforced `CHECK (type IN ('liquid','investment'))` (migration 010) but the LLM-facing proposal tools accept and pass through any string unvalidated:
```python
after = {"name": name, "type": type, "currency": currency}
```
Before this phase the field was decorative, so an arbitrary string was harmless; now it silently produces a well-formed proposal that will only fail at apply-time with a DB `IntegrityError` (again risking an unhandled 500 rather than a clean rejection at proposal-creation time, where the user could be told immediately).
**Fix:**
```python
if type is not None and type not in {"liquid", "investment"}:
    return {"tool": "propose_add_account",
            "error": f"Invalid account type '{type}'. Must be 'liquid' or 'investment'."}
```
(mirror in `propose_edit_account`.)

## Info

### IN-01: `average_daily_spending`'s day-span denominator is unscoped by the investment exclusion, while the numerator is

**File:** `backend/tools.py:417-440`
**Issue:** The spending total is correctly computed from `cashflow_transactions` (excludes investment-account rows), but when no explicit period is given, the day-count denominator falls back to `SELECT MIN(date), MAX(date) FROM transactions` — the base table, explicitly including investment-account transaction dates. This is called out in-line as intentional ("leave on the base table so the denominator ... isn't shrunk by the exclusion view"), but the effect is the reverse of what's stated in edge cases: if the investment account's earliest or latest transaction date falls *outside* the liquid-transaction date range, the denominator is inflated (not merely "not shrunk"), silently diluting the reported daily average. Not a bug in the sense of an incorrect switch (matches the phase-context's instruction to leave this one alone), but worth flagging as a real precision edge case introduced by this phase's exclusion-view work.
**Fix:** If precision matters here, scope the fallback date-span query to `WHERE account_id IS NULL OR account_id NOT IN (SELECT id FROM accounts WHERE type = 'investment')` (or simply query `cashflow_transactions` for the span too) — trades off against the documented "don't let the exclusion view shrink the denominator" rationale, so this is a judgment call, not a required fix.

---

_Reviewed: 2026-07-25T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
