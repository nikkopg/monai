# Deferred Items — Phase 07

Out-of-scope discoveries logged during plan execution, per executor scope-boundary rules
(only auto-fix issues directly caused by the current task's changes).

## 07-05

- **`backend/tests/test_settings.py::test_put_settings_requires_key`** fails locally with
  `503 != 401` when `MONAI_API_KEY` env var is unset in the shell running pytest (the
  260703-ja8 fail-closed guard returns 503 for empty-key misconfiguration before the
  401 auth-check path is reached). Not touched by plan 07-05 (`test_settings.py` is not
  in `files_modified`); pre-existing environment/test-isolation issue, not caused by the
  CH-01 delegation fix. Not fixed — out of scope. Re-run with `MONAI_API_KEY` exported to
  confirm it passes normally.
