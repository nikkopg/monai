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
result: FIXED — root cause: `asset_type_groups[].total_value` / `groups[].subtotal`
are Decimal → serialized as JSON strings → recharts got NaN geometry → blank pie.
Fix: Number()-coerce both toggle branches in page.tsx (commit 4a870a2). Verified
live: 3 sectors render, toggle present, tsc clean, no console errors.

### 2. Value-history line chart (VZ-02 / INVX-01)
expected: The historical value line chart renders from `GET /investments/history`.
The Value / P&L toggle switches the plotted series, and the range selector filters
the date window. A portfolio with no history rows degrades gracefully (empty state).
result: CHART WORKS — the reported "600M on Jul 11" is NOT a code bug: a single
corrupt Jul-11 BTC snapshot stored market_value=600,000,000 (implied 87.8B IDR/BTC
vs that day's real ~1.159B; correct value ≈7.9M like Jul 12/13). Plus leftover
NULL-platform TSTSCH test-orphan snapshot rows. Both are bad DATA, awaiting user
decision to correct (no silent mutation of financial data).

### 3. Chat multi-platform add / delete (CH-01)
expected: In a live chat session, adding a holding on a specific platform
("add 5 BBCA on Stockbit") and deleting an account/holding ("delete my BCA account")
both work end-to-end — the LLM selects `find_platforms` / `find_accounts`, proposes
the correct write, and the confirmed write applies.
result: CODE FIXED, needs live retest — root cause: query.py built the agent's
FunctionTool list separately and never registered find_platforms/find_accounts, so
the LLM got "Tool find_platforms not found" and fell back to list_categories. Fix:
register both as agent read-tools (commit 5c04365). REQUIRES backend container
rebuild (`docker compose up -d --build backend`) then a live chat retest.

## Summary

total: 3
passed: 1
issues: 0
pending: 2
skipped: 0
blocked: 0

## Gaps

- Jul-11 BTC snapshot corrupt (market_value=600,000,000; correct ≈7,915,000). Awaiting
  user decision: correct to real value, delete the row, or leave as-is.
- NULL-platform TSTSCH test-orphan rows in portfolio_value_history (from pre-platform_id
  schema). Deletion blocked pending explicit user OK.
- CH-01 fix needs backend rebuild + live chat retest before item 3 can pass.
- Deferred (not a gap): WR-03 Numeric(18,2) price precision migration.
