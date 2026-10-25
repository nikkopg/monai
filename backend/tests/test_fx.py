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


def test_fetch_frankfurter_rate_bad_rate_returns_none(monkeypatch):
    """null / garbage / zero / negative / non-finite rate -> None, never raises."""
    from backend import fx

    for bad in ("garbage", 0, -1, "NaN", "Infinity"):
        monkeypatch.setattr(
            httpx, "get", lambda *a, _b=bad, **k: _resp({"date": "2024-01-15", "rates": {"IDR": _b}})
        )
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


def _counting_get(body):
    calls = {"n": 0}

    def _get(*a, **k):
        calls["n"] += 1
        return _resp(body)

    return calls, _get


def _failing_get(*a, **k):
    raise httpx.HTTPError("vendor down")


def test_get_rate_today_memo_one_http_call(monkeypatch, fx_jan1900_clean):
    """D-18: today's rate is memoised ~15 min per (pair, date); never in the DB."""
    from types import SimpleNamespace

    from backend import fx

    calls, getter = _counting_get({"rates": {"IDR": 16000}})
    monkeypatch.setattr(httpx, "get", getter)
    clock = {"t": 1000.0}
    monkeypatch.setattr(fx, "time", SimpleNamespace(monotonic=lambda: clock["t"]))

    for _ in range(2):
        assert fx.get_rate("USD", "IDR", _JAN_TODAY, db=_FakeDb()) == Decimal("16000")
    assert calls["n"] == 1
    clock["t"] += fx._TODAY_TTL_SECONDS + 1
    assert fx.get_rate("USD", "IDR", _JAN_TODAY, db=_FakeDb()) == Decimal("16000")
    assert calls["n"] == 2
    assert _jan_rows() == []


def test_get_rate_today_failure_not_memoised(monkeypatch, fx_jan1900_clean):
    from backend import fx

    monkeypatch.setattr(httpx, "get", _failing_get)
    assert fx.get_rate("USD", "IDR", _JAN_TODAY, db=_FakeDb()) is None
    calls, getter = _counting_get({"rates": {"IDR": 16000}})
    monkeypatch.setattr(httpx, "get", getter)
    assert fx.get_rate("USD", "IDR", _JAN_TODAY, db=_FakeDb()) == Decimal("16000")
    assert calls["n"] == 1


def test_spot_returns_rate_and_effective_date(monkeypatch, fx_jan1900_clean):
    from backend import fx

    monkeypatch.setattr(
        httpx, "get", lambda *a, **k: _resp({"date": "1900-01-09", "rates": {"IDR": 16000}})
    )
    assert fx.spot("USD", _FakeDb()) == (Decimal("16000"), date(1900, 1, 9))

    monkeypatch.setattr(httpx, "get", _failing_get)
    assert fx.spot("IDR", _FakeDb()) == (Decimal("1"), _JAN_TODAY)  # identity, no HTTP
    fx._today_memo.clear()
    with pytest.raises(fx.FxUnavailable):
        fx.spot("USD", _FakeDb())


def test_to_idr(monkeypatch, fx_jan1900_clean):
    from backend import fx

    monkeypatch.setattr(httpx, "get", _failing_get)
    out = fx.to_idr(Decimal("-12.50"), "IDR", date(1900, 1, 3), _FakeDb())
    assert out == Decimal("-12.50") and isinstance(out, Decimal)
    with pytest.raises(fx.FxUnavailable):  # never returns the unconverted amount
        fx.to_idr("-12.50", "USD", date(1900, 1, 3), _FakeDb())

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _resp({"rates": {"IDR": 16000}}))
    out = fx.to_idr("-12.50", "USD", date(1900, 1, 3), _FakeDb())
    assert out == Decimal("-200000.00") and isinstance(out, Decimal)


def test_base_and_exception():
    from backend import fx

    assert fx.BASE == "IDR"
    assert issubclass(fx.FxUnavailable, Exception)


def test_cash_and_gold_have_explicit_ttl_entries():
    """cash and gold must not silently inherit _DEFAULT_TTL (Pitfall 1)."""
    from backend import prices

    assert "gold" in prices.TTL_BY_ASSET_TYPE
    assert "cash" in prices.TTL_BY_ASSET_TYPE
    assert prices.TTL_BY_ASSET_TYPE["gold"] == prices.TTL_BY_ASSET_TYPE["mutual_fund"]


# ---------------------------------------------------------------------------
# Range adapter, _store_range, ensure_flow_rates (Phase 42-05, D-20/D-21).
# Synthetic dates: 1902 (store tests, today pinned 1902-01-07), 1903 (ensure
# tests, today pinned 1903-04-01). Rates are round numbers.
# ---------------------------------------------------------------------------

def _range_body(rates: dict):
    return _resp({"base": "USD", "rates": {d: {"IDR": v} for d, v in rates.items()}})


def test_fetch_frankfurter_range_parses_probe_shape(monkeypatch):
    from backend import fx

    body = _range_body({"1902-01-03": 16000, "1902-01-06": 16050.5})
    monkeypatch.setattr(httpx, "get", lambda *a, **k: body)
    got = fx.fetch_frankfurter_range("USD", "IDR", date(1902, 1, 3), date(1902, 1, 6))
    assert got == [(date(1902, 1, 3), Decimal("16000")), (date(1902, 1, 6), Decimal("16050.5"))]
    assert fx.FX_RANGE_ADAPTERS["frankfurter"] is fx.fetch_frankfurter_range


def test_fetch_frankfurter_range_failures_return_none(monkeypatch):
    from backend import fx

    class _NotFound:
        def raise_for_status(self):
            req = httpx.Request("GET", "https://example.invalid")
            raise httpx.HTTPStatusError("404", request=req, response=httpx.Response(404, request=req))

    bad = [
        _NotFound(),
        _resp({"rates": {"1902-01-03": [16000]}}),  # value is a list
        _resp({"rates": {"not-a-date": {"IDR": 16000}}}),  # non-date key
        _resp({"rates": {"1902-01-03": {"IDR": "garbage"}}}),  # InvalidOperation
        _resp({"rates": {"1902-01-03": {"IDR": 16000}, "1902-01-06": {"IDR": 0}}}),  # zero rate
        _resp({"rates": {"1902-01-03": {"IDR": -5}}}),  # negative rate
    ]
    for r in bad:
        monkeypatch.setattr(httpx, "get", lambda *a, _r=r, **k: _r)
        assert fx.fetch_frankfurter_range("USD", "IDR", date(1902, 1, 3), date(1902, 1, 6)) is None


@pytest.fixture()
def range_env(monkeypatch):
    """Counts httpx.get calls; cleans 1902/1903 USD->IDR rows, ZZ42 fx accounts
    and 1903 transactions before and after. Skips when Postgres is down."""
    from backend import fx
    from backend.db import SessionLocal, engine

    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception as e:
        pytest.skip(f"Postgres not available: {e}")

    def _clean():
        s = SessionLocal()
        try:
            s.execute(text("DELETE FROM transactions WHERE date >= '1903-01-01' AND date < '1904-01-01'"))
            s.execute(text("DELETE FROM accounts WHERE name LIKE 'ZZ42 fx %'"))
            s.execute(text(
                "DELETE FROM fx_rate_cache WHERE rate_date >= '1902-01-01' AND rate_date < '1904-01-01' "
                "AND base_currency = 'USD' AND quote_currency = 'IDR'"
            ))
            s.commit()
        finally:
            s.close()

    _clean()
    env = {"calls": [], "behaviour": None}

    def pin(today):
        monkeypatch.setattr(fx, "_jakarta_today", lambda: today)

    def _get(url, params=None, **kw):
        env["calls"].append((url, params))
        return env["behaviour"]()

    monkeypatch.setattr(httpx, "get", _get)
    env["pin"] = pin
    yield env
    _clean()


def _seed_cache(rate_date: date, rate: str) -> None:
    from backend.db import SessionLocal

    s = SessionLocal()
    try:
        s.execute(
            text(
                "INSERT INTO fx_rate_cache (rate_date, base_currency, quote_currency, rate, source, fetched_at) "
                "VALUES (:d, 'USD', 'IDR', :r, 'frankfurter', now())"
            ),
            {"d": rate_date, "r": rate},
        )
        s.commit()
    finally:
        s.close()


def _seed_txs(rows: list[tuple[date, str, str]]) -> None:
    """rows: (day, amount, currency). One account per currency."""
    import secrets

    from backend.db import SessionLocal

    s = SessionLocal()
    try:
        accounts: dict[str, int] = {}
        for _day, _amt, cur in rows:
            if cur not in accounts:
                accounts[cur] = s.execute(
                    text("INSERT INTO accounts (name, type, currency) VALUES (:n, 'liquid', :c) RETURNING id"),
                    {"n": f"ZZ42 fx {cur.lower()} {secrets.token_hex(4)}", "c": cur},
                ).scalar()
        for day, amt, cur in rows:
            s.execute(
                text(
                    "INSERT INTO transactions (date, amount, currency, account_id, is_transfer) "
                    "VALUES (:d, :a, :c, :acc, false)"
                ),
                {"d": datetime(day.year, day.month, day.day, 12), "a": amt, "c": cur, "acc": accounts[cur]},
            )
        s.commit()
    finally:
        s.close()


def _usd_rows() -> list[tuple]:
    from backend.db import SessionLocal

    s = SessionLocal()
    try:
        return [tuple(r) for r in s.execute(text(
            "SELECT rate_date, rate FROM fx_rate_cache WHERE rate_date >= '1902-01-01' "
            "AND rate_date < '1904-01-01' AND base_currency = 'USD' AND quote_currency = 'IDR' "
            "ORDER BY rate_date"
        ))]
    finally:
        s.close()


def test_store_range_is_immutable_and_skips_today(range_env):
    from backend import fx
    from backend.db import SessionLocal

    range_env["pin"](date(1902, 1, 7))
    _seed_cache(date(1902, 1, 6), "16000")
    range_env["behaviour"] = lambda: _range_body(
        {"1902-01-03": 16100, "1902-01-06": 17000, "1902-01-07": 17100}
    )
    n = fx._store_range("USD", "IDR", date(1902, 1, 3), date(1902, 1, 7))

    assert n == 1  # only 01-03 is new; 01-06 exists, 01-07 is today
    assert _usd_rows() == [
        (date(1902, 1, 3), Decimal("16100.000000")),
        (date(1902, 1, 6), Decimal("16000.000000")),
    ]
    assert len(range_env["calls"]) == 1

    range_env["calls"].clear()
    assert fx._store_range("U$D", "IDR", date(1902, 1, 3), date(1902, 1, 6)) == 0
    assert range_env["calls"] == []


def _ensure(start, end):
    from backend import fx
    from backend.db import SessionLocal

    s = SessionLocal()
    try:
        return fx.ensure_flow_rates(s, start, end)
    finally:
        s.close()


def test_ensure_flow_rates_covered_makes_no_call(range_env):
    range_env["pin"](date(1903, 4, 1))
    _seed_txs([(date(1903, 3, 20), "-12.50", "USD")])
    _seed_cache(date(1903, 3, 18), "16000")
    assert _ensure(date(1903, 3, 1), date(1903, 3, 31)) == 0
    assert range_env["calls"] == []


def test_ensure_flow_rates_one_call_spans_gaps(range_env):
    from backend.db import SessionLocal

    range_env["pin"](date(1903, 4, 1))
    _seed_txs([(date(1903, 3, 4), "-12.50", "USD"), (date(1903, 3, 12), "-12.50", "USD")])
    range_env["behaviour"] = lambda: _range_body(
        {"1903-02-25": 16000, "1903-03-04": 16050.5, "1903-03-12": 16100}
    )
    n = _ensure(date(1903, 3, 1), date(1903, 3, 31))

    assert n == 3
    assert len(range_env["calls"]) == 1
    assert range_env["calls"][0][0].endswith("/v1/1903-02-25..1903-03-12")
    s = SessionLocal()
    try:
        vals = s.execute(text(
            "SELECT amount_idr FROM transactions_idr WHERE date >= '1903-03-01' AND date < '1903-04-01' "
            "AND currency = 'USD'"
        )).scalars().all()
    finally:
        s.close()
    assert len(vals) == 2 and all(v is not None for v in vals)


def test_ensure_flow_rates_idr_only_makes_no_call(range_env):
    range_env["pin"](date(1903, 4, 1))
    _seed_txs([(date(1903, 3, 10), "-50000", "IDR")])
    assert _ensure(date(1903, 3, 1), date(1903, 3, 31)) == 0
    assert range_env["calls"] == []


def test_ensure_flow_rates_future_gap_raises_without_call(range_env):
    from backend import fx

    range_env["pin"](date(1903, 4, 1))
    _seed_txs([(date(1903, 4, 11), "-12.50", "USD")])
    with pytest.raises(fx.FxUnavailable):
        _ensure(date(1903, 4, 1), date(1903, 4, 30))
    assert range_env["calls"] == []


def test_ensure_flow_rates_vendor_down_raises_after_one_call(range_env):
    from backend import fx

    class _NotFound:
        def raise_for_status(self):
            req = httpx.Request("GET", "https://example.invalid")
            raise httpx.HTTPStatusError("404", request=req, response=httpx.Response(404, request=req))

    range_env["pin"](date(1903, 4, 1))
    _seed_txs([(date(1903, 3, 4), "-12.50", "USD")])
    range_env["behaviour"] = lambda: _NotFound()
    with pytest.raises(fx.FxUnavailable) as exc:
        _ensure(date(1903, 3, 1), date(1903, 3, 31))

    assert len(range_env["calls"]) == 1
    msg = str(exc.value)
    assert "1 USD transaction date(s)" in msg and "1903-03-04" in msg
    assert "12.50" not in msg
