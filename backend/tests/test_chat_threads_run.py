"""
Thread-run engine tests (Phase 36 plan 03): the server-owned turn.

Detach, re-attach and replay are tested at the query / chat_service level with
anyio task groups, never through the HTTP client: the session TestClient gives
each request its own event loop, so a detached task would die with it
(Pitfall 4).

Tests:
  test_make_proposal_stamps_turn_id, test_turn_id_reaches_tool_executor_thread
      -- CURRENT_TURN_ID stamps chat proposals only (D-12a)
  test_stop_rejects_by_turn_id, test_fallback_sweep_only_matches_rows_without_turn_id
      -- Stop is precise per turn (D-12)
  test_disconnect_detaches, test_reattach_replay_order, test_reattach_redacts_tokens,
  test_redact_tokens_leaves_other_chunks, test_pump_cancel_still_releases,
  test_subscriber_pings_when_quiet, test_one_run_per_key, test_last_is_capped
      -- the detached pump, its event buffer and subscribers (D-05..D-08)

All values are synthetic. The DB is the isolated monai_test database.
"""

import asyncio
import contextlib
import contextvars
import datetime
import json
import uuid

import anyio
import pytest

from backend import chat_service
from backend import query as q
from backend import tools
from backend.tests.chat_stubs import (
    StubLLM,
    _collect,
    _install_stub_workflow,
    _of_type,
    _payloads,
    _seed_proposal,
    purge_seeded,
    stream_bare,
)


@pytest.fixture(autouse=True)
def _clean():
    q._ACTIVE.clear()
    q._LAST.clear()
    yield
    q._ACTIVE.clear()
    q._LAST.clear()
    purge_seeded()


def _status_of(pid: str) -> str:
    from backend.db import SessionLocal
    from backend.models import Proposal

    db = SessionLocal()
    try:
        return db.get(Proposal, uuid.UUID(str(pid))).status
    finally:
        db.close()


def _turn_id_of(pid: str):
    from backend.db import SessionLocal
    from backend.models import Proposal

    db = SessionLocal()
    try:
        return db.get(Proposal, uuid.UUID(str(pid))).turn_id
    finally:
        db.close()


def _delete(*pids: str) -> None:
    from backend.db import SessionLocal
    from backend.models import Proposal

    db = SessionLocal()
    try:
        for pid in pids:
            row = db.get(Proposal, uuid.UUID(str(pid)))
            if row is not None:
                db.delete(row)
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# turn_id plumbing (D-12a)
# ---------------------------------------------------------------------------


def test_make_proposal_stamps_turn_id():
    turn = uuid.uuid4()
    payload = {"operation": "add_transaction", "rows": []}
    made: list[str] = []
    try:

        def inside():
            tools.CURRENT_TURN_ID.set(turn)
            chat_id, _ = tools._make_proposal("add_transaction", payload, "chat")
            mcp_id, _ = tools._make_proposal("add_transaction", payload, "mcp")
            made.extend([chat_id, mcp_id])
            return chat_id, mcp_id

        chat_id, mcp_id = contextvars.copy_context().run(inside)
        unset_id, _ = tools._make_proposal("add_transaction", payload, "chat")
        made.append(unset_id)

        assert _turn_id_of(chat_id) == turn
        assert _turn_id_of(mcp_id) is None
        assert _turn_id_of(unset_id) is None
    finally:
        _delete(*made)


async def test_turn_id_reaches_tool_executor_thread(monkeypatch):
    _install_stub_workflow(monkeypatch, StubLLM(mode="tool", final_text="Done"))
    turn = uuid.uuid4()

    async def drive():
        tools.CURRENT_TURN_ID.set(turn)
        return await _collect(q.agent_stream("synthetic question"))

    lines = await asyncio.create_task(drive())
    answer = _of_type(_payloads(lines), "answer")[0]
    pid = answer["proposals"][0]["id"]

    assert _turn_id_of(pid) == turn


# ---------------------------------------------------------------------------
# Stop rejects by turn id (D-12)
# ---------------------------------------------------------------------------


def test_stop_rejects_by_turn_id():
    run_a = q.Run(key="a")
    run_b = q.Run(key="b")
    # A's rows predate A.started_at: only the turn id can catch them.
    run_a.started_at = datetime.datetime.now(
        datetime.timezone.utc
    ) + datetime.timedelta(minutes=1)
    mine, _ = _seed_proposal(turn_id=uuid.UUID(run_a.id))
    theirs, _ = _seed_proposal(turn_id=uuid.UUID(run_b.id))
    mcp, _ = _seed_proposal(channel="mcp")

    assert q.reject_run_proposals(run_a) == [mine]
    assert _status_of(mine) == "rejected"
    assert _status_of(theirs) == "pending"
    assert _status_of(mcp) == "pending"


def test_fallback_sweep_only_matches_rows_without_turn_id():
    run_c = q.Run(key="c")
    run_c.started_at = datetime.datetime.now(
        datetime.timezone.utc
    ) - datetime.timedelta(seconds=2)
    legacy, _ = _seed_proposal()
    other_turn, _ = _seed_proposal(turn_id=uuid.uuid4())

    # Membership, not equality: other tests' leftover legacy rows may be in range.
    rejected = q.reject_run_proposals(run_c)
    assert legacy in rejected and other_turn not in rejected
    assert _status_of(legacy) == "rejected"
    assert _status_of(other_turn) == "pending"


# ---------------------------------------------------------------------------
# Detached pump, buffer and subscribers (D-05, D-06, D-07, D-08)
# ---------------------------------------------------------------------------


def _types(lines: list[str]) -> list[str]:
    return [p["type"] for p in _payloads(lines)]


async def _wait_for(pred, timeout: float = 5.0) -> None:
    async with asyncio.timeout(timeout):
        while not pred():
            await asyncio.sleep(0.01)


async def test_disconnect_detaches(monkeypatch):
    _install_stub_workflow(monkeypatch, StubLLM(mode="drip", drip_gap=0.05))
    run = q.start_run("t")

    async def consume():
        async for _ in stream_bare(run, "q"):
            tg.cancel_scope.cancel()  # the client goes away after the first chunk

    async with anyio.create_task_group() as tg:
        tg.start_soon(consume)

    assert q._ACTIVE["t"] is run and not run.done and not run.stopped
    await run.pump

    assert run.done and not run.stopped
    assert _types(run.events) == ["run", "step", "answer"]
    assert q._LAST["t"] is run and "t" not in q._ACTIVE


async def test_reattach_replay_order(monkeypatch):
    _install_stub_workflow(monkeypatch, StubLLM(mode="drip", drip_gap=0.05))
    run = q.start_run("t")
    first = asyncio.create_task(_collect(stream_bare(run, "q")))
    await _wait_for(lambda: len(run.events) >= 2)
    assert not run.done  # mid-run
    second = asyncio.create_task(_collect(q.subscribe(run)))

    lines_first = await first
    await run.pump
    lines_late = await _collect(q.subscribe(run))  # after completion: from _LAST

    assert lines_first == await second == lines_late
    assert _types(lines_first) == ["run", "step", "answer"]
    assert lines_first[-1] == "data: [DONE]\n\n"


@pytest.mark.parametrize(
    "mode, kind", [("tool", "answer"), ("tool_then_429", "error")]
)
async def test_reattach_redacts_tokens(monkeypatch, mode, kind):
    _install_stub_workflow(monkeypatch, StubLLM(mode=mode, final_text="Done"))
    run = q.start_run("t")
    await _collect(stream_bare(run, "q"))
    await run.pump

    full = await _collect(q.subscribe(run))
    redacted = await _collect(q.subscribe(run, redact=True))

    terminal = _of_type(_payloads(full), kind)[0]
    token = terminal["proposals"][0]["token"]  # the original stream keeps it
    assert token in "".join(full)
    assert token not in "".join(redacted)
    red = _of_type(_payloads(redacted), kind)[0]
    assert red["proposals"] and all("token" not in p for p in red["proposals"])
    assert red.get("proposal_token") is None


def test_redact_tokens_leaves_other_chunks():
    step = q._sse({"type": "step", "text": "thinking"})
    stray = q._sse({"type": "tool_result", "token": "synthetic"})
    for chunk in (
        step,
        stray,
        ": ping\n\n",
        q._DONE,
        'data: {"token": broken\n\n',
        "not an sse line",
    ):
        assert q.redact_tokens(chunk) == chunk


async def test_pump_cancel_still_releases(monkeypatch):
    _install_stub_workflow(monkeypatch, StubLLM(mode="hang"))
    run = q.start_run("t")
    chat_service.launch(run, "q")
    await _wait_for(lambda: run.handler is not None and run.task is not None)

    run.pump.cancel()  # process shutdown
    with contextlib.suppress(asyncio.CancelledError):
        await run.pump

    assert run.done and run.events[-1] == q._DONE
    assert "t" not in q._ACTIVE and q._LAST["t"] is run
    await _wait_for(run.handler.is_done)  # agent_stream's own shielded halt


async def test_subscriber_pings_when_quiet(monkeypatch):
    _install_stub_workflow(monkeypatch, StubLLM(mode="hang"))
    run = q.start_run("t")
    chat_service.launch(run, "q")

    seen = []
    async for chunk in q.subscribe(run, ping_interval=0.05):
        seen.append(chunk)
        if chunk == ": ping\n\n":
            break
    await q.stop_run(run)
    await run.pump

    assert seen[-1] == ": ping\n\n"
    assert not any(e.startswith(":") for e in run.events)  # pings never reach the buffer


def test_one_run_per_key():
    a = q.start_run("a")
    assert a is not None
    assert q.start_run("a") is None
    assert q.start_run("b") is not None


def test_last_is_capped():
    for i in range(25):
        q.release_run(q.start_run(f"k{i}"))

    assert list(q._LAST) == [f"k{i}" for i in range(5, 25)]


# ---------------------------------------------------------------------------
# Persisted turns (plan 05): threads, messages, replayed history
# ---------------------------------------------------------------------------


@pytest.fixture()
def _threads():
    """Collect created thread ids; delete them (messages cascade) afterwards."""
    ids: list = []
    yield ids
    from sqlalchemy import text

    from backend.db import SessionLocal

    db = SessionLocal()
    try:
        for t in ids:
            db.execute(text("DELETE FROM threads WHERE id = :i"), {"i": t})
        db.commit()
    finally:
        db.close()


def _messages(tid):
    from backend.db import SessionLocal
    from backend.models import Message

    db = SessionLocal()
    try:
        return list(
            db.query(Message).filter(Message.thread_id == tid).order_by(Message.seq)
        )
    finally:
        db.close()


def _thread(tid):
    from backend.db import SessionLocal
    from backend.models import Thread

    db = SessionLocal()
    try:
        return db.get(Thread, tid)
    finally:
        db.close()


async def _turn(question, thread_id=None, threads=None):
    run = await chat_service.start_turn(question, thread_id)
    assert run is not None
    if threads is not None and run.thread_id not in threads:
        threads.append(run.thread_id)
    lines = await _collect(q.run_stream(run))
    return run, lines


async def test_turn_persists_user_and_assistant(monkeypatch, _threads):
    _install_stub_workflow(monkeypatch, StubLLM())
    question = "ZZTest how much did I spend this month?"
    run, lines = await _turn(question, threads=_threads)

    first = _payloads(lines)
    assert first[0]["type"] == "thread" and first[1]["type"] == "run"
    assert first[0]["thread_id"] == str(run.thread_id)
    assert lines[-1].strip() == "data: [DONE]"

    t = _thread(run.thread_id)
    assert t.title == chat_service.title_from(question)
    user, asst = _messages(run.thread_id)
    assert (user.seq, user.role, user.status, user.content) == (1, "user", "complete", question)
    assert (asst.seq, asst.role, asst.status, asst.content) == (2, "assistant", "complete", "Hello")
    assert str(asst.id) == first[0]["assistant_message_id"]
    assert str(user.id) == first[0]["user_message_id"]
    assert asst.parts["provider"]["model"] == "example-model:7b"
    assert asst.parts["steps"] == []


async def test_followup_replays_prior_pair(monkeypatch, _threads):
    llm = StubLLM()
    _install_stub_workflow(monkeypatch, llm)
    run, _ = await _turn("ZZTest first question", threads=_threads)
    before = _thread(run.thread_id).updated_at
    await _turn("ZZTest second question", run.thread_id)

    today = datetime.datetime.now().astimezone().date().isoformat()
    seen = llm.seen[-1]
    assert any(f"[{today}] ZZTest first question" in c for c in seen)
    assert any("Hello" in c for c in seen)
    assert _thread(run.thread_id).updated_at > before
    assert len(_messages(run.thread_id)) == 4


async def test_error_turn_persisted_and_not_replayed(monkeypatch, _threads):
    llm = StubLLM(mode="429")
    _install_stub_workflow(monkeypatch, llm)
    run, _ = await _turn("ZZTest fails with 429", threads=_threads)
    _, asst = _messages(run.thread_id)
    assert asst.status == "error" and asst.content == ""
    assert asst.parts["error"]["code"] == "rate_limit"

    llm.mode = "ok"
    await _turn("ZZTest next question", run.thread_id)
    joined = " ".join(llm.seen[-1])
    assert "ZZTest fails with 429" not in joined and "rate_limit" not in joined


async def test_stop_persists_cancelled_and_backfills_message_id(monkeypatch, _threads):
    _install_stub_workflow(monkeypatch, StubLLM(mode="tool_then_hang"))
    run = await chat_service.start_turn("ZZTest stop me")
    _threads.append(run.thread_id)
    stream = asyncio.create_task(_collect(q.run_stream(run)))
    while not run.proposal_ids:
        await asyncio.sleep(0.05)
    await q.stop_run(run)
    await asyncio.wait_for(stream, 10)

    _, asst = _messages(run.thread_id)
    assert asst.status == "cancelled" and asst.content == ""
    pid = asst.parts["proposals"][0]["id"]
    assert asst.parts["proposals"] == [{"id": pid, "operation": "add_transaction"}]
    assert _status_of(pid) == "rejected"
    assert _turn_id_of(pid) == uuid.UUID(run.id)
    from backend.db import SessionLocal
    from backend.models import Proposal

    db = SessionLocal()
    try:
        assert db.get(Proposal, uuid.UUID(pid)).message_id == asst.id
    finally:
        db.close()
    assert "token" not in json.dumps(asst.parts)


async def test_stop_racing_persist_stores_cancelled(monkeypatch, _threads):
    """WR-02: Stop flipping `stopped` after _persist_end read it still stores cancelled."""
    class FlipRun(q.Run):
        _reads = 0

        @property
        def stopped(self):  # False on the first read (status), True after (re-check)
            FlipRun._reads += 1
            return FlipRun._reads > 1

        @stopped.setter
        def stopped(self, v):
            pass

    _install_stub_workflow(monkeypatch, StubLLM(final_text="ZZTest answer"))
    run = await chat_service.start_turn("ZZTest race")
    _threads.append(run.thread_id)
    run.__class__ = FlipRun
    await _collect(q.run_stream(run))

    _, asst = _messages(run.thread_id)
    assert asst.status == "cancelled" and asst.content == ""


async def test_tool_turn_parts_have_no_token(monkeypatch, _threads):
    _install_stub_workflow(monkeypatch, StubLLM(mode="tool", final_text="Done"))
    run, lines = await _turn("ZZTest tool turn", threads=_threads)
    answer = _of_type(_payloads(lines), "answer")[0]
    _, asst = _messages(run.thread_id)
    assert asst.status == "complete"
    assert asst.parts["steps"] == [{"tool": "seed_proposal", "args": {}}]
    assert "token" not in json.dumps(asst.parts)
    assert answer["proposals"][0]["token"] not in json.dumps(asst.parts)
    pid = asst.parts["proposals"][0]["id"]
    from backend.db import SessionLocal
    from backend.models import Proposal

    db = SessionLocal()
    try:
        assert db.get(Proposal, uuid.UUID(pid)).message_id == asst.id
    finally:
        db.close()


async def test_start_turn_busy_persists_nothing(monkeypatch, _threads):
    _install_stub_workflow(monkeypatch, StubLLM(mode="hang"))
    run = await chat_service.start_turn("ZZTest busy one")
    _threads.append(run.thread_id)
    assert await chat_service.start_turn("ZZTest busy two", run.thread_id) is None
    assert len(_messages(run.thread_id)) == 1  # only the first user message
    await q.stop_run(run)
    await run.pump


async def test_start_turn_unknown_thread():
    tid = uuid.uuid4()
    with pytest.raises(LookupError):
        await chat_service.start_turn("ZZTest nowhere", tid)
    assert str(tid) not in q._ACTIVE and str(tid) not in q._LAST
