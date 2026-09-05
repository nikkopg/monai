"""
Category management endpoint tests — CASH-06 (rename), CASH-07 (merge),
and the affected-count read (D-09).

Reworked for the hierarchy (Phase 11 plan 11-03): rename/merge now operate on
categories.name + transactions.category_id (D-11), not the legacy free-text
`category` string column, so these tests seed real Category rows. GET
/categories's tree shape (id/parent_id/kind/color/effective_color/tx_count,
?kind= filter) has its own thorough coverage in test_category_hierarchy.py —
not duplicated here.

  - GET /categories/{name}/affected-count returns the transaction count
  - POST /categories/rename edits categories.name (single row); the legacy
    `category` string on affected transactions is untouched (D-11)
  - POST /categories/merge moves transactions.category_id + deletes the
    source row
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


def _unique_cat(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _make_category(db, name: str):
    from backend.models import Category
    cat = Category(name=name, parent_id=None, kind="expense", color="#112233", icon=None, is_system=False)
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


def _make_transaction(db, category_id: int, legacy_category: str | None = None) -> int:
    from backend.models import Transaction
    tx = Transaction(
        date=datetime.datetime(2024, 1, 15, 12, 0, 0),
        amount=-50000,
        currency="IDR",
        category=legacy_category,
        raw_category=legacy_category,
        merchant="Cat Test Merchant",
        is_transfer=False,
        category_id=category_id,
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)
    return tx.id


def _category_exists(db, cat_id: int) -> bool:
    """Raw-SQL existence check — a strongly-referenced ORM object deleted by
    another session raises ObjectDeletedError on db.get() after
    expire_all(), a plain SELECT sidesteps the identity-map refresh."""
    return db.execute(text("SELECT 1 FROM categories WHERE id = :id"), {"id": cat_id}).first() is not None


def _cleanup(db, *, category_ids=(), tx_ids=()):
    from backend.models import Category, Transaction
    for tx_id in tx_ids:
        tx = db.get(Transaction, tx_id)
        if tx:
            db.delete(tx)
    db.commit()
    for cat_id in category_ids:
        cat = db.get(Category, cat_id)
        if cat:
            db.delete(cat)
            db.commit()


# ---------------------------------------------------------------------------
# GET /categories/{name}/affected-count
# ---------------------------------------------------------------------------

def test_affected_count(client, db_session):
    cat = _make_category(db_session, _unique_cat("CatCount"))
    ids = [_make_transaction(db_session, cat.id) for _ in range(3)]
    try:
        resp = client.get(f"/categories/{cat.name}/affected-count")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["category"] == cat.name
        assert body["affected_count"] == 3
    finally:
        _cleanup(db_session, category_ids=[cat.id], tx_ids=ids)


# ---------------------------------------------------------------------------
# POST /categories/rename — CASH-06
# ---------------------------------------------------------------------------

def test_rename(client, api_key, db_session):
    """Rename edits categories.name (single row, D-11); a fixture transaction
    keeps its category_id AND its legacy `category` string is unchanged."""
    from backend.models import Category, Transaction

    old = _unique_cat("RenameOld")
    new = _unique_cat("RenameNew")
    cat = _make_category(db_session, old)
    legacy = "legacy-untouched"
    ids = [_make_transaction(db_session, cat.id, legacy_category=legacy) for _ in range(2)]
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
        assert db_session.get(Category, cat.id).name == new
        for tx_id in ids:
            tx = db_session.get(Transaction, tx_id)
            assert tx.category_id == cat.id
            assert tx.category == legacy  # D-11: legacy string untouched by rename
    finally:
        _cleanup(db_session, category_ids=[cat.id], tx_ids=ids)


def test_rename_requires_api_key(client, api_key):
    """No header (with a configured key present) → 401 (auth-protected route)."""
    resp = client.post("/categories/rename", json={"old_name": "a", "new_name": "b"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /categories/merge — CASH-07
# ---------------------------------------------------------------------------

def test_merge(client, api_key, db_session):
    """Merge moves ALL from_name transactions (via category_id) to into_name
    and deletes the source category row."""
    from backend.models import Transaction

    from_name = _unique_cat("MergeFrom")
    into_name = _unique_cat("MergeInto")
    from_cat = _make_category(db_session, from_name)
    into_cat = _make_category(db_session, into_name)
    from_cat_id = from_cat.id  # capture BEFORE expire_all — merge deletes this row
    from_ids = [_make_transaction(db_session, from_cat_id) for _ in range(2)]
    into_id = _make_transaction(db_session, into_cat.id)
    try:
        resp = client.post(
            "/categories/merge",
            json={"from_name": from_name, "into_name": into_name},
            headers={"MONAI_API_KEY": api_key},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["affected_count"] == 2
        assert body["from_name"] == from_name and body["into_name"] == into_name

        db_session.expire_all()
        assert not _category_exists(db_session, from_cat_id)  # source row deleted by merge
        for tx_id in from_ids:
            tx = db_session.get(Transaction, tx_id)
            assert tx.category_id == into_cat.id
        # the pre-existing into_cat transaction is untouched
        assert db_session.get(Transaction, into_id).category_id == into_cat.id
    finally:
        _cleanup(db_session, category_ids=[into_cat.id], tx_ids=from_ids + [into_id])


def test_merge_requires_api_key(client, api_key):
    """No header (with a configured key present) → 401 (auth-protected route)."""
    resp = client.post("/categories/merge", json={"from_name": "a", "into_name": "b"})
    assert resp.status_code == 401
