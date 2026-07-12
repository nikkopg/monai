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


# ---------------------------------------------------------------------------
# value_history_series (VZ-02, INVX-01, Plan 07-04)
# ---------------------------------------------------------------------------

def _add_history_row(db, ticker, platform_id, snapshot_date, market_value, cost_basis):
    from decimal import Decimal
    from backend.models import PortfolioValueHistory
    row = PortfolioValueHistory(
        snapshot_date=snapshot_date,
        ticker=ticker,
        quantity=Decimal("1"),
        market_value=Decimal(str(market_value)),
        cost_basis=Decimal(str(cost_basis)),
        currency="IDR",
        platform_id=platform_id,
    )
    db.add(row)
    db.commit()
    return row


def _cleanup_history(db, tickers):
    from backend.models import PortfolioValueHistory
    db.query(PortfolioValueHistory).filter(PortfolioValueHistory.ticker.in_(tickers)).delete(
        synchronize_session=False
    )
    db.commit()


def test_value_history_series_aggregates_per_date(db_session):
    """Aggregation test: per-date total_market_value = Σ market_value,
    total_pnl = Σ(market_value − cost_basis), summed across positions on the
    same day (including a second ticker so the Σ is exercised). Asserted as a
    DELTA (before vs. after inserting fixture rows) so the test is robust to
    other pre-existing portfolio_value_history rows already in this DB — the
    function itself aggregates ALL rows for a date by design (whole-portfolio
    view, no ticker filter)."""
    import datetime as _dt
    from decimal import Decimal
    from backend.portfolio import value_history_series

    plat = _make_platform(db_session, "TestHistoryPlatform")
    t1, t2 = _random_ticker(), _random_ticker()
    try:
        d1 = _dt.date.today() - _dt.timedelta(days=2)
        d2 = _dt.date.today() - _dt.timedelta(days=1)
        d3 = _dt.date.today()

        before = {p["date"]: p for p in value_history_series(db_session, "All")}
        zero = {"total_market_value": Decimal("0"), "total_pnl": Decimal("0")}

        _add_history_row(db_session, t1, plat, d1, "1000", "800")
        _add_history_row(db_session, t1, plat, d2, "1100", "800")
        _add_history_row(db_session, t2, plat, d2, "500", "600")  # same day as t1's 2nd row
        _add_history_row(db_session, t1, plat, d3, "1200", "800")

        after = {p["date"]: p for p in value_history_series(db_session, "All")}

        def delta(d, field):
            return after[d][field] - before.get(d, zero)[field]

        assert delta(d1, "total_market_value") == Decimal("1000")
        assert delta(d1, "total_pnl") == Decimal("200")  # 1000 - 800

        # d2 sums BOTH t1 and t2's rows
        assert delta(d2, "total_market_value") == Decimal("1600")   # 1100 + 500
        assert delta(d2, "total_pnl") == Decimal("200")             # (1100-800) + (500-600)

        assert delta(d3, "total_market_value") == Decimal("1200")
        assert delta(d3, "total_pnl") == Decimal("400")  # 1200 - 800

        # Points are sorted ascending by date.
        assert [p["date"] for p in after.values()] == sorted(after)
    finally:
        _cleanup_history(db_session, [t1, t2])


def test_value_history_series_range_filter(db_session):
    """Range filter trims by snapshot_date; a bad range raises ValueError."""
    import datetime as _dt
    from backend.portfolio import value_history_series

    plat = _make_platform(db_session, "TestHistoryRangePlatform")
    t = _random_ticker()
    try:
        old_date = _dt.date.today() - _dt.timedelta(days=200)
        recent_date = _dt.date.today() - _dt.timedelta(days=5)
        _add_history_row(db_session, t, plat, old_date, "100", "80")
        _add_history_row(db_session, t, plat, recent_date, "110", "80")

        series_1m = value_history_series(db_session, "1M")
        dates_1m = {p["date"] for p in series_1m}
        assert recent_date in dates_1m
        assert old_date not in dates_1m

        series_all = value_history_series(db_session, "All")
        dates_all = {p["date"] for p in series_all}
        assert old_date in dates_all and recent_date in dates_all

        with pytest.raises(ValueError):
            value_history_series(db_session, "not-a-range")
    finally:
        _cleanup_history(db_session, [t])


def test_value_history_series_empty_is_graceful(db_session):
    """No-backfill (D-13): an empty portfolio_value_history returns an empty
    series, not an error, for a range with no matching rows."""
    from backend.portfolio import value_history_series

    t = _random_ticker()  # never inserted -> no rows for this ticker anywhere
    series = value_history_series(db_session, "1M")
    assert isinstance(series, list)
    assert all(p["date"] for p in series)  # sanity: doesn't blow up on real data
    # A ticker that was never seeded contributes nothing — assert isolation
    # by checking the random ticker's own history is empty via a direct query.
    from backend.models import PortfolioValueHistory
    rows = db_session.query(PortfolioValueHistory).filter(
        PortfolioValueHistory.ticker == t
    ).all()
    assert rows == []


# ---------------------------------------------------------------------------
# FX-aware valuation, cash, gold, currency-mismatch, None-propagation
# (Plan 07-02: FX-03, CG-01, CG-02, CG-03)
# ---------------------------------------------------------------------------

def _add_event_ccy(db, ticker, event_type, quantity, price, day, platform_id, currency):
    """Like _add_event but stamps a currency (FX-04)."""
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
        currency=currency,
    )
    db.add(ev)
    db.commit()
    return ev


def test_recompute_fx_converts_native_cost_to_idr_at_trade_date_rate(db_session, monkeypatch):
    """FX-03: a USD buy converts to IDR at the trade-date rate; total_cost/
    avg_cost land in IDR, exact Decimal (no float drift): 200 USD-cost qty=1
    at rate 15800 -> 3160000 IDR total_cost/avg_cost."""
    from decimal import Decimal
    from backend import portfolio as portfolio_mod

    plat = _make_platform(db_session, "TestFxPlatform")
    t = _random_ticker()

    def fake_get_rate(base, quote, as_of, db):
        assert base == "USD" and quote == "IDR"
        return Decimal("15800")

    monkeypatch.setattr(portfolio_mod.fx, "get_rate", fake_get_rate)
    try:
        _add_event_ccy(db_session, t, "buy", 1, 200, 1, plat, "USD")
        r = portfolio_mod.recompute_holding_from_events(db_session, t, plat)
        db_session.commit()
        assert r["quantity"] == Decimal("1")
        assert r["avg_cost"] == Decimal("3160000")  # 200 * 15800, exact
    finally:
        _cleanup_ticker(db_session, t)


def test_recompute_fx_d02_invariant_preserved_across_partial_sell(db_session, monkeypatch):
    """D-02 preserved under FX conversion: a partial sell leaves avg_cost
    unchanged (only qty/total_cost drop by avg_cost×sold_qty)."""
    from decimal import Decimal
    from backend import portfolio as portfolio_mod

    plat = _make_platform(db_session, "TestFxD02Platform")
    t = _random_ticker()

    def fake_get_rate(base, quote, as_of, db):
        return Decimal("15000")

    monkeypatch.setattr(portfolio_mod.fx, "get_rate", fake_get_rate)
    try:
        _add_event_ccy(db_session, t, "buy", 10, 100, 1, plat, "USD")  # avg_cost 100*15000=1500000
        r_before = portfolio_mod.recompute_holding_from_events(db_session, t, plat)
        db_session.commit()
        assert r_before["avg_cost"] == Decimal("1500000")

        _add_event_ccy(db_session, t, "sell", 4, 200, 2, plat, "USD")
        r_after = portfolio_mod.recompute_holding_from_events(db_session, t, plat)
        db_session.commit()
        assert r_after["quantity"] == Decimal("6")
        assert r_after["avg_cost"] == r_before["avg_cost"]  # UNCHANGED by the sell
    finally:
        _cleanup_ticker(db_session, t)


def test_recompute_fx_none_propagates_never_fabricates_rate(db_session, monkeypatch):
    """A failed FX lookup (vendor outage/gap) makes the recompute result None,
    never a fabricated rate=1.0."""
    from backend import portfolio as portfolio_mod

    plat = _make_platform(db_session, "TestFxNonePlatform")
    t = _random_ticker()

    def fake_get_rate(base, quote, as_of, db):
        return None

    monkeypatch.setattr(portfolio_mod.fx, "get_rate", fake_get_rate)
    try:
        _add_event_ccy(db_session, t, "buy", 10, 100, 1, plat, "USD")
        r = portfolio_mod.recompute_holding_from_events(db_session, t, plat)
        db_session.commit()
        assert r["quantity"] is None
        assert r["avg_cost"] is None
    finally:
        _cleanup_ticker(db_session, t)


def test_summary_realized_pnl_fx_converted_for_non_idr_position(db_session, monkeypatch):
    """CR-01 regression: portfolio_summary's realized_pnl for a USD position must
    be FX-converted to IDR, not the raw native magnitude.

    Buy 10 @ 100 USD then sell 4 @ 200 USD, both at rate 15000:
      avg_cost = 100 * 15000 = 1_500_000 IDR/unit
      realized = (200*15000 - 1_500_000) * 4 = 1_500_000 * 4 = 6_000_000 IDR
    The pre-fix bug (native sum) would report (200-100)*4 = 400 — the assertion
    below fails loudly on that regression.
    """
    from decimal import Decimal
    from backend import portfolio as portfolio_mod

    plat = _make_platform(db_session, "TestRealizedFxPlatform")
    t = _random_ticker()

    def fake_get_rate(base, quote, as_of, db):
        # portfolio_summary converts realized P&L for EVERY holding now, so
        # unrelated IDR holdings in the shared DB call get_rate("IDR","IDR") —
        # model real get_rate's base==quote identity short-circuit.
        if base == quote:
            return Decimal("1")
        assert base == "USD" and quote == "IDR"
        return Decimal("15000")

    monkeypatch.setattr(portfolio_mod.fx, "get_rate", fake_get_rate)
    try:
        _add_event_ccy(db_session, t, "buy", 10, 100, 1, plat, "USD")
        _add_event_ccy(db_session, t, "sell", 4, 200, 2, plat, "USD")
        # recompute creates the Holding row so portfolio_summary iterates it.
        portfolio_mod.recompute_holding_from_events(db_session, t, plat)
        db_session.commit()

        summary = portfolio_mod.portfolio_summary(db_session)
        hrow = next(
            h for g in summary["groups"] for h in g["holdings"] if h["ticker"] == t
        )
        assert hrow["realized_pnl"] == Decimal("6000000")  # IDR, FX-converted
        assert hrow["realized_pnl"] != Decimal("400")       # NOT the raw-USD bug
    finally:
        _cleanup_ticker(db_session, t)


def test_cash_holding_values_via_fx_with_no_price_cache_row(db_session, monkeypatch):
    """CG-01: a cash holding (asset_type='cash') values as quantity ×
    fx_rate(currency, 'IDR', today) with NO price_cache row present at all —
    the special-case branch must fire, not the generic price_cache path."""
    from decimal import Decimal
    from backend.models import Holding
    from backend import portfolio as portfolio_mod

    plat = _make_platform(db_session, "TestCashPlatform")
    t = _random_ticker()

    def fake_get_rate(base, quote, as_of, db):
        # _realized_for_position now converts every holding's ledger, so
        # unrelated IDR holdings in the shared DB hit get_rate("IDR","IDR") —
        # model real get_rate's base==quote identity short-circuit.
        if base == quote:
            return Decimal("1")
        assert base == "USD" and quote == "IDR"
        return Decimal("15500")

    monkeypatch.setattr(portfolio_mod.fx, "get_rate", fake_get_rate)
    db_session.add(Holding(
        ticker=t, quantity=Decimal("100"), avg_cost=Decimal("0"),
        currency="USD", asset_type="cash", platform_id=plat,
    ))
    db_session.commit()
    try:
        # Sanity: no price_cache row exists for this ticker (special-case proof).
        from backend.models import PriceCache
        assert db_session.query(PriceCache).filter(PriceCache.ticker == t).count() == 0

        summary = portfolio_mod.portfolio_summary(db_session)
        hrow = next(
            h for g in summary["groups"] for h in g["holdings"] if h["ticker"] == t
        )
        # 100 USD * 15500 = 1550000 IDR
        assert hrow["current_value"] == Decimal("1550000")
        assert hrow["current_value"] is not None
        assert hrow["is_stale"] is False  # no false "stale" badge (INV-05)
        assert hrow["price_source"] == "fx"
    finally:
        _cleanup_ticker(db_session, t)


def test_cash_snapshot_writes_history_row_not_skipped(db_session, monkeypatch):
    """CG-01: snapshot_all_holdings writes a portfolio_value_history row for a
    cash holding today (no price_cache row needed) and does NOT skip it —
    otherwise cash never appears in Plan 04's VZ-02 line chart."""
    from decimal import Decimal
    import datetime as _dt
    from backend.models import Holding, PortfolioValueHistory
    from backend import portfolio as portfolio_mod

    plat = _make_platform(db_session, "TestCashSnapshotPlatform")
    t = _random_ticker()

    def fake_get_rate(base, quote, as_of, db):
        return Decimal("15600")

    monkeypatch.setattr(portfolio_mod.fx, "get_rate", fake_get_rate)
    db_session.add(Holding(
        ticker=t, quantity=Decimal("50"), avg_cost=Decimal("0"),
        currency="USD", asset_type="cash", platform_id=plat,
    ))
    db_session.commit()
    try:
        result = portfolio_mod.snapshot_all_holdings(db_session)
        db_session.commit()
        assert result["written"] >= 1

        row = db_session.query(PortfolioValueHistory).filter(
            PortfolioValueHistory.ticker == t,
            PortfolioValueHistory.snapshot_date == _dt.date.today(),
        ).one_or_none()
        assert row is not None
        assert row.market_value == Decimal("780000")  # 50 * 15600
    finally:
        db_session.query(PortfolioValueHistory).filter(
            PortfolioValueHistory.ticker == t
        ).delete()
        db_session.commit()
        _cleanup_ticker(db_session, t)


def test_gold_holding_full_ledger_pnl_identical_to_crypto(db_session):
    """CG-02: a gold holding gets full average-cost ledger P&L, grams ×
    per-gram price, identical to any crypto/stock position — no branch."""
    from decimal import Decimal
    from backend.portfolio import recompute_holding_from_events, portfolio_summary
    from backend.writes import apply_set_price

    plat = _make_platform(db_session, "TestGoldPlatform")
    t = _random_ticker()
    try:
        _add_event(db_session, t, "buy", 10, 1000000, 1, plat)  # 10 grams @ 1,000,000/g
        recompute_holding_from_events(db_session, t, plat)
        db_session.commit()

        from backend.models import Holding
        h = db_session.query(Holding).filter(
            Holding.ticker == t, Holding.platform_id == plat
        ).one()
        h.asset_type = "gold"
        db_session.commit()

        apply_set_price(db_session, t, 1200000, source="manual")
        db_session.commit()

        summary = portfolio_summary(db_session)
        hrow = next(
            h for g in summary["groups"] for h in g["holdings"] if h["ticker"] == t
        )
        assert hrow["current_price"] == Decimal("1200000")
        assert hrow["current_value"] == Decimal("12000000")  # 10 * 1,200,000
        assert hrow["unrealized_pnl"] == Decimal("2000000")  # (1200000-1000000)*10
        assert hrow["price_source"] == "manual"
    finally:
        _cleanup_prices(db_session, t)
        _cleanup_ticker(db_session, t)


def test_portfolio_summary_asset_type_grouping(db_session, monkeypatch):
    """VZ-01 data contract: portfolio_summary groups holdings by asset_type
    (current IDR market value per group), alongside the existing platform
    grouping."""
    from decimal import Decimal
    from backend.models import Holding
    from backend import portfolio as portfolio_mod
    from backend.writes import apply_set_price

    plat = _make_platform(db_session, "TestAssetTypeGroupPlatform")
    t_crypto = _random_ticker()
    t_cash = _random_ticker()

    def fake_get_rate(base, quote, as_of, db):
        return Decimal("15000")

    monkeypatch.setattr(portfolio_mod.fx, "get_rate", fake_get_rate)
    db_session.add(Holding(
        ticker=t_crypto, quantity=Decimal("1"), avg_cost=Decimal("100"),
        currency="IDR", asset_type="crypto", platform_id=plat,
    ))
    db_session.add(Holding(
        ticker=t_cash, quantity=Decimal("10"), avg_cost=Decimal("0"),
        currency="USD", asset_type="cash", platform_id=plat,
    ))
    db_session.commit()
    apply_set_price(db_session, t_crypto, 500, source="manual")
    db_session.commit()
    try:
        summary = portfolio_mod.portfolio_summary(db_session)
        assert "asset_type_groups" in summary
        by_type = {g["asset_type"] for g in summary["asset_type_groups"]}
        assert {"crypto", "cash"} <= by_type
        # DB is shared across tests (not isolated per-test), so assert our
        # holdings' own contribution rather than an exact group aggregate.
        crypto_row = next(
            h for g in summary["groups"] for h in g["holdings"] if h["ticker"] == t_crypto
        )
        cash_row = next(
            h for g in summary["groups"] for h in g["holdings"] if h["ticker"] == t_cash
        )
        assert crypto_row["current_value"] == Decimal("500")     # 1 * 500
        assert cash_row["current_value"] == Decimal("150000")    # 10 * 15000
    finally:
        _cleanup_prices(db_session, t_crypto)
        _cleanup_ticker(db_session, t_crypto)
        _cleanup_ticker(db_session, t_cash)
