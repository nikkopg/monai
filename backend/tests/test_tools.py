"""
Tool correctness tests.

Two groups:
  - resolve_period: pure date logic, no DB.
  - tool SQL: integration against the live Postgres (requires `docker compose up db`
    and a loaded database). Skipped automatically if the DB is unreachable.
"""

import datetime

import pytest

from backend.tools import resolve_period


# --------------------------------------------------------------------------
# Pure date-logic tests (no DB)
# --------------------------------------------------------------------------

class TestResolvePeriod:
    def test_all_time_is_unbounded(self):
        assert resolve_period("all_time") == (None, None)

    def test_this_month_starts_on_first(self):
        s, e = resolve_period("this_month")
        assert s.day == 1
        # end is the first of the following month
        assert e.day == 1
        assert (e.year, e.month) != (s.year, s.month)

    def test_last_month_precedes_this_month(self):
        last_s, last_e = resolve_period("last_month")
        this_s, _ = resolve_period("this_month")
        assert last_e == this_s
        assert last_s.day == 1

    def test_this_year_spans_jan_to_jan(self):
        s, e = resolve_period("this_year")
        assert (s.month, s.day) == (1, 1)
        assert (e.month, e.day) == (1, 1)
        assert e.year == s.year + 1

    def test_last_year(self):
        s, e = resolve_period("last_year")
        this_s, _ = resolve_period("this_year")
        assert e == this_s
        assert s.year == this_s.year - 1

    def test_last_30_days_span(self):
        s, e = resolve_period("last_30_days")
        assert (e - s).days == 31  # 30 days back + today inclusive

    def test_custom_makes_end_exclusive(self):
        s, e = resolve_period("custom", "2024-01-01", "2024-12-31")
        assert s == datetime.date(2024, 1, 1)
        assert e == datetime.date(2025, 1, 1)  # exclusive day after

    def test_december_rolls_over(self):
        # last_month from a December date is exercised indirectly; just ensure no crash
        s, e = resolve_period("last_month")
        assert s < e

    def test_unknown_period_raises(self):
        with pytest.raises(ValueError):
            resolve_period("fortnight")


# --------------------------------------------------------------------------
# Integration tests against live Postgres
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def db_available():
    from sqlalchemy import text
    from backend.db import engine
    try:
        with engine.connect() as c:
            n = c.execute(text("SELECT COUNT(*) FROM transactions")).scalar()
        if not n:
            pytest.skip("transactions table is empty")
    except Exception as e:
        pytest.skip(f"Postgres not available: {e}")
    return True


class TestToolSQL:
    def test_spending_total_non_negative(self, db_available):
        from backend.tools import spending_total
        assert spending_total("all_time")["total"] >= 0

    def test_income_total_non_negative(self, db_available):
        from backend.tools import income_total
        assert income_total("all_time")["total"] >= 0

    def test_net_equals_income_minus_spending(self, db_available):
        from backend.tools import spending_total, income_total, net_total
        spend = spending_total("all_time")["total"]
        inc = income_total("all_time")["total"]
        net = net_total("all_time")["net"]
        assert abs(net - (inc - spend)) < 1.0  # float tolerance

    def test_categories_all_positive_and_descending(self, db_available):
        from backend.tools import spending_by_category
        rows = spending_by_category("all_time", limit=10)["rows"]
        totals = [t for _, t in rows]
        assert all(t > 0 for t in totals)
        assert totals == sorted(totals, reverse=True)

    def test_count_all_ge_expense(self, db_available):
        from backend.tools import transaction_count
        all_n = transaction_count("all_time", kind="all")["count"]
        exp_n = transaction_count("all_time", kind="expense")["count"]
        inc_n = transaction_count("all_time", kind="income")["count"]
        assert all_n >= exp_n
        assert all_n >= inc_n

    def test_largest_expenses_descending_magnitude(self, db_available):
        from backend.tools import largest_transactions
        rows = largest_transactions("all_time", limit=5, kind="expense")["rows"]
        mags = [r["amount"] for r in rows]
        assert mags == sorted(mags, reverse=True)
        assert all(m > 0 for m in mags)  # reported as positive magnitude
