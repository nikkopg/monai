"""Hand-run: record a coin fee on one position's funded buys (quick 261108-gdf).

    python -m backend.backfill_coin_fees --platform-id N --ticker T            # dry run, changes nothing
    python -m backend.backfill_coin_fees --platform-id N --ticker T --apply    # write, in one transaction

The owner runs this by hand, one position per run. Nothing at boot, in the scheduler or in a
migration imports or runs it, and importing it does nothing. It uses DATABASE_URL, whose
default is the LIVE database, so the first line it prints is the database name: check it.

For the one open position it finds the funded buys that have no fee yet and records a coin fee
on each: fee = filled quantity x --rate (default 0.001), rounded to 8 decimals (half-up, or
down with --rounding down), fee_kind coin, and the stored quantity becomes filled - fee. The
cash legs are never touched; total buy cost stays the same (price x net + price x fee = price x
filled) while the quantity drops, so the average cost rises. Unfunded buys (an opening lot) and
events that already have a fee are skipped and counted. Both rounding totals are printed every
time so they can be compared with the exchange's figure, and --expect-quantity prints the gap to
the balance the exchange shows (it never refuses).

Left alone, with a printed reason and nothing written: no_position (none open, or closed),
zero_quantity, cash, ledger_mismatch (the stored row differs from its events), no_rate (a
trade-date rate is missing) and negative_running_quantity (a later sell could not be covered by
the net quantity). A position that ends exactly flat is applied and reported: close it next
with backend.close_zero_positions. Every change is audited.

The output contains amounts. It goes to your terminal; do not paste it into tracked files.
"""
import argparse
import sys
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from sqlalchemy import func, inspect, select

from backend.db import SessionLocal, engine
from backend.models import AuditLog, ClosedPosition, Holding, Platform, PortfolioEvent, PortfolioValueHistory, Transaction
from backend.portfolio import _realized_for_position, recompute_holding_from_events
from backend.writes import _portfolio_event_snapshot, _running_quantities

Q8 = Decimal("1e-8")
SOURCE = "coin_fee_backfill"
_ROUNDINGS = {"half-up": ROUND_HALF_UP, "down": ROUND_DOWN}
_COUNTED = {"transactions": Transaction, "closed_positions": ClosedPosition,
            "portfolio_events": PortfolioEvent, "holdings": Holding}


def fee_for(filled: Decimal, rate: Decimal, rounding: str) -> Decimal:
    """The coin fee on a filled quantity: filled x rate to 8 decimals."""
    return (filled * rate).quantize(Q8, _ROUNDINGS[rounding])


def _counts(db) -> dict[str, int]:
    db.flush()
    return {n: db.scalar(select(func.count()).select_from(m)) for n, m in _COUNTED.items()}


def _num(x) -> str:
    return "n/a" if x is None else format(x.normalize(), "f")


def _figures(db, h, result) -> dict:
    """Quantity, IDR cost (unrounded), USD (native) average cost and realized P&L of the ledger."""
    return {
        "quantity": result["quantity"],
        "cost_idr": result["avg_cost"] * result["quantity"],
        "usd_avg_cost": _realized_for_position(db, h.ticker, h.platform_id)["native_avg_cost"],
        "realized_idr": result["realized_pnl"],
    }


def run(db, platform_id: int, ticker: str, rate: Decimal = Decimal("0.001"), rounding: str = "half-up",
        expect_quantity: Decimal | None = None, apply: bool = False) -> dict:
    """Record the coin fee on one position's fee-less funded buys.

    One position, one transaction: the caller's session is rolled back (dry run, or any
    left-alone reason) or committed once (apply).
    """
    if db.get(Platform, platform_id) is None:
        raise ValueError(f"No platform with id {platform_id}")
    rep = {"left": None, "nothing": False, "applied": apply, "lines": [], "before": None, "after": None,
           "total_half_up": Decimal(0), "total_down": Decimal(0), "rounding": rounding,
           "skipped_unfunded": 0, "skipped_with_fee": 0, "skipped_tiny_fee": 0,
           "floor_events": 0, "flat": False, "expect": None}

    def leave(reason: str) -> dict:
        db.rollback()
        rep["left"] = reason
        return rep

    try:
        q = select(Holding).where(Holding.ticker == ticker, Holding.platform_id == platform_id)
        h = db.scalars(q.with_for_update() if apply else q).one_or_none()
        if h is None:
            return leave("no_position")
        if h.quantity == 0:
            return leave("zero_quantity")
        if h.asset_type == "cash" or h.ticker == "CASH":
            return leave("cash")
        events = db.scalars(
            select(PortfolioEvent)
            .where(PortfolioEvent.ticker == ticker, PortfolioEvent.platform_id == platform_id)
            .order_by(PortfolioEvent.date, PortfolioEvent.id)
        ).all()
        targets = []
        for e in events:
            if e.fee is not None:
                rep["skipped_with_fee"] += 1
            elif e.event_type == "buy" and e.transaction_id is None:
                rep["skipped_unfunded"] += 1
            elif e.event_type == "buy":
                fee = fee_for(e.quantity, rate, rounding)
                rep["total_half_up"] += fee_for(e.quantity, rate, "half-up")
                rep["total_down"] += fee_for(e.quantity, rate, "down")
                if fee == 0:
                    rep["skipped_tiny_fee"] += 1
                else:
                    targets.append((e, fee))
        if not targets:
            rep["nothing"] = True
            rep["after"] = {"quantity": h.quantity}
            db.rollback()
        else:
            _fix_events(db, h, events, targets, rate, rounding, rep, apply)
        if expect_quantity is not None and rep["left"] is None:
            after_qty = rep["after"]["quantity"]
            rep["expect"] = {"expected": expect_quantity, "after": after_qty, "difference": after_qty - expect_quantity}
    except Exception as exc:
        db.rollback()
        raise RuntimeError(f"{exc}; nothing was changed") from exc
    return rep


def _fix_events(db, h, events, targets, rate, rounding, rep, apply) -> None:
    """Steps 2 to 4 of run(): figures before, the change, figures after, the count check, commit."""
    def left(reason: str) -> None:
        db.rollback()
        rep["left"] = reason

    counts_before = _counts(db)
    audit_before = db.scalar(select(func.count()).select_from(AuditLog))
    floor = db.scalar(select(func.min(PortfolioValueHistory.snapshot_date)))
    stored = (h.quantity, h.avg_cost)
    before = recompute_holding_from_events(db, h.ticker, h.platform_id)
    db.flush()
    db.refresh(h)
    if before["quantity"] is None:
        return left("no_rate")
    if (h.quantity, h.avg_cost) != stored:
        return left("ledger_mismatch")  # recompute would overwrite a hand-edited row
    rep["before"] = _figures(db, h, before)

    changed = []
    for e, fee in targets:
        snap = _portfolio_event_snapshot(e)
        rep["lines"].append({"id": e.id, "date": e.date, "filled": e.quantity, "fee": fee, "net": e.quantity - fee})
        e.quantity, e.fee, e.fee_kind = e.quantity - fee, fee, "coin"
        changed.append((e, snap))
    if any(q < 0 for q in _running_quantities(events)):
        return left("negative_running_quantity")
    for e, snap in changed:
        db.add(AuditLog(entity="portfolio_event", entity_id=e.id, operation="edit", before=snap,
                        after={**_portfolio_event_snapshot(e), "source": SOURCE,
                               "fee_rate": format(rate, "f"), "rounding": rounding}))
    db.flush()
    after = recompute_holding_from_events(db, h.ticker, h.platform_id)
    db.flush()
    db.refresh(h)
    if after["quantity"] is None:
        return left("no_rate")
    rep["after"] = _figures(db, h, after)
    rep["flat"] = after["quantity"] == 0
    rep["floor_events"] = sum(1 for e, _ in changed if floor is not None and e.date < floor)
    if _counts(db) != counts_before or db.scalar(select(func.count()).select_from(AuditLog)) != audit_before + len(changed):
        raise RuntimeError("row counts moved unexpectedly (a record may have been added at that moment); re-run")
    if apply:
        db.commit()
    else:
        db.rollback()


def _print(rep: dict) -> None:
    for ln in rep["lines"]:
        print(f"event id={ln['id']} date={ln['date']} filled={_num(ln['filled'])} fee={_num(ln['fee'])} net={_num(ln['net'])}")
    if rep["before"] and rep["after"]:
        for key in ("quantity", "cost_idr", "usd_avg_cost", "realized_idr"):
            print(f"{key}: before={_num(rep['before'][key])} after={_num(rep['after'][key])}")
    print(f"fee total half-up={_num(rep['total_half_up'])} down={_num(rep['total_down'])} (using {rep['rounding']})")
    print(f"skipped_unfunded={rep['skipped_unfunded']} skipped_with_fee={rep['skipped_with_fee']} "
          f"skipped_tiny_fee={rep['skipped_tiny_fee']}")
    print(f"events_before_snapshot_floor={rep['floor_events']}")
    if rep["expect"]:
        x = rep["expect"]
        print(f"expected_quantity={_num(x['expected'])} after={_num(x['after'])} difference={_num(x['difference'])}")
    if rep["flat"]:
        print("flat after the fix: run python -m backend.close_zero_positions")
    if rep["left"]:
        print(f"left alone: {rep['left']}")
    elif rep["nothing"]:
        print("Nothing to fix.")
    elif rep["applied"]:
        print("Applied: one transaction committed.")
    else:
        print("Dry run: nothing was changed. A rate missing from the cache may have been fetched and "
              "cached, exactly as loading the Investments page does; nothing else was written.")
        print("Run again with --apply to record the fees.")


def _rate(text: str) -> Decimal:
    try:
        value = Decimal(text)
    except ArithmeticError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number")
    if not (value.is_finite() and 0 < value < 1):
        raise argparse.ArgumentTypeError("the rate must be strictly between 0 and 1")
    return value


def _decimal(text: str) -> Decimal:
    try:
        value = Decimal(text)
    except ArithmeticError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number")
    if not value.is_finite():
        raise argparse.ArgumentTypeError(f"{text!r} is not a number")
    return value


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m backend.backfill_coin_fees", description=__doc__.split("\n")[0])
    ap.add_argument("--platform-id", type=int, required=True, help="the platform holding the position")
    ap.add_argument("--ticker", required=True, help="the position's ticker, exactly as stored")
    ap.add_argument("--rate", type=_rate, default=Decimal("0.001"), help="fee as a fraction of the filled quantity (default 0.001)")
    ap.add_argument("--rounding", choices=sorted(_ROUNDINGS), default="half-up", help="how the fee is rounded to 8 decimals")
    ap.add_argument("--expect-quantity", type=_decimal, default=None, help="the balance the exchange shows; prints the gap")
    ap.add_argument("--apply", action="store_true", help="write the fees (default is a dry run)")
    args = ap.parse_args(argv)
    url = engine.url  # never print the password
    print(f"database: {url.database} host: {url.host} port: {url.port}")
    print("mode: APPLY" if args.apply else "mode: dry run")
    if not any(c["name"] == "fee" for c in inspect(engine).get_columns("portfolio_events")):
        print("portfolio_events has no fee column: run `alembic upgrade head` first.")
        return 1
    db = SessionLocal()
    try:
        plat = db.get(Platform, args.platform_id)
        if plat is None:
            print(f"No platform with id {args.platform_id}.")
            return 1
        print(f"platform: id={plat.id} name={plat.name} currency={plat.currency}")
        print(f"position: ticker={args.ticker}")
        rep = run(db, args.platform_id, args.ticker, args.rate, args.rounding, args.expect_quantity, apply=args.apply)
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
