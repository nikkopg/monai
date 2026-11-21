"""GET /proposals carries a chat proposal's thread and request (261121-m17).

A proposal whose message_id points at an assistant message gets `thread_id`
(that message's thread) and `request` (the closest earlier user message in the
thread, cut to 200 characters). A proposal with no message gets None for both.
Synthetic data only; everything created here is deleted afterwards.
"""

import datetime
import secrets
import uuid

import pytest
from sqlalchemy import text


@pytest.fixture()
def chat_proposal(authed):
    from backend.db import SessionLocal
    from backend.models import Message, Proposal, Thread

    db = SessionLocal()
    made: dict[str, uuid.UUID] = {}
    try:
        t = Thread(title="ZZTest provenance")
        db.add(t)
        db.flush()
        db.add(Message(thread_id=t.id, seq=1, role="user", content="ZZ older question", parts={}))
        db.add(Message(thread_id=t.id, seq=2, role="assistant", content="ZZ older answer", parts={}))
        long_ask = "ZZ add coffee 25000 to Cash " + "x" * 300
        db.add(Message(thread_id=t.id, seq=3, role="user", content=long_ask, parts={}))
        answer = Message(thread_id=t.id, seq=4, role="assistant", content="ZZ proposed", parts={})
        db.add(answer)
        db.flush()
        now = datetime.datetime.now(datetime.timezone.utc)

        def mk(message_id):
            p = Proposal(
                token=secrets.token_urlsafe(32), operation="add_transaction",
                payload={"operation": "add_transaction", "rows": []}, status="pending",
                channel="chat", expires_at=now + datetime.timedelta(minutes=15), message_id=message_id,
            )
            db.add(p)
            db.flush()
            return p.id

        made = {"thread": t.id, "linked": mk(answer.id), "bare": mk(None)}
        db.commit()
        yield {**made, "long_ask": long_ask}
    finally:
        db.rollback()
        for key in ("linked", "bare"):
            if key in made:
                db.execute(text("DELETE FROM proposals WHERE id = :i"), {"i": made[key]})
        if "thread" in made:
            db.execute(text("DELETE FROM messages WHERE thread_id = :i"), {"i": made["thread"]})
            db.execute(text("DELETE FROM threads WHERE id = :i"), {"i": made["thread"]})
        db.commit()
        db.close()


def test_chat_proposal_carries_thread_and_request(client, chat_proposal):
    r = client.get("/proposals?status=pending")
    assert r.status_code == 200
    by_id = {p["id"]: p for p in r.json()}
    linked = by_id[str(chat_proposal["linked"])]
    assert linked["thread_id"] == str(chat_proposal["thread"])
    # The closest earlier user message, not the older one, cut to 200 characters.
    assert linked["request"] == chat_proposal["long_ask"][:200]
    bare = by_id[str(chat_proposal["bare"])]
    assert bare["thread_id"] is None and bare["request"] is None
