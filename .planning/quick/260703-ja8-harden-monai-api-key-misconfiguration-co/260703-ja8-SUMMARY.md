---
phase: quick-260703-ja8
plan: 01
subsystem: auth
tags: [fastapi, docker-compose, auth, misconfiguration, fail-closed]

requires: []
provides:
  - docker-compose fails fast (aborts) when MONAI_API_KEY is unset or empty
  - require_api_key() raises HTTPException(503) JSON error instead of an unhandled RuntimeError/500 on empty key
  - test coverage for the empty-key 503 path
affects: [deployment, backend-auth]

tech-stack:
  added: []
  patterns:
    - "compose required-var interpolation (${VAR:?message}) used to fail fast on missing secrets"
    - "fail-closed auth guard raises HTTPException instead of a bare exception, so FastAPI serializes a JSON error"

key-files:
  created: []
  modified:
    - docker-compose.yml
    - backend/auth.py
    - backend/tests/test_auth.py

key-decisions:
  - "Used ${VAR:?message} (not ${VAR?message}) so the guard fires on BOTH unset AND empty-string values"
  - "Guard ordering preserved: empty-key check remains the first statement in require_api_key(), before hmac comparison, keeping the fail-closed property"

patterns-established:
  - "Server misconfiguration in a FastAPI dependency should raise HTTPException(503) with an actionable detail message, not a bare RuntimeError that surfaces as an opaque text/plain 500"

requirements-completed: [QUICK-260703-ja8]

coverage:
  - id: D1
    description: "docker compose up/config fails fast with a clear message when MONAI_API_KEY is unset or empty"
    requirement: "QUICK-260703-ja8"
    verification:
      - kind: other
        ref: "python3 -c \"import yaml; yaml.safe_load(open('docker-compose.yml'))\" + grep -c ':?MONAI_API_KEY must be set' docker-compose.yml (== 2)"
        status: pass
    human_judgment: true
    rationale: "docker CLI is unavailable in-sandbox, so `docker compose config` could not be executed to observe the actual abort. Verified via YAML-parse + grep that both MONAI_API_KEY entries use the ${VAR:?...} required-var form, which is documented Compose behavior, but a human with docker CLI access should confirm `docker compose up` actually aborts before first deployment."
  - id: D2
    description: "A write request against a server with empty MONAI_API_KEY returns a 503 JSON error with a helpful detail, not an opaque text/plain 500"
    requirement: "QUICK-260703-ja8"
    verification:
      - kind: unit
        ref: "backend/tests/test_auth.py#test_empty_configured_key_returns_503"
        status: pass
    human_judgment: false
  - id: D3
    description: "The auth guard stays fail-closed: the empty-key check runs FIRST, before any key comparison"
    requirement: "QUICK-260703-ja8"
    verification:
      - kind: unit
        ref: "backend/tests/test_auth.py -q (full suite, 8 passed, including all pre-existing 401/200/422 cases)"
        status: pass
    human_judgment: false

duration: 5min
completed: 2026-07-03
status: complete
---

# Quick Task 260703-ja8: Harden MONAI_API_KEY misconfiguration handling Summary

**docker-compose required-var interpolation plus a 503 JSON auth guard turn a silently-empty MONAI_API_KEY into a fast, actionable failure instead of an hour of live debugging.**

## Performance

- **Duration:** ~5 min
- **Completed:** 2026-07-03T13:56Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments
- `docker-compose.yml` backend and frontend services now use `${MONAI_API_KEY:?MONAI_API_KEY must be set - add it to .env}` so `docker compose up`/`config` aborts immediately (with a clear message) if the var is unset OR empty
- `backend/auth.py`'s `require_api_key()` now raises `HTTPException(status_code=503, detail=...)` for the empty-`_CONFIGURED_KEY` case instead of an unhandled `RuntimeError`, so FastAPI serializes a proper JSON 503 error instead of an opaque `text/plain` 500; the guard is still the first check in the function, preserving fail-closed behavior
- Added `test_empty_configured_key_returns_503` to `backend/tests/test_auth.py`, covering the new path; full suite (8 tests) passes

## Task Commits

Each task was committed atomically:

1. **Task 1: Make docker-compose fail fast on unset/empty MONAI_API_KEY** - `7399a16` (fix)
2. **Task 2: Replace RuntimeError guard with HTTPException(503) in require_api_key** - `fde99c5` (fix)
3. **Task 3: Add/adjust auth test for the empty-key 503 path** - `cb80d8c` (test)

## Files Created/Modified
- `docker-compose.yml` - both `MONAI_API_KEY` env entries (backend, frontend) switched from `${MONAI_API_KEY}` to the required-var form `${MONAI_API_KEY:?MONAI_API_KEY must be set - add it to .env}`
- `backend/auth.py` - `require_api_key()` empty-key branch now raises `HTTPException(status_code=503, ...)` instead of `RuntimeError`; module and function docstrings updated to match
- `backend/tests/test_auth.py` - added `test_empty_configured_key_returns_503`, updated the module docstring test-list comment block

## Decisions Made
- Used `:?` (not `?`) in the compose interpolation so the guard fires on both an unset var and an explicit empty string, matching the plan's requirement.
- Kept the empty-key guard as the very first statement in `require_api_key()`, ahead of the `hmac.compare_digest` call, so the fail-closed property (no silent open writes) is unchanged — only the exception type/shape changed.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. `docker compose config` could not be run in-sandbox (no docker CLI available), so Task 1 was verified via YAML-parse + grep per the plan's own guidance; this is documented as a human-judgment coverage item (D1) for a future human check with docker CLI access.

## User Setup Required

None - no external service configuration required. Note: any deployment that previously relied on an unset `MONAI_API_KEY` silently defaulting to empty will now need the var set in `.env` before `docker compose up` succeeds — this is the intended hardening, not a regression.

## Next Phase Readiness
- `backend/main.py`, the frontend, and the reverse proxy were untouched, per the plan's success criteria.
- No blockers for subsequent phases; this quick task closes an operational/security gap uncovered during live Phase 2 debugging (see STATE.md pending todos/blockers).

---
*Phase: quick-260703-ja8*
*Completed: 2026-07-03*

## Self-Check: PASSED

- FOUND: docker-compose.yml
- FOUND: backend/auth.py
- FOUND: backend/tests/test_auth.py
- FOUND: 7399a16 (Task 1 commit)
- FOUND: fde99c5 (Task 2 commit)
- FOUND: cb80d8c (Task 3 commit)
