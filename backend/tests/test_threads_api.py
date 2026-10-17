"""
HTTP semantics of the thread routes (Phase 36 plan 06).

Auth is covered in test_auth.py; the same-thread POST 409 in
test_chat_reliability.py. All values are synthetic; DB is monai_test.
"""

import json
import uuid

import pytest
from sqlalchemy import text

import backend.query as q
from backend.db import SessionLocal
from backend.models import Message, Thread
from backend.tests.chat_stubs import _seed_proposal, purge_seeded


@pytest.fixture()
def env(client, api_key, monkeypatch):
    """Fresh registries, a stubbed agent, and the auth header."""
    monkeypatch.setattr(q, "_ACTIVE", {})
    monkeypatch.setattr(q, "_LAST", {})

    async def _stub(question, **kw):
        yield "data: " + json.dumps({"type": "answer", "text": "stub answer", "trace": [],
                                     "proposals": []}) + "\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(q, "agent_stream", _stub)
    created: list = []
    yield client, {"MONAI_API_KEY": api_key}, created
    db = SessionLocal()
    for t in created:
        db.execute(text("DELETE FROM threads WHERE id = :i"), {"i": t})
    db.commit()
    db.close()
    purge_seeded()


def _mk(created, title="ZZTest thread") -> uuid.UUID:
    db = SessionLocal()
    t = Thread(title=title)
    db.add(t)
    db.commit()
    tid = t.id
    db.close()
    created.append(tid)
    return tid


def _events(text_: str) -> list:
    out = []
    for block in text_.split("\n\n"):
        if block.startswith("data: ") and block != "data: [DONE]":
            out.append(json.loads(block[6:]))
    return out


def test_new_thread_events_and_detail(env):
    client, h, created = env
    r = client.post("/query-stream", json={"question": "ZZTest hello"}, headers=h)
    assert r.status_code == 200
    ev = _events(r.text)
    assert [e["type"] for e in ev[:2]] == ["thread", "run"]
    tid = ev[0]["thread_id"]
    created.append(uuid.UUID(tid))
    d = client.get(f"/threads/{tid}", headers=h).json()
    assert d["active_run"] is None
    assert [(m["seq"], m["role"]) for m in d["messages"]] == [(1, "user"), (2, "assistant")]
    assert d["messages"][0]["content"] == "ZZTest hello"


def test_query_stream_unknown_thread_404(env):
    client, h, _ = env
    r = client.post("/query-stream", json={"question": "q", "thread_id": str(uuid.uuid4())}, headers=h)
    assert r.status_code == 404
    assert q._ACTIVE == {}


def test_list_threads_shape(env):
    client, h, created = env
    _mk(created, "ZZTest listed")
    rows = client.get("/threads", headers=h).json()
    assert rows and set(rows[0]) == {"id", "title", "updated_at"}
    stamps = [r["updated_at"] for r in rows]
    assert stamps == sorted(stamps, reverse=True)


def test_get_thread_404_and_422(env):
    client, h, _ = env
    assert client.get(f"/threads/{uuid.uuid4()}", headers=h).status_code == 404
    assert client.get("/threads/not-a-uuid", headers=h).status_code == 422


def test_get_thread_no_token(env):
    client, h, created = env
    tid = _mk(created)
    pid, token = _seed_proposal()
    db = SessionLocal()
    db.add(Message(thread_id=tid, seq=1, role="assistant", content="a",
                   parts={"proposals": [{"id": pid, "operation": "add_transaction"}]}))
    db.commit()
    db.close()
    r = client.get(f"/threads/{tid}", headers=h)
    assert r.status_code == 200
    p = r.json()["messages"][0]["parts"]["proposals"][0]
    assert p["status"] == "pending" and p["payload"]
    assert token not in r.text
    assert "token" not in p and "code" not in p
    assert '"token"' not in r.text and '"code"' not in r.text


def test_get_thread_active_run(env):
    client, h, created = env
    tid = _mk(created)
    run = q.start_run(str(tid))
    assert client.get(f"/threads/{tid}", headers=h).json()["active_run"] == {"run_id": run.id}


def test_get_thread_reads_active_run_before_detail(env, monkeypatch):
    """WR-08: a run that ends while the detail loads is still reported as active."""
    import backend.main as main

    client, h, created = env
    tid = _mk(created)
    run = q.start_run(str(tid))
    real = main._thread_detail_sync

    def finishing(thread_id):
        q.release_run(run)  # the pump finishes while the detail is being read
        return real(thread_id)

    monkeypatch.setattr(main, "_thread_detail_sync", finishing)
    assert client.get(f"/threads/{tid}", headers=h).json()["active_run"] == {"run_id": run.id}


def test_patch_thread(env):
    client, h, created = env
    tid = _mk(created)
    r = client.patch(f"/threads/{tid}", json={"title": "  ZZTest renamed  "}, headers=h)
    assert r.status_code == 200 and r.json()["title"] == "ZZTest renamed"
    for bad in ("", "   ", "x" * 201):
        assert client.patch(f"/threads/{tid}", json={"title": bad}, headers=h).status_code == 422
    assert client.patch(f"/threads/{uuid.uuid4()}", json={"title": "ZZTest x"}, headers=h).status_code == 404


def test_409_delete_while_running(env):
    client, h, created = env
    tid = _mk(created)
    q.start_run(str(tid))
    assert client.delete(f"/threads/{tid}", headers=h).status_code == 409
    q._ACTIVE.clear()
    assert client.delete(f"/threads/{tid}", headers=h).status_code == 204
    assert client.get(f"/threads/{tid}", headers=h).status_code == 404
    assert client.delete(f"/threads/{tid}", headers=h).status_code == 404


def test_delete_purges_last_run_buffer(env):
    """WR-07: a deleted thread's finished run is no longer replayable or stoppable."""
    client, h, created = env
    tid = _mk(created)
    run = q.Run(key=str(tid))
    q.push(run, q._sse({"type": "answer", "text": "ZZTest private", "trace": [], "proposals": []}))
    q.push(run, q._DONE)
    run.done = True
    q._LAST[str(tid)] = run
    assert client.delete(f"/threads/{tid}", headers=h).status_code == 204
    assert str(tid) not in q._LAST and q.find_run(run.id) is None
    assert client.get(f"/threads/{tid}/stream", headers=h).status_code == 204


def test_delete_keeps_proposal_row(env):
    client, h, created = env
    tid = _mk(created)
    pid, _ = _seed_proposal()
    db = SessionLocal()
    db.add(Message(thread_id=tid, seq=1, role="assistant", content="a",
                   parts={"proposals": [{"id": pid, "operation": "add_transaction"}]}))
    db.commit()
    db.execute(text("UPDATE proposals SET message_id = (SELECT id FROM messages WHERE thread_id = :t) WHERE id = :p"),
               {"t": tid, "p": pid})
    db.commit()
    assert client.delete(f"/threads/{tid}", headers=h).status_code == 204
    row = db.execute(text("SELECT message_id FROM proposals WHERE id = :p"), {"p": pid}).one()
    db.close()
    assert row[0] is None


def test_thread_stream_204_without_run(env):
    client, h, created = env
    tid = _mk(created)
    assert client.get(f"/threads/{tid}/stream", headers=h).status_code == 204


def test_thread_stream_replay_redacts_token(env):
    client, h, created = env
    tid = _mk(created)
    run = q.Run(key=str(tid))
    secret = "synthetic-secret-token-value"
    q.push(run, q._sse({"type": "answer", "text": "ok", "trace": [],
                        "proposals": [{"id": "p1", "token": secret}], "proposal_token": secret}))
    q.push(run, q._DONE)
    run.done = True
    q._LAST[str(tid)] = run
    r = client.get(f"/threads/{tid}/stream", headers=h)
    assert r.status_code == 200
    assert r.text.rstrip().endswith("[DONE]")
    assert secret not in r.text


def test_late_stop_flips_persisted_answer(env):
    client, h, created = env
    r = client.post("/query-stream", json={"question": "ZZTest late stop"}, headers=h)
    ev = _events(r.text)
    tid = ev[0]["thread_id"]
    created.append(uuid.UUID(tid))
    run_id = ev[1]["run_id"]
    assert client.get(f"/threads/{tid}", headers=h).json()["messages"][1]["status"] == "complete"
    assert client.post(f"/query-stream/{run_id}/cancel", headers=h).status_code == 200
    m = client.get(f"/threads/{tid}", headers=h).json()["messages"][1]
    assert m["status"] == "cancelled" and m["content"] == ""


# ---------------------------------------------------------------------------
# /compact and /clear (Phase 38 plan 06)
# ---------------------------------------------------------------------------


class _Summariser:
    def __init__(self, exc=None, delay=0.0):
        self.exc, self.delay, self.calls = exc, delay, 0

    async def achat(self, messages, **kw):
        import asyncio

        from llama_index.core.llms import ChatMessage, ChatResponse

        self.calls += 1
        await asyncio.sleep(self.delay)
        if self.exc:
            raise self.exc
        return ChatResponse(message=ChatMessage(role="assistant", content="ZZ route summary"))


def _mk_pairs(created, pairs=2, last_status="complete"):
    tid = _mk(created)
    db = SessionLocal()
    for i in range(pairs):
        db.add(Message(thread_id=tid, seq=2 * i + 1, role="user", content=f"ZZ q{i}", parts={}))
        db.add(Message(thread_id=tid, seq=2 * i + 2, role="assistant", content=f"ZZ a{i}",
                       status=last_status if i == pairs - 1 else "complete", parts={}))
    db.commit()
    db.close()
    return tid


def _cols(tid):
    db = SessionLocal()
    t = db.get(Thread, tid)
    out = (t.summary, t.summary_upto_seq)
    db.close()
    return out


@pytest.mark.parametrize("action", ["compact", "clear"])
def test_compact_clear_422_and_404(env, action):
    client, h, _ = env
    assert client.post(f"/threads/not-a-uuid/{action}", headers=h).status_code == 422
    assert client.post(f"/threads/{uuid.uuid4()}/{action}", headers=h).status_code == 404


@pytest.mark.parametrize("action", ["compact", "clear"])
def test_compact_clear_409_when_busy(env, monkeypatch, action):
    from backend import chat_service

    client, h, created = env
    monkeypatch.setattr(chat_service, "_COMPACTING", set())
    tid = _mk_pairs(created)
    q._ACTIVE[str(tid)] = q.Run(key=str(tid))
    assert client.post(f"/threads/{tid}/{action}", headers=h).status_code == 409
    q._ACTIVE.clear()
    chat_service._COMPACTING.add(str(tid))
    try:
        assert client.post(f"/threads/{tid}/{action}", headers=h).status_code == 409
    finally:
        chat_service._COMPACTING.discard(str(tid))


def test_compact_success_returns_flags_only(env, monkeypatch):
    client, h, created = env
    monkeypatch.setattr(q, "_get_llm", lambda: _Summariser())
    tid = _mk_pairs(created)
    r = client.post(f"/threads/{tid}/compact", headers=h)
    assert r.status_code == 200
    assert r.json() == {"summary_upto_seq": 4, "has_summary": True, "compacted": True}
    assert "ZZ route summary" not in r.text
    d = client.get(f"/threads/{tid}", headers=h)
    assert "ZZ route summary" not in d.text
    assert d.json()["has_summary"] is True and d.json()["summary_upto_seq"] == 4
    assert _cols(tid) == ("ZZ route summary", 4)


def test_compact_nothing_to_fold(env, monkeypatch):
    client, h, created = env
    stub = _Summariser()
    monkeypatch.setattr(q, "_get_llm", lambda: stub)
    tid = _mk_pairs(created, pairs=1, last_status="error")
    r = client.post(f"/threads/{tid}/compact", headers=h)
    assert r.status_code == 200 and r.json()["compacted"] is False
    assert stub.calls == 0


def test_compact_provider_failure_is_503(env, monkeypatch):
    from backend.tests.chat_stubs import Err429

    client, h, created = env
    monkeypatch.setattr(q, "_get_llm", lambda: _Summariser(exc=Err429("synthetic secret")))
    tid = _mk_pairs(created)
    r = client.post(f"/threads/{tid}/compact", headers=h)
    assert r.status_code == 503
    assert r.json()["detail"] == "Couldn't compact this chat right now. Try again later."
    assert _cols(tid) == (None, 0)


def test_compact_timeout_is_503(env, monkeypatch):
    import backend.main as main

    client, h, created = env
    monkeypatch.setattr(main, "COMPACT_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(q, "_get_llm", lambda: _Summariser(delay=1.0))
    tid = _mk_pairs(created)
    r = client.post(f"/threads/{tid}/compact", headers=h)
    assert r.status_code == 503
    assert r.json()["detail"] == "Couldn't compact this chat right now. Try again later."
    assert _cols(tid) == (None, 0)


def test_clear_keeps_messages(env):
    client, h, created = env
    tid = _mk_pairs(created)
    db = SessionLocal()
    t = db.get(Thread, tid)
    t.summary, t.summary_upto_seq = "ZZ route summary", 2
    db.commit()
    db.close()
    r = client.post(f"/threads/{tid}/clear", headers=h)
    assert r.status_code == 200
    assert r.json() == {"summary_upto_seq": 4, "has_summary": False}
    d = client.get(f"/threads/{tid}", headers=h).json()
    assert len(d["messages"]) == 4 and d["has_summary"] is False and d["summary_upto_seq"] == 4
