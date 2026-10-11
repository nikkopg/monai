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
import time

import pytest
from sqlalchemy import text

from backend.tests.chat_stubs import (
    Err429,
    StubLLM,
    _DEFAULT_ROWS,
    _SEEDED,
    _collect,
    _install_stub_workflow,
    _of_type,
    _payloads,
    _seed_proposal,
    purge_seeded,
    stream_bare,
)


@pytest.fixture(autouse=True)
def _cleanup_seeded():
    yield
    purge_seeded()


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
    # IN-04: one failure, one log line (the event branch and `await handler` both see it).
    assert sum(r.getMessage().startswith("chat run failed") for r in warnings) == 1
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

    lines = await _collect(agent_stream("synthetic question", idle_timeout=30))
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


# ---------------------------------------------------------------------------
# D-13 / D-14 / D-14a: idle watchdog and keep-alive pings
# ---------------------------------------------------------------------------


async def test_idle_timeout_emits_error(monkeypatch):
    from backend.query import Run, agent_stream

    _install_stub_workflow(monkeypatch, StubLLM(mode="hang"))
    run = Run()

    lines = await _collect(agent_stream("q", run=run, idle_timeout=0.3, ping_interval=5))
    payloads = _payloads(lines)

    assert _of_type(payloads, "answer") == []
    errs = _of_type(payloads, "error")
    assert [e["code"] for e in errs] == ["idle_timeout"]
    assert errs[0]["idle_seconds"] == 0.3
    assert lines[-1] == "data: [DONE]\n\n"
    assert run.handler.is_done()


async def test_stream_deltas_reset_idle_timer(monkeypatch):
    from backend.query import agent_stream

    # 5 deltas 0.2 s apart (~0.8 s total) survive a 0.5 s idle limit.
    _install_stub_workflow(monkeypatch, StubLLM(mode="drip"))

    payloads = _payloads(await _collect(agent_stream("q", idle_timeout=0.5, ping_interval=5)))

    assert _of_type(payloads, "error") == []
    assert len(_of_type(payloads, "answer")) == 1


async def test_quiet_stream_emits_ping(monkeypatch):
    from backend.query import agent_stream

    _install_stub_workflow(monkeypatch, StubLLM(mode="hang"))

    lines = await _collect(agent_stream("q", idle_timeout=0.6, ping_interval=0.1))

    assert lines.count(": ping\n\n") >= 2
    assert [e["code"] for e in _of_type(_payloads(lines), "error")] == ["idle_timeout"]


async def test_stream_ends_if_producer_dies_before_first_step(monkeypatch):
    """IN-01: a producer cancelled before it ran posts no sentinel; the stream still ends."""
    from backend.query import Run, agent_stream

    _install_stub_workflow(monkeypatch, StubLLM(mode="hang"))
    run = Run(key="synthetic")
    gen = agent_stream("q", run=run, ping_interval=0.05)
    first = asyncio.ensure_future(gen.__anext__())
    await asyncio.sleep(0)  # the generator runs up to its first queue wait
    assert run.task is not None and not run.task.done()
    run.task.cancel()  # before the producer's first step

    async def rest():
        return [await first] + [line async for line in gen]

    lines = await asyncio.wait_for(rest(), 2)
    assert lines[-1] == "data: [DONE]\n\n"


async def test_pings_do_not_reset_idle(monkeypatch):
    import time

    from backend.query import agent_stream

    _install_stub_workflow(monkeypatch, StubLLM(mode="hang"))

    t0 = time.monotonic()
    lines = await _collect(agent_stream("q", idle_timeout=0.6, ping_interval=0.1))

    assert time.monotonic() - t0 < 3
    assert [e["code"] for e in _of_type(_payloads(lines), "error")] == ["idle_timeout"]


async def test_idle_after_proposal_carries_proposals(monkeypatch):
    from backend.query import agent_stream

    _install_stub_workflow(monkeypatch, StubLLM(mode="tool_then_hang"))

    payloads = _payloads(await _collect(agent_stream("q", idle_timeout=0.4, ping_interval=5)))

    err = _of_type(payloads, "error")[0]
    assert err["code"] == "idle_timeout"
    assert err["proposals"][0]["id"] == str(_SEEDED[0])
    assert err["proposals"][0]["token"]


async def test_idle_timeout_defaults_to_config(monkeypatch):
    from backend import config
    from backend.query import agent_stream

    assert config.CHAT_IDLE_TIMEOUT_SECONDS == 120  # env unset in the test env
    monkeypatch.setattr(config, "CHAT_IDLE_TIMEOUT_SECONDS", 0.3)
    _install_stub_workflow(monkeypatch, StubLLM(mode="hang"))

    errs = _of_type(_payloads(await _collect(agent_stream("q", ping_interval=5))), "error")

    assert [e["code"] for e in errs] == ["idle_timeout"]


# ---------------------------------------------------------------------------
# Plan 02: run registry, Stop, disconnect cleanup, bulk reject (D-08..D-16)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_registry():
    import backend.query as query_mod

    query_mod._ACTIVE.clear()
    query_mod._LAST.clear()
    yield
    query_mod._ACTIVE.clear()
    query_mod._LAST.clear()


def _status_of(pid: str) -> str:
    from backend.db import SessionLocal

    db = SessionLocal()
    try:
        return db.execute(
            text("SELECT status FROM proposals WHERE id = :i"), {"i": pid}
        ).scalar_one()
    finally:
        db.close()


def _audit_count() -> int:
    from backend.db import SessionLocal

    db = SessionLocal()
    try:
        return db.execute(text("SELECT count(*) FROM audit_log")).scalar_one()
    finally:
        db.close()


async def test_run_stream_first_event_is_run(monkeypatch):
    from backend.query import CHAT_KEY, start_run

    _install_stub_workflow(monkeypatch, StubLLM(mode="ok"))
    run = start_run(CHAT_KEY)

    lines = await _collect(stream_bare(run, "synthetic question"))
    payloads = _payloads(lines)

    assert payloads[0] == {"type": "run", "run_id": run.id}
    assert len(_of_type(payloads, "answer")) == 1
    assert lines[-1] == "data: [DONE]\n\n"


def test_start_run_refuses_second_active_run():
    from backend.query import CHAT_KEY, start_run

    first = start_run(CHAT_KEY)
    assert first is not None
    assert start_run(CHAT_KEY) is None


@pytest.mark.parametrize("exit_path", ["answer", "error", "cancel", "disconnect"])
async def test_registry_released_on_every_exit(monkeypatch, exit_path):
    import anyio

    import backend.query as q

    mode = {"answer": "ok", "error": "429"}.get(exit_path, "hang")
    _install_stub_workflow(monkeypatch, StubLLM(mode=mode))
    run = q.start_run(q.CHAT_KEY)

    if exit_path in ("answer", "error"):
        await _collect(stream_bare(run, "q"))
    elif exit_path == "cancel":
        n = 0
        async for _ in stream_bare(run, "q"):
            n += 1
            if n == 2:  # run event + first step: the workflow is live
                await q.stop_run(run)
    else:
        async def consume():
            async for _ in stream_bare(run, "q"):
                if run.handler is not None and run.task is not None:
                    tg.cancel_scope.cancel()

        async with anyio.create_task_group() as tg:
            tg.start_soon(consume)

        # D-06: a disconnect only detaches the subscriber. The run lives on.
        assert q._ACTIVE[q.CHAT_KEY] is run
        assert not run.handler.is_done()
        await q.stop_run(run)

    await run.pump

    assert q.CHAT_KEY not in q._ACTIVE
    assert q._LAST[q.CHAT_KEY] is run
    assert q.start_run(q.CHAT_KEY) is not None


async def test_cancel_mid_run_ends_workflow(monkeypatch):
    import backend.query as q

    _install_stub_workflow(monkeypatch, StubLLM(mode="hang"))
    run = q.start_run(q.CHAT_KEY)
    lines: list[str] = []
    async for line in stream_bare(run, "q"):
        lines.append(line)
        if len(lines) == 2:
            await q.stop_run(run)

    payloads = _payloads(lines)
    assert _of_type(payloads, "answer") == []
    assert lines[-1] == "data: [DONE]\n\n"
    assert run.handler.is_done()


async def test_disconnect_detaches_and_keeps_proposals_pending(monkeypatch):
    """D-06 (amends Phase 34 D-12): a disconnect neither halts nor rejects."""
    import anyio

    import backend.query as q

    _install_stub_workflow(monkeypatch, StubLLM(mode="hang"))
    run = q.start_run(q.CHAT_KEY)
    pid, _ = _seed_proposal()
    run.proposal_ids.append(pid)

    async def consume():
        async for _ in stream_bare(run, "q"):
            if run.handler is not None:
                tg.cancel_scope.cancel()

    async with anyio.create_task_group() as tg:
        tg.start_soon(consume)

    assert _status_of(pid) == "pending"
    assert not run.handler.is_done()
    assert q._ACTIVE[q.CHAT_KEY] is run

    await q.stop_run(run)  # only Stop cancels and rejects
    await run.pump

    assert _status_of(pid) == "rejected"
    assert run.handler.is_done()
    assert q.CHAT_KEY not in q._ACTIVE


def test_reject_run_proposals_scope():
    import backend.query as q

    run = q.start_run(q.CHAT_KEY)
    a, _ = _seed_proposal()
    b, _ = _seed_proposal()  # not recorded: caught by the created-since-start sweep
    c, _ = _seed_proposal(channel="mcp")
    run.proposal_ids.append(a)
    before = _audit_count()

    assert sorted(q.reject_run_proposals(run)) == sorted([a, b])
    assert _status_of(a) == _status_of(b) == "rejected"
    assert _status_of(c) == "pending"
    assert _audit_count() == before
    # D-08a: a second call still reports every rejected id.
    assert sorted(q.reject_run_proposals(run)) == sorted([a, b])


async def test_stopped_run_sweeps_again_for_late_propose():
    """WR-01: a propose_* that commits after Stop's sweep is rejected at cleanup."""
    import backend.query as q

    run = q.start_run(q.CHAT_KEY)
    await q.stop_run(run)  # the sweep finds nothing yet
    late, _ = _seed_proposal()  # the tool thread commits after the sweep
    assert _status_of(late) == "pending"

    await q.finish_run(run)  # the pump's terminal step after a clean end

    assert _status_of(late) == "rejected"
    assert run.done and run.events[-1] == "data: [DONE]\n\n"
    assert q.CHAT_KEY not in q._ACTIVE


async def test_completed_unstopped_run_does_not_sweep():
    import backend.query as q

    run = q.start_run(q.CHAT_KEY)
    other, _ = _seed_proposal()  # delivered proposal must stay approvable
    await q.finish_run(run)

    assert _status_of(other) == "pending"
    assert run.done and run.events[-1] == "data: [DONE]\n\n"


# ---------------------------------------------------------------------------
# Plan 02: HTTP routes (409, cancel). Runs carry no handler/task: the session
# TestClient gives each request its own loop, so mid-run behaviour is tested
# at the query level above.
# ---------------------------------------------------------------------------


def _cancel(client, api_key, run):
    return client.post(
        f"/query-stream/{run.id}/cancel", headers={"MONAI_API_KEY": api_key}
    )


def test_second_run_returns_409(client, api_key, monkeypatch):
    import backend.query as q

    called = []

    async def _stub(question, **kw):
        called.append(question)
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(q, "agent_stream", _stub)
    occupying = q.start_run(q.CHAT_KEY)

    resp = client.post(
        "/query-stream", json={"question": "q"}, headers={"MONAI_API_KEY": api_key}
    )

    assert resp.status_code == 409
    assert resp.json() == {"detail": "A run is already in progress for this conversation"}
    assert called == []
    assert q._ACTIVE[q.CHAT_KEY] is occupying


def test_cancel_route_rejects_pending(client, api_key):
    import backend.query as q

    run = q.start_run(q.CHAT_KEY)
    a, _ = _seed_proposal()
    b, _ = _seed_proposal()
    c, _ = _seed_proposal(channel="mcp")
    run.proposal_ids.append(a)
    before = _audit_count()

    resp = _cancel(client, api_key, run)

    assert resp.status_code == 200
    assert sorted(resp.json()["rejected"]) == sorted([a, b])
    assert _status_of(c) == "pending"
    assert _audit_count() == before


def test_cancel_unknown_run_404(client, api_key):
    import uuid

    resp = client.post(
        f"/query-stream/{uuid.uuid4()}/cancel", headers={"MONAI_API_KEY": api_key}
    )
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Run not found"}


def test_cancel_after_completion_still_rejects(client, api_key):
    import backend.query as q

    run = q.start_run(q.CHAT_KEY)
    a, _ = _seed_proposal()
    run.proposal_ids.append(a)
    q.release_run(run)  # now the last-finished run

    resp = _cancel(client, api_key, run)

    assert resp.status_code == 200
    assert a in resp.json()["rejected"]
    assert _status_of(a) == "rejected"


def test_cancel_returns_rejected_ids_even_if_an_earlier_sweep_ran(client, api_key):
    import backend.query as q

    run = q.start_run(q.CHAT_KEY)
    a, _ = _seed_proposal()
    run.proposal_ids.append(a)
    q.reject_run_proposals(run)  # an earlier sweep (the pump's or Stop's) got there first

    assert a in _cancel(client, api_key, run).json()["rejected"]


def test_cancel_route_unknown_after_next_run(client, api_key):
    import backend.query as q

    first = q.start_run(q.CHAT_KEY)
    q.release_run(first)
    assert q.start_run(q.CHAT_KEY) is not None  # clears the last-finished slot

    assert _cancel(client, api_key, first).status_code == 404
