"""SBN bond support (quick 261117-rw1): coupon math, pay dates and the migration 024 schema.

All values are synthetic. The schema test only reads catalog tables; it writes nothing.
"""
import uuid
from datetime import date, timedelta
from types import SimpleNamespace
from decimal import Decimal

import pytest
from sqlalchemy import text

from backend.bonds import coupon_amounts, pay_dates

D = Decimal


@pytest.mark.parametrize(
    "nominal,rate,tax,expected",
    [
        ("12000000", "6.00", "10", (60000, 6000, 54000)),
        ("25000000", "6.25", "10", (130208, 13021, 117187)),
        ("1000032", "6.25", "10", (5209, 521, 4688)),
        ("1000000", "6.45", "15", (5375, 806, 4569)),
    ],
)
def test_coupon_amounts_vectors(nominal, rate, tax, expected):
    got = coupon_amounts(D(nominal), D(rate), D(tax))
    assert got == tuple(D(x) for x in expected)
    assert all(g == g.to_integral_value() for g in got)


def test_coupon_amounts_zero_tax():
    gross, tax, net = coupon_amounts(D("12000000"), D("6.00"), D("0"))
    assert (gross, tax, net) == (D(60000), D(0), D(60000))


def test_pay_dates_basic_and_year_cross():
    assert pay_dates(15, date(2026, 11, 20), date(2027, 2, 15)) == [
        date(2026, 12, 15), date(2027, 1, 15), date(2027, 2, 15),
    ]


def test_pay_dates_bounds_are_after_exclusive_through_inclusive():
    assert pay_dates(15, date(2026, 11, 15), date(2026, 12, 15)) == [date(2026, 12, 15)]
    assert pay_dates(15, date(2026, 11, 14), date(2026, 11, 15)) == [date(2026, 11, 15)]


def test_pay_dates_empty():
    assert pay_dates(15, date(2026, 11, 20), date(2026, 11, 20)) == []
    assert pay_dates(15, date(2026, 11, 20), date(2026, 11, 1)) == []
    assert pay_dates(15, date(2026, 11, 16), date(2026, 12, 14)) == []


@pytest.fixture()
def db_session():
    from backend.db import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_migration_024_schema(db_session):
    cols = {
        r[0]: r[1] for r in db_session.execute(text(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = 'holdings'"
        ))
    }
    for name, dtype in {
        "coupon_rate": "numeric", "coupon_floating": "boolean", "coupon_day": "smallint",
        "maturity_date": "date", "coupon_tax_pct": "numeric", "coupon_account_id": "integer",
    }.items():
        assert cols.get(name) == dtype, name

    chan = db_session.execute(text(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'ck_proposals_channel'"
    )).scalar()
    assert chan and "schedule" in chan

    idx = db_session.execute(text(
        "SELECT indexdef FROM pg_indexes WHERE indexname = 'uq_proposals_schedule_key'"
    )).scalar()
    assert idx and "UNIQUE" in idx and "'schedule'" in idx

    assert db_session.execute(text(
        "SELECT 1 FROM pg_constraint WHERE conname = 'ck_holdings_bond_terms'"
    )).scalar() == 1
    assert db_session.execute(text(
        "SELECT 1 FROM pg_constraint WHERE conname = 'fk_holdings_coupon_account'"
    )).scalar() == 1

    kind = db_session.execute(text(
        "SELECT kind FROM categories WHERE name = 'Investment income' LIMIT 1"
    )).scalar()
    assert kind == "income"


# ---------------------------------------------------------------------------
# T2: bond terms write path (funded buy, POST /holdings, PUT /holdings)
# ---------------------------------------------------------------------------

T = "ZZSBN2"


def _purge(db) -> None:
    db.rollback()
    accts = "(SELECT id FROM accounts WHERE name LIKE 'zzsbn2-%')"
    plats = "(SELECT id FROM platforms WHERE name LIKE 'zzsbn2-%')"
    for sql in (
        "DELETE FROM audit_log WHERE entity = 'closed_position' AND entity_id IN "
        "(SELECT id FROM closed_positions WHERE ticker LIKE 'ZZSBN2%')",
        "DELETE FROM audit_log WHERE before->>'ticker' LIKE 'ZZSBN2%' OR after->>'ticker' LIKE 'ZZSBN2%'",
        "DELETE FROM proposals WHERE payload->>'key' LIKE '%ZZSBN2%'",
        f"DELETE FROM closed_positions WHERE ticker LIKE 'ZZSBN2%' OR platform_id IN {plats}",
        f"DELETE FROM portfolio_events WHERE ticker LIKE 'ZZSBN2%' OR platform_id IN {plats}",
        "DELETE FROM portfolio_value_history WHERE ticker LIKE 'ZZSBN2%'",
        f"DELETE FROM holdings WHERE ticker LIKE 'ZZSBN2%' OR platform_id IN {plats}",
        "DELETE FROM audit_log WHERE entity = 'transaction' AND entity_id IN "
        f"(SELECT id FROM transactions WHERE account_id IN {accts})",
        f"DELETE FROM transactions WHERE account_id IN {accts}",
        f"DELETE FROM audit_log WHERE entity = 'account' AND entity_id IN {accts}",
        "DELETE FROM accounts WHERE name LIKE 'zzsbn2-%'",
        "DELETE FROM platforms WHERE name LIKE 'zzsbn2-%'",
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


def _account(db, type_="liquid", currency="IDR") -> tuple[int, str]:
    from backend.models import Account

    name = f"zzsbn2-acc-{uuid.uuid4().hex[:6]}"
    a = Account(name=name, type=type_, currency=currency)
    db.add(a)
    db.commit()
    return a.id, name


def _platform(db) -> int:
    from backend.models import Platform

    p = Platform(name=f"zzsbn2-plat-{uuid.uuid4().hex[:6]}", kind="exchange")
    db.add(p)
    db.commit()
    return p.id


def _terms(acc_id, **over) -> dict:
    return {"rate": 6.0, "floating": False, "pay_day": 15, "maturity_date": "2030-06-15",
            "tax_pct": 10, "coupon_account_id": acc_id, **over}


def _buy(client, acc_name, plat, ticker, bond=None, asset_type="bond", qty=12000000, on="2026-11-01"):
    body = {"source_account_name": acc_name, "platform_id": plat, "ticker": ticker,
            "quantity": qty, "price": 1, "cash_amount": qty, "date": on,
            "asset_type": asset_type}
    if bond is not None:
        body["bond"] = bond
    return client.post("/portfolio-events/funded-buy", json=body)


def _holding(db, ticker):
    from backend.models import Holding

    db.expire_all()
    return db.query(Holding).filter(Holding.ticker == ticker).one_or_none()


def _counts(db, plat) -> tuple[int, int]:
    n_ev = db.execute(text("SELECT count(*) FROM portfolio_events WHERE platform_id = :p"), {"p": plat}).scalar()
    n_tx = db.execute(text("SELECT count(*) FROM transactions t JOIN accounts a ON a.id = t.account_id "
                           "WHERE a.name LIKE 'zzsbn2-%'")).scalar()
    return n_ev, n_tx


def test_funded_buy_stores_terms(authed, db):
    acc_id, acc = _account(db)
    plat = _platform(db)
    r = _buy(authed, acc, plat, f"{T}A", _terms(acc_id))
    assert r.status_code == 201, r.text
    h = _holding(db, f"{T}A")
    assert (h.coupon_rate, h.coupon_floating, h.coupon_day) == (D("6.00"), False, 15)
    assert (h.maturity_date, h.coupon_tax_pct, h.coupon_account_id) == (date(2030, 6, 15), D("10.00"), acc_id)
    assert (h.quantity, h.avg_cost) == (D("12000000"), D("1"))
    after = db.execute(text(
        "SELECT after FROM audit_log WHERE entity = 'portfolio_event' AND after->>'ticker' = :t"), {"t": f"{T}A"}
    ).scalar()
    assert after["bond"]["rate"] == "6.0" and after["bond"]["maturity_date"] == "2030-06-15"


def test_funded_buy_without_bond_unchanged(authed, db):
    _, acc = _account(db)
    plat = _platform(db)
    assert _buy(authed, acc, plat, f"{T}B", asset_type="stock").status_code == 201
    h = _holding(db, f"{T}B")
    assert h.coupon_rate is None and h.coupon_account_id is None and h.maturity_date is None


@pytest.mark.parametrize("over", [
    {"pay_day": 0}, {"pay_day": 29}, {"rate": 0}, {"rate": 100}, {"rate": 6.255}, {"tax_pct": 100},
    {"coupon_account_id": 2_000_000_000},
])
def test_funded_buy_bad_terms_422_nothing_saved(authed, db, over):
    acc_id, acc = _account(db)
    plat = _platform(db)
    r = _buy(authed, acc, plat, f"{T}C", _terms(acc_id, **over))
    assert r.status_code == 422, r.text
    assert _counts(db, plat) == (0, 0)
    assert _holding(db, f"{T}C") is None


@pytest.mark.parametrize("kind", ["investment", "usd"])
def test_funded_buy_wrong_coupon_account_422(authed, db, kind):
    _, acc = _account(db)
    bad_id, _ = _account(db, type_="investment") if kind == "investment" else _account(db, currency="USD")
    plat = _platform(db)
    assert _buy(authed, acc, plat, f"{T}D", _terms(bad_id)).status_code == 422
    assert _counts(db, plat) == (0, 0)


def test_funded_buy_bond_on_non_bond_asset_422(authed, db):
    acc_id, acc = _account(db)
    plat = _platform(db)
    assert _buy(authed, acc, plat, f"{T}E", _terms(acc_id), asset_type="stock").status_code == 422
    assert _counts(db, plat) == (0, 0)


def test_funded_buy_usd_bond_422(authed, db):
    acc_id, _ = _account(db)
    _, usd_acc = _account(db, currency="USD")
    plat = _platform(db)
    assert _buy(authed, usd_acc, plat, f"{T}F", _terms(acc_id)).status_code == 422
    assert _counts(db, plat) == (0, 0)
    assert _holding(db, f"{T}F") is None


def test_post_and_put_holding_terms(authed, db):
    acc_id, _ = _account(db)
    plat = _platform(db)
    r = authed.post("/holdings", json={
        "ticker": f"{T}G", "quantity": 5000000, "avg_cost": 1, "asset_type": "bond",
        "platform_id": plat, "bond": _terms(acc_id)})
    assert r.status_code == 201, r.text
    hid = r.json()["id"]
    assert _holding(db, f"{T}G").coupon_rate == D("6.00")

    r = authed.put(f"/holdings/{hid}", json={"bond": _terms(acc_id, rate=6.25, floating=True, pay_day=10)})
    assert r.status_code == 200, r.text
    h = _holding(db, f"{T}G")
    assert (h.coupon_rate, h.coupon_floating, h.coupon_day) == (D("6.25"), True, 10)
    row = db.execute(text(
        "SELECT before, after FROM audit_log WHERE entity = 'holding' AND entity_id = :i AND operation = 'edit'"),
        {"i": hid}).one()
    assert row.before["bond"]["rate"] == "6.00" and row.before["bond"]["coupon_account_id"] == acc_id
    assert row.after["bond"]["rate"] == "6.25" and row.after["bond"]["floating"] is True


def test_post_holding_bond_on_non_bond_422(authed, db):
    acc_id, _ = _account(db)
    plat = _platform(db)
    r = authed.post("/holdings", json={
        "ticker": f"{T}H", "quantity": 1, "avg_cost": 1, "asset_type": "stock",
        "platform_id": plat, "bond": _terms(acc_id)})
    assert r.status_code == 422
    assert _holding(db, f"{T}H") is None


# ---------------------------------------------------------------------------
# T3: face valuation, no price fetch, the summary `bond` dict
# ---------------------------------------------------------------------------


def _bond_holding(**over):
    h = dict(quantity=D("12000000"), coupon_rate=D("6.00"), coupon_floating=False, coupon_day=15,
             maturity_date=date(2027, 1, 15), coupon_tax_pct=D("10.00"), coupon_account_id=7)
    return SimpleNamespace(**{**h, **over})


def test_bond_info_dates_and_amounts():
    from backend.bonds import bond_info

    info = bond_info(_bond_holding(), date(2026, 11, 20), {7: "Bank Synth"})
    assert info["next_coupon_date"] == date(2026, 12, 15)
    assert info["upcoming"] == [date(2026, 12, 15), date(2027, 1, 15)]
    assert (info["gross"], info["tax"], info["net"]) == (60000, 6000, 54000)
    assert info["coupon_account_name"] == "Bank Synth"
    # a pay day equal to today still counts as next
    assert bond_info(_bond_holding(), date(2026, 12, 15), {})["next_coupon_date"] == date(2026, 12, 15)


def test_bond_info_after_maturity_and_missing_terms():
    from backend.bonds import bond_info

    done = bond_info(_bond_holding(), date(2027, 1, 16), {})
    assert done["next_coupon_date"] is None and done["upcoming"] == [] and done["gross"] == 60000
    for missing in ("coupon_rate", "coupon_day", "maturity_date"):
        info = bond_info(_bond_holding(**{missing: None}), date(2026, 11, 20), {})
        assert info["upcoming"] == []
        assert (info["gross"], info["tax"], info["net"], info["next_coupon_date"]) == (None,) * 4


def _expected_upcoming(day, maturity):
    from backend import fx

    return [d.isoformat() for d in pay_dates(day, fx._jakarta_today() - timedelta(days=1), maturity)[:3]]


def test_funded_buy_lands_in_todays_snapshot(authed, db, monkeypatch):
    # The route refreshes today's snapshot, so the trend sees the buy before the next 01:00 run.
    from datetime import date

    import backend.main as main_mod
    from backend.models import PortfolioValueHistory
    from backend.scheduler import refresh_today_snapshot_job

    monkeypatch.setattr(main_mod, "refresh_today_snapshot_job", refresh_today_snapshot_job)

    acc_id, acc = _account(db)
    plat = _platform(db)
    assert _buy(authed, acc, plat, f"{T}S", _terms(acc_id)).status_code == 201
    db.expire_all()
    rows = db.query(PortfolioValueHistory).filter(PortfolioValueHistory.ticker == f"{T}S",
                                                  PortfolioValueHistory.snapshot_date == date.today()).all()
    assert [float(r.market_value) for r in rows] == [12000000]


def test_summary_and_platform_detail_value_bond_at_face(authed, db):
    acc_id, acc = _account(db)
    plat = _platform(db)
    assert _buy(authed, acc, plat, f"{T}I", _terms(acc_id)).status_code == 201
    r = authed.post("/holdings", json={"ticker": f"{T}J", "quantity": 2, "avg_cost": 3,
                                       "asset_type": "other", "platform_id": plat})
    assert r.status_code in (200, 201), r.text

    summary = authed.get("/investments/summary").json()
    detail = authed.get(f"/platforms/{plat}/detail").json()
    for rows in ([h for g in summary["groups"] for h in g["holdings"] if g["platform_id"] == plat],
                 detail["holdings"]):
        by = {h["ticker"]: h for h in rows}
        b = by[f"{T}I"]
        assert (float(b["current_price"]), float(b["current_value"]), float(b["unrealized_pnl"])) == (1, 12000000, 0)
        assert b["is_stale"] is False and b["price_source"] == "face"
        bd = b["bond"]
        assert (bd["rate"], bd["floating"], bd["pay_day"], bd["tax_pct"]) == (6.0, False, 15, 10.0)
        assert bd["coupon_account_name"] == acc and bd["coupon_account_id"] == acc_id
        assert (bd["gross"], bd["tax"], bd["net"]) == (60000, 6000, 54000)
        assert bd["upcoming"] == _expected_upcoming(15, date(2030, 6, 15))
        assert bd["next_coupon_date"] == bd["upcoming"][0] and bd["next_coupon_date"].endswith("-15")
        assert by[f"{T}J"]["bond"] is None and by[f"{T}J"]["price_source"] != "face"


def test_snapshot_writes_bond_at_face_without_price_cache(authed, db):
    from backend.portfolio import snapshot_all_holdings

    acc_id, acc = _account(db)
    plat = _platform(db)
    assert _buy(authed, acc, plat, f"{T}K", _terms(acc_id)).status_code == 201
    snapshot_all_holdings(db)
    db.commit()
    row = db.execute(text("SELECT market_value, quantity FROM portfolio_value_history WHERE ticker = :t"),
                     {"t": f"{T}K"}).one()
    assert row.market_value == row.quantity == D("12000000")
    assert db.execute(text("SELECT count(*) FROM price_cache WHERE ticker = :t"), {"t": f"{T}K"}).scalar() == 0


def test_refresh_all_prices_skips_bonds(authed, db, monkeypatch):
    from backend import prices
    from backend.models import Holding

    acc_id, acc = _account(db)
    plat = _platform(db)
    assert _buy(authed, acc, plat, f"{T}L", _terms(acc_id)).status_code == 201
    calls: list[str] = []

    def spy(ticker, *a):
        calls.append(ticker)
        return None

    monkeypatch.setattr(prices, "PRICE_ADAPTERS", {k: spy for k in prices.PRICE_ADAPTERS})
    monkeypatch.setattr(prices, "fetch_manual_price", spy)
    monkeypatch.setattr(prices, "fetch_crypto_price", spy)
    out = prices.refresh_all_prices(db, force=True)
    others = {h.ticker for h in db.query(Holding).all() if h.asset_type != "bond"}
    assert f"{T}L" not in calls
    assert (out["refreshed"], out["skipped"], out["failed"]) == (0, 0, len(others))


# ---------------------------------------------------------------------------
# T4: coupon and maturity proposals, the approve path, Edit amount
# ---------------------------------------------------------------------------

D4 = date  # readability in the dates below


def _bond(client, db, ticker, buy="2026-01-05", maturity="2026-04-15"):
    """A synthetic 12,000,000 bond at 6.00% / 10% tax paying on the 15th into its own account."""  # pii-ok synthetic
    acc_id, acc = _account(db)
    plat = _platform(db)
    r = _buy(client, acc, plat, ticker, _terms(acc_id, maturity_date=maturity), on=buy)
    assert r.status_code == 201, r.text
    return acc_id, acc, plat


def _run(db, today):
    from backend.bonds import propose_due

    n = propose_due(db, today)
    db.commit()
    return n


def _props(db, ticker):
    db.expire_all()
    return db.execute(text(
        "SELECT id, status, channel, operation, payload FROM proposals "
        "WHERE payload->>'key' LIKE :k ORDER BY payload->>'key'"), {"k": f"%:{ticker}:%"}).all()


def _keys(db, ticker):
    return [p.payload["key"].split(":")[0] + ":" + p.payload["key"].rsplit(":", 1)[1] for p in _props(db, ticker)]


def _approve(client, approver_key, pid):
    return client.post(f"/proposals/{pid}/approve", headers={"MONAI_APPROVER_KEY": approver_key})


def _patch(client, approver_key, pid, body, i=0):
    return client.patch(f"/proposals/{pid}/rows/{i}", json=body, headers={"MONAI_APPROVER_KEY": approver_key})


def test_propose_coupon_once_and_idempotent(authed, db):
    _bond(authed, db, f"{T}P1")
    _run(db, D4(2026, 3, 20))
    (p,) = _props(db, f"{T}P1")
    assert (p.status, p.channel, p.operation) == ("pending", "schedule", "add_coupon")
    assert p.payload["key"].endswith(f":{T}P1:2026-03-15")
    a = p.payload["rows"][0]["after"]
    assert (a["amount"], a["gross"], a["tax"], a["date"]) == ("54000", "60000", "6000", "2026-03-15")
    assert all(isinstance(v, (str, int, bool)) for v in a.values())
    _run(db, D4(2026, 3, 20))
    assert len(_props(db, f"{T}P1")) == 1
    # nothing written to the ledger by the job: only the buy's cash leg exists
    assert db.execute(text("SELECT count(*) FROM transactions t JOIN accounts a ON a.id = t.account_id "
                           "WHERE a.name LIKE 'zzsbn2-%'")).scalar() == 1


def test_no_coupon_when_bought_after_pay_date(authed, db):
    _bond(authed, db, f"{T}P2", buy="2026-03-16")
    _run(db, D4(2026, 3, 20))
    assert _props(db, f"{T}P2") == []


def test_no_coupon_when_dividend_already_on_the_date(authed, db):
    from backend.writes import apply_add_portfolio_event

    _, _, plat = _bond(authed, db, f"{T}P3")
    apply_add_portfolio_event(db, {"ticker": f"{T}P3", "event_type": "dividend", "quantity": "1",
                                   "price": "54000", "platform_id": plat, "currency": "IDR", "date": "2026-03-15"})
    db.commit()
    _run(db, D4(2026, 3, 20))
    assert _props(db, f"{T}P3") == []


def test_catch_up_window(authed, db):
    _bond(authed, db, f"{T}P4")
    _run(db, D4(2026, 4, 12))  # 03-15 is 28 days back: inside the 31-day window
    assert _keys(db, f"{T}P4") == ["coupon:2026-03-15"]
    _bond(authed, db, f"{T}P5")
    _run(db, D4(2026, 5, 1))  # 03-15 is 47 days back: never proposed
    assert _keys(db, f"{T}P5") == ["coupon:2026-04-15", "maturity:2026-04-15"]


def test_maturity_proposal_once_and_no_coupon_after_maturity(authed, db):
    _, acc, plat = _bond(authed, db, f"{T}P6")
    _run(db, D4(2026, 4, 15))
    _run(db, D4(2026, 4, 15))
    props = _props(db, f"{T}P6")
    assert [p.operation for p in props] == ["add_coupon", "add_funded_sell"]
    a = props[1].payload["rows"][0]["after"]
    assert (a["quantity"], a["price"], a["cash_amount"], a["source_account_name"], a["date"]) == (
        12000000.0, 1.0, 12000000.0, acc, "2026-04-15")
    assert (a["platform_id"], a["asset_type"], a["cash_currency"], a["event_currency"]) == (plat, "bond", "IDR", "IDR")
    _bond(authed, db, f"{T}P7")
    _run(db, D4(2026, 6, 20))  # long past maturity: the maturity payout only
    assert _keys(db, f"{T}P7") == ["maturity:2026-04-15"]


def test_ineligible_holdings_are_skipped_quietly(authed, db):
    _, _, plat = _bond(authed, db, f"{T}P8")
    r = authed.post("/holdings", json={"ticker": f"{T}P9", "quantity": 5, "avg_cost": 1,
                                       "asset_type": "bond", "platform_id": plat})
    assert r.status_code in (200, 201), r.text
    db.execute(text("UPDATE holdings SET coupon_account_id = NULL WHERE ticker = :t"), {"t": f"{T}P8"})
    db.commit()
    _run(db, D4(2026, 3, 20))
    assert _props(db, f"{T}P8") == [] and _props(db, f"{T}P9") == []


def test_duplicate_schedule_key_is_refused_by_the_index(db):
    from sqlalchemy.exc import IntegrityError

    from backend.tools import _make_proposal

    payload = {"operation": "add_coupon", "key": f"coupon:0:{T}Q:2026-03-15", "rows": []}
    _make_proposal("add_coupon", payload, "schedule", db=db)
    with pytest.raises(IntegrityError):
        _make_proposal("add_coupon", dict(payload), "schedule", db=db)
    db.rollback()


def _realized(client, plat, ticker):
    row = next(h for h in client.get(f"/platforms/{plat}/detail").json()["holdings"] if h["ticker"] == ticker)
    return row["realized_pnl"], row["quantity"], row["avg_cost"]


def test_approve_coupon_writes_linked_pair_atomically(authed, db, approver_key):
    from backend.models import PortfolioEvent, Transaction

    ticker = f"{T}R1"
    _, acc, plat = _bond(authed, db, ticker)
    before = _realized(authed, plat, ticker)
    _run(db, D4(2026, 3, 20))
    pid = str(_props(db, ticker)[0].id)
    r = _approve(authed, approver_key, pid)
    assert r.status_code == 200, r.text
    db.expire_all()
    ev = db.query(PortfolioEvent).filter(PortfolioEvent.ticker == ticker, PortfolioEvent.event_type == "dividend").one()
    tx = db.get(Transaction, ev.transaction_id)
    assert (tx.amount, tx.category, tx.merchant, tx.is_transfer) == (D("54000"), "Investment income", f"Coupon {ticker}", False)
    assert tx.date.date() == date(2026, 3, 15) and tx.account.name == acc
    cat = db.execute(text("SELECT name FROM categories WHERE id = :i"), {"i": tx.category_id}).scalar()
    assert cat == "Investment income"
    assert (ev.quantity, ev.price, ev.source_account_id, ev.date) == (D("1"), D("54000"), tx.account_id, date(2026, 3, 15))
    for entity, eid in (("transaction", tx.id), ("portfolio_event", ev.id)):
        assert db.execute(text("SELECT count(*) FROM audit_log WHERE entity = :e AND entity_id = :i AND operation = 'add'"),
                          {"e": entity, "i": eid}).scalar() == 1
    after = _realized(authed, plat, ticker)
    assert (after[1], after[2]) == (before[1], before[2])
    assert float(after[0]) - float(before[0] or 0) == 54000
    assert _props(db, ticker)[0].status == "confirmed"
    _run(db, D4(2026, 3, 20))
    assert len(_props(db, ticker)) == 1


def test_token_confirm_of_a_schedule_proposal_is_403(authed, db):
    from backend.models import Proposal

    _bond(authed, db, f"{T}R2")
    _run(db, D4(2026, 3, 20))
    p = db.get(Proposal, _props(db, f"{T}R2")[0].id)
    assert authed.post(f"/proposals/{p.id}/confirm", json={"token": p.token}).status_code == 403


def test_edit_amount_then_approve_writes_the_edited_amount(authed, db, approver_key):
    from backend.models import PortfolioEvent, Transaction

    ticker = f"{T}R3"
    _bond(authed, db, ticker)
    _run(db, D4(2026, 3, 20))
    pid = str(_props(db, ticker)[0].id)
    for body, i in (({"amount": 0}, 0), ({"amount": -5}, 0), ({"amount": "50000.123"}, 0), ({"amount": 50000}, 1),
                    ({"amount": 50000, "skip": True}, 0), ({"amount": 50000, "category": "Food"}, 0),
                    ({"category": "Food"}, 0), ({"skip": True}, 0), ({}, 0)):
        assert _patch(authed, approver_key, pid, body, i).status_code == 422, (body, i)
    assert _props(db, ticker)[0].payload["rows"][0]["after"]["amount"] == "54000"
    assert _patch(authed, approver_key, pid, {"amount": 50000}).status_code == 200
    assert _props(db, ticker)[0].payload["rows"][0]["after"]["amount"] == "50000"
    assert _approve(authed, approver_key, pid).status_code == 200
    db.expire_all()
    ev = db.query(PortfolioEvent).filter(PortfolioEvent.ticker == ticker, PortfolioEvent.event_type == "dividend").one()
    assert (ev.price, db.get(Transaction, ev.transaction_id).amount) == (D("50000"), D("50000"))
    assert _patch(authed, approver_key, pid, {"amount": 40000}).status_code == 409


def test_amount_is_refused_on_a_transaction_batch(authed, db, approver_key):
    from backend.models import Proposal
    import datetime as dt
    import secrets

    _, acc = _account(db)
    p = Proposal(token=secrets.token_urlsafe(32), operation="add_transaction", status="pending", channel="mcp",
                 code="ABC234", expires_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1),
                 payload={"operation": "add_transaction", "key": f"x:{T}S:1", "rows": [{"before": None, "after": {
                     "date": "2026-01-10", "amount": "-100", "account": acc, "currency": "IDR"}}]})
    db.add(p)
    db.commit()
    assert _patch(authed, approver_key, str(p.id), {"amount": 5}).status_code == 422


def test_approving_a_coupon_after_the_bond_closed_is_422_and_writes_nothing(authed, db, approver_key):
    ticker = f"{T}R4"
    _, acc, plat = _bond(authed, db, ticker)
    _run(db, D4(2026, 3, 20))
    pid = str(_props(db, ticker)[0].id)
    sell = authed.post("/portfolio-events/funded-sell", json={
        "source_account_name": acc, "platform_id": plat, "ticker": ticker, "quantity": 12000000,
        "price": 1, "cash_amount": 12000000, "date": "2026-03-18"})
    assert sell.status_code == 201, sell.text
    r = _approve(authed, approver_key, pid)
    assert r.status_code == 422 and "no longer held" in r.text
    db.expire_all()
    assert db.execute(text("SELECT count(*) FROM portfolio_events WHERE ticker = :t AND event_type = 'dividend'"),
                      {"t": ticker}).scalar() == 0
    assert db.execute(text("SELECT count(*) FROM transactions WHERE merchant = :m"), {"m": f"Coupon {ticker}"}).scalar() == 0
    assert _props(db, ticker)[0].status == "pending"


def test_approving_maturity_closes_the_position_and_credits_the_account(authed, db, approver_key):
    ticker = f"{T}R5"
    _, acc, plat = _bond(authed, db, ticker)
    _run(db, D4(2026, 4, 15))
    pid = str(next(p for p in _props(db, ticker) if p.operation == "add_funded_sell").id)
    assert _approve(authed, approver_key, pid).status_code == 200
    assert _holding(db, ticker) is None
    assert db.execute(text("SELECT count(*) FROM closed_positions WHERE ticker = :t"), {"t": ticker}).scalar() == 1
    credit = db.execute(text(
        "SELECT t.amount FROM transactions t JOIN accounts a ON a.id = t.account_id "
        "WHERE a.name = :a AND t.amount > 0"), {"a": acc}).scalar()
    assert credit == D("12000000")


# ---------------------------------------------------------------------------
# T5: a coupon's income transaction and dividend event stay in step
# ---------------------------------------------------------------------------


def _coupon(client, db, approver_key, ticker):
    """Approve one 54,000 coupon; return (plat, acc_name, event_id, tx_id)."""
    from backend.models import PortfolioEvent

    _, acc, plat = _bond(client, db, ticker)
    _run(db, D4(2026, 3, 20))
    assert _approve(client, approver_key, str(_props(db, ticker)[0].id)).status_code == 200
    db.expire_all()
    ev = db.query(PortfolioEvent).filter(PortfolioEvent.ticker == ticker, PortfolioEvent.event_type == "dividend").one()
    return plat, acc, ev.id, ev.transaction_id


def _pair(db, ev_id, tx_id):
    from backend.models import PortfolioEvent, Transaction

    db.expire_all()
    ev, tx = db.get(PortfolioEvent, ev_id), db.get(Transaction, tx_id)
    return ev, tx


def _audit(db, entity, eid, op):
    return db.execute(text("SELECT count(*) FROM audit_log WHERE entity = :e AND entity_id = :i AND operation = :o"),
                      {"e": entity, "i": eid, "o": op}).scalar()


def test_event_price_edit_moves_the_transaction_and_realized(authed, db, approver_key):
    ticker = f"{T}L1"
    plat, _, ev_id, tx_id = _coupon(authed, db, approver_key, ticker)
    assert float(_realized(authed, plat, ticker)[0]) == 54000
    r = authed.put(f"/portfolio-events/{ev_id}", json={"price": 50000, "date": "2026-03-16"})
    assert r.status_code == 200, r.text
    ev, tx = _pair(db, ev_id, tx_id)
    assert (tx.amount, tx.date.date(), ev.price, ev.quantity) == (D("50000"), date(2026, 3, 16), D("50000"), D("1"))
    assert float(_realized(authed, plat, ticker)[0]) == 50000
    assert _audit(db, "transaction", tx_id, "edit") == 1


@pytest.mark.parametrize("body", [{"cash_amount": 40000}, {"fee": 0}, {"fee": 100, "fee_kind": "cash"}, {"event_type": "buy"}])
def test_coupon_event_refuses_cash_fee_and_type_switch(authed, db, approver_key, body):
    ticker = f"{T}L2"
    _, _, ev_id, tx_id = _coupon(authed, db, approver_key, ticker)
    assert authed.put(f"/portfolio-events/{ev_id}", json=body).status_code == 422
    ev, tx = _pair(db, ev_id, tx_id)
    assert (tx.amount, ev.event_type, ev.price, ev.fee) == (D("54000"), "dividend", D("54000"), None)


def test_funded_buy_cannot_become_a_dividend(authed, db):
    ticker = f"{T}L3"
    _, acc, plat = _bond(authed, db, ticker)
    ev_id = db.execute(text("SELECT id FROM portfolio_events WHERE ticker = :t"), {"t": ticker}).scalar()
    assert authed.put(f"/portfolio-events/{ev_id}", json={"event_type": "dividend"}).status_code == 422


def test_transaction_amount_edit_moves_the_event_and_realized(authed, db, approver_key):
    ticker = f"{T}L4"
    plat, _, ev_id, tx_id = _coupon(authed, db, approver_key, ticker)
    assert authed.put(f"/transactions/{tx_id}", json={"amount": 52000}).status_code == 200
    ev, tx = _pair(db, ev_id, tx_id)
    assert (tx.amount, ev.quantity, ev.price) == (D("52000"), D("1"), D("52000"))
    assert float(_realized(authed, plat, ticker)[0]) == 52000
    assert _audit(db, "portfolio_event", ev_id, "edit") == 1


@pytest.mark.parametrize("amount", [-100, 0])
def test_transaction_edit_to_non_positive_amount_is_422_and_changes_nothing(authed, db, approver_key, amount):
    ticker = f"{T}L5"
    _, _, ev_id, tx_id = _coupon(authed, db, approver_key, ticker)
    assert authed.put(f"/transactions/{tx_id}", json={"amount": amount}).status_code == 422
    ev, tx = _pair(db, ev_id, tx_id)
    assert (tx.amount, ev.price) == (D("54000"), D("54000"))
    assert _audit(db, "transaction", tx_id, "edit") == 0


def test_transaction_edit_without_amount_leaves_the_event_alone(authed, db, approver_key):
    ticker = f"{T}L6"
    _, _, ev_id, tx_id = _coupon(authed, db, approver_key, ticker)
    assert authed.put(f"/transactions/{tx_id}", json={"notes": "synthetic note"}).status_code == 200
    assert _audit(db, "portfolio_event", ev_id, "edit") == 0
    assert _pair(db, ev_id, tx_id)[0].price == D("54000")


def test_deleting_the_transaction_removes_the_event(authed, db, approver_key):
    from backend.models import PortfolioEvent, Transaction

    ticker = f"{T}L7"
    plat, _, ev_id, tx_id = _coupon(authed, db, approver_key, ticker)
    r = authed.delete(f"/transactions/{tx_id}")
    assert (r.status_code, r.json()["deleted_ids"]) == (200, [tx_id])
    db.expire_all()
    assert db.get(PortfolioEvent, ev_id) is None and db.get(Transaction, tx_id) is None
    assert float(_realized(authed, plat, ticker)[0] or 0) == 0
    assert _audit(db, "portfolio_event", ev_id, "delete") == 1 and _audit(db, "transaction", tx_id, "delete") == 1


def test_bulk_delete_removes_the_event_too(authed, db, approver_key):
    from backend.models import PortfolioEvent

    ticker = f"{T}L8"
    _, _, ev_id, tx_id = _coupon(authed, db, approver_key, ticker)
    r = authed.post("/transactions/bulk-delete", json={"ids": [tx_id]})
    assert r.status_code == 200 and r.json()["deleted"] == [tx_id]
    db.expire_all()
    assert db.get(PortfolioEvent, ev_id) is None


def test_deleting_the_event_removes_the_transaction(authed, db, approver_key):
    from backend.models import Transaction

    ticker = f"{T}L9"
    _, _, ev_id, tx_id = _coupon(authed, db, approver_key, ticker)
    r = authed.delete(f"/portfolio-events/{ev_id}")
    assert (r.status_code, r.json()["deleted_transaction_id"]) == (200, tx_id)
    db.expire_all()
    assert db.get(Transaction, tx_id) is None


def test_funded_buy_leg_behaviour_is_unchanged(authed, db):
    from backend.models import PortfolioEvent, Transaction

    ticker = f"{T}M1"
    _, acc, plat = _bond(authed, db, ticker)
    ev_id, tx_id = db.execute(text("SELECT id, transaction_id FROM portfolio_events WHERE ticker = :t"), {"t": ticker}).one()
    assert authed.put(f"/transactions/{tx_id}", json={"amount": -11000000}).status_code == 200
    db.expire_all()
    ev = db.get(PortfolioEvent, ev_id)
    assert (ev.quantity, ev.price, ev.transaction_id) == (D("12000000"), D("1"), tx_id)  # event untouched
    assert authed.delete(f"/transactions/{tx_id}").status_code == 200
    db.expire_all()
    ev = db.get(PortfolioEvent, ev_id)
    assert ev is not None and ev.transaction_id is None and db.get(Transaction, tx_id) is None
