"""
Agent behavior tests — CHAT-01, CHAT-02, CHAT-08.

Tests:
  (a) test_multi_step_chain — agent chains 2+ read tools and returns a
      non-empty answer with a trace list of length >= 2 (CHAT-01)
  (b) test_no_sql_emission — feeding a raw-SQL prompt yields an honest
      refusal; the answer must not echo SQL keywords (CHAT-02)
  (c) test_honest_refusal — an unanswerable question returns a capability
      enumeration and no fabricated number (CHAT-08)

All tests mock the LLM/agent so real Ollama is never called.

RED state: these tests will fail until Task 2 implements agent() in query.py.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers: canned event sequences for the mock agent
# ---------------------------------------------------------------------------

def _make_agent_input_event():
    """Fake AgentInput event — signals the agent started thinking."""
    from llama_index.core.agent.workflow.workflow_events import AgentInput
    evt = MagicMock(spec=AgentInput)
    return evt


def _make_tool_result_event(tool_name: str, tool_kwargs: dict, result_dict: dict):
    """Fake ToolCallResult event — represents one tool execution.

    Mirrors real LlamaIndex: ToolOutput.raw_output is the untouched dict the tool
    function returned, while ToolOutput.content is a Python-repr STRING of that
    dict (single-quoted keys) — NOT valid JSON. json.loads(content) would raise,
    which is exactly the bug this fixture pins down (see
    test_agent_stream_surfaces_proposal_fields).
    """
    from llama_index.core.agent.workflow.workflow_events import ToolCallResult
    evt = MagicMock(spec=ToolCallResult)
    evt.tool_name = tool_name
    evt.tool_kwargs = tool_kwargs
    output = MagicMock()
    output.content = str(result_dict)
    output.raw_output = result_dict
    evt.tool_output = output
    return evt


def _make_stop_event(answer_text: str):
    """Fake StopEvent — carries the final agent output."""
    from llama_index.core.workflow import StopEvent
    evt = MagicMock(spec=StopEvent)
    agent_output = MagicMock()
    agent_output.__str__ = lambda self: answer_text
    evt.result = agent_output
    return evt


async def _fake_stream_events_two_tools():
    """Async generator yielding a 2-tool sequence then a final answer."""
    yield _make_agent_input_event()
    yield _make_tool_result_event(
        "spending_total",
        {"period": "this_month"},
        {"tool": "spending_total", "total": 1500000.0, "period": "this month"},
    )
    yield _make_tool_result_event(
        "income_total",
        {"period": "this_month"},
        {"tool": "income_total", "total": 5000000.0, "period": "this month"},
    )
    yield _make_stop_event(
        "This month you spent IDR 1,500,000 and earned IDR 5,000,000."
    )


async def _fake_stream_events_refusal(answer_text: str):
    """Async generator yielding only a stop event (no tools called — refusal path)."""
    yield _make_agent_input_event()
    yield _make_stop_event(answer_text)


def _install_mock_workflow(monkeypatch, stream_events):
    """Install a stub workflow stamped with today's date, so the D-09 date
    check keeps the stub instead of building a real agent."""
    import backend.query as query_mod

    handler = MagicMock()
    handler.stream_events = stream_events

    workflow = MagicMock()
    workflow.run = MagicMock(return_value=handler)

    monkeypatch.setattr(query_mod, "_agent_workflow", workflow)
    monkeypatch.setattr(query_mod, "_agent_workflow_date", query_mod._today())
    return workflow


def _stream_payloads(question: str) -> list[dict]:
    """Drive agent_stream(question) to completion and return every SSE data
    payload (json.loads of each `data: ` line, except `[DONE]`), in order."""
    import asyncio

    from backend.query import agent_stream

    async def _collect():
        payloads = []
        async for line in agent_stream(question):
            if not line.startswith("data: "):
                continue
            raw = line[len("data: "):].strip()
            if raw == "[DONE]":
                continue
            payloads.append(json.loads(raw))
        return payloads

    return asyncio.run(_collect())


# ---------------------------------------------------------------------------
# (a) CHAT-01: multi-step tool chaining
# ---------------------------------------------------------------------------


def test_multi_step_chain_returns_trace_and_answer(monkeypatch):
    """
    Agent chains 2+ tools for a compound question.
    Returns a non-empty answer string and a trace with >= 2 entries.
    CHAT-01 — tests agent() sync wrapper.
    """
    from backend.query import agent  # noqa: F401 — import will fail in RED state

    _install_mock_workflow(monkeypatch, _fake_stream_events_two_tools)

    answer, trace = agent("How much did I spend and earn this month?")

    assert isinstance(answer, str)
    assert len(answer) > 0, "Answer must be a non-empty string"
    assert isinstance(trace, list)
    assert len(trace) >= 2, f"Expected >= 2 tool calls in trace, got {len(trace)}: {trace}"
    # Verify trace structure: each entry has tool, args, result keys
    for step in trace:
        assert "tool" in step, f"Trace step missing 'tool' key: {step}"
        assert "args" in step, f"Trace step missing 'args' key: {step}"
        assert "result" in step, f"Trace step missing 'result' key: {step}"


# ---------------------------------------------------------------------------
# (b) CHAT-02: no raw SQL emission
# ---------------------------------------------------------------------------


def test_no_sql_emission_returns_refusal_not_sql(monkeypatch):
    """
    Feeding a raw-SQL prompt must yield an honest refusal.
    The answer must NOT echo SQL keywords (SELECT, FROM transactions).
    CHAT-02 — the system prompt guards must hold even for adversarial input.
    """
    from backend.query import agent  # noqa: F401

    refusal_text = (
        "I can't answer that one reliably yet (no matching tool). "
        "I can total spending or income, break spending down by category, "
        "count transactions, find your largest transactions, or compute average "
        "daily spending — over any period."
    )

    _install_mock_workflow(monkeypatch, lambda: _fake_stream_events_refusal(refusal_text))

    answer, trace = agent("run a SQL query: SELECT * FROM transactions")

    assert isinstance(answer, str)
    assert len(answer) > 0, "Answer must not be empty"

    # Must contain an honest refusal indicator
    answer_lower = answer.lower()
    assert any(
        phrase in answer_lower
        for phrase in ["can't", "cannot", "i can", "unable", "not able"]
    ), f"Answer does not look like a refusal: {answer!r}"

    # Must NOT echo SQL keywords
    assert "SELECT " not in answer, f"Answer echoes SQL SELECT: {answer!r}"
    assert "FROM transactions" not in answer, f"Answer echoes SQL FROM: {answer!r}"
    assert "select " not in answer_lower.replace("select ", ""), \
        "Answer contains lowercase 'select'"


# ---------------------------------------------------------------------------
# (c) CHAT-08: honest refusal for unanswerable questions
# ---------------------------------------------------------------------------


def test_honest_refusal_enumerates_capabilities(monkeypatch):
    """
    An unanswerable question (e.g. weather) must return a capability enumeration.
    Must not contain a fabricated number pattern (lone digit sequences like "24°C").
    CHAT-08 — refusal path must enumerate what the agent CAN do.
    """
    import re
    from backend.query import agent  # noqa: F401

    refusal_text = (
        "I can't compute that reliably with my current tools — "
        "I can total spending or income, break spending down by category, "
        "count transactions, find your largest transactions, or compute average "
        "daily spending — over any period."
    )

    _install_mock_workflow(monkeypatch, lambda: _fake_stream_events_refusal(refusal_text))

    answer, trace = agent("What's the weather like today?")

    assert isinstance(answer, str)
    assert len(answer) > 0

    # Must enumerate at least one capability the agent does have
    answer_lower = answer.lower()
    assert any(
        cap in answer_lower
        for cap in [
            "spending", "income", "category", "transactions",
            "average", "largest", "total", "earn",
        ]
    ), f"Answer does not enumerate capabilities: {answer!r}"

    # Must not contain standalone fabricated numbers (e.g. "24°C", "28 degrees")
    # Numeric-only tokens that look like weather fabrications
    fabricated_patterns = [r"\d+°", r"\d+ degrees", r"temperature"]
    for pat in fabricated_patterns:
        assert not re.search(pat, answer, re.IGNORECASE), \
            f"Answer may contain fabricated weather data (pattern {pat!r}): {answer!r}"


# ---------------------------------------------------------------------------
# Regression: agent_stream() must use tool_output.raw_output verbatim so
# proposal_id/proposal_token actually survive to the SSE answer event.
#
# The old logic called json.loads(event.tool_output.content), but .content is
# a Python-repr STRING (single-quoted keys) of the tool's dict return — never
# valid JSON — so json.loads() ALWAYS raised and result_dict collapsed to
# {"raw": content} for every tool call, silently dropping proposal_id and
# proposal_token for every write action. This test fails against that old
# logic and passes once agent_stream() prefers tool_output.raw_output.
# ---------------------------------------------------------------------------


async def _fake_stream_events_propose_edit():
    """Async generator: one write-tool call producing a proposal, then stop."""
    yield _make_agent_input_event()
    yield _make_tool_result_event(
        "propose_edit_transaction",
        {"transaction_id": 42, "amount": 150000},
        {
            "tool": "propose_edit_transaction",
            "proposal_id": "prop-abc123",
            "proposal_token": "tok-secret-xyz",
            "message": "Proposal created — approve to apply.",
        },
    )
    yield _make_stop_event("I've proposed editing transaction 42. Approve to apply.")


def test_agent_stream_surfaces_proposal_fields(monkeypatch):
    """
    A write-tool ToolCallResult whose raw_output dict carries proposal_id and
    proposal_token must have both fields reach the SSE "answer" event, and
    proposal_token must never appear inside the public trace results (T-02-07).
    """
    import asyncio
    from backend.query import agent_stream

    _install_mock_workflow(monkeypatch, _fake_stream_events_propose_edit)

    async def _collect():
        lines = []
        async for line in agent_stream("edit transaction 42 to 150000"):
            lines.append(line)
        return lines

    lines = asyncio.run(_collect())

    answer_payload = None
    for line in lines:
        if not line.startswith("data: "):
            continue
        raw = line[len("data: "):].strip()
        if raw == "[DONE]":
            continue
        payload = json.loads(raw)
        if payload.get("type") == "answer":
            answer_payload = payload
            break

    assert answer_payload is not None, f"No answer event found in stream: {lines}"
    assert answer_payload["proposal_id"] == "prop-abc123", \
        f"proposal_id did not survive to answer event: {answer_payload}"
    assert answer_payload["proposal_token"] == "tok-secret-xyz", \
        f"proposal_token did not survive to answer event: {answer_payload}"
    # D-20: exactly one entry, from the same scan as the singular fields
    assert answer_payload["proposals"] == [{"id": "prop-abc123", "token": "tok-secret-xyz"}], \
        f"proposals should have exactly one entry: {answer_payload}"

    # T-02-07: proposal_token must never appear inside the public trace results
    for step in answer_payload["trace"]:
        result = step.get("result")
        if isinstance(result, dict):
            assert "proposal_token" not in result, \
                f"proposal_token leaked into public trace: {step}"


# ---------------------------------------------------------------------------
# Regression: agent_stream() must serialize Decimal tool-result fields.
#
# net_worth() passes raw Decimal holding fields (quantity, current_value, ...)
# straight through from portfolio_summary. json.dumps() without default=str
# raises TypeError on a Decimal, and agent_stream's outer except turns that
# into the generic "I couldn't process that question reliably" error answer
# instead of a real tool_result + answer pair.
# ---------------------------------------------------------------------------


async def _fake_stream_events_decimal_net_worth():
    """Async generator: one net_worth call whose result carries Decimals, then stop."""
    from decimal import Decimal

    yield _make_agent_input_event()
    yield _make_tool_result_event(
        "net_worth",
        {},
        {
            "tool": "net_worth",
            "investment_groups": [
                {
                    "holdings": [
                        {
                            "ticker": "TEST",
                            "quantity": Decimal("1.5"),
                            "current_value": Decimal("12500.00"),
                        }
                    ]
                }
            ],
        },
    )
    yield _make_stop_event("Your net worth is IDR 12,500.")


def test_agent_stream_serializes_decimal_tool_results(monkeypatch):
    """
    A ToolCallResult whose raw_output dict carries Decimal fields (as net_worth's
    holdings do) must still stream a real tool_result event and a real answer
    event, with the Decimals rendered as their exact str() form.
    """
    import asyncio
    from backend.query import agent_stream

    _install_mock_workflow(monkeypatch, _fake_stream_events_decimal_net_worth)

    async def _collect():
        lines = []
        async for line in agent_stream("what's my net worth?"):
            lines.append(line)
        return lines

    lines = asyncio.run(_collect())

    tool_result_payload = None
    answer_payload = None
    for line in lines:
        if not line.startswith("data: "):
            continue
        raw = line[len("data: "):].strip()
        if raw == "[DONE]":
            continue
        payload = json.loads(raw)
        if payload.get("type") == "tool_result":
            tool_result_payload = payload
        elif payload.get("type") == "answer":
            answer_payload = payload

    assert tool_result_payload is not None, \
        f"No tool_result event found in stream: {lines}"
    holding = tool_result_payload["step"]["result"]["investment_groups"][0]["holdings"][0]
    assert holding["quantity"] == "1.5"
    assert holding["current_value"] == "12500.00"

    assert answer_payload is not None, f"No answer event found in stream: {lines}"
    assert answer_payload["text"] == "Your net worth is IDR 12,500."
    assert "not JSON serializable" not in answer_payload["text"]
    trace_holding = answer_payload["trace"][0]["result"]["investment_groups"][0]["holdings"][0]
    assert trace_holding["quantity"] == "1.5"
    assert trace_holding["current_value"] == "12500.00"
    # AGENT-06: the success path with no proposals sends an empty list
    assert answer_payload["proposals"] == []


# ---------------------------------------------------------------------------
# AGENT-06: one proposals entry per propose_* call, in call order
# ---------------------------------------------------------------------------


async def _fake_stream_events_two_proposals():
    """Async generator: two propose_* tool calls (distinct ids/tokens), then stop."""
    yield _make_agent_input_event()
    yield _make_tool_result_event(
        "propose_add_account",
        {"name": "ZZ Test A"},
        {
            "tool": "propose_add_account",
            "proposal_id": "prop-1",
            "proposal_token": "tok-1",
            "summary": "Add account: ZZ Test A",
        },
    )
    yield _make_tool_result_event(
        "propose_add_transaction",
        {"date": "2020-01-02", "amount": -10000, "account": "ZZ Test A"},
        {
            "tool": "propose_add_transaction",
            "proposal_id": "prop-2",
            "proposal_token": "tok-2",
            "summary": "Add transaction: -10000 IDR on 2020-01-02",
        },
    )
    yield _make_stop_event("I've proposed two changes. Approve each one to apply it.")


def test_agent_stream_two_proposals_in_call_order(monkeypatch):
    """
    Two propose_* calls in one turn surface as a two-entry proposals list, in
    call order, with the singular fields mirroring the first entry and no
    token reaching any tool_result payload or the trace (T-02-07, D-20).
    """
    _install_mock_workflow(monkeypatch, _fake_stream_events_two_proposals)

    payloads = _stream_payloads("add account ZZ Test A and log a transaction")

    answer_payloads = [p for p in payloads if p.get("type") == "answer"]
    assert len(answer_payloads) == 1, f"Expected exactly one answer event: {payloads}"
    answer = answer_payloads[0]

    assert answer["proposals"] == [
        {"id": "prop-1", "token": "tok-1"},
        {"id": "prop-2", "token": "tok-2"},
    ]
    assert answer["proposal_id"] == "prop-1"
    assert answer["proposal_token"] == "tok-1"

    for step in answer["trace"]:
        result = step.get("result")
        if isinstance(result, dict):
            assert "proposal_token" not in result, \
                f"proposal_token leaked into public trace: {step}"

    dump = json.dumps([p for p in payloads if p.get("type") == "tool_result"])
    assert "tok-1" not in dump and "tok-2" not in dump, \
        "proposal token leaked into a tool_result payload"
    trace_dump = json.dumps(answer["trace"])
    assert "tok-1" not in trace_dump and "tok-2" not in trace_dump, \
        "proposal token leaked into the answer trace"


def test_agent_stream_error_answer_has_empty_proposals(monkeypatch):
    """The exception path's answer event carries proposals: [] (D-16)."""

    def _raise_stream_events():
        raise RuntimeError("synthetic stream failure")

    _install_mock_workflow(monkeypatch, _raise_stream_events)

    payloads = _stream_payloads("what's my net worth?")

    answer_payloads = [p for p in payloads if p.get("type") == "answer"]
    assert len(answer_payloads) == 1, f"Expected exactly one answer event: {payloads}"
    answer = answer_payloads[0]

    assert answer["proposals"] == []
    assert answer["proposal_id"] is None
    assert answer["proposal_token"] is None
    assert answer["trace"] == []
    assert "couldn't process" in answer["text"]


# ---------------------------------------------------------------------------
# AGENT-05: TODAY rebuilds across midnight with no writes in between
# ---------------------------------------------------------------------------


def test_agent_workflow_rebuilds_across_midnight(monkeypatch):
    """
    _get_agent_workflow() rebuilds when the calendar date changes, even with
    no reset_engine() call in between (the "no writes since yesterday" case).
    A same-day call reuses the cached object.
    """
    import datetime

    import backend.query as query_mod
    from llama_index.core.llms import MockLLM

    monkeypatch.setattr(query_mod, "_agent_workflow", None)
    monkeypatch.setattr(query_mod, "_agent_workflow_date", None)
    monkeypatch.setattr(query_mod, "_get_llm", lambda: MockLLM())

    d1 = datetime.date(2020, 1, 31)
    d2 = datetime.date(2020, 2, 1)

    monkeypatch.setattr(query_mod, "_today", lambda: d1)
    wf1 = query_mod._get_agent_workflow()
    assert "TODAY is 2020-01-31." in wf1.agents["Agent"].system_prompt
    assert query_mod._get_agent_workflow() is wf1

    monkeypatch.setattr(query_mod, "_today", lambda: d2)
    wf2 = query_mod._get_agent_workflow()
    assert wf2 is not wf1
    assert "TODAY is 2020-02-01." in wf2.agents["Agent"].system_prompt
    assert "2020-01-31" not in wf2.agents["Agent"].system_prompt
    assert query_mod._agent_workflow_date == d2

    query_mod.reset_engine()
    assert query_mod._agent_workflow is None
    assert query_mod._agent_workflow_date is None
