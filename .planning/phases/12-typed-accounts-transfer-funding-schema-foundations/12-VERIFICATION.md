---
phase: 12-typed-accounts-transfer-funding-schema-foundations
verified: 2026-07-25T00:00:00Z
status: passed
score: 3/3 must-haves verified
behavior_unverified: 0
overrides_applied: 0
---

# Phase 12: Typed Accounts + Transfer/Funding Schema Foundations Verification Report

**Phase Goal:** The schema can distinguish liquid from investment accounts with certainty, and has the columns needed to pair transfers and funded portfolio events.
**Verified:** 2026-07-25
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | All 4 live accounts are manually audited and classified liquid/investment — none left NULL or auto-inferred | ✓ VERIFIED | Live DB `SELECT id,name,type FROM accounts`: id 1 (Cash)=liquid, 2 (BCA)=liquid, 3 (Investments)=investment, 559 (Stockbit)=liquid. `SELECT COUNT(*) FROM accounts WHERE type IS NULL` = 0. `alembic/versions/010_typed_accounts.py` hard-codes `ACCOUNT_TYPE = {1:"liquid",2:"liquid",3:"investment",559:"liquid"}` (D-02) with no inference logic, plus an abort-loudly `RuntimeError` if the live account-id set drifts from this exact map. 12-CONTEXT.md D-02/D-03/D-04 record the human audit rationale (Stockbit=broker cash not positions; Investments=the real double-count). |
| 2 | `accounts.type` is DB-enforced (CHECK) AND investment-typed accounts excluded from every cashflow total — structurally impossible, not by convention | ✓ VERIFIED | `\d accounts` shows `CHECK ck_accounts_type (type::text = ANY (ARRAY['liquid','investment']))`, `NOT NULL`, `DEFAULT 'liquid'`. `cashflow_transactions` view (`pg_get_viewdef`) uses `WHERE NOT (EXISTS (SELECT 1 FROM accounts a WHERE a.id=t.account_id AND a.type='investment'))` — confirmed 0 investment rows in the view, and NULL-`account_id` row count identical raw vs. view (12 = 12). `backend/tools.py` grep confirms all 10 cashflow-total FROM-clause sites (spending_total L127, income_total L144, net_total L161, spending_by_category's `_ROLLUP_FROM` L237, spending_in_category L302, transaction_count L383, largest_transactions L403, average_daily_spending total L426, monthly_trend L456, find_transactions L553) read `FROM cashflow_transactions`; the 5 intentional LEAVE sites (currency probe L101, date-span L436, account_balances L497-503, delete/reassign COUNT guards L886/943/995) correctly remain `FROM transactions`. Live runnable proof: `raw_spend (563,759,700) − view_spend (450,755,700) = inv_expense (113,004,000)`, all three derived live via SQL — exactly matches the SUMMARY's claimed delta. |
| 3 | `transactions.transfer_pair_id` and `portfolio_events.source_account_id` exist (nullable, indexed) | ✓ VERIFIED | `\d transactions`: `transfer_pair_id integer`, nullable, index `ix_transactions_transfer_pair_id`, no FK (as designed — pairing semantics deferred to Phase 13). `\d portfolio_events`: `source_account_id integer`, nullable, index `ix_portfolio_events_source_account_id`, FK `fk_portfolio_events_source_account → accounts.id`. `backend/models.py` mirrors both (L157 `Transaction.transfer_pair_id`, L277 `PortfolioEvent.source_account_id`). |

**Score:** 3/3 truths verified (0 present, behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `alembic/versions/010_typed_accounts.py` | Migration: backfill→assert→CHECK→tighten→pairing columns→view | ✓ VERIFIED | Applied to live dev DB (revision `f1a2b3c4d5e6`, down_revision `e5f6a7b8c9d0`). All 6 upgrade steps present, idempotency-guarded, matches docstring exactly. |
| `backend/models.py` | ORM mirrors DB: `Account.type` NOT NULL/default, `Transaction.transfer_pair_id`, `PortfolioEvent.source_account_id` | ✓ VERIFIED | All three mappings present and correct (L54, L157, L277). |
| `cashflow_transactions` (DB view) | NOT EXISTS-keyed exclusion view, NULL-safe | ✓ VERIFIED | Exists live, correct predicate, correct column superset (includes `transfer_pair_id`, created after pairing columns per plan). |
| `ck_accounts_type` (CHECK constraint) | Binary closed set | ✓ VERIFIED | Present live: `type IN ('liquid','investment')`. |
| `backend/tests/test_typed_accounts.py` | 4 named tests: type map, classification, CHECK+default, pairing columns | ✓ VERIFIED | All 4 collect and pass against live DB. |
| `backend/tests/test_cashflow_view.py` | 4 named tests: view exclusion, NULL parity, double-count delta, tools-level exclusion | ✓ VERIFIED | All 4 collect and pass against live DB. |
| `backend/tools.py` | 10 cashflow-total FROM-clause sites switched to view | ✓ VERIFIED | Grep-confirmed; matches SUMMARY's site list exactly. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `alembic/versions/010_typed_accounts.py` | live Postgres `accounts`/`transactions`/`portfolio_events` | `alembic upgrade head` | WIRED | Migration applied; DB state matches migration's intended output exactly. |
| `backend/tools.py` cashflow functions | `cashflow_transactions` view | `FROM cashflow_transactions` in parameterized `text()` SQL | WIRED | 10/10 sites switched; explicit column lists preserved (no `SELECT *`), matching the "FROM-clause-only" constraint. |
| `backend/models.py` | live DB schema | SQLAlchemy `Mapped[...]` column defs | WIRED | `Account.type` nullable=False/server_default='liquid'; pairing columns mapped with correct nullability/FK. |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Phase-12 named test suite (8 tests) | `pytest backend/tests/test_typed_accounts.py backend/tests/test_cashflow_view.py -q` | `8 passed` | ✓ PASS |
| Full backend suite (single run) | `pytest backend/tests/ -q` | `244 passed, 1 failed` (the pre-existing, pre-logged `test_settings.py::test_put_settings_requires_key`) | ✓ PASS (matches documented, out-of-scope pre-existing failure) |
| Double-count delta, derived live | `SELECT raw_spend, view_spend, inv_expense ...` | `563,759,700 − 450,755,700 = 113,004,000` | ✓ PASS |
| View excludes investment rows | `SELECT COUNT(*) FROM cashflow_transactions ct JOIN accounts a ... WHERE a.type='investment'` | `0` | ✓ PASS |
| NULL-account_id parity | raw vs. view `COUNT(*) WHERE account_id IS NULL` | `12 = 12` | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| ACCT-03 | 12-01, 12-02, 12-03 | Accounts typed liquid/investment (DB-enforced after live audit); investment-typed accounts excluded from cashflow totals | ✓ SATISFIED | All three roadmap success criteria verified above; REQUIREMENTS.md line 99 status "Complete" confirmed accurate. |

No orphaned requirements — REQUIREMENTS.md maps only ACCT-03 to Phase 12, and all three plans declare `requirements: [ACCT-03]`.

### Anti-Patterns Found

None. Grepped `backend/tools.py`, `backend/models.py`, `alembic/versions/010_typed_accounts.py`, and both new test files for `TBD|FIXME|XXX|TODO|HACK|PLACEHOLDER` — zero matches.

### Out-of-Scope Items (Noted, Not Gaps)

`12-REVIEW.md` flags 3 warnings + 1 info item, all forward-looking robustness gaps that don't affect this phase's stated success criteria and are explicitly write-path/next-phase-facing:

- **WR-01** (`propose_delete_account`'s orphan guard doesn't count `portfolio_events.source_account_id` dependents) — unreachable until Phase 13 writes to that column; Phase-13-facing per task instructions.
- **WR-02** (abort-loudly guard doesn't re-verify pre-existing non-NULL values match D-02, only checks for NULL) — a migration-robustness edge case for a scenario (stray junk `type` value) that did not occur on this live DB (verified: actual values match D-02 exactly). Does not affect the achieved outcome.
- **WR-03** (`propose_add_account`/`propose_edit_account` don't validate `type` against the closed set before DB apply-time) — write-path validation, explicitly Phase-13-facing per task instructions.
- **IN-01** (`average_daily_spending`'s date-span denominator intentionally stays on the base table) — documented, intentional design choice per the plan's own LEAVE list, not a defect.

None of these block Criterion 1, 2, or 3.

### Human Verification Required

None. All three success criteria are structural/data-state facts fully verifiable via live DB introspection and passing automated tests — no visual, real-time, or subjective-judgment behavior involved.

### Gaps Summary

No gaps. All three ROADMAP success criteria are verified true against both the source code and the live dev database. The migration was applied (not just written), the CHECK constraint and view exist and behave correctly, the pairing columns exist with correct nullability/indexing, and the application layer (`tools.py`) demonstrably inherits the structural exclusion (live delta matches investment-expense magnitude exactly). The one full-suite test failure is a pre-existing, pre-logged, out-of-scope regression (`test_settings.py`), not caused by this phase.

---

_Verified: 2026-07-25_
_Verifier: Claude (gsd-verifier)_
