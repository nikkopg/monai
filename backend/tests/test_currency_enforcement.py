"""DB-level currency enforcement + the transactions_idr view (Phase 42, plan 01).

Covers migration 020 as applied to conftest's `monai_test`: IDR/USD CHECKs, the
composite (account_id, currency) foreign key, the view's honest 7-day
carry-back, and the column-drift guard (D-16). Synthetic values only: `ZZ42 `
account names, round rates, 1901 dates. Skips when Postgres is unreachable.
"""
import secrets
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


@pytest.fixture()
def db():
    from backend.db import SessionLocal, engine

    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception as e:
        pytest.skip(f"Postgres not available: {e}")

    session = SessionLocal()

    def _clean():
        session.rollback()
        session.execute(text("DELETE FROM transactions WHERE date < '1902-01-01'"))
        session.execute(text("DELETE FROM accounts WHERE name LIKE 'ZZ42 %'"))
        session.execute(text("DELETE FROM fx_rate_cache WHERE rate_date < '1902-01-01'"))
        session.commit()

    _clean()
    try:
        yield session
    finally:
        _clean()
        session.close()


def _account(db, name: str, currency: str | None = "IDR") -> int:
    if currency is None:
        sql = "INSERT INTO accounts (name, type) VALUES (:n, 'liquid') RETURNING id"
    else:
        sql = "INSERT INTO accounts (name, type, currency) VALUES (:n, 'liquid', :c) RETURNING id"
    return db.execute(text(sql), {"n": name, "c": currency}).scalar()


def _tx(db, when: date, amount: str, currency: str, account_id: int | None) -> int:
    return db.execute(
        text(
            "INSERT INTO transactions (date, amount, currency, account_id, is_transfer) "
            "VALUES (:d, :a, :c, :acc, false) RETURNING id"
        ),
        {"d": datetime(when.year, when.month, when.day, 12), "a": amount, "c": currency, "acc": account_id},
    ).scalar()


def _rejected(db, fn) -> None:
    with pytest.raises(IntegrityError):
        fn()
    db.rollback()


def test_db_constraints_reject_mismatch_and_out_of_set(db):
    tag = secrets.token_hex(4)
    idr = _account(db, f"ZZ42 db idr {tag}")
    usd = _account(db, f"ZZ42 db usd {tag}", "USD")
    db.commit()

    _rejected(db, lambda: _tx(db, date(1901, 1, 1), "-1.00", "USD", idr))  # mismatch
    _rejected(db, lambda: _account(db, f"ZZ42 db eur {tag}", "EUR"))  # out of set
    _rejected(db, lambda: _tx(db, date(1901, 1, 1), "-1.00", "EUR", None))  # out of set
    _rejected(  # explicit NULL currency
        db,
        lambda: db.execute(
            text("INSERT INTO accounts (name, type, currency) VALUES (:n, 'liquid', NULL)"),
            {"n": f"ZZ42 db null {tag}"},
        ),
    )

    defaulted = _account(db, f"ZZ42 db default {tag}", None)
    assert db.execute(text("SELECT currency FROM accounts WHERE id = :i"), {"i": defaulted}).scalar() == "IDR"
    _tx(db, date(1901, 1, 1), "-1.00", "IDR", None)  # MATCH SIMPLE: NULL account_id unchecked
    _tx(db, date(1901, 1, 1), "-1.00", "USD", usd)
    db.commit()


def _cols(db, table: str) -> list[str]:
    return [
        r[0]
        for r in db.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = :t ORDER BY ordinal_position"
            ),
            {"t": table},
        )
    ]


def test_view_columns_drift_guard(db):
    tx_cols = _cols(db, "transactions")
    assert tx_cols, "transactions table has no columns"
    assert _cols(db, "transactions_idr") == tx_cols + ["amount_idr", "fx_rate", "fx_rate_date"]
    assert _cols(db, "cashflow_transactions") == _cols(db, "transactions_idr")


def _rate(db, rate_date: date, rate: str, effective: date | None = None) -> None:
    db.execute(
        text(
            "INSERT INTO fx_rate_cache (rate_date, base_currency, quote_currency, rate, source, rate_effective_date) "
            "VALUES (:d, 'USD', 'IDR', :r, 'test', :e)"
        ),
        {"d": rate_date, "r": rate, "e": effective},
    )


def _view(db, tx_id: int):
    return db.execute(
        text("SELECT amount_idr, fx_rate, fx_rate_date FROM transactions_idr WHERE id = :i"), {"i": tx_id}
    ).one()


def test_idr_view_values(db):
    tag = secrets.token_hex(4)
    idr = _account(db, f"ZZ42 view idr {tag}")
    usd = _account(db, f"ZZ42 view usd {tag}", "USD")
    _rate(db, date(1901, 1, 4), "16000.000000")
    _rate(db, date(1901, 2, 2), "16100.000000", effective=date(1901, 2, 1))
    _rate(db, date(1901, 3, 1), "16000.000000")
    _rate(db, date(1901, 3, 4), "16200.000000")

    sat = _tx(db, date(1901, 1, 5), "-12.50", "USD", usd)
    incl = _tx(db, date(1901, 1, 11), "-12.50", "USD", usd)  # d-7 inclusive
    excl = _tx(db, date(1901, 1, 12), "-12.50", "USD", usd)  # d-8 excluded
    eff = _tx(db, date(1901, 2, 2), "-1.00", "USD", usd)
    latest = _tx(db, date(1901, 3, 5), "-1.00", "USD", usd)
    idr_tx = _tx(db, date(1901, 1, 5), "-5000.00", "IDR", idr)
    db.commit()

    assert _view(db, sat) == (Decimal("-200000"), Decimal("16000"), date(1901, 1, 4))
    assert _view(db, incl)[1:] == (Decimal("16000"), date(1901, 1, 4))
    assert _view(db, excl) == (None, None, None)  # no default rate, ever
    assert _view(db, eff)[2] == date(1901, 2, 1)
    assert _view(db, latest)[1] == Decimal("16200")
    assert _view(db, idr_tx) == (Decimal("-5000"), Decimal("1"), None)


def test_models_are_db_light():
    from sqlalchemy.orm import configure_mappers

    from backend.models import Account, FxRateCache, Transaction

    acc = Account.__table__.c.currency
    assert acc.nullable is False and str(acc.server_default.arg) == "IDR"
    assert str(Transaction.__table__.c.currency.server_default.arg) == "IDR"
    eff = FxRateCache.__table__.c.rate_effective_date
    assert eff.nullable is True
    for fk in Transaction.__table__.foreign_key_constraints:
        assert {c.name for c in fk.columns} != {"account_id", "currency"}
    configure_mappers()
