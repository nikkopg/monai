"""
Chat reliability tests (Phase 34): REL-01, REL-02, REL-04, REL-07, REL-09.

Every test drives the REAL agent_stream through a REAL LlamaIndex
AgentWorkflow whose FunctionAgent uses StubLLM, so the terminal workflow
events (WorkflowFailedEvent, WorkflowTimedOutEvent, ...) are genuinely
produced rather than mocked. The stub workflow is planted through the
backend.query._agent_workflow / _agent_workflow_date seam.

Tests:
  test_provider_429_emits_error_not_answer — a provider 429 is an error
      event, never an empty successful answer (REL-01, D-01)
  test_classify_error_shapes — every provider failure shape maps to its
      typed code (D-03)
  test_error_event_has_no_raw_exception_text — no exception text or question
      in any SSE line; the class and message go to the log (D-04)
  test_error_after_proposal_carries_proposals,
  test_answer_proposals_carry_payload_and_expiry — proposals hydrated from the
      DB row, token only in the terminal event (D-05, D-05a, D-19, REL-07)
  test_empty_answer_without_trace_is_error,
  test_blank_text_with_tool_steps_is_answer — the empty rule (REL-02, D-06)
  test_whole_run_timeout_maps_to_timeout, test_cancelled_workflow_emits_no_answer
      — terminal subclasses of StopEvent are not answers (D-01a)
  test_events_carry_model_and_provider — model label (REL-09, D-21)
  test_idle_timeout_emits_error and friends — idle watchdog and pings (REL-04)

All values are synthetic. The DB is the isolated monai_test database
selected by conftest.
"""

import asyncio
import datetime
import json
import logging
import secrets
import time

import pytest
from llama_index.core.agent.workflow import AgentWorkflow, FunctionAgent
from llama_index.core.base.llms.types import TextBlock, ToolCallBlock
from llama_index.core.llms import (
    ChatMessage,
    ChatResponse,
    LLMMetadata,
    MockFunctionCallingLLM,
)
from llama_index.core.llms.llm import ToolSelection
from llama_index.core.tools import FunctionTool
from sqlalchemy import text


class Err429(Exception):
    """Synthetic provider rate-limit error (duck-typed status_code)."""

    status_code = 429


def _resp(content: str, delta: str) -> ChatResponse:
    return ChatResponse(
        message=ChatMessage(role="assistant", content=content), delta=delta
    )


class StubLLM(MockFunctionCallingLLM):
    """Scripted function-calling LLM. `mode` picks the behaviour."""

    mode: str = "ok"
    model: str = "example-model:7b"
    calls: int = 0
    final_text: str = "Hello"
    drip_count: int = 5
    drip_gap: float = 0.2

    @property
    def metadata(self):
        return LLMMetadata(is_function_calling_model=True, is_chat_model=True)

    async def astream_chat_with_tools(
        self, tools, user_msg=None, chat_history=None, **kw
    ):
        self.calls += 1
        n = self.calls
        mode = self.mode
        text_ = self.final_text

        async def final():
            if text_ == "":
                yield _resp("", "")
                return
            half = max(1, len(text_) // 2)
            yield _resp(text_[:half], text_[:half])
            yield _resp(text_, text_[half:])

        async def tool_turn():
            yield _resp("let me check", "let me check")
            yield ChatResponse(
                message=ChatMessage(
                    role="assistant",
                    blocks=[
                        TextBlock(text="let me check"),
                        ToolCallBlock(
                            tool_name="seed_proposal",
                            tool_kwargs={},
                            tool_call_id="c1",
                        ),
                    ],
                ),
                delta="",
            )

        async def gen():
            if mode == "429":
                raise Err429("rate limited SECRET-sk-synthetic")
            if mode == "hang":
                yield _resp("par", "par")
                await asyncio.sleep(3600)
            elif mode == "empty":
                yield _resp("", "")
            elif mode == "drip":
                acc = ""
                for i in range(self.drip_count):
                    if i:
                        await asyncio.sleep(self.drip_gap)
                    acc += "x"
                    yield _resp(acc, "x")
                async for r in final():
                    yield r
            elif mode in ("tool", "tool_then_429", "tool_then_hang"):
                if n == 1:
                    async for r in tool_turn():
                        yield r
                elif mode == "tool_then_429":
                    raise Err429("rate limited SECRET-sk-synthetic")
                elif mode == "tool_then_hang":
                    yield _resp("par", "par")
                    await asyncio.sleep(3600)
                else:
                    async for r in final():
                        yield r
            else:
                async for r in final():
                    yield r

        return gen()

    def get_tool_calls_from_response(
        self, response, error_on_no_tool_call=True, **kw
    ):
        out = []
        for b in response.message.blocks:
            if isinstance(b, ToolCallBlock):
                out.append(
                    ToolSelection(
                        tool_id=b.tool_call_id or "c1",
                        tool_name=b.tool_name,
                        tool_kwargs=b.tool_kwargs
                        if isinstance(b.tool_kwargs, dict)
                        else {},
                    )
                )
        return out


# ---------------------------------------------------------------------------
# Proposal seeding
# ---------------------------------------------------------------------------

_SEEDED: list = []

_DEFAULT_ROWS = [
    {
        "before": None,
        "after": {
            "date": "2020-01-01",
            "amount": "-12345.00",
            "merchant": "Example Merchant",
            "account": "Account A",
        },
    }
]


def _seed_proposal(*, channel="chat", rows=None) -> tuple[str, str]:
    from backend.db import SessionLocal
    from backend.models import Proposal

    rows = _DEFAULT_ROWS if rows is None else rows
    token = secrets.token_urlsafe(32)
    db = SessionLocal()
    try:
        p = Proposal(
            token=token,
            operation="add_transaction",
            payload={"operation": "add_transaction", "rows": rows},
            status="pending",
            channel=channel,
            expires_at=datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(minutes=15),
        )
        db.add(p)
        db.commit()
        _SEEDED.append(p.id)
        return str(p.id), token
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _cleanup_seeded():
    yield
    if not _SEEDED:
        return
    from backend.db import SessionLocal

    db = SessionLocal()
    try:
        for i in _SEEDED:
            db.execute(text("DELETE FROM proposals WHERE id = :i"), {"i": i})
        db.commit()
    finally:
        db.close()
        _SEEDED.clear()


def seed_proposal() -> dict:
    """Create a synthetic pending proposal."""
    pid, token = _seed_proposal()
    return {
        "tool": "seed_proposal",
        "proposal_id": pid,
        "proposal_token": token,
        "summary": "synthetic",
    }


# ---------------------------------------------------------------------------
# Harness helpers
# ---------------------------------------------------------------------------


def _install_stub_workflow(monkeypatch, llm, *, timeout=30.0):
    import backend.query as query_mod

    agent = FunctionAgent(
        tools=[FunctionTool.from_defaults(fn=seed_proposal, name="seed_proposal")],
        llm=llm,
        system_prompt="synthetic",
    )
    workflow = AgentWorkflow(agents=[agent], timeout=timeout)
    monkeypatch.setattr(query_mod, "_agent_workflow", workflow)
    monkeypatch.setattr(query_mod, "_agent_workflow_date", query_mod._today())
    return workflow


async def _collect(gen) -> list[str]:
    return [line async for line in gen]


def _payloads(lines: list[str]) -> list[dict]:
    out = []
    for line in lines:
        if not line.startswith("data: "):
            continue
        raw = line[len("data: "):].strip()
        if raw == "[DONE]":
            continue
        out.append(json.loads(raw))
    return out


def _of_type(payloads: list[dict], t: str) -> list[dict]:
    return [p for p in payloads if p.get("type") == t]


# ---------------------------------------------------------------------------
# REL-01: the reproduction (written first, D-01)
# ---------------------------------------------------------------------------


async def test_provider_429_emits_error_not_answer(monkeypatch):
    from backend.query import agent_stream

    _install_stub_workflow(monkeypatch, StubLLM(mode="429"))

    lines = await _collect(agent_stream("synthetic question"))
    payloads = _payloads(lines)

    assert _of_type(payloads, "answer") == [], f"429 must not yield an answer: {payloads}"
    errors = _of_type(payloads, "error")
    assert len(errors) == 1, payloads
    assert errors[0]["code"] == "rate_limit"
    assert errors[0]["model"] == "example-model:7b"
    assert lines[-1] == "data: [DONE]\n\n"


# ---------------------------------------------------------------------------
# D-03: the classifier (synthetic exception shapes, no network)
# ---------------------------------------------------------------------------


def _exc(name="Err", bases=(Exception,), **attrs):
    return type(name, bases, attrs)("x")


def _classify_cases():
    import httpx
    from types import SimpleNamespace

    from llama_index.core.workflow import WorkflowTimeoutError

    conn_base = type("APIConnectionError", (Exception,), {})
    api_timeout = type("APITimeoutError", (conn_base,), {})
    resp_429 = _exc("HTTPErr")
    resp_429.response = SimpleNamespace(status_code=429)
    return [
        (_exc(status_code=429), "rate_limit"),
        (_exc(status_code=500), "provider_unavailable"),
        (_exc(status_code=503), "provider_unavailable"),
        (_exc(status_code=529), "provider_unavailable"),
        (_exc(status_code=401), "auth"),
        (_exc(status_code=403), "auth"),
        (resp_429, "rate_limit"),
        (TimeoutError(), "timeout"),
        (httpx.ReadTimeout("x"), "timeout"),
        (api_timeout("x"), "timeout"),  # not shadowed by its connection base
        (WorkflowTimeoutError("x"), "timeout"),
        (ConnectionError(), "connection"),
        (httpx.ConnectError("x"), "connection"),
        (conn_base("x"), "connection"),
        (_exc("ResponseError", status_code=-1), "unknown"),
        (_exc(status_code=404), "unknown"),
        (ValueError(), "unknown"),
    ]


@pytest.mark.parametrize("exc,code", _classify_cases())
def test_classify_error_shapes(exc, code):
    from backend.query import classify_error

    assert classify_error(exc) == code


# ---------------------------------------------------------------------------
# D-04: no raw exception text or question in any SSE line
# ---------------------------------------------------------------------------


async def test_error_event_has_no_raw_exception_text(monkeypatch, caplog):
    from backend.query import agent_stream

    caplog.set_level(logging.WARNING)
    _install_stub_workflow(monkeypatch, StubLLM(mode="429"))

    lines = await _collect(agent_stream("QUESTION-MARKER synthetic"))

    blob = "".join(lines)
    assert "SECRET-sk-synthetic" not in blob
    assert "QUESTION-MARKER" not in blob
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("Err429" in r.getMessage() for r in warnings)
    assert not any("QUESTION-MARKER" in r.getMessage() for r in warnings)


# ---------------------------------------------------------------------------
# D-05 / D-19 / REL-07: proposals hydrated from the DB row
# ---------------------------------------------------------------------------


def _token_of(pid: str) -> str:
    from backend.db import SessionLocal
    from backend.models import Proposal

    db = SessionLocal()
    try:
        return db.get(Proposal, pid).token
    finally:
        db.close()


async def test_error_after_proposal_carries_proposals(monkeypatch):
    from backend.query import agent_stream

    _install_stub_workflow(monkeypatch, StubLLM(mode="tool_then_429"))

    payloads = _payloads(await _collect(agent_stream("synthetic question")))

    assert _of_type(payloads, "answer") == []
    err = _of_type(payloads, "error")[0]
    assert err["code"] == "rate_limit"
    entry = err["proposals"][0]
    pid = str(_SEEDED[0])
    assert entry["id"] == pid
    assert entry["token"] == _token_of(pid)  # D-05a
    assert entry["operation"] == "add_transaction"
    assert entry["payload"]["rows"] == _DEFAULT_ROWS
    datetime.datetime.fromisoformat(entry["expires_at"])


async def test_answer_proposals_carry_payload_and_expiry(monkeypatch):
    from backend.query import agent_stream

    _install_stub_workflow(monkeypatch, StubLLM(mode="tool", final_text="Done"))

    payloads = _payloads(await _collect(agent_stream("synthetic question")))

    answer = _of_type(payloads, "answer")[0]
    entry = answer["proposals"][0]
    pid = str(_SEEDED[0])
    token = _token_of(pid)
    assert entry["id"] == pid and entry["token"] == token
    assert entry["operation"] == "add_transaction"
    assert entry["payload"]["rows"] == _DEFAULT_ROWS
    datetime.datetime.fromisoformat(entry["expires_at"])
    # T-02-07: the token is in the terminal answer only
    assert token not in json.dumps(_of_type(payloads, "tool_result"))
    assert token not in json.dumps(answer["trace"])
    assert _of_type(payloads, "tool_result")[0]["step"]["result"]["proposal_id"] == pid


# ---------------------------------------------------------------------------
# D-06: the empty rule
# ---------------------------------------------------------------------------


async def test_empty_answer_without_trace_is_error(monkeypatch):
    from backend.query import agent_stream

    _install_stub_workflow(monkeypatch, StubLLM(mode="empty"))

    payloads = _payloads(await _collect(agent_stream("synthetic question")))

    assert _of_type(payloads, "answer") == []
    assert [e["code"] for e in _of_type(payloads, "error")] == ["empty"]


async def test_blank_text_with_tool_steps_is_answer(monkeypatch):
    from backend.query import agent_stream

    _install_stub_workflow(monkeypatch, StubLLM(mode="tool", final_text=""))

    payloads = _payloads(await _collect(agent_stream("synthetic question")))

    assert _of_type(payloads, "error") == []
    answer = _of_type(payloads, "answer")[0]
    assert answer["text"] == "" and len(answer["trace"]) == 1


# ---------------------------------------------------------------------------
# D-01a / D-15: terminal StopEvent subclasses are not answers
# ---------------------------------------------------------------------------


async def test_whole_run_timeout_maps_to_timeout(monkeypatch):
    from backend.query import agent_stream

    _install_stub_workflow(monkeypatch, StubLLM(mode="hang"), timeout=0.5)

    lines = await _collect(agent_stream("synthetic question"))
    payloads = _payloads(lines)

    assert _of_type(payloads, "answer") == []
    assert [e["code"] for e in _of_type(payloads, "error")] == ["timeout"]
    assert lines[-1] == "data: [DONE]\n\n"


async def test_cancelled_workflow_emits_no_answer(monkeypatch):
    from backend.query import Run, agent_stream

    _install_stub_workflow(monkeypatch, StubLLM(mode="hang"))
    run = Run()
    lines: list[str] = []
    async for line in agent_stream("synthetic question", run=run):
        lines.append(line)
        if len(lines) == 1:
            await run.handler.cancel_run()
    await asyncio.sleep(0)

    payloads = _payloads(lines)
    assert _of_type(payloads, "answer") == [] and _of_type(payloads, "error") == []
    assert lines[-1] == "data: [DONE]\n\n"
    assert run.task.done()


# ---------------------------------------------------------------------------
# D-10: the run records proposal ids as results arrive
# ---------------------------------------------------------------------------


async def test_run_records_proposal_ids(monkeypatch):
    from backend.query import Run, agent_stream

    _install_stub_workflow(monkeypatch, StubLLM(mode="tool", final_text="Done"))
    run = Run()

    await _collect(agent_stream("synthetic question", run=run))

    assert run.proposal_ids == [str(_SEEDED[0])]


# ---------------------------------------------------------------------------
# REL-09 / D-21: model + provider come from the LLM instance that ran
# ---------------------------------------------------------------------------


async def test_events_carry_model_and_provider(monkeypatch):
    from backend.query import agent_stream

    _install_stub_workflow(monkeypatch, StubLLM(mode="ok"))
    answer = _of_type(_payloads(await _collect(agent_stream("q"))), "answer")[0]
    assert answer["model"] == "example-model:7b"
    assert "provider" in answer and answer["provider"] is None  # StubLLM is no provider class


def test_llm_label_maps_class_to_provider():
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from backend.query import _llm_label

    for cls_name, provider in (("Ollama", "ollama"), ("Anthropic", "claude"), ("OpenAI", "openai")):
        llm = type(cls_name, (), {"model": "example-model:7b"})()
        wf = SimpleNamespace(agents={"Agent": SimpleNamespace(llm=llm)})
        assert _llm_label(wf) == ("example-model:7b", provider)
    assert _llm_label(MagicMock()) == (None, None)
