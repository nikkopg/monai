"""Read-only composition of the liquid and investment net-worth series (NWH-02, D-03).

This module composes `backend.reconstruction.monthly_liquid_series` (Phase 20)
and `backend.investment_reconstruction.monthly_investment_series` (Phase 21)
into one authoritative monthly net-worth series, computed fresh on every
call. It persists nothing: no `net_worth_history` table exists and no
migration backs one -- the ARCHITECTURE.md table proposal is superseded by
D-03. It issues no INSERT, UPDATE, or DELETE anywhere in this file, and
imports nothing from `backend.writes`, and issues no SQL of its own: it only
composes the two sibling engines.
"""

from backend.db import SessionLocal
from backend.investment_reconstruction import monthly_investment_series
from backend.reconstruction import liquid_drift_estimate, monthly_liquid_series

# Composition-owned -- deliberately does NOT re-enumerate GAP_REASONS or
# INVESTMENT_GAP_REASONS (that would be three places to keep in sync). Each
# engine's own reason stays verbatim inside its own `liquid`/`investment`
# sub-object; the three members below describe only the COMBINED verdict.
COMPOSED_GAP_REASONS = (
    "liquid_half_gapped",
    "investment_half_gapped",
    "both_halves_gapped",
)

_MAX_MONTHS = 600


def _usable_investment(row: dict) -> bool:
    return bool(row["honest"]) and row["investment_total"] is not None


def _carry_investment_forward(rows: list[dict]) -> list[dict]:
    """An investment row with no usable value becomes a copy of the last usable
    row (total, positions, as_of_date and valuation_basis included) with only
    `month` replaced. Before the first usable row a gap passes through."""
    held = None
    out = []
    for row in rows:
        if _usable_investment(row):
            held = row
            out.append(row)
        elif held is not None:
            out.append({**held, "month": row["month"]})
        else:
            out.append(row)
    return out


def monthly_net_worth_series(months: int = 72, *, db=None) -> dict:
    """The composed monthly net-worth series: one row per month, each
    carrying both a `liquid` and an `investment` sub-object (SC4/NWH-06) plus
    a combined `total`/`honest`/`gap_reason`.

    Both sibling engines are driven from ONE session (D-10):
    `monthly_liquid_series` takes a raw `Connection` via `conn=`;
    `monthly_investment_series` takes a `Session` via `db=`. Passing
    `db.connection()` to the first returns the connection bound to that
    session's current transaction, so both halves read one database state.

    The combined `total` is non-null when both halves have a value for the
    month -- never a partial sum, never zero-for-unknown. The investment half
    carries forward from its last known month (keeping that month's
    `as_of_date` and `valuation_basis`) and is never invented before its first
    known value; a liquid gap is never carried. A "net worth" figure that
    silently omits the bank balance is a fabricated number by this project's
    standard.

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
    if not (1 <= months <= _MAX_MONTHS):
        raise ValueError(f"months must be between 1 and {_MAX_MONTHS} (inclusive), got {months}")

    owns_db = db is None
    db = db or SessionLocal()
    try:
        liquid = monthly_liquid_series(months=months, conn=db.connection())
        investment = monthly_investment_series(months=months, db=db)
        inv_rows = investment["rows"]
        if not _usable_investment(inv_rows[0]) and months < _MAX_MONTHS:
            # ponytail: one extra full-history read when the window opens on a gap,
            # so a known value older than the window can seed the carry; add a
            # bounded lookback if that read ever gets slow.
            inv_rows = monthly_investment_series(months=_MAX_MONTHS, db=db)["rows"]
        inv_rows = _carry_investment_forward(inv_rows)[-months:]

        liquid_by_month = {r["month"]: r for r in liquid["rows"]}
        investment_by_month = {r["month"]: r for r in inv_rows}

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


# This module exposes no FastAPI route yet (plan 22-03 adds one), is not
# registered in backend/tools.py's TOOLS dict, and is not registered as a
# LlamaIndex FunctionTool in backend/query.py -- agent/MCP registration of
# the trend series is explicitly deferred, out of NWH-01..06's scope.
