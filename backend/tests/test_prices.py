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
