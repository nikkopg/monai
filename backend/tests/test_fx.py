"""
FX adapter + immutable rate-cache tests (Plan 07-01; durable write tests
added Plan 27-02).

Mirrors test_prices.py's mocked-httpx style. Proves (not assumes): the
adapter never raises, the cache is immutable per (date, base, quote)
(FX-05), the SSRF guard rejects invalid currency codes before any HTTP
request is issued (Pitfall 5), and (WRITE-03) a fetched rate is committed
durably through a dedicated session no matter what the caller's own
transaction does.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import text

# Synthetic key: 1900-01-01 predates all vendor data. Committed rows persist
# in monai_test across runs, so every durable-write test below uses only
# this key and cleans it via the fx_key_clean fixture (before AND after).
_KEY_DATE = date(1900, 1, 1)


@pytest.fixture()
def fx_key_clean():
    """Deletes the synthetic (1900-01-01, USD, IDR) fx_rate_cache row before
    and after the test. Skips when Postgres is unreachable (test_proposals.py
    db_available idiom)."""
    from backend.db import SessionLocal, engine

    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception as e:
        pytest.skip(f"Postgres not available: {e}")

    def _clean():
        db = SessionLocal()
        try:
            db.execute(
                text(
                    "DELETE FROM fx_rate_cache WHERE rate_date = :d "
                    "AND base_currency = 'USD' AND quote_currency = 'IDR'"
                ),
                {"d": _KEY_DATE},
            )
            db.commit()
        finally:
            db.close()

    _clean()
    yield
    _clean()


_JAN_TODAY = date(1900, 1, 10)


@pytest.fixture()
def fx_jan1900_clean(monkeypatch):
    """Deletes USD->IDR fx_rate_cache rows dated January 1900 before and after,
    and pins the Jakarta "today" to 1900-01-10. Skips when Postgres is down."""
    from backend import fx
    from backend.db import SessionLocal, engine

    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception as e:
        pytest.skip(f"Postgres not available: {e}")

    def _clean():
        db = SessionLocal()
        try:
            db.execute(
                text(
                    "DELETE FROM fx_rate_cache WHERE rate_date BETWEEN '1900-01-01' "
                    "AND '1900-01-31' AND base_currency = 'USD' AND quote_currency = 'IDR'"
                )
            )
            db.commit()
        finally:
            db.close()

    _clean()
    monkeypatch.setattr(fx, "_jakarta_today", lambda: _JAN_TODAY, raising=False)
    yield
    _clean()


def _jan_rows() -> list[tuple]:
    from backend.db import SessionLocal

    db = SessionLocal()
    try:
        return [
            tuple(r)
            for r in db.execute(
                text(
                    "SELECT rate_date, rate_effective_date, rate FROM fx_rate_cache "
                    "WHERE rate_date BETWEEN '1900-01-01' AND '1900-01-31' "
                    "AND base_currency = 'USD' AND quote_currency = 'IDR' ORDER BY rate_date"
                )
            )
        ]
    finally:
        db.close()


def _count_key_rows() -> int:
    from backend.db import SessionLocal

    db = SessionLocal()
    try:
        return int(
            db.execute(
                text(
                    "SELECT COUNT(*) FROM fx_rate_cache WHERE rate_date = :d "
                    "AND base_currency = 'USD' AND quote_currency = 'IDR'"
                ),
                {"d": _KEY_DATE},
            ).scalar()
            or 0
        )
    finally:
        db.close()


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
    assert result == (Decimal("15561"), "frankfurter", date(2024, 1, 15))
    assert isinstance(result[0], Decimal)


def _resp(body):
    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return body

    return _Resp()


def test_fetch_frankfurter_rate_missing_date_tolerated(monkeypatch):
    """A body without "date" -> effective date None, rate still returned."""
    from backend import fx

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _resp({"rates": {"IDR": 15561}}))
    assert fx.fetch_frankfurter_rate("USD", "IDR", date(2024, 1, 15)) == (
        Decimal("15561"),
        "frankfurter",
        None,
    )


def test_fetch_frankfurter_rate_malformed_date_returns_none(monkeypatch):
    """A malformed "date" -> None, never raises."""
    from backend import fx

    monkeypatch.setattr(
        httpx, "get", lambda *a, **k: _resp({"date": "not-a-date", "rates": {"IDR": 15561}})
    )
    assert fx.fetch_frankfurter_rate("USD", "IDR", date(2024, 1, 15)) is None


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


def test_get_rate_usdt_treated_as_usd(monkeypatch, fx_key_clean):
    """base='USDT' -> normalized to USD before the frankfurter call (FX-02).

    Uses the cleaned synthetic key (fx_key_clean): a cache miss now commits
    durably (WRITE-03), so this test needs a key it can safely clean up.
    """
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
    result = fx.get_rate("USDT", "IDR", _KEY_DATE, db=_FakeDb())
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
    def __init__(self, rate, rate_date=date(2024, 1, 15), rate_effective_date=None):
        self.rate = rate
        self.rate_date = rate_date
        self.rate_effective_date = rate_effective_date


class _FakeQuery:
    """Minimal stand-in for db.scalars(select(...)).first() used by get_rate."""

    def __init__(self, existing_row=None):
        self._existing_row = existing_row

    def first(self):
        return self._existing_row


class _FakeDb:
    """Minimal Session stand-in for the CALLER side of get_rate. Read-only:
    get_rate no longer add()s/flush()es onto the caller's session (WRITE-03,
    D-17) — the cache-miss write now happens on its own dedicated
    SessionLocal(). This fake's `added` must stay empty for every test that
    uses it."""

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


def test_get_rate_durable_when_caller_never_commits(monkeypatch, fx_key_clean):
    """WRITE-03/D-17: a fetched rate is committed even when the caller's own
    session is closed without ever committing — the write lands on a short
    dedicated SessionLocal(), never on the caller's session."""
    from backend import fx
    from backend.db import SessionLocal

    call_count = {"n": 0}

    def _get(url, params, timeout):
        call_count["n"] += 1

        class _Resp:
            def raise_for_status(self):
                pass

            def json(self):
                return {"rates": {"IDR": 12345}}

        return _Resp()

    monkeypatch.setattr(httpx, "get", _get)

    caller = SessionLocal()
    try:
        result = fx.get_rate("USD", "IDR", _KEY_DATE, db=caller)
        assert result == Decimal("12345")
        # get_rate never add()s/flush()es anything onto the caller's session.
        assert not caller.new
        assert not caller.dirty
    finally:
        caller.close()  # closed WITHOUT committing

    assert call_count["n"] == 1
    assert _count_key_rows() == 1


def test_get_rate_no_refetch_after_durable_write(monkeypatch, fx_key_clean):
    """WRITE-03/D-18: a second get_rate on the SAME caller session sees the
    durably committed row under READ COMMITTED — no re-fetch. A third call on
    a fresh session also sees it, still with no re-fetch and no second row."""
    from backend import fx
    from backend.db import SessionLocal

    def _first_get(url, params, timeout):
        class _Resp:
            def raise_for_status(self):
                pass

            def json(self):
                return {"rates": {"IDR": 12345}}

        return _Resp()

    monkeypatch.setattr(httpx, "get", _first_get)

    caller1 = SessionLocal()
    try:
        first = fx.get_rate("USD", "IDR", _KEY_DATE, db=caller1)
        assert first == Decimal("12345")

        def _boom(*a, **k):
            raise AssertionError("must not refetch — the row is already durably committed")

        monkeypatch.setattr(httpx, "get", _boom)

        second = fx.get_rate("USD", "IDR", _KEY_DATE, db=caller1)
        assert second == Decimal("12345")
    finally:
        caller1.close()  # closed WITHOUT committing

    caller2 = SessionLocal()
    try:
        third = fx.get_rate("USD", "IDR", _KEY_DATE, db=caller2)
        assert third == Decimal("12345")
    finally:
        caller2.close()

    assert _count_key_rows() == 1


def test_get_rate_integrity_conflict_returns_existing_row(monkeypatch, fx_key_clean):
    """WRITE-03/D-19: when the dedicated insert loses a race, the pre-existing
    (immutable) row wins — the freshly fetched rate is discarded, never
    fabricated on top of it (FX-05)."""
    from backend import fx
    from backend.db import SessionLocal
    from backend.models import FxRateCache

    seed = SessionLocal()
    try:
        seed.add(
            FxRateCache(
                rate_date=_KEY_DATE,
                base_currency="USD",
                quote_currency="IDR",
                rate=Decimal("11111"),
                source="zz-test",
                fetched_at=datetime.now(timezone.utc),
            )
        )
        seed.commit()
    finally:
        seed.close()

    def _get(url, params, timeout):
        class _Resp:
            def raise_for_status(self):
                pass

            def json(self):
                return {"rates": {"IDR": 22222}}

        return _Resp()

    monkeypatch.setattr(httpx, "get", _get)

    db = _FakeDb()  # existing_row=None -> forces a cache miss on the caller's read
    result = fx.get_rate("USD", "IDR", _KEY_DATE, db=db)
    assert result == Decimal("11111")
    assert db.added == []

    assert _count_key_rows() == 1


def test_get_rate_past_saturday_records_effective_date(monkeypatch, fx_jan1900_clean):
    """D-19: a past weekend date is cached under the requested date with the
    business date Frankfurter reports beside it."""
    from backend import fx

    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **k: _resp({"date": "1900-01-05", "rates": {"IDR": 16000}}),
    )
    assert fx.get_rate("USD", "IDR", date(1900, 1, 6), db=_FakeDb()) == Decimal("16000")
    assert _jan_rows() == [(date(1900, 1, 6), date(1900, 1, 5), Decimal("16000.000000"))]


def test_get_rate_today_and_future_not_persisted(monkeypatch, fx_jan1900_clean):
    """D-17: as_of >= Jakarta today returns a rate and writes nothing; today-1 persists."""
    from backend import fx

    monkeypatch.setattr(
        httpx, "get", lambda *a, **k: _resp({"date": "1900-01-09", "rates": {"IDR": 16000}})
    )
    for d in (date(1900, 1, 10), date(1900, 1, 11)):
        assert fx.get_rate("USD", "IDR", d, db=_FakeDb()) == Decimal("16000")
    assert _jan_rows() == []
    assert fx.get_rate("USD", "IDR", date(1900, 1, 9), db=_FakeDb()) == Decimal("16000")
    assert [r[0] for r in _jan_rows()] == [date(1900, 1, 9)]


def test_get_rate_today_ignores_frozen_cache_row(monkeypatch, fx_jan1900_clean):
    """D-17/D-24: a row frozen under today's date is neither served nor modified."""
    from backend import fx
    from backend.db import SessionLocal
    from backend.models import FxRateCache

    seed = SessionLocal()
    try:
        seed.add(
            FxRateCache(
                rate_date=_JAN_TODAY,
                base_currency="USD",
                quote_currency="IDR",
                rate=Decimal("15000"),
                source="zz-test",
                fetched_at=datetime.now(timezone.utc),
            )
        )
        seed.commit()
    finally:
        seed.close()

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _resp({"rates": {"IDR": 16000}}))
    db = _FakeDb(existing_row=_FakeRow(Decimal("15000")))
    assert fx.get_rate("USD", "IDR", _JAN_TODAY, db=db) == Decimal("16000")
    assert _jan_rows() == [(_JAN_TODAY, None, Decimal("15000.000000"))]


def test_cash_and_gold_have_explicit_ttl_entries():
    """cash and gold must not silently inherit _DEFAULT_TTL (Pitfall 1)."""
    from backend import prices

    assert "gold" in prices.TTL_BY_ASSET_TYPE
    assert "cash" in prices.TTL_BY_ASSET_TYPE
    assert prices.TTL_BY_ASSET_TYPE["gold"] == prices.TTL_BY_ASSET_TYPE["mutual_fund"]
