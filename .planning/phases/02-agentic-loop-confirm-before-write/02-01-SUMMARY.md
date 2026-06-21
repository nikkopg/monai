---
phase: 02-agentic-loop-confirm-before-write
plan: "01"
subsystem: backend/query
tags: [agent, llama-index, function-agent, tdd, chat]
dependency_graph:
  requires: []
  provides:
    - agent() sync wrapper (answer_text, tool_trace)
    - agent_stream() async SSE generator
    - ask() backward-compat shim
    - reset_engine() clears both singletons
    - pytest-asyncio auto mode + async_client fixture
  affects:
    - backend/main.py (POST /query now calls agent() via ask() shim)
    - Plans 02-02, 02-03 (build on agent_stream() and agent() surface)
tech_stack:
  added:
    - pyproject.toml with [tool.pytest.ini_options] asyncio_mode=auto
  patterns:
    - FunctionAgent + AgentWorkflow (llama-index-core 0.14.22) wrapping 9 read tools
    - FunctionTool.from_defaults(fn=) — docstring as tool description, annotations as schema
    - WorkflowHandler.stream_events() async iteration for SSE events
    - Lazy-singleton pattern extended to _llm + _agent_workflow
    - ThreadPoolExecutor bridge for sync agent() inside running event loop (pytest context)
    - TDD red/green cycle: test commit 86aef89 → impl commit ebcaae5
key_files:
  created:
    - pyproject.toml (pytest-asyncio config)
    - backend/tests/test_agent.py (3 behavior tests: CHAT-01/02/08)
  modified:
    - backend/query.py (FunctionAgent loop, agent/agent_stream/ask/reset_engine)
    - backend/tests/conftest.py (async_client fixture added)
decisions:
  - FunctionAgent chosen over ReActAgent — gemma4:31b-cloud confirmed tools capability
  - max_iterations=10, timeout=120.0 on AgentWorkflow (T-02-03 DoS mitigation)
  - agent() sync wrapper uses ThreadPoolExecutor when event loop already running (pytest compat)
  - _extract_json() kept for test_router.py backward-compatibility
  - ask() thin shim preserves POST /query handler contract without any main.py changes
metrics:
  duration: "5m 3s"
  completed: "2026-06-21"
  tasks: 2
  files: 4
---

# Phase 02 Plan 01: FunctionAgent Multi-Step Loop Summary

**One-liner:** LlamaIndex FunctionAgent wrapping 9 read tools with SSE streaming, TDD-driven, replacing single-shot router.

## What Was Built

Replaced the single-shot `route()`/`ask()` router in `backend/query.py` with a LlamaIndex `FunctionAgent` + `AgentWorkflow` that plans and chains all 9 existing read tools across multiple steps per turn.

Key deliverables:
- `agent(question)` — sync entry point returning `(answer_text, tool_trace)` tuple
- `agent_stream(question)` — async generator yielding SSE events (`step`, `tool_result`, `answer`, `[DONE]`)
- `ask(question)` — thin shim preserving the existing `POST /query` handler contract
- `reset_engine()` — now clears both `_llm` and `_agent_workflow` singletons
- `pyproject.toml` with `asyncio_mode = "auto"` enabling the async test infrastructure
- `async_client` fixture in `conftest.py` for future async endpoint tests
- `test_agent.py` with 3 behavior tests proving CHAT-01/02/08 paths

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Configure async test infra and write failing agent tests (RED) | 86aef89 | pyproject.toml, conftest.py, test_agent.py |
| 2 | Replace router with FunctionAgent multi-step loop (GREEN) | ebcaae5 | backend/query.py |

## Verification Results

Full suite: **36/36 tests pass**

```
backend/tests/test_agent.py::test_multi_step_chain_returns_trace_and_answer PASSED
backend/tests/test_agent.py::test_no_sql_emission_returns_refusal_not_sql PASSED
backend/tests/test_agent.py::test_honest_refusal_enumerates_capabilities PASSED
... (33 pre-existing tests) ALL PASSED
```

Acceptance criteria verified:
- `grep -c "FunctionAgent" backend/query.py` → 3 (≥1 required)
- `grep -c "ReActAgent" backend/query.py` → 0
- `grep -c "FunctionTool.from_defaults" backend/query.py` → 9 (≥1 required)
- `grep -v '^#' backend/query.py | grep -c "_agent_workflow = None"` → 2 (declaration + reset)
- `grep -c "max_iterations" backend/query.py` → 2
- `grep -c "run_sql\|SELECT \|text(" backend/query.py` → 0
- `grep -c "async def agent_stream" backend/query.py` → 1

## Deviations from Plan

### Auto-fixed Issues

None.

### Design decisions made during implementation

**1. ThreadPoolExecutor bridge in agent() for pytest-asyncio compatibility**
- **Found during:** Task 2 implementation
- **Issue:** pytest-asyncio runs tests in an async event loop. `asyncio.run()` raises `RuntimeError: This event loop is already running` when called from within a running loop. The `agent()` sync wrapper needed to drive an async coroutine in both sync and async contexts.
- **Fix:** Detect running event loop via `asyncio.get_running_loop()`; if present, submit `asyncio.run(_run())` to a `ThreadPoolExecutor` thread (which has no running loop). Clean and avoids `nest_asyncio`.
- **Files modified:** `backend/query.py` lines 225-238
- **Commit:** ebcaae5

**2. RuntimeWarning on test_post_query_public_no_key**
- **Found during:** Full suite run
- **Issue:** `BasicRuntime.run_workflow.<locals>.run_with_concurrency_limit` was never awaited — a LlamaIndex internal coroutine that isn't properly cleaned up when the exception path fires before the async loop starts (Ollama not available in CI).
- **Disposition:** All 36 tests pass; the warning is from LlamaIndex's internal handler lifecycle during the exception-exit path (real Ollama unavailable). Out of scope for this plan — tracked below.
- **Deferred:** See Known Issues.

## Known Issues

| Issue | File | Description | Severity |
|-------|------|-------------|----------|
| RuntimeWarning: coroutine never awaited | backend/query.py | LlamaIndex WorkflowHandler internal coroutine not cleaned up when agent() hits exception path before async loop start | Low — tests pass; only affects error path |

## Known Stubs

None — no hardcoded placeholders or TODO stubs introduced.

## Threat Surface Scan

No new network endpoints, auth paths, or schema changes introduced in this plan. The `agent_stream()` function is an async generator used internally; it is exposed to HTTP in plan 02-02 via `POST /query-stream`. The system prompt guardrails (T-02-01 no SQL, T-02-02 no fabrication, T-02-03 iteration cap) are implemented as specified in the threat model.

## TDD Gate Compliance

- RED commit: `86aef89` — `test(02-01): configure async test infra and add failing agent behavior tests (RED)`
- GREEN commit: `ebcaae5` — `feat(02-01): replace single-shot router with FunctionAgent multi-step loop (GREEN)`
- Both gates present in git log. No REFACTOR commit needed (no cleanup required post-GREEN).

## Self-Check: PASSED
