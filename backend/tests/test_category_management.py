"""
Category management endpoint tests — CASH-06 (rename), CASH-07 (merge),
GET /categories (distinct name enumeration, WARNING 2 fix), and the
affected-count read (D-09).

  - GET /categories returns {"categories": [distinct names, sorted]}
  - GET /categories/{name}/affected-count returns the transaction count
  - POST /categories/rename remaps all matching transactions + returns count (CASH-06)
  - POST /categories/merge moves all from_name rows to into_name + returns count (CASH-07)
  - mutating routes are auth-protected and route through apply_* helpers, then reset_engine()

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


def _make_transaction(db, category: str) -> int:
    from backend.models import Transaction
    tx = Transaction(
        date=datetime.datetime(2024, 1, 15, 12, 0, 0),
        amount=-50000,
        currency="IDR",
        category=category,
        raw_category=category,
        merchant="Cat Test Merchant",
        is_transfer=False,
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)
    return tx.id


def _unique_cat(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# GET /categories — distinct name enumeration (WARNING 2 fix)
# ---------------------------------------------------------------------------

def test_get_categories_returns_distinct_names(client, db_session):
    """GET /categories returns a `categories` list containing every seeded
    category name (distinct, across all transactions)."""
    from backend.models import Transaction

    cat = _unique_cat("CatList")
    tx_id = _make_transaction(db_session, cat)
    try:
        resp = client.get("/categories")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "categories" in body
        assert isinstance(body["categories"], list)
        assert cat in body["categories"]
    finally:
        tx = db_session.get(Transaction, tx_id)
        if tx:
            db_session.delete(tx)
            db_session.commit()


# ---------------------------------------------------------------------------
# GET /categories/{name}/affected-count
# ---------------------------------------------------------------------------

def test_affected_count(client, db_session):
    from backend.models import Transaction

    cat = _unique_cat("CatCount")
    ids = [_make_transaction(db_session, cat) for _ in range(3)]
    try:
        resp = client.get(f"/categories/{cat}/affected-count")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["category"] == cat
        assert body["affected_count"] == 3
    finally:
        for tx_id in ids:
            tx = db_session.get(Transaction, tx_id)
            if tx:
                db_session.delete(tx)
        db_session.commit()


# ---------------------------------------------------------------------------
# POST /categories/rename — CASH-06
# ---------------------------------------------------------------------------

def test_rename(client, api_key, db_session):
    """Rename remaps ALL matching transactions to the new name and returns the
    affected count (CASH-06)."""
    from backend.models import Transaction

    old = _unique_cat("RenameOld")
    new = _unique_cat("RenameNew")
    ids = [_make_transaction(db_session, old) for _ in range(2)]
    try:
        resp = client.post(
            "/categories/rename",
            json={"old_name": old, "new_name": new},
            headers={"MONAI_API_KEY": api_key},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["affected_count"] == 2
        assert body["old_name"] == old and body["new_name"] == new

        db_session.expire_all()
        for tx_id in ids:
            tx = db_session.get(Transaction, tx_id)
            assert tx.category == new
    finally:
        for tx_id in ids:
            tx = db_session.get(Transaction, tx_id)
            if tx:
                db_session.delete(tx)
        db_session.commit()


def test_rename_requires_api_key(client, api_key):
    """No header (with a configured key present) → 401 (auth-protected route)."""
    resp = client.post("/categories/rename", json={"old_name": "a", "new_name": "b"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /categories/merge — CASH-07
# ---------------------------------------------------------------------------

def test_merge(client, api_key, db_session):
    """Merge moves ALL from_name transactions to into_name and returns the
    affected count (CASH-07)."""
    from backend.models import Transaction

    from_cat = _unique_cat("MergeFrom")
    into_cat = _unique_cat("MergeInto")
    from_ids = [_make_transaction(db_session, from_cat) for _ in range(2)]
    into_id = _make_transaction(db_session, into_cat)
    try:
        resp = client.post(
            "/categories/merge",
            json={"from_name": from_cat, "into_name": into_cat},
            headers={"MONAI_API_KEY": api_key},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["affected_count"] == 2
        assert body["from_name"] == from_cat and body["into_name"] == into_cat

        db_session.expire_all()
        for tx_id in from_ids:
            tx = db_session.get(Transaction, tx_id)
            assert tx.category == into_cat
        # the pre-existing into_cat row is untouched
        assert db_session.get(Transaction, into_id).category == into_cat
    finally:
        for tx_id in from_ids + [into_id]:
            tx = db_session.get(Transaction, tx_id)
            if tx:
                db_session.delete(tx)
        db_session.commit()


def test_merge_requires_api_key(client, api_key):
    """No header (with a configured key present) → 401 (auth-protected route)."""
    resp = client.post("/categories/merge", json={"from_name": "a", "into_name": "b"})
    assert resp.status_code == 401
