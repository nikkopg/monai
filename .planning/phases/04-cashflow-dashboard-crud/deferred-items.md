# Deferred Items — Phase 04 (cashflow-dashboard-crud)

Out-of-scope discoveries logged during plan execution, not fixed per the
executor scope-boundary rule (only auto-fix issues directly caused by the
current task's changes).

## 04-01

- `backend/tests/test_settings.py::test_put_settings_requires_key` fails in
  this environment (503 instead of expected 401) because `MONAI_API_KEY` is
  unset/misconfigured in the local test run. Pre-existing, unrelated to
  `backend/writes.py` / `_execute_proposal_payload` changes (Phase 3 area,
  the empty-key 503 guard from commit `cb80d8c`). Not fixed here — out of
  scope for the 04-01 write-path extraction plan.

## 04-06

- Same `backend/tests/test_settings.py::test_put_settings_requires_key` 503
  failure still present in this environment during the full-suite regression
  (109 passed, 1 failed). Re-confirmed out of scope: 04-06 only touches
  `backend/tools.py` (period registry) and `backend/main.py`
  (`cashflow_summary` ValueError→422 mapping) plus their tests — none of which
  exercise `PUT /settings`. Left as-is per the executor scope boundary.
