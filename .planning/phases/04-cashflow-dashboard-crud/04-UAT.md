---
status: diagnosed
phase: 04-cashflow-dashboard-crud
source: [04-01-SUMMARY.md, 04-02-SUMMARY.md, 04-03-SUMMARY.md, 04-04-SUMMARY.md, 04-05-SUMMARY.md]
started: 2026-07-05T06:26:47Z
updated: 2026-07-05T06:35:00Z
---

## Current Test
<!-- OVERWRITE each test - shows where we are -->

[testing complete]

## Tests

### 1. Cold Start Smoke Test
expected: Stop any running backend/frontend/DB, then start the full stack from scratch. FastAPI boots without errors, Postgres is reachable, and the app loads in the browser showing live data (health check / homepage / /cashflow returns real data, not an error state).
result: pass

### 2. Cashflow Dashboard Loads
expected: Navigate to /cashflow. The page shows an income/expense/net totals row (3 cards), a per-account balances table with current balance + this-period net per account, a spending-by-category donut, an income-vs-expense bar, and a full-width 6-month trend chart — all populated from real data.
result: pass

### 3. Period Selector Refetches
expected: The dashboard has period pills (This week / This month / Last month / This year). Clicking a different period re-fetches and the totals, per-account period net, category donut, and charts update to reflect the selected period (trend stays ≥6 months).
result: issue
reported: "i got this when clicking this week, other card work — Couldn't load the dashboard — check the backend is running and reload the page."
severity: major

### 4. Charts Render Correctly
expected: Spending-by-category donut shows one colored slice per category. Income vs Expense bar shows income in green and expense in red. The 6-month trend chart shows a bar series across months. No overlapping/broken/empty chart areas.
result: pass

### 5. Add Transaction (Modal)
expected: Click "Add transaction" — a modal opens (no inline form on the page anymore). Fill it in and submit. The modal closes, the new transaction appears in the recent-transactions list, and the dashboard totals + per-account balances update without a page reload.
result: pass

### 6. Edit Transaction
expected: Each transaction row has an Edit action. Clicking it opens the same modal pre-filled with that transaction's values. Change something and save — the row reflects the edit and the dashboard figures update live.
result: pass

### 7. Delete Transaction
expected: Each transaction row has a Delete action. Clicking it opens a confirm dialog. Confirming removes the transaction from the list and updates the totals/balances; cancelling leaves it unchanged.
result: pass

### 8. Account Create + Edit
expected: In the account management section you can create a new account and inline-edit an existing account's name. Changes appear immediately in the per-account balances list without a page reload.
result: pass

### 9. Delete Account with Reassign
expected: Deleting an account that has transactions does NOT silently drop them — the confirm dialog shows how many transactions are affected and offers a destination-account picker. Choosing a destination and confirming reassigns those transactions to it, then deletes the account. Deleting an empty account just deletes it.
result: pass

### 10. Category Rename
expected: In the category management section, each category shows a live affected-transaction count. Renaming a category remaps all its matching transactions to the new name; the count and any category-based figures (donut) reflect the change.
result: pass
note: "User observed 'jajan' and 'Jajan' exist as two separate categories — categories are case-sensitive, fragmenting spending. Logged as a separate minor gap (test 10). Merge is the intended consolidation path."

### 11. Category Merge
expected: Merging one category into another shows the affected count and requires a confirm dialog before applying. After confirming, transactions from the source category now count under the destination category, and the source no longer appears.
result: pass

### 12. CSV Upload
expected: The CSV upload control lets you pick a Wallet CSV export and import it. After import it reports how many rows were imported and how many skipped (Skipped shown in red only when > 0), and the new transactions/figures appear on the dashboard.
result: pass

## Summary

total: 12
passed: 11
issues: 2
pending: 0
skipped: 0
blocked: 0

## Gaps

- truth: "Selecting the 'This week' period loads the dashboard with week-scoped figures"
  status: failed
  reason: "User reported: i got this when clicking this week, other card work — Couldn't load the dashboard — check the backend is running and reload the page."
  severity: major
  test: 3
  root_cause: "Frontend/backend period-key contract mismatch: the 'This week' pill sends period=this_week, but PERIODS in backend/tools.py has no week entry, so resolve_period() raises ValueError. /cashflow/summary is the only endpoint calling resolve_period without the standard ValueError→HTTPException(422) mapping, so it surfaces as HTTP 500 and the frontend renders its generic error state."
  artifacts:
    - path: "ui/app/cashflow/page.tsx"
      issue: "Lines 50-57: Period type + PERIOD_OPTIONS include this_week, a key the backend doesn't recognize; lines 83-97: loadSummary collapses any non-ok into the generic error copy"
    - path: "backend/tools.py"
      issue: "Lines 30-33: PERIODS tuple lacks any week entry; lines 40-75: resolve_period() has no week branch, raises ValueError at line 75"
    - path: "backend/main.py"
      issue: "Lines 214-237: /cashflow/summary calls resolve_period (line 228) without ValueError→422 mapping, so invalid period becomes a raw 500"
  missing:
    - "Add 'this_week' to PERIODS and a this_week branch in resolve_period (ISO-Monday week start, half-open [monday, next_monday) bounds, consistent with existing conventions)"
    - "Wrap /cashflow/summary handler with the standard try/except ValueError → HTTPException(422)"
    - "(Optional) frontend distinguishes 4xx from connectivity failure in error copy; consider last_week sibling"
  debug_session: ".planning/debug/this-week-period-fails.md"

- truth: "The same category is not duplicated by a typo or case difference ('jajan' vs 'Jajan')"
  status: failed
  reason: "User observed during rename test: 'why jajan and Jajan created 2 different categories?' — categories are free-text and case-sensitive, so typing the name by hand creates duplicate categories that fragment spending."
  severity: minor
  test: 10
  root_cause: "Category is entered as a free-text field on the transaction form; there is no constraint on category names and no normalization, so any spelling/case variant ('jajan' vs 'Jajan') becomes a distinct category value stored on the transaction row."
  user_fix_direction: "Replace the free-text category input in the Add/Edit Transaction modal with a dropdown/select populated from the existing categories (GET /categories), so the user chooses an existing category instead of retyping it. (Optional: still allow creating a new category deliberately, but default to selection to prevent accidental typos/case duplicates.)"
  artifacts:
    - path: "ui/app/cashflow/TransactionModal.tsx"
      issue: "Category entered via free-text input, allowing typo/case-variant duplicates"
  missing:
    - "Change TransactionModal category field from free-text input to a select sourced from GET /categories"
    - "(Optional) allow an explicit 'add new category' affordance rather than free typing by default"
  debug_session: "(inline — cause understood from UAT; no debug agent needed)"
