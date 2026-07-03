---
phase: quick-260703-grn
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/query.py
  - backend/tests/test_agent.py
autonomous: true
requirements:
  - quick-260703-grn
must_haves:
  truths:
    - "For any write-tool call, the SSE answer event carries a non-null proposal_id and proposal_token."
    - "proposal_token never appears inside the public trace results (T-02-07 preserved)."
    - "A regression test fails against the old json.loads(content) logic and passes after the fix."
  artifacts:
    - backend/query.py
    - backend/tests/test_agent.py
  key_links:
    - "event.tool_output.raw_output (dict) -> result_dict -> _extract_proposal_id / _extract_proposal_token -> SSE answer payload"
---

<objective>
Fix `agent_stream()` in `backend/query.py` so proposal fields reach the frontend.

The `ToolCallResult` branch currently reads `event.tool_output.content` (a Python-repr
string of the tool's dict return) and calls `json.loads()` on it, which ALWAYS raises,
producing `result_dict = {"raw": "<string>"}` for every tool call. As a result
`_extract_proposal_id`/`_extract_proposal_token` never find anything, the SSE `answer`
event's `proposal_id`/`proposal_token` are always null, and the frontend ProposalCard
never renders for any write action (the backend proposal row is created correctly).

Root cause is confirmed (see planning context) — do not re-investigate. LlamaIndex's
`FunctionTool.call()` sets `ToolOutput(raw_output=<actual dict returned by the tool fn>)`,
so `event.tool_output.raw_output` IS the untouched Python dict.

Purpose: proposal_id/proposal_token actually reach the SSE consumer so ProposalCard renders.
Output: corrected `ToolCallResult` handling + a regression test that pins the behavior.
</objective>

<execution_context>
@/home/user/monai/.claude/gsd-core/workflows/execute-plan.md
@/home/user/monai/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@backend/query.py
@backend/tests/test_agent.py
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Prefer raw_output dict in the ToolCallResult branch of agent_stream</name>
  <files>backend/query.py</files>
  <behavior>
    - Given a ToolCallResult whose tool_output.raw_output is a dict containing
      proposal_id and proposal_token, result_dict equals that dict verbatim (no json.loads round-trip).
    - Given a ToolCallResult whose raw_output is NOT a dict, the existing fallback runs:
      json.loads(content) on success, else {"raw": content}.
    - proposal_token is still stripped from the trace-visible result (unchanged T-02-07 behavior).
  </behavior>
  <action>
    In the `elif isinstance(event, ToolCallResult):` branch (currently ~lines 194-199),
    replace the unconditional `content = event.tool_output.content` +
    `json.loads(content)` logic with a raw_output-first resolution:

    1. Read `raw_output = getattr(event.tool_output, "raw_output", None)`.
    2. If `isinstance(raw_output, dict)`, set `result_dict = raw_output` directly and
       skip the json.loads round-trip entirely.
    3. Otherwise (raw_output is not a dict — defensive; none of backend/tools.py's
       functions currently return non-dict, but do not assume that invariant holds
       elsewhere), fall back to the EXISTING behavior: read
       `content = event.tool_output.content`, attempt `json.loads(content)`, and on any
       exception use `{"raw": content}`.

    Do NOT touch `_extract_proposal_id`/`_extract_proposal_token` — they are correct once
    handed a real dict. Do NOT change the downstream trace-building, the proposal_token
    stripping (`trace_result`), the tool_trace append shape, or the StopEvent payload
    construction. Keep the branch's output identical for the non-dict fallback path so
    the existing mocked tests remain green.
  </action>
  <verify>
    <automated>python -m py_compile backend/query.py</automated>
  </verify>
  <done>When raw_output is a dict it is used verbatim as result_dict; the json.loads(content)/{"raw": content} fallback runs only when raw_output is not a dict; no other logic in agent_stream changed.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Add regression test proving proposal fields survive to the answer event</name>
  <files>backend/tests/test_agent.py</files>
  <behavior>
    - A ToolCallResult event whose tool_output.raw_output is a dict with proposal_id and
      proposal_token, and whose tool_output.content is a NON-JSON Python-repr string
      (mirroring real LlamaIndex), drives agent_stream.
    - The emitted SSE "answer" event carries the correct proposal_id and proposal_token
      (would be null under the old json.loads-only logic — this is the regression guard).
    - proposal_token does NOT appear in any public trace entry's result.
  </behavior>
  <action>
    Extend `backend/tests/test_agent.py` following existing conventions (MagicMock-based
    fake events, monkeypatch of `backend.query._agent_workflow`, no real Ollama/DB).

    1. Update the shared `_make_tool_result_event` helper so it mirrors real LlamaIndex:
       set `output.raw_output = result_dict` and set `output.content` to a NON-JSON
       Python-repr string (e.g. `str(result_dict)`, which yields single-quoted keys so
       `json.loads` on it would raise). This makes the existing tests exercise the new
       raw_output path realistically; they must still pass (they only assert answer/trace
       shape, not parsed content values). Verify `test_multi_step_chain_returns_trace_and_answer`,
       `test_no_sql_emission_returns_refusal_not_sql`, and `test_honest_refusal_enumerates_capabilities`
       still pass after this change.

    2. Add a new async-driven regression test (e.g. `test_agent_stream_surfaces_proposal_fields`).
       Build a fake stream: an AgentInput, one ToolCallResult for a write tool (e.g.
       `propose_edit_transaction`) whose raw_output dict includes both `proposal_id` and
       `proposal_token` (plus a couple of ordinary keys), then a StopEvent. Monkeypatch
       `_agent_workflow` with a mock whose `run(...)` returns a handler whose
       `stream_events()` returns that async generator.

    3. Drive `backend.query.agent_stream(question)` (an async generator) and collect the
       emitted SSE lines — use `asyncio.run()` around a small inline async collector, or
       pytest-asyncio if the file's config already supports it (follow whatever the file
       currently uses; the existing tests are sync + monkeypatch, so an `asyncio.run()`
       collector inside a sync test is the lowest-friction choice). Parse the line whose
       decoded JSON has `type == "answer"`.

    4. Assert: `payload["proposal_id"]` equals the injected id, `payload["proposal_token"]`
       equals the injected token, and NO entry in `payload["trace"]` has a `result`
       containing the key `proposal_token`.
  </action>
  <verify>
    <automated>cd /home/user/monai && python -m pytest backend/tests/test_agent.py -x -q</automated>
  </verify>
  <done>New regression test passes and fails if Task 1's fix is reverted; the three pre-existing agent tests still pass. If llama_index or pytest is unavailable in this sandbox, note the skip in the SUMMARY rather than marking the test failed.</done>
</task>

</tasks>

<verification>
- `python -m py_compile backend/query.py` succeeds.
- `python -m pytest backend/tests/test_agent.py -x -q` passes (all four tests), OR is noted
  as un-runnable in this sandbox if llama_index/pytest is not installed (no Postgres/Ollama
  is required — the agent workflow is fully mocked).
- Manual reasoning check: reverting the Task 1 change makes the new test fail (proposal_id/
  proposal_token come back null).
</verification>

<success_criteria>
- `agent_stream()` uses `event.tool_output.raw_output` verbatim when it is a dict, and only
  falls back to `json.loads(content)`/`{"raw": content}` when it is not.
- `_extract_proposal_id`/`_extract_proposal_token`, backend/tools.py, and the frontend are untouched.
- A regression test asserts proposal_id + proposal_token reach the SSE answer event and that
  proposal_token stays out of the public trace.
</success_criteria>

<output>
Create `.planning/quick/260703-grn-fix-agent-stream-to-use-tooloutput-raw-o/260703-grn-SUMMARY.md` when done.
</output>
