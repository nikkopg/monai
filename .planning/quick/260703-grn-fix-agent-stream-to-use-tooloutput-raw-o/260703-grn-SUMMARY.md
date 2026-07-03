---
phase: quick-260703-grn
plan: 01
subsystem: api
tags: [llama-index, agent-stream, sse, proposals, pytest]

# Dependency graph
requires:
  - phase: 02-agentic-loop-confirm-before-write
    provides: agent_stream() SSE generator, propose_* write-tool registry, ProposalCard frontend
provides:
  - Corrected ToolCallResult handling in agent_stream() so proposal_id/proposal_token
    reach the SSE answer event for every write-tool call
  - Regression test pinning the raw_output-first resolution behavior
affects: [02-agentic-loop-confirm-before-write, any future work touching backend/query.py agent_stream/agent]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "ToolOutput.raw_output-first resolution: prefer the untouched dict LlamaIndex
      attaches to ToolOutput.raw_output before falling back to json.loads(content),
      since .content is a Python-repr string (single-quoted keys), never valid JSON"

key-files:
  created: []
  modified:
    - backend/query.py
    - backend/tests/test_agent.py

key-decisions:
  - "Scoped the fix to agent_stream() only, per plan — did not touch the structurally
    similar json.loads(content) logic in the agent() sync wrapper (Task scope boundary;
    agent() does not extract/surface proposal_id/proposal_token today)"
  - "Verified the fix is load-bearing by temporarily reverting it and confirming the new
    regression test fails (proposal_id/proposal_token come back None), then restored it"

patterns-established:
  - "Test fixtures for ToolCallResult events now set both raw_output (dict) and content
    (str(dict), a non-JSON Python-repr string) to mirror real LlamaIndex behavior"

requirements-completed: [quick-260703-grn]

coverage:
  - id: D1
    description: "agent_stream()'s ToolCallResult branch uses tool_output.raw_output verbatim when it is a dict, falling back to json.loads(content)/{\"raw\": content} only when it is not"
    verification:
      - kind: unit
        ref: "backend/tests/test_agent.py#test_agent_stream_surfaces_proposal_fields"
        status: pass
    human_judgment: false
  - id: D2
    description: "proposal_token continues to never appear in the public/persisted trace (T-02-07 preserved)"
    verification:
      - kind: unit
        ref: "backend/tests/test_agent.py#test_agent_stream_surfaces_proposal_fields"
        status: pass
    human_judgment: false
  - id: D3
    description: "Pre-existing agent() sync-wrapper tests (CHAT-01/02/08) remain green after updating the shared tool-result fixture to mirror real LlamaIndex raw_output/content shape"
    verification:
      - kind: unit
        ref: "backend/tests/test_agent.py#test_multi_step_chain_returns_trace_and_answer, test_no_sql_emission_returns_refusal_not_sql, test_honest_refusal_enumerates_capabilities"
        status: pass
    human_judgment: false
  - id: D4
    description: "End-to-end proof that ProposalCard renders in the browser for a real write action (live Ollama + Postgres + Next.js UI)"
    verification: []
    human_judgment: true
    rationale: "No live Postgres/Ollama available in this sandbox — only the mocked agent workflow could be exercised. A human must confirm in a running deployment that the SSE proposal_id/proposal_token now reach the frontend and ProposalCard renders."

# Metrics
duration: 12min
completed: 2026-07-03
status: complete
---

# Quick Task 260703-grn: Fix agent_stream() to surface proposal fields Summary

**Fixed `agent_stream()`'s `ToolCallResult` branch to read `tool_output.raw_output` verbatim instead of always failing `json.loads(tool_output.content)`, so `proposal_id`/`proposal_token` finally reach the SSE `answer` event for every write-tool call.**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-07-03T13:21:00Z (approx)
- **Completed:** 2026-07-03T13:33:13Z
- **Tasks:** 2/2
- **Files modified:** 2

## Accomplishments
- Root-caused and fixed the always-failing `json.loads(event.tool_output.content)` call in `agent_stream()`'s `ToolCallResult` branch — `.content` is a Python-repr string (single-quoted keys), never valid JSON, so `result_dict` always collapsed to `{"raw": content}` and `proposal_id`/`proposal_token` were always `None` in the SSE `answer` event for every write action.
- Now prefers `event.tool_output.raw_output` (the untouched dict LlamaIndex's `FunctionTool.call()` sets) when it is a `dict`, falling back to the original `json.loads(content)` / `{"raw": content}` logic only when it is not.
- Added a regression test (`test_agent_stream_surfaces_proposal_fields`) that drives `agent_stream()` end-to-end (mocked workflow) and asserts the SSE `answer` payload carries the correct `proposal_id`/`proposal_token`, and that `proposal_token` never leaks into the public trace (T-02-07 preserved).
- Verified the regression test is load-bearing: temporarily reverted the Task 1 fix, confirmed the new test fails with `proposal_id`/`proposal_token` coming back `None`, then restored the fix and confirmed the test passes again.
- Updated the shared `_make_tool_result_event` test fixture to mirror real LlamaIndex shape (`raw_output` = dict, `content` = non-JSON `str(dict)`), and confirmed the three pre-existing `agent()` sync-wrapper tests (CHAT-01/02/08) still pass unchanged.

## Task Commits

Each task was committed atomically:

1. **Task 1: Prefer raw_output dict in the ToolCallResult branch of agent_stream** - `498cebc` (fix)
2. **Task 2: Add regression test proving proposal fields survive to the answer event** - `957a478` (test)

**Plan metadata:** committed separately by the orchestrator (docs commit not made by this executor, per constraints).

## Files Created/Modified
- `backend/query.py` - `agent_stream()`'s `ToolCallResult` branch now resolves `result_dict` from `tool_output.raw_output` first (dict-verbatim), falling back to `json.loads(content)`/`{"raw": content}` only when `raw_output` is not a dict. No other logic (trace building, `proposal_token` stripping, `_extract_proposal_id`/`_extract_proposal_token`, StopEvent payload) touched.
- `backend/tests/test_agent.py` - `_make_tool_result_event` fixture now sets `output.raw_output = result_dict` and `output.content = str(result_dict)` (non-JSON Python-repr, mirroring real LlamaIndex). Added `_fake_stream_events_propose_edit` helper and `test_agent_stream_surfaces_proposal_fields` regression test.

## Decisions Made
- Scoped the fix strictly to `agent_stream()` as specified in the plan; the sync `agent()` wrapper has a structurally similar `json.loads(content)` block (lines ~285-290) but does not extract or surface `proposal_id`/`proposal_token` today, so it was left untouched — out of scope for this quick task.
- Verified test validity by manually reverting the fix and confirming the regression test fails as expected (not just "passes trivially"), per the plan's manual-reasoning verification step.

## Deviations from Plan

None — plan executed exactly as written. Both tasks completed as specified; no Rule 1-4 auto-fixes were needed.

## Issues Encountered
- First attempt to run `pytest`/`py_compile` used a `cd /home/user/monai` prefix which (in this worktree-isolated sandbox) navigated to the shared main checkout instead of the worktree copy, causing a false "test not found" result. Re-ran all verification commands using the worktree's default working directory (no `cd`) and confirmed all 4 tests collect and pass correctly in the worktree. No code was affected — this was purely a verification-tooling correction.
- `backend/tests/test_auth.py::test_get_accounts_public_no_key` fails in this sandbox with `connection to server at "127.0.0.1", port 5434 failed: Connection refused` — this is a pre-existing live-Postgres dependency unrelated to this change (confirmed the failure is a DB connection error, not related to `backend/query.py` or `backend/tests/test_agent.py`). Noted here per sandbox constraints; not fixed (out of scope, no live Postgres available).

## User Setup Required

None - no external service configuration required. This is a backend logic fix; no new dependencies, environment variables, or infrastructure changes.

## Next Phase Readiness
- `backend/query.py::agent_stream()` now correctly surfaces `proposal_id`/`proposal_token` to the SSE consumer for every write-tool call — the backend half of the ProposalCard-not-rendering bug is fixed and covered by a regression test.
- **Live verification still needed** (deferred — no Postgres/Ollama in this sandbox): confirm in a running deployment (`docker compose up` or local dev stack) that a real write request (e.g. "edit transaction X") causes the frontend ProposalCard to actually render, now that `proposal_id`/`proposal_token` are non-null in the SSE `answer` event. This closes the loop on the gap discovered during Phase 2 Plan 03 Task 3 human verification.

---
*Phase: quick-260703-grn*
*Completed: 2026-07-03*

## Self-Check: PASSED

- FOUND: backend/query.py
- FOUND: backend/tests/test_agent.py
- FOUND: .planning/quick/260703-grn-fix-agent-stream-to-use-tooloutput-raw-o/260703-grn-SUMMARY.md
- FOUND commit: 498cebc (fix)
- FOUND commit: 957a478 (test)
