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
    """Fake ToolCallResult event — represents one tool execution."""
    from llama_index.core.agent.workflow.workflow_events import ToolCallResult
    evt = MagicMock(spec=ToolCallResult)
    evt.tool_name = tool_name
    evt.tool_kwargs = tool_kwargs
    output = MagicMock()
    output.content = json.dumps(result_dict)
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

    mock_handler = MagicMock()
    mock_handler.stream_events = lambda: _fake_stream_events_two_tools()

    mock_workflow = MagicMock()
    mock_workflow.run = MagicMock(return_value=mock_handler)

    monkeypatch.setattr("backend.query._agent_workflow", mock_workflow)

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

    mock_handler = MagicMock()
    mock_handler.stream_events = lambda: _fake_stream_events_refusal(refusal_text)

    mock_workflow = MagicMock()
    mock_workflow.run = MagicMock(return_value=mock_handler)

    monkeypatch.setattr("backend.query._agent_workflow", mock_workflow)

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

    mock_handler = MagicMock()
    mock_handler.stream_events = lambda: _fake_stream_events_refusal(refusal_text)

    mock_workflow = MagicMock()
    mock_workflow.run = MagicMock(return_value=mock_handler)

    monkeypatch.setattr("backend.query._agent_workflow", mock_workflow)

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
