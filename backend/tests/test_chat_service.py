"""
Thread service tests (Phase 36 plan 05): title rule and thread data helpers.

All values are synthetic. The DB is the isolated monai_test database.
"""

from backend import chat_service


def test_title_from():
    assert chat_service.title_from("  How much   did I\nspend this month?  ") == "How much did I spend this month?"
    assert chat_service.title_from("") == ""
    long_q = "ZZTest " + " ".join(["spending"] * 11)  # 90 chars
    assert len(long_q) > 60
    t = chat_service.title_from(long_q)
    assert t.endswith("…") and len(t) <= 61
    assert long_q.startswith(t[:-1]) and long_q[len(t) - 1] == " "  # word boundary
    one = "Z" * 80
    assert chat_service.title_from(one) == "Z" * 60 + "…"


# ---------------------------------------------------------------------------
# Thread data helpers
# ---------------------------------------------------------------------------

import datetime
import json
import uuid

import pytest
from sqlalchemy import text

from backend.db import SessionLocal
from backend.models import Message, Proposal, Thread
from backend.tests.chat_stubs import _seed_proposal, purge_seeded


@pytest.fixture()
def db():
    s = SessionLocal()
    created: list = []
    s.created = created  # thread ids to delete in teardown
    yield s
    s.rollback()
    for t in created:
        s.execute(text("DELETE FROM threads WHERE id = :i"), {"i": t})
    s.commit()
    s.close()
    purge_seeded()


def _mk_thread(db, title="ZZTest thread", updated=None) -> Thread:
    t = Thread(title=title)
    db.add(t)
    db.flush()
    if updated is not None:
        db.execute(text("UPDATE threads SET updated_at = :u WHERE id = :i"), {"u": updated, "i": t.id})
    db.commit()
    db.created.append(t.id)
    return t


def _walk_keys(o):
    if isinstance(o, dict):
        for k, v in o.items():
            yield k
            yield from _walk_keys(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk_keys(v)


def test_list_threads_shape_and_order(db):
    now = datetime.datetime.now(datetime.timezone.utc)
    old = _mk_thread(db, "ZZTest old", now - datetime.timedelta(days=2))
    new = _mk_thread(db, "ZZTest new", now + datetime.timedelta(days=1))
    rows = chat_service.list_threads(db, limit=2000)
    assert set(rows[0]) == {"id", "title", "updated_at"}
    ids = [r["id"] for r in rows]
    assert ids.index(new.id) < ids.index(old.id)


def test_list_threads_limit(db):
    _mk_thread(db, "ZZTest a")
    _mk_thread(db, "ZZTest b")
    assert len(chat_service.list_threads(db, limit=1)) == 1


def test_thread_detail_live_proposal_status_and_no_token(db):
    t = _mk_thread(db)
    pid_pending, tok1 = _seed_proposal()
    pid_old, tok2 = _seed_proposal()
    db.execute(
        text("UPDATE proposals SET expires_at = now() - interval '1 hour' WHERE id = :i"),
        {"i": pid_old},
    )
    missing = str(uuid.uuid4())
    parts = {
        "steps": [],
        "proposals": [
            {"id": pid_pending, "operation": "add_transaction"},
            {"id": pid_old, "operation": "add_transaction"},
            {"id": missing, "operation": "add_transaction"},
        ],
    }
    db.add(Message(thread_id=t.id, seq=1, role="user", content="ZZTest q", parts={}))
    db.add(Message(thread_id=t.id, seq=2, role="assistant", content="a", parts=parts))
    db.commit()

    d = chat_service.thread_detail(db, t.id)
    assert [m["seq"] for m in d["messages"]] == [1, 2]
    got = {p["id"]: p for p in d["messages"][1]["parts"]["proposals"]}
    assert got[pid_pending]["status"] == "pending" and got[pid_pending]["payload"]
    assert got[pid_pending]["expires_at"] is not None
    assert got[pid_old]["status"] == "expired"
    assert got[missing]["status"] == "missing"
    assert got[missing]["payload"] is None and got[missing]["expires_at"] is None
    keys = set(_walk_keys(d))
    assert "token" not in keys and "code" not in keys
    blob = json.dumps(d, default=str)
    assert tok1 not in blob and tok2 not in blob
    assert chat_service.thread_detail(db, uuid.uuid4()) is None


def test_rename_thread(db):
    t = _mk_thread(db)
    assert chat_service.rename_thread(db, t.id, "  ZZTest renamed  ")["title"] == "ZZTest renamed"
    for bad in ("", "   ", "x" * 201):
        with pytest.raises(ValueError):
            chat_service.rename_thread(db, t.id, bad)
    assert chat_service.rename_thread(db, t.id, "y" * 200)["title"] == "y" * 200
    assert chat_service.rename_thread(db, uuid.uuid4(), "ZZTest nope") is None


def test_delete_thread_cascades_and_keeps_proposal(db):
    t = _mk_thread(db)
    pid, _ = _seed_proposal()
    m = Message(thread_id=t.id, seq=1, role="assistant", content="a", parts={})
    db.add(m)
    db.flush()
    db.execute(
        text("UPDATE proposals SET message_id = :m WHERE id = :p"), {"m": m.id, "p": pid}
    )
    db.commit()
    assert chat_service.delete_thread(db, t.id) is True
    assert db.get(Thread, t.id) is None
    assert db.query(Message).filter(Message.thread_id == t.id).count() == 0
    db.expire_all()
    assert db.get(Proposal, uuid.UUID(pid)).message_id is None
    assert chat_service.delete_thread(db, t.id) is False


def test_mark_cancelled(db):
    t = _mk_thread(db)
    done = Message(thread_id=t.id, seq=1, role="assistant", content="answer", parts={})
    err = Message(thread_id=t.id, seq=2, role="assistant", content="", status="error", parts={})
    db.add_all([done, err])
    db.commit()
    assert chat_service.mark_cancelled(done.id) is True
    assert chat_service.mark_cancelled(done.id) is False
    assert chat_service.mark_cancelled(err.id) is False
    db.expire_all()
    assert (db.get(Message, done.id).status, db.get(Message, done.id).content) == ("cancelled", "")
    assert db.get(Message, err.id).status == "error"
