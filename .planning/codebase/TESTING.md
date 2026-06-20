# Testing

**Analysis Date:** 2026-06-20

## Framework

- **pytest** (`>=8.0.0`) for both packages. Declared in `backend/requirements.txt`
  and `poc/requirements.txt`.
- **No pytest config file** — there is no `pytest.ini`, `pyproject.toml`,
  `setup.cfg`, or `tox.ini`. Tests are run by invoking pytest directly from the
  repo root; discovery relies on default `test_*.py` / `Test*` / `test_*`
  naming. A `.pytest_cache/` exists (tests have been run).
- **No JS/frontend tests** — `ui/package.json` defines only `dev`, `build`,
  `start`; no test runner, no Jest/Vitest/Playwright.

## Test Layout

```
backend/tests/
├── __init__.py
├── test_tools.py     # resolve_period (pure) + tool SQL invariants (integration)
└── test_router.py    # _extract_json model-output parsing (pure)

poc/tests/            # Approach A (throwaway)
├── __init__.py
├── test_parser.py
└── test_db.py
```

Per `TODOS.md` the suite is "21 tests" total. Coverage is concentrated on the
two highest-risk areas of the production backend: **date math** and **router
JSON extraction**.

## Patterns & Style

- **Class-grouped tests** by concern: `TestResolvePeriod`, `TestToolSQL`
  (`backend/tests/test_tools.py`). Router tests are module-level functions
  (`backend/tests/test_router.py`).
- **Pure logic vs. integration split** is explicit and documented in test
  docstrings:
  - *Pure* tests (no DB, no LLM): `resolve_period` boundary logic,
    `_extract_json` parsing — fast, deterministic, always run.
  - *Integration* tests: tool SQL run against **live Postgres** with real data.
- **Conditional skip for DB-dependent tests:** a module-scoped fixture
  `db_available` (`backend/tests/test_tools.py`) probes
  `SELECT COUNT(*) FROM transactions`; it calls `pytest.skip(...)` if Postgres
  is unreachable *or* the table is empty. So integration tests are opt-in by
  environment, never hard failures on a fresh checkout.
- **Invariant-based assertions** rather than golden values (robust to changing
  data): e.g. `spending_total >= 0`, `net ≈ income - spending` (with float
  tolerance `< 1.0`), category totals are positive and descending, largest
  expenses sorted by magnitude. This tests *correctness properties* of the
  hand-written SQL — directly serving the "correct by construction" design.
- **Error-path coverage:** `pytest.raises(ValueError)` for unknown periods
  (`test_unknown_period_raises`) and for malformed model output
  (`test_no_json_raises`).
- **Edge cases covered:** end-date exclusivity (`test_custom_makes_end_exclusive`),
  month/year rollover, `last_30_days` span arithmetic, markdown-fenced and
  prose-wrapped JSON, nested braces, `null` tool.

## Mocking

- **No mocking framework** (`unittest.mock`, `pytest-mock`, etc.) is used.
- Strategy is to test **pure functions directly** (date logic, JSON extraction)
  and run integration tests against a **real database** rather than mocks. The
  LLM is never invoked in tests — only the deterministic `_extract_json` parser
  that consumes model output is tested.

## Fixtures

- `db_available` (module scope) — the only fixture; gates the integration class.
- Tool integration tests import their target function *inside* each test body
  (`from backend.tools import spending_total`) to keep import side effects local.

## Coverage & CI

- **No coverage tooling** configured (no `pytest-cov`, no `.coveragerc`, no
  coverage thresholds).
- **No CI pipeline** — no `.github/workflows/`, CircleCI, or equivalent. Tests
  are run manually.

## How to Run

```bash
# Pure tests run anywhere (no DB needed for resolve_period / _extract_json):
pytest backend/tests/

# Integration tool tests need a loaded Postgres:
docker compose up -d db      # then load data via /import
pytest backend/tests/test_tools.py

# PoC tests:
pytest poc/tests/
```

(The backend dev runner uses `uv run --with-requirements backend/requirements.txt`;
pytest is available in `.venv-backend/bin/pytest`.)

## Known Testing Gaps (from `TODOS.md`)

> "Only `tools.py` and the router JSON parser are tested." Untested:
- `backend/main.py` endpoints — `/transactions` (create+list), `/import`
  (happy path + bad-column 422), `/accounts`.
- `backend/importer.py:parse_csv` — should mirror the PoC parser tests.
- No tests for `query.ask()` end-to-end (would need an LLM stub).
- No frontend tests at all.

---

*Testing analysis: 2026-06-20*
