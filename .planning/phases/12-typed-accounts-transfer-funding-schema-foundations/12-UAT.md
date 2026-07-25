---
status: partial
phase: 12-typed-accounts-transfer-funding-schema-foundations
source: [12-01-SUMMARY.md, 12-02-SUMMARY.md, 12-03-SUMMARY.md]
started: 2026-07-26T06:10:00Z
updated: 2026-07-26T06:20:00Z
tester: claude (self-driven at user request; human-visual test deferred)
---

## Current Test

[testing complete — 1 item deferred to human]

## Tests

### 1. Cold Start Smoke Test
expected: Restart the backend container; it boots without errors, `alembic upgrade head` is idempotent (stays at revision f1a2b3c4d5e6), and the API serves live data.
result: pass
evidence: after `docker compose restart backend`, alembic current = f1a2b3c4d5e6 (head); GET /accounts -> HTTP 200.

### 2. Account classification (Criterion 1)
expected: All accounts typed liquid|investment, none NULL; the three liquid accounts (Cash, BCA, Stockbit) are liquid and there is exactly one investment account ("Investments").
result: pass
evidence: {1:Cash=liquid, 2:BCA=liquid, 559:Stockbit=liquid, 994:Investments=investment}; 0 NULL types.
note: initially failed because the test hard-coded the investment account's surrogate id (3); that id changed to 994 when the accidentally-deleted "Investments" account was restored. Fixed the test to assert the classification invariant (exactly one investment account named "Investments") instead of a specific id. Migration ACCOUNT_TYPE map (historical) still records id 3 and its test passes unchanged.

### 3. accounts.type is DB-enforced (Criterion 2, schema half)
expected: A CHECK constraint rejects any type outside {liquid, investment}; a new account inserted without a type defaults to 'liquid' (server_default) so the CSV importer keeps working.
result: pass
evidence: INSERT type='crypto' -> ERROR "violates check constraint ck_accounts_type"; INSERT without type -> default_type=liquid (both via rolled-back txn).

### 4. Cashflow totals exclude investment — double-count gone (Criterion 2, application half)
expected: The cashflow_transactions view excludes investment-account rows; every cashflow total reads the view; raw_spend − view_spend equals the investment-account expense.
result: pass
evidence: raw=563,759,700; view=450,755,700; delta=113,004,000 (the investment expense). 0 investment rows leak into the view. Live API GET /cashflow/summary served by the rebuilt container (tools.py uses cashflow_transactions).

### 5. NULL-account rows retained in the view
expected: Transactions with account_id IS NULL remain IN cashflow_transactions (they are not investment).
result: pass
evidence: base NULL-account rows = 12; view NULL-account rows = 12.

### 6. Pairing columns exist (Criterion 3)
expected: transactions.transfer_pair_id and portfolio_events.source_account_id exist, nullable, indexed.
result: pass
evidence: both nullable=YES; indexes ix_transactions_transfer_pair_id and ix_portfolio_events_source_account_id present.

### 7. Phase + regression test suite
expected: Phase 12 tests pass; no new regressions.
result: pass
evidence: test_typed_accounts.py + test_cashflow_view.py = 8 passed; full backend suite = 244 passed, 1 failed (test_settings.py::test_put_settings_requires_key — pre-existing, unrelated, logged in deferred-items.md).

### 8. Cashflow page renders correctly in the browser (human visual)
expected: Open the cashflow page; the spending/income/net totals no longer include the investment money, and the numbers look right to you.
result: skipped
reason: needs-human — subjective visual confirmation in the browser; user opted to skip this one. All underlying data/API behavior is proven by tests 1–7. (Note: the "Net worth" hero still combines liquid + investment balances; the liquid/investment display split is Phase 15, not a Phase 12 defect.)

## Summary

total: 8
passed: 7
issues: 0
skipped: 1
blocked: 0
pending: 0

## Gaps

[none — the one issue found (stale id-3 assertion) was root-caused and fixed inline during this session; re-verified green]
