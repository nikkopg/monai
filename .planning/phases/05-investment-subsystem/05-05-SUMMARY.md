---
phase: 05-investment-subsystem
plan: 05
subsystem: ai-query-tools
tags: [correlation, portfolio-events, spending, agent-tools, tdd]
status: complete
requires:
  - 05-03 (portfolio_events ledger — provides the buy rows this tool reads)
provides:
  - "spending_before_after_purchase tool (CHAT-03 / D-15)"
  - "TOOLS registry entry exposing it on the agent /query path"
affects:
  - backend/tools.py
tech-stack:
  added: []
  patterns:
    - "Structured-dict return keyed on 'tool'"
    - "Parameterized SQL only (correctness-by-construction)"
    - "Reuse of spending_in_category custom-period contract (no new date SQL)"
    - "Honest error dict instead of fabricated number"
key-files:
  created: []
  modified:
    - backend/tools.py
    - backend/tests/test_tools.py
decisions:
  - "Pivot = MIN(date) of earliest 'buy' event for the ticker (D-15)"
  - "Equal-length windows: N = days since pivot; before [pivot-N, pivot-1], after [pivot, today]"
  - "Pivot day itself counts as 'after' (after_start = pivot inclusive)"
  - "No buy event or future/today purchase → structured error dict, never a number (T-05-05-FAB)"
metrics:
  duration: ~5 min
  completed: 2026-07-11
  tasks: 1
  files: 2
---

# Phase 5 Plan 5: Spending↔Portfolio Correlation Tool Summary

`spending_before_after_purchase(ticker, category)` — the CHAT-03 payoff of the INV-07 event ledger: resolves the earliest buy event for a ticker as a pivot date and compares category spending in equal-length before/after windows, returning before/after totals + delta, or an honest error when it can't.

## What Was Built

- **`backend/tools.py`** — new `spending_before_after_purchase(ticker, category)` tool placed right after its callee `spending_in_category`, plus a `TOOLS` registry entry so the agent `/query` path exposes it. Pivot is `SELECT MIN(date) FROM portfolio_events WHERE ticker=:ticker AND event_type='buy'` (parameterized). `n_days = today − pivot`; before window `[pivot−n_days, pivot−1]`, after window `[pivot, today]` (equal length). Each window totals via the existing `spending_in_category(period="custom", start_date=..., end_date=...)` contract — no new date-range SQL.
- **`backend/tests/test_tools.py`** — `test_spending_before_after_purchase`: seeds a `portfolio_events` buy pivot + one before-window expense and two after-window expenses (including a pivot-day boundary expense) under a unique ticker/category, asserts `pivot_date`, `window_days`, `before_total`/`after_total`/`delta`/`delta_pct`, and the no-buy-event error path; cleans up in a `finally`.

## Verification Results

- `pytest backend/tests/test_tools.py::test_spending_before_after_purchase -x -q` → **1 passed**.
- `python -c "from backend.tools import TOOLS; assert 'spending_before_after_purchase' in TOOLS"` → **registered**.
- Full `backend/tests/test_tools.py` → **22 passed** (no regressions).

## TDD Gate Compliance

- RED: `b75f174 test(05-05): add failing test...` — failed with `ImportError` (tool absent) before implementation.
- GREEN: `08e3a33 feat(05-05): spending_before_after_purchase...` — test green after implementation.
- REFACTOR: none needed.

## Honesty / Threat Mitigations

- **T-05-05-FAB (fabrication):** no buy event → `{"tool":..., "error": "No buy event found..."}`; today/future purchase (`n_days < 1`) → `{"tool":..., "error": "...no 'after' window yet."}`. Test asserts the unknown-ticker path returns an error dict with no `before_total` key — never a made-up number.
- **T-05-05-SQL (tampering):** `ticker` and `category` reach only bound parameters (`text(... :ticker ...)` and `spending_in_category`'s parameterized `:cat`); no string-built SQL, the LLM sees only the tool name/args.

## Deviations from Plan

None — plan executed as written. (Used `datetime.date`/`datetime.timedelta` qualified names to match the module's existing `import datetime` style rather than the research skeleton's bare `date`/`timedelta`; behavior identical.)

## Self-Check: PASSED

- `backend/tools.py` contains `spending_before_after_purchase` and its `TOOLS` entry — FOUND.
- `backend/tests/test_tools.py` contains `test_spending_before_after_purchase` — FOUND.
- Commit `b75f174` (RED) — FOUND.
- Commit `08e3a33` (GREEN) — FOUND.
