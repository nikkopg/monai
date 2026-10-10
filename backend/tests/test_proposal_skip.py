"""Phase 32 per-row skip tests (D-19, D-20) against monai_test.

Synthetic values only. Every seeded account, transaction and proposal is deleted
in teardown. Never assert that a leftover row from another test is still pending.
"""
import datetime
import secrets
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text

from backend.tests.test_write_endpoints import _cleanup_account

SKIP_ALL_MSG = "Every row is skipped — reject this proposal instead"


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


@pytest.fixture()
def acct(db_session):
    """One synthetic liquid account plus a proposal factory; all cleaned up."""
    from backend.models import Account, Proposal

    name = f"Skip Test Wallet {uuid.uuid4().hex[:8]}"
    db_session.add(Account(name=name, type="liquid", currency="IDR"))
    db_session.commit()
    pids: list[uuid.UUID] = []

    def make(rows, *, operation="add_transaction", status="pending",
             expires_delta=timedelta(hours=1)):
        p = Proposal(
            token=secrets.token_urlsafe(32), operation=operation,
            payload={"operation": operation, "rows": rows},
            status=status, channel="mcp", code="ABC234",
            expires_at=datetime.datetime.now(datetime.timezone.utc) + expires_delta,
        )
        db_session.add(p)
        db_session.commit()
        pids.append(p.id)
        return str(p.id)

    def row(i):
        return {"before": None, "after": {
            "date": f"2026-01-{10 + i:02d}", "amount": str(-12500 - i), "account": name,
            "category": None, "merchant": f"Synthetic Shop {i}", "notes": None,
            "currency": "IDR", "is_transfer": False,
        }}

    make.row, make.name = row, name
    yield make
    db_session.rollback()
    for i in pids:
        db_session.execute(text("DELETE FROM proposals WHERE id = :i"), {"i": i})
    db_session.commit()
    _cleanup_account(db_session, name)


def _appr(k):
    return {"MONAI_APPROVER_KEY": k}


def _skip(client, pid, i, skip, headers):
    return client.patch(f"/proposals/{pid}/rows/{i}", json={"skip": skip}, headers=headers)


def _status_and_rows(pid):
    from backend.db import SessionLocal
    from backend.models import Proposal

    db = SessionLocal()
    try:
        p = db.get(Proposal, uuid.UUID(pid))
        return p.status, p.payload["rows"]
    finally:
        db.close()


def test_skip_requires_approver_key(client, api_key, approver_key, acct):
    pid = acct([acct.row(0)])
    assert client.patch(f"/proposals/{pid}/rows/0", json={"skip": True}).status_code == 401
    assert _skip(client, pid, 0, True, _appr(api_key)).status_code == 401
    assert "skip" not in _status_and_rows(pid)[1][0]


def test_skip_unknown_proposal_404(client, approver_key, acct):
    assert _skip(client, str(uuid.uuid4()), 0, True, _appr(approver_key)).status_code == 404


def test_skip_decided_proposal_409(client, approver_key, acct):
    for status in ("confirmed", "rejected"):
        pid = acct([acct.row(0)], status=status)
        assert _skip(client, pid, 0, True, _appr(approver_key)).status_code == 409


def test_skip_expired_410(client, approver_key, acct):
    status_expired = acct([acct.row(0)], status="expired")
    past_due = acct([acct.row(0)], expires_delta=timedelta(minutes=-5))
    for pid in (status_expired, past_due):
        assert _skip(client, pid, 0, True, _appr(approver_key)).status_code == 410


def test_skip_non_batch_operation_422(client, approver_key, acct):
    pid = acct([{"before": None, "after": {}}], operation="add_transfer")
    assert _skip(client, pid, 0, True, _appr(approver_key)).status_code == 422


def test_skip_index_out_of_range_422(client, approver_key, acct):
    pid = acct([acct.row(0), acct.row(1)])
    for i in (2, -1):
        assert _skip(client, pid, i, True, _appr(approver_key)).status_code == 422


def test_skip_toggle_persists(client, approver_key, acct):
    pid = acct([acct.row(0), acct.row(1)])
    assert _skip(client, pid, 1, True, _appr(approver_key)).status_code == 200
    assert _status_and_rows(pid)[1][1]["skip"] is True
    assert _skip(client, pid, 1, False, _appr(approver_key)).status_code == 200
    assert _status_and_rows(pid)[1][1]["skip"] is False


def test_approve_leaves_out_skipped_rows(client, approver_key, db_session, acct):
    from backend.models import Account, AuditLog, Transaction

    pid = acct([acct.row(0), acct.row(1), acct.row(2)])
    assert _skip(client, pid, 1, True, _appr(approver_key)).status_code == 200
    r = client.post(f"/proposals/{pid}/approve", headers=_appr(approver_key))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "confirmed"
    db_session.expire_all()
    acc = db_session.query(Account).filter(Account.name == acct.name).one()
    txs = db_session.query(Transaction).filter(Transaction.account_id == acc.id).all()
    assert sorted(str(t.merchant) for t in txs) == ["Synthetic Shop 0", "Synthetic Shop 2"]
    n_audit = db_session.query(AuditLog).filter(
        AuditLog.entity == "transaction", AuditLog.entity_id.in_([t.id for t in txs])
    ).count()
    assert n_audit == 2


def test_approve_all_skipped_refused(client, approver_key, db_session, acct):
    from backend.models import Account, Transaction

    pid = acct([acct.row(0), acct.row(1)])
    for i in (0, 1):
        assert _skip(client, pid, i, True, _appr(approver_key)).status_code == 200
    r = client.post(f"/proposals/{pid}/approve", headers=_appr(approver_key))
    assert r.status_code == 422
    assert r.json()["detail"] == SKIP_ALL_MSG
    assert _status_and_rows(pid)[0] == "pending"
    db_session.expire_all()
    acc = db_session.query(Account).filter(Account.name == acct.name).one()
    assert db_session.query(Transaction).filter(Transaction.account_id == acc.id).count() == 0


def test_empty_rows_proposal_still_approves(client, approver_key, acct):
    pid = acct([])
    r = client.post(f"/proposals/{pid}/approve", headers=_appr(approver_key))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "confirmed"
