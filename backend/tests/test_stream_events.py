"""
Phase 37 event contract for agent_stream (D-02, D-02a, D-12, D-25).

token / tool_start / timed and sourced tool_result, driven by the scripted
StubLLM so the real AgentWorkflow event order is exercised. All values are
synthetic; the DB is monai_test.
"""

import json
from unittest.mock import MagicMock

import pytest

from backend.tests.chat_stubs import (
    StubLLM,
    _SEEDED,
    _collect,
    _install_stub_workflow,
    _of_type,
    _payloads,
    fake_spending_total,
    purge_seeded,
    slow_echo,
)

MAR_KW = {"period": "custom", "start_date": "2001-03-01", "end_date": "2001-03-31"}


@pytest.fixture(autouse=True)
def _cleanup_seeded():
    yield
    purge_seeded()


async def _run(monkeypatch, llm, **extra):
    from backend.query import agent_stream

    _install_stub_workflow(monkeypatch, llm, **extra)
    lines = await _collect(agent_stream("synthetic question"))
    return lines, _payloads(lines)


def _kinds(payloads):
    return [p["type"] for p in payloads if p["type"] != "run"]


async def test_event_order_iterations_and_authoritative_answer(monkeypatch):
    llm = StubLLM(mode="tool", tool_name="slow_echo", tool_kwargs={"n": 1})
    _, ps = await _run(monkeypatch, llm, extra_tools={"slow_echo": slow_echo})

    assert _kinds(ps) == [
        "step", "token", "tool_start", "tool_result",
        "step", "token", "token", "answer",
    ]
    toks = _of_type(ps, "token")
    assert [(t["delta"], t["iteration"]) for t in toks] == [
        ("let me check", 0), ("He", 1), ("llo", 1),
    ]
    start, result = _of_type(ps, "tool_start")[0], _of_type(ps, "tool_result")[0]
    assert start["call_id"] == result["call_id"] == "c0-0"
    assert start["iteration"] == 0 and start["tool"] == "slow_echo" and start["args"] == {"n": 1}
    assert isinstance(result["ms"], int) and result["ms"] >= 0
    assert set(result["step"]) == {"tool", "args", "result"}

    answer = _of_type(ps, "answer")[0]
    assert answer["text"] == "".join(t["delta"] for t in toks if t["iteration"] == 1) == "Hello"
    # removing the new events leaves the pre-phase sequence (old clients, eval)
    assert [k for k in _kinds(ps) if k not in ("token", "tool_start")] == [
        "step", "tool_result", "step", "answer",
    ]


async def test_token_payload_keys_are_exact(monkeypatch):
    _, ps = await _run(monkeypatch, StubLLM(mode="ok"))
    toks = _of_type(ps, "token")
    assert toks and all(set(t) == {"type", "delta", "iteration"} for t in toks)


async def test_same_name_calls_with_colliding_ids_get_distinct_call_ids(monkeypatch):
    llm = StubLLM(mode="two_calls")
    _, ps = await _run(monkeypatch, llm, extra_tools={"slow_echo": slow_echo})

    starts = _of_type(ps, "tool_start")
    results = _of_type(ps, "tool_result")
    assert sorted(s["call_id"] for s in starts) == ["c0-0", "c0-1"]
    by_n = {s["args"]["n"]: s["call_id"] for s in starts}
    assert len(results) == 2
    for r in results:
        assert r["call_id"] == by_n[r["step"]["args"]["n"]]
        assert r["ms"] >= 40  # the tool sleeps 50 ms


async def test_result_without_tool_call_gets_fresh_id_and_null_ms(monkeypatch):
    from llama_index.core.agent.workflow.workflow_events import AgentInput
    from backend.tests.test_agent import (
        _install_mock_workflow,
        _make_stop_event,
        _make_tool_result_event,
    )
    from backend.query import agent_stream

    async def events():
        yield MagicMock(spec=AgentInput)
        yield _make_tool_result_event("slow_echo", {"n": 1}, {"tool": "slow_echo", "n": 1})
        yield _make_stop_event("done")

    _install_mock_workflow(monkeypatch, events)
    ps = _payloads(await _collect(agent_stream("q")))
    r = _of_type(ps, "tool_result")[0]
    assert r["call_id"] and r["ms"] is None
    assert _of_type(ps, "tool_start") == []


async def test_read_tool_result_carries_sources_and_write_does_not(monkeypatch):
    from backend.sources import source_for

    llm = StubLLM(mode="tool", tool_name="spending_total", tool_kwargs=MAR_KW)
    _, ps = await _run(monkeypatch, llm, extra_tools={"spending_total": fake_spending_total})
    expected = source_for("spending_total", MAR_KW, {"tool": "spending_total", "total": 1.0})
    assert expected  # non-vacuous
    assert _of_type(ps, "tool_result")[0]["sources"] == expected

    _, ps = await _run(monkeypatch, StubLLM(mode="tool"))
    assert _of_type(ps, "tool_result")[0]["sources"] == []


async def test_proposal_token_never_in_token_tool_start_or_tool_result(monkeypatch):
    lines, ps = await _run(monkeypatch, StubLLM(mode="tool"))
    token = _of_type(ps, "answer")[0]["proposal_token"]
    assert token and _SEEDED
    for line in lines:
        if any(f'"type": "{t}"' in line for t in ("token", "tool_start", "tool_result")):
            assert token not in line
