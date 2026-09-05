---
phase: 12-typed-accounts-transfer-funding-schema-foundations
plan: 03
subsystem: database
tags: [sqlalchemy, postgresql, tools-registry]

# Dependency graph
requires:
  - phase: 12-typed-accounts-transfer-funding-schema-foundations
    plan: 02
    provides: "cashflow_transactions exclusion view (NOT EXISTS keyed on type='investment', NULL-account_id-safe), migration 010 applied to live DB"
provides:
  - "Every cashflow total/listing in backend/tools.py reads FROM cashflow_transactions instead of FROM transactions — the investment-account double-count is structurally impossible in the application layer, not just at the DB view level"
affects: [13-transfer-funding-writes, 15-net-worth-dashboard]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Read tools inherit a structural data-quality invariant by reading a view instead of the base table — no per-tool WHERE clause discipline required, so future cashflow tools can't reintroduce the double-count by omission"

key-files:
  created: []
  modified:
    - backend/tools.py

key-decisions:
  - "Switched 10 FROM-clause sites across 10 functions: spending_total, income_total, net_total, spending_by_category (_ROLLUP_FROM, shared by both its sql and child_sql queries), spending_in_category, transaction_count, largest_transactions, average_daily_spending (the total only), monthly_trend, find_transactions"
  - "Plan text described the 10th switch site as 'spending_by_category's grand-total denominator at L302' — the actual code at that line belongs to spending_in_category (a genuine, independent cashflow-total-by-category function with no percentage logic anywhere in spending_by_category). Treated as a function-name mislabel from plan drafting (line number and SQL pattern were both correct); switched spending_in_category's FROM clause since it is unambiguously a cashflow total per the plan's own objective ('every cashflow total... inherits the investment-exclusion') and the switch makes the stated '10 sites' count exact"
  - "Left 5 sites on FROM transactions intentionally: the currency probe (L101), average_daily_spending's MIN/MAX date-span query (L436 — a denominator, not a total), account_balances (per-account list, not an aggregate total — now carries a comment pointing the liquid/investment net-worth split to Phase 15), and the two delete/reassign COUNT guards (L886, L943, L995 — row-existence checks)"

requirements-completed: [ACCT-03]

coverage:
  - id: D1
    description: "tools.spending_total(period='all_time') equals the view-computed spending total (excludes investment-account expenses) — application layer inherits Criterion 2's structural exclusion"
    requirement: "ACCT-03"
    verification:
      - kind: unit
        ref: "python -m pytest backend/tests/test_cashflow_view.py::test_tools_spending_excludes_investment -q"
        status: pass
      - kind: manual
        ref: "Live-DB check: raw_spending (563,759,700) - tools.spending_total (450,755,700) == investment_expense (113,004,000), all three derived live via SQL — confirms the delta the test asserts, not a hardcoded figure"
        status: pass
    human_judgment: false
  - id: D2
    description: "Full backend test suite has no new failures after the switch"
    requirement: "ACCT-03"
    verification:
      - kind: unit
        ref: "python -m pytest backend/tests/ -q"
        status: pass
    human_judgment: false

duration: 20min
completed: 2026-07-25
status: complete
---

# Phase 12 Plan 03: Switch tools.py Cashflow Reads onto the Exclusion View Summary

**Every cashflow total and transaction listing in backend/tools.py now reads FROM cashflow_transactions instead of FROM transactions — 10 FROM-clause sites across 10 functions switched, 5 intentional non-cashflow sites left untouched, application-layer investment double-count structurally eliminated.**

## Performance

- **Duration:** ~20 min
- **Tasks:** 1
- **Files modified:** 1 (backend/tools.py)

## Accomplishments

- Switched `spending_total`, `income_total`, `net_total`, `spending_by_category` (via the shared `_ROLLUP_FROM` constant, used by both its top-level and per-child SQL), `spending_in_category`, `transaction_count`, `largest_transactions`, `average_daily_spending` (the total sub-query only), `monthly_trend`, and `find_transactions` onto `cashflow_transactions`.
- Left `_currency()`'s probe query, `average_daily_spending`'s `MIN(date)/MAX(date)` date-span query, `account_balances` (per-account listing, not an aggregate total), and the three delete/reassign `COUNT(*)` guards (`propose_delete_account`, `propose_rename_category`, `propose_merge_category`) on the base `transactions` table, exactly as the plan's LEAVE list specified.
- Added a one-line code comment above `account_balances`'s SQL pointing the liquid/investment net-worth split to Phase 15.
- Verified live: `test_tools_spending_excludes_investment` is GREEN; `raw_spending (563,759,700) − tools.spending_total (450,755,700) == investment_expense (113,004,000)`, all three values derived live via SQL, confirming the application layer now inherits the exact structural exclusion the view enforces.
- Full suite: 244 passed, 1 pre-existing unrelated failure (`test_settings.py::test_put_settings_requires_key`, logged in `deferred-items.md` from Plan 02, confirmed out of scope).
- Only the FROM-clause table identifier changed at every switched site — WHERE clauses, bound params, and explicit column lists (no `SELECT *`) are byte-for-byte unchanged.

## Task Commits

Each task was committed atomically:

1. **Task 1: Switch every cashflow-total FROM-clause in tools.py to the view** - `d94fd30` (feat)

**Plan metadata:** _pending — this commit_

## Files Created/Modified

- `backend/tools.py` - 10 FROM-clause table-name switches (`transactions` → `cashflow_transactions`) across `spending_total`, `income_total`, `net_total`, `_ROLLUP_FROM`/`spending_by_category`, `spending_in_category`, `transaction_count`, `largest_transactions`, `average_daily_spending`, `monthly_trend`, `find_transactions`; one added code comment on `account_balances`

## Decisions Made

See frontmatter `key-decisions`. The one requiring judgment: the plan's Task 1 `<action>` block described its 10th switch site as belonging to `spending_by_category` ("the grand-total denominator... used for the percentage denominator") at line ~302, but `spending_by_category` in the actual codebase has no percentage/grand-total logic at all — only its shared `_ROLLUP_FROM` constant (already covered as site #4). The real code at line 302 belongs to `spending_in_category`, a separate, genuinely independent cashflow-total-by-category function that reads `FROM transactions` with the identical `SELECT COALESCE(SUM(-amount), 0)` pattern the plan described. Given the plan's own objective — "switch every cashflow total... so the application layer inherits the structural investment-exclusion" — and that the switch makes the plan's stated "ten FROM-clause sites" count land exactly right, this was treated as a function-name mislabel during plan drafting (the line number, SQL shape, and site count were all correct; only the attributed function name was wrong) rather than an out-of-scope addition, and `spending_in_category`'s FROM clause was switched.

## Deviations from Plan

### Auto-fixed Issues

None — no bugs, missing functionality, or blocking issues encountered. The plan/reality reconciliation above (spending_in_category vs. spending_by_category) is a plan-interpretation decision, not a Rule 1-3 auto-fix, and is documented above under Decisions Made rather than as a deviation.

## Issues Encountered

None. `.venv/bin/python` (not the bare `python` on PATH, which is absent) was needed to run pytest with the project's installed dependencies (`fastmcp`, etc.) — a local environment discovery detail, not a code issue.

## User Setup Required

None - the running Docker container's PHASE GATE rebuild (`docker compose up -d --build`) and live API spot-check for the ~investment phantom disappearing from `spending_total`/`net_total` is the plan's final manual verification step, deferred to `/gsd-verify-work` per the plan's `<verification>` block — the automated tests already prove correctness at the DB/tools layer.

## Next Phase Readiness

- Phase 12's Criterion 2 (typed accounts + structural cashflow exclusion) is now fully met at both the DB view layer (Plan 02) and the application/tools layer (this plan) — the investment double-count is impossible to reintroduce in any cashflow-total tool, present or future, without deliberately reading the base table.
- Phase 13 (transfer/funding writes) can build on `transactions.transfer_pair_id` and `portfolio_events.source_account_id` (Plan 02) plus the now-consistent cashflow-total read surface from this plan.
- Phase 15 (net worth dashboard) has an explicit code-comment marker on `account_balances` for where the liquid/investment split needs to land.
- One pre-existing, unrelated test failure (`test_settings.py::test_put_settings_requires_key`) remains open — tracked in `deferred-items.md` from Plan 02, not a regression from this plan.
- Manual PHASE GATE step (rebuild container, spot-check the live API) still needs to run before `/gsd-verify-work` closes Phase 12.

---
*Phase: 12-typed-accounts-transfer-funding-schema-foundations*
*Completed: 2026-07-25*

## Self-Check: PASSED

- FOUND: .planning/phases/12-typed-accounts-transfer-funding-schema-foundations/12-03-SUMMARY.md
- FOUND: backend/tools.py
- FOUND: d94fd30
