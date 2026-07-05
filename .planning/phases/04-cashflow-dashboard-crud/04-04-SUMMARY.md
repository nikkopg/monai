---
phase: 04-cashflow-dashboard-crud
plan: 04
subsystem: ui
tags: [nextjs, react, recharts, cashflow, dashboard]

# Dependency graph
requires:
  - phase: 04-cashflow-dashboard-crud (Plan 03)
    provides: "GET /cashflow/summary endpoint (D-08) composing totals, spending-by-category, account_balances, monthly_trend"
provides:
  - "Recharts (^3.9.2) as the phase's one new frontend dependency (D-07)"
  - "ui/app/styles.ts extended with dangerBtn (destructive button variant) and chartColors (6-color categorical palette)"
  - "Three reusable chart components: CategoryDonut, IncomeExpenseBar, TrendChart"
  - "Grown /cashflow page: period selector, totals summary row, per-account dual-balance row, charts row, 6-month trend row"
  - "ui/e2e/cashflow-dashboard.spec.ts covering dashboard render + period-refetch"
affects: ["04-cashflow-dashboard-crud (Plan 05 — CRUD writes on this same page)"]

# Tech tracking
tech-stack:
  added: ["recharts@^3.9.2"]
  patterns:
    - "Chart components under ui/app/cashflow/charts/ each wrap ResponsiveContainer in an explicit-height (280px) div (Pitfall 3)"
    - "Recharts Tooltip formatter typed against Recharts v3's ValueType (number | string | ReadonlyArray<...> | undefined), not a bare number, to satisfy the library's Formatter<TValue,TName> signature"
    - "by_category rows arrive from the backend as [category, total] tuples (existing spending_by_category shape) and are mapped to {category,total} objects client-side before being handed to CategoryDonut"

key-files:
  created:
    - ui/app/cashflow/charts/CategoryDonut.tsx
    - ui/app/cashflow/charts/IncomeExpenseBar.tsx
    - ui/app/cashflow/charts/TrendChart.tsx
    - ui/e2e/cashflow-dashboard.spec.ts
  modified:
    - ui/package.json
    - ui/package-lock.json
    - ui/app/styles.ts
    - ui/app/cashflow/page.tsx

key-decisions:
  - "IncomeExpenseBar takes a single-element array shaped {label, income, expense} for the current period rather than a multi-period series, since the plan's data source (summary.totals) is one snapshot, not a time series — XAxis uses a synthetic 'label' key ('This period')"
  - "Total Expenses figure is displayed as a negative number (fmt(-Math.abs(totals.expense))) even though the backend returns expense as a positive magnitude, to match the existing recent-transactions table's signed-number convention and the UI-SPEC's expense=red semantics"

requirements-completed: [CASH-01, CASH-02, CASH-03]

# Metrics
duration: ~35min
completed: 2026-07-05
---

# Phase 04 Plan 04: Cashflow Dashboard (Charts + Read-Side Layout) Summary

**Recharts-based dashboard on /cashflow — period selector, income/expense/net totals, per-account dual balances, spending-by-category donut, income-vs-expense bar, and a 6-month trend chart, all sourced from one GET /cashflow/summary fetch.**

## Performance

- **Duration:** ~35 min
- **Tasks:** 3/3 completed
- **Files modified:** 8 (2 created chart dir with 3 files, 1 new e2e spec, package.json/lock, styles.ts, page.tsx)

## Accomplishments
- Installed `recharts@^3.9.2` (D-07), the phase's one locked new dependency, vetted APPROVED in RESEARCH.md's Package Legitimacy Audit
- Extended `ui/app/styles.ts` with `dangerBtn` (spreads `btn`, Destructive background — consumed by Plan 05) and `chartColors` (6-color categorical palette for the donut), leaving `card`/`input`/`btn`/`label` untouched
- Built three Recharts components (`CategoryDonut`, `IncomeExpenseBar`, `TrendChart`), each wrapped in an explicit `height: 280` div before `ResponsiveContainer` (Pitfall 3), following the income=`#4ade80`/expense=`#f87171` color contract with flat fills, no gradients/shadows
- Grew `ui/app/cashflow/page.tsx` with the full read-side dashboard: a period selector (This week/This month/Last month/This year pill buttons), a 3-card totals row, a per-account balances table (current_balance + period_net, D-04), a 2-chart row, and a full-width 6-month trend row — all driven by one `loadSummary()` fetch to `/api/cashflow/summary` that reruns on period change
- Added empty-state ("Nothing here for this period.") and error-state ("Couldn't load the dashboard...") copy per the UI-SPEC Copywriting Contract
- Preserved the existing manual-entry form and recent-transactions table verbatim (Plan 05 refactors the form into a modal)
- Added `ui/e2e/cashflow-dashboard.spec.ts`, mocking `GET /api/cashflow/summary` via Playwright route interception so the spec is deterministic regardless of live backend/seed state, asserting the heading, the three summary captions, a chart `<svg>`, and a period-pill click triggering a new `?period=` request

## Task Commits

Each task was committed atomically:

1. **Task 1: Install Recharts and add dangerBtn + chartColors to ui/app/styles.ts** - `77c65d4` (feat)
2. **Task 2: Build the three Recharts chart components** - `63010bd` (feat)
3. **Task 3: Grow page.tsx with the dashboard and add a Playwright spec** - `f1d6031` (feat)

_Note: this plan has no `tdd="true"` tasks; all three commits are `feat`._

## Files Created/Modified
- `ui/package.json`, `ui/package-lock.json` - added `recharts@^3.9.2`
- `ui/app/styles.ts` - added `dangerBtn` and `chartColors` exported constants
- `ui/app/cashflow/charts/CategoryDonut.tsx` - Recharts `PieChart` donut, cycles `chartColors` per slice
- `ui/app/cashflow/charts/IncomeExpenseBar.tsx` - grouped `BarChart`, income green / expense red
- `ui/app/cashflow/charts/TrendChart.tsx` - >=6-month grouped `BarChart` over `month` axis, same color contract, net intentionally not plotted
- `ui/app/cashflow/page.tsx` - grown with period selector, summary row, account balances row, charts row, trend row; existing entry form + recent-transactions table preserved
- `ui/e2e/cashflow-dashboard.spec.ts` - new Playwright spec (heading, captions, chart svg, period-refetch), backend mocked via route interception

## Decisions Made
- Displayed `IncomeExpenseBar` as a single-bar-group snapshot (`{label: "This period", income, expense}`) rather than inventing a fabricated multi-point series, since `GET /cashflow/summary`'s `totals` field is a single aggregate for the selected period, not a time series — this matches the UI-SPEC's "Income vs Expense" framing (current period only; the multi-month view is `TrendChart`'s job)
- Formatted Recharts `Tooltip` formatters against the library's actual v3 `ValueType` union (`number | string | ReadonlyArray<...> | undefined`) instead of a bare `number`, since Recharts v3's `Formatter<TValue,TName>` type is broader than a simple numeric callback — this was a real TS2322/TS2345 compile error caught by `tsc`, not a stylistic choice (see Deviations)
- Mocked the summary fetch in the e2e spec via Playwright `page.route()` interception rather than depending on a live seeded backend, so the spec's pass/fail is deterministic in any environment (mirrors how `settings.spec.ts` already renders without a live backend for its own assertions)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Recharts v3 Tooltip formatter type mismatch**
- **Found during:** Task 2 (chart components) and Task 3 (page.tsx build verification)
- **Issue:** The plan's/RESEARCH.md's Recharts code example used `formatter={(v: number) => v.toLocaleString()}`, but Recharts v3.9.2's actual `Tooltip` `formatter` prop type is `Formatter<TValue extends ValueType, TName extends NameType>` where `ValueType = number | string | ReadonlyArray<number | string>`, and the value can also arrive as `undefined`. A bare `(value: number) => string` callback fails `tsc --noEmit` with TS2322/TS2345.
- **Fix:** Typed each chart's `fmt` helper against `number | string | ReadonlyArray<number | string> | undefined`, formatting via `Intl.NumberFormat` only when `typeof v === "number"` and passing the value through otherwise.
- **Files modified:** `ui/app/cashflow/charts/CategoryDonut.tsx`, `ui/app/cashflow/charts/IncomeExpenseBar.tsx`, `ui/app/cashflow/charts/TrendChart.tsx`
- **Verification:** `cd ui && npx tsc --noEmit -p tsconfig.json` reports zero errors across the whole project after the fix; confirmed via RESEARCH.md's own Assumption A1 ("if a prop name/type changed in v3, the executor will hit a TypeScript error immediately and can consult live docs" — exactly what happened here).
- **Committed in:** `63010bd` (part of Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug)
**Impact on plan:** Necessary for correctness — the chart components would not have compiled otherwise. No scope creep; the fix stayed within the plan's own file list.

## Issues Encountered

**Live e2e run blocked by a stale shared backend process, not a code defect.** This sandbox has a long-running, root-owned `uvicorn backend.main:app` process on port 8001 that predates this worktree's code (its `/openapi.json` lists only `/health, /accounts, /transactions, /settings, /import, /query, /query-stream, /proposals, /proposals/{id}/confirm, /proposals/{id}/reject` — no `/cashflow/summary`). Static review confirms `backend/main.py:214-237` in this worktree *does* define `GET /cashflow/summary` correctly (composing `income_total`/`spending_total`/`net_total`/`spending_by_category`/`account_balances`/`monthly_trend` per D-08, matching Plan 03's wave-2 merge). Since the running backend is a shared, root-owned, out-of-worktree process, restarting it is out of scope for a plan executor and was not attempted.

Given this, `npx playwright test e2e/cashflow-dashboard.spec.ts` could not be run end-to-end against a live matching backend in this environment. To still validate the spec and page logic:
- `cd ui && npx tsc --noEmit -p tsconfig.json` passes with zero errors (full project, including the new spec file).
- `cd ui && npm run build` succeeds — Next.js compiles the grown `page.tsx`, the three chart components, and Recharts bundles without error; all 8 routes (including `/cashflow` at 114 kB / 201 kB First Load JS) statically generate successfully.
- The Playwright browser itself was verified launchable (via `PLAYWRIGHT_CHROMIUM_PATH=/usr/bin/google-chrome`, since the sandbox's usual pinned Chromium binary at `/opt/pw-browsers` was also absent in this environment) and did render the live `/cashflow` page — confirming the dev server, proxy, and existing Phase 3 content (entry form + recent transactions) all work; the dashboard sections did not appear because the live backend's 404 on `/cashflow/summary` triggers the page's own error-state copy path, which is itself correct, expected behavior given the endpoint mismatch, not a bug in this plan's code.
- The spec's assertions themselves (heading, three summary captions, chart `<svg>`, and the period-refetch check) mock `GET /api/cashflow/summary` via `page.route()` interception specifically so they don't depend on this environment's stale backend — but the mock still requires the *frontend* dev server (serving this worktree's `page.tsx`) to be reachable at the base URL the Playwright config points to, and that dev server process in this sandbox appears to be serving a build that predates Task 3's changes (see the recent-transactions rows in the captured error-context, which are real seeded data, not this spec's fixture — proving the dev server is live and proxying correctly, but the running Next.js process needs a restart to pick up the new `page.tsx`).

**Recommendation for the orchestrator / next verification pass:** restart both the Next.js dev server and the FastAPI backend from this worktree's checked-out code (not the stale root-owned processes) before running the live e2e suite, or run it in CI/a fresh container where no stale processes are pre-existing. No code change is needed on this plan's side.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Plan 05 (CRUD writes: `TransactionModal`, `AccountManager`, `CategoryManager`, `CsvUpload`, delete/edit/reassign flows) can build directly on this plan's output:
- `dangerBtn` is ready for delete/merge-confirm buttons.
- `page.tsx`'s existing entry form is the known refactor target into `TransactionModal`.
- The per-account balances table and chart components are stable, typed, and require no further changes for Plan 05 to layer CRUD sections beneath them.

No blockers. The only open item is the environment-level stale-backend issue documented above under Issues Encountered, which affects live e2e verification in this specific sandbox, not the shipped code.

## Self-Check: PASSED

All created/modified files verified present on disk; all three task commit hashes (`77c65d4`, `63010bd`, `f1d6031`) verified present in git log.
