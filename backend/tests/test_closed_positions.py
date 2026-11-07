"""Closed-position records (quick 261107-nq6).

A funded sell that takes a position's ledger quantity to exactly zero saves one
closed record and removes the holding and its events. The sell's cash leg stays.
All values are synthetic; tickers are prefixed ZZNQ6, accounts and platforms zznq6-.
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text

T = "ZZNQ6"
TOL = Decimal("0.00000001")


def _purge(db) -> None:
    db.rollback()
    accts = "(SELECT id FROM accounts WHERE name LIKE 'zznq6-%')"
    plats = "(SELECT id FROM platforms WHERE name LIKE 'zznq6-%')"
    for sql in (
        "DELETE FROM audit_log WHERE entity = 'closed_position' AND entity_id IN "
        "(SELECT id FROM closed_positions WHERE ticker LIKE 'ZZNQ6%')",
        "DELETE FROM audit_log WHERE before->>'ticker' LIKE 'ZZNQ6%' OR after->>'ticker' LIKE 'ZZNQ6%'",
        f"DELETE FROM closed_positions WHERE ticker LIKE 'ZZNQ6%' OR platform_id IN {plats}",
        f"DELETE FROM portfolio_events WHERE ticker LIKE 'ZZNQ6%' OR platform_id IN {plats}",
        f"DELETE FROM holdings WHERE ticker LIKE 'ZZNQ6%' OR platform_id IN {plats}",
        "DELETE FROM price_cache WHERE ticker LIKE 'ZZNQ6%'",
        f"DELETE FROM audit_log WHERE entity = 'transaction' AND entity_id IN "
        f"(SELECT id FROM transactions WHERE account_id IN {accts})",
        f"DELETE FROM transactions WHERE account_id IN {accts}",
        f"DELETE FROM audit_log WHERE entity = 'account' AND entity_id IN {accts}",
        "DELETE FROM accounts WHERE name LIKE 'zznq6-%'",
        "DELETE FROM platforms WHERE name LIKE 'zznq6-%'",
        "DELETE FROM fx_rate_cache WHERE source = 'zznq6'",
    ):
        db.execute(text(sql))
    db.commit()


@pytest.fixture()
def db(db_available):
    from backend.db import SessionLocal

    s = SessionLocal()
    _purge(s)
    try:
        yield s
    finally:
        _purge(s)
        s.close()


@pytest.fixture(scope="module")
def db_available():
    from backend.db import engine

    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception as e:  # pragma: no cover
        pytest.skip(f"Postgres not available: {e}")
    return True


def _account(db, currency="IDR") -> str:
    from backend.models import Account

    name = f"zznq6-acc-{uuid.uuid4().hex[:6]}"
    db.add(Account(name=name, type="liquid", currency=currency))
    db.commit()
    return name


def _platform(db) -> int:
    from backend.models import Platform

    p = Platform(name=f"zznq6-plat-{uuid.uuid4().hex[:6]}", kind="exchange")
    db.add(p)
    db.commit()
    return p.id


def _rate(db, day: str, rate: str) -> None:
    db.execute(
        text(
            "INSERT INTO fx_rate_cache (rate_date, base_currency, quote_currency, rate, source) "
            "VALUES (:d, 'USD', 'IDR', :r, 'zznq6') ON CONFLICT DO NOTHING"
        ),
        {"d": day, "r": rate},
    )
    db.commit()


def _funded(client, kind, acc, plat, ticker, qty, price, cash, day, ccy=None):
    body = {
        "source_account_name": acc, "platform_id": plat, "ticker": ticker,
        "quantity": qty, "price": price, "cash_amount": cash, "date": day,
    }
    if ccy:
        body["event_currency"] = ccy
    return client.post(f"/portfolio-events/funded-{kind}", json=body)


def _prim_event(db, plat, ticker, etype, qty, price, day, ccy="IDR"):
    from backend.writes import apply_add_portfolio_event

    ev = apply_add_portfolio_event(db, {
        "ticker": ticker, "event_type": etype, "quantity": qty, "price": price,
        "platform_id": plat, "currency": ccy, "date": day,
    })
    db.commit()
    return ev


def _total(db) -> Decimal:
    from backend.portfolio import portfolio_summary

    db.rollback()
    return portfolio_summary(db)["total_realized_pnl"]


def _holding(db, ticker, plat):
    from backend.models import Holding

    db.rollback()
    return db.query(Holding).filter(Holding.ticker == ticker, Holding.platform_id == plat).one_or_none()


def _events(db, ticker):
    from backend.models import PortfolioEvent

    db.rollback()
    return db.query(PortfolioEvent).filter(PortfolioEvent.ticker == ticker).all()


def _closed(db, ticker):
    from backend.models import ClosedPosition

    db.rollback()
    return db.query(ClosedPosition).filter(ClosedPosition.ticker == ticker).all()


def test_full_sell_closes_position(authed, db):
    from backend.models import Account, Transaction

    acc, plat, tk = _account(db), _platform(db), f"{T}A"
    assert _funded(authed, "buy", acc, plat, tk, 10, 100, 1000, "2024-03-01").status_code == 201
    r = _funded(authed, "sell", acc, plat, tk, 10, 150, 1500, "2024-03-05")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["closed_position_id"] is not None
    assert body["portfolio_event_id"] is None
    assert _holding(db, tk, plat) is None
    assert _events(db, tk) == []
    amounts = sorted(
        (t.amount, t.is_transfer)
        for t in db.query(Transaction).join(Account, Transaction.account_id == Account.id).filter(Account.name == acc)
    )
    assert amounts == [(Decimal("-1000"), True), (Decimal("1500"), True)]
    rows = [c for c in authed.get("/closed-positions").json() if c["ticker"] == tk]
    assert len(rows) == 1
    assert rows[0]["realized_pnl"] == 500
    assert rows[0]["close_date"] == "2024-03-05"
    assert rows[0]["platform_id"] == plat
    assert rows[0]["platform_name"].startswith("zznq6-plat-")


def test_close_keeps_realized_total(authed, db):
    from backend.writes import close_position_if_flat

    acc, plat, tk = _account(db), _platform(db), f"{T}B"
    base = _total(db)
    assert _funded(authed, "buy", acc, plat, tk, 10, 100, 1000, "2024-03-01").status_code == 201
    r = _funded(authed, "sell", acc, plat, tk, 4, 150, 600, "2024-03-02")
    assert r.status_code == 201 and r.json()["closed_position_id"] is None
    _prim_event(db, plat, tk, "dividend", 1, 30, "2024-03-03")
    _prim_event(db, plat, tk, "sell", 6, 120, "2024-03-04")  # primitive: no close, row stays at zero
    before = _total(db) - base
    rec = close_position_if_flat(db, tk, plat)
    assert rec is not None
    db.commit()
    after = _total(db) - base
    assert abs(before - Decimal("350")) <= TOL
    assert abs(after - Decimal("350")) <= TOL
    assert round(before, 2) == round(after, 2)


def test_total_is_closed_plus_open(authed, db):
    acc, plat = _account(db), _platform(db)
    base = _total(db)
    closed_tk, open_tk = f"{T}C", f"{T}D"
    _funded(authed, "buy", acc, plat, closed_tk, 10, 100, 1000, "2024-03-01")
    assert _funded(authed, "sell", acc, plat, closed_tk, 10, 150, 1500, "2024-03-02").json()["closed_position_id"]
    _funded(authed, "buy", acc, plat, open_tk, 10, 100, 1000, "2024-03-01")
    _funded(authed, "sell", acc, plat, open_tk, 4, 130, 520, "2024-03-02")  # realized 120
    from backend.portfolio import portfolio_summary

    db.rollback()
    summary = portfolio_summary(db)
    assert abs((summary["total_realized_pnl"] - base) - Decimal("620")) <= TOL
    held = [h for g in summary["groups"] for h in g["holdings"] if h["ticker"] == open_tk]
    assert len(held) == 1 and held[0]["realized_pnl"] == Decimal("120")
    assert not [h for g in summary["groups"] for h in g["holdings"] if h["ticker"] == closed_tk]


def test_close_usd_realized_at_trade_date_rates(db):
    from backend.portfolio import _realized_for_position
    from backend.writes import close_position_if_flat

    plat, tk = _platform(db), f"{T}E"
    _rate(db, "1994-03-01", "16000")
    _rate(db, "1994-03-02", "16500")
    _prim_event(db, plat, tk, "buy", 2, 50, "1994-03-01", "USD")
    _prim_event(db, plat, tk, "sell", 2, 60, "1994-03-02", "USD")
    db.rollback()
    expected = _realized_for_position(db, tk, plat)["realized_pnl"]
    rec = close_position_if_flat(db, tk, plat)
    assert rec is not None
    db.commit()
    assert expected == Decimal("380000")
    assert _closed(db, tk)[0].realized_pnl == expected


def test_close_never_touches_ledger_totals(authed, db):
    from backend import tools
    from backend.models import Transaction

    acc, plat, tk = _account(db), _platform(db), f"{T}F"
    kw = dict(period="custom", start_date="2024-03-01", end_date="2024-03-31")
    inc, spend = tools.income_total(**kw)["total"], tools.spending_total(**kw)["total"]
    _funded(authed, "buy", acc, plat, tk, 10, 100, 1000, "2024-03-01")
    assert _funded(authed, "sell", acc, plat, tk, 10, 150, 1500, "2024-03-02").json()["closed_position_id"]
    assert tools.income_total(**kw)["total"] == inc
    assert tools.spending_total(**kw)["total"] == spend
    row = next(r for r in tools.account_balances()["rows"] if r["name"] == acc)
    assert row["current_balance"] == 500  # -1000 + 1500, nothing else
    from backend.models import Account

    db.rollback()
    n = db.query(Transaction).join(Account, Transaction.account_id == Account.id).filter(Account.name == acc).count()
    assert n == 2


def test_close_rolls_back_as_one(db):
    from backend.models import ClosedPosition, Transaction
    from backend.writes import apply_add_funded_buy, apply_add_funded_sell

    acc, plat, tk = _account(db), _platform(db), f"{T}G"
    apply_add_funded_buy(db, {
        "source_account_name": acc, "platform_id": plat, "ticker": tk,
        "quantity": 10, "price": 100, "cash_amount": 1000, "date": "2024-03-01",
    })
    db.commit()
    res = apply_add_funded_sell(db, {
        "source_account_name": acc, "platform_id": plat, "ticker": tk,
        "quantity": 10, "price": 150, "cash_amount": 1500, "date": "2024-03-02",
    })
    assert res["closed_position"] is not None
    db.rollback()
    h = _holding(db, tk, plat)
    assert h is not None and h.quantity == Decimal("10")
    assert len(_events(db, tk)) == 1
    assert _closed(db, tk) == []
    from backend.models import Account

    assert db.query(Transaction).join(Account, Transaction.account_id == Account.id).filter(Account.name == acc).count() == 1


def test_later_buy_starts_fresh(authed, db):
    acc, plat, tk = _account(db), _platform(db), f"{T}H"
    _rate(db, "1994-03-01", "16000")
    _funded(authed, "buy", acc, plat, tk, 10, 100, 1000, "2024-03-01")
    assert _funded(authed, "sell", acc, plat, tk, 10, 150, 1500, "2024-03-02").json()["closed_position_id"]
    total_closed = _total(db)
    r = _funded(authed, "buy", acc, plat, tk, 5, 70, 1000000, "1994-03-01", "USD")
    assert r.status_code == 201, r.text
    h = _holding(db, tk, plat)
    assert h.quantity == Decimal("5") and h.currency == "USD"
    assert h.avg_cost == Decimal("70") * Decimal("16000")
    assert len(_closed(db, tk)) == 1
    assert abs(_total(db) - total_closed) <= TOL  # a plain buy realizes nothing


def test_dust_stays_open(authed, db):
    acc, plat, tk = _account(db), _platform(db), f"{T}I"
    _funded(authed, "buy", acc, plat, tk, 1, 100, 100, "2024-03-01")
    r = _funded(authed, "sell", acc, plat, tk, 0.99999999, 100, 100, "2024-03-02")
    assert r.status_code == 201 and r.json()["closed_position_id"] is None
    h = _holding(db, tk, plat)
    assert h is not None and h.quantity == Decimal("0.00000001")
    assert len(_events(db, tk)) == 2
    assert _closed(db, tk) == []


def test_close_audit_rows(authed, db):
    from backend.models import AuditLog

    acc, plat, tk = _account(db), _platform(db), f"{T}J"
    _funded(authed, "buy", acc, plat, tk, 10, 100, 1000, "2024-03-01")
    cid = _funded(authed, "sell", acc, plat, tk, 10, 150, 1500, "2024-03-02").json()["closed_position_id"]
    db.rollback()
    add = db.query(AuditLog).filter(AuditLog.entity == "closed_position", AuditLog.entity_id == cid).all()
    assert len(add) == 1 and add[0].operation == "add"
    assert add[0].after["ticker"] == tk and add[0].after["realized_pnl"] == "500.00000000"
    ev_del = db.execute(
        text("SELECT before FROM audit_log WHERE entity = 'portfolio_event' AND operation = 'delete' "
             "AND before->>'ticker' = :t"), {"t": tk}).fetchall()
    assert len(ev_del) == 2
    assert all(isinstance(r[0]["quantity"], str) for r in ev_del)
    h_del = db.execute(
        text("SELECT before FROM audit_log WHERE entity = 'holding' AND operation = 'delete' "
             "AND before->>'ticker' = :t"), {"t": tk}).fetchall()
    assert len(h_del) == 1
