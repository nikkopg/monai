"""Phase 31 approval-path tests (APPR-01, APPR-02, APPR-05) against monai_test.

Synthetic values only. Every seeded row is deleted in a finally/teardown. Never
assert that a leftover row from another test is still pending: any
GET /proposals bulk-expires stale rows.
"""
import datetime
import types
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text


@pytest.fixture(scope="module")
def db_available():
    from backend.db import engine
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception as e:
        pytest.skip(f"Postgres not available: {e}")
    return True


@pytest.fixture()
def db_session(db_available):
    from backend.db import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


_PAYLOAD = {"operation": "add_transaction", "rows": []}


def _count(db) -> int:
    return db.execute(text("SELECT count(*) FROM proposals")).scalar()


def _make_and_check(db, channel, ttl):
    from backend.models import Proposal
    from backend.tools import _make_proposal

    pid, _token = (
        _make_proposal("add_transaction", _PAYLOAD)
        if channel is None
        else _make_proposal("add_transaction", _PAYLOAD, channel=channel)
    )
    try:
        row = db.get(Proposal, uuid.UUID(pid))
        assert row.channel == (channel or "chat")
        assert row.status == "pending"
        assert row.failed_attempts == 0
        assert row.code is None
        assert abs((row.expires_at - row.created_at) - ttl) < timedelta(seconds=60)
    finally:
        db.rollback()
        db.execute(text("DELETE FROM proposals WHERE id = :i"), {"i": pid})
        db.commit()


def test_ttl_for_table():
    from backend.proposals import ttl_for

    assert ttl_for("chat") == timedelta(minutes=15)
    assert ttl_for("mcp") == timedelta(hours=48)
    for ch in ("discord", "upload"):
        with pytest.raises(ValueError):
            ttl_for(ch)


def test_ttl_make_proposal_chat_default(db_session):
    _make_and_check(db_session, None, timedelta(minutes=15))


def test_ttl_make_proposal_mcp(db_session):
    _make_and_check(db_session, "mcp", timedelta(hours=48))


def test_ttl_make_proposal_unknown_channel_raises(db_session):
    from backend.tools import _make_proposal

    before = _count(db_session)
    with pytest.raises(ValueError):
        _make_proposal("add_transaction", _PAYLOAD, channel="discord")
    db_session.rollback()
    assert _count(db_session) == before


def _fake(status="pending"):
    return types.SimpleNamespace(status=status, status_changed_at=None, confirmed_at=None)


def test_transition_confirmed_stamps_both_times():
    from backend.proposals import transition

    p = _fake()
    transition(p, "confirmed")
    assert p.status == "confirmed"
    assert p.status_changed_at is not None and p.status_changed_at.tzinfo is not None
    assert p.confirmed_at == p.status_changed_at


def test_transition_rejected_keeps_confirmed_at_none():
    from backend.proposals import transition

    p = _fake()
    transition(p, "rejected")
    assert p.status == "rejected"
    assert p.status_changed_at is not None
    assert p.confirmed_at is None


def test_transition_refuses_non_pending_and_unknown_target():
    from backend.proposals import transition

    for st in ("confirmed", "rejected", "expired"):
        with pytest.raises(ValueError, match=f"Proposal already {st}"):
            transition(_fake(st), "rejected")
    for bad in ("locked", "pending"):
        p = _fake()
        with pytest.raises(ValueError):
            transition(p, bad)
        assert p.status == "pending"
