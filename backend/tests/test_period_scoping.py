"""
Regression: category spending must honor an absolute (custom) date range.

Bug: "how much did I spend on food in June 2026" returned the all-time food
total because the query defaulted to period="all_time" instead of scoping to
June. These tests pin the deterministic contract the LLM relies
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
    from backend.models import Category

    db = SessionLocal()
    inserted_ids: list[int] = []
    category_ids: list[int] = []
    try:
        acc = _get_or_create_account(db, "zzscopetest-account")
        db.flush()

        # spending_in_category is hierarchy-backed (11-04): each test category
        # must exist as a categories node, and transactions carry category_id.
        cat_ids: dict[str, int] = {}
        for name in (_CAT_ALPHA, _CAT_BETA):
            cat = Category(name=name, parent_id=None, kind="expense", is_system=False)
            db.add(cat)
            db.flush()
            cat_ids[name] = cat.id
            category_ids.append(cat.id)

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
                category_id=cat_ids[category],
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
            cleanup.query(Category).filter(
                Category.id.in_(category_ids)
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
    category, not the all-time total (the all-time-total bug)."""
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


# ---------------------------------------------------------------------------
# Gap closure 04-06: this_week / last_week named periods (UAT gap 1)
#
# The frontend's "This week" pill sends period=this_week, but PERIODS had no
# week entry, so resolve_period raised ValueError and the dashboard broke.
# These tests pin the ISO-Monday, half-open [monday, next_monday) contract
# without freezing the clock — they assert weekday/duration/containment
# invariants that hold on any calendar day.
# ---------------------------------------------------------------------------

def test_this_week_is_iso_monday_half_open_and_contains_today():
    """resolve_period('this_week') → [ISO Monday, next Monday), 7-day span,
    containing today. Deterministic on any day (no time freezing)."""
    s, e = resolve_period("this_week")
    assert s.weekday() == 0  # ISO Monday start
    assert (e - s).days == 7  # exactly one week, half-open
    assert s <= datetime.date.today() < e  # today falls inside the window


def test_last_week_ends_where_this_week_starts():
    """resolve_period('last_week') → the week immediately before this_week:
    its end equals this_week's start (adjacency), also ISO-Monday, 7-day."""
    tw_start, _ = resolve_period("this_week")
    s, e = resolve_period("last_week")
    assert s.weekday() == 0
    assert (e - s).days == 7
    assert e == tw_start  # last_week's end == this_week's start (no gap/overlap)


def test_this_week_is_case_insensitive():
    """resolve_period normalizes via .lower(), so THIS_WEEK == this_week —
    lock the contract the router relies on."""
    assert resolve_period("THIS_WEEK") == resolve_period("this_week")


def test_unknown_period_still_raises_valueerror_naming_the_value():
    """The ValueError fallthrough is preserved and its message names the
    offending value (the fallthrough interpolates PERIODS + the input)."""
    with pytest.raises(ValueError) as exc:
        resolve_period("fortnight")
    assert "fortnight" in str(exc.value)


# ── POL-04: "the last N months" means N full calendar months ─────────────────


def test_last_n_months_resolves_full_months():
    from backend.tools import PERIODS

    assert resolve_period("last_6_months", today=datetime.date(1996, 3, 15)) == (
        datetime.date(1995, 9, 1), datetime.date(1996, 3, 1))
    assert resolve_period("last_1_months", today=datetime.date(1996, 1, 31)) == (
        datetime.date(1995, 12, 1), datetime.date(1996, 1, 1))
    assert resolve_period("last_12_months", today=datetime.date(1996, 12, 31)) == (
        datetime.date(1995, 12, 1), datetime.date(1996, 12, 1))
    assert resolve_period("LAST_6_MONTHS", today=datetime.date(1996, 3, 15))[0] == datetime.date(1995, 9, 1)
    with pytest.raises(ValueError):
        resolve_period("last_0_months")
    with pytest.raises(ValueError):
        resolve_period("last_99999999_months")
    assert {"last_3_months", "last_6_months", "last_12_months"} <= set(PERIODS)


def _stub_trend(monkeypatch, tools_mod, *, fx_error=None):
    today = datetime.date.today()
    y, m = divmod(today.year * 12 + today.month - 1 - 6, 12)
    start = datetime.date(y, m + 1, 1)
    gap = datetime.date(y, m + 1, 1)  # the stub omits the first month
    present = start
    rows = []
    while present <= today.replace(day=1):
        if present != gap:
            rows.append({"month": present.isoformat()[:7], "income": 10.0, "expense": 5.0, "net": 5.0,
                         "unconverted_count": 0})
        present = tools_mod._first_of_next_month(present)
    monkeypatch.setattr(tools_mod, "_monthly_trend", lambda months: {
        "rows": rows, "fx_error": fx_error, "usd_rows": 0, "start": start})
    seen = []

    def cats(s, e, lim):
        seen.append((s, e, lim))
        return {"rows": [("ZZ Food", 2500.0)]}

    monkeypatch.setattr(tools_mod, "_spending_by_category", cats)
    return start, seen


def test_monthly_trend_covers_every_month_with_categories(monkeypatch):
    from backend import tools as tools_mod

    start, seen = _stub_trend(monkeypatch, tools_mod)
    r = tools_mod.monthly_trend(6)
    assert [x["month"] for x in r["rows"]] == sorted(x["month"] for x in r["rows"]) and len(r["rows"]) == 7
    first = r["rows"][0]
    assert first["month"] == start.isoformat()[:7] and (first["income"], first["expense"], first["net"]) == (0, 0, 0)
    assert all(x["top_categories"] == [("ZZ Food", 2500.0)] for x in r["rows"])
    assert len(seen) == 7 and all(lim == 5 for _, _, lim in seen)
    today = datetime.date.today()
    last_full = tools_mod.resolve_period("last_6_months")
    assert last_full[0] == start
    assert r["window"] == (f"6 full months {start.isoformat()[:7]} to "
                           f"{(last_full[1] - datetime.timedelta(days=1)).isoformat()[:7]}, "
                           f"plus {today.isoformat()[:7]} so far")
    assert len(tools_mod.monthly_trend(3)["rows"]) == 7


def test_monthly_trend_refusal_skips_categories(monkeypatch):
    from backend import tools as tools_mod

    _, seen = _stub_trend(monkeypatch, tools_mod, fx_error="ZZ no rate")
    r = tools_mod.monthly_trend(6)
    assert "error" in r and seen == []
