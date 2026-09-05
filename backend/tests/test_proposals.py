"""
Proposal lifecycle tests — confirm/reject/expire/replay/audit (CHAT-05, CHAT-06).

Integration tests against the live Postgres. Each test creates its own proposal
(and seed data where needed) and cleans up after itself.
"""

import datetime
import uuid
from decimal import Decimal

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


def _make_platform(db, name: str = "ZZ Test Platform CH01") -> int:
    from backend.models import Platform
    import secrets
    platform = Platform(name=f"{name} {secrets.token_hex(4)}", kind="exchange")
    db.add(platform)
    db.commit()
    db.refresh(platform)
    return platform.id


def test_confirm_add_holding_persists_platform_id(client, api_key, db_session):
    """CH-01 regression closure: a chat-initiated add_holding proposal carrying
    platform_id, when confirmed via _execute_proposal_payload, must write a
    Holding WITH platform_id set — no NOT NULL IntegrityError (Pitfall 2, the
    confirm-time write is the actual bug; delegating to apply_add_holding fixes it).
    """
    from backend.models import Holding, Proposal
    import secrets

    platform_id = _make_platform(db_session)

    token = secrets.token_urlsafe(32)
    expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=15)
    after = {
        "ticker": "ZZCH01",
        "quantity": "1",
        "avg_cost": "100",
        "platform_id": platform_id,
        "purchase_date": None,
        "currency": "IDR",
        "asset_type": "crypto",
    }
    payload = {"operation": "add_holding", "rows": [{"before": None, "after": after}]}
    p = Proposal(
        token=token, operation="add_holding", payload=payload,
        status="pending", expires_at=expires_at,
    )
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)

    audit_before = int(
        db_session.execute(
            text("SELECT COUNT(*) FROM audit_log WHERE entity='holding'")
        ).scalar() or 0
    )

    resp = client.post(
        f"/proposals/{p.id}/confirm",
        json={"token": token},
        headers={"MONAI_API_KEY": api_key},
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    assert resp.json()["status"] == "confirmed"

    db_session.expire_all()
    holding = db_session.query(Holding).filter(Holding.ticker == "ZZCH01").one()
    assert holding.platform_id == platform_id, (
        "CH-01 regression: platform_id not persisted on chat-confirmed add_holding"
    )

    # Audit trail preserved through delegation (T-07-05-AUD)
    audit_after = int(
        db_session.execute(
            text("SELECT COUNT(*) FROM audit_log WHERE entity='holding' AND entity_id=:id"),
            {"id": holding.id},
        ).scalar() or 0
    )
    assert audit_after >= 1, "Audit-log row missing after delegated add_holding confirm"

    # Cleanup
    from backend.models import Platform
    db_session.delete(holding)
    platform = db_session.get(Platform, platform_id)
    if platform:
        db_session.delete(platform)
    db_session.commit()


def test_confirm_edit_holding_via_delegation(client, api_key, db_session):
    """edit_holding confirm delegates to apply_edit_holding — quantity updates, audit row written."""
    from backend.models import Holding, Platform, Proposal
    import secrets

    platform_id = _make_platform(db_session)
    holding = Holding(
        ticker="ZZCH01EDIT", quantity=1, avg_cost=100, currency="IDR",
        asset_type="crypto", platform_id=platform_id,
    )
    db_session.add(holding)
    db_session.commit()
    db_session.refresh(holding)

    token = secrets.token_urlsafe(32)
    expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=15)
    before = {"quantity": "1"}
    after = {"quantity": "5"}
    payload = {
        "operation": "edit_holding",
        "rows": [{"id": holding.id, "before": before, "after": after}],
    }
    p = Proposal(
        token=token, operation="edit_holding", payload=payload,
        status="pending", expires_at=expires_at,
    )
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)

    resp = client.post(
        f"/proposals/{p.id}/confirm",
        json={"token": token},
        headers={"MONAI_API_KEY": api_key},
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    db_session.expire_all()
    updated = db_session.get(Holding, holding.id)
    from decimal import Decimal
    assert updated.quantity == Decimal("5")

    audit_count = int(
        db_session.execute(
            text("SELECT COUNT(*) FROM audit_log WHERE entity='holding' AND entity_id=:id AND operation='edit'"),
            {"id": holding.id},
        ).scalar() or 0
    )
    assert audit_count >= 1, "Audit-log row missing after delegated edit_holding confirm"

    # Cleanup
    db_session.delete(updated)
    platform = db_session.get(Platform, platform_id)
    if platform:
        db_session.delete(platform)
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


# ---------------------------------------------------------------------------
# Phase 14 Plan 01: RED-first propose->confirm integration tests for the 5
# new operations (CHAT-09/XFER-01..04/ACCT-02). Every propose_* function
# targeted below DOES NOT EXIST YET — each test imports its target
# function-locally (the Phase-13 lazy-import RED idiom) and is EXPECTED to
# fail RED (ImportError) until Plan 14-02 registers the tools. Do not wire
# tools.py/query.py/main.py here.
# ---------------------------------------------------------------------------


def _make_account(db, name: str) -> int:
    from backend.models import Account
    existing = db.query(Account).filter(Account.name == name).first()
    if existing:
        db.delete(existing)
        db.commit()
    acc = Account(name=name, type="liquid", currency="IDR")
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc.id


def _cleanup_account(db, name: str) -> None:
    """Remove an account and every dependent transaction/audit-log row
    (mirrors test_write_tools.py's _cleanup_account)."""
    from backend.models import Account, AuditLog, Transaction
    acc = db.query(Account).filter(Account.name == name).first()
    if acc is None:
        return
    tx_ids = [t.id for t in db.query(Transaction).filter(Transaction.account_id == acc.id).all()]
    if tx_ids:
        db.query(AuditLog).filter(
            AuditLog.entity == "transaction", AuditLog.entity_id.in_(tx_ids)
        ).delete(synchronize_session=False)
        db.query(Transaction).filter(Transaction.id.in_(tx_ids)).delete(synchronize_session=False)
    db.query(AuditLog).filter(AuditLog.entity == "account", AuditLog.entity_id == acc.id).delete()
    db.delete(acc)
    db.commit()


def _cleanup_ticker(db, ticker: str) -> None:
    """Remove any holding/events/price_cache/audit rows for a ticker (mirrors
    test_write_tools.py's _cleanup_ticker)."""
    from backend.models import AuditLog, Holding, PortfolioEvent, PriceCache
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


def _cleanup_platform(db, platform_id: int) -> None:
    from backend.models import Platform
    plat = db.get(Platform, platform_id)
    if plat is not None:
        db.delete(plat)
        db.commit()


def test_confirm_transfer_writes_both_legs(client, api_key, db_session):
    """propose_add_transfer -> confirm -> exactly 2 paired Transaction rows,
    both is_transfer=True, sharing transfer_pair_id == leg A's own id, leg
    amounts are -abs/+abs of the magnitude (XFER-01). RED until Plan 14-02."""
    from backend.models import Transaction

    name_a, name_b = "zz14test-TransferA", "zz14test-TransferB"
    acc_a = _make_account(db_session, name_a)
    acc_b = _make_account(db_session, name_b)
    try:
        from backend.tools import propose_add_transfer  # RED: not implemented until Plan 14-02

        result = propose_add_transfer(
            from_account=name_a, to_account=name_b, amount=100000, currency="IDR",
            date="2024-03-01", notes="test transfer",
        )
        resp = client.post(
            f"/proposals/{result['proposal_id']}/confirm",
            json={"token": result["proposal_token"]},
            headers={"MONAI_API_KEY": api_key},
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

        db_session.expire_all()
        rows = db_session.query(Transaction).filter(Transaction.account_id.in_([acc_a, acc_b])).all()
        assert len(rows) == 2, f"expected exactly 2 paired legs, got {len(rows)}"
        assert all(r.is_transfer for r in rows), "both legs must be tagged is_transfer=true"

        pair_ids = {r.transfer_pair_id for r in rows}
        assert len(pair_ids) == 1 and None not in pair_ids, (
            f"both legs must share one non-null transfer_pair_id, got {pair_ids}"
        )

        by_account = {r.account_id: r for r in rows}
        assert by_account[acc_a].amount == Decimal("-100000"), "source leg must be debited (-abs magnitude)"
        assert by_account[acc_b].amount == Decimal("100000"), "destination leg must be credited (+abs magnitude)"
    finally:
        db_session.rollback()
        _cleanup_account(db_session, name_a)
        _cleanup_account(db_session, name_b)


def test_confirm_investment_transfer_links_event(client, api_key, db_session):
    """propose_add_investment_transfer -> confirm -> 1 cash Transaction
    (is_transfer=True, negative amount) + 1 PortfolioEvent whose
    source_account_id == the cash leg's account_id, and NO new synthetic
    accounts row. Deposit sentinel: ticker=='CASH', event_type=='deposit'
    (RESEARCH Q1 resolution, XFER-02). RED until Plan 14-02."""
    from backend.models import Account, Transaction, PortfolioEvent

    name = "zz14test-InvestSource"
    ticker = "CASH"
    acc_id = _make_account(db_session, name)
    plat_id = _make_platform_local(db_session, "zz14test-InvestPlatform")
    try:
        accounts_before = int(db_session.execute(text("SELECT COUNT(*) FROM accounts")).scalar() or 0)

        from backend.tools import propose_add_investment_transfer  # RED: not implemented until Plan 14-02

        result = propose_add_investment_transfer(
            from_account=name, platform_id=plat_id, amount=500000, currency="IDR",
            date="2024-03-02", notes="fund platform",
        )
        resp = client.post(
            f"/proposals/{result['proposal_id']}/confirm",
            json={"token": result["proposal_token"]},
            headers={"MONAI_API_KEY": api_key},
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

        db_session.expire_all()
        tx = db_session.query(Transaction).filter(Transaction.account_id == acc_id).one()
        assert tx.is_transfer is True
        assert tx.amount == Decimal("-500000")

        ev = db_session.query(PortfolioEvent).filter(
            PortfolioEvent.platform_id == plat_id, PortfolioEvent.ticker == ticker
        ).one()
        assert ev.source_account_id == tx.account_id, "event must link back to the funding account (D-05)"
        assert ev.event_type == "deposit"

        accounts_after = int(db_session.execute(text("SELECT COUNT(*) FROM accounts")).scalar() or 0)
        assert accounts_after == accounts_before, "no synthetic accounts row for the investment side (D-05)"
    finally:
        db_session.rollback()
        # CASH is a shared production sentinel ticker (RESEARCH Q1) — scope
        # cleanup to this test's own platform_id, never a global ticker purge.
        from backend.models import AuditLog, Holding
        eids = [e.id for e in db_session.query(PortfolioEvent).filter(
            PortfolioEvent.platform_id == plat_id, PortfolioEvent.ticker == ticker
        ).all()]
        if eids:
            db_session.query(AuditLog).filter(
                AuditLog.entity == "portfolio_event", AuditLog.entity_id.in_(eids)
            ).delete(synchronize_session=False)
            db_session.query(PortfolioEvent).filter(PortfolioEvent.id.in_(eids)).delete(synchronize_session=False)
        hids = [h.id for h in db_session.query(Holding).filter(
            Holding.platform_id == plat_id, Holding.ticker == ticker
        ).all()]
        if hids:
            db_session.query(AuditLog).filter(
                AuditLog.entity == "holding", AuditLog.entity_id.in_(hids)
            ).delete(synchronize_session=False)
            db_session.query(Holding).filter(Holding.id.in_(hids)).delete(synchronize_session=False)
        db_session.commit()
        _cleanup_platform(db_session, plat_id)
        _cleanup_account(db_session, name)


def test_confirm_funded_buy_writes_both_sides(client, api_key, db_session):
    """propose_add_funded_buy -> confirm -> cash Transaction amount ==
    Decimal(str(-cash_amount)) (DEBIT, is_transfer=True), 'buy' PortfolioEvent
    linked via source_account_id, and the (ticker, platform_id) Holding
    recomputed (XFER-03). RED until Plan 14-02."""
    from backend.models import Transaction, PortfolioEvent, Holding

    name = "zz14test-FundedBuySource"
    ticker = "ZZ14FUNDEDBUY"
    acc_id = _make_account(db_session, name)
    plat_id = _make_platform_local(db_session, "zz14test-FundedBuyPlatform")
    _cleanup_ticker(db_session, ticker)
    try:
        from backend.tools import propose_add_funded_buy  # RED: not implemented until Plan 14-02

        result = propose_add_funded_buy(
            source_account_name=name, platform_id=plat_id, ticker=ticker,
            quantity=10, price=100000, cash_amount=1000000, cash_currency="IDR",
            event_currency="IDR", date="2024-03-03",
        )
        resp = client.post(
            f"/proposals/{result['proposal_id']}/confirm",
            json={"token": result["proposal_token"]},
            headers={"MONAI_API_KEY": api_key},
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

        db_session.expire_all()
        tx = db_session.query(Transaction).filter(Transaction.account_id == acc_id).one()
        assert tx.amount == Decimal(str(-1000000)), "cash leg must DEBIT the source (buy)"
        assert tx.is_transfer is True

        ev = db_session.query(PortfolioEvent).filter(PortfolioEvent.ticker == ticker).one()
        assert ev.event_type == "buy"
        assert ev.source_account_id == acc_id

        h = db_session.query(Holding).filter(
            Holding.ticker == ticker, Holding.platform_id == plat_id
        ).one()
        assert h.quantity == Decimal("10"), "holding must be recomputed from the ledger (D-06)"
    finally:
        db_session.rollback()
        _cleanup_ticker(db_session, ticker)
        _cleanup_account(db_session, name)
        _cleanup_platform(db_session, plat_id)


def test_confirm_funded_sell_writes_both_sides(client, api_key, db_session):
    """propose_add_funded_sell -> confirm -> cash Transaction amount
    positive (CREDIT), 'sell' PortfolioEvent linked via source_account_id
    (XFER-03). RED until Plan 14-02."""
    from backend.models import Transaction, PortfolioEvent

    name = "zz14test-FundedSellDest"
    ticker = "ZZ14FUNDEDSELL"
    acc_id = _make_account(db_session, name)
    plat_id = _make_platform_local(db_session, "zz14test-FundedSellPlatform")
    _cleanup_ticker(db_session, ticker)
    try:
        from backend.tools import propose_add_funded_sell  # RED: not implemented until Plan 14-02

        result = propose_add_funded_sell(
            source_account_name=name, platform_id=plat_id, ticker=ticker,
            quantity=10, price=100000, cash_amount=1000000, cash_currency="IDR",
            event_currency="IDR", date="2024-03-04",
        )
        resp = client.post(
            f"/proposals/{result['proposal_id']}/confirm",
            json={"token": result["proposal_token"]},
            headers={"MONAI_API_KEY": api_key},
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

        db_session.expire_all()
        tx = db_session.query(Transaction).filter(Transaction.account_id == acc_id).one()
        # sell CREDITS the destination — positive, the sign that distinguishes it from a funded buy
        assert tx.amount == Decimal("1000000")
        assert tx.is_transfer is True

        ev = db_session.query(PortfolioEvent).filter(PortfolioEvent.ticker == ticker).one()
        assert ev.event_type == "sell"
        assert ev.source_account_id == acc_id
    finally:
        db_session.rollback()
        _cleanup_ticker(db_session, ticker)
        _cleanup_account(db_session, name)
        _cleanup_platform(db_session, plat_id)


def test_confirm_balance_adjustment(client, api_key, db_session):
    """propose_add_balance_adjustment -> confirm -> exactly ONE new
    Transaction tagged category='Adjustment' and is_transfer=True whose
    amount == target_balance minus the account's current UNFILTERED
    SUM(amount) (ACCT-02/D-07). RED until Plan 14-02."""
    import datetime as _dt
    from backend.models import Transaction

    name = "zz14test-AdjustAccount"
    acc_id = _make_account(db_session, name)
    try:
        db_session.add(Transaction(
            date=_dt.datetime(2024, 3, 1, 12, 0, 0), amount=200000, currency="IDR",
            category="Salary", account_id=acc_id, is_transfer=False,
        ))
        db_session.add(Transaction(
            date=_dt.datetime(2024, 3, 2, 12, 0, 0), amount=50000, currency="IDR",
            category=None, account_id=acc_id, is_transfer=True,
        ))
        db_session.commit()

        current = Decimal(str(db_session.execute(
            text("SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE account_id = :id"),
            {"id": acc_id},
        ).scalar()))
        target = current + Decimal("77777")
        expected_delta = target - current

        from backend.tools import propose_add_balance_adjustment  # RED: not implemented until Plan 14-02

        result = propose_add_balance_adjustment(account_id=acc_id, target_balance=float(target))
        resp = client.post(
            f"/proposals/{result['proposal_id']}/confirm",
            json={"token": result["proposal_token"]},
            headers={"MONAI_API_KEY": api_key},
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

        db_session.expire_all()
        all_rows = db_session.query(Transaction).filter(Transaction.account_id == acc_id).all()
        assert len(all_rows) == 3, f"expected exactly one new adjustment row, got {len(all_rows) - 2} new row(s)"

        adj_rows = [r for r in all_rows if r.category == "Adjustment"]
        assert len(adj_rows) == 1, "expected exactly one 'Adjustment'-tagged row"
        assert adj_rows[0].amount == expected_delta
    finally:
        db_session.rollback()
        _cleanup_account(db_session, name)


def test_confirm_malformed_funded_buy_returns_422(client, api_key, db_session):
    """A confirm-time payload for operation='add_funded_buy' missing the
    required 'ticker' key must surface as a clean 422, never an unhandled
    KeyError -> 500 (Pitfall 3, autonomous decision 4). Stays green trivially
    pre-14-02 (unknown operation -> ValueError -> 422 via the existing
    _execute_proposal_payload else-branch) and remains the regression guard
    once 14-02 adds the dispatch branch + KeyError guard."""
    import secrets
    from backend.models import Proposal

    token = secrets.token_urlsafe(32)
    expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=15)
    after = {
        "source_account_name": "zz14test-MalformedBuySrc", "cash_currency": "IDR",
        "cash_amount": 1000000, "quantity": 10, "price": 100000,
        "platform_id": 1, "event_currency": "IDR", "date": "2024-03-05",
        # "ticker" intentionally omitted — pins the payload-shape hazard
    }
    payload = {"operation": "add_funded_buy", "rows": [{"before": None, "after": after}]}
    p = Proposal(token=token, operation="add_funded_buy", payload=payload,
                status="pending", expires_at=expires_at)
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)

    try:
        resp = client.post(
            f"/proposals/{p.id}/confirm",
            json={"token": token},
            headers={"MONAI_API_KEY": api_key},
        )
        assert resp.status_code == 422, f"Expected 422 (never 500), got {resp.status_code}: {resp.text}"
    finally:
        db_session.rollback()
        db_session.expire_all()
        leftover = db_session.get(Proposal, p.id)
        if leftover is not None:
            db_session.delete(leftover)
            db_session.commit()
        # Defensive: if a future implementation ever creates the account
        # before the KeyError fires, don't leak it.
        _cleanup_account(db_session, "zz14test-MalformedBuySrc")


def _make_platform_local(db, name: str) -> int:
    """zz14test-scoped platform seed helper (parallels test_proposals.py's
    existing `_make_platform`, but WITHOUT the random-suffix behavior so the
    returned platform_id is stable for cleanup lookups within one test)."""
    from backend.models import Platform
    existing = db.query(Platform).filter(Platform.name == name).first()
    if existing:
        db.delete(existing)
        db.commit()
    plat = Platform(name=name, kind="exchange")
    db.add(plat)
    db.commit()
    db.refresh(plat)
    return plat.id
