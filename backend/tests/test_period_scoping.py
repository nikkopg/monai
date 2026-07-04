"""
Regression: category spending must honor an absolute (custom) date range.

Bug: "how much did I spend on food in June 2026" returned ~60M IDR — the
all-time food total — because the query defaulted to period="all_time" instead
of scoping to June. These tests pin the deterministic contract the LLM relies
on: a custom single-month period must exclude out-of-range rows, for ANY
category (not just food), and must differ from the all-time total.

Self-contained: inserts its own rows under unique test categories and deletes
them afterward, so it does not depend on (or pollute) the user's real data.
"""

import datetime
from decimal import Decimal

import pytest

from backend.db import SessionLocal
from backend.importer import _get_or_create_account
from backend.models import Transaction
from backend.tools import resolve_period, spending_in_category

# Unique categories so ILIKE substring matching can't collide with real data.
_CAT_ALPHA = "zzscopetest-groceries"
_CAT_BETA = "zzscopetest-transit"
_CURRENCY = "IDR"


@pytest.fixture()
def seeded_scoping_data():
    """Insert known June-2026 rows plus adjacent-month rows for two categories.

    June alpha total: 10_000 + 20_000 = 30_000  (plus a May row of 500_000 outside June)
    June beta  total: 5_000 + 7_000  = 12_000   (plus a July row of 900_000 outside June)
    """
    db = SessionLocal()
    inserted_ids: list[int] = []
    try:
        acc = _get_or_create_account(db, "zzscopetest-account", _CURRENCY)
        db.flush()

        rows = [
            # (category, date, amount)  amount negative = expense
            (_CAT_ALPHA, datetime.datetime(2026, 6, 5, 9, 0), Decimal("-10000")),
            (_CAT_ALPHA, datetime.datetime(2026, 6, 20, 9, 0), Decimal("-20000")),
            (_CAT_ALPHA, datetime.datetime(2026, 5, 15, 9, 0), Decimal("-500000")),  # out of June
            (_CAT_BETA, datetime.datetime(2026, 6, 10, 9, 0), Decimal("-5000")),
            (_CAT_BETA, datetime.datetime(2026, 6, 30, 9, 0), Decimal("-7000")),  # June 30 must count
            (_CAT_BETA, datetime.datetime(2026, 7, 1, 9, 0), Decimal("-900000")),  # out of June
        ]
        for category, when, amount in rows:
            tx = Transaction(
                date=when,
                amount=amount,
                currency=_CURRENCY,
                category=category,
                raw_category=category,
                merchant="scopetest",
                notes=None,
                account_id=acc.id,
                is_transfer=False,
            )
            db.add(tx)
            db.flush()
            inserted_ids.append(tx.id)
        db.commit()
        yield
    finally:
        # Clean up only the rows this test inserted.
        cleanup = SessionLocal()
        try:
            cleanup.query(Transaction).filter(
                Transaction.id.in_(inserted_ids)
            ).delete(synchronize_session=False)
            cleanup.commit()
        finally:
            cleanup.close()
        db.close()


def test_custom_june_range_is_half_open_and_inclusive():
    """resolve_period('custom', June 1, June 30) covers all of June, exclusive
    of July 1 — so a June-30 transaction is counted and a July-1 one is not."""
    s, e = resolve_period("custom", "2026-06-01", "2026-06-30")
    assert s == datetime.date(2026, 6, 1)
    assert e == datetime.date(2026, 7, 1)  # end made exclusive → June 30 included


def test_custom_month_scopes_category_and_excludes_other_months(seeded_scoping_data):
    """A custom single-month period returns only that month's spend for the
    category, not the all-time total (the exact 60M bug)."""
    june = spending_in_category(
        _CAT_ALPHA, period="custom", start_date="2026-06-01", end_date="2026-06-30"
    )["total"]
    all_time = spending_in_category(_CAT_ALPHA, period="all_time")["total"]

    assert june == pytest.approx(30000.0)
    # all-time includes the 500k May row → strictly larger than the June scope.
    assert all_time == pytest.approx(530000.0)
    assert june < all_time


def test_custom_month_scopes_a_second_category_independently(seeded_scoping_data):
    """The same custom-period scoping must work for any other category, and the
    June-30 boundary row must be counted while the July-1 row is excluded."""
    june = spending_in_category(
        _CAT_BETA, period="custom", start_date="2026-06-01", end_date="2026-06-30"
    )["total"]
    all_time = spending_in_category(_CAT_BETA, period="all_time")["total"]

    assert june == pytest.approx(12000.0)  # 5k + 7k (June 30 included)
    assert all_time == pytest.approx(912000.0)  # + the 900k July row
    assert june < all_time
