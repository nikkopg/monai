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
        "DELETE FROM proposals WHERE payload::text LIKE '%ZZNQ6%'",
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


def _prim_event(db, plat, ticker, etype, qty, price, day, ccy="IDR", asset_type=None):
    from backend.writes import apply_add_portfolio_event

    ev = apply_add_portfolio_event(db, {
        "ticker": ticker, "event_type": etype, "quantity": qty, "price": price,
        "platform_id": plat, "currency": ccy, "date": day, "asset_type": asset_type,
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


# ---------------------------------------------------------------------------
# Task 2: correction rules, sell refusal, CASH, chat total, fixing a record
# ---------------------------------------------------------------------------


def _full_close(client, db, tk="A", buy_day="2024-03-01", sell_day="2024-03-02"):
    acc, plat = _account(db), _platform(db)
    tk = f"{T}{tk}"
    assert _funded(client, "buy", acc, plat, tk, 10, 100, 1000, buy_day).status_code == 201
    r = _funded(client, "sell", acc, plat, tk, 10, 150, 1500, sell_day)
    assert r.status_code == 201 and r.json()["closed_position_id"], r.text
    return acc, plat, tk, r.json()["closed_position_id"]


def test_edit_sell_to_zero_closes(authed, db):
    from backend.models import Transaction

    acc, plat, tk = _account(db), _platform(db), f"{T}K1"
    base = _total(db)
    _funded(authed, "buy", acc, plat, tk, 10, 100, 1000, "2024-03-01")
    sell = _funded(authed, "sell", acc, plat, tk, 7, 150, 1050, "2024-03-02").json()
    r = authed.put(f"/portfolio-events/{sell['portfolio_event_id']}", json={"quantity": 10, "cash_amount": 1500})
    assert r.status_code == 200, r.text
    assert r.json()["ticker"] == tk
    recs = _closed(db, tk)
    assert len(recs) == 1 and recs[0].realized_pnl == Decimal("500")
    assert abs((_total(db) - base) - Decimal("500")) <= TOL
    assert db.get(Transaction, sell["transaction_id"]).amount == Decimal("1500")


def test_edit_buy_to_zero_does_not_close(authed, db):
    acc, plat, tk = _account(db), _platform(db), f"{T}K2"
    base = _total(db)
    buy = _funded(authed, "buy", acc, plat, tk, 10, 100, 1000, "2024-03-01").json()
    sell = _funded(authed, "sell", acc, plat, tk, 7, 150, 1050, "2024-03-02").json()
    assert authed.put(f"/portfolio-events/{buy['portfolio_event_id']}", json={"quantity": 7}).status_code == 200
    h = _holding(db, tk, plat)
    assert h is not None and h.quantity == 0
    assert len(_events(db, tk)) == 2 and _closed(db, tk) == []
    assert abs((_total(db) - base) - Decimal("350")) <= TOL
    assert authed.put(f"/portfolio-events/{sell['portfolio_event_id']}", json={"price": 150}).status_code == 200
    assert len(_closed(db, tk)) == 1 and _holding(db, tk, plat) is None
    assert abs((_total(db) - base) - Decimal("350")) <= TOL


def test_delete_to_zero_does_not_close(authed, db):
    acc, plat, tk = _account(db), _platform(db), f"{T}K3"
    b1 = _funded(authed, "buy", acc, plat, tk, 5, 100, 500, "2024-03-01").json()
    _funded(authed, "buy", acc, plat, tk, 5, 100, 500, "2024-03-02")
    _funded(authed, "sell", acc, plat, tk, 5, 120, 600, "2024-03-03")
    assert authed.delete(f"/portfolio-events/{b1['portfolio_event_id']}").status_code == 200
    h = _holding(db, tk, plat)
    assert h is not None and h.quantity == 0
    assert len(_events(db, tk)) == 2 and _closed(db, tk) == []


def test_back_dated_sell_reopened_is_not_closed(authed, db):
    acc, plat, tk = _account(db), _platform(db), f"{T}K4"
    _funded(authed, "buy", acc, plat, tk, 10, 100, 1000, "2024-01-10")
    _funded(authed, "buy", acc, plat, tk, 4, 100, 400, "2024-03-10")
    r = _funded(authed, "sell", acc, plat, tk, 10, 120, 1200, "2024-02-10")
    assert r.status_code == 201 and r.json()["closed_position_id"] is None
    assert _holding(db, tk, plat).quantity == Decimal("4") and _closed(db, tk) == []


def test_close_date_is_latest_sell(authed, db):
    acc, plat, tk = _account(db), _platform(db), f"{T}K5"
    _funded(authed, "buy", acc, plat, tk, 10, 100, 1000, "2024-01-10")
    _funded(authed, "sell", acc, plat, tk, 5, 120, 600, "2024-03-10")
    r = _funded(authed, "sell", acc, plat, tk, 5, 120, 600, "2024-02-10")
    assert r.json()["closed_position_id"] is not None
    assert _closed(db, tk)[0].close_date.isoformat() == "2024-03-10"


def test_oversell_refused(authed, db):
    from backend.models import Account, Transaction

    acc, plat, tk = _account(db), _platform(db), f"{T}K6"
    _funded(authed, "buy", acc, plat, tk, 10, 100, 1000, "2024-03-01")

    def n_tx():
        db.rollback()
        return db.query(Transaction).join(Account, Transaction.account_id == Account.id).filter(Account.name == acc).count()

    r = _funded(authed, "sell", acc, plat, tk, 15, 100, 1500, "2024-03-02")
    assert r.status_code == 422 and "10" in r.text and "nothing was saved" in r.text
    r = _funded(authed, "sell", acc, plat, tk, 5, 100, 500, "2024-02-01")  # before the first buy
    assert r.status_code == 422
    assert n_tx() == 1 and len(_events(db, tk)) == 1 and _closed(db, tk) == []
    assert _holding(db, tk, plat).quantity == Decimal("10")


def test_negative_ledger_never_closes(authed, db):
    plat, tk = _platform(db), f"{T}K7"
    sell = _prim_event(db, plat, tk, "sell", 5, 150, "2024-01-01")
    _prim_event(db, plat, tk, "buy", 5, 100, "2024-02-01")
    assert authed.put(f"/portfolio-events/{sell.id}", json={"price": 150}).status_code == 200
    h = _holding(db, tk, plat)
    assert h is not None and h.quantity == 0
    assert len(_events(db, tk)) == 2 and _closed(db, tk) == []


def test_cash_position_never_closes(authed, db):
    acc, plat, tk = _account(db), _platform(db), f"{T}K8"
    _prim_event(db, plat, tk, "deposit", 100, 1, "2024-03-01", asset_type="cash")
    r = _funded(authed, "sell", acc, plat, tk, 100, 1, 100, "2024-03-02")
    assert r.status_code == 201 and r.json()["closed_position_id"] is None
    h = _holding(db, tk, plat)
    assert h is not None and h.quantity == 0
    assert len(_events(db, tk)) == 2 and _closed(db, tk) == []


def test_confirm_path_closes(authed, db):
    from backend.tools import propose_add_funded_sell

    acc, plat, tk = _account(db), _platform(db), f"{T}K9"
    _funded(authed, "buy", acc, plat, tk, 10, 100, 1000, "2024-03-01")
    res = propose_add_funded_sell(acc, plat, tk, 10, 150, 1500, date="2024-03-02")
    r = authed.post(f"/proposals/{res['proposal_id']}/confirm", json={"token": res["proposal_token"]})
    assert r.status_code == 200, r.text
    assert len(_closed(db, tk)) == 1 and _holding(db, tk, plat) is None


def test_late_dividend_after_close(authed, db):
    acc, plat, tk, _ = _full_close(authed, db, "L")
    base_total = _total(db)
    r = authed.post("/portfolio-events", json={
        "ticker": tk, "event_type": "dividend", "quantity": 1, "price": 30,
        "platform_id": plat, "currency": "IDR", "date": "2024-03-10"})
    assert r.status_code == 201, r.text
    h = _holding(db, tk, plat)
    assert h is not None and h.quantity == 0
    assert abs((_total(db) - base_total) - Decimal("30")) <= TOL


def test_fix_closed_record(authed, db):
    from backend.models import Account, AuditLog, Transaction

    acc, plat, tk, cid = _full_close(authed, db, "M")
    tx_before = db.query(Transaction).join(Account, Transaction.account_id == Account.id).filter(Account.name == acc).count()
    t0 = _total(db)
    r = authed.put(f"/closed-positions/{cid}", json={"realized_pnl": 400, "close_date": "2024-04-01"})
    assert r.status_code == 200, r.text
    assert r.json()["realized_pnl"] == 400 and r.json()["close_date"] == "2024-04-01"
    assert abs((_total(db) - t0) - Decimal("-100")) <= TOL
    db.rollback()
    edit = db.query(AuditLog).filter(AuditLog.entity == "closed_position", AuditLog.entity_id == cid,
                                     AuditLog.operation == "edit").one()
    assert edit.after["realized_pnl"] == "400" or Decimal(edit.after["realized_pnl"]) == 400
    assert isinstance(edit.before["realized_pnl"], str)
    assert authed.delete(f"/closed-positions/{cid}").status_code == 200
    assert abs((_total(db) - t0) - Decimal("-500")) <= TOL
    assert db.query(AuditLog).filter(AuditLog.entity == "closed_position", AuditLog.entity_id == cid,
                                     AuditLog.operation == "delete").count() == 1
    assert authed.delete(f"/closed-positions/{cid}").status_code == 404
    assert authed.put(f"/closed-positions/{cid}", json={"realized_pnl": 1}).status_code == 404
    assert db.query(Transaction).join(Account, Transaction.account_id == Account.id).filter(Account.name == acc).count() == tx_before


def test_platform_delete_and_reassign(authed, db):
    from backend.writes import apply_set_price

    acc, plat_a, tk, cid = _full_close(authed, db, "N")
    # a plain delete: no holdings left, the record survives unattached and the total holds
    total = _total(db)
    assert authed.get(f"/platforms/{plat_a}/detail").json()["closed_realized_pnl"] == 500
    assert authed.delete(f"/platforms/{plat_a}").status_code == 200
    row = next(c for c in authed.get("/closed-positions").json() if c["id"] == cid)
    assert row["platform_id"] is None and row["platform_name"] is None
    assert abs(_total(db) - total) <= TOL

    # a reassign moves an open holding and the closed record together
    acc2, plat_b, plat_c = _account(db), _platform(db), _platform(db)
    open_tk, closed_tk = f"{T}N2", f"{T}N3"
    apply_set_price(db, open_tk, 100)
    db.commit()
    _funded(authed, "buy", acc2, plat_b, open_tk, 1, 100, 100, "2024-03-01")
    _funded(authed, "buy", acc2, plat_b, closed_tk, 2, 100, 200, "2024-03-01")
    cid2 = _funded(authed, "sell", acc2, plat_b, closed_tk, 2, 150, 300, "2024-03-02").json()["closed_position_id"]
    assert cid2
    assert authed.delete(f"/platforms/{plat_b}", params={"reassign_to": plat_c}).status_code == 200
    moved = next(c for c in authed.get("/closed-positions").json() if c["id"] == cid2)
    assert moved["platform_id"] == plat_c
    assert authed.get(f"/platforms/{plat_c}/detail").json()["closed_realized_pnl"] == 100


def test_spending_comparison_after_close(authed, db):
    from backend import tools

    _, _, tk, _ = _full_close(authed, db, "P")
    out = tools.spending_before_after_purchase(tk, "Food")
    assert "No buy event found" in out["error"]


def test_net_worth_reports_total_realized(authed, db):
    from backend import tools
    from backend.portfolio import portfolio_summary
    from backend.writes import close_position_if_flat

    plat, tk = _platform(db), f"{T}Q"
    _prim_event(db, plat, tk, "buy", 10, 100, "2024-03-01")
    _prim_event(db, plat, tk, "sell", 10, 150, "2024-03-02")
    before = tools.net_worth()
    assert before["total_realized_pnl"] == float(_total(db))
    assert close_position_if_flat(db, tk, plat) is not None
    db.commit()
    after = tools.net_worth()
    assert abs(after["total_realized_pnl"] - before["total_realized_pnl"]) < 1e-6
    assert after["total_realized_pnl"] == float(portfolio_summary(db)["total_realized_pnl"])
    assert tk not in str(after) and "closed" not in str(after).lower()
    r = authed.get("/net-worth")
    assert r.status_code == 200 and "investment_total" in r.json()


# --- F-3 trend effects of deleting a closed position's events (accepted, Q3) ---


def _month_start(n):
    from datetime import date

    t = date.today().replace(day=1)
    y, m = t.year, t.month - n
    while m <= 0:
        m, y = m + 12, y - 1
    return date(y, m, 1)


def _mkey(n):
    d = _month_start(n)
    return f"{d.year}-{d.month:02d}"


def _trend_seed(db, snapshots):
    """Wipe the ledger tables in this UNCOMMITTED session; seed X (closed later) and Y (stays open)."""
    from datetime import timedelta

    from backend.models import Platform, PortfolioValueHistory

    for t in ("portfolio_value_history", "portfolio_events", "holdings", "net_worth_corrections"):
        db.execute(text(f"DELETE FROM {t}"))
    p = Platform(name=f"zznq6-plat-{uuid.uuid4().hex[:6]}", kind="exchange")
    db.add(p)
    db.flush()
    x, y = f"{T}X", f"{T}Y"
    from backend.writes import apply_add_portfolio_event as add

    def d(n, day):
        return (_month_start(n) + timedelta(days=day - 1)).isoformat()

    add(db, {"ticker": y, "event_type": "buy", "quantity": 20, "price": 100, "platform_id": p.id, "currency": "IDR", "date": d(6, 5)})
    add(db, {"ticker": x, "event_type": "buy", "quantity": 10, "price": 100, "platform_id": p.id, "currency": "IDR", "date": d(5, 5)})
    add(db, {"ticker": x, "event_type": "sell", "quantity": 10, "price": 150, "platform_id": p.id, "currency": "IDR", "date": d(2, 5)})
    for n, with_x in snapshots:
        if with_x:
            db.add(PortfolioValueHistory(snapshot_date=_month_start(n) + timedelta(days=19), ticker=x, platform_id=p.id,
                                         quantity=10, market_value=1500, cost_basis=0, currency="IDR"))
        db.add(PortfolioValueHistory(snapshot_date=_month_start(n) + timedelta(days=19), ticker=y, platform_id=p.id,
                                     quantity=20, market_value=2000, cost_basis=0, currency="IDR"))
    db.flush()
    return x, p.id


def _trend(db):
    from backend.investment_reconstruction import monthly_investment_series
    from backend.net_worth_history import _carry_investment_forward

    rows = monthly_investment_series(7, db=db)["rows"]
    return rows, {r["month"]: r["investment_total"] for r in _carry_investment_forward(rows)}


def test_trend_snapshot_regime_unchanged(db):
    from backend.writes import close_position_if_flat

    try:
        x, plat = _trend_seed(db, [(5, True), (4, True), (3, True), (2, False), (1, False)])
        _, before = _trend(db)
        assert close_position_if_flat(db, x, plat) is not None
        _, after = _trend(db)
        for n in range(6, 0, -1):
            assert before[_mkey(n)] == after[_mkey(n)], _mkey(n)
        assert before[_mkey(5)] == Decimal("3500") and after[_mkey(2)] == Decimal("2000")
    finally:
        db.rollback()


def test_trend_replay_regime_loses_closed_value(db):
    from backend.writes import close_position_if_flat

    try:
        x, plat = _trend_seed(db, [])
        _, before = _trend(db)
        assert close_position_if_flat(db, x, plat) is not None
        _, after = _trend(db)
        for n in (5, 4, 3):
            assert before[_mkey(n)] == Decimal("3000") and after[_mkey(n)] == Decimal("2000")
        for n in (2, 1):
            assert before[_mkey(n)] == after[_mkey(n)] == Decimal("2000")
    finally:
        db.rollback()


def test_trend_partial_snapshot_flips_gap(db):
    from backend.writes import close_position_if_flat

    try:
        x, plat = _trend_seed(db, [(5, True), (4, False), (3, True), (2, False), (1, False)])
        raw_before, before = _trend(db)
        m4 = next(r for r in raw_before if r["month"] == _mkey(4))
        assert m4["honest"] is False and m4["gap_reason"] == "snapshot_missing_position"
        assert before[_mkey(4)] == Decimal("3500")  # a gap carried forward
        assert close_position_if_flat(db, x, plat) is not None
        raw_after, after = _trend(db)
        assert next(r for r in raw_after if r["month"] == _mkey(4))["honest"] is True
        assert after[_mkey(4)] == Decimal("2000")  # now an honest but understated month
    finally:
        db.rollback()
