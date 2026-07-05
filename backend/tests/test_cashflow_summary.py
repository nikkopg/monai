"""
Cashflow summary aggregation tests — CASH-01/02/03.

Pins the aggregation-layer behavior of the two new read tools this phase adds
to backend/tools.py: monthly_trend() (CASH-02, >=6-month rolling window) and
account_balances() (CASH-03/D-04, per-account current_balance + period_net).

These tests exercise tools.py directly, not the HTTP endpoint (that's Plan 03).

Reuses the db_available/db_session fixtures and _make_account/_make_transaction
seed-row helper style from test_write_tools.py — no new fixture machinery.
"""

import datetime

import pytest

from sqlalchemy import text


# ---------------------------------------------------------------------------
# DB fixture — skip if Postgres not available (mirrors test_write_tools.py)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def db_available():
    from backend.db import engine
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception as e:
        pytest.skip(f"Postgres not available: {e}")
    return True


@pytest.fixture()
def db_session(db_available):
    """Return a live SQLAlchemy session; roll back after each test."""
    from backend.db import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Seed-row helpers (mirrors test_write_tools.py _make_transaction/_make_account)
# ---------------------------------------------------------------------------

def _make_transaction(db, *, date=None, amount=-50000, account_id=None, is_transfer=False) -> int:
    """Insert a minimal transaction row; return its id."""
    from backend.models import Transaction
    tx = Transaction(
        date=date or datetime.datetime(2024, 1, 15, 12, 0, 0),
        amount=amount,
        currency="IDR",
        category="Food",
        merchant="Test Merchant",
        account_id=account_id,
        is_transfer=is_transfer,
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)
    return tx.id


def _make_account(db, name: str = "Test Account CFS") -> int:
    from backend.models import Account
    # Clean up leftover from a prior run
    existing = db.query(Account).filter(Account.name == name).first()
    if existing:
        db.delete(existing)
        db.commit()
    acc = Account(name=name, type="checking", currency="IDR")
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc.id


# ---------------------------------------------------------------------------
# CASH-02: monthly_trend() rolling >=6-month window
# ---------------------------------------------------------------------------

def test_trend_covers_six_months(db_session):
    """monthly_trend(6) returns >=6 month buckets covering a rolling window
    (Pitfall 4 guard: NOT a calendar-year bound).
    """
    from backend.tools import monthly_trend

    today = datetime.date.today()
    seeded_ids = []
    try:
        # Seed one income + one expense transaction per month for the last 6 months.
        for i in range(6):
            month_date = today.replace(day=1) - datetime.timedelta(days=30 * i)
            seeded_ids.append(
                _make_transaction(
                    db_session,
                    date=datetime.datetime(month_date.year, month_date.month, 10, 12, 0, 0),
                    amount=100000,
                )
            )
            seeded_ids.append(
                _make_transaction(
                    db_session,
                    date=datetime.datetime(month_date.year, month_date.month, 20, 12, 0, 0),
                    amount=-40000,
                )
            )

        result = monthly_trend(6)

        assert result["tool"] == "monthly_trend"
        assert len(result["rows"]) >= 6, (
            f"Expected >=6 month rows for a rolling window, got {len(result['rows'])}"
        )
        for row in result["rows"]:
            assert set(("month", "income", "expense", "net")) <= set(row.keys())
            assert isinstance(row["income"], float)
            assert isinstance(row["expense"], float)
            assert row["income"] >= 0
            assert row["expense"] >= 0
    finally:
        from backend.models import Transaction
        for tx_id in seeded_ids:
            tx = db_session.get(Transaction, tx_id)
            if tx:
                db_session.delete(tx)
        db_session.commit()


# ---------------------------------------------------------------------------
# CASH-03/D-04: account_balances() dual per-account balances
# ---------------------------------------------------------------------------

def test_account_balances(db_session):
    """account_balances(start, end) returns current_balance (all-time) that
    differs from period_net (scoped) when the account has both in-period and
    out-of-period transactions.
    """
    from backend.tools import account_balances
    from backend.models import Account, Transaction

    acc_id = _make_account(db_session, "AccBalTestCFS")
    seeded_ids = []
    try:
        # Out-of-period transaction: well before the test period window.
        seeded_ids.append(
            _make_transaction(
                db_session,
                date=datetime.datetime(2020, 1, 15, 12, 0, 0),
                amount=500000,
                account_id=acc_id,
            )
        )
        # In-period transaction.
        seeded_ids.append(
            _make_transaction(
                db_session,
                date=datetime.datetime(2024, 6, 15, 12, 0, 0),
                amount=-20000,
                account_id=acc_id,
            )
        )

        period_start = datetime.date(2024, 6, 1)
        period_end = datetime.date(2024, 7, 1)

        result = account_balances(period_start, period_end)

        assert result["tool"] == "account_balances"
        row = next((r for r in result["rows"] if r["id"] == acc_id), None)
        assert row is not None, f"Account {acc_id} missing from account_balances rows"

        assert row["current_balance"] == pytest.approx(480000.0)  # 500000 - 20000, all-time
        assert row["period_net"] == pytest.approx(-20000.0)  # only the in-period tx
        assert row["current_balance"] != row["period_net"], (
            "current_balance (all-time) must differ from period_net (scoped) "
            "when out-of-period transactions exist (CASH-03/D-04)"
        )
    finally:
        for tx_id in seeded_ids:
            tx = db_session.get(Transaction, tx_id)
            if tx:
                db_session.delete(tx)
        db_session.commit()
        acc = db_session.get(Account, acc_id)
        if acc:
            db_session.delete(acc)
            db_session.commit()


def test_account_balances_zero_transactions(db_session):
    """An account with zero transactions appears in account_balances with 0/0
    (LEFT JOIN), not omitted from the result set.
    """
    from backend.tools import account_balances
    from backend.models import Account

    acc_id = _make_account(db_session, "EmptyAccCFS")
    try:
        result = account_balances(None, None)
        row = next((r for r in result["rows"] if r["id"] == acc_id), None)
        assert row is not None
        assert row["current_balance"] == 0.0
        assert row["period_net"] == 0.0
    finally:
        acc = db_session.get(Account, acc_id)
        if acc:
            db_session.delete(acc)
            db_session.commit()


# ---------------------------------------------------------------------------
# CASH-01: dict-shape composition contract at the aggregation layer
# ---------------------------------------------------------------------------

def test_summary_totals_shape(db_session):
    """monthly_trend / account_balances return the documented {"tool", "rows"}
    dict shape, seeded with a mix of income and expense rows (CASH-01's
    payload composition contract at the aggregation layer).
    """
    from backend.tools import monthly_trend, account_balances

    acc_id = _make_account(db_session, "ShapeTestCFS")
    seeded_ids = []
    try:
        seeded_ids.append(_make_transaction(db_session, amount=200000, account_id=acc_id))
        seeded_ids.append(_make_transaction(db_session, amount=-75000, account_id=acc_id))

        trend_result = monthly_trend(6)
        assert isinstance(trend_result, dict)
        assert trend_result["tool"] == "monthly_trend"
        assert isinstance(trend_result["rows"], list)

        balances_result = account_balances(None, None)
        assert isinstance(balances_result, dict)
        assert balances_result["tool"] == "account_balances"
        assert isinstance(balances_result["rows"], list)
        for row in balances_result["rows"]:
            assert set(("id", "name", "current_balance", "period_net")) <= set(row.keys())
    finally:
        from backend.models import Transaction, Account
        for tx_id in seeded_ids:
            tx = db_session.get(Transaction, tx_id)
            if tx:
                db_session.delete(tx)
        db_session.commit()
        acc = db_session.get(Account, acc_id)
        if acc:
            db_session.delete(acc)
            db_session.commit()
