"""
Transaction CRUD endpoint tests — CASH-04.

Pins the direct REST write path for transactions (PUT/DELETE /transactions/{id}):
  - PUT edits only supplied fields and writes an AuditLog "edit" row
  - DELETE removes the row and writes an AuditLog "delete" row
  - unknown id → 404
  - each mutating route is auth-protected (require_api_key) and routes through
    the backend/writes.py apply_* helpers (never inline ORM), then reset_engine()

Requires a live Postgres (docker compose up db). Tests seed + clean up rows.
"""

import datetime

import pytest

from sqlalchemy import text


# ---------------------------------------------------------------------------
# DB fixture — skip if Postgres not available (mirrors test_write_tools.py)
# ---------------------------------------------------------------------------

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


def _make_transaction(db, *, category="Food", merchant="Test Merchant", amount=-50000) -> int:
    from backend.models import Transaction
    tx = Transaction(
        date=datetime.datetime(2024, 1, 15, 12, 0, 0),
        amount=amount,
        currency="IDR",
        category=category,
        raw_category=category,
        merchant=merchant,
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
                "WHERE entity = 'transaction' AND entity_id = :eid AND operation = :op"
            ),
            {"eid": entity_id, "op": operation},
        ).scalar()
        or 0
    )


# ---------------------------------------------------------------------------
# PUT /transactions/{id}
# ---------------------------------------------------------------------------

def test_put_edits_only_supplied_fields_and_audits(client, api_key, db_session):
    """PUT with a partial body updates only the provided field, leaves the rest
    unchanged, and writes an AuditLog edit row (CASH-04)."""
    from backend.models import Transaction

    tx_id = _make_transaction(db_session, category="Food", merchant="Original")
    before_audit = _audit_rows(db_session, tx_id, "edit")
    try:
        resp = client.put(
            f"/transactions/{tx_id}",
            json={"category": "Transport"},
            headers={"MONAI_API_KEY": api_key},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["category"] == "Transport"
        assert body["merchant"] == "Original"  # untouched

        db_session.expire_all()
        tx = db_session.get(Transaction, tx_id)
        assert tx.category == "Transport"
        assert tx.merchant == "Original"

        assert _audit_rows(db_session, tx_id, "edit") == before_audit + 1
    finally:
        tx = db_session.get(Transaction, tx_id)
        if tx:
            db_session.delete(tx)
            db_session.commit()


def test_put_unknown_id_returns_404(client, api_key):
    resp = client.put(
        "/transactions/999999999",
        json={"category": "X"},
        headers={"MONAI_API_KEY": api_key},
    )
    assert resp.status_code == 404


def test_put_requires_api_key(client, api_key):
    """PUT without the API key (with a configured key present) → 401."""
    resp = client.put("/transactions/1", json={"category": "X"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# DELETE /transactions/{id}
# ---------------------------------------------------------------------------

def test_delete_removes_row_and_audits(client, api_key, db_session):
    """DELETE removes the transaction and writes an AuditLog delete row."""
    from backend.models import Transaction

    tx_id = _make_transaction(db_session)
    before_audit = _audit_rows(db_session, tx_id, "delete")

    resp = client.delete(f"/transactions/{tx_id}", headers={"MONAI_API_KEY": api_key})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "deleted"

    db_session.expire_all()
    assert db_session.get(Transaction, tx_id) is None
    assert _audit_rows(db_session, tx_id, "delete") == before_audit + 1


def test_delete_unknown_id_returns_404(client, api_key):
    resp = client.delete("/transactions/999999999", headers={"MONAI_API_KEY": api_key})
    assert resp.status_code == 404


def test_delete_requires_api_key(client, api_key):
    resp = client.delete("/transactions/1")
    assert resp.status_code == 401
