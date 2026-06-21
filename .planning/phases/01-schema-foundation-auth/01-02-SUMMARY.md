---
phase: 01-schema-foundation-auth
plan: 02
subsystem: auth
tags: [auth, api-key, fastapi, nextjs, proxy, security]
dependency_graph:
  requires: [01-01]
  provides: [FND-02, require_api_key, server-side-proxy]
  affects: [backend/main.py, backend/auth.py, ui/app/api/proxy, docker-compose.yml]
tech_stack:
  added: []
  patterns:
    - FastAPI APIKeyHeader with auto_error=False + hmac.compare_digest constant-time comparison
    - Next.js App Router catch-all route handler as server-side API proxy
    - Fail-closed env guard (RuntimeError on empty MONAI_API_KEY)
key_files:
  created:
    - backend/auth.py
    - backend/tests/test_auth.py
    - ui/app/api/[...proxy]/route.ts
  modified:
    - backend/main.py
    - ui/next.config.js
    - docker-compose.yml
decisions:
  - "D-05: Auth via per-route FastAPI dependency (dependencies=[Depends(require_api_key)]) — side-effect only, no handler signature change"
  - "D-06: Public surface = all GETs + POST /query; protected surface = POST /transactions + POST /import only"
  - "D-07: Key delivered to backend by Next.js server-side proxy (process.env.MONAI_API_KEY in route.ts) — never NEXT_PUBLIC_"
  - "D-08: Header MONAI_API_KEY, constant-time via hmac.compare_digest, single static key from env"
metrics:
  duration: 337s
  completed_date: "2026-06-21"
  tasks_completed: 3
  files_changed: 6
---

# Phase 01 Plan 02: API-Key Auth and Server-Side Proxy Summary

**One-liner:** Enforce MONAI_API_KEY write-gate via FastAPI `require_api_key` dependency with `hmac.compare_digest`, delivered browser-safe through a Next.js App Router catch-all server-side proxy route.

## What Was Built

### Task 1: require_api_key dependency + auth unit tests (TDD)

Created `backend/auth.py` implementing the `require_api_key` FastAPI dependency:
- `APIKeyHeader(name="MONAI_API_KEY", auto_error=False)` — missing header yields 401, not FastAPI's default 403
- `hmac.compare_digest` for constant-time comparison (mitigates T-01-05 timing attack)
- Fail-closed: raises `RuntimeError` when `_CONFIGURED_KEY` is empty (mitigates T-01-07)
- Returns `None` (side-effect only) for use in `dependencies=[]` decorator parameter

Created `backend/tests/test_auth.py` with 7 test cases:
- 401 on missing key for POST /transactions and POST /import
- 401 on wrong key for POST /transactions and POST /import
- Non-401 (422, body validation) on valid key + incomplete body — DB-safe (no live write)
- 200 for GET /accounts without key (public)
- Non-401 for POST /query without key (public, D-06)

TDD cycle: RED commit (tests fail — `backend.auth` absent) → GREEN commit (auth.py created, all 7 pass).

### Task 2: Gate write routes in main.py

Added `from backend.auth import require_api_key` import and `dependencies=[Depends(require_api_key)]` to exactly 2 route decorators:
- `@app.post("/transactions", ...)` — write route
- `@app.post("/import", ...)` — write route

`POST /query` and all GET routes have no auth dependency (D-06). Full suite: 55 tests passed.

### Task 3: Next.js server-side proxy + docker-compose wiring

Created `ui/app/api/[...proxy]/route.ts` — Next.js App Router catch-all route handler:
- Reads `MONAI_API` and `MONAI_API_KEY` from `process.env` (server-side only)
- Injects `MONAI_API_KEY` header via `headers.set("MONAI_API_KEY", API_KEY)` on every upstream request
- Forwards method, headers, body, and query string transparently
- Exports GET, POST, PUT, PATCH, DELETE for forward-compat

Removed the `async rewrites()` block from `ui/next.config.js` — the route handler now owns `/api/*`. Wired `MONAI_API_KEY: ${MONAI_API_KEY}` to both backend and frontend services in `docker-compose.yml` via host env / `.env` file (no hardcoded secret).

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 (RED) | 41729b0 | test(01-02): add failing auth tests for require_api_key dependency |
| 1 (GREEN) | 7374ea8 | feat(01-02): implement require_api_key dependency with constant-time comparison |
| 2 | ea4021e | feat(01-02): gate POST /transactions and POST /import with require_api_key |
| 3 | 77642e3 | feat(01-02): add server-side Next.js proxy route handler and docker-compose key wiring |

## Deviations from Plan

None - plan executed exactly as written.

The TDD flow naturally split into RED/GREEN as the test file was committed before `backend/auth.py` existed. Task 2 triggered all 4 "missing key" tests to go from 422 (routes ungated) to 401 (routes gated), which was the expected course of events across tasks.

## Known Stubs

None. All auth paths are wired and functional.

## Threat Surface Scan

No new network endpoints or auth paths introduced beyond those in the plan's threat model. The `/api/[...proxy]` route handler is the proxy surface already analyzed as T-01-06 (mitigated by server-side key injection).

| Flag | File | Description |
|------|------|-------------|
| — | — | No unplanned threat surface introduced |

## User Setup Required

Before running in production, set `MONAI_API_KEY` in the environment:

```bash
# Generate a strong key
python3 -c "import secrets; print(secrets.token_hex(32))"

# Add to your .env file or shell environment:
MONAI_API_KEY=<generated-value>

# docker compose up will pick it up from the host environment
docker compose up -d
```

The `require_api_key` dependency is fail-closed: if `MONAI_API_KEY` is unset when the server starts, all write requests will raise `RuntimeError` (500) rather than silently accepting writes.

## Self-Check: PASSED

- backend/auth.py: FOUND
- backend/tests/test_auth.py: FOUND
- ui/app/api/[...proxy]/route.ts: FOUND
- All 4 commits verified in git log
- 55 tests pass with `MONAI_API_KEY=test-secret-key`
EOF
