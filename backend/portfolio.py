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
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

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

    Upserts the `holdings` row keyed on (ticker, platform_id). If the
    resulting quantity is 0 the row is retained as a zero-qty row (D-04:
    "drops off the active list" is a query-time filter, not a delete). Does
    NOT commit — the caller owns the transaction boundary (mirrors writes.py).

    Returns: {ticker, quantity, avg_cost, realized_pnl, dividend_total}.
    """
    events = db.scalars(
        select(PortfolioEvent)
        .where(PortfolioEvent.ticker == ticker, PortfolioEvent.platform_id == platform_id)
        .order_by(PortfolioEvent.date, PortfolioEvent.id)
    ).all()

    qty = Decimal("0")
    total_cost = Decimal("0")  # cost basis of the currently-open quantity
    realized_pnl = Decimal("0")
    dividend_total = Decimal("0")

    for ev in events:
        if ev.event_type == "buy":
            total_cost += ev.price * ev.quantity
            qty += ev.quantity
        elif ev.event_type == "sell":
            avg_cost = (total_cost / qty) if qty > 0 else Decimal("0")
            realized_pnl += (ev.price - avg_cost) * ev.quantity
            # avg_cost UNCHANGED by a sell (D-02): reduce the pool proportionally
            # rather than re-deriving avg_cost from a smaller basis.
            total_cost -= avg_cost * ev.quantity
            qty -= ev.quantity
        elif ev.event_type == "dividend":
            # Dividends fold into realized return (D-02); qty/cost untouched.
            # Convention: quantity=1, price=amount for a lump-sum dividend.
            realized_pnl += ev.price * ev.quantity
            dividend_total += ev.price * ev.quantity

    avg_cost = (total_cost / qty) if qty > 0 else Decimal("0")

    holding = db.query(Holding).filter(
        Holding.ticker == ticker, Holding.platform_id == platform_id
    ).one_or_none()
    if holding is None:
        holding = Holding(
            ticker=ticker, quantity=qty, avg_cost=avg_cost, currency="IDR",
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

    Returns a dict shaped for PortfolioSummary:
      {groups: [{platform_id, platform_name, kind, subtotal, holdings: [...]}],
       total_value, total_unrealized_pnl, total_realized_pnl, as_of}
    """
    holdings = db.query(Holding).order_by(Holding.ticker).all()
    platforms = {p.id: p for p in db.query(Platform).all()}

    # Realized P&L is a ledger byproduct — recompute is read-only here (we do
    # NOT persist; the summary is a pure read composing existing state).
    groups: dict[object, dict] = {}
    total_value = Decimal("0")
    total_unrealized = Decimal("0")
    total_realized = Decimal("0")

    for h in holdings:
        price_row = _latest_price(db, h.ticker)
        current_price = price_row.price if price_row is not None else None
        current_value = (
            current_price * h.quantity if current_price is not None else None
        )
        u_pnl = unrealized_pnl(current_price, h.avg_cost, h.quantity)

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
                "price_source": price_row.source if price_row is not None else None,
                "price_fetched_at": (
                    price_row.fetched_at.isoformat() if price_row is not None else None
                ),
                # Server-computed freshness (INV-05): the frontend renders this
                # flag, never the TTL. A ticker with no price row is stale.
                "is_stale": _price_is_stale(
                    price_row.fetched_at if price_row is not None else None,
                    h.asset_type,
                ),
            }
        )
        if current_value is not None:
            groups[gkey]["subtotal"] += current_value

    # Stable order: real platforms first (by name), unassigned last.
    ordered = sorted(
        groups.values(),
        key=lambda g: (g["platform_id"] is None, (g["platform_name"] or "").lower()),
    )

    return {
        "groups": ordered,
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
