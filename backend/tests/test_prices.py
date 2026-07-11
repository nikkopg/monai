"""
Price-adapter tests (Plan 04 — filled from the Wave-0 RED scaffold).

Adapters NEVER raise: on any HTTP/parse error they return None so the caller
falls back to the last price_cache row (INV-02/03, Pitfall 2). `is_stale`
respects the per-asset-type TTL (INV-05). All mocked — no live network.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest


def test_fetch_crypto_price(monkeypatch):
    """Known coin-id → (Decimal, 'coingecko'); unknown ticker → None; HTTPError → None."""
    from backend import prices

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"bitcoin": {"idr": 1_500_000_000}}

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Resp())
    result = prices.fetch_crypto_price("BTC")
    assert result == (Decimal("1500000000"), "coingecko")
    assert isinstance(result[0], Decimal)

    # Unknown ticker never hits the network — resolves to None via the fixed map.
    assert prices.fetch_crypto_price("NOTACOIN") is None

    # HTTPError is swallowed — adapter returns None, never raises.
    def _boom(*a, **k):
        raise httpx.HTTPError("boom")

    monkeypatch.setattr(httpx, "get", _boom)
    assert prices.fetch_crypto_price("BTC") is None


def test_fetch_crypto_price_explicit_coin_id(monkeypatch):
    """Explicit coin_id overrides the symbol map — works for unknown tickers too."""
    from backend import prices

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"bittensor": {"idr": 4_200_000_000}}

    captured = {}

    def _get(url, params, timeout):
        captured.update(params)
        return _Resp()

    monkeypatch.setattr(httpx, "get", _get)
    result = prices.fetch_crypto_price("TAO", coin_id="bittensor")
    assert result == (Decimal("4200000000"), "coingecko")
    assert captured["ids"] == "bittensor"


def test_fetch_crypto_price_no_coin_id_falls_back_to_map(monkeypatch):
    """coin_id=None, known ticker -> falls back to TICKER_TO_COINGECKO_ID (regression guard)."""
    from backend import prices

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"bitcoin": {"idr": 1_500_000_000}}

    captured = {}

    def _get(url, params, timeout):
        captured.update(params)
        return _Resp()

    monkeypatch.setattr(httpx, "get", _get)
    result = prices.fetch_crypto_price("BTC", coin_id=None)
    assert result == (Decimal("1500000000"), "coingecko")
    assert captured["ids"] == "bitcoin"


def test_fetch_crypto_price_unknown_ticker_no_coin_id_is_none(monkeypatch):
    """No coin_id + unknown ticker -> None, no outbound call (no fabrication)."""
    from backend import prices

    def _boom(*a, **k):
        raise AssertionError("must not call the network with no resolved coin id")

    monkeypatch.setattr(httpx, "get", _boom)
    assert prices.fetch_crypto_price("NOTACOIN", coin_id=None) is None
    assert prices.fetch_crypto_price("NOTACOIN", coin_id="") is None


def test_fetch_idx_price_fallback(monkeypatch):
    """yfinance raising → None (fallback contract, INV-03) — never raises."""
    import yfinance as yf

    from backend import prices

    def _boom(*a, **k):
        raise RuntimeError("yahoo down")

    monkeypatch.setattr(yf, "Ticker", _boom)
    assert prices.fetch_idx_price("BBCA") is None

    # Non-alphanumeric ticker short-circuits to None before any outbound call.
    assert prices.fetch_idx_price("../evil") is None


def test_fetch_idx_price_success(monkeypatch):
    """fast_info['lastPrice'] → (Decimal, 'yfinance')."""
    import yfinance as yf

    from backend import prices

    class _Ticker:
        def __init__(self, symbol):
            assert symbol == "BBCA.JK"
            self.fast_info = {"lastPrice": 6175.0}

    monkeypatch.setattr(yf, "Ticker", _Ticker)
    assert prices.fetch_idx_price("BBCA") == (Decimal("6175.0"), "yfinance")


def test_fetch_manual_price_is_none():
    from backend import prices

    assert prices.fetch_manual_price("ANYTHING") is None


def test_override_requires_api_key(client, api_key):
    """POST /prices/override without the header → 401 (T-05-04-AC).

    The api_key fixture configures a non-empty server key (so auth is enforced);
    the request deliberately omits the MONAI_API_KEY header.
    """
    resp = client.post("/prices/override", json={"ticker": "BTC", "price": 100})
    assert resp.status_code == 401


def test_override_rejects_nonpositive_price(client, api_key):
    """Negative/zero price → 422 at the schema boundary (V5, T-05-04-INP)."""
    headers = {"MONAI_API_KEY": api_key}
    assert client.post("/prices/override", json={"ticker": "BTC", "price": -5}, headers=headers).status_code == 422
    assert client.post("/prices/override", json={"ticker": "BTC", "price": 0}, headers=headers).status_code == 422


def test_refresh_tolerates_failing_ticker(client, api_key, monkeypatch):
    """POST /prices/refresh does not 500 when a ticker fetch fails (Pitfall 2).

    refresh_all_prices already swallows per-ticker failures (adapters return
    None); here we assert the endpoint returns 200 with count fields even when
    every fetch 'fails'.
    """
    import backend.main as main_mod

    def _all_fail(db, *, force=False):
        return {"refreshed": 0, "skipped": 0, "failed": 3}

    # Patch the name the route imports lazily from backend.prices.
    import backend.prices as prices_mod
    monkeypatch.setattr(prices_mod, "refresh_all_prices", _all_fail)

    resp = client.post("/prices/refresh", headers={"MONAI_API_KEY": api_key})
    assert resp.status_code == 200
    assert resp.json()["failed"] == 3


def test_refresh_requires_api_key(client, api_key):
    """POST /prices/refresh without the header → 401 (T-05-04-AC)."""
    assert client.post("/prices/refresh").status_code == 401


def test_is_stale_respects_ttl():
    """Fresh within TTL → False; past TTL → True; missing → True (INV-05)."""
    from backend import prices

    now = datetime.now(timezone.utc)
    # crypto TTL is 5 min
    assert prices.is_stale(now - timedelta(minutes=2), "crypto") is False
    assert prices.is_stale(now - timedelta(minutes=10), "crypto") is True
    # idx_stock TTL is 1 day
    assert prices.is_stale(now - timedelta(hours=2), "idx_stock") is False
    assert prices.is_stale(now - timedelta(days=2), "idx_stock") is True
    # missing timestamp is always stale
    assert prices.is_stale(None, "crypto") is True
    # naive timestamp treated as UTC (no crash)
    assert prices.is_stale(now.replace(tzinfo=None) - timedelta(minutes=10), "crypto") is True
