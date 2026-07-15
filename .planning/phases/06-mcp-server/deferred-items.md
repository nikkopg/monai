# Deferred Items — Phase 06 (MCP Server)

## Pre-existing test failures (out of scope for 06-01)

Observed during 06-01 verification (`python -m pytest backend/tests -q`), confirmed
pre-existing via `git stash` (present before this plan's changes, unrelated files):

- `backend/tests/test_prices.py::test_fetch_idx_price_fallback` — `ModuleNotFoundError`
- `backend/tests/test_prices.py::test_fetch_idx_price_success` — `ModuleNotFoundError`
- `backend/tests/test_scheduler.py::test_build_scheduler_registers_daily_job`
- `backend/tests/test_settings.py::test_put_settings_requires_key` — assertion failure

None of these files were touched by 06-01 (fastmcp pin + test_mcp.py scaffold only).
Out of scope per deviation-rules scope boundary — not fixed here.
