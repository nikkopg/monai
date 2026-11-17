"""SBN retail government bonds (ORI, SBR, ST, SR) with a monthly coupon (quick 261117-rw1).

An SBN is held to maturity and valued at face: quantity is the nominal in IDR and the unit
price is 1. Its terms live on the holding (rate, floating flag, pay day, maturity, tax %,
coupon account). Each month it pays

    gross = round_half_up(nominal x rate / 100 / 12)
    tax   = round_half_up(gross x tax_pct / 100)
    net   = gross - tax

in whole rupiah. The pay day is 1..28: every SBN series pays on the 10th or the 15th, so no
month-end clamping is ever needed.

`propose_due` is the one DB-touching function (lazy imports): it creates the pending coupon
and maturity proposals the daily job hands to the Inbox. Nothing is written to the ledger
until the owner approves.
"""
import logging
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

logger = logging.getLogger(__name__)

_ONE = Decimal(1)

# ponytail: a server off for over a month, or a bond entered long after purchase, misses the
# older coupons (the owner logs those by hand); upgrade path is a per-bond "coupons from" date.
CATCH_UP = timedelta(days=31)


def coupon_amounts(nominal: Decimal, rate: Decimal, tax_pct: Decimal) -> tuple[Decimal, Decimal, Decimal]:
    """(gross, tax, net) of one monthly coupon, whole rupiah, rounded half up."""
    gross = (nominal * rate / 100 / 12).quantize(_ONE, rounding=ROUND_HALF_UP)
    tax = (gross * tax_pct / 100).quantize(_ONE, rounding=ROUND_HALF_UP)
    return gross, tax, gross - tax


def pay_dates(day: int, after: date, through: date) -> list[date]:
    """Every date with this day-of-month strictly after `after` and on or before `through`."""
    out: list[date] = []
    y, m = after.year, after.month
    while True:
        d = date(y, m, day)
        if d > through:
            return out
        if d > after:
            out.append(d)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def bond_info(h, today: date, account_names: dict[int, str]) -> dict:
    """The summary `bond` dict of a bond holding: terms, monthly gross/tax/net, next pay dates."""
    info = {
        "rate": h.coupon_rate,
        "floating": h.coupon_floating,
        "pay_day": h.coupon_day,
        "maturity_date": h.maturity_date,
        "tax_pct": h.coupon_tax_pct,
        "coupon_account_id": h.coupon_account_id,
        "coupon_account_name": account_names.get(h.coupon_account_id),
        "gross": None, "tax": None, "net": None, "next_coupon_date": None, "upcoming": [],
    }
    if None in (h.coupon_rate, h.coupon_day, h.maturity_date):
        return info
    info["gross"], info["tax"], info["net"] = coupon_amounts(h.quantity, h.coupon_rate, h.coupon_tax_pct or Decimal(0))
    info["upcoming"] = pay_dates(h.coupon_day, today - timedelta(days=1), h.maturity_date)[:3]
    info["next_coupon_date"] = info["upcoming"][0] if info["upcoming"] else None
    return info


def propose_due(db, today: date) -> int:
    """Create the pending coupon / maturity proposals due on or before `today`; return how many.

    One 'schedule' proposal per bond position and pay date. A date is skipped when any
    schedule proposal with its key exists (pending, confirmed or rejected) or a dividend
    event already sits on it; uq_proposals_schedule_key makes a duplicate impossible even
    under a race. Adds to the caller's transaction and never commits.
    """
    from sqlalchemy import func, text

    from backend.models import Account, Holding, PortfolioEvent
    from backend.tools import _make_proposal  # lazy: tools imports a lot, avoid an import cycle

    seen = {k for (k,) in db.execute(text("SELECT payload->>'key' FROM proposals WHERE channel = 'schedule'"))}
    made = 0
    holdings = db.query(Holding).filter(Holding.asset_type == "bond", Holding.quantity > 0).all()
    for h in holdings:
        if None in (h.coupon_rate, h.coupon_day, h.maturity_date, h.coupon_account_id):
            logger.info("bond %s on platform %s has incomplete terms; no proposal", h.ticker, h.platform_id)
            continue
        acct = db.get(Account, h.coupon_account_id)
        if acct is None:
            continue
        pos = (PortfolioEvent.ticker == h.ticker, PortfolioEvent.platform_id == h.platform_id)
        floor = today - CATCH_UP
        first = db.query(func.min(PortfolioEvent.date)).filter(
            *pos, PortfolioEvent.event_type.in_(("buy", "deposit"))).scalar() or h.purchase_date
        if first is not None:
            floor = max(floor, first)
        paid = {d for (d,) in db.query(PortfolioEvent.date).filter(*pos, PortfolioEvent.event_type == "dividend")}
        gross, tax, net = coupon_amounts(h.quantity, h.coupon_rate, h.coupon_tax_pct or Decimal(0))
        base = f"{h.platform_id}:{h.ticker}"
        for d in pay_dates(h.coupon_day, floor, min(today, h.maturity_date)):
            if f"coupon:{base}:{d}" in seen or d in paid:
                continue
            after = {
                "ticker": h.ticker, "platform_id": h.platform_id, "date": d.isoformat(),
                "account_id": acct.id, "account": acct.name, "amount": str(net),
                "gross": str(gross), "tax": str(tax), "rate": str(h.coupon_rate),
                "floating": bool(h.coupon_floating), "tax_pct": str(h.coupon_tax_pct or 0),
                "nominal": str(h.quantity),
            }
            payload = {"operation": "add_coupon", "key": f"coupon:{base}:{d}", "rows": [{"before": None, "after": after}]}
            _make_proposal("add_coupon", payload, "schedule", db=db)
            made += 1
        key = f"maturity:{base}:{h.maturity_date}"
        if today >= h.maturity_date and key not in seen:
            qty = float(h.quantity)
            after = {
                "source_account_name": acct.name, "cash_currency": "IDR", "cash_amount": qty,
                "ticker": h.ticker, "quantity": qty, "price": 1.0, "platform_id": h.platform_id,
                "event_currency": "IDR", "date": h.maturity_date.isoformat(),
                "notes": "Maturity at face value", "asset_type": "bond", "fee": None, "fee_kind": None,
            }
            payload = {"operation": "add_funded_sell", "key": key, "rows": [{"before": None, "after": after}]}
            _make_proposal("add_funded_sell", payload, "schedule", db=db)
            made += 1
    return made
