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


def _make_account(db, name: str, currency: str = "IDR") -> int:
    from backend.models import Account
    acc = Account(name=name, type="liquid", currency=currency)
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc.id


def _make_transaction(db, account_id: int, *, currency="IDR", amount=-50000, category="Food", is_transfer=False) -> int:
    from backend.models import Transaction
    tx = Transaction(
        date=datetime.datetime(2024, 1, 15, 12, 0, 0),
        amount=amount,
        currency=currency,
        category=category,
        raw_category=category,
        merchant="Acc Test",
        account_id=account_id,
        is_transfer=is_transfer,
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
    db.rollback()  # a failed test may leave a dirty session that would mask its error
    for tx_id in tx_ids:
        tx = db.get(Transaction, tx_id)
        if tx:
            db.delete(tx)
    db.commit()
    for acc_id in account_ids:  # also drops rows a test created indirectly (adjustments)
        db.execute(text("DELETE FROM transactions WHERE account_id = :a"), {"a": acc_id})
        db.commit()
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
        json={"name": name, "type": "liquid", "currency": "IDR"},
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


# ---------------------------------------------------------------------------
# Phase 44 (D-01): account currency is IDR or USD
# ---------------------------------------------------------------------------

def _account_count(db, name: str) -> int:
    return int(db.execute(text("SELECT COUNT(*) FROM accounts WHERE name = :n"), {"n": name}).scalar() or 0)


def test_post_account_usd_created(client, api_key, db_session):
    from backend.models import AuditLog

    name = _unique_name("ZZ44 usd")
    resp = client.post(
        "/accounts",
        json={"name": name, "type": "liquid", "currency": "USD"},
        headers={"MONAI_API_KEY": api_key},
    )
    assert resp.status_code == 201, resp.text
    acc_id = resp.json()["id"]
    try:
        assert resp.json()["currency"] == "USD"
        db_session.expire_all()
        stored = db_session.execute(
            text("SELECT currency FROM accounts WHERE id = :i"), {"i": acc_id}
        ).scalar()
        assert stored == "USD"
        audit = db_session.query(AuditLog).filter_by(entity="account", entity_id=acc_id, operation="add").one()
        assert audit.after["currency"] == "USD"
    finally:
        _cleanup(db_session, account_ids=[acc_id])


def test_post_account_null_currency_is_idr(client, api_key, db_session):
    resp = client.post(
        "/accounts",
        json={"name": _unique_name("ZZ44 null"), "type": "liquid", "currency": None},
        headers={"MONAI_API_KEY": api_key},
    )
    assert resp.status_code == 201, resp.text
    try:
        assert resp.json()["currency"] == "IDR"
    finally:
        _cleanup(db_session, account_ids=[resp.json()["id"]])


def test_post_account_out_of_set_is_422(client, api_key, db_session):
    name = _unique_name("ZZ44 eur")
    resp = client.post(
        "/accounts",
        json={"name": name, "type": "liquid", "currency": "EUR"},
        headers={"MONAI_API_KEY": api_key},
    )
    assert resp.status_code == 422, resp.text
    assert "IDR" in resp.text and "USD" in resp.text
    assert _account_count(db_session, name) == 0


def test_put_account_currency_on_empty_account(client, api_key, db_session):
    from backend.models import Account

    acc_id = _make_account(db_session, _unique_name("ZZ44 putccy"))
    try:
        headers = {"MONAI_API_KEY": api_key}
        resp = client.put(f"/accounts/{acc_id}", json={"currency": "USD"}, headers=headers)
        assert resp.status_code == 200, resp.text
        db_session.expire_all()
        assert db_session.get(Account, acc_id).currency == "USD"

        resp = client.put(f"/accounts/{acc_id}", json={"currency": "idr"}, headers=headers)
        assert resp.status_code == 200, resp.text
        db_session.expire_all()
        assert db_session.get(Account, acc_id).currency == "IDR"
    finally:
        _cleanup(db_session, account_ids=[acc_id])


def test_apply_add_account_currency_rules(db_session):
    from backend.models import AuditLog
    from backend.writes import apply_add_account

    try:
        for given, expected in [(None, "IDR"), ("", "IDR"), ("  ", "IDR"), ("usd", "USD"), (" usd ", "USD")]:
            acc = apply_add_account(db_session, {"name": _unique_name("ZZ44 prim"), "type": "liquid", "currency": given})
            db_session.flush()
            assert acc.currency == expected
            audit = db_session.query(AuditLog).filter_by(entity="account", entity_id=acc.id).one()
            assert audit.after["currency"] == expected

        with pytest.raises(ValueError, match="IDR") as exc:
            apply_add_account(db_session, {"name": _unique_name("ZZ44 prim"), "type": "liquid", "currency": "EUR"})
        assert "USD" in str(exc.value)
    finally:
        db_session.rollback()


# ---------------------------------------------------------------------------
# Phase 44 (D-02): currency lock once an account has rows
# ---------------------------------------------------------------------------

def test_apply_edit_account_lock_refuses_before_mutation(db_session):
    from backend.models import Account, AuditLog
    from backend.writes import apply_edit_account

    acc_id = _make_account(db_session, _unique_name("ZZ44 lock"), "USD")
    tx_id = _make_transaction(db_session, acc_id, currency="USD", amount=-50)
    try:
        with pytest.raises(ValueError, match="its currency can't change"):
            apply_edit_account(db_session, acc_id, {"currency": "IDR"}, None)
        assert db_session.get(Account, acc_id).currency == "USD"
        assert not [o for o in db_session.new if isinstance(o, AuditLog)]
        db_session.rollback()
    finally:
        _cleanup(db_session, account_ids=[acc_id], tx_ids=[tx_id])


def test_put_currency_change_with_rows_is_422(client, api_key, db_session):
    from backend.models import Account

    name = _unique_name("ZZ44 lockrest")
    acc_id = _make_account(db_session, name, "USD")
    tx_id = _make_transaction(db_session, acc_id, currency="USD", amount=-50)
    try:
        resp = client.put(f"/accounts/{acc_id}", json={"currency": "IDR"}, headers={"MONAI_API_KEY": api_key})
        assert resp.status_code == 422, resp.text
        assert name in resp.text and "1 record" in resp.text
        db_session.expire_all()
        assert db_session.get(Account, acc_id).currency == "USD"
        assert _audit_rows(db_session, acc_id, "edit") == 0
    finally:
        _cleanup(db_session, account_ids=[acc_id], tx_ids=[tx_id])


def test_lock_counts_adjustment_rows(client, api_key, db_session):
    acc_id = _make_account(db_session, _unique_name("ZZ44 lockadj"))
    tx_id = _make_transaction(db_session, acc_id, category="Adjustment", is_transfer=True)
    try:
        resp = client.put(f"/accounts/{acc_id}", json={"currency": "USD"}, headers={"MONAI_API_KEY": api_key})
        assert resp.status_code == 422, resp.text
    finally:
        _cleanup(db_session, account_ids=[acc_id], tx_ids=[tx_id])


def test_lock_same_value_is_noop(client, api_key, db_session):
    from backend.models import Account

    acc_id = _make_account(db_session, _unique_name("ZZ44 locknoop"), "USD")
    tx_id = _make_transaction(db_session, acc_id, currency="USD", amount=-50)
    new_name = _unique_name("ZZ44 renamed")
    try:
        headers = {"MONAI_API_KEY": api_key}
        resp = client.put(f"/accounts/{acc_id}", json={"currency": "usd"}, headers=headers)
        assert resp.status_code == 200, resp.text
        resp = client.put(f"/accounts/{acc_id}", json={"name": new_name}, headers=headers)
        assert resp.status_code == 200, resp.text
        db_session.expire_all()
        acc = db_session.get(Account, acc_id)
        assert acc.currency == "USD" and acc.name == new_name
    finally:
        _cleanup(db_session, account_ids=[acc_id], tx_ids=[tx_id])


def test_lock_chat_shaped_rename_passes(db_session):
    from backend import tools
    from backend.models import Account
    from backend.writes import apply_edit_account

    acc_id = _make_account(db_session, _unique_name("ZZ44 chat"), "USD")
    tx_id = _make_transaction(db_session, acc_id, currency="USD", amount=-50)
    new_name = _unique_name("ZZ44 chatnew")
    try:
        acc = db_session.get(Account, acc_id)
        before = tools._account_to_dict(acc)
        apply_edit_account(db_session, acc_id, {**before, "name": new_name}, before)
        db_session.commit()
        db_session.expire_all()
        acc = db_session.get(Account, acc_id)
        assert acc.name == new_name and acc.currency == "USD"
    finally:
        _cleanup(db_session, account_ids=[acc_id], tx_ids=[tx_id])


# ---------------------------------------------------------------------------
# Phase 44 (D-05): reassign only into the same currency
# ---------------------------------------------------------------------------

def test_reassign_cross_currency_is_422(client, api_key, db_session):
    from backend.models import Account, Transaction

    src = _make_account(db_session, _unique_name("ZZ44 xsrc"), "USD")
    dst_name = _unique_name("ZZ44 xdst")
    dst = _make_account(db_session, dst_name, "IDR")
    tx_ids = [_make_transaction(db_session, src, currency="USD", amount=-50) for _ in range(2)]
    try:
        resp = client.delete(f"/accounts/{src}?reassign_to={dst}", headers={"MONAI_API_KEY": api_key})
        assert resp.status_code == 422, resp.text
        assert "USD" in resp.text and "IDR" in resp.text and dst_name in resp.text
        db_session.expire_all()
        assert db_session.get(Account, src) is not None
        assert all(db_session.get(Transaction, t).account_id == src for t in tx_ids)
        assert _audit_rows(db_session, src, "delete") == 0
    finally:
        _cleanup(db_session, account_ids=[src, dst], tx_ids=tx_ids)


def test_reassign_same_currency_usd(client, api_key, db_session):
    from backend.models import Transaction

    src = _make_account(db_session, _unique_name("ZZ44 usrc"), "USD")
    dst = _make_account(db_session, _unique_name("ZZ44 udst"), "USD")
    tx_ids = [_make_transaction(db_session, src, currency="USD", amount=-50) for _ in range(2)]
    try:
        resp = client.delete(f"/accounts/{src}?reassign_to={dst}", headers={"MONAI_API_KEY": api_key})
        assert resp.status_code == 200, resp.text
        assert resp.json()["reassigned"] == 2
        db_session.expire_all()
        assert all(db_session.get(Transaction, t).account_id == dst for t in tx_ids)
    finally:
        _cleanup(db_session, account_ids=[src, dst], tx_ids=tx_ids)


def test_reassign_to_itself_is_422(client, api_key, db_session):
    from backend.models import Account, Transaction

    acc_id = _make_account(db_session, _unique_name("ZZ44 self"))
    tx_id = _make_transaction(db_session, acc_id)
    try:
        resp = client.delete(f"/accounts/{acc_id}?reassign_to={acc_id}", headers={"MONAI_API_KEY": api_key})
        assert resp.status_code == 422, resp.text
        db_session.expire_all()
        assert db_session.get(Account, acc_id) is not None
        assert db_session.get(Transaction, tx_id).account_id == acc_id
    finally:
        _cleanup(db_session, account_ids=[acc_id], tx_ids=[tx_id])


# ---------------------------------------------------------------------------
# Phase 44 (D-07, CUR-05): a USD adjustment is a native USD delta
# ---------------------------------------------------------------------------

def test_adjust_usd_account_native_delta(client, api_key, db_session):
    from decimal import Decimal

    from backend.models import Transaction

    acc_id = _make_account(db_session, _unique_name("ZZ44 adj"), "USD")
    tx_id = _make_transaction(db_session, acc_id, currency="USD", amount=Decimal("-50.00"))
    try:
        resp = client.post(
            f"/accounts/{acc_id}/adjust-balance",
            json={"target_balance": 12.34},
            headers={"MONAI_API_KEY": api_key},
        )
        assert resp.status_code == 201, resp.text
        db_session.expire_all()
        rows = db_session.query(Transaction).filter_by(account_id=acc_id, category="Adjustment").all()
        assert len(rows) == 1
        adj = rows[0]
        assert adj.currency == "USD" and adj.is_transfer is True
        assert adj.amount == Decimal("62.34")
    finally:
        _cleanup(db_session, account_ids=[acc_id], tx_ids=[tx_id])
