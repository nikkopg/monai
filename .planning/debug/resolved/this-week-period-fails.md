---
status: resolved
trigger: "UAT Phase 4 Test 3: i got this when clicking this week, other card work — Couldn't load the dashboard — check the backend is running and reload the page."
created: 2026-07-05T10:11:28Z
updated: 2026-08-03T05:42:00Z
---

## Current Focus
<!-- OVERWRITE on each update - reflects NOW -->

hypothesis: CONFIRMED — frontend "This week" pill sends period=this_week, which backend resolve_period()/PERIODS did not recognize; the resulting ValueError was unhandled in the /cashflow/summary endpoint and became HTTP 500, which triggered the dashboard error state
test: complete (static trace + unit repro + live endpoint repro all agree)
expecting: n/a — resolved
next_action: none — both recommended fixes are present in current source (verified 2026-08-03)

## Symptoms
<!-- Written during gathering, then IMMUTABLE -->

expected: Selecting the "This week" period on the /cashflow dashboard loads the dashboard with week-scoped figures, same as other period pills
actual: Clicking "This week" renders the dashboard error state — "Couldn't load the dashboard — check the backend is running and reload the page." All other pills (This month / Last month / This year) work.
errors: HTTP 500 Internal Server Error from GET /cashflow/summary?period=this_week; underlying ValueError: "Unknown period 'this_week'. Valid: ('this_month', 'last_month', 'this_year', 'last_year', 'last_30_days', 'last_90_days', 'all_time', 'custom')"
reproduction: Open /cashflow, click the "This week" period pill (or: curl "http://127.0.0.1:8001/cashflow/summary?period=this_week" → 500)
started: Discovered during Phase 4 UAT (cashflow-dashboard-crud), Test 3

## Eliminated
<!-- APPEND only - prevents re-investigating -->

- hypothesis: "Backend not running / general backend failure (the error copy's literal suggestion)"
  evidence: Live probe — this_month, last_month, this_year all return HTTP 200 with real data from the same server; only this_week returns 500
  timestamp: 2026-07-05T10:16:00Z

- hypothesis: "Date-range/SQL bind bug specific to week boundaries (e.g. empty or invalid range)"
  evidence: resolve_period() has NO week branch at all — execution never reaches SQL; it raises ValueError at backend/tools.py:75 before any query runs
  timestamp: 2026-07-05T10:16:00Z

- hypothesis: "Stale root-owned backend on :8001 serving an old build explains the failure"
  evidence: Unit-level repro against THIS worktree's code (uv run, backend/tools.py) raises the identical ValueError for 'this_week'; the bug exists in current source regardless of which build serves :8001
  timestamp: 2026-07-05T10:16:00Z

## Evidence
<!-- APPEND only - facts discovered -->

- timestamp: 2026-07-05T10:11:28Z
  checked: .planning/debug/knowledge-base.md
  found: Knowledge base does not exist — no prior known patterns to test
  implication: Proceed with fresh hypothesis formation

- timestamp: 2026-07-05T10:13:00Z
  checked: graphify query "cashflow summary period resolution this week" + graphify explain "resolve_period" (main repo graph)
  found: Key nodes — Period type at ui/app/cashflow/page.tsx:50, PERIOD_OPTIONS at :52, resolve_period() at backend/tools.py:40 (called by cashflow_summary, income_total, spending_total, net_total, spending_by_category)
  implication: Scoped investigation to exactly three files

- timestamp: 2026-07-05T10:14:00Z
  checked: ui/app/cashflow/page.tsx:50-57, 83-97, 116-117
  found: Period type = "this_week" | "this_month" | "last_month" | "this_year"; PERIOD_OPTIONS maps "This week" → value "this_week"; loadSummary fetches /api/cashflow/summary?period=${p} and on !r.ok (or throw) sets summaryError to the exact copy the user reported
  implication: The pill sends the literal string "this_week"; any non-2xx response produces the observed error state

- timestamp: 2026-07-05T10:14:30Z
  checked: backend/tools.py:30-33 (PERIODS) and :40-75 (resolve_period)
  found: PERIODS = ('this_month', 'last_month', 'this_year', 'last_year', 'last_30_days', 'last_90_days', 'all_time', 'custom') — NO week entry; resolve_period has no week branch and falls through to `raise ValueError(f"Unknown period {period!r}. Valid: {PERIODS}")` at line 75. grep confirms "this_week" appears nowhere in backend/*.py
  implication: Backend never supported a week period; frontend added a pill the backend cannot resolve

- timestamp: 2026-07-05T10:15:00Z
  checked: backend/main.py:214-237 (GET /cashflow/summary) and ValueError handling across main.py
  found: cashflow_summary calls resolve_period at line 228 with NO try/except; sibling endpoints (lines 141-142, 283-284, 408-409) explicitly map ValueError → HTTPException 422, and there is no global @app.exception_handler(ValueError)
  implication: The ValueError propagates unhandled out of the endpoint → FastAPI converts it to HTTP 500 Internal Server Error

- timestamp: 2026-07-05T10:16:00Z
  checked: Unit repro against THIS worktree's code — uv run --with-requirements backend/requirements.txt python -c "from backend.tools import resolve_period; ..."
  found: this_month → (2026-07-01, 2026-08-01); last_month → (2026-06-01, 2026-07-01); this_year → (2026-01-01, 2027-01-01); this_week → ValueError: Unknown period 'this_week'. Valid: ('this_month', 'last_month', 'this_year', 'last_year', 'last_30_days', 'last_90_days', 'all_time', 'custom')
  implication: Exactly the three working pills resolve; exactly the failing pill raises — perfect differential match with the UAT report

- timestamp: 2026-07-05T10:16:30Z
  checked: Live endpoint probe — curl http://127.0.0.1:8001/cashflow/summary?period={each pill value}
  found: this_week → HTTP 500 "Internal Server Error"; this_month/last_month/this_year → HTTP 200 with real JSON payloads
  implication: End-to-end confirmation of the full failure chain (pill → 500 → frontend error state)

## Resolution
<!-- OVERWRITE as understanding evolves -->

root_cause: |
  Frontend/backend period-key contract mismatch. The "This week" pill in
  ui/app/cashflow/page.tsx (PERIOD_OPTIONS, line 53) sends period=this_week to
  GET /cashflow/summary, but the backend's named-period registry
  (backend/tools.py PERIODS, lines 30-33) contains no week period and
  resolve_period() (lines 40-75) has no week branch — it raises
  ValueError("Unknown period 'this_week'. Valid: (...)") at line 75. The
  /cashflow/summary endpoint (backend/main.py:214-237) calls resolve_period at
  line 228 WITHOUT the try/except ValueError→422 mapping that sibling endpoints
  use, so the exception escapes as HTTP 500. The frontend's loadSummary
  (page.tsx:83-97) treats any non-ok response as total dashboard failure and
  renders "Couldn't load the dashboard — check the backend is running and
  reload the page."
fix: RESOLVED IN SOURCE (verified 2026-08-03, not by this session — landed during later phase work). Both recommended remedies are present: (1) backend/tools.py PERIODS now includes "this_week"/"last_week" (lines 30-34) and resolve_period() has both branches using ISO-Monday half-open bounds (lines 59-67); (2) the /cashflow/summary endpoint now wraps resolve_period() in try/except ValueError → HTTPException(422) (backend/main.py:843-848), matching every sibling endpoint, so an unknown period can never surface as a raw 500 again.
verification: unit repro on current source — resolve_period("this_week") → (2026-08-03, 2026-08-10); resolve_period("last_week") → (2026-07-27, 2026-08-03). No further change required.
files_changed: [backend/tools.py, backend/main.py]  # changed by later phase work, not this debug session
