"""
Account CRUD endpoint tests — CASH-05, D-05/D-06.

Pins the direct REST write path for accounts, including reassign-then-delete:
  - POST /accounts creates + audits
  - PUT /accounts/{id} updates + audits; unknown id → 404
  - DELETE /accounts/{id} with no transactions succeeds + audits
  - DELETE with transactions and no reassign_to → 422 with affected_count (D-06)
  - DELETE with reassign_to → transactions move to the target, source removed,
    reassignment audited inside apply_delete_account (WARNING 1 fix)
  - propose_delete_account in tools.py stays block-only (Open Question 2)

Requires a live Postgres. Tests seed + clean up their own rows.
"""

import datetime
import uuid

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


def _unique_name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _make_account(db, name: str) -> int:
    from backend.models import Account
    acc = Account(name=name, type="checking", currency="IDR")
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc.id


def _make_transaction(db, account_id: int) -> int:
    from backend.models import Transaction
    tx = Transaction(
        date=datetime.datetime(2024, 1, 15, 12, 0, 0),
        amount=-50000,
        currency="IDR",
        category="Food",
        raw_category="Food",
        merchant="Acc Test",
        account_id=account_id,
        is_transfer=False,
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)
    return tx.id


def _audit_rows(db, entity_id: int, operation: str) -> int:
    return int(
        db.execute(
            text(
                "SELECT COUNT(*) FROM audit_log "
                "WHERE entity = 'account' AND entity_id = :eid AND operation = :op"
            ),
            {"eid": entity_id, "op": operation},
        ).scalar()
        or 0
    )


def _cleanup(db, *, account_ids=(), tx_ids=()):
    from backend.models import Account, Transaction
    for tx_id in tx_ids:
        tx = db.get(Transaction, tx_id)
        if tx:
            db.delete(tx)
    db.commit()
    for acc_id in account_ids:
        acc = db.get(Account, acc_id)
        if acc:
            db.delete(acc)
    db.commit()


# ---------------------------------------------------------------------------
# POST /accounts
# ---------------------------------------------------------------------------

def test_post_creates_and_audits(client, api_key, db_session):
    from backend.models import Account

    name = _unique_name("AccCreate")
    resp = client.post(
        "/accounts",
        json={"name": name, "type": "savings", "currency": "IDR"},
        headers={"MONAI_API_KEY": api_key},
    )
    assert resp.status_code == 201, resp.text
    acc_id = resp.json()["id"]
    try:
        assert resp.json()["name"] == name
        assert _audit_rows(db_session, acc_id, "add") == 1
    finally:
        _cleanup(db_session, account_ids=[acc_id])


def test_post_requires_api_key(client, api_key):
    resp = client.post("/accounts", json={"name": "x"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# PUT /accounts/{id}
# ---------------------------------------------------------------------------

def test_put_updates_and_audits(client, api_key, db_session):
    from backend.models import Account

    acc_id = _make_account(db_session, _unique_name("AccEdit"))
    new_name = _unique_name("AccEditNew")
    try:
        resp = client.put(
            f"/accounts/{acc_id}",
            json={"name": new_name},
            headers={"MONAI_API_KEY": api_key},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["name"] == new_name

        db_session.expire_all()
        assert db_session.get(Account, acc_id).name == new_name
        assert _audit_rows(db_session, acc_id, "edit") == 1
    finally:
        _cleanup(db_session, account_ids=[acc_id])


def test_put_unknown_id_returns_404(client, api_key):
    resp = client.put(
        "/accounts/999999999", json={"name": "x"}, headers={"MONAI_API_KEY": api_key}
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /accounts/{id} — no transactions
# ---------------------------------------------------------------------------

def test_delete_no_transactions_succeeds_and_audits(client, api_key, db_session):
    from backend.models import Account

    acc_id = _make_account(db_session, _unique_name("AccDel"))
    resp = client.delete(f"/accounts/{acc_id}", headers={"MONAI_API_KEY": api_key})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "deleted"

    db_session.expire_all()
    assert db_session.get(Account, acc_id) is None
    assert _audit_rows(db_session, acc_id, "delete") == 1


# ---------------------------------------------------------------------------
# DELETE with transactions + no reassign_to → 422 with affected_count (D-06)
# ---------------------------------------------------------------------------

def test_delete_blocked_without_reassign(client, api_key, db_session):
    acc_id = _make_account(db_session, _unique_name("AccBlock"))
    tx_ids = [_make_transaction(db_session, acc_id) for _ in range(2)]
    try:
        resp = client.delete(f"/accounts/{acc_id}", headers={"MONAI_API_KEY": api_key})
        assert resp.status_code == 422, resp.text
        detail = resp.json()["detail"]
        assert detail["affected_count"] == 2
        assert "affected_count" in detail
    finally:
        _cleanup(db_session, account_ids=[acc_id], tx_ids=tx_ids)


# ---------------------------------------------------------------------------
# DELETE with reassign_to → reassign-then-delete, audited (WARNING 1 fix)
# ---------------------------------------------------------------------------

def test_reassign_then_delete(client, api_key, db_session):
    from backend.models import Account, Transaction

    src_id = _make_account(db_session, _unique_name("AccSrc"))
    dst_id = _make_account(db_session, _unique_name("AccDst"))
    tx_ids = [_make_transaction(db_session, src_id) for _ in range(3)]
    try:
        resp = client.delete(
            f"/accounts/{src_id}?reassign_to={dst_id}",
            headers={"MONAI_API_KEY": api_key},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["reassigned"] == 3

        db_session.expire_all()
        # source account removed
        assert db_session.get(Account, src_id) is None
        # transactions now belong to the target
        for tx_id in tx_ids:
            assert db_session.get(Transaction, tx_id).account_id == dst_id

        # reassignment recorded in the audit trail (target + count)
        row = db_session.execute(
            text(
                "SELECT after FROM audit_log "
                "WHERE entity = 'account' AND entity_id = :eid AND operation = 'delete' "
                "ORDER BY id DESC LIMIT 1"
            ),
            {"eid": src_id},
        ).fetchone()
        assert row is not None, "no delete audit row for the reassigned account"
        after = row[0]
        assert after is not None, "reassignment delete audit row must record target + count"
        assert after["reassign_to"] == dst_id
        assert after["reassigned_count"] == 3
    finally:
        _cleanup(db_session, account_ids=[src_id, dst_id], tx_ids=tx_ids)


def test_reassign_unknown_target_returns_404(client, api_key, db_session):
    src_id = _make_account(db_session, _unique_name("AccSrc2"))
    tx_ids = [_make_transaction(db_session, src_id)]
    try:
        resp = client.delete(
            f"/accounts/{src_id}?reassign_to=999999999",
            headers={"MONAI_API_KEY": api_key},
        )
        assert resp.status_code == 404
    finally:
        _cleanup(db_session, account_ids=[src_id], tx_ids=tx_ids)


# ---------------------------------------------------------------------------
# Open Question 2: propose_delete_account stays block-only (no reassign_to)
# ---------------------------------------------------------------------------

def test_propose_delete_account_unchanged():
    """propose_delete_account has no reassign_to parameter — the agent tool
    stays block-only; reassignment lives only in the direct endpoint + helper."""
    import inspect
    from backend.tools import propose_delete_account

    sig = inspect.signature(propose_delete_account)
    assert "reassign_to" not in sig.parameters
