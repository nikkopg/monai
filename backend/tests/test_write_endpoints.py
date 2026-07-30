"""
Direct REST write-endpoint tests for Phase 14's 5 new operations
(CHAT-09/XFER-01..04/ACCT-02).

Phase-14 Plan 01 (Wave 0, RED-first): every route below DOES NOT EXIST YET.
A POST to a nonexistent route returns 404 — the intended RED signal, mirroring
Phase 13's lazy-import RED idiom on the agent side. These tests turn GREEN
once Plan 14-03 adds the routes.

Fixtures `client`/`api_key` come from conftest.py (session-scoped TestClient +
monkeypatched MONAI_API_KEY). `db_available`/`db_session` are defined locally,
mirroring test_account_crud.py.

Requires a live Postgres. Tests seed + clean up their own `zz14test-`-prefixed
rows.
"""

from decimal import Decimal

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


# ---------------------------------------------------------------------------
# Seed / cleanup helpers (mirror test_write_tools.py's idiom)
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


def _make_platform(db, name: str) -> int:
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


def _cleanup_platform(db, platform_id: int) -> None:
    from backend.models import Platform
    plat = db.get(Platform, platform_id)
    if plat is not None:
        db.delete(plat)
        db.commit()


def _cleanup_ticker(db, ticker: str) -> None:
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


# ---------------------------------------------------------------------------
# Happy-path tests — 201, RED (404) until Plan 14-03 adds the route
# ---------------------------------------------------------------------------

def test_post_transfer(client, api_key, db_session):
    """POST /transactions/transfer -> 201, both legs paired (XFER-01)."""
    from backend.models import Transaction

    name_a, name_b = "zz14test-RestTransferA", "zz14test-RestTransferB"
    acc_a = _make_account(db_session, name_a)
    acc_b = _make_account(db_session, name_b)
    try:
        resp = client.post(
            "/transactions/transfer",
            json={
                "from_account": name_a, "to_account": name_b, "amount": 100000,
                "currency": "IDR", "date": "2024-03-10", "notes": "rest transfer",
            },
            headers={"MONAI_API_KEY": api_key},
        )
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert "leg_a_id" in data and "leg_b_id" in data and "transfer_pair_id" in data

        db_session.expire_all()
        rows = db_session.query(Transaction).filter(Transaction.account_id.in_([acc_a, acc_b])).all()
        assert len(rows) == 2, f"expected exactly 2 paired legs, got {len(rows)}"
        assert all(r.is_transfer for r in rows)
        pair_ids = {r.transfer_pair_id for r in rows}
        assert len(pair_ids) == 1 and None not in pair_ids
    finally:
        db_session.rollback()
        _cleanup_account(db_session, name_a)
        _cleanup_account(db_session, name_b)


def test_post_investment_transfer(client, api_key, db_session):
    """POST /transactions/investment-transfer -> 201, cash leg + linked
    PortfolioEvent (ticker=='CASH', deposit sentinel, RESEARCH Q1) (XFER-02)."""
    from backend.models import Transaction, PortfolioEvent, AuditLog, Holding

    name = "zz14test-RestInvestSource"
    ticker = "CASH"
    acc_id = _make_account(db_session, name)
    plat_id = _make_platform(db_session, "zz14test-RestInvestPlatform")
    try:
        resp = client.post(
            "/transactions/investment-transfer",
            json={
                "from_account": name, "platform_id": plat_id, "amount": 500000,
                "currency": "IDR", "date": "2024-03-11",
            },
            headers={"MONAI_API_KEY": api_key},
        )
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"

        db_session.expire_all()
        tx = db_session.query(Transaction).filter(Transaction.account_id == acc_id).one()
        assert tx.is_transfer is True
        assert tx.amount == Decimal("-500000")

        ev = db_session.query(PortfolioEvent).filter(
            PortfolioEvent.platform_id == plat_id, PortfolioEvent.ticker == ticker
        ).one()
        assert ev.source_account_id == acc_id
        assert ev.event_type == "deposit"
    finally:
        db_session.rollback()
        # CASH is a shared production sentinel ticker — scope cleanup to this
        # test's own platform_id, never a global ticker purge.
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


def test_post_funded_buy(client, api_key, db_session):
    """POST /portfolio-events/funded-buy -> 201, cash leg debited + 'buy'
    event + holding recomputed (XFER-03)."""
    from backend.models import Transaction, PortfolioEvent, Holding

    name = "zz14test-RestFundedBuySource"
    ticker = "ZZ14RESTBUY"
    acc_id = _make_account(db_session, name)
    plat_id = _make_platform(db_session, "zz14test-RestFundedBuyPlatform")
    _cleanup_ticker(db_session, ticker)
    try:
        resp = client.post(
            "/portfolio-events/funded-buy",
            json={
                "source_account_name": name, "platform_id": plat_id, "ticker": ticker,
                "quantity": 10, "price": 100000, "cash_amount": 1000000,
                "cash_currency": "IDR", "event_currency": "IDR", "date": "2024-03-12",
            },
            headers={"MONAI_API_KEY": api_key},
        )
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"

        db_session.expire_all()
        tx = db_session.query(Transaction).filter(Transaction.account_id == acc_id).one()
        assert tx.amount == Decimal("-1000000")
        assert tx.is_transfer is True

        ev = db_session.query(PortfolioEvent).filter(PortfolioEvent.ticker == ticker).one()
        assert ev.event_type == "buy"
        assert ev.source_account_id == acc_id

        h = db_session.query(Holding).filter(
            Holding.ticker == ticker, Holding.platform_id == plat_id
        ).one()
        assert h.quantity == Decimal("10")
    finally:
        db_session.rollback()
        _cleanup_ticker(db_session, ticker)
        _cleanup_account(db_session, name)
        _cleanup_platform(db_session, plat_id)


def test_post_funded_sell(client, api_key, db_session):
    """POST /portfolio-events/funded-sell -> 201, cash leg credited + 'sell'
    event (XFER-03)."""
    from backend.models import Transaction, PortfolioEvent

    name = "zz14test-RestFundedSellDest"
    ticker = "ZZ14RESTSELL"
    acc_id = _make_account(db_session, name)
    plat_id = _make_platform(db_session, "zz14test-RestFundedSellPlatform")
    _cleanup_ticker(db_session, ticker)
    try:
        resp = client.post(
            "/portfolio-events/funded-sell",
            json={
                "source_account_name": name, "platform_id": plat_id, "ticker": ticker,
                "quantity": 10, "price": 100000, "cash_amount": 1000000,
                "cash_currency": "IDR", "event_currency": "IDR", "date": "2024-03-13",
            },
            headers={"MONAI_API_KEY": api_key},
        )
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"

        db_session.expire_all()
        tx = db_session.query(Transaction).filter(Transaction.account_id == acc_id).one()
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


def test_post_adjust_balance(client, api_key, db_session):
    """POST /accounts/{id}/adjust-balance -> 201, single Adjustment
    transaction with the correct delta (ACCT-02)."""
    import datetime as _dt
    from backend.models import Transaction

    name = "zz14test-RestAdjustAccount"
    acc_id = _make_account(db_session, name)
    try:
        db_session.add(Transaction(
            date=_dt.datetime(2024, 3, 14, 12, 0, 0), amount=200000, currency="IDR",
            category="Salary", account_id=acc_id, is_transfer=False,
        ))
        db_session.add(Transaction(
            date=_dt.datetime(2024, 3, 15, 12, 0, 0), amount=50000, currency="IDR",
            category=None, account_id=acc_id, is_transfer=True,
        ))
        db_session.commit()

        current = Decimal(str(db_session.execute(
            text("SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE account_id = :id"),
            {"id": acc_id},
        ).scalar()))
        target = current + Decimal("77777")
        expected_delta = target - current

        resp = client.post(
            f"/accounts/{acc_id}/adjust-balance",
            json={"target_balance": float(target)},
            headers={"MONAI_API_KEY": api_key},
        )
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"

        db_session.expire_all()
        all_rows = db_session.query(Transaction).filter(Transaction.account_id == acc_id).all()
        assert len(all_rows) == 3, f"expected exactly one new adjustment row, got {len(all_rows) - 2} new row(s)"

        adj_rows = [r for r in all_rows if r.category == "Adjustment"]
        assert len(adj_rows) == 1
        assert adj_rows[0].amount == expected_delta
    finally:
        db_session.rollback()
        _cleanup_account(db_session, name)


# ---------------------------------------------------------------------------
# Input validation / auth tests — pin the V5/auth threat controls
# ---------------------------------------------------------------------------

def test_transfer_rejects_negative_amount(client, api_key, db_session):
    """POST /transactions/transfer with amount=-1 -> 422 (V5, schema-level
    Field(gt=0) guard — the apply_* primitive owns sign normalization, the
    schema must reject a negative/zero magnitude before it ever runs)."""
    name_a, name_b = "zz14test-NegAmtA", "zz14test-NegAmtB"
    acc_a = _make_account(db_session, name_a)
    acc_b = _make_account(db_session, name_b)
    try:
        resp = client.post(
            "/transactions/transfer",
            json={
                "from_account": name_a, "to_account": name_b, "amount": -1,
                "currency": "IDR", "date": "2024-03-16",
            },
            headers={"MONAI_API_KEY": api_key},
        )
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"
    finally:
        db_session.rollback()
        _cleanup_account(db_session, name_a)
        _cleanup_account(db_session, name_b)


def test_funded_buy_rejects_zero_cash_amount(client, api_key, db_session):
    """POST /portfolio-events/funded-buy with cash_amount=0 -> 422 (V5)."""
    name = "zz14test-ZeroCashSrc"
    ticker = "ZZ14ZEROCASH"
    acc_id = _make_account(db_session, name)
    plat_id = _make_platform(db_session, "zz14test-ZeroCashPlatform")
    try:
        resp = client.post(
            "/portfolio-events/funded-buy",
            json={
                "source_account_name": name, "platform_id": plat_id, "ticker": ticker,
                "quantity": 10, "price": 100000, "cash_amount": 0,
                "cash_currency": "IDR", "event_currency": "IDR", "date": "2024-03-17",
            },
            headers={"MONAI_API_KEY": api_key},
        )
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"
    finally:
        db_session.rollback()
        _cleanup_account(db_session, name)
        _cleanup_platform(db_session, plat_id)


def test_transfer_missing_api_key_401(client, api_key, db_session):
    """POST /transactions/transfer without MONAI_API_KEY header -> 401 (V2).

    Uses the api_key fixture to ensure _CONFIGURED_KEY is non-empty
    (fail-closed guard) but omits the header from the request, mirroring
    test_proposals.py::test_confirm_requires_api_key."""
    resp = client.post(
        "/transactions/transfer",
        json={
            "from_account": "zz14test-NoKeyA", "to_account": "zz14test-NoKeyB",
            "amount": 1000, "currency": "IDR", "date": "2024-03-18",
        },
    )
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"
