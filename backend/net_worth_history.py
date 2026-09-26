"""Read-only composition of the liquid and investment net-worth series (NWH-02, D-03).

This module composes `backend.reconstruction.monthly_liquid_series` (Phase 20)
and `backend.investment_reconstruction.monthly_investment_series` (Phase 21)
into one authoritative monthly net-worth series, computed fresh on every
call. It persists nothing: no `net_worth_history` table exists and no
migration backs one -- the ARCHITECTURE.md table proposal is superseded by
D-03. It issues no INSERT, UPDATE, or DELETE anywhere in this file, and
imports nothing from `backend.writes`. The only raw SQL this module issues
of its own is the single newest-bucket parity read against
`portfolio_value_history` (see `_parity_verdict` below) -- everything else
is delegated verbatim to the two sibling engines.
"""

import logging
from decimal import Decimal

from sqlalchemy import text

from backend.db import SessionLocal
from backend.investment_reconstruction import monthly_investment_series
from backend.reconstruction import liquid_drift_estimate, monthly_liquid_series

logger = logging.getLogger(__name__)

# Composition-owned -- deliberately does NOT re-enumerate GAP_REASONS or
# INVESTMENT_GAP_REASONS (that would be three places to keep in sync). Each
# engine's own reason stays verbatim inside its own `liquid`/`investment`
# sub-object; the four members below describe only the COMBINED verdict.
# `parity_mismatch` is the one member neither sibling engine can ever
# produce -- it is set exclusively by this layer's own newest-bucket
# comparison, which is what makes a parity disagreement distinguishable from
# an ordinary honesty gap.
COMPOSED_GAP_REASONS = (
    "liquid_half_gapped",
    "investment_half_gapped",
    "both_halves_gapped",
    "parity_mismatch",
)


def monthly_net_worth_series(months: int = 72, *, db=None) -> dict:
    """The composed monthly net-worth series: one row per month, each
    carrying both a `liquid` and an `investment` sub-object (SC4/NWH-06) plus
    a combined `total`/`honest`/`gap_reason`.

    Both sibling engines are driven from ONE session (D-10):
    `monthly_liquid_series` takes a raw `Connection` via `conn=`;
    `monthly_investment_series` takes a `Session` via `db=`. Passing
    `db.connection()` to the first returns the connection bound to that
    session's current transaction, so both halves read one database state.

    The combined `total` is non-null only when both halves are independently
    honest (D-04) -- never a partial sum, never zero-for-unknown, never
    carried forward from the previous bucket (D-06). A "net worth" figure
    that silently omits the bank balance is a fabricated number by this
    project's standard.

    `months` outside 1-600 raises `ValueError` before any DB work. 600
    months is 50 years -- comfortably past this project's data floor -- and
    bounds the `generate_series` both sibling engines run.

    23.1 D-06: the envelope also carries `liquid_drift_estimate`, the
    computed anchor-day residual `backend.reconstruction.liquid_drift_estimate`
    returns (or `None` when no liquid account has an anchor). It is computed fresh on every
    call, on the same session as both halves, and reported ONCE at envelope
    level -- never spread across rows, never persisted, never fabricated.

    Never commits its own session and never rolls back a caller-supplied
    one -- the transaction boundary belongs to the caller, same convention
    as both sibling engines.
    """
    if not (1 <= months <= 600):
        raise ValueError(f"months must be between 1 and 600 (inclusive), got {months}")

    owns_db = db is None
    db = db or SessionLocal()
    try:
        liquid = monthly_liquid_series(months=months, conn=db.connection())
        investment = monthly_investment_series(months=months, db=db)

        liquid_by_month = {r["month"]: r for r in liquid["rows"]}
        investment_by_month = {r["month"]: r for r in investment["rows"]}

        liquid_months = set(liquid_by_month)
        investment_months = set(investment_by_month)
        if liquid_months != investment_months:
            # Same posture as net_worth()'s coverage assertion: refuse to
            # silently drop or invent a bucket rather than zip a partial mess.
            raise ValueError(
                "monthly_net_worth_series: liquid and investment month keys "
                f"disagree, symmetric difference = {liquid_months ^ investment_months}"
            )

        rows: list[dict] = []
        gap_counts: dict[str, int] = {}
        honest_months: list[str] = []

        for month in sorted(liquid_months):
            lrow = liquid_by_month[month]
            irow = investment_by_month[month]

            liquid_sub = {
                "total": lrow["liquid_total"],
                "by_account": lrow["liquid_by_account"],
                "honest": lrow["honest"],
                "gap_reason": lrow["gap_reason"],
                "valuation_basis": lrow["valuation_basis"],
            }
            investment_sub = {
                "total": irow["investment_total"],
                "by_position": irow["investment_by_position"],
                "honest": irow["honest"],
                "gap_reason": irow["gap_reason"],
                "valuation_basis": irow["valuation_basis"],
                "as_of_date": irow["as_of_date"],
            }

            honest = bool(liquid_sub["honest"]) and bool(investment_sub["honest"])
            if honest:
                total = liquid_sub["total"] + investment_sub["total"]
                gap_reason = None
                honest_months.append(month)
            else:
                total = None
                if not liquid_sub["honest"] and not investment_sub["honest"]:
                    gap_reason = "both_halves_gapped"
                elif not liquid_sub["honest"]:
                    gap_reason = "liquid_half_gapped"
                else:
                    gap_reason = "investment_half_gapped"
                gap_counts[gap_reason] = gap_counts.get(gap_reason, 0) + 1

            rows.append(
                {
                    "month": month,
                    "liquid": liquid_sub,
                    "investment": investment_sub,
                    "honest": honest,
                    "total": total,
                    "gap_reason": gap_reason,
                }
            )

        # D-11/D-08: the newest bucket alone gets a like-for-like parity
        # verdict, and only when it is already combined-honest -- a row that
        # already gaps needs no parity verdict.
        if rows and rows[-1]["honest"]:
            newest = rows[-1]
            verdict = _parity_verdict(db, newest)
            if verdict is not None:
                newest["honest"] = False
                newest["total"] = None
                newest["gap_reason"] = verdict
                honest_months.remove(newest["month"])
                gap_counts[verdict] = gap_counts.get(verdict, 0) + 1

        return {
            "tool": "net_worth_history_series",
            "rows": rows,
            "honest_months": honest_months,
            "gap_summary": gap_counts,
            "liquid_drift_estimate": liquid_drift_estimate(conn=db.connection()),
        }
    finally:
        if owns_db:
            db.close()


def _parity_verdict(db, row: dict) -> str | None:
    """Like-for-like parity check for the newest combined-honest bucket
    (D-11), half by half against like-typed sources -- never the composed
    total against a live `net_worth()`/`portfolio_summary()` total.

    Why half-by-half, not total-vs-total: `net_worth()`'s investment half
    reads `price_cache` live; the composed investment half reads the
    once-daily `portfolio_value_history` snapshot. The two routinely
    differ by a small amount -- a real, expected drift
    between a continuous read and a periodic snapshot, not a bug. Comparing
    the composed total against a live `net_worth()` total would gap the
    current bucket on most ordinary days, pushing the chart's right edge
    back a month -- exactly the mismatch NWH-02 exists to eliminate.

    Rounding tolerance, stated once here as the documented rule: `net_worth()`
    and `account_balances()` return `float`; both composed engines return
    `Decimal`. Every comparison below converts the float side via
    `Decimal(str(value))`, then quantizes BOTH sides to whole IDR
    (`quantize(Decimal("1"))`) before comparing -- that quantization IS the
    parity tolerance, not an unstated side effect. Never compare a `float`
    to a `Decimal` directly.

    Liquid half -- exact and genuinely failable: a fresh `SUM(t.amount)` at
    call time via `account_balances()` rows filtered to `type == "liquid"`
    (the identical filter `net_worth()` uses), with no snapshot lag.

    Investment half -- only when `valuation_basis == "snapshot"`: one
    parameterized read summing `market_value` from `portfolio_value_history`
    for the exact `snapshot_date` this row's composition already selected.
    This is near-tautological by construction -- it re-reads whichever date
    the composition chose, so it CANNOT prove that date was the right one to
    pick (plan 22-04's separate `as_of_date` assertion closes that gap, not
    this check). What it CAN catch is a dropped or double-counted row in the
    composition's own summing. When `valuation_basis == "replay"` (no stored
    snapshot to compare against for this bucket) the investment-half
    comparison is skipped and only the liquid half is checked.

    Fails closed: any exception raised while comparing routes to the gap
    path via `"parity_mismatch"`, logged at WARNING -- an unverified combined
    total must never survive a broken comparison.
    """
    try:
        from backend.tools import account_balances

        one = Decimal("1")

        live_liquid = sum(
            (Decimal(str(r["current_balance"])) for r in account_balances()["rows"] if r["type"] == "liquid"),
            Decimal("0"),
        )
        composed_liquid = row["liquid"]["total"]
        if composed_liquid.quantize(one) != live_liquid.quantize(one):
            logger.warning(
                "net_worth_history parity mismatch (liquid half): composed=%s live=%s",
                composed_liquid, live_liquid,
            )
            return "parity_mismatch"

        investment = row["investment"]
        if investment["valuation_basis"] == "snapshot":
            snapshot_total = db.connection().execute(
                text(
                    "SELECT COALESCE(SUM(market_value), 0) FROM portfolio_value_history "
                    "WHERE snapshot_date = :snapshot_date"
                ),
                {"snapshot_date": investment["as_of_date"]},
            ).scalar()
            composed_investment = investment["total"]
            live_investment = Decimal(str(snapshot_total))
            if composed_investment.quantize(one) != live_investment.quantize(one):
                logger.warning(
                    "net_worth_history parity mismatch (investment half): "
                    "composed=%s snapshot=%s as_of=%s",
                    composed_investment, live_investment, investment["as_of_date"],
                )
                return "parity_mismatch"
        # basis == "replay": no stored snapshot exists for this bucket, so
        # there is nothing like-typed to compare the investment half
        # against here -- the liquid-half check above still ran.

        return None
    except Exception:
        logger.warning(
            "net_worth_history parity check raised an exception; gapping the "
            "bucket rather than returning an unverified total",
            exc_info=True,
        )
        return "parity_mismatch"


# This module exposes no FastAPI route yet (plan 22-03 adds one), is not
# registered in backend/tools.py's TOOLS dict, and is not registered as a
# LlamaIndex FunctionTool in backend/query.py -- agent/MCP registration of
# the trend series is explicitly deferred, out of NWH-01..06's scope.
