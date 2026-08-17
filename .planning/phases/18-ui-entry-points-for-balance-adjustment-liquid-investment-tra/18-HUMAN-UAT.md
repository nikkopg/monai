---
status: partial
phase: 18-ui-entry-points-for-balance-adjustment-liquid-investment-tra
source: [18-VERIFICATION.md]
started: 2026-08-17T16:35:00+07:00
updated: 2026-08-17T16:35:00+07:00
---

## Current Test

[awaiting human testing]

## Prerequisite

The `monai-frontend` container currently on port 3001 was built 2026-08-02 and does NOT
contain any phase-18 code. Rebuild before testing, or every test below will read as failed:

```bash
docker compose up -d --build
```

## Tests

### 1. Balance adjustment live write (ACCT-02)
test: Against docker-compose (real Postgres), open a liquid account row in Cashflow → Accounts, use "Adjust balance" to set a new target balance, and submit.
expected: A new "Adjustment" transaction record appears in the ledger and the account's derived balance on the summary reconciles to the entered target — confirming `apply_add_balance_adjustment`'s fresh-unfiltered-SUM delta computation against real data, not just the route-mocked e2e fixture.
result: [pending]

### 2. Liquid→investment deposit live write (XFER-02)
test: Against docker-compose, open a platform detail page, click "Deposit cash", pick a real liquid account, and submit a deposit.
expected: A Deposit portfolio event appears on the platform ledger AND the chosen liquid account's balance is debited by the same amount — one atomic dual-leg write via `apply_add_investment_transfer`.
result: [pending]

### 3. Funded buy/sell live write (XFER-03)
test: Against docker-compose, open the platform detail "Buy & Sell" tab, use "+ Log event" to submit a funded Buy (with a Funding account chosen), then a funded Sell.
expected: Buy debits the chosen liquid account and records the holding/event in one atomic commit; Sell credits it back. The persisted `cash_amount` matches what was submitted (default qty×price or edited value).
result: [pending]

## Summary

total: 3
passed: 0
issues: 0
pending: 3
skipped: 0
blocked: 0

## Gaps

## Notes

All three items were flagged open in all three plans' own `<verification>` sections and in
each SUMMARY's coverage block (`human_judgment: true`) — the phase-18 e2e suite is entirely
route-mocked by design, so it proves the UI sends the correct payload shape but never
exercises the live write path. Phase 18 is the last phase of milestone v1.2, so there is no
later phase to defer these to.

Related open item: the live DB currently has zero `type='investment'` accounts
(see `.planning/todos/pending/260817-inv-missing-investments-account.md`). Test 2 and 3
operate on platforms/holdings rather than the investment *account* row, so they are not
blocked by it — but net-worth numbers observed while testing will be skewed until it's resolved.
