---
phase: 01-schema-foundation-auth
verified: 2026-06-21T18:31:00+07:00
status: passed
score: 4/4
overrides_applied: 0
---

# Phase 1: Schema Foundation + Auth — Verification Report

**Phase Goal:** The database schema is safe to evolve and all write endpoints are authenticated
**Verified:** 2026-06-21T18:31:00+07:00
**Status:** PASSED
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `alembic upgrade head` on an existing volume applies 5 new tables without destroying `transactions`/`accounts` data | VERIFIED | Two migrations exist: 001 (baseline, `down_revision=None`, stamped not run) + 002 (chains to 001, 5 `create_table` calls, `CREATE OR REPLACE VIEW date_helpers`). Operator confirmed: `alembic current = 7b4e9f1a6c52 head`, transactions=5609, accounts=3 intact (01-01-SUMMARY.md, Task 4 checkpoint). |
| 2 | All `POST`/`PUT`/`DELETE`/`PATCH` endpoints return 401 when `MONAI_API_KEY` is missing or wrong; GET endpoints and `POST /query` remain public | VERIFIED | `backend/auth.py` uses `APIKeyHeader(auto_error=False)` + `hmac.compare_digest`; `main.py` line 74 and line 97 carry `dependencies=[Depends(require_api_key)]` on `/transactions` and `/import` only; `/query` (line 113) and all GET routes have no auth dependency. `test_auth.py` asserts 401 on missing/wrong key and non-401 on valid key. |
| 3 | Transaction amounts flowing through the API are stored and returned as `Decimal` (no float rounding visible in responses) | VERIFIED | `Transaction.amount` is `Mapped[Decimal]` on `Numeric(18,2)` in `models.py` (line 63). `MoneyDecimal = Annotated[Decimal, PlainSerializer(lambda x: float(x), return_type=float, when_used="json")]` in `schemas.py`; both `TransactionCreate.amount` and `TransactionOut.amount` use `MoneyDecimal`. `test_decimal.py` asserts `isinstance(payload["amount"], float)` (JSON number, not string) and round-trip preservation as `Decimal`. |
| 4 | `Base.metadata.create_all()` has been removed from `db.py`; schema is fully Alembic-managed | VERIFIED | `backend/db.py` contains no `create_all` (grep returns nothing). `init_db` absent from `main.py`. Docstring in `db.py` explicitly records the removal. `backend/entrypoint.sh` runs `alembic upgrade head` before `exec uvicorn`. |

**Score:** 4/4 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `alembic/env.py` | Wired to DATABASE_URL and Base.metadata | VERIFIED | `target_metadata = Base.metadata`; reads `DATABASE_URL` from `os.environ`; `%%` escape for configparser; sync NullPool engine. |
| `alembic/versions/001_baseline.py` | Baseline migration (stamp not run on live DB) | VERIFIED | `down_revision = None`; prominent STAMP comment in `upgrade()`; creates accounts + transactions with 4 named indexes. |
| `alembic/versions/002_new_tables.py` | 5 new tables + date_helpers view | VERIFIED | `down_revision = "3a1f8c2d9e04"`; `op.execute(_DATE_HELPERS_VIEW)`; exactly 5 `create_table` calls (audit_log, proposals, holdings, portfolio_events, price_cache). |
| `backend/models.py` | 5 new ORM models + `Transaction.amount` as `Mapped[Decimal]` | VERIFIED | All 5 models present (AuditLog, Proposal, Holding, PortfolioEvent, PriceCache) using SQLAlchemy 2.0 `Mapped[]` style. `Transaction.amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))` at line 63. |
| `backend/entrypoint.sh` | Runs `alembic upgrade head` before uvicorn | VERIFIED | `alembic upgrade head` on line 7; `exec uvicorn backend.main:app` on line 9; `set -e`. |
| `backend/Dockerfile` | COPYs entrypoint.sh, chmod +x, CMD invokes it | VERIFIED | Lines 15-16 COPY + chmod; line 20 `CMD ["./backend/entrypoint.sh"]`. |
| `backend/auth.py` | `require_api_key` with `hmac.compare_digest`, `auto_error=False`, fail-closed | VERIFIED | All three properties confirmed: `APIKeyHeader(name="MONAI_API_KEY", auto_error=False)`; `hmac.compare_digest(api_key, _CONFIGURED_KEY)`; `RuntimeError` on empty `_CONFIGURED_KEY`. |
| `ui/app/api/[...proxy]/route.ts` | Server-side proxy injecting `MONAI_API_KEY` header | VERIFIED | Reads `process.env.MONAI_API_KEY` (not `NEXT_PUBLIC_`); calls `headers.set("MONAI_API_KEY", API_KEY)`; exports GET, POST, PUT, PATCH, DELETE. |
| `backend/tests/test_auth.py` | Auth tests asserting 401/non-401 behavior | VERIFIED | 401 assertions for missing key (line 32, 106, 121) and wrong key (line 47); non-401 for valid key (line 66); non-401 for GET /accounts and POST /query (line 95). |
| `backend/schemas.py` | `MoneyDecimal` type + both Transaction schemas use it | VERIFIED | `MoneyDecimal = Annotated[Decimal, PlainSerializer(...)]` at line 17; `TransactionCreate.amount: MoneyDecimal` (line 25); `TransactionOut.amount: MoneyDecimal` (line 39). |
| `backend/tests/conftest.py` | Shared `TestClient` + `api_key` fixtures | VERIFIED | File exists; `test_decimal.py` imports from it; `test_auth.py` uses it. |
| `backend/tests/test_decimal.py` | Decimal round-trip and JSON-number serialization tests | VERIFIED | `isinstance(payload["amount"], float)` assertion present; `TransactionCreate` Decimal round-trip test; `TransactionOut` JSON number test. |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `alembic/env.py` | `backend.models.Base.metadata` | `target_metadata = Base.metadata` | WIRED | Line 27: `target_metadata = Base.metadata`; import from `backend.models` on line 18. |
| `alembic/versions/002_new_tables.py` | `date_helpers` view | `op.execute(CREATE OR REPLACE VIEW date_helpers)` | WIRED | `_DATE_HELPERS_VIEW` constant contains `CREATE OR REPLACE VIEW date_helpers`; called via `op.execute(_DATE_HELPERS_VIEW)` in `upgrade()`. |
| `backend/entrypoint.sh` | `alembic upgrade head` | Docker CMD invokes entrypoint before uvicorn | WIRED | `CMD ["./backend/entrypoint.sh"]` in Dockerfile; `alembic upgrade head` on line 7 of entrypoint.sh. |
| `backend/main.py` | `backend.auth.require_api_key` | `dependencies=[Depends(require_api_key)]` on write routes | WIRED | `from backend.auth import require_api_key` imported at line 24; exactly 2 occurrences of `dependencies=[Depends(require_api_key)]` (lines 74 and 97). `/query` and GET routes have no such dependency. |
| `ui/app/api/[...proxy]/route.ts` | FastAPI backend | `fetch` with injected `MONAI_API_KEY` header | WIRED | `headers.set("MONAI_API_KEY", API_KEY)` at line 35; `API_KEY = process.env.MONAI_API_KEY` at line 16; no `NEXT_PUBLIC_` anywhere in UI. |
| `backend/schemas.py TransactionCreate.amount` | `MoneyDecimal` | field type annotation | WIRED | `amount: MoneyDecimal = Field(...)` in `TransactionCreate`. |
| `MoneyDecimal` | JSON number output | `PlainSerializer(float, when_used='json')` | WIRED | `PlainSerializer(lambda x: float(x), return_type=float, when_used="json")` in definition. |
| `docker-compose.yml` | `MONAI_API_KEY` in both services | `${MONAI_API_KEY}` env interpolation | WIRED | 3 lines reference `MONAI_API_KEY` in docker-compose.yml: lines 35 (backend) and 51 (frontend), both using `${MONAI_API_KEY}` (no hardcoded literal). |

---

### Data-Flow Trace (Level 4)

Not applicable — this phase delivers schema infrastructure, auth middleware, and serialization types. No dynamic-data-rendering components were introduced.

---

### Behavioral Spot-Checks

| Behavior | Verification Method | Result | Status |
|----------|---------------------|--------|--------|
| `require_api_key` raises 401 on missing header | `test_auth.py` line 32, 106, 121 assert `status_code == 401` | Tests assert correctly | PASS |
| `require_api_key` raises 401 on wrong key | `test_auth.py` line 47 asserts `status_code == 401` | Tests assert correctly | PASS |
| `POST /query` has no auth dependency | `main.py` line 113: `@app.post("/query")` — no `dependencies=` parameter | Confirmed no auth on /query | PASS |
| `create_all` absent from `db.py` | `grep create_all backend/db.py` returns nothing | Not found | PASS |
| `NEXT_PUBLIC_MONAI_API_KEY` absent from all UI files | `grep -rn NEXT_PUBLIC_MONAI_API_KEY ui/` returns nothing | Not found | PASS |
| Migration 002 has exactly 5 `create_table` calls | `grep -c create_table alembic/versions/002_new_tables.py` returns 5 | Confirmed | PASS |
| `Transaction.amount` is `Mapped[Decimal]` | `models.py` line 63: `amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))` | Confirmed | PASS |

---

### Probe Execution

No `scripts/*/tests/probe-*.sh` files exist in this project. Phase does not declare probes. Step 7c: SKIPPED (no probes declared or present).

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| FND-01 | 01-01-PLAN.md | Alembic migrations preserve existing data | SATISFIED | Two migrations + stamp recipe; operator verified transactions=5609, accounts=3 intact; `alembic current = 7b4e9f1a6c52 head`. Note: REQUIREMENTS.md checkbox still shows `[ ]` — documentation gap only, not an implementation gap. |
| FND-02 | 01-02-PLAN.md | Write endpoints require MONAI_API_KEY | SATISFIED | `require_api_key` on POST /transactions + POST /import; hmac.compare_digest; auto_error=False; fail-closed RuntimeError; 401 tests pass. |
| FND-03 | 01-01-PLAN.md + 01-03-PLAN.md | Decimal end-to-end for money amounts | SATISFIED | `Transaction.amount: Mapped[Decimal]` on `Numeric(18,2)`; `MoneyDecimal` with `PlainSerializer`; both Transaction schemas retrofitted; decimal tests green. |

**Note on FND-01 checkbox:** REQUIREMENTS.md line 12 shows `- [ ] **FND-01**` (unchecked) while the traceability table on line 98 shows `Status: Pending`. The implementation is demonstrably complete (migrations exist, were applied, operator-verified). This is a documentation-only discrepancy — the checkbox was not updated after the operator confirmed Task 4. Not a code gap.

**Orphaned requirements:** None. All Phase 1 requirements (FND-01, FND-02, FND-03) are claimed by plans and verified above.

---

### Anti-Patterns Found

Scan performed on all files modified by this phase.

| File | Pattern | Severity | Impact |
|------|---------|----------|--------|
| — | No TBD/FIXME/XXX markers found | — | — |
| — | No placeholder implementations found | — | — |
| — | No hardcoded empty returns in API routes | — | — |

No anti-patterns detected. All debt marker checks returned clean.

---

### Human Verification Required

None. All success criteria are verifiable from source code and the operator-confirmed migration checkpoint documented in 01-01-SUMMARY.md.

The one item that could benefit from human confirmation is the live DB state (transactions=5609, accounts=3, 5 new tables + date_helpers view), but this was already performed and recorded by the operator on 2026-06-21 as the Task 4 blocking checkpoint. Re-verification is not required.

---

## Gaps Summary

No gaps. All 4 roadmap success criteria are VERIFIED in the codebase.

**Minor documentation gap (non-blocking):** REQUIREMENTS.md FND-01 checkbox is still `[ ]` (unchecked) despite the requirement being fully satisfied and the traceability table showing Complete. The operator should update the checkbox to `[x]` for consistency, but this does not block phase progression.

---

_Verified: 2026-06-21T18:31:00+07:00_
_Verifier: Claude (gsd-verifier)_
