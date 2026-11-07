"""Hand-run: turn existing zero-quantity positions into closed records (quick 261107-nq6).

    python -m backend.close_zero_positions            # dry run, changes nothing
    python -m backend.close_zero_positions --apply    # convert, in one transaction

The owner runs this by hand, once. Nothing at boot, in the scheduler or in a migration
imports or runs it, and importing it does nothing. It uses DATABASE_URL, whose default is
the LIVE database, so the first line it prints is the database name: check it.

A zero-quantity position whose events sum to exactly zero, include a sell and never went
negative is saved as a ClosedPosition (realized P&L in IDR as the app itself computes it),
then its holding and events are deleted. Empty zero rows (no events) are deleted with an
audit row and no record. Everything else is left alone and reported with its reason: CASH
rows, rows with no sell, a ledger that went negative, a ledger that does not sum to zero,
and a position whose FX rate cannot be resolved. Cash transactions are never touched.

The output contains amounts. It goes to your terminal; do not paste it into tracked files.
"""
import argparse
import sys
from decimal import Decimal

from sqlalchemy import func, inspect, select

from backend.db import SessionLocal, engine
from backend.models import ClosedPosition, Holding, PortfolioEvent, PortfolioValueHistory, Transaction
from backend.portfolio import _realized_for_position
from backend.writes import apply_delete_holding, close_blocker, close_position_if_flat

TOL = Decimal("0.00000001")
_COUNTED = {"transactions": Transaction, "closed_positions": ClosedPosition,
            "portfolio_events": PortfolioEvent, "holdings": Holding}


def _counts(db) -> dict[str, int]:
    db.flush()
    return {n: db.scalar(select(func.count()).select_from(m)) for n, m in _COUNTED.items()}


def _num(x: Decimal) -> str:
    return format(x.normalize(), "f")


def run(db, apply: bool = False) -> dict:
    """Classify every zero-quantity holding; with apply, convert in one transaction.

    Classification writes nothing and never recomputes (a recompute would overwrite a
    hand-edited row). The caller's session is rolled back (dry run) or committed once.
    """
    before = _counts(db)
    q = select(Holding).where(Holding.quantity == 0).order_by(Holding.platform_id, Holding.ticker)
    holdings = db.scalars(q.with_for_update() if apply else q).all()
    floor = db.scalar(select(func.min(PortfolioValueHistory.snapshot_date)))
    convert, empty, left, cash = [], [], [], 0
    for h in holdings:
        events = db.scalars(
            select(PortfolioEvent)
            .where(PortfolioEvent.ticker == h.ticker, PortfolioEvent.platform_id == h.platform_id)
            .order_by(PortfolioEvent.date, PortfolioEvent.id)
        ).all()
        who = {"holding_id": h.id, "ticker": h.ticker, "platform_id": h.platform_id}
        is_cash = h.asset_type == "cash" or h.ticker == "CASH"
        if not events and not is_cash:
            empty.append(who)
            continue
        reason = close_blocker(h, events)
        if reason == "cash":
            cash += 1
            continue
        if reason is None:
            realized = _realized_for_position(db, h.ticker, h.platform_id)["realized_pnl"]
            reason = "no_rate" if realized is None else None
        if reason is not None:
            left.append({**who, "reason": reason})
            continue
        convert.append({
            **who, "realized": realized,
            "close_date": max(e.date for e in events if e.event_type == "sell"),
            "events": len(events),
            "floor_events": sum(1 for e in events if floor is not None and e.date < floor),
        })

    if apply:
        try:
            for c in convert:
                rec = close_position_if_flat(db, c["ticker"], c["platform_id"])
                if rec is None or abs(rec.realized_pnl - c["realized"]) > TOL:
                    raise RuntimeError(f"{c['ticker']} (platform {c['platform_id']}) did not close as classified")
            for e in empty:
                apply_delete_holding(db, e["holding_id"], {
                    "id": str(e["holding_id"]), "ticker": e["ticker"], "quantity": "0",
                    "platform_id": str(e["platform_id"]),
                })
            expected = {
                "transactions": before["transactions"],  # cash is never touched
                "closed_positions": before["closed_positions"] + len(convert),
                "portfolio_events": before["portfolio_events"] - sum(c["events"] for c in convert),
                "holdings": before["holdings"] - len(convert) - len(empty),
            }
            if _counts(db) != expected:
                raise RuntimeError(
                    "row counts moved unexpectedly (a record may have been added at that moment, "
                    "for example a Bitget sync); re-run"
                )
            db.commit()
        except Exception as exc:
            db.rollback()
            raise RuntimeError(f"{exc}; nothing was changed") from exc
    else:
        db.rollback()
    return {"convert": convert, "empty": empty, "left": left, "cash": cash,
            "floor": floor, "applied": apply}


def _print(rep: dict) -> None:
    print(f"snapshot floor: {rep['floor'] or 'none'}")
    print(f"convert: {len(rep['convert'])}")
    print(f"empty rows to delete (no events, no record): {len(rep['empty'])}")
    print(f"cash rows left alone: {rep['cash']}")
    print(f"left alone: {len(rep['left'])}")
    for c in rep["convert"]:
        print(f"  holding_id={c['holding_id']} ticker={c['ticker']} platform_id={c['platform_id']} "
              f"realized={_num(c['realized'])} close_date={c['close_date']} events={c['events']} "
              f"events_before_snapshot_floor={c['floor_events']}")
    for e in rep["empty"]:
        print(f"  holding_id={e['holding_id']} ticker={e['ticker']} platform_id={e['platform_id']} empty")
    for x in rep["left"]:
        print(f"  holding_id={x['holding_id']} ticker={x['ticker']} platform_id={x['platform_id']} "
              f"left_alone={x['reason']}")
    if not rep["convert"] and not rep["empty"]:
        print("Nothing to convert.")
    elif rep["applied"]:
        print("Applied: one transaction committed.")
    else:
        print("Dry run: nothing was changed. A rate missing from the cache may have been fetched and "
              "cached, exactly as loading the Investments page does; nothing else was written.")
        print("Run again with --apply to convert.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m backend.close_zero_positions", description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="convert (default is a dry run)")
    args = ap.parse_args(argv)
    url = engine.url  # never print the password
    print(f"database: {url.database} host: {url.host} port: {url.port}")
    print("mode: APPLY" if args.apply else "mode: dry run")
    if not inspect(engine).has_table("closed_positions"):
        print("The closed_positions table is missing: run `alembic upgrade head` first.")
        return 1
    db = SessionLocal()
    try:
        rep = run(db, apply=args.apply)
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
