"""Hand-run: convert one platform's open IDR positions to USD (quick 261108-bkz).

    python -m backend.convert_platform_to_usd --platform-id N            # dry run, changes nothing
    python -m backend.convert_platform_to_usd --platform-id N --apply    # convert, in one transaction

The owner runs this by hand, one platform per run. Nothing at boot, in the scheduler or in a
migration imports or runs it, and importing it does nothing. It uses DATABASE_URL, whose
default is the LIVE database, so the first line it prints is the database name: check it.

Each eligible position (open, IDR, not cash, with events, all events IDR and dated before
today, every trade-date rate known, stored row equal to its ledger) has every event's price
divided by that event's own date USD->IDR rate (the same `fx.get_rate` the app multiplies it
back with), then the event and the holding are set to USD. The IDR cost basis and realized
P&L therefore stay the same within a stated rounding tolerance, and valuation is untouched
(it reads the IDR price cache, never the holding's currency). The platform is set to USD too.
Everything else is left exactly as it was and listed with its reason. Every change is audited.

The output contains amounts. It goes to your terminal; do not paste it into tracked files.
"""
import argparse
import sys
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, inspect, select

from backend import fx
from backend.db import SessionLocal, engine
from backend.models import AuditLog, ClosedPosition, Holding, Platform, PortfolioEvent, PortfolioValueHistory, Transaction
from backend.portfolio import recompute_holding_from_events
from backend.writes import _portfolio_event_snapshot

Q12 = Decimal("1e-12")
HALF_ULP = Decimal("5e-13")  # half of the 12th decimal: the most one rounded price can be off
SOURCE = "usd_conversion"
_COUNTED = {"transactions": Transaction, "closed_positions": ClosedPosition,
            "portfolio_events": PortfolioEvent, "holdings": Holding}


class _Skip(Exception):
    """Leave this position exactly as it was (rolls back its savepoint only)."""

    def __init__(self, reason: str):
        self.reason = reason


def _counts(db) -> dict[str, int]:
    db.flush()
    return {n: db.scalar(select(func.count()).select_from(m)) for n, m in _COUNTED.items()}


def _num(x: Decimal) -> str:
    return format(x.normalize(), "f")


def _classify(db, h, events):
    """The reason this position stays as it is, or None. Writes nothing."""
    if h.quantity == 0:
        return "zero_quantity"
    if h.asset_type == "cash" or h.ticker == "CASH":
        return "cash"  # relabelling an IDR amount as USD would value it at the USD rate
    if not events:
        return "no_events"  # the opening-lot path would mis-price a USD position
    if any((e.currency or h.currency) != "IDR" for e in events):
        return "mixed_currency"
    today = fx._jakarta_today()
    if any(e.date >= today for e in events):
        return "rate_not_final"  # checked before any rate call: today's rate is not final
    if any(fx.get_rate("USD", "IDR", e.date, db) is None for e in events):
        return "no_rate"  # the exact call recompute makes once the event is USD
    return None


def _convert(db, h, events, floor) -> dict:
    """Convert one position inside the caller's savepoint; raises _Skip to undo just it."""
    stored = (h.quantity, h.avg_cost)
    before = recompute_holding_from_events(db, h.ticker, h.platform_id)
    db.flush()
    db.refresh(h)
    if before["quantity"] is None:
        raise _Skip("no_rate")
    if (h.quantity, h.avg_cost) != stored:
        raise _Skip("ledger_mismatch")  # recompute would overwrite a hand-edited row

    tol = Decimal("1e-12")
    for e in events:
        rate = fx.get_rate("USD", "IDR", e.date, db)
        snap = _portfolio_event_snapshot(e)
        e.price = (e.price / rate).quantize(Q12, ROUND_HALF_UP)
        e.currency = "USD"
        tol += e.quantity * rate * HALF_ULP
        db.add(AuditLog(entity="portfolio_event", entity_id=e.id, operation="edit", before=snap,
                        after={**_portfolio_event_snapshot(e), "price": format(e.price, "f"),
                               "source": SOURCE, "rate": format(rate, "f")}))
    db.add(AuditLog(entity="holding", entity_id=h.id, operation="edit",
                    before={"ticker": h.ticker, "currency": "IDR", "source": SOURCE},
                    after={"ticker": h.ticker, "currency": "USD", "source": SOURCE}))
    h.currency = "USD"
    db.flush()
    after = recompute_holding_from_events(db, h.ticker, h.platform_id)
    db.flush()
    cost_b, cost_a = before["avg_cost"] * before["quantity"], None
    if after["quantity"] is not None:
        cost_a = after["avg_cost"] * after["quantity"]
    if (cost_a is None or after["quantity"] != before["quantity"] or abs(cost_a - cost_b) > tol
            or abs(after["realized_pnl"] - before["realized_pnl"]) > tol):
        raise RuntimeError(f"{h.ticker} (platform {h.platform_id}) moved beyond the rounding tolerance")
    return {
        "holding_id": h.id, "ticker": h.ticker, "events": len(events),
        "cost_before": cost_b, "cost_after": cost_a,
        "realized_before": before["realized_pnl"], "realized_after": after["realized_pnl"],
        "tolerance": tol,
        "floor_events": sum(1 for e in events if floor is not None and e.date < floor),
    }


def run(db, platform_id: int, apply: bool = False) -> dict:
    """Classify the platform's open IDR holdings and convert the eligible ones.

    Classification writes nothing. Each conversion runs in its own savepoint. The
    caller's session is rolled back (dry run) or committed once (apply).
    """
    plat = db.get(Platform, platform_id)
    if plat is None:
        raise ValueError(f"No platform with id {platform_id}")
    before = _counts(db)
    audit_before = db.scalar(select(func.count()).select_from(AuditLog))
    q = (select(Holding).where(Holding.platform_id == platform_id, Holding.currency == "IDR")
         .order_by(Holding.ticker))
    holdings = db.scalars(q.with_for_update() if apply else q).all()
    floor = db.scalar(select(func.min(PortfolioValueHistory.snapshot_date)))
    convert, left = [], []
    try:
        for h in holdings:
            who = {"holding_id": h.id, "ticker": h.ticker}
            events = db.scalars(
                select(PortfolioEvent)
                .where(PortfolioEvent.ticker == h.ticker, PortfolioEvent.platform_id == platform_id)
                .order_by(PortfolioEvent.date, PortfolioEvent.id)
            ).all()
            reason = _classify(db, h, events)
            if reason is None:
                try:
                    with db.begin_nested():
                        convert.append(_convert(db, h, events, floor))
                except _Skip as skip:
                    reason = skip.reason
            if reason is not None:
                left.append({**who, "reason": reason})
        platform_change = plat.currency != "USD"
        if platform_change:
            db.add(AuditLog(entity="platform", entity_id=plat.id, operation="edit",
                            before={"currency": plat.currency},
                            after={"currency": "USD", "source": SOURCE}))
            plat.currency = "USD"
        expected_audit = audit_before + sum(c["events"] for c in convert) + len(convert) + int(platform_change)
        if _counts(db) != before or db.scalar(select(func.count()).select_from(AuditLog)) != expected_audit:
            raise RuntimeError(
                "row counts moved unexpectedly (a record may have been added at that moment); re-run"
            )
        if apply:
            db.commit()
        else:
            db.rollback()
    except Exception as exc:
        db.rollback()
        raise RuntimeError(f"{exc}; nothing was changed") from exc
    return {"convert": convert, "left": left, "floor": floor, "applied": apply,
            "platform_change": platform_change}


def _print(rep: dict) -> None:
    print(f"snapshot floor: {rep['floor'] or 'none'}")
    print(f"convert: {len(rep['convert'])}")
    for c in rep["convert"]:
        print(f"  holding_id={c['holding_id']} ticker={c['ticker']} events={c['events']} "
              f"cost_idr_before={_num(c['cost_before'])} cost_idr_after={_num(c['cost_after'])} "
              f"realized_idr_before={_num(c['realized_before'])} realized_idr_after={_num(c['realized_after'])} "
              f"tolerance={_num(c['tolerance'])} events_before_snapshot_floor={c['floor_events']}")
    print(f"left alone: {len(rep['left'])}")
    for x in rep["left"]:
        print(f"  holding_id={x['holding_id']} ticker={x['ticker']} left_alone={x['reason']}")
    for key in ("cost", "realized"):
        print(f"total {key} idr: before={_num(sum((c[key + '_before'] for c in rep['convert']), Decimal(0)))} "
              f"after={_num(sum((c[key + '_after'] for c in rep['convert']), Decimal(0)))}")
    print("platform currency: IDR -> USD" if rep["platform_change"] else "platform currency: already USD")
    if not rep["convert"]:
        print("Nothing to convert.")
    elif rep["applied"]:
        print("Applied: one transaction committed.")
    else:
        print("Dry run: nothing was changed. A rate missing from the cache may have been fetched and "
              "cached, exactly as loading the Investments page does; nothing else was written.")
        print("Run again with --apply to convert.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m backend.convert_platform_to_usd", description=__doc__.split("\n")[0])
    ap.add_argument("--platform-id", type=int, required=True, help="the one platform to convert")
    ap.add_argument("--apply", action="store_true", help="convert (default is a dry run)")
    args = ap.parse_args(argv)
    url = engine.url  # never print the password
    print(f"database: {url.database} host: {url.host} port: {url.port}")
    print("mode: APPLY" if args.apply else "mode: dry run")
    scale = next((c["type"].scale for c in inspect(engine).get_columns("portfolio_events") if c["name"] == "price"), None)
    if scale is None or scale < 12:
        print("portfolio_events.price has fewer than 12 decimals: run `alembic upgrade head` first.")
        return 1
    db = SessionLocal()
    try:
        plat = db.get(Platform, args.platform_id)
        if plat is None:
            print(f"No platform with id {args.platform_id}.")
            return 1
        print(f"platform: id={plat.id} name={plat.name} currency={plat.currency}")
        rep = run(db, args.platform_id, apply=args.apply)
    except Exception as exc:
        db.rollback()
        print(f"Failed: {exc}")
        if "nothing was changed" not in str(exc):
            print("Nothing was changed.")
        return 1
    finally:
        db.close()
    _print(rep)
    return 0


if __name__ == "__main__":
    sys.exit(main())
