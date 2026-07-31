---
status: partial
phase: 15-net-worth-aggregation-dashboard
source: [15-VERIFICATION.md]
started: 2026-07-31T09:51:52Z
updated: 2026-07-31T09:51:52Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. Live /cashflow dashboard visual check
expected: After rebuilding the stack (`docker compose up -d --build` — the running
container is stale and 404s on `/net-worth`, the known deploy-requires-rebuild
gotcha), open `http://localhost:3001/` and confirm:
- The net-worth hero shows ONE combined number equal to liquid subtotal + investment
  subtotal (verifier saw total 310,474,634.28 against the live DB; 8 liquid accounts,
  5 investment platforms, 9/9 accounts covered).
- The liquid/investment split row renders both subtotals.
- Under "Liquid accounts" there is NO investment-typed account (no double-count).
- The hero has NO ▲/▼ delta chip (net-worth trend is deferred).
- Per-account balances still render even for accounts with zero activity this period.
result: [pending]

## Summary

total: 1
passed: 0
issues: 0
pending: 1
skipped: 0
blocked: 0

## Gaps
