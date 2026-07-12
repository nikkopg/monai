---
status: partial
phase: 07-investment-subsystem-v2-multi-platform-multi-currency-cash-g
source: [07-VERIFICATION.md]
started: 2026-07-12T16:19:09Z
updated: 2026-07-12T16:19:09Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. Allocation pie chart (VZ-01)
expected: On the investments page, the allocation pie renders from the existing
`portfolio_summary` payload (no new network fetch). The asset-type / platform
toggle re-groups the slices correctly, and an empty portfolio shows the empty
state rather than a broken chart.
result: [pending]

### 2. Value-history line chart (VZ-02 / INVX-01)
expected: The historical value line chart renders from `GET /investments/history`.
The Value / P&L toggle switches the plotted series, and the range selector filters
the date window. A portfolio with no history rows degrades gracefully (empty state).
result: [pending]

### 3. Chat multi-platform add / delete (CH-01)
expected: In a live chat session, adding a holding on a specific platform
("add 5 BBCA on Stockbit") and deleting an account/holding ("delete my BCA account")
both work end-to-end — the LLM selects `find_platforms` / `find_accounts`, proposes
the correct write, and the confirmed write applies. (The confirm-time write path is
already covered by an automated regression test; this item exercises the live agent's
actual tool-selection behavior, which cannot be verified programmatically.)
result: [pending]

## Summary

total: 3
passed: 0
issues: 0
pending: 3
skipped: 0
blocked: 0

## Gaps
