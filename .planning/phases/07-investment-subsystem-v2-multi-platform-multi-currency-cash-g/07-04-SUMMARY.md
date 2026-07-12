---
phase: 07-investment-subsystem-v2-multi-platform-multi-currency-cash-g
plan: 04
subsystem: portfolio-value-history-chart
tags: [recharts, history, pnl, open-read, wave-1]
status: complete
dependency-graph:
  requires:
    - backend/models.py::PortfolioValueHistory (Phase 5 D-13/D-14)
  provides:
    - backend/portfolio.py::value_history_series
    - GET /investments/history
    - backend/schemas.py::ValueHistoryResponse
    - backend/schemas.py::ValueHistoryPointOut
    - ui/app/investments/ValueHistoryChart.tsx
  affects:
    - ui/app/investments/page.tsx (new history fetch + chart render)
tech-stack:
  added: []
  patterns:
    - "Pure read-only calculator (portfolio_summary convention): no commit, groups PortfolioValueHistory rows by snapshot_date"
    - "ValueError -> HTTPException(422) at the API boundary (project-wide convention)"
    - "Recharts LineChart clone of TrendChart.tsx (Bar->Line, date x-axis), explicit-height wrapper load-bearing"
key-files:
  created:
    - ui/app/investments/ValueHistoryChart.tsx
  modified:
    - backend/portfolio.py
    - backend/main.py
    - backend/schemas.py
    - backend/tests/test_portfolio.py
    - ui/app/investments/page.tsx
decisions:
  - "value_history_series aggregates ALL rows for a date with no ticker/asset_type filter — cash rows (once Plan 02 writes them) appear automatically, matching the plan's 'cash is a first-class line, not filtered out' requirement"
  - "Range tokens (1M/3M/6M/All) implemented as a fixed _HISTORY_RANGES dict mapping to a day-count cutoff; unrecognized token raises ValueError, mapped to 422 — matches the 07-UI-SPEC.md range-selector copy contract verbatim"
  - "Aggregation test asserts DELTAS (before/after fixture insert) rather than absolute per-date totals, since portfolio_value_history is a shared dev DB that may already hold rows for 'today' from prior manual/dev seeding — makes the test robust without needing a fully isolated test DB"
  - "ValueHistoryChart view toggle (Value/P&L) renders exactly one Line at a time per 07-UI-SPEC.md's 'mutually exclusive tabs, not overlaid series' rule; P&L line color is sign-based off the latest visible point (Success/Destructive), Value line is always Accent"
metrics:
  duration: ~35m
  completed: 2026-07-12
---

# Phase 7 Plan 4: Portfolio Value History Chart Summary

Shipped the VZ-02/INVX-01 historical line chart end-to-end: `value_history_series()`
aggregates the already-populated `portfolio_value_history` snapshots (Phase 5 D-13/D-14)
into a daily {value, P&L} series with a range filter, `GET /investments/history` exposes
it as an open read (no API key, matching `/investments/summary`), and
`ValueHistoryChart.tsx` (a Recharts `LineChart` clone of `TrendChart.tsx`) renders it with
a value/P&L toggle and a 1M/3M/6M/All range selector, wired into `page.tsx` between the
P&L summary and the "Log event" CTA per `07-UI-SPEC.md`'s locked placement. No `fx.get_rate`
call happens at read time — this plan's read path is independent of Plans 01/02 — but the
series' cash coverage depends on Plan 02's `snapshot_all_holdings` cash special-case having
written cash rows.

## What Was Built

**Task 1 — `value_history_series()` + `GET /investments/history`:**
- `backend/portfolio.py::value_history_series(db, range_param="All")` — queries every
  `PortfolioValueHistory` row (no ticker/asset_type filter, so cash rows are included the
  moment they exist), groups by `snapshot_date`, and sums `market_value` /
  `(market_value - cost_basis)` as Decimal per date. `_HISTORY_RANGES` maps `1M/3M/6M/All`
  to a day-count cutoff (`None` for `All`); an unrecognized token raises `ValueError`. No
  rows for the filtered window returns `[]`, not an error (D-13 no-backfill semantics).
- `backend/main.py::investments_history` — `GET /investments/history?range=...`, no
  `Depends(require_api_key)` (open read, matches `investments_summary`), wraps `ValueError`
  in `HTTPException(422)`.
- `backend/schemas.py::ValueHistoryPointOut` / `ValueHistoryResponse` — follow the
  `*Out`/`*Response` naming convention; money fields use `MoneyDecimal` (Decimal validation,
  float JSON serialization).
- `backend/tests/test_portfolio.py` — 3 new tests: aggregation (multi-ticker same-day sum,
  asserted as a before/after delta to tolerate pre-existing dev-DB rows), range filter +
  bad-range `ValueError`, and empty-history graceful case. 8/8 tests in the file pass.

**Task 2 — `ValueHistoryChart.tsx` + page wire:**
- `ui/app/investments/ValueHistoryChart.tsx` — clone of `TrendChart.tsx` with `Bar`→`Line`
  and a `date` x-axis. Props-driven (`data`, `range`, `onRangeChange`) — no internal fetch,
  matching `AllocationPieChart`'s stated statelessness convention from `07-UI-SPEC.md`.
  Renders a title row with the 1M/3M/6M/All range-selector pills, a second toggle row for
  Value/P&L (one `Line` at a time), and the explicit-height `ResponsiveContainer` wrapper
  (`width: 100%, height: 280` — load-bearing per the documented Recharts blank-render
  pitfall). Empty/sparse state (`data.length < 2`) renders the D-13-honest "Not enough
  history yet" copy instead of the chart.
- `ui/app/investments/page.tsx` — added `history`/`historyRange` state and a `loadHistory`
  `useCallback` fetching `GET /api/investments/history?range=...` independently of the
  existing `load()` (summary/platforms), so a "Refresh prices" click does not re-fetch
  history. Chart renders between the Unrealized/Realized P&L grid and the "Log event" CTA
  row, per `07-UI-SPEC.md`'s locked chart placement.

## Verification

- `cd backend && python -m pytest tests/test_portfolio.py -x` → **8 passed** (via
  `uv run --with-requirements backend/requirements.txt`).
- `cd ui && npx tsc --noEmit` → clean, no errors.
- `grep -n 'require_api_key' backend/main.py | grep history` → no match (open read confirmed).
- `grep -n 'height: 280' ui/app/investments/ValueHistoryChart.tsx` → present.
- `grep -n 'ValueHistoryChart' ui/app/investments/page.tsx` → imported + rendered.
- Existing holdings table / summary blocks in `page.tsx` unchanged (only additive edits).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 — blocking] Local Postgres was missing migration 008 (`fx_rate_cache` +
`portfolio_events.currency`), blocking the entire backend test suite, not just this plan's tests**
- **Found during:** Task 1 verification — the pre-existing `test_recompute_holding_from_events`
  test failed with `psycopg.errors.UndefinedColumn: column portfolio_events.currency does not
  exist` before my new tests ever ran.
- **Issue:** Plan 01 authored and committed `alembic/versions/008_fx_rate_cache.py` to `main`,
  but the local dev DB (`monai-db`, port 5434) was still on migration 007's head
  (`c1d2e3f4a5b6`) — the migration was never applied to this environment. This is not new
  schema work; it's running an already-reviewed, already-committed migration.
- **Fix:** `uv run --with-requirements backend/requirements.txt --with alembic -- alembic
  upgrade head`, which applied `d3e4f5a6b7c8` (migration 008) cleanly. No source change.
- **Files modified:** none (DB state only, via the existing migration file)
- **Commit:** N/A (no source change; DB-only operation)

**2. [Rule 1 — bug] Aggregation test initially asserted absolute per-date totals, which
collided with pre-existing dev-DB rows for "today"**
- **Found during:** Task 1 — first test run failed with `AssertionError: assert
  Decimal('651894043.01') == Decimal('1600')`, because other `portfolio_value_history` rows
  already existed for today's date in this shared dev DB (from prior manual/dev seeding),
  and `value_history_series` correctly sums ALL rows for a date by design (whole-portfolio
  view, no ticker filter — this is the intended behavior, not a bug in the function).
- **Fix:** Rewrote `test_value_history_series_aggregates_per_date` to capture the series
  before inserting fixture rows, then assert the delta (after − before) per date/field,
  making the test robust to any pre-existing rows without weakening the aggregation
  assertion itself.
- **Files modified:** `backend/tests/test_portfolio.py`
- **Commit:** `90bcafb` (Task 1, folded into the same commit as the test was still being
  authored pre-verification)

No other deviations — plan executed as written otherwise.

## Known Stubs

None. `value_history_series` reads real `portfolio_value_history` rows and `ValueHistoryChart`
renders whatever the endpoint returns — no hardcoded/mock data path exists. The chart will show
the D-13-honest empty state until the collector has written 2+ days of snapshots, which is
expected behavior per the plan, not a stub.

## Threat Flags

None beyond the plan's own `<threat_model>` — all five registered threats (T-07-04-INJ,
T-07-04-INT, T-07-04-DoS, T-07-04-XSS, T-07-04-SC) were mitigated exactly as specified: the
`range` parameter is validated against a fixed dict (never interpolated into SQL), P&L is
read directly from already-audited snapshots (no client-side money math), the range filter
caps the row scan, Recharts/React auto-escaping renders all values, and no new npm package
was introduced.

## Self-Check: PASSED

- FOUND: backend/portfolio.py (value_history_series)
- FOUND: backend/main.py (GET /investments/history)
- FOUND: backend/schemas.py (ValueHistoryResponse, ValueHistoryPointOut)
- FOUND: ui/app/investments/ValueHistoryChart.tsx
- FOUND: ui/app/investments/page.tsx (ValueHistoryChart wired)
- FOUND commit: 90bcafb (Task 1)
- FOUND commit: 7e117c8 (Task 2)
