"""
FX rate adapter registry + immutable historical-rate cache (FX-01/02/04/05, D-08).

`FX_ADAPTERS` is a `dict[str, Callable]` keyed by provider name — structural
clone of `PRICE_ADAPTERS` in `backend/prices.py`. `fetch_frankfurter_rate`
returns `(Decimal, source, effective_date)` on success or `None` on ANY failure
(`effective_date` is the ECB business date Frankfurter used, or None when the
body carries no date) — the adapter
NEVER raises, so a vendor outage can never 500 the endpoint (mirrors
`fetch_crypto_price`'s contract).

`get_rate()` is the single entry point every valuation caller must use — it
never calls the adapter directly. It is cache-first and INSERT-only for PAST
dates: a `fx_rate_cache` row for a given `(rate_date, base_currency,
quote_currency)` is written at most once and never updated, so
historical-at-purchase P&L (FX-03) stays reproducible even as the vendor's
"latest" data moves (FX-05). The row stores the requested date as `rate_date`
and the business date Frankfurter actually used as `rate_effective_date`
(a Saturday request is keyed Saturday, effective Friday).

"Today" is the Asia/Jakarta date computed here (`_jakarta_today`), never the
caller's or the process's. A date on or after today is fetched live and is
NEVER read from or written to `fx_rate_cache`: a rate fetched before the ECB
publishes would otherwise freeze under today's date.
On a cache miss, the INSERT runs on its own short-lived `SessionLocal()`
session that commits immediately (WRITE-03) — a fetched rate survives even
when the caller's own session never commits. The caller's session is only
ever read; a concurrent insert of the same key resolves to the existing row.
On adapter failure + cache miss, `get_rate` returns None — callers must
propagate that as "rate unavailable", never fabricate rate=1.0.

SSRF mitigation (T-07-01-SSRF): `base`/`quote` are validated against
`^[A-Z]{3,4}$` BEFORE any URL is built — a currency string never reaches
the outbound request unless it already looks like a currency code.

All money is Decimal(str(x)) — never float.
"""

import re
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from decimal import Decimal
from typing import Callable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.db import SessionLocal
from backend.models import FxRateCache

# ISO-4217-shaped currency code (3-4 uppercase letters — allows USDT).
_CURRENCY_RE = re.compile(r"^[A-Z]{3,4}$")

# USDT has no frankfurter rate (not a fiat currency) — treated as ≈1:1 USD
# per FX-02. Extend this dict if more stablecoins are added later.
_FX_ALIASES: dict[str, str] = {"USDT": "USD"}

_JAKARTA = ZoneInfo("Asia/Jakarta")


def _jakarta_today() -> date:
    """Today in Asia/Jakarta, independent of the process timezone."""
    return datetime.now(_JAKARTA).date()


def fetch_frankfurter_rate(
    base: str, quote: str, as_of: date
) -> tuple[Decimal, str, date | None] | None:
    """GET https://api.frankfurter.dev/v1/{as_of}?base={base}&symbols={quote}.

    No API key, ECB-sourced. Live-verified (RESEARCH, 2026-07-12):
    /v1/2024-01-15?base=USD&symbols=IDR -> {"date":"2024-01-15","rates":{"IDR":15561}}.
    Returns (rate, "frankfurter", effective_date) where effective_date is the
    body's "date" (the ECB business date used; a weekend request reports the
    prior Friday), or None when the body has no date. Returns None on ANY
    failure (HTTP error, missing key, malformed JSON or date, 404 for
    pre-1999 dates) — never raises. No walk-backward logic: frankfurter
    already returns the nearest prior business-day rate (Pitfall 3).
    """
    import httpx

    try:
        resp = httpx.get(
            f"https://api.frankfurter.dev/v1/{as_of.isoformat()}",
            params={"base": base.upper(), "symbols": quote.upper()},
            timeout=10.0,
        )
        resp.raise_for_status()
        body = resp.json()
        rate = body.get("rates", {}).get(quote.upper())
        if rate is None:
            return None
        eff = body.get("date")
        return (
            Decimal(str(rate)),
            "frankfurter",
            date.fromisoformat(eff) if eff else None,
        )
    except (httpx.HTTPError, KeyError, ValueError, TypeError):
        return None  # caller propagates None — never fabricates a rate


FX_ADAPTERS: dict[str, Callable[[str, str, date], tuple[Decimal, str, date | None] | None]] = {
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


def _lookup(base: str, quote: str, as_of: date, db: Session) -> tuple[Decimal, date | None] | None:
    """Rate plus the business date it belongs to, or None when unavailable.

    1. base==quote -> (Decimal("1"), as_of) (identity, no HTTP call).
    2. USDT normalized to USD before lookup (FX-02).
    3. base/quote validated as ^[A-Z]{3,4}$ BEFORE any HTTP call — invalid
       codes return None (SSRF guard, Pitfall 5).
    4. as_of on or after Jakarta today -> adapter only; the cache is neither
       read nor written (D-17), so a pre-publish rate never freezes.
    5. Past date, cache HIT -> stored Decimal, adapter never called (FX-05).
    6. Past date, cache MISS -> adapter called; a non-None result INSERTs
       exactly one immutable row keyed (rate_date, base_currency,
       quote_currency) with rate_effective_date, committed on its own
       dedicated session (WRITE-03). If another writer already inserted the
       same key, that row's rate is returned instead (FX-05).
    7. Adapter None (vendor outage) -> None, never a fabricated rate=1.0.
    """
    base_norm = _FX_ALIASES.get(base.upper(), base.upper())
    quote_norm = _FX_ALIASES.get(quote.upper(), quote.upper())

    if base_norm == quote_norm:
        return Decimal("1"), as_of

    if not (_CURRENCY_RE.match(base_norm) and _CURRENCY_RE.match(quote_norm)):
        return None  # SSRF guard — no HTTP request issued for an invalid code

    if isinstance(as_of, datetime):
        as_of = as_of.date()
    adapter = FX_ADAPTERS["frankfurter"]

    if as_of >= _jakarta_today():
        result = adapter(base_norm, quote_norm, as_of)
        return None if result is None else (result[0], result[2])

    existing = _latest_cache_row(db, as_of, base_norm, quote_norm)
    if existing is not None:
        return existing.rate, existing.rate_effective_date or existing.rate_date

    result = adapter(base_norm, quote_norm, as_of)
    if result is None:
        return None  # vendor outage/no data — caller's responsibility to propagate

    rate, source, effective = result
    with SessionLocal() as cache_session:
        cache_session.add(
            FxRateCache(
                rate_date=as_of,
                base_currency=base_norm,
                quote_currency=quote_norm,
                rate=rate,
                rate_effective_date=effective,
                source=source,
                fetched_at=datetime.now(timezone.utc),
            )
        )
        try:
            cache_session.commit()
        except IntegrityError:
            cache_session.rollback()
            existing2 = _latest_cache_row(cache_session, as_of, base_norm, quote_norm)
            if existing2 is not None:
                # a concurrent writer won; rows are immutable (FX-05)
                return existing2.rate, existing2.rate_effective_date or existing2.rate_date
            raise  # unexpected: insert failed but no row exists — surface it
    return rate, effective or as_of


def get_rate(base: str, quote: str, as_of: date, db: Session) -> Decimal | None:
    """Cache-first, immutable-write FX lookup (FX-01/02/04/05); see `_lookup`."""
    found = _lookup(base, quote, as_of, db)
    return None if found is None else found[0]
