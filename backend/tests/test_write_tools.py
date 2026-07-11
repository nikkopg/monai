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
# D-12: Platform write helpers (apply_add_platform / apply_delete_platform)
# ---------------------------------------------------------------------------


def _make_platform(db, name: str = "Test Platform WTT", kind: str | None = "brokerage") -> int:
    from backend.models import Platform
    existing = db.query(Platform).filter(Platform.name == name).first()
    if existing:
        db.delete(existing)
        db.commit()
    plat = Platform(name=name, kind=kind)
    db.add(plat)
    db.commit()
    db.refresh(plat)
    return plat.id


def test_apply_add_platform_creates_row_and_audit(db_session):
    """apply_add_platform inserts a platforms row and writes exactly one
    AuditLog(entity="platform", operation="add", before=None).
    """
    from backend.writes import apply_add_platform
    from backend.models import Platform, AuditLog

    name = "BCA Sekuritas WTT"
    # Clean up leftover from a prior run
    existing = db_session.query(Platform).filter(Platform.name == name).first()
    if existing:
        db_session.delete(existing)
        db_session.commit()

    before_audit = int(
        db_session.execute(
            text("SELECT COUNT(*) FROM audit_log WHERE entity = 'platform'")
        ).scalar()
        or 0
    )

    plat = apply_add_platform(db_session, {"name": name, "kind": "brokerage"})
    db_session.commit()
    db_session.refresh(plat)

    # Row exists with the supplied values
    row = db_session.query(Platform).filter(Platform.name == name).first()
    assert row is not None
    assert row.kind == "brokerage"

    # Exactly one new platform AuditLog row, operation="add", before=None
    after_audit = int(
        db_session.execute(
            text("SELECT COUNT(*) FROM audit_log WHERE entity = 'platform'")
        ).scalar()
        or 0
    )
    assert after_audit == before_audit + 1

    log = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity == "platform", AuditLog.entity_id == plat.id)
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert log is not None
    assert log.operation == "add"
    assert log.before is None

    # Cleanup
    db_session.query(AuditLog).filter(
        AuditLog.entity == "platform", AuditLog.entity_id == plat.id
    ).delete()
    db_session.delete(row)
    db_session.commit()


def test_apply_delete_platform_reassigns_holdings(db_session):
    """apply_delete_platform with reassign_to moves dependent holdings to the
    target platform, records reassigned_count in the AuditLog after-dict, then
    deletes the source platform.
    """
    from backend.writes import apply_delete_platform
    from backend.models import Platform, Holding, AuditLog
    import random

    source_id = _make_platform(db_session, "SrcPlatformWTT", "brokerage")
    target_id = _make_platform(db_session, "DstPlatformWTT", "exchange")

    ticker = f"REASSIGN{random.randint(1000, 9999)}"
    h = Holding(
        ticker=ticker,
        quantity=3,
        avg_cost=100000,
        currency="IDR",
        platform_id=source_id,
    )
    db_session.add(h)
    db_session.commit()
    db_session.refresh(h)
    h_id = h.id

    before = {"id": source_id, "name": "SrcPlatformWTT", "kind": "brokerage"}
    reassigned = apply_delete_platform(db_session, source_id, before, reassign_to=target_id)
    db_session.commit()

    assert reassigned == 1

    # Holding now points at the target platform
    db_session.expire_all()
    moved = db_session.get(Holding, h_id)
    assert moved is not None
    assert moved.platform_id == target_id

    # Source platform is gone
    assert db_session.get(Platform, source_id) is None

    # The delete AuditLog after-dict carries reassigned_count
    log = (
        db_session.query(AuditLog)
        .filter(
            AuditLog.entity == "platform",
            AuditLog.entity_id == source_id,
            AuditLog.operation == "delete",
        )
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert log is not None
    assert log.after is not None
    assert log.after.get("reassigned_count") == 1
    assert log.after.get("reassign_to") == target_id

    # Cleanup
    db_session.query(AuditLog).filter(
        AuditLog.entity == "platform", AuditLog.entity_id.in_([source_id, target_id])
    ).delete(synchronize_session=False)
    db_session.delete(moved)
    tgt = db_session.get(Platform, target_id)
    if tgt:
        db_session.delete(tgt)
    db_session.commit()


def test_post_platforms_requires_api_key(client, api_key):
    """POST /platforms without the key → 401; with the key → 201 and the row."""
    from backend.db import engine

    # Skip cleanly when Postgres is down (mirrors db_available)
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception as e:
        pytest.skip(f"Postgres not available: {e}")

    name = "AuthCheckPlatformWTT"
    from backend.db import SessionLocal
    from backend.models import Platform, AuditLog

    _db = SessionLocal()
    try:
        existing = _db.query(Platform).filter(Platform.name == name).first()
        if existing:
            _db.query(AuditLog).filter(
                AuditLog.entity == "platform", AuditLog.entity_id == existing.id
            ).delete()
            _db.delete(existing)
            _db.commit()
    finally:
        _db.close()

    # No key header → 401
    r_no_key = client.post("/platforms", json={"name": name, "kind": "brokerage"})
    assert r_no_key.status_code == 401

    # With key → 201 and the created row
    r_ok = client.post(
        "/platforms",
        json={"name": name, "kind": "brokerage"},
        headers={"MONAI_API_KEY": api_key},
    )
    assert r_ok.status_code == 201, r_ok.text
    body = r_ok.json()
    assert body["name"] == name
    assert body["kind"] == "brokerage"
    assert "id" in body

    # Cleanup
    _db = SessionLocal()
    try:
        row = _db.query(Platform).filter(Platform.name == name).first()
        if row:
            _db.query(AuditLog).filter(
                AuditLog.entity == "platform", AuditLog.entity_id == row.id
            ).delete()
            _db.delete(row)
            _db.commit()
    finally:
        _db.close()


# ---------------------------------------------------------------------------
# INV-01/06/07: portfolio events, holding override, composed summary (Plan 05-03)
# ---------------------------------------------------------------------------


def _cleanup_ticker(db, ticker: str) -> None:
    """Remove any holding/events/price_cache/audit rows for a ticker."""
    from backend.models import Holding, PortfolioEvent, PriceCache, AuditLog

    hids = [h.id for h in db.query(Holding).filter(Holding.ticker == ticker).all()]
    if hids:
        db.query(AuditLog).filter(
            AuditLog.entity == "holding", AuditLog.entity_id.in_(hids)
        ).delete(synchronize_session=False)
    eids = [e.id for e in db.query(PortfolioEvent).filter(PortfolioEvent.ticker == ticker).all()]
    if eids:
        db.query(AuditLog).filter(
            AuditLog.entity == "portfolio_event", AuditLog.entity_id.in_(eids)
        ).delete(synchronize_session=False)
    db.query(PortfolioEvent).filter(PortfolioEvent.ticker == ticker).delete(synchronize_session=False)
    db.query(Holding).filter(Holding.ticker == ticker).delete(synchronize_session=False)
    db.query(PriceCache).filter(PriceCache.ticker == ticker).delete(synchronize_session=False)
    db.commit()


def test_apply_add_portfolio_event_audits_and_recomputes(db_session):
    """apply_add_portfolio_event inserts a portfolio_events row (INV-07), writes
    one AuditLog(entity="portfolio_event"), and recomputes the holding's
    qty/avg_cost from the ledger (D-01)."""
    from decimal import Decimal
    from backend.writes import apply_add_portfolio_event
    from backend.models import PortfolioEvent, Holding, AuditLog

    ticker = "EVTTEST01"
    _cleanup_ticker(db_session, ticker)

    before_audit = int(
        db_session.execute(
            text("SELECT COUNT(*) FROM audit_log WHERE entity = 'portfolio_event'")
        ).scalar() or 0
    )

    apply_add_portfolio_event(db_session, {
        "ticker": ticker, "event_type": "buy",
        "quantity": 10, "price": 100, "date": "2024-01-10",
    })
    db_session.commit()

    # Event row exists
    ev = db_session.query(PortfolioEvent).filter(PortfolioEvent.ticker == ticker).one()
    assert ev.event_type == "buy"

    # Holding recomputed from the ledger (D-01)
    h = db_session.query(Holding).filter(Holding.ticker == ticker).one()
    assert h.quantity == Decimal("10")
    assert h.avg_cost == Decimal("100")

    # Exactly one new portfolio_event AuditLog row
    after_audit = int(
        db_session.execute(
            text("SELECT COUNT(*) FROM audit_log WHERE entity = 'portfolio_event'")
        ).scalar() or 0
    )
    assert after_audit == before_audit + 1

    _cleanup_ticker(db_session, ticker)


def test_apply_add_portfolio_event_sets_platform_and_asset_type_without_clobber(db_session):
    """A buy event carrying platform_id/asset_type sets them on the recomputed
    holding; a later event on the same ticker with those fields omitted must
    NOT null out the existing assignment (set-when-provided semantics)."""
    from backend.writes import apply_add_portfolio_event
    from backend.models import Holding, Platform

    ticker = "EVTTEST02"
    _cleanup_ticker(db_session, ticker)
    plat_id = _make_platform(db_session, name="Test Platform EVT")

    try:
        # First buy: platform_id + asset_type provided -> land on the holding.
        apply_add_portfolio_event(db_session, {
            "ticker": ticker, "event_type": "buy",
            "quantity": 10, "price": 100, "date": "2024-01-10",
            "platform_id": plat_id, "asset_type": "crypto",
        })
        db_session.commit()

        h = db_session.query(Holding).filter(Holding.ticker == ticker).one()
        assert h.platform_id == plat_id
        assert h.asset_type == "crypto"

        # Second buy: platform_id/asset_type omitted -> must NOT clobber existing.
        apply_add_portfolio_event(db_session, {
            "ticker": ticker, "event_type": "buy",
            "quantity": 5, "price": 110, "date": "2024-01-11",
        })
        db_session.commit()

        h = db_session.query(Holding).filter(Holding.ticker == ticker).one()
        assert h.platform_id == plat_id
        assert h.asset_type == "crypto"
    finally:
        _cleanup_ticker(db_session, ticker)
        plat = db_session.get(Platform, plat_id)
        if plat is not None:
            db_session.delete(plat)
            db_session.commit()


def test_portfolio_event_rejects_unknown_type(client, api_key):
    """POST /portfolio-events with event_type 'gift' → 422 at the schema
    boundary, BEFORE any recompute runs (T-05-03-EVT)."""
    from backend.db import engine
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception as e:
        pytest.skip(f"Postgres not available: {e}")

    r = client.post(
        "/portfolio-events",
        json={"ticker": "GIFTTEST", "event_type": "gift",
              "quantity": 1, "price": 100, "date": "2024-01-10"},
        headers={"MONAI_API_KEY": api_key},
    )
    assert r.status_code == 422, r.text

    # No holding was created as a side effect of the rejected request.
    from backend.db import SessionLocal
    from backend.models import Holding
    _db = SessionLocal()
    try:
        assert _db.query(Holding).filter(Holding.ticker == "GIFTTEST").first() is None
    finally:
        _db.close()


def test_portfolio_event_requires_api_key(client, api_key):
    """POST /portfolio-events without the key header → 401 (T-05-03-AC).

    The api_key fixture configures a server key so the fail-closed 503 guard is
    satisfied; omitting the request header then exercises the 401 path.
    """
    r = client.post(
        "/portfolio-events",
        json={"ticker": "NOAUTHEVT", "event_type": "buy",
              "quantity": 1, "price": 100, "date": "2024-01-10"},
    )
    assert r.status_code == 401


def test_apply_edit_and_delete_holding_audit(db_session):
    """apply_edit_holding and apply_delete_holding (D-03 direct override) each
    write one AuditLog(entity="holding") row."""
    from backend.writes import apply_add_holding, apply_edit_holding, apply_delete_holding
    from backend.models import Holding, AuditLog

    ticker = "OVERRIDE01"
    _cleanup_ticker(db_session, ticker)

    h = apply_add_holding(db_session, {
        "ticker": ticker, "quantity": 5, "avg_cost": 200, "currency": "IDR",
        "asset_type": "crypto",
    })
    db_session.commit()
    db_session.refresh(h)
    h_id = h.id

    edit_before = int(
        db_session.execute(
            text("SELECT COUNT(*) FROM audit_log WHERE entity='holding' AND operation='edit'")
        ).scalar() or 0
    )
    apply_edit_holding(db_session, h_id, {"quantity": 7}, {"id": h_id, "quantity": "5"})
    db_session.commit()
    edit_after = int(
        db_session.execute(
            text("SELECT COUNT(*) FROM audit_log WHERE entity='holding' AND operation='edit'")
        ).scalar() or 0
    )
    assert edit_after == edit_before + 1

    del_before = int(
        db_session.execute(
            text("SELECT COUNT(*) FROM audit_log WHERE entity='holding' AND operation='delete'")
        ).scalar() or 0
    )
    apply_delete_holding(db_session, h_id, {"id": h_id, "ticker": ticker})
    db_session.commit()
    del_after = int(
        db_session.execute(
            text("SELECT COUNT(*) FROM audit_log WHERE entity='holding' AND operation='delete'")
        ).scalar() or 0
    )
    assert del_after == del_before + 1
    assert db_session.get(Holding, h_id) is None

    _cleanup_ticker(db_session, ticker)


def test_investments_summary_grouped_payload(db_session):
    """GET /investments/summary composes holdings grouped by platform (with an
    'unassigned' group for null platform_id), each with unrealized/realized P&L,
    plus total_value and an as_of timestamp (D-05, INV-06)."""
    from decimal import Decimal
    from backend.portfolio import portfolio_summary
    from backend.models import PriceCache

    ticker = "SUMMARY01"
    _cleanup_ticker(db_session, ticker)

    # Seed a position from the ledger: buy 10 @ 100 then sell 4 @ 250.
    from backend.writes import apply_add_portfolio_event
    apply_add_portfolio_event(db_session, {
        "ticker": ticker, "event_type": "buy", "quantity": 10, "price": 100, "date": "2024-01-01"})
    apply_add_portfolio_event(db_session, {
        "ticker": ticker, "event_type": "sell", "quantity": 4, "price": 250, "date": "2024-01-02"})
    # A current price so unrealized is non-null.
    db_session.add(PriceCache(ticker=ticker, price=Decimal("300"), currency="IDR", source="manual"))
    db_session.commit()

    summary = portfolio_summary(db_session)

    assert "as_of" in summary and summary["as_of"]
    assert "total_value" in summary
    assert "total_unrealized_pnl" in summary
    assert "total_realized_pnl" in summary

    # Our ticker lands in the unassigned group (null platform_id).
    rows = [
        row for g in summary["groups"] for row in g["holdings"]
        if row["ticker"] == ticker
    ]
    assert len(rows) == 1, f"expected one summary row for {ticker}, got {rows}"
    row = rows[0]
    # qty 6 @ avg_cost 100; current 300 → unrealized (300-100)*6 = 1200
    assert row["quantity"] == Decimal("6")
    assert row["avg_cost"] == Decimal("100")
    assert row["current_price"] == Decimal("300")
    assert row["unrealized_pnl"] == Decimal("1200")
    # realized (250-100)*4 = 600
    assert row["realized_pnl"] == Decimal("600")
    # This holding has null platform_id → it must sit in the unassigned group.
    unassigned = [g for g in summary["groups"] if g["platform_id"] is None]
    assert unassigned and any(
        r["ticker"] == ticker for r in unassigned[0]["holdings"]
    )

    _cleanup_ticker(db_session, ticker)


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
