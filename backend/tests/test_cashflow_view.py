"""
Nyquist Wave 0 scaffold for Phase 12 (ACCT-03) — cashflow_transactions view.

Encodes Criterion 2 (view excludes investment-account rows, keeps
NULL-account_id rows, and the raw-vs-view double-count delta equals the
investment-account expense magnitude), plus a tools-level exclusion check
that gates Plan 03.

D-05: the module-scoped `_seed_cashflow_rows` autouse fixture below seeds
synthetic `zz-cfv-*` rows (an investment-account expense, a liquid-account
expense, and a NULL-account expense) so these invariants are non-vacuous
against an empty database, and tears them down afterward. Each test asserts
its required seeded shape as a precondition before checking the invariant.
"""

import pytest
from sqlalchemy import text

from backend.db import engine


@pytest.fixture(scope="module", autouse=True)
def _seed_cashflow_rows():
    """Seed one investment-account expense, one liquid-account expense and
    one NULL-account expense (synthetic, D-05), then delete them by id."""
    account_ids: dict[str, int] = {}
    txn_ids: list[int] = []
    with engine.begin() as c:
        account_ids["invest"] = c.execute(
            text(
                "INSERT INTO accounts (name, type, currency) "
                "VALUES ('zz-cfv-invest', 'investment', 'IDR') RETURNING id"
            )
        ).scalar()
        account_ids["liquid"] = c.execute(
            text(
                "INSERT INTO accounts (name, type, currency) "
                "VALUES ('zz-cfv-liquid', 'liquid', 'IDR') RETURNING id"
            )
        ).scalar()
        for d, amt, account_key in (
            ("2020-02-03", -7000.00, "invest"),
            ("2020-02-04", -3000.00, "liquid"),
        ):
            txn_ids.append(
                c.execute(
                    text(
                        "INSERT INTO transactions (date, amount, currency, account_id, is_transfer) "
                        "VALUES (:d, :amt, 'IDR', :aid, false) RETURNING id"
                    ),
                    {"d": d, "amt": amt, "aid": account_ids[account_key]},
                ).scalar()
            )
        txn_ids.append(
            c.execute(
                text(
                    "INSERT INTO transactions (date, amount, currency, account_id, is_transfer) "
                    "VALUES ('2020-02-05', -2000.00, 'IDR', NULL, false) RETURNING id"
                )
            ).scalar()
        )

    yield

    with engine.begin() as c:
        c.execute(text("DELETE FROM transactions WHERE id = ANY(:ids)"), {"ids": txn_ids})
        c.execute(text("DELETE FROM accounts WHERE id = ANY(:ids)"), {"ids": list(account_ids.values())})


def _assert_seeded_shape(conn):
    """Precondition: the seeded investment-account expense and NULL-account
    row exist, so this test can never pass vacuously on an empty DB."""
    investment_expenses = conn.execute(
        text(
            "SELECT COUNT(*) FROM transactions t JOIN accounts a ON a.id = t.account_id "
            "WHERE a.type = 'investment' AND t.amount < 0 AND t.is_transfer = false"
        )
    ).scalar()
    null_account_rows = conn.execute(
        text("SELECT COUNT(*) FROM transactions WHERE account_id IS NULL")
    ).scalar()
    assert investment_expenses >= 1
    assert null_account_rows >= 1


def test_view_excludes_investment():
    """No investment-account row ever appears in cashflow_transactions."""
    with engine.connect() as conn:
        _assert_seeded_shape(conn)
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
        _assert_seeded_shape(conn)
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
        _assert_seeded_shape(conn)
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
    total (i.e. exclude investment-account expenses)."""
    from backend import tools

    with engine.connect() as conn:
        _assert_seeded_shape(conn)
        view_total = conn.execute(
            text(
                "SELECT COALESCE(SUM(-amount), 0) FROM cashflow_transactions "
                "WHERE amount < 0 AND is_transfer = false"
            )
        ).scalar()

    tools_total = tools.spending_total(period="all_time")["total"]
    assert tools_total == float(view_total)
