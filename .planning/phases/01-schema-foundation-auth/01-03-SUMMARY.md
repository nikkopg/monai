---
phase: 01-schema-foundation-auth
plan: "03"
subsystem: backend/schemas
tags: [decimal, pydantic-v2, serialization, test-fixtures, money-type]

dependency_graph:
  requires:
    - "01-01: Alembic setup (FND-01 storage side)"
    - "01-02: Auth dependency (FND-02)"
  provides:
    - "MoneyDecimal shared type reusable in Phase 2/5 schemas"
    - "backend/tests/conftest.py TestClient + api_key fixtures used by Plan 02 test_auth.py"
  affects:
    - "backend/schemas.py TransactionCreate.amount and TransactionOut.amount"
    - "Any API call returning transaction amounts (now JSON numbers, not strings)"

tech_stack:
  added:
    - "alembic>=1.13.0 (added to requirements.txt)"
    - "httpx>=0.27.0 (test dependency for TestClient async support)"
    - "pytest>=8.0.0 (pinned in requirements.txt)"
  patterns:
    - "Pydantic v2 PlainSerializer annotated type alias for Decimal-to-float JSON serialization"
    - "pytest conftest.py session-scoped TestClient fixture"
    - "Monkeypatch on module-level singleton (_CONFIGURED_KEY) for auth fixture"

key_files:
  created:
    - backend/tests/conftest.py
    - backend/tests/test_decimal.py
  modified:
    - backend/schemas.py
    - backend/requirements.txt

decisions:
  - "D-14: Decimals serialize as JSON numbers via PlainSerializer(float, when_used='json')"
  - "D-15: Single MoneyDecimal type alias defined once in schemas.py, reused for all money fields"
  - "D-13: Retrofit reaches existing TransactionCreate.amount and TransactionOut.amount (both changed from float)"
  - "api_key conftest fixture patches backend.auth._CONFIGURED_KEY directly (avoids import-time env ordering issue)"

metrics:
  duration_minutes: 4
  completed_date: "2026-06-21"
  tasks_completed: 1
  tasks_total: 1
  files_created: 2
  files_modified: 2
---

# Phase 1 Plan 03: MoneyDecimal Type and Decimal Serialization Tests Summary

**One-liner:** Pydantic v2 `MoneyDecimal = Annotated[Decimal, PlainSerializer(float, when_used='json')]` closes the float-in-transit leak; both Transaction schema `amount` fields retrofitted; decimal tests green.

## What Was Built

Plan 03 closes the serialization side of FND-03 by introducing a single shared annotated Decimal money type and establishing the shared test fixtures the rest of the phase relies on.

### `MoneyDecimal` type alias (`backend/schemas.py`)

```python
MoneyDecimal = Annotated[
    Decimal,
    PlainSerializer(lambda x: float(x), return_type=float, when_used="json"),
]
```

- Validates as `Decimal` on the Python side (preserving precision)
- Serializes as a JSON `float` (number), not a string, when `model_dump_json()` is called
- Addresses Pydantic v2 Pitfall 4: v2 intentionally serializes `Decimal` as strings by default

`TransactionCreate.amount` and `TransactionOut.amount` changed from `float` to `MoneyDecimal`.

### Shared test fixtures (`backend/tests/conftest.py`)

- `client` (session-scoped): `TestClient(backend.main.app)` — reused by Plan 02's `test_auth.py`
- `api_key` (function-scoped): patches `backend.auth._CONFIGURED_KEY` directly via `monkeypatch.setattr`, returns the key string. Avoids import-time env ordering issue (auth module reads key at import time).

### Decimal serialization tests (`backend/tests/test_decimal.py`)

5 tests covering:
1. `MoneyDecimal` produces `float` in `model_dump_json()` output (not `str`)
2. `MoneyDecimal` preserves `Decimal` on the Python side
3. `TransactionCreate` accepts `Decimal("-25000.00")` and round-trips as `Decimal`
4. `TransactionCreate` rejects non-numeric input
5. `TransactionOut` serializes `amount` as JSON number when read from ORM data

All 5 pass. Existing 21 tests in `test_router.py` and `test_tools.py` unaffected.

## TDD Gate Compliance

- RED commit `43d7885`: `test(01-03): add failing Decimal serialization tests and shared conftest (RED)` — confirmed failure: `ImportError: cannot import name 'MoneyDecimal'`
- GREEN commit `16e2ec9`: `feat(01-03): add MoneyDecimal type and retrofit Transaction schemas (GREEN)` — all 5 tests pass

## Commits

| Commit | Type | Description |
|--------|------|-------------|
| `43d7885` | test | RED: failing tests + conftest |
| `16e2ec9` | feat | GREEN: MoneyDecimal + schema retrofit |

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — `MoneyDecimal` is fully wired; both `amount` fields are live. No placeholder values.

## Threat Flags

None — no new network endpoints, auth paths, or schema trust boundaries introduced. This plan operates entirely within the existing Pydantic serialization layer.

## Self-Check: PASSED

- `backend/schemas.py` — exists, contains `MoneyDecimal`, `PlainSerializer`, two `amount: MoneyDecimal` fields
- `backend/tests/conftest.py` — exists, contains `TestClient`, `api_key` fixture
- `backend/tests/test_decimal.py` — exists, `5 passed` confirmed
- `backend/requirements.txt` — `alembic>=1.13.0`, `httpx>=0.27.0`, `pytest>=8.0.0` added
- Commits `43d7885` and `16e2ec9` confirmed in `git log`
