"""SBN retail government bonds (ORI, SBR, ST, SR) with a monthly coupon (quick 261117-rw1).

An SBN is held to maturity and valued at face: quantity is the nominal in IDR and the unit
price is 1. Its terms live on the holding (rate, floating flag, pay day, maturity, tax %,
coupon account). Each month it pays

    gross = round_half_up(nominal x rate / 100 / 12)
    tax   = round_half_up(gross x tax_pct / 100)
    net   = gross - tax

in whole rupiah. The pay day is 1..28: every SBN series pays on the 10th or the 15th, so no
month-end clamping is ever needed.

Pure functions only here (stdlib, no DB import at module level).
"""
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

_ONE = Decimal(1)


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
