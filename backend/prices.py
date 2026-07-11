"""
Pluggable price-adapter registry + staleness + batch refresh (D-08/D-09/D-10/D-11).

`PRICE_ADAPTERS` is a `dict[str, Callable]` keyed by `asset_type` (mirrors the
`TOOLS` registry in backend/tools.py). Each adapter returns `(Decimal, source)`
on success or `None` on ANY failure — adapters NEVER raise, so one slow/failing
external source can never 500 the endpoint or abort a refresh batch (Pitfall 2,
T-05-04-DEG). On None the caller keeps the last price_cache row and marks it
stale downstream.

SSRF mitigation (T-05-04-SSRF): crypto tickers resolve ONLY via the fixed
module-level `TICKER_TO_COINGECKO_ID` map (unknown → None); a free-text ticker
is never interpolated into the CoinGecko URL. IDX tickers are validated as
alphanumeric before `yfinance.Ticker(f"{ticker}.JK")`.

All money is Decimal(str(x)) — never float.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import Holding, PriceCache

# Fixed server-side ticker → CoinGecko coin-id map (SSRF mitigation, Pitfall 1/2):
# CoinGecko ids are opaque slugs (symbols collide across ~10.6k symbols), so we
# never resolve at runtime and never pass a user ticker into the URL. Extend this
# map to support more coins.
TICKER_TO_COINGECKO_ID: dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "USDT": "tether",
    "USDC": "usd-coin",
    "BNB": "binancecoin",
    "XRP": "ripple",
    "ADA": "cardano",
    "DOGE": "dogecoin",
    "MATIC": "matic-network",
}

# Per-asset-type freshness TTLs (D-10, Claude's discretion): crypto trades 24/7 so
# it goes stale fast; IDX quotes are daily; manual/mutual-fund prices rarely change.
TTL_BY_ASSET_TYPE: dict[str, timedelta] = {
    "crypto": timedelta(minutes=5),
    "idx_stock": timedelta(days=1),
    "mutual_fund": timedelta(days=7),
    "other": timedelta(days=7),
}
_DEFAULT_TTL = timedelta(days=7)


def fetch_crypto_price(ticker: str, coin_id: str | None = None) -> tuple[Decimal, str] | None:
    """CoinGecko /simple/price in native IDR (D-07 — no FX conversion).

    `coin_id`, when provided (Tier 1 per-holding override), is used verbatim
    as the CoinGecko coin-id — disambiguates tickers that map to multiple
    CoinGecko coins (e.g. TAO). Otherwise `ticker` is resolved via the fixed
    TICKER_TO_COINGECKO_ID map; an unresolved ticker returns None (never an
    outbound request with a user-controlled id — SSRF, Pitfall 1; no
    fabrication). Returns (Decimal, "coingecko") or None on any HTTP/parse
    error — never raises.
    """
    import httpx

    resolved = coin_id if coin_id else TICKER_TO_COINGECKO_ID.get(ticker.upper())
    if resolved is None:
        return None
    try:
        resp = httpx.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": resolved, "vs_currencies": "idr"},
            timeout=10.0,
        )
        resp.raise_for_status()
        price = resp.json().get(resolved, {}).get("idr")
        if price is None:
            return None
        return Decimal(str(price)), "coingecko"
    except (httpx.HTTPError, KeyError, ValueError):
        return None  # caller falls back to the latest price_cache row


def fetch_idx_price(ticker: str) -> tuple[Decimal, str] | None:
    """yfinance `.JK` suffix — native IDR IDX quote (delayed ~15-20 min).

    Verified live against yfinance 1.5.1 (Task 0, 2026-07-11): the correct
    current-price key is `fast_info["lastPrice"]` (camelCase). `last_price`
    (snake_case) returns None on 1.5.1. `BBCA.JK` → 6175.0.

    Ticker is validated alphanumeric before use (no arbitrary outbound URL is
    user-constructible — T-05-04-SSRF). Best-effort: any exception or empty
    result returns None so the caller falls back to price_cache (INV-03).
    """
    if not ticker.isalnum():
        return None
    import yfinance as yf

    try:
        price = yf.Ticker(f"{ticker}.JK").fast_info.get("lastPrice")
        if price is None:
            return None
        return Decimal(str(price)), "yfinance"
    except Exception:
        return None


def fetch_manual_price(ticker: str) -> tuple[Decimal, str] | None:
    """No live source for mutual_fund/other — always None so the caller's
    fallback (read the last manually-set price_cache row) is the only path."""
    return None


PRICE_ADAPTERS: dict[str, Callable[[str], tuple[Decimal, str] | None]] = {
    "crypto": fetch_crypto_price,
    "idx_stock": fetch_idx_price,
    "mutual_fund": fetch_manual_price,
    "other": fetch_manual_price,
}


def is_stale(fetched_at: datetime | None, asset_type: str | None) -> bool:
    """True once `fetched_at` is older than the asset-type TTL (INV-05).

    A missing timestamp is always stale. Server-computed — the frontend renders
    this flag, never the TTL itself. Naive timestamps are treated as UTC.
    """
    if fetched_at is None:
        return True
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    ttl = TTL_BY_ASSET_TYPE.get(asset_type or "", _DEFAULT_TTL)
    return datetime.now(timezone.utc) - fetched_at > ttl


def _latest_price_row(db: Session, ticker: str) -> PriceCache | None:
    return db.scalars(
        select(PriceCache)
        .where(PriceCache.ticker == ticker)
        .order_by(PriceCache.fetched_at.desc(), PriceCache.id.desc())
        .limit(1)
    ).first()


def refresh_all_prices(db: Session, *, force: bool = False) -> dict:
    """Route each holding to its adapter and cache fresh prices (D-08/D-09).

    For every holding: if `force` or its cached price is missing/stale, call the
    asset_type-routed adapter. On a non-None result, insert a new price_cache row
    (source from the adapter). On None, leave the last row (marked stale
    downstream). Per-ticker try/except means one failing/slow source never aborts
    the batch (T-05-04-DEG). Does NOT commit — caller owns the transaction.

    Returns {refreshed, skipped, failed} counts.
    """
    refreshed = skipped = failed = 0
    for h in db.query(Holding).all():
        adapter = PRICE_ADAPTERS.get(h.asset_type or "other", fetch_manual_price)
        if not force:
            row = _latest_price_row(db, h.ticker)
            if row is not None and not is_stale(row.fetched_at, h.asset_type):
                skipped += 1
                continue
        try:
            if adapter is fetch_crypto_price:
                result = fetch_crypto_price(h.ticker, h.coingecko_id)
            else:
                result = adapter(h.ticker)
        except Exception:
            # Defensive: adapters are contracted never to raise, but a bad
            # adapter must still not abort the batch.
            result = None
        if result is None:
            failed += 1
            continue
        price, source = result
        db.add(
            PriceCache(
                ticker=h.ticker,
                price=Decimal(str(price)),
                currency="IDR",
                source=source,
                fetched_at=datetime.now(timezone.utc),
            )
        )
        refreshed += 1
    return {"refreshed": refreshed, "skipped": skipped, "failed": failed}
