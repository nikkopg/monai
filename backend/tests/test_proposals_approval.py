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


# ---------------------------------------------------------------------------
# Approver key dependencies (APPR-01, D-15)
# ---------------------------------------------------------------------------

def _set_keys(monkeypatch, api, approver):
    import backend.auth as auth

    monkeypatch.setattr(auth, "_CONFIGURED_KEY", api)
    monkeypatch.setattr(auth, "_CONFIGURED_APPROVER_KEY", approver, raising=False)
    return auth


def test_approver_auth_key_ok_matrix(monkeypatch):
    auth = _set_keys(monkeypatch, "api-x", "appr-y")
    assert auth.approver_key_ok("appr-y") is True
    for bad in ("api-x", None, ""):
        assert auth.approver_key_ok(bad) is False
    auth = _set_keys(monkeypatch, "api-x", "api-x")
    for v in ("api-x", None, "", "appr-y"):
        assert auth.approver_key_ok(v) is False
    auth = _set_keys(monkeypatch, "api-x", "")
    for v in ("api-x", None, "", "appr-y"):
        assert auth.approver_key_ok(v) is False


def test_approver_auth_require_dependency(monkeypatch):
    from fastapi import HTTPException

    auth = _set_keys(monkeypatch, "api-x", "")
    with pytest.raises(HTTPException) as e:
        auth.require_approver_key("anything")
    assert e.value.status_code == 503
    auth = _set_keys(monkeypatch, "api-x", "api-x")
    with pytest.raises(HTTPException) as e:
        auth.require_approver_key("api-x")
    assert e.value.status_code == 503
    assert "api-x" not in e.value.detail
    auth = _set_keys(monkeypatch, "api-x", "appr-y")
    for bad in (None, "wrong"):
        with pytest.raises(HTTPException) as e:
            auth.require_approver_key(bad)
        assert e.value.status_code == 401
        assert e.value.detail == "Invalid or missing approver key"
        assert "appr-y" not in e.value.detail and "api-x" not in e.value.detail
    assert auth.require_approver_key("appr-y") is None
    assert auth.optional_approver("appr-y") is True
    assert auth.optional_approver("nope") is False
    assert auth.optional_approver(None) is False


def test_approver_auth_reject_scope_dependency(monkeypatch):
    from fastapi import HTTPException

    auth = _set_keys(monkeypatch, "api-x", "appr-y")
    assert auth.require_reject_scope("api-x", None) == "chat"
    assert auth.require_reject_scope(None, "appr-y") == "approver"
    for args in (("api-x", "wrong"), (None, None), ("wrong", None)):
        with pytest.raises(HTTPException) as e:
            auth.require_reject_scope(*args)
        assert e.value.status_code == 401


def test_mcp_guard_rejects_approver_key(client, api_key, approver_key):
    for headers in (
        {"MONAI_API_KEY": approver_key},
        {"Authorization": f"Bearer {approver_key}"},
        {"MONAI_APPROVER_KEY": approver_key},
    ):
        assert client.post("/mcp", json={}, headers=headers).status_code == 401
