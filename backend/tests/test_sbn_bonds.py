"""SBN bond support (quick 261117-rw1): coupon math, pay dates and the migration 024 schema.

All values are synthetic. The schema test only reads catalog tables; it writes nothing.
"""
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
