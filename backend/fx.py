"""
FX rate adapter registry + immutable historical-rate cache (FX-01/02/04/05, D-08).

`FX_ADAPTERS` is a `dict[str, Callable]` keyed by provider name — structural
clone of `PRICE_ADAPTERS` in `backend/prices.py`. `fetch_frankfurter_rate`
returns `(Decimal, source)` on success or `None` on ANY failure — the adapter
NEVER raises, so a vendor outage can never 500 the endpoint (mirrors
`fetch_crypto_price`'s contract).

`get_rate()` is the single entry point every valuation caller must use — it
never calls the adapter directly. It is cache-first and INSERT-only: a
`fx_rate_cache` row for a given `(rate_date, base_currency, quote_currency)`
is written at most once and never updated, so historical-at-purchase P&L
(FX-03) stays reproducible even as the vendor's "latest" data moves (FX-05).
On adapter failure + cache miss, `get_rate` returns None — callers must
propagate that as "rate unavailable", never fabricate rate=1.0.

SSRF mitigation (T-07-01-SSRF): `base`/`quote` are validated against
`^[A-Z]{3,4}$` BEFORE any URL is built — a currency string never reaches
the outbound request unless it already looks like a currency code.

All money is Decimal(str(x)) — never float.
"""

import re
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import FxRateCache

# ISO-4217-shaped currency code (3-4 uppercase letters — allows USDT).
_CURRENCY_RE = re.compile(r"^[A-Z]{3,4}$")

# USDT has no frankfurter rate (not a fiat currency) — treated as ≈1:1 USD
# per FX-02. Extend this dict if more stablecoins are added later.
_FX_ALIASES: dict[str, str] = {"USDT": "USD"}


def fetch_frankfurter_rate(base: str, quote: str, as_of: date) -> tuple[Decimal, str] | None:
    """GET https://api.frankfurter.dev/v1/{as_of}?base={base}&symbols={quote}.

    No API key, ECB-sourced. Live-verified (RESEARCH, 2026-07-12):
    /v1/2024-01-15?base=USD&symbols=IDR -> {"rates":{"IDR":15561}}. Returns
    None on ANY failure (HTTP error, missing key, malformed JSON, 404 for
    pre-1999 dates) — never raises. Per orchestrator decision, no
    walk-backward logic is added: frankfurter already returns the nearest
    prior business-day rate for non-trading dates (Pitfall 3).
    """
    import httpx

    try:
        resp = httpx.get(
            f"https://api.frankfurter.dev/v1/{as_of.isoformat()}",
            params={"base": base.upper(), "symbols": quote.upper()},
            timeout=10.0,
        )
        resp.raise_for_status()
        rate = resp.json().get("rates", {}).get(quote.upper())
        if rate is None:
            return None
        return Decimal(str(rate)), "frankfurter"
    except (httpx.HTTPError, KeyError, ValueError, TypeError):
        return None  # caller propagates None — never fabricates a rate


FX_ADAPTERS: dict[str, Callable[[str, str, date], tuple[Decimal, str] | None]] = {
    "frankfurter": fetch_frankfurter_rate,
}


def _latest_cache_row(db: Session, as_of: date, base: str, quote: str) -> FxRateCache | None:
    return db.scalars(
        select(FxRateCache).where(
            FxRateCache.rate_date == as_of,
            FxRateCache.base_currency == base,
            FxRateCache.quote_currency == quote,
        )
    ).first()


def get_rate(base: str, quote: str, as_of: date, db: Session) -> Decimal | None:
    """Cache-first, immutable-write FX lookup (FX-01/02/04/05).

    1. base==quote -> Decimal("1") (identity, no HTTP call).
    2. USDT normalized to USD before lookup (FX-02).
    3. base/quote validated as ^[A-Z]{3,4}$ BEFORE any HTTP call — invalid
       codes return None (SSRF guard, Pitfall 5).
    4. Cache HIT -> stored Decimal, adapter never called (FX-05).
    5. Cache MISS -> adapter called; a non-None result INSERTs exactly one
       immutable row keyed (rate_date, base_currency, quote_currency), then
       returns the Decimal.
    6. Adapter None (vendor outage) -> None, never a fabricated rate=1.0.
    """
    base_norm = _FX_ALIASES.get(base.upper(), base.upper())
    quote_norm = _FX_ALIASES.get(quote.upper(), quote.upper())

    if base_norm == quote_norm:
        return Decimal("1")

    if not (_CURRENCY_RE.match(base_norm) and _CURRENCY_RE.match(quote_norm)):
        return None  # SSRF guard — no HTTP request issued for an invalid code

    existing = _latest_cache_row(db, as_of, base_norm, quote_norm)
    if existing is not None:
        return existing.rate

    adapter = FX_ADAPTERS["frankfurter"]
    result = adapter(base_norm, quote_norm, as_of)
    if result is None:
        return None  # vendor outage/no data — caller's responsibility to propagate

    rate, source = result
    db.add(
        FxRateCache(
            rate_date=as_of,
            base_currency=base_norm,
            quote_currency=quote_norm,
            rate=rate,
            source=source,
            fetched_at=datetime.now(timezone.utc),
        )
    )
    db.flush()  # LOAD-BEARING (CR-02): SessionLocal is autoflush=False, so a
    # same-request repeat lookup for this (rate_date, base, quote) must see this
    # pending row via _latest_cache_row — otherwise it re-inserts the same unique
    # key and the next commit raises IntegrityError (500). Same idiom as writes.py.
    return rate
