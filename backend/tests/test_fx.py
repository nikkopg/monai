"""
FX adapter + immutable rate-cache tests (Plan 07-01).

Mirrors test_prices.py's mocked-httpx style. Proves (not assumes): the
adapter never raises, the cache is immutable per (date, base, quote)
(FX-05), and the SSRF guard rejects invalid currency codes before any HTTP
request is issued (Pitfall 5).
"""

from datetime import date
from decimal import Decimal

import httpx
import pytest


def test_fetch_frankfurter_rate_success(monkeypatch):
    """Mocked httpx returning rates -> (Decimal, 'frankfurter'), Decimal exact."""
    from backend import fx

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"amount": 1.0, "base": "USD", "date": "2024-01-15", "rates": {"IDR": 15561}}

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Resp())
    result = fx.fetch_frankfurter_rate("USD", "IDR", date(2024, 1, 15))
    assert result == (Decimal("15561"), "frankfurter")
    assert isinstance(result[0], Decimal)


def test_fetch_frankfurter_rate_http_error_returns_none(monkeypatch):
    """httpx.HTTPError / 404 -> None, never raises."""
    from backend import fx

    def _boom(*a, **k):
        raise httpx.HTTPError("boom")

    monkeypatch.setattr(httpx, "get", _boom)
    assert fx.fetch_frankfurter_rate("USD", "IDR", date(2024, 1, 15)) is None


def test_fetch_frankfurter_rate_malformed_json_returns_none(monkeypatch):
    """Missing/malformed rates key -> None, never raises."""
    from backend import fx

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"rates": {}}  # quote currency absent

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Resp())
    assert fx.fetch_frankfurter_rate("USD", "IDR", date(2024, 1, 15)) is None


def test_get_rate_identity_shortcut_no_http_call(monkeypatch):
    """base == quote -> Decimal('1'), no HTTP call issued."""
    from backend import fx

    def _boom(*a, **k):
        raise AssertionError("must not call the network for base==quote")

    monkeypatch.setattr(httpx, "get", _boom)
    assert fx.get_rate("IDR", "IDR", date(2024, 1, 15), db=None) == Decimal("1")


def test_get_rate_invalid_currency_no_http_call(monkeypatch):
    """Currency failing ^[A-Z]{3,4}$ -> None, WITHOUT any HTTP request (SSRF guard)."""
    from backend import fx

    def _boom(*a, **k):
        raise AssertionError("must not call the network for an invalid currency code")

    monkeypatch.setattr(httpx, "get", _boom)
    assert fx.get_rate("XX!", "IDR", date(2024, 1, 15), db=None) is None


def test_get_rate_usdt_treated_as_usd(monkeypatch):
    """base='USDT' -> normalized to USD before the frankfurter call (FX-02)."""
    from backend import fx

    captured = {}

    def _get(url, params, timeout):
        captured.update(params)

        class _Resp:
            def raise_for_status(self):
                pass

            def json(self):
                return {"rates": {"IDR": 15561}}

        return _Resp()

    monkeypatch.setattr(httpx, "get", _get)
    result = fx.get_rate("USDT", "IDR", date(2024, 1, 15), db=_FakeDb())
    assert result == Decimal("15561")
    assert captured["base"] == "USD"


def test_get_rate_adapter_none_returns_none_no_fallback_to_one(monkeypatch):
    """Adapter returning None (vendor outage) -> None, never rate=1.0."""
    from backend import fx

    def _boom(*a, **k):
        raise httpx.HTTPError("vendor down")

    monkeypatch.setattr(httpx, "get", _boom)
    assert fx.get_rate("USD", "IDR", date(2024, 1, 15), db=_FakeDb()) is None


class _FakeRow:
    def __init__(self, rate):
        self.rate = rate


class _FakeQuery:
    """Minimal stand-in for db.scalars(select(...)).first() used by get_rate."""

    def __init__(self, existing_row=None):
        self._existing_row = existing_row

    def first(self):
        return self._existing_row


class _FakeDb:
    """Minimal Session stand-in: tracks .add() calls, cache starts empty."""

    def __init__(self, existing_row=None):
        self.added = []
        self._existing_row = existing_row

    def scalars(self, _stmt):
        return _FakeQuery(self._existing_row)

    def add(self, obj):
        self.added.append(obj)


def test_get_rate_cache_hit_does_not_call_adapter(monkeypatch):
    """Cache HIT returns stored Decimal without calling the adapter (FX-05)."""
    from backend import fx

    def _boom(*a, **k):
        raise AssertionError("adapter must not be called on a cache hit")

    monkeypatch.setattr(httpx, "get", _boom)

    db = _FakeDb(existing_row=_FakeRow(Decimal("15561")))
    result = fx.get_rate("USD", "IDR", date(2024, 1, 15), db=db)
    assert result == Decimal("15561")
    assert isinstance(result, Decimal)
    assert db.added == []


def test_get_rate_cache_miss_writes_exactly_one_row(monkeypatch):
    """Cache MISS calls adapter, writes exactly one fx_rate_cache row."""
    from backend import fx

    call_count = {"n": 0}

    def _get(url, params, timeout):
        call_count["n"] += 1

        class _Resp:
            def raise_for_status(self):
                pass

            def json(self):
                return {"rates": {"IDR": 15561}}

        return _Resp()

    monkeypatch.setattr(httpx, "get", _get)

    db = _FakeDb(existing_row=None)
    result = fx.get_rate("USD", "IDR", date(2024, 1, 15), db=db)
    assert result == Decimal("15561")
    assert call_count["n"] == 1
    assert len(db.added) == 1
    row = db.added[0]
    assert row.rate_date == date(2024, 1, 15)
    assert row.base_currency == "USD"
    assert row.quote_currency == "IDR"
    assert row.rate == Decimal("15561")
    assert row.source == "frankfurter"


def test_get_rate_second_call_same_pair_does_not_refetch(monkeypatch):
    """A second get_rate for the same (date, USD, IDR) reads the cache — no
    second HTTP call, no second row write (FX-05 immutability, full round-trip)."""
    from backend import fx

    call_count = {"n": 0}

    def _get(url, params, timeout):
        call_count["n"] += 1

        class _Resp:
            def raise_for_status(self):
                pass

            def json(self):
                return {"rates": {"IDR": 15561}}

        return _Resp()

    monkeypatch.setattr(httpx, "get", _get)

    # Simulates the real DB round-trip: after the first miss+insert, a second
    # get_rate call would find the row via a fresh query. We model this by
    # constructing a DB whose scalars() reflects whatever has been added so far.
    class _StatefulDb:
        def __init__(self):
            self.added = []

        def scalars(self, _stmt):
            return _FakeQuery(self.added[0] if self.added else None)

        def add(self, obj):
            self.added.append(obj)

    db = _StatefulDb()
    first = fx.get_rate("USD", "IDR", date(2024, 1, 15), db=db)
    second = fx.get_rate("USD", "IDR", date(2024, 1, 15), db=db)
    assert first == Decimal("15561")
    assert second == Decimal("15561")
    assert call_count["n"] == 1, "adapter must be called exactly once across both get_rate calls"
    assert len(db.added) == 1, "exactly one fx_rate_cache row must be written"


def test_cash_and_gold_have_explicit_ttl_entries():
    """cash and gold must not silently inherit _DEFAULT_TTL (Pitfall 1)."""
    from backend import prices

    assert "gold" in prices.TTL_BY_ASSET_TYPE
    assert "cash" in prices.TTL_BY_ASSET_TYPE
    assert prices.TTL_BY_ASSET_TYPE["gold"] == prices.TTL_BY_ASSET_TYPE["mutual_fund"]
