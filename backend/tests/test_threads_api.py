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
