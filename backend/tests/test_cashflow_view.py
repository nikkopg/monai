"""
Nyquist Wave 0 scaffold for Phase 12 (ACCT-03) — cashflow_transactions view.

Encodes Criterion 2 (view excludes investment-account rows, keeps
NULL-account_id rows, and the raw-vs-view double-count delta equals the
investment-account expense magnitude), plus a tools-level exclusion check
that gates Plan 03.

All four tests run against the LIVE dev DB via the `backend.db.engine`
singleton. Tests 1-3 query `cashflow_transactions`, which does not exist
until migration 010 (Plan 02) — they fail at query time ("relation
cashflow_transactions does not exist"), which is the intended RED, never a
collection error. Test 4 stays RED until Plan 03 switches tools.py's
spending_total onto the view.
"""

from sqlalchemy import text

from backend.db import engine


def test_view_excludes_investment():
    """No investment-account row ever appears in cashflow_transactions."""
    with engine.connect() as conn:
        count = conn.execute(
            text(
                "SELECT COUNT(*) FROM cashflow_transactions ct "
                "JOIN accounts a ON a.id = ct.account_id "
                "WHERE a.type = 'investment'"
            )
        ).scalar()
    assert count == 0


def test_view_keeps_null_account():
    """NULL-account_id rows are preserved by the view (NOT EXISTS, not a
    bare NOT IN / inner join, which would silently drop them — T-12-02)."""
    with engine.connect() as conn:
        raw_null = conn.execute(
            text("SELECT COUNT(*) FROM transactions WHERE account_id IS NULL")
        ).scalar()
        view_null = conn.execute(
            text("SELECT COUNT(*) FROM cashflow_transactions WHERE account_id IS NULL")
        ).scalar()
    assert raw_null == view_null


def test_double_count_delta():
    """raw_spending - view_spending == investment_expense, derived live
    (never hard-coded) — the ~45.9M "Investments" phantom removed by
    construction."""
    with engine.connect() as conn:
        raw = conn.execute(
            text(
                "SELECT COALESCE(SUM(-amount), 0) FROM transactions "
                "WHERE amount < 0 AND is_transfer = false"
            )
        ).scalar()
        view = conn.execute(
            text(
                "SELECT COALESCE(SUM(-amount), 0) FROM cashflow_transactions "
                "WHERE amount < 0 AND is_transfer = false"
            )
        ).scalar()
        inv = conn.execute(
            text(
                "SELECT COALESCE(SUM(-amount), 0) FROM transactions t "
                "JOIN accounts a ON a.id = t.account_id "
                "WHERE a.type = 'investment' AND t.amount < 0 AND t.is_transfer = false"
            )
        ).scalar()
    assert raw - view == inv


def test_tools_spending_excludes_investment():
    """Tools-level exclusion: spending_total must equal the view-computed
    total (i.e. exclude investment-account expenses). RED until Plan 03
    switches tools.py's spending_total onto cashflow_transactions — kept as
    a distinct node id so Plan 02 does not need it green."""
    from backend import tools

    with engine.connect() as conn:
        view_total = conn.execute(
            text(
                "SELECT COALESCE(SUM(-amount), 0) FROM cashflow_transactions "
                "WHERE amount < 0 AND is_transfer = false"
            )
        ).scalar()

    tools_total = tools.spending_total(period="all_time")["total"]
    assert tools_total == float(view_total)
