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
from datetime import date
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
