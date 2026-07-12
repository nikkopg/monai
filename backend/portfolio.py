"""
Average-cost portfolio accounting from the event ledger (D-01/D-02).

`portfolio_events` is the source of truth for every position (D-01). This
module derives `holdings.quantity` / `holdings.avg_cost` by scanning a
ticker's events in date order, and returns realized P&L + dividend total as a
byproduct. All money math is Decimal — never float — matching the
Numeric(28,8) quantity / Numeric(18,2) money column precision (D-09).

Key invariant (D-02): a SELL realizes `(sell_price − avg_cost) × sold_qty`
and leaves `avg_cost` UNCHANGED. This is expressed by reducing the running
`total_cost` by `avg_cost × sold_qty` (not by re-deriving avg_cost from a
smaller pool — 05-RESEARCH.md Pitfall 4 / Anti-Patterns). Dividends fold into
realized return only; they never touch qty/avg_cost.

Composed reads (portfolio_summary) live here too so the API layer stays a thin
router: it reads holdings + the latest price_cache row per ticker and hands
them to these pure calculators.
"""

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend import fx
from backend.models import (
    Holding,
    Platform,
    PortfolioEvent,
    PortfolioValueHistory,
    PriceCache,
)
from backend.prices import is_stale as _price_is_stale

logger = logging.getLogger(__name__)


def recompute_holding_from_events(db: Session, ticker: str, platform_id: int) -> dict:
    """D-01/D-02: rebuild a position's state from its event ledger.

    Position identity is (ticker, platform_id) (Quick 260711-rb2) — the same
    asset can exist on multiple platforms as independent positions. Scans
    `portfolio_events` for (ticker, platform_id) in (date, id) order, deriving
    running quantity + average cost. Buys add cost+qty; sells realize
    `(price − avg_cost) × qty` and reduce total_cost by `avg_cost × qty`
    (leaving avg_cost unchanged, D-02); dividends fold into realized only.

    FX-03/FX-04: each event's native price×quantity is converted to IDR via
    `fx.get_rate(ev.currency or holding.currency, "IDR", ev.date, db)` at the
    event's OWN trade date BEFORE accumulating into total_cost — cost basis is
    historical-at-purchase, current value (portfolio_summary) uses today's
    rate, so unrealized P&L includes FX drift. If a rate is unavailable
    (vendor outage/gap), this function returns quantity=None/avg_cost=None
    (propagated, never a fabricated rate=1.0) and does NOT upsert the holding
    row for that broken state — caller (apply_add_portfolio_event) still owns
    the transaction boundary.

    Upserts the `holdings` row keyed on (ticker, platform_id). If the
    resulting quantity is 0 the row is retained as a zero-qty row (D-04:
    "drops off the active list" is a query-time filter, not a delete). Does
    NOT commit — the caller owns the transaction boundary (mirrors writes.py).

    Returns: {ticker, quantity, avg_cost, realized_pnl, dividend_total}, all
    None if an FX rate could not be resolved for one of the ledger's events.
    """
    events = db.scalars(
        select(PortfolioEvent)
        .where(PortfolioEvent.ticker == ticker, PortfolioEvent.platform_id == platform_id)
        .order_by(PortfolioEvent.date, PortfolioEvent.id)
    ).all()

    holding = db.query(Holding).filter(
        Holding.ticker == ticker, Holding.platform_id == platform_id
    ).one_or_none()
    # Fallback currency for events that omit one (schema default is IDR, but
    # an existing holding's currency is the authoritative fallback).
    default_currency = holding.currency if holding is not None else "IDR"

    qty = Decimal("0")
    total_cost = Decimal("0")  # cost basis of the currently-open quantity, IDR
    realized_pnl = Decimal("0")
    dividend_total = Decimal("0")

    for ev in events:
        ev_currency = ev.currency or default_currency
        rate = fx.get_rate(ev_currency, "IDR", ev.date, db)
        if rate is None:
            # Vendor outage/gap — propagate None, never fabricate rate=1.0.
            return {
                "ticker": ticker,
                "quantity": None,
                "avg_cost": None,
                "realized_pnl": None,
                "dividend_total": None,
            }
        native_amount = ev.price * ev.quantity
        idr_amount = native_amount * rate

        if ev.event_type == "buy":
            total_cost += idr_amount
            qty += ev.quantity
        elif ev.event_type == "sell":
            avg_cost = (total_cost / qty) if qty > 0 else Decimal("0")
            realized_pnl += (ev.price * rate - avg_cost) * ev.quantity
            # avg_cost UNCHANGED by a sell (D-02): reduce the pool proportionally
            # rather than re-deriving avg_cost from a smaller basis.
            total_cost -= avg_cost * ev.quantity
            qty -= ev.quantity
        elif ev.event_type == "dividend":
            # Dividends fold into realized return (D-02); qty/cost untouched.
            # Convention: quantity=1, price=amount for a lump-sum dividend.
            realized_pnl += idr_amount
            dividend_total += idr_amount

    avg_cost = (total_cost / qty) if qty > 0 else Decimal("0")

    if holding is None:
        holding = Holding(
            ticker=ticker, quantity=qty, avg_cost=avg_cost, currency=default_currency,
            platform_id=platform_id,
        )
        db.add(holding)
    else:
        holding.quantity = qty
        holding.avg_cost = avg_cost

    return {
        "ticker": ticker,
        "quantity": qty,
        "avg_cost": avg_cost,
        "realized_pnl": realized_pnl,
        "dividend_total": dividend_total,
    }


def unrealized_pnl(
    current_price: Decimal | None, avg_cost: Decimal, qty: Decimal
) -> Decimal | None:
    """(current_price − avg_cost) × qty, all Decimal.

    Returns None when there is no current price (no price_cache row yet) — the
    holding's unrealized P&L is genuinely unknown until Plan 04 backfills live
    prices; callers surface it as null, not zero.
    """
    if current_price is None:
        return None
    return (current_price - avg_cost) * qty


def _latest_price(db: Session, ticker: str) -> PriceCache | None:
    """Most-recent price_cache row for a ticker (by fetched_at, id), or None.

    All prices (fetched or manual) flow through price_cache, so this is the one
    read path for "current price". Plan 04 populates fresh rows; this slice
    reads whatever is already there (or None -> "no price yet").
    """
    return db.scalars(
        select(PriceCache)
        .where(PriceCache.ticker == ticker)
        .order_by(PriceCache.fetched_at.desc(), PriceCache.id.desc())
        .limit(1)
    ).first()


def portfolio_summary(db: Session) -> dict:
    """Compose the GET /investments/summary payload (D-05, INV-06).

    Reads every holding, joins the latest price_cache price per ticker (price
    is platform-independent), and groups holdings by platform (Quick
    260711-rb2: platform_id is required — one group per real platform, no
    more "unassigned" bucket). Per-holding fields: current_price (nullable),
    current_value (nullable), unrealized_pnl (nullable), realized_pnl (from
    the event ledger, scoped to THIS holding's (ticker, platform_id) position
    — the same ticker on two platforms must not double-count each other's
    realized P&L). Totals sum the non-null contributions; total_value /
    total_unrealized are null-safe. Zero-qty holdings are still returned
    (D-04 filtering is a UI concern).

    CG-01: asset_type=='cash' is special-cased BEFORE the price_cache read —
    value = quantity × fx.get_rate(currency, "IDR", today, db), no
    price_cache row involved at all. Its per-row current_price/current_value
    come from that FX amount (never None while a rate resolves), is_stale is
    hardcoded False, price_source is "fx" — NOT the generic
    _price_is_stale(None, 'cash')=True path, which would show a permanent
    false "stale" badge (INV-05). Gold (CG-02) takes no branch — it flows
    through the normal price_cache path exactly like crypto/stocks.

    Returns a dict shaped for PortfolioSummary:
      {groups: [{platform_id, platform_name, kind, subtotal, holdings: [...]}],
       asset_type_groups: [{asset_type, total_value}],
       total_value, total_unrealized_pnl, total_realized_pnl, as_of}
    """
    holdings = db.query(Holding).order_by(Holding.ticker).all()
    platforms = {p.id: p for p in db.query(Platform).all()}
    today = date.today()

    # Realized P&L is a ledger byproduct — recompute is read-only here (we do
    # NOT persist; the summary is a pure read composing existing state).
    groups: dict[object, dict] = {}
    asset_type_totals: dict[str | None, Decimal] = {}
    total_value = Decimal("0")
    total_unrealized = Decimal("0")
    total_realized = Decimal("0")

    for h in holdings:
        if h.asset_type == "cash":
            # CG-01: cash values as amount × today's FX rate — no price_cache
            # read at all (Open Question 2, LOCKED).
            rate = fx.get_rate(h.currency, "IDR", today, db)
            current_price = rate  # "price" of 1 unit of cash in IDR
            current_value = h.quantity * rate if rate is not None else None
            u_pnl = unrealized_pnl(current_price, h.avg_cost, h.quantity)
            price_source = "fx"
            price_fetched_at = datetime.now(timezone.utc).isoformat()
            # INV-05: cash is fresh whenever a rate resolved — never the
            # false "stale" badge from _price_is_stale(None, 'cash').
            is_stale = rate is None
        else:
            price_row = _latest_price(db, h.ticker)
            current_price = price_row.price if price_row is not None else None
            current_value = (
                current_price * h.quantity if current_price is not None else None
            )
            u_pnl = unrealized_pnl(current_price, h.avg_cost, h.quantity)
            price_source = price_row.source if price_row is not None else None
            price_fetched_at = (
                price_row.fetched_at.isoformat() if price_row is not None else None
            )
            is_stale = _price_is_stale(
                price_row.fetched_at if price_row is not None else None,
                h.asset_type,
            )

        # Realized P&L + dividend total from THIS position's event ledger
        # (source of truth) — scoped to (ticker, platform_id), never the bare
        # ticker, or two platforms' realized P&L would double-count.
        realized = _realized_for_position(db, h.ticker, h.platform_id)

        if current_value is not None:
            total_value += current_value
        if u_pnl is not None:
            total_unrealized += u_pnl
        total_realized += realized["realized_pnl"]

        gkey = h.platform_id
        if gkey not in groups:
            plat = platforms.get(h.platform_id)
            groups[gkey] = {
                "platform_id": h.platform_id,
                "platform_name": plat.name if plat is not None else "Unassigned",
                "kind": plat.kind if plat is not None else None,
                "subtotal": Decimal("0"),
                "holdings": [],
            }
        groups[gkey]["holdings"].append(
            {
                "id": h.id,
                "ticker": h.ticker,
                "asset_type": h.asset_type,
                "coingecko_id": h.coingecko_id,
                "quantity": h.quantity,
                "avg_cost": h.avg_cost,
                "current_price": current_price,
                "current_value": current_value,
                "unrealized_pnl": u_pnl,
                "realized_pnl": realized["realized_pnl"],
                "price_source": price_source,
                "price_fetched_at": price_fetched_at,
                # Server-computed freshness (INV-05): the frontend renders this
                # flag, never the TTL. A ticker with no price row is stale.
                "is_stale": is_stale,
            }
        )
        if current_value is not None:
            groups[gkey]["subtotal"] += current_value
            # VZ-01 pie data contract: aggregate current IDR value by asset_type.
            atkey = h.asset_type
            asset_type_totals[atkey] = asset_type_totals.get(atkey, Decimal("0")) + current_value

    # Stable order: real platforms first (by name), unassigned last.
    ordered = sorted(
        groups.values(),
        key=lambda g: (g["platform_id"] is None, (g["platform_name"] or "").lower()),
    )
    asset_type_groups = [
        {"asset_type": atype, "total_value": val}
        for atype, val in sorted(asset_type_totals.items(), key=lambda kv: (kv[0] is None, kv[0] or ""))
    ]

    return {
        "groups": ordered,
        "asset_type_groups": asset_type_groups,
        "total_value": total_value,
        "total_unrealized_pnl": total_unrealized,
        "total_realized_pnl": total_realized,
        "as_of": datetime.now(timezone.utc).isoformat(),
    }


def snapshot_all_holdings(db: Session) -> dict:
    """D-13: write one portfolio_value_history row per holding for today.

    For each holding, read its current price from price_cache, then record
    market_value = price × quantity and cost_basis = avg_cost × quantity (all
    Decimal). Rows are keyed on the unique (snapshot_date, ticker, platform_id)
    index: a same-day row for that position already existing is skipped, so
    re-running the job is idempotent (upsert-or-skip) AND a ticker held on two
    platforms records BOTH. Holdings without a current price are skipped
    (market_value is unknown until a price row exists — D-13 tolerates gaps).

    CG-01: asset_type=='cash' is special-cased BEFORE the "no price_cache row
    -> skip" gate — cash never has a price_cache row, so without this branch
    it would be skipped forever and never appear in Plan 04's VZ-02 history
    series. market_value = quantity × fx.get_rate(currency, "IDR", today, db);
    cost_basis mirrors the same CG-01 semantics (cash has no cost-basis P&L
    except FX movement, so cost_basis uses the holding's own avg_cost × qty,
    consistent with every other asset type's cost_basis formula here). If the
    FX rate is unavailable, the row is skipped (not written with a fabricated
    rate=1.0) — counted the same as any other skip.

    Per-holding work is wrapped in try/except so one ticker's failure never
    aborts the whole snapshot or the scheduler thread (T-05-06-DEG). Does NOT
    commit — the caller (the daily job) owns the transaction boundary.

    Returns {written, skipped, failed} counts.
    """
    today = date.today()
    written = skipped = failed = 0
    for h in db.query(Holding).all():
        try:
            exists = db.scalars(
                select(PortfolioValueHistory).where(
                    PortfolioValueHistory.snapshot_date == today,
                    PortfolioValueHistory.ticker == h.ticker,
                    PortfolioValueHistory.platform_id == h.platform_id,
                )
            ).first()
            if exists is not None:
                skipped += 1
                continue

            if h.asset_type == "cash":
                # CG-01: cash never has a price_cache row — special-case it
                # BEFORE the price_row None-skip gate below, or it would be
                # skipped forever (Plan 04's VZ-02 series would permanently
                # omit cash, a first-class position).
                rate = fx.get_rate(h.currency, "IDR", today, db)
                if rate is None:
                    skipped += 1
                    continue
                db.add(
                    PortfolioValueHistory(
                        snapshot_date=today,
                        ticker=h.ticker,
                        quantity=h.quantity,
                        market_value=h.quantity * rate,
                        cost_basis=h.avg_cost * h.quantity,
                        currency="IDR",
                        platform_id=h.platform_id,
                    )
                )
                written += 1
                continue

            price_row = _latest_price(db, h.ticker)
            if price_row is None:
                skipped += 1
                continue

            db.add(
                PortfolioValueHistory(
                    snapshot_date=today,
                    ticker=h.ticker,
                    quantity=h.quantity,
                    market_value=price_row.price * h.quantity,
                    cost_basis=h.avg_cost * h.quantity,
                    currency="IDR",
                    platform_id=h.platform_id,
                )
            )
            written += 1
        except Exception:
            # One ticker's failure must not abort the snapshot (T-05-06-DEG).
            logger.warning("snapshot failed for ticker %s", h.ticker, exc_info=True)
            failed += 1
    return {"written": written, "skipped": skipped, "failed": failed}


_HISTORY_RANGES = {"1M": 30, "3M": 90, "6M": 180, "All": None}


def value_history_series(db: Session, range_param: str = "All") -> list[dict]:
    """Compose the GET /investments/history payload (VZ-02, INVX-01).

    Pure read over the already-populated portfolio_value_history (D-13/D-14) —
    makes NO fx.get_rate call, so this can run in Wave 1 independent of the FX
    plans; series CONTENTS (whether cash appears) depend on Plan 02's
    snapshot_all_holdings cash special-case having written cash rows, not on
    anything at read time. Groups every row (including cash) by snapshot_date:
    total_market_value = Σ market_value, total_pnl = Σ(market_value −
    cost_basis), both Decimal. range_param trims by snapshot_date using
    _HISTORY_RANGES; an unrecognized token raises ValueError (422 at the API
    layer). No rows (collector just went live) returns an empty list — no
    backfill (D-13), not an error.
    """
    if range_param not in _HISTORY_RANGES:
        raise ValueError(f"unknown range: {range_param!r}")

    rows = db.scalars(
        select(PortfolioValueHistory).order_by(PortfolioValueHistory.snapshot_date)
    ).all()

    days = _HISTORY_RANGES[range_param]
    if days is not None:
        cutoff = date.today() - timedelta(days=days)
        rows = [r for r in rows if r.snapshot_date >= cutoff]

    by_date: dict[date, dict] = {}
    for r in rows:
        bucket = by_date.setdefault(
            r.snapshot_date,
            {"date": r.snapshot_date, "total_market_value": Decimal("0"), "total_pnl": Decimal("0")},
        )
        bucket["total_market_value"] += r.market_value
        bucket["total_pnl"] += r.market_value - r.cost_basis

    return [by_date[d] for d in sorted(by_date)]


def _realized_for_position(db: Session, ticker: str, platform_id: int) -> dict:
    """Realized P&L + dividend total for a (ticker, platform_id) position
    WITHOUT mutating the holding.

    Mirrors recompute's ledger scan but is read-only (the summary must not
    write). Kept private — the public recompute is the write path. Scoped to
    the position's platform_id (Quick 260711-rb2) so the same ticker on two
    platforms never double-counts each other's realized P&L.
    """
    events = db.scalars(
        select(PortfolioEvent)
        .where(PortfolioEvent.ticker == ticker, PortfolioEvent.platform_id == platform_id)
        .order_by(PortfolioEvent.date, PortfolioEvent.id)
    ).all()

    qty = Decimal("0")
    total_cost = Decimal("0")
    realized_pnl = Decimal("0")
    dividend_total = Decimal("0")

    for ev in events:
        if ev.event_type == "buy":
            total_cost += ev.price * ev.quantity
            qty += ev.quantity
        elif ev.event_type == "sell":
            avg_cost = (total_cost / qty) if qty > 0 else Decimal("0")
            realized_pnl += (ev.price - avg_cost) * ev.quantity
            total_cost -= avg_cost * ev.quantity
            qty -= ev.quantity
        elif ev.event_type == "dividend":
            realized_pnl += ev.price * ev.quantity
            dividend_total += ev.price * ev.quantity

    return {"realized_pnl": realized_pnl, "dividend_total": dividend_total}
