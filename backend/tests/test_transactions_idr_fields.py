"""Phase 44 D-16: GET /transactions rows carry amount_idr, fx_rate and fx_rate_date.

The values come from the transactions_idr view. Every value is synthetic (ZZ44
names, 1997 dates, round rates) and the FX adapters are stubbed: this file never
touches the network. The range stub counts its calls so "no vendor call when
covered, at most one when not" is asserted, not assumed.
"""

from datetime import date, datetime

import pytest
from sqlalchemy import text

from backend import fx
from backend.db import SessionLocal


def _clean() -> None:
    s = SessionLocal()
    try:
        ids = "SELECT id FROM transactions WHERE account_id IN (SELECT id FROM accounts WHERE name LIKE 'ZZ44 %')"
        s.execute(text(f"DELETE FROM audit_log WHERE entity = 'transaction' AND entity_id IN ({ids})"))
        s.execute(text(
            "DELETE FROM transactions WHERE account_id IN (SELECT id FROM accounts WHERE name LIKE 'ZZ44 %')"))
        s.execute(text("DELETE FROM accounts WHERE name LIKE 'ZZ44 %'"))
        s.execute(text(
            "DELETE FROM fx_rate_cache WHERE base_currency = 'USD' AND quote_currency = 'IDR' "
            "AND rate_date BETWEEN '1997-01-01' AND '1997-12-31'"))
        s.commit()
    finally:
        s.close()


@pytest.fixture()
def idr_env(monkeypatch):
    """Clean slate + network-free FX; yields the list of range-vendor calls."""
    calls: list[tuple] = []

    def _range(base, quote, start, end):
        calls.append((base, quote, start, end))
        return None

    monkeypatch.setitem(fx.FX_ADAPTERS, "frankfurter", lambda base, quote, as_of: None)
    monkeypatch.setitem(fx.FX_RANGE_ADAPTERS, "frankfurter", _range)
    _clean()
    try:
        yield calls
    finally:
        _clean()


def _account(currency: str) -> int:
    s = SessionLocal()
    try:
        acc = s.execute(text(
            "INSERT INTO accounts (name, type, currency) VALUES (:n, 'liquid', :c) RETURNING id"),
            {"n": f"ZZ44 {currency.lower()} fields", "c": currency}).scalar()
        s.commit()
        return acc
    finally:
        s.close()


def _tx(acc: int, day: date, amount: str, currency: str) -> int:
    s = SessionLocal()
    try:
        tid = s.execute(text(
            "INSERT INTO transactions (date, amount, currency, merchant, account_id, is_transfer) "
            "VALUES (:d, :a, :c, 'zz44 row', :acc, false) RETURNING id"),
            {"d": datetime(day.year, day.month, day.day, 12), "a": amount, "c": currency, "acc": acc}).scalar()
        s.commit()
        return tid
    finally:
        s.close()


def _rate(day: date, rate: str) -> None:
    s = SessionLocal()
    try:
        s.execute(text(
            "INSERT INTO fx_rate_cache (rate_date, base_currency, quote_currency, rate, source, fetched_at) "
            "VALUES (:d, 'USD', 'IDR', :r, 'frankfurter', now())"), {"d": day, "r": rate})
        s.commit()
    finally:
        s.close()


def test_idr_row_fields(authed, idr_env):
    acc = _account("IDR")
    _tx(acc, date(1997, 6, 6), "-50000.00", "IDR")
    rows = authed.get("/transactions", params={"account_id": acc}).json()
    assert len(rows) == 1
    assert rows[0].get("amount_idr") == -50000.0
    assert rows[0].get("fx_rate") == 1.0
    assert rows[0].get("fx_rate_date") is None
    assert idr_env == []


def test_usd_row_carry_back(authed, idr_env):
    """A Saturday row reads Friday's cached rate and says so (view carry-back)."""
    acc = _account("USD")
    _rate(date(1997, 6, 6), "16000.000000")
    _tx(acc, date(1997, 6, 7), "-12.50", "USD")
    rows = authed.get("/transactions", params={"account_id": acc}).json()
    assert len(rows) == 1
    assert rows[0].get("amount_idr") == -200000.0
    assert rows[0].get("fx_rate") == 16000.0
    assert rows[0].get("fx_rate_date") == "1997-06-06"
    assert idr_env == []


def test_usd_row_no_rate_is_null(authed, idr_env):
    """No rate within 7 days: 200, three nulls, at most one vendor call, never a guess."""
    acc = _account("USD")
    _tx(acc, date(1997, 9, 10), "-12.50", "USD")
    r = authed.get("/transactions", params={"account_id": acc})
    assert r.status_code == 200
    row = r.json()[0]
    assert row["amount"] == -12.5
    assert row.get("amount_idr") is None
    assert row.get("fx_rate") is None
    assert row.get("fx_rate_date") is None
    assert len(idr_env) == 1


def test_paging_and_amount_filter_unchanged(authed, idr_env):
    acc = _account("IDR")
    old, mid, new = (_tx(acc, date(1997, 6, d), "-1000.00", "IDR") for d in (2, 3, 4))
    first = authed.get("/transactions", params={"account_id": acc, "limit": 2, "offset": 0}).json()
    assert [r["id"] for r in first] == [new, mid]
    assert [r["id"] for r in authed.get(
        "/transactions", params={"account_id": acc, "limit": 2, "offset": 2}).json()] == [old]

    usd = _account("USD")
    _rate(date(1997, 6, 6), "16000.000000")
    uid = _tx(usd, date(1997, 6, 6), "-12.50", "USD")
    hit = authed.get("/transactions", params={"account_id": usd, "amount_min": 12}).json()
    assert [r["id"] for r in hit] == [uid]
    assert authed.get("/transactions", params={"account_id": usd, "amount_min": 13}).json() == []
