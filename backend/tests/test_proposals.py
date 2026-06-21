"""
Proposal lifecycle tests — confirm/reject/expire/replay/audit (CHAT-05, CHAT-06).

Integration tests against the live Postgres. Each test creates its own proposal
(and seed data where needed) and cleans up after itself.
"""

import datetime
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.main import app

# ---------------------------------------------------------------------------
# DB + auth fixtures
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


# Use module-level client to avoid re-importing; api_key fixture patches auth
@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


_TEST_API_KEY = "test-monai-api-key-proposals"


@pytest.fixture()
def api_key(monkeypatch: pytest.MonkeyPatch) -> str:
    import backend.auth as auth_mod
    monkeypatch.setattr(auth_mod, "_CONFIGURED_KEY", _TEST_API_KEY)
    return _TEST_API_KEY


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def _make_transaction(db) -> int:
    from backend.models import Transaction
    tx = Transaction(
        date=datetime.datetime(2024, 5, 1, 12, 0, 0),
        amount=-30000,
        currency="IDR",
        category="TestCat",
        merchant="TestMerchant",
        is_transfer=False,
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)
    return tx.id


def _insert_proposal(db, *, tx_id: int, status="pending",
                     expires_delta: datetime.timedelta | None = None) -> tuple[str, str, str]:
    """Insert a minimal edit_transaction proposal; return (proposal_id, token, tx_id_str)."""
    from backend.models import Proposal
    import secrets

    if expires_delta is None:
        expires_delta = datetime.timedelta(minutes=15)

    token = secrets.token_urlsafe(32)
    expires_at = datetime.datetime.now(datetime.timezone.utc) + expires_delta
    before = {"id": tx_id, "category": "TestCat", "amount": "-30000"}
    after = {"id": tx_id, "category": "NewCat", "amount": "-30000"}
    payload = {
        "operation": "edit_transaction",
        "rows": [{"id": tx_id, "before": before, "after": after}],
    }
    p = Proposal(
        token=token,
        operation="edit_transaction",
        payload=payload,
        status=status,
        expires_at=expires_at,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return str(p.id), token, str(tx_id)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_confirm_proposal_applies_write(client, api_key, db_session):
    """POST /proposals/{id}/confirm with valid token → 200, status confirmed, target row changed."""
    from backend.models import Transaction

    tx_id = _make_transaction(db_session)
    proposal_id, token, _ = _insert_proposal(db_session, tx_id=tx_id)

    resp = client.post(
        f"/proposals/{proposal_id}/confirm",
        json={"token": token},
        headers={"MONAI_API_KEY": api_key},
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["status"] == "confirmed"

    # Target row must be updated
    db_session.expire_all()
    tx = db_session.get(Transaction, tx_id)
    assert tx.category == "NewCat", f"Expected 'NewCat', got {tx.category!r}"

    # Cleanup
    db_session.delete(tx)
    db_session.commit()


def test_token_single_use(client, api_key, db_session):
    """Second confirm with same token → 409 (CHAT-05)."""
    from backend.models import Transaction

    tx_id = _make_transaction(db_session)
    proposal_id, token, _ = _insert_proposal(db_session, tx_id=tx_id)

    # First confirm
    r1 = client.post(
        f"/proposals/{proposal_id}/confirm",
        json={"token": token},
        headers={"MONAI_API_KEY": api_key},
    )
    assert r1.status_code == 200

    # Second confirm — must return 409
    r2 = client.post(
        f"/proposals/{proposal_id}/confirm",
        json={"token": token},
        headers={"MONAI_API_KEY": api_key},
    )
    assert r2.status_code == 409, f"Expected 409 on replay, got {r2.status_code}: {r2.text}"

    # Cleanup
    db_session.expire_all()
    tx = db_session.get(Transaction, tx_id)
    if tx:
        db_session.delete(tx)
        db_session.commit()


def test_expired_proposal(client, api_key, db_session):
    """Confirm after expiry → 410 (CHAT-05, D-09)."""
    tx_id = _make_transaction(db_session)
    # Set expires_at 1 minute in the past
    proposal_id, token, _ = _insert_proposal(
        db_session, tx_id=tx_id,
        expires_delta=datetime.timedelta(minutes=-1),
    )

    resp = client.post(
        f"/proposals/{proposal_id}/confirm",
        json={"token": token},
        headers={"MONAI_API_KEY": api_key},
    )
    assert resp.status_code == 410, f"Expected 410 on expired, got {resp.status_code}: {resp.text}"

    # Cleanup
    from backend.models import Proposal, Transaction
    db_session.expire_all()
    tx = db_session.get(Transaction, tx_id)
    if tx:
        db_session.delete(tx)
    # Clean up the proposal
    p = db_session.get(Proposal, uuid.UUID(proposal_id))
    if p:
        db_session.delete(p)
    db_session.commit()


def test_wrong_token_rejected(client, api_key, db_session):
    """Confirm with wrong token → 401."""
    tx_id = _make_transaction(db_session)
    proposal_id, token, _ = _insert_proposal(db_session, tx_id=tx_id)

    resp = client.post(
        f"/proposals/{proposal_id}/confirm",
        json={"token": "completely-wrong-token"},
        headers={"MONAI_API_KEY": api_key},
    )
    assert resp.status_code == 401, f"Expected 401 on bad token, got {resp.status_code}: {resp.text}"

    # Cleanup the proposal and tx
    db_session.expire_all()
    from backend.models import Proposal, Transaction
    p = db_session.get(Proposal, uuid.UUID(proposal_id))
    tx = db_session.get(Transaction, tx_id)
    if p:
        db_session.delete(p)
    if tx:
        db_session.delete(tx)
    db_session.commit()


def test_audit_on_confirm(client, api_key, db_session):
    """After confirm, the expected number of audit_log rows exist with before/after (CHAT-06)."""
    from sqlalchemy import text
    from backend.models import Transaction

    tx_id = _make_transaction(db_session)
    proposal_id, token, _ = _insert_proposal(db_session, tx_id=tx_id)

    audit_before = int(
        db_session.execute(text("SELECT COUNT(*) FROM audit_log WHERE entity='transaction' AND entity_id=:id"),
                           {"id": tx_id}).scalar() or 0
    )

    resp = client.post(
        f"/proposals/{proposal_id}/confirm",
        json={"token": token},
        headers={"MONAI_API_KEY": api_key},
    )
    assert resp.status_code == 200

    db_session.expire_all()
    audit_after = int(
        db_session.execute(text("SELECT COUNT(*) FROM audit_log WHERE entity='transaction' AND entity_id=:id"),
                           {"id": tx_id}).scalar() or 0
    )
    assert audit_after == audit_before + 1, (
        f"Expected {audit_before + 1} audit rows, got {audit_after}"
    )

    # Cleanup
    db_session.expire_all()
    tx = db_session.get(Transaction, tx_id)
    if tx:
        db_session.delete(tx)
    db_session.commit()


def test_reject_leaves_db_unchanged(client, api_key, db_session):
    """Reject → status rejected, target row unchanged, no audit row added."""
    from sqlalchemy import text
    from backend.models import Transaction

    tx_id = _make_transaction(db_session)
    original_category = db_session.get(Transaction, tx_id).category
    proposal_id, token, _ = _insert_proposal(db_session, tx_id=tx_id)

    audit_before = int(
        db_session.execute(text("SELECT COUNT(*) FROM audit_log WHERE entity='transaction' AND entity_id=:id"),
                           {"id": tx_id}).scalar() or 0
    )

    resp = client.post(
        f"/proposals/{proposal_id}/reject",
        headers={"MONAI_API_KEY": api_key},
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    assert resp.json()["status"] == "rejected"

    # Target row unchanged
    db_session.expire_all()
    tx = db_session.get(Transaction, tx_id)
    assert tx.category == original_category

    # No new audit row
    audit_after = int(
        db_session.execute(text("SELECT COUNT(*) FROM audit_log WHERE entity='transaction' AND entity_id=:id"),
                           {"id": tx_id}).scalar() or 0
    )
    assert audit_after == audit_before

    # Cleanup
    db_session.delete(tx)
    db_session.commit()


def test_confirm_requires_api_key(client, api_key, db_session):
    """Confirm without MONAI_API_KEY header → 401 (T-02-08).

    Uses the api_key fixture to ensure _CONFIGURED_KEY is non-empty (fail-closed guard)
    but omits the header from the request — auth.py then returns 401 for missing header.
    """
    tx_id = _make_transaction(db_session)
    proposal_id, token, _ = _insert_proposal(db_session, tx_id=tx_id)

    resp = client.post(
        f"/proposals/{proposal_id}/confirm",
        json={"token": token},
        # No MONAI_API_KEY header — relies on api_key fixture having set _CONFIGURED_KEY
    )
    assert resp.status_code == 401, f"Expected 401 without API key, got {resp.status_code}: {resp.text}"

    # Cleanup
    from backend.models import Proposal, Transaction
    db_session.expire_all()
    p = db_session.get(Proposal, uuid.UUID(proposal_id))
    tx = db_session.get(Transaction, tx_id)
    if p:
        db_session.delete(p)
    if tx:
        db_session.delete(tx)
    db_session.commit()


def test_get_proposals_excludes_token(client, api_key, db_session):
    """GET /proposals response JSON has NO 'token' field anywhere (T-02-07)."""
    tx_id = _make_transaction(db_session)
    proposal_id, token, _ = _insert_proposal(db_session, tx_id=tx_id)

    resp = client.get("/proposals?status=pending")
    assert resp.status_code == 200

    data = resp.json()
    # Check top-level keys and all nested dicts recursively
    def _has_token_key(obj) -> bool:
        if isinstance(obj, dict):
            if "token" in obj:
                return True
            return any(_has_token_key(v) for v in obj.values())
        if isinstance(obj, list):
            return any(_has_token_key(item) for item in obj)
        return False

    assert not _has_token_key(data), (
        "GET /proposals response contains a 'token' field — this must never be serialized"
    )

    # Cleanup
    from backend.models import Proposal, Transaction
    db_session.expire_all()
    p = db_session.get(Proposal, uuid.UUID(proposal_id))
    tx = db_session.get(Transaction, tx_id)
    if p:
        db_session.delete(p)
    if tx:
        db_session.delete(tx)
    db_session.commit()
