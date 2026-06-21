"""
Write-tool tests — proposal-producer correctness (CHAT-04, CHAT-07, D-06).

All tests require a live Postgres (docker compose up db) with at least the
schema migrated. Tests that need seed data create + clean up their own rows.

Groups:
  - test_propose_creates_row: core invariant — proposal row created, target unchanged
  - Per-entity proposal creation (transaction add/edit/delete, account add/edit,
    holding add/edit/delete, category rename/merge)
  - test_orphan_delete_blocked: D-06 — propose_delete_account with dependents
"""

import datetime
import uuid

import pytest

from sqlalchemy import text


# ---------------------------------------------------------------------------
# DB fixture — skip if Postgres not available
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
    """Return a live SQLAlchemy session; roll back after each test."""
    from backend.db import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Seed-row helpers
# ---------------------------------------------------------------------------

def _make_transaction(db) -> int:
    """Insert a minimal transaction row; return its id."""
    from backend.models import Transaction
    tx = Transaction(
        date=datetime.datetime(2024, 1, 15, 12, 0, 0),
        amount=-50000,
        currency="IDR",
        category="Food",
        merchant="Test Merchant",
        is_transfer=False,
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)
    return tx.id


def _make_account(db, name: str = "Test Account WTT") -> int:
    from backend.models import Account
    # Clean up leftover from a prior run
    existing = db.query(Account).filter(Account.name == name).first()
    if existing:
        db.delete(existing)
        db.commit()
    acc = Account(name=name, type="checking", currency="IDR")
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc.id


def _make_holding(db) -> int:
    from backend.models import Holding
    import random
    ticker = f"TSTTICKER{random.randint(1000,9999)}"
    h = Holding(ticker=ticker, quantity=10, avg_cost=100000, currency="IDR")
    db.add(h)
    db.commit()
    db.refresh(h)
    return h.id


def _count_proposals(db) -> int:
    return int(db.execute(text("SELECT COUNT(*) FROM proposals")).scalar() or 0)


# ---------------------------------------------------------------------------
# Core invariant test
# ---------------------------------------------------------------------------

def test_propose_creates_row(db_session):
    """propose_edit_transaction returns proposal_id AND proposal_token;
    a pending Proposal row exists; the target Transaction is UNCHANGED.
    """
    from backend.tools import propose_edit_transaction
    from backend.models import Transaction, Proposal

    tx_id = _make_transaction(db_session)
    original = db_session.get(Transaction, tx_id)
    original_category = original.category

    # Count proposals before
    before_count = _count_proposals(db_session)

    result = propose_edit_transaction(tx_id, category="Transport")

    # Must have both fields
    assert "proposal_id" in result, f"proposal_id missing from result: {result}"
    assert "proposal_token" in result, f"proposal_token missing from result: {result}"
    assert result["proposal_token"], "proposal_token must be non-empty"
    assert result.get("error") is None

    # Proposal row exists in DB
    db_session.expire_all()
    after_count = _count_proposals(db_session)
    assert after_count == before_count + 1

    proposal_id = result["proposal_id"]
    proposal = db_session.get(Proposal, uuid.UUID(proposal_id))
    assert proposal is not None
    assert proposal.status == "pending"
    assert proposal.token == result["proposal_token"]

    # Target transaction is UNCHANGED (CHAT-04)
    db_session.expire_all()
    tx_after = db_session.get(Transaction, tx_id)
    assert tx_after.category == original_category, (
        f"Transaction was mutated: expected {original_category!r}, got {tx_after.category!r}"
    )

    # Cleanup
    db_session.delete(proposal)
    db_session.delete(tx_after)
    db_session.commit()


# ---------------------------------------------------------------------------
# Per-entity proposal-creation tests
# ---------------------------------------------------------------------------

def test_propose_add_transaction_creates_proposal(db_session):
    """propose_add_transaction returns proposal with required fields."""
    from backend.tools import propose_add_transaction
    from backend.models import Proposal

    result = propose_add_transaction(
        date="2024-03-01",
        amount=-75000,
        account="BCA",
        category="Food",
        currency="IDR",
    )
    assert "proposal_id" in result
    assert "proposal_token" in result
    assert "error" not in result

    # Cleanup
    from uuid import UUID
    p = db_session.get(Proposal, UUID(result["proposal_id"]))
    if p:
        db_session.delete(p)
        db_session.commit()


def test_propose_delete_transaction_creates_proposal(db_session):
    """propose_delete_transaction creates a proposal; original row untouched."""
    from backend.tools import propose_delete_transaction
    from backend.models import Transaction, Proposal
    from uuid import UUID

    tx_id = _make_transaction(db_session)

    result = propose_delete_transaction(tx_id)
    assert "proposal_id" in result
    assert "proposal_token" in result
    assert "error" not in result

    # Transaction must still exist
    db_session.expire_all()
    still_there = db_session.get(Transaction, tx_id)
    assert still_there is not None

    # Cleanup
    p = db_session.get(Proposal, UUID(result["proposal_id"]))
    if p:
        db_session.delete(p)
    db_session.delete(still_there)
    db_session.commit()


def test_propose_add_account_creates_proposal(db_session):
    """propose_add_account returns a valid proposal."""
    from backend.tools import propose_add_account
    from backend.models import Proposal
    from uuid import UUID

    result = propose_add_account(name="New Test Bank", type="savings", currency="IDR")
    assert "proposal_id" in result
    assert "proposal_token" in result
    assert "error" not in result

    p = db_session.get(Proposal, UUID(result["proposal_id"]))
    if p:
        db_session.delete(p)
        db_session.commit()


def test_propose_edit_account_creates_proposal(db_session):
    """propose_edit_account creates a proposal; original row untouched."""
    from backend.tools import propose_edit_account
    from backend.models import Account, Proposal
    from uuid import UUID

    acc_id = _make_account(db_session, "EditAccWTT")
    original_name = db_session.get(Account, acc_id).name

    result = propose_edit_account(acc_id, name="EditAccWTT-Renamed")
    assert "proposal_id" in result
    assert "proposal_token" in result
    assert "error" not in result

    db_session.expire_all()
    assert db_session.get(Account, acc_id).name == original_name

    p = db_session.get(Proposal, UUID(result["proposal_id"]))
    acc = db_session.get(Account, acc_id)
    if p:
        db_session.delete(p)
    if acc:
        db_session.delete(acc)
    db_session.commit()


def test_propose_add_holding_creates_proposal(db_session):
    """propose_add_holding returns a valid proposal."""
    from backend.tools import propose_add_holding
    from backend.models import Proposal
    from uuid import UUID

    result = propose_add_holding(ticker="TSTADD", quantity=5, avg_cost=50000, currency="IDR")
    assert "proposal_id" in result
    assert "proposal_token" in result
    assert "error" not in result

    p = db_session.get(Proposal, UUID(result["proposal_id"]))
    if p:
        db_session.delete(p)
        db_session.commit()


def test_propose_edit_holding_creates_proposal(db_session):
    """propose_edit_holding creates a proposal; original holding untouched."""
    from backend.tools import propose_edit_holding
    from backend.models import Holding, Proposal
    from decimal import Decimal
    from uuid import UUID

    h_id = _make_holding(db_session)
    original_qty = db_session.get(Holding, h_id).quantity

    result = propose_edit_holding(h_id, quantity=99)
    assert "proposal_id" in result
    assert "proposal_token" in result
    assert "error" not in result

    db_session.expire_all()
    assert db_session.get(Holding, h_id).quantity == original_qty

    p = db_session.get(Proposal, UUID(result["proposal_id"]))
    h = db_session.get(Holding, h_id)
    if p:
        db_session.delete(p)
    if h:
        db_session.delete(h)
    db_session.commit()


def test_propose_delete_holding_creates_proposal(db_session):
    """propose_delete_holding creates a proposal; original holding untouched."""
    from backend.tools import propose_delete_holding
    from backend.models import Holding, Proposal
    from uuid import UUID

    h_id = _make_holding(db_session)

    result = propose_delete_holding(h_id)
    assert "proposal_id" in result
    assert "proposal_token" in result
    assert "error" not in result

    db_session.expire_all()
    assert db_session.get(Holding, h_id) is not None

    p = db_session.get(Proposal, UUID(result["proposal_id"]))
    h = db_session.get(Holding, h_id)
    if p:
        db_session.delete(p)
    if h:
        db_session.delete(h)
    db_session.commit()


def test_propose_rename_category_creates_proposal(db_session):
    """propose_rename_category returns a proposal for a non-orphaning rename."""
    from backend.tools import propose_rename_category
    from backend.models import Proposal
    from uuid import UUID

    result = propose_rename_category("Food", "Food & Drinks")
    assert "proposal_id" in result
    assert "proposal_token" in result
    assert "error" not in result

    p = db_session.get(Proposal, UUID(result["proposal_id"]))
    if p:
        db_session.delete(p)
        db_session.commit()


def test_propose_merge_category_creates_proposal(db_session):
    """propose_merge_category returns a proposal for a non-orphaning merge."""
    from backend.tools import propose_merge_category
    from backend.models import Proposal
    from uuid import UUID

    result = propose_merge_category("Shopping", "Retail")
    assert "proposal_id" in result
    assert "proposal_token" in result
    assert "error" not in result

    p = db_session.get(Proposal, UUID(result["proposal_id"]))
    if p:
        db_session.delete(p)
        db_session.commit()


# ---------------------------------------------------------------------------
# D-06: Orphan-delete blocked
# ---------------------------------------------------------------------------

def test_orphan_delete_blocked(db_session):
    """propose_delete_account with dependent transactions returns an error dict
    and creates NO Proposal row (D-06).
    """
    from backend.tools import propose_delete_account
    from backend.models import Account, Transaction

    # Create an account with one transaction
    acc_id = _make_account(db_session, "OrphanTestAccWTT")

    tx = Transaction(
        date=datetime.datetime(2024, 2, 1, 12, 0, 0),
        amount=-10000,
        currency="IDR",
        category="Test",
        account_id=acc_id,
        is_transfer=False,
    )
    db_session.add(tx)
    db_session.commit()
    db_session.refresh(tx)
    tx_id = tx.id

    before_count = _count_proposals(db_session)

    result = propose_delete_account(acc_id)

    # Must return an error, not a proposal
    assert "error" in result, f"Expected error dict, got: {result}"
    assert "proposal_id" not in result or result.get("proposal_id") is None

    # NO proposal row was created
    db_session.expire_all()
    after_count = _count_proposals(db_session)
    assert after_count == before_count, (
        f"Proposal row was created despite orphan-delete block: {before_count} → {after_count}"
    )

    # Cleanup
    db_session.delete(tx)
    db_session.commit()
    acc = db_session.get(Account, acc_id)
    if acc:
        db_session.delete(acc)
        db_session.commit()
