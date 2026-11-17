"""SBN bond support (quick 261117-rw1): coupon math, pay dates and the migration 024 schema.

All values are synthetic. The schema test only reads catalog tables; it writes nothing.
"""
import uuid
from datetime import date
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
        "DELETE FROM audit_log WHERE before->>'ticker' LIKE 'ZZSBN2%' OR after->>'ticker' LIKE 'ZZSBN2%'",
        f"DELETE FROM portfolio_events WHERE ticker LIKE 'ZZSBN2%' OR platform_id IN {plats}",
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


def _buy(client, acc_name, plat, ticker, bond=None, asset_type="bond", qty=12000000):
    body = {"source_account_name": acc_name, "platform_id": plat, "ticker": ticker,
            "quantity": qty, "price": 1, "cash_amount": qty, "date": "2026-11-01",
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
