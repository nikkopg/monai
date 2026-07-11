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


def _make_platform(db, name: str) -> int:
    """Insert (or reuse) a platforms row; return its id. Position identity now
    requires a platform_id on every holding/event (Quick 260711-rb2)."""
    from backend.models import Platform
    existing = db.query(Platform).filter(Platform.name == name).first()
    if existing:
        return existing.id
    plat = Platform(name=name, kind="brokerage")
    db.add(plat)
    db.commit()
    db.refresh(plat)
    return plat.id


def _add_event(db, ticker, event_type, quantity, price, day, platform_id):
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
        platform_id=platform_id,
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

    plat = _make_platform(db_session, "TestPortfolioPlatform")

    # --- Case 1: single buy ------------------------------------------------
    t1 = _random_ticker()
    try:
        _add_event(db_session, t1, "buy", 10, 100, 1, plat)
        r = recompute_holding_from_events(db_session, t1, plat)
        db_session.commit()
        assert r["quantity"] == Decimal("10")
        assert r["avg_cost"] == Decimal("100")
        assert r["realized_pnl"] == Decimal("0")
        h = db_session.query(Holding).filter(Holding.ticker == t1).one()
        assert h.quantity == Decimal("10")
        assert h.avg_cost == Decimal("100")
        assert h.platform_id == plat
    finally:
        _cleanup_ticker(db_session, t1)

    # --- Case 2: two buys at different prices -> weighted avg -------------
    t2 = _random_ticker()
    try:
        _add_event(db_session, t2, "buy", 10, 100, 1, plat)
        _add_event(db_session, t2, "buy", 10, 200, 2, plat)
        r = recompute_holding_from_events(db_session, t2, plat)
        db_session.commit()
        assert r["quantity"] == Decimal("20")
        assert r["avg_cost"] == Decimal("150")
        assert r["realized_pnl"] == Decimal("0")
    finally:
        _cleanup_ticker(db_session, t2)

    # --- Case 3: dividend folds into realized only -----------------------
    t3 = _random_ticker()
    try:
        _add_event(db_session, t3, "buy", 10, 100, 1, plat)
        _add_event(db_session, t3, "dividend", 1, 500, 2, plat)  # quantity=1, price=amount
        r = recompute_holding_from_events(db_session, t3, plat)
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
        _add_event(db_session, t4, "buy", 10, 100, 1, plat)
        _add_event(db_session, t4, "sell", 10, 250, 2, plat)
        r = recompute_holding_from_events(db_session, t4, plat)
        db_session.commit()
        assert r["quantity"] == Decimal("0")
        h = db_session.query(Holding).filter(Holding.ticker == t4).one_or_none()
        assert h is not None
        assert h.quantity == Decimal("0")
    finally:
        _cleanup_ticker(db_session, t4)


def test_recompute_holding_per_position_independent(db_session):
    """Quick 260711-rb2: same ticker on two platforms are independent
    positions — recomputing one does NOT touch the other's qty/avg_cost."""
    from decimal import Decimal
    from backend.portfolio import recompute_holding_from_events
    from backend.models import Holding

    plat_a = _make_platform(db_session, "MultiPlatformA")
    plat_b = _make_platform(db_session, "MultiPlatformB")
    ticker = _random_ticker()
    try:
        _add_event(db_session, ticker, "buy", 10, 100, 1, plat_a)
        _add_event(db_session, ticker, "buy", 5, 300, 1, plat_b)

        ra = recompute_holding_from_events(db_session, ticker, plat_a)
        rb = recompute_holding_from_events(db_session, ticker, plat_b)
        db_session.commit()

        assert ra["quantity"] == Decimal("10")
        assert ra["avg_cost"] == Decimal("100")
        assert rb["quantity"] == Decimal("5")
        assert rb["avg_cost"] == Decimal("300")

        ha = (
            db_session.query(Holding)
            .filter(Holding.ticker == ticker, Holding.platform_id == plat_a)
            .one()
        )
        hb = (
            db_session.query(Holding)
            .filter(Holding.ticker == ticker, Holding.platform_id == plat_b)
            .one()
        )
        assert ha.quantity == Decimal("10") and ha.avg_cost == Decimal("100")
        assert hb.quantity == Decimal("5") and hb.avg_cost == Decimal("300")

        # Recomputing plat_a again must not disturb plat_b's position.
        _add_event(db_session, ticker, "buy", 10, 200, 2, plat_a)
        recompute_holding_from_events(db_session, ticker, plat_a)
        db_session.commit()

        db_session.expire_all()
        hb_after = (
            db_session.query(Holding)
            .filter(Holding.ticker == ticker, Holding.platform_id == plat_b)
            .one()
        )
        assert hb_after.quantity == Decimal("5")
        assert hb_after.avg_cost == Decimal("300")
    finally:
        _cleanup_ticker(db_session, ticker)


def _cleanup_prices(db, ticker):
    from backend.models import PriceCache
    db.query(PriceCache).filter(PriceCache.ticker == ticker).delete()
    db.commit()


def test_manual_price_override(db_session):
    """INV-04/D-11: apply_set_price writes source='manual' and the summary's P&L
    for that holding immediately uses it (newest price_cache row wins)."""
    from decimal import Decimal
    from backend.writes import apply_set_price
    from backend.portfolio import portfolio_summary, recompute_holding_from_events

    plat = _make_platform(db_session, "TestManualPricePlatform")
    t = _random_ticker()
    try:
        _add_event(db_session, t, "buy", 10, 100, 1, plat)  # avg_cost 100, qty 10
        recompute_holding_from_events(db_session, t, plat)
        db_session.commit()

        row = apply_set_price(db_session, t, 150)
        db_session.commit()
        assert row.source == "manual"
        assert row.price == Decimal("150")

        summary = portfolio_summary(db_session)
        hrow = next(
            h for g in summary["groups"] for h in g["holdings"] if h["ticker"] == t
        )
        assert hrow["current_price"] == Decimal("150")
        assert hrow["price_source"] == "manual"
        # unrealized = (150 − 100) × 10 = 500
        assert hrow["unrealized_pnl"] == Decimal("500")
        assert hrow["is_stale"] is False  # just written → fresh
    finally:
        _cleanup_prices(db_session, t)
        _cleanup_ticker(db_session, t)


def test_staleness_ttl(db_session):
    """INV-05: a price_cache row older than its asset-type TTL surfaces
    is_stale=True in the summary; a fresh one is is_stale=False."""
    import datetime as _dt
    from decimal import Decimal
    from backend.models import Holding, PriceCache
    from backend.portfolio import portfolio_summary

    plat = _make_platform(db_session, "TestStalenessPlatform")
    t = _random_ticker()
    try:
        # crypto holding; crypto TTL is 5 min
        db_session.add(Holding(ticker=t, quantity=Decimal("1"), avg_cost=Decimal("100"),
                               currency="IDR", asset_type="crypto", platform_id=plat))
        stale_at = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=1)
        db_session.add(PriceCache(ticker=t, price=Decimal("200"), currency="IDR",
                                  source="coingecko", fetched_at=stale_at))
        db_session.commit()

        hrow = next(
            h for g in portfolio_summary(db_session)["groups"]
            for h in g["holdings"] if h["ticker"] == t
        )
        assert hrow["is_stale"] is True

        # A fresh row flips it back to False.
        db_session.add(PriceCache(ticker=t, price=Decimal("210"), currency="IDR",
                                  source="manual",
                                  fetched_at=_dt.datetime.now(_dt.timezone.utc)))
        db_session.commit()
        hrow = next(
            h for g in portfolio_summary(db_session)["groups"]
            for h in g["holdings"] if h["ticker"] == t
        )
        assert hrow["is_stale"] is False
    finally:
        _cleanup_prices(db_session, t)
        _cleanup_ticker(db_session, t)


def test_avg_cost_realized_pnl(db_session):
    """D-02: a SELL realizes (sell_price − avg_cost) × sold_qty and leaves
    avg_cost UNCHANGED. Verified across BOTH a profitable and a losing sell,
    plus the unrealized_pnl calculator including the no-price (None) case.
    """
    from decimal import Decimal
    from backend.portfolio import recompute_holding_from_events, unrealized_pnl

    plat = _make_platform(db_session, "TestAvgCostPlatform")

    # --- Profitable partial sell: buy 10 @ 100, sell 4 @ 250 -------------
    t1 = _random_ticker()
    try:
        _add_event(db_session, t1, "buy", 10, 100, 1, plat)
        _add_event(db_session, t1, "sell", 4, 250, 2, plat)
        r = recompute_holding_from_events(db_session, t1, plat)
        db_session.commit()
        assert r["quantity"] == Decimal("6")
        assert r["avg_cost"] == Decimal("100")          # UNCHANGED by the sell (D-02)
        assert r["realized_pnl"] == Decimal("600")      # (250 − 100) × 4
    finally:
        _cleanup_ticker(db_session, t1)

    # --- Losing partial sell: buy 10 @ 100, sell 4 @ 60 -----------------
    t2 = _random_ticker()
    try:
        _add_event(db_session, t2, "buy", 10, 100, 1, plat)
        _add_event(db_session, t2, "sell", 4, 60, 2, plat)
        r = recompute_holding_from_events(db_session, t2, plat)
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
