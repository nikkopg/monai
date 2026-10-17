"""
Phase 37 D-18/D-19: replace-and-truncate (regenerate and edit-and-resend).

Service level: chat_service.start_turn(..., replace_from) locks the proposals
linked to the doomed messages, refuses once one was applied, supersedes the
pending chat ones with an audit row, deletes the old branch and inserts the new
question in one transaction. HTTP level: POST /query-stream maps the outcomes
to 422 / 409.

All values are synthetic. The DB is the isolated monai_test database.
"""

import json
import uuid

import pytest
from sqlalchemy import text

from backend import chat_service
from backend import query as q
from backend.db import SessionLocal
from backend.models import Message, Thread
from backend.tests.chat_stubs import (
    StubLLM,
    _collect,
    _install_stub_workflow,
    _payloads,
    _seed_proposal,
    purge_seeded,
)

Q1, Q2 = "ZZ37 first question", "ZZ37 second question"


@pytest.fixture(autouse=True)
def _clean():
    q._ACTIVE.clear()
    q._LAST.clear()
    yield
    q._ACTIVE.clear()
    q._LAST.clear()
    purge_seeded()


@pytest.fixture()
def threads():
    ids: list = []
    yield ids
    db = SessionLocal()
    try:
        for t in ids:
            db.execute(text("DELETE FROM audit_log WHERE after->>'thread_id' = :t"), {"t": str(t)})
            db.execute(text("DELETE FROM threads WHERE id = :i"), {"i": t})
        db.commit()
    finally:
        db.close()


def _mk_thread(threads, turns, *, last_status="complete", pids=()):
    """Thread with (question, answer) pairs; pids are listed on the LAST assistant's
    parts.proposals. Returns (tid, [message ids in seq order])."""
    db = SessionLocal()
    try:
        t = Thread(title="ZZ37 thread")
        db.add(t)
        db.flush()
        mids, seq = [], 0
        for i, (qu, an) in enumerate(turns):
            last = i == len(turns) - 1
            seq += 1
            u = Message(thread_id=t.id, seq=seq, role="user", content=qu, status="complete", parts={})
            seq += 1
            parts = {"steps": []}
            if last and pids:
                parts["proposals"] = [{"id": p, "operation": "add_transaction"} for p in pids]
            a = Message(
                thread_id=t.id, seq=seq, role="assistant", content=an,
                status=last_status if last else "complete", parts=parts,
            )
            db.add_all([u, a])
            db.flush()
            mids += [u.id, a.id]
        db.commit()
        threads.append(t.id)
        return t.id, mids
    finally:
        db.close()


def _set(pid: str, **cols) -> None:
    db = SessionLocal()
    try:
        sets = ", ".join(f"{k} = :{k}" for k in cols)
        db.execute(text(f"UPDATE proposals SET {sets} WHERE id = :i"), {**cols, "i": uuid.UUID(pid)})
        db.commit()
    finally:
        db.close()


def _prop(pid: str):
    db = SessionLocal()
    try:
        from backend.models import Proposal

        p = db.get(Proposal, uuid.UUID(pid))
        return p.status, p.message_id
    finally:
        db.close()


def _msgs(tid):
    db = SessionLocal()
    try:
        return [(m.id, m.seq, m.role, m.status, m.content)
                for m in db.query(Message).filter(Message.thread_id == tid).order_by(Message.seq)]
    finally:
        db.close()


def _audit(tid):
    db = SessionLocal()
    try:
        rows = db.execute(
            text("SELECT operation, before, after FROM audit_log WHERE after->>'thread_id' = :t"),
            {"t": str(tid)},
        ).all()
        return [(r.operation, r.before, r.after) for r in rows]
    finally:
        db.close()


async def _replace(question, tid, mid):
    run = await chat_service.start_turn(question, tid, replace_from=mid)
    assert run is not None
    return run, await _collect(q.run_stream(run))


async def test_regenerate_supersedes_pending_and_truncates(monkeypatch, threads):
    llm = StubLLM()
    _install_stub_workflow(monkeypatch, llm)
    p1, _ = _seed_proposal()
    p2, _ = _seed_proposal()
    tid, old = _mk_thread(threads, [(Q1, "old answer")], pids=[p1])
    _set(p2, message_id=old[1])

    run, lines = await _replace(Q1, tid, old[0])

    assert _prop(p1) == ("superseded", None)
    assert _prop(p2) == ("superseded", None)
    audit = _audit(tid)
    assert sorted(a[0] for a in audit) == ["superseded", "superseded"]
    assert {a[2]["reason"] for a in audit} == {"regenerated"}
    assert {a[1]["proposal_id"] for a in audit} == {p1, p2}
    msgs = _msgs(tid)
    assert [(m[1], m[2], m[4]) for m in msgs] == [(1, "user", Q1), (2, "assistant", "Hello")]
    assert not {m[0] for m in msgs} & set(old)
    assert _payloads(lines)[0]["user_message_id"] == str(msgs[0][0])


async def test_edit_from_first_turn_drops_all_old_history(monkeypatch, threads):
    llm = StubLLM()
    _install_stub_workflow(monkeypatch, llm)
    p1, _ = _seed_proposal()
    tid, old = _mk_thread(threads, [(Q1, "answer one"), (Q2, "answer two")], pids=[p1])

    await _replace("ZZ37 reworded", tid, old[0])

    msgs = _msgs(tid)
    assert [(m[1], m[4]) for m in msgs] == [(1, "ZZ37 reworded"), (2, "Hello")]
    assert not {m[0] for m in msgs} & set(old)
    assert _audit(tid)[0][2]["reason"] == "edited"
    replayed = " ".join(llm.seen[0])
    assert Q1 not in replayed and Q2 not in replayed and "answer one" not in replayed


async def test_edit_from_second_turn_keeps_first(monkeypatch, threads):
    _install_stub_workflow(monkeypatch, StubLLM())
    tid, old = _mk_thread(threads, [(Q1, "answer one"), (Q2, "answer two")])

    await _replace("ZZ37 reworded", tid, old[2])

    msgs = _msgs(tid)
    assert [m[0] for m in msgs[:2]] == old[:2]
    assert [(m[1], m[4]) for m in msgs[2:]] == [(3, "ZZ37 reworded"), (4, "Hello")]


async def test_confirmed_proposal_refuses_and_changes_nothing(monkeypatch, threads):
    _install_stub_workflow(monkeypatch, StubLLM())
    p1, _ = _seed_proposal()
    p2, _ = _seed_proposal()
    tid, old = _mk_thread(threads, [(Q1, "old answer")], pids=[p1, p2])
    _set(p1, status="confirmed")
    before = _msgs(tid)

    with pytest.raises(chat_service.ReplaceConflict):
        await chat_service.start_turn(Q1, tid, replace_from=old[0])

    assert _msgs(tid) == before
    assert _prop(p1)[0] == "confirmed" and _prop(p2)[0] == "pending"
    assert _audit(tid) == []
    assert q._ACTIVE == {}


async def test_active_run_returns_none_and_changes_nothing(monkeypatch, threads):
    _install_stub_workflow(monkeypatch, StubLLM())
    p1, _ = _seed_proposal()
    tid, old = _mk_thread(threads, [(Q1, "old answer")], pids=[p1])
    before = _msgs(tid)
    held = q.start_run(str(tid))

    assert await chat_service.start_turn(Q1, tid, replace_from=old[0]) is None

    q.release_run(held)
    assert _msgs(tid) == before and _prop(p1)[0] == "pending"


async def test_replace_without_thread_id_is_value_error(monkeypatch):
    _install_stub_workflow(monkeypatch, StubLLM())
    with pytest.raises(ValueError):
        await chat_service.start_turn(Q1, None, replace_from=uuid.uuid4())
    assert q._ACTIVE == {}


async def test_unknown_message_is_value_error(monkeypatch, threads):
    _install_stub_workflow(monkeypatch, StubLLM())
    tid, _ = _mk_thread(threads, [(Q1, "a")])
    before = _msgs(tid)
    with pytest.raises(ValueError):
        await chat_service.start_turn(Q1, tid, replace_from=uuid.uuid4())
    assert _msgs(tid) == before and q._ACTIVE == {}


async def test_message_of_another_thread_is_value_error(monkeypatch, threads):
    _install_stub_workflow(monkeypatch, StubLLM())
    tid, _ = _mk_thread(threads, [(Q1, "a")])
    other, other_msgs = _mk_thread(threads, [(Q2, "b")])
    before = _msgs(other)
    with pytest.raises(ValueError):
        await chat_service.start_turn(Q1, tid, replace_from=other_msgs[0])
    assert _msgs(other) == before


async def test_assistant_message_is_value_error(monkeypatch, threads):
    _install_stub_workflow(monkeypatch, StubLLM())
    tid, old = _mk_thread(threads, [(Q1, "a")])
    before = _msgs(tid)
    with pytest.raises(ValueError):
        await chat_service.start_turn(Q1, tid, replace_from=old[1])
    assert _msgs(tid) == before


async def test_regenerate_failed_turn_leaves_one_pair(monkeypatch, threads):
    _install_stub_workflow(monkeypatch, StubLLM())
    tid, old = _mk_thread(threads, [(Q1, "")], last_status="error")

    await _replace(Q1, tid, old[0])

    msgs = _msgs(tid)
    assert [(m[1], m[2], m[3]) for m in msgs] == [(1, "user", "complete"), (2, "assistant", "complete")]


async def test_mcp_pending_proposal_is_left_pending(monkeypatch, threads):
    _install_stub_workflow(monkeypatch, StubLLM())
    p1, _ = _seed_proposal(channel="mcp")
    tid, old = _mk_thread(threads, [(Q1, "old answer")], pids=[p1])

    await _replace(Q1, tid, old[0])

    assert _prop(p1)[0] == "pending"
    assert _audit(tid) == []
