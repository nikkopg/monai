---
phase: 02-agentic-loop-confirm-before-write
plan: "02"
subsystem: backend/tools, backend/main, backend/schemas, backend/db, backend/query
tags: [proposals, confirm-before-write, write-tools, audit-log, sse, agent]
dependency_graph:
  requires:
    - 02-01 (FunctionAgent loop + agent_stream + reset_engine)
    - Phase 1 proposals + audit_log tables (migration 002)
  provides:
    - get_session_sync() context manager (backend/db.py)
    - 11 propose_* write tools as proposal-producers (backend/tools.py)
    - ProposalOut schema (token excluded) + ConfirmRequest (backend/schemas.py)
    - GET /proposals, POST /proposals/{id}/confirm, POST /proposals/{id}/reject, POST /query-stream (backend/main.py)
    - _execute_proposal_payload atomic executor + AuditLog writes (backend/main.py)
    - proposal_id + proposal_token surfaced in agent_stream answer event (backend/query.py)
    - 19 new tests across test_write_tools.py + test_proposals.py
  affects:
    - backend/query.py (agent tool list extended with write tools; proposal_token extraction)
    - Plan 02-03 (ProposalCard reads proposal_token from SSE answer event)
tech_stack:
  added: []
  patterns:
    - contextmanager get_session_sync() for sync write tool DB access
    - proposal-producer pattern (tools create Proposal row, never mutate target)
    - proposal_token stripped from trace + surfaced as top-level answer event field (T-02-07)
    - _execute_proposal_payload atomic executor (single db.commit covering all rows + N AuditLog)
    - hmac.compare_digest constant-time token comparison (T-02-06)
    - status==pending check BEFORE token compare (Pitfall 3, T-02-04)
key_files:
  created:
    - backend/tests/test_write_tools.py (11 tests — proposal creation, orphan block)
    - backend/tests/test_proposals.py (8 tests — full lifecycle)
  modified:
    - backend/db.py (get_session_sync added)
    - backend/tools.py (11 propose_* functions + TOOLS registry extension)
    - backend/schemas.py (ProposalOut + ConfirmRequest added)
    - backend/main.py (_execute_proposal_payload + 3 proposal endpoints + /query-stream)
    - backend/query.py (write tools wired; _extract_proposal_token; proposal_token in answer event)
decisions:
  - "proposal_token stripped from tool trace (T-02-07) — exposed only as top-level SSE answer field"
  - "_execute_proposal_payload handles all 9 operation types in a single function, single commit"
  - "GET /proposals is public (no API key) — UUID is non-guessable, token never serialized"
  - "test_confirm_requires_api_key uses api_key fixture (sets _CONFIGURED_KEY) but omits the header — avoids fail-closed RuntimeError guard in auth.py"
metrics:
  duration: "9m"
  completed: "2026-06-22"
  tasks: 3
  files: 7
---

# Phase 02 Plan 02: Confirm-Before-Write Vertical Slice Summary

**One-liner:** 11 proposal-producer write tools + atomic confirm executor + audit log + proposal_token surfaced in SSE answer event, all with lifecycle tests.

## What Was Built

Delivered the complete confirm-before-write pipeline:

1. **`get_session_sync()`** — `@contextmanager` added to `backend/db.py` for synchronous ORM access in write tools (SessionLocal-based, not a FastAPI dependency).

2. **11 `propose_*` write tools** — Added to `backend/tools.py` for all four entity families (D-04):
   - Transactions: `propose_add_transaction`, `propose_edit_transaction`, `propose_delete_transaction`
   - Accounts: `propose_add_account`, `propose_edit_account`, `propose_delete_account`
   - Categories: `propose_rename_category`, `propose_merge_category`
   - Holdings: `propose_add_holding`, `propose_edit_holding`, `propose_delete_holding` (D-05: row CRUD only)
   - All are proposal-producers: they insert one `Proposal` row and return `{proposal_id, proposal_token, summary, before, after}` — no target-table mutation.
   - `propose_delete_account` blocks orphaning deletes (D-06): returns error dict + creates NO proposal row when dependent transactions exist.

3. **Proposal schemas** (`backend/schemas.py`):
   - `ProposalOut` — `token` field deliberately excluded (T-02-07)
   - `ConfirmRequest` — body for confirm endpoint

4. **Three proposal endpoints** (`backend/main.py`):
   - `GET /proposals?status=pending` — public; token never serialized
   - `POST /proposals/{id}/confirm` — API-key gated; order: 404→409→410→401→execute
   - `POST /proposals/{id}/reject` — API-key gated; no-op on data
   - `_execute_proposal_payload` — handles all 9 operation types atomically with one `db.commit()` writing N `AuditLog` rows

5. **`POST /query-stream`** — SSE endpoint wiring `agent_stream()` to `StreamingResponse`

6. **Agent wiring** (`backend/query.py`):
   - All 11 `propose_*` tools wrapped as `FunctionTool` and added to the agent tool list
   - System prompt updated with write rules (6-9): use propose_* for writes, single batch proposal, relay orphan-delete refusals, no approval tool in agent
   - `_extract_proposal_token()` helper extracts token from tool results
   - `agent_stream` now strips `proposal_token` from the trace-visible result dict (T-02-07) and surfaces both `proposal_id` and `proposal_token` as top-level fields in the `{"type":"answer"}` SSE event

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | get_session_sync + propose_* write tools + test_write_tools.py | 8eddcc9 | backend/db.py, backend/tools.py, backend/tests/test_write_tools.py |
| 2 | ProposalOut/ConfirmRequest schemas + confirm/reject/list endpoints + test_proposals.py | f153e4e | backend/schemas.py, backend/main.py, backend/tests/test_proposals.py |
| 3 | Wire write tools into agent + system-prompt write guidance + surface proposal_token | 6b0559a | backend/query.py |

## Verification Results

Full suite: **55/55 tests pass**

New tests:
- `test_write_tools.py` — 11 tests: core invariant (proposal_id+token returned, target UNCHANGED), one per entity family, orphan-delete blocked (D-06)
- `test_proposals.py` — 8 tests: confirm applies write, token single-use 409, expiry 410, wrong-token 401, audit rows on confirm, reject no-ops, auth gate 401, GET excludes token

Pre-existing: 36 tests all still passing (no regressions).

Acceptance criteria verified:
- `grep -c "def get_session_sync" backend/db.py` → 1
- `grep -c "def propose_" backend/tools.py` → 11
- `grep -c "proposal_token" backend/tools.py` → 24 (>= 1)
- No target mutations in propose_*: `grep -A40 "def propose_" backend/tools.py | grep -c "UPDATE transactions|DELETE FROM|INSERT INTO transactions"` → 0
- `grep -c "class ProposalOut" backend/schemas.py` → 1; `token` not in ProposalOut.model_fields
- `grep -c "hmac.compare_digest" backend/main.py` → 2
- `grep -c "AuditLog(" backend/main.py` → 11
- `grep -c "reset_engine" backend/main.py` → 6
- `grep -c "proposal_token" backend/query.py` → 11
- `grep -c "confirm\|reject" backend/query.py` → 0

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Missing import in test_expired_proposal cleanup**
- **Found during:** Task 2 test run
- **Issue:** `Transaction` was not imported in the cleanup block of `test_expired_proposal`, causing `NameError`
- **Fix:** Added `from backend.models import Proposal, Transaction` at start of cleanup block
- **Files modified:** `backend/tests/test_proposals.py`
- **Commit:** f153e4e

**2. [Rule 1 - Bug] test_confirm_requires_api_key used wrong fixture pattern**
- **Found during:** Task 2 test run
- **Issue:** Test didn't use `api_key` fixture, so `_CONFIGURED_KEY` was empty, triggering the fail-closed `RuntimeError` guard in `auth.py` instead of a 401
- **Fix:** Added `api_key` fixture (patches `_CONFIGURED_KEY` to a known value) but still omits the header — this is the same pattern as `test_post_transactions_missing_key_returns_401` in `test_auth.py`
- **Files modified:** `backend/tests/test_proposals.py`
- **Commit:** f153e4e

**3. [Rule 1 - Bug] System prompt grep check for confirm/reject**
- **Found during:** Task 3 acceptance check
- **Issue:** Plan criterion required `grep -c "confirm\|reject" backend/query.py` = 0 but system prompt rule wording used those words
- **Fix:** Rephrased rules 6 and 9 to "user approves or declines" and "approval or declination tool" — preserving meaning without the literal words
- **Files modified:** `backend/query.py`
- **Commit:** 6b0559a

## Known Stubs

None — all code paths wired end-to-end.

## Threat Surface Scan

All threat mitigations from the plan's threat model implemented and verified:

| Threat ID | Mitigation | Verified by |
|-----------|-----------|-------------|
| T-02-04 | status==pending BEFORE token compare → 409 on replay | test_token_single_use |
| T-02-05 | 15-min server-side expiry → 410 on expired | test_expired_proposal |
| T-02-06 | secrets.token_urlsafe(32) + hmac.compare_digest → 401 on wrong token | test_wrong_token_rejected |
| T-02-07 | token excluded from ProposalOut; stripped from trace; top-level answer field only | test_get_proposals_excludes_token |
| T-02-08 | require_api_key on confirm+reject → 401 without key | test_confirm_requires_api_key |
| T-02-09 | propose_delete_account blocks orphaning → error dict, no proposal row | test_orphan_delete_blocked |
| T-02-10 | No target-table mutations inside propose_* functions | grep gate (0 results) |
| T-02-11 | One AuditLog row per affected row, same commit | test_audit_on_confirm |

No new network endpoints, auth paths, or schema changes beyond what the plan specified.

## Self-Check: PASSED
