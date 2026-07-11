"""
Portfolio recompute / manual-price / staleness / cost-basis tests (Wave 0 RED targets).

These are deliberately failing red targets for later Phase-5 slices to turn green:
  - test_recompute_holding_from_events  — Plan 03 (recompute holding from portfolio_events)
  - test_manual_price_override          — Plan 03/04 (source='manual' wins as current price)
  - test_staleness_ttl                  — Plan 04 (price_cache TTL / staleness flag)
  - test_avg_cost_realized_pnl          — Plan 03 (avg-cost + realized P&L math)

Each body calls pytest.fail(...) so the downstream RED->GREEN transition is visible
(these are real failing targets, NOT skips). DB-touching stubs reuse the module-level
db_available / db_session fixtures (mirrors test_write_tools.py) so they degrade to a
skip when Postgres is down once the real assertions land.
"""

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
# Red targets — filled in by Plan 03/04
# ---------------------------------------------------------------------------

def _random_ticker() -> str:
    import random
    return f"TSTPF{random.randint(100000, 999999)}"


def _add_event(db, ticker, event_type, quantity, price, day):
    """Insert a portfolio_events row directly (bypasses writes.py so the
    recompute algorithm is tested in isolation from the audit/apply path)."""
    import datetime as _dt
    from decimal import Decimal
    from backend.models import PortfolioEvent
    ev = PortfolioEvent(
        date=_dt.date(2024, 1, day),
        ticker=ticker,
        event_type=event_type,
        quantity=Decimal(str(quantity)),
        price=Decimal(str(price)),
    )
    db.add(ev)
    db.commit()
    return ev


def _cleanup_ticker(db, ticker):
    from backend.models import PortfolioEvent, Holding
    db.query(PortfolioEvent).filter(PortfolioEvent.ticker == ticker).delete()
    db.query(Holding).filter(Holding.ticker == ticker).delete()
    db.commit()


def test_recompute_holding_from_events(db_session):
    """D-01: portfolio_events is the source of truth. Scanning the ledger in
    date order derives quantity + avg_cost and upserts the holdings row.
    """
    from decimal import Decimal
    from backend.portfolio import recompute_holding_from_events
    from backend.models import Holding

    # --- Case 1: single buy ------------------------------------------------
    t1 = _random_ticker()
    try:
        _add_event(db_session, t1, "buy", 10, 100, 1)
        r = recompute_holding_from_events(db_session, t1)
        db_session.commit()
        assert r["quantity"] == Decimal("10")
        assert r["avg_cost"] == Decimal("100")
        assert r["realized_pnl"] == Decimal("0")
        h = db_session.query(Holding).filter(Holding.ticker == t1).one()
        assert h.quantity == Decimal("10")
        assert h.avg_cost == Decimal("100")
    finally:
        _cleanup_ticker(db_session, t1)

    # --- Case 2: two buys at different prices -> weighted avg -------------
    t2 = _random_ticker()
    try:
        _add_event(db_session, t2, "buy", 10, 100, 1)
        _add_event(db_session, t2, "buy", 10, 200, 2)
        r = recompute_holding_from_events(db_session, t2)
        db_session.commit()
        assert r["quantity"] == Decimal("20")
        assert r["avg_cost"] == Decimal("150")
        assert r["realized_pnl"] == Decimal("0")
    finally:
        _cleanup_ticker(db_session, t2)

    # --- Case 3: dividend folds into realized only -----------------------
    t3 = _random_ticker()
    try:
        _add_event(db_session, t3, "buy", 10, 100, 1)
        _add_event(db_session, t3, "dividend", 1, 500, 2)  # quantity=1, price=amount
        r = recompute_holding_from_events(db_session, t3)
        db_session.commit()
        assert r["quantity"] == Decimal("10")       # qty unchanged by dividend
        assert r["avg_cost"] == Decimal("100")      # avg_cost unchanged by dividend
        assert r["realized_pnl"] == Decimal("500")
        assert r["dividend_total"] == Decimal("500")
    finally:
        _cleanup_ticker(db_session, t3)

    # --- Case 4: sell the full position -> qty 0, row retained (D-04) -----
    t4 = _random_ticker()
    try:
        _add_event(db_session, t4, "buy", 10, 100, 1)
        _add_event(db_session, t4, "sell", 10, 250, 2)
        r = recompute_holding_from_events(db_session, t4)
        db_session.commit()
        assert r["quantity"] == Decimal("0")
        h = db_session.query(Holding).filter(Holding.ticker == t4).one_or_none()
        assert h is not None
        assert h.quantity == Decimal("0")
    finally:
        _cleanup_ticker(db_session, t4)


def test_manual_price_override():
    pytest.fail("not yet implemented — Plan 03/04 fills this")


def test_staleness_ttl():
    pytest.fail("not yet implemented — Plan 03/04 fills this")


def test_avg_cost_realized_pnl(db_session):
    """D-02: a SELL realizes (sell_price − avg_cost) × sold_qty and leaves
    avg_cost UNCHANGED. Verified across BOTH a profitable and a losing sell,
    plus the unrealized_pnl calculator including the no-price (None) case.
    """
    from decimal import Decimal
    from backend.portfolio import recompute_holding_from_events, unrealized_pnl

    # --- Profitable partial sell: buy 10 @ 100, sell 4 @ 250 -------------
    t1 = _random_ticker()
    try:
        _add_event(db_session, t1, "buy", 10, 100, 1)
        _add_event(db_session, t1, "sell", 4, 250, 2)
        r = recompute_holding_from_events(db_session, t1)
        db_session.commit()
        assert r["quantity"] == Decimal("6")
        assert r["avg_cost"] == Decimal("100")          # UNCHANGED by the sell (D-02)
        assert r["realized_pnl"] == Decimal("600")      # (250 − 100) × 4
    finally:
        _cleanup_ticker(db_session, t1)

    # --- Losing partial sell: buy 10 @ 100, sell 4 @ 60 -----------------
    t2 = _random_ticker()
    try:
        _add_event(db_session, t2, "buy", 10, 100, 1)
        _add_event(db_session, t2, "sell", 4, 60, 2)
        r = recompute_holding_from_events(db_session, t2)
        db_session.commit()
        assert r["quantity"] == Decimal("6")
        assert r["avg_cost"] == Decimal("100")          # STILL unchanged on a loss
        assert r["realized_pnl"] == Decimal("-160")     # (60 − 100) × 4
    finally:
        _cleanup_ticker(db_session, t2)

    # --- unrealized_pnl calculator: (current − avg_cost) × qty -----------
    assert unrealized_pnl(Decimal("120"), Decimal("100"), Decimal("6")) == Decimal("120")
    assert unrealized_pnl(Decimal("80"), Decimal("100"), Decimal("6")) == Decimal("-120")
    # No price yet -> unrealized is None (Plan 04 backfills live prices)
    assert unrealized_pnl(None, Decimal("100"), Decimal("6")) is None
