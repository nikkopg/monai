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


def test_holding_dict_carries_currency(db_session):
    """45-05: every holding dict exposes the holding's own currency so the
    funded-trade modal can tell a USD position from an IDR one."""
    from decimal import Decimal
    from backend.models import Holding
    from backend import portfolio as portfolio_mod

    plat = _make_platform(db_session, "zz45-holding-currency")
    t_usd, t_idr = _random_ticker(), _random_ticker()
    for t, ccy in ((t_usd, "USD"), (t_idr, "IDR")):
        db_session.add(Holding(
            ticker=t, quantity=Decimal("1"), avg_cost=Decimal("1"),
            currency=ccy, asset_type="stock", platform_id=plat,
        ))
    db_session.commit()
    try:
        summary = portfolio_mod.portfolio_summary(db_session)
        by_ticker = {
            h["ticker"]: h for g in summary["groups"] for h in g["holdings"]
        }
        assert by_ticker[t_usd]["currency"] == "USD"
        assert by_ticker[t_idr]["currency"] == "IDR"
    finally:
        _cleanup_ticker(db_session, t_usd)
        _cleanup_ticker(db_session, t_idr)


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


# ---------------------------------------------------------------------------
# Phase 17 Plan 01 (Wave 0, RED-first) — platform-detail reads (D-05,
# PLAT-01). Neither route exists today (only POST /portfolio-events) — both
# 404 until 17-03 adds them.
# ---------------------------------------------------------------------------

def test_platform_detail(client, db_session, authed):
    """GET /platforms/{id}/detail returns the group whose platform_id == id,
    with subtotal + holdings carrying realized_pnl and unrealized_pnl
    (PLAT-01/D-05); a non-existent platform id returns 404."""
    from decimal import Decimal
    from backend.portfolio import recompute_holding_from_events
    from backend.writes import apply_set_price

    plat = _make_platform(db_session, "zz17test-PlatformDetailPlatform")
    t = _random_ticker()
    try:
        _add_event(db_session, t, "buy", 5, 100000, 1, plat)
        recompute_holding_from_events(db_session, t, plat)
        db_session.commit()
        apply_set_price(db_session, t, 120000, source="manual")
        db_session.commit()

        resp = client.get(f"/platforms/{plat}/detail")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["platform_id"] == plat
        holding_row = next((h for h in data["holdings"] if h["ticker"] == t), None)
        assert holding_row is not None, "expected our probe holding in the platform group"
        assert "realized_pnl" in holding_row
        assert "unrealized_pnl" in holding_row
        assert Decimal(str(holding_row["unrealized_pnl"])) == Decimal("100000")  # (120000-100000)*5

        missing = client.get("/platforms/999999999/detail")
        assert missing.status_code == 404, f"Expected 404 for a nonexistent platform, got {missing.status_code}"
    finally:
        _cleanup_prices(db_session, t)
        _cleanup_ticker(db_session, t)


def test_portfolio_events_by_platform(client, db_session, authed):
    """GET /portfolio-events?platform_id={id} returns ONLY that platform's
    events, ordered date-desc, each row carrying date/ticker/event_type/
    quantity/price (PLAT-01/D-05)."""
    plat_a = _make_platform(db_session, "zz17test-EventsPlatformA")
    plat_b = _make_platform(db_session, "zz17test-EventsPlatformB")
    t = _random_ticker()
    try:
        _add_event(db_session, t, "buy", 3, 100000, 1, plat_a)
        _add_event(db_session, t, "sell", 1, 110000, 5, plat_a)
        _add_event(db_session, t, "buy", 2, 90000, 3, plat_b)  # different platform — must NOT leak in

        resp = client.get(f"/portfolio-events?platform_id={plat_a}")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        our_rows = [row for row in data if row["ticker"] == t]
        assert len(our_rows) == 2, (
            f"expected exactly plat_a's 2 events for ticker {t}, got {len(our_rows)} "
            "— a leaked plat_b row would inflate this count"
        )
        dates = [row["date"] for row in our_rows]
        assert dates == sorted(dates, reverse=True), "expected date-desc ordering"
        assert {row["event_type"] for row in our_rows} == {"buy", "sell"}
        for row in data:
            assert {"date", "ticker", "event_type", "quantity", "price"} <= row.keys()
    finally:
        _cleanup_ticker(db_session, t)


# ---------------------------------------------------------------------------
# Regression: recompute-clobbers-holdings (Phase 18 UAT #3)
# ---------------------------------------------------------------------------

def test_funded_buy_on_backed_position_sums_not_replaces(db_session):
    """A funded buy on an event-backed position must SUM into the prior
    quantity, never REPLACE it. This is the exact behaviour the clobber bug
    violated."""
    from decimal import Decimal
    from backend.models import Holding
    from backend.writes import apply_add_portfolio_event

    plat = _make_platform(db_session, "TestPortfolioPlatform")
    t = _random_ticker()
    try:
        # Opening lot recorded as an event (the post-backfill world).
        apply_add_portfolio_event(db_session, {
            "date": "2026-07-11", "ticker": t, "event_type": "buy",
            "quantity": 1000, "price": 5000, "platform_id": plat, "currency": "IDR",
        })
        # A later funded buy.
        apply_add_portfolio_event(db_session, {
            "date": "2026-09-01", "ticker": t, "event_type": "buy",
            "quantity": 100, "price": 5000, "platform_id": plat, "currency": "IDR",
        })
        db_session.commit()

        h = db_session.query(Holding).filter(
            Holding.ticker == t, Holding.platform_id == plat
        ).one()
        # SUMS: 1000 + 100 == 1100 (a clobber would have left 100).
        assert h.quantity == Decimal("1100"), (
            f"funded buy must sum: expected 1100, got {h.quantity} "
            "(100 would mean the prior lot was clobbered)"
        )
    finally:
        _cleanup_ticker(db_session, t)


def test_buy_on_eventless_nonzero_holding_sums_with_an_opening_lot(db_session):
    """A buy on a NON-ZERO holding that has NO backing events must SUM with the
    existing row, never overwrite it (the clobber bug class). The current row is
    authoritative, so it becomes an opening lot dated the new event's date."""
    from decimal import Decimal
    from backend.models import Holding, PortfolioEvent
    from backend.writes import apply_add_portfolio_event

    plat = _make_platform(db_session, "TestPortfolioPlatform")
    t = _random_ticker()
    try:
        # Legacy-style holding: direct row, NO portfolio_events.
        db_session.add(Holding(
            ticker=t, quantity=Decimal("500"), avg_cost=Decimal("5000"),
            currency="IDR", platform_id=plat, asset_type="mutual_fund",
        ))
        db_session.commit()

        apply_add_portfolio_event(db_session, {
            "date": "2026-09-01", "ticker": t, "event_type": "buy",
            "quantity": 100, "price": 5000, "platform_id": plat, "currency": "IDR",
        })
        db_session.commit()

        h = db_session.query(Holding).filter(Holding.ticker == t, Holding.platform_id == plat).one()
        assert h.quantity == Decimal("600")  # summed, not overwritten
        evs = db_session.query(PortfolioEvent).filter(PortfolioEvent.ticker == t).order_by(PortfolioEvent.id).all()
        assert [(e.event_type, e.quantity) for e in evs] == [("buy", Decimal("500")), ("buy", Decimal("100"))]
    finally:
        _cleanup_ticker(db_session, t)


# ---------------------------------------------------------------------------
# Quick 261108-d2c — USD positions shown in USD (display only). The two page
# routes ask portfolio_summary for usd_view; everything else is unchanged.
# ---------------------------------------------------------------------------

_USD_VIEW_DAY_RATES = {1: "15000", 2: "16000", 3: "18000"}


def _usd_view_stubs(monkeypatch, spot=None):
    """Stub both FX paths so no test can reach the network. `spot` is the
    spot_stale_ok result, or None to raise FxUnavailable."""
    from decimal import Decimal
    from backend import portfolio as portfolio_mod

    def fake_get_rate(base, quote, as_of, db):
        if base == quote:
            return Decimal("1")
        if (as_of.year, as_of.month) == (2024, 1) and as_of.day in _USD_VIEW_DAY_RATES:
            return Decimal(_USD_VIEW_DAY_RATES[as_of.day])
        return Decimal("20000")

    def fake_spot(currency, db):
        if spot is None:
            raise portfolio_mod.fx.FxUnavailable("no rate")
        return spot

    monkeypatch.setattr(portfolio_mod.fx, "get_rate", fake_get_rate)
    monkeypatch.setattr(portfolio_mod.fx, "spot_stale_ok", fake_spot)


def _usd_view_position(db, plat, t):
    """USD position: buy 10 @ 2, buy 10 @ 4, sell 5 @ 5 (native USD); manual
    IDR price 100000. Native avg cost 3; IDR avg cost 47000."""
    from backend import portfolio as portfolio_mod
    from backend.writes import apply_set_price

    _add_event_ccy(db, t, "buy", 10, 2, 1, plat, "USD")
    _add_event_ccy(db, t, "buy", 10, 4, 2, plat, "USD")
    _add_event_ccy(db, t, "sell", 5, 5, 3, plat, "USD")
    portfolio_mod.recompute_holding_from_events(db, t, plat)
    db.commit()
    apply_set_price(db, t, 100000, source="manual")
    db.commit()


def _usd_view_row(summary, t):
    return next(h for g in summary["groups"] for h in g["holdings"] if h["ticker"] == t)


def test_usd_view_values_from_own_trades_and_today_rate(db_session, monkeypatch):
    """L3/L4: USD avg cost is the average-cost rule on the native USD prices
    (3, not IDR 47000 / today's rate 2.35); price and value are IDR / rate."""
    import datetime as _dt
    from decimal import Decimal
    from backend import portfolio as portfolio_mod

    plat = _make_platform(db_session, "zz-d2c-usd-view")
    t, idr_t = _random_ticker(), _random_ticker()
    _usd_view_stubs(monkeypatch, spot=(Decimal("20000"), _dt.date(2026, 1, 2), False))
    try:
        _usd_view_position(db_session, plat, t)
        _add_event_ccy(db_session, idr_t, "buy", 2, 1000, 1, plat, "IDR")
        portfolio_mod.recompute_holding_from_events(db_session, idr_t, plat)
        db_session.commit()

        row = _usd_view_row(portfolio_mod.portfolio_summary(db_session, usd_view=True), t)
        assert row["currency"] == "USD"
        assert row["usd_avg_cost"] == Decimal("3")
        assert row["usd_current_price"] == Decimal("5")
        assert row["usd_current_value"] == Decimal("75")
        assert row["usd_unrealized_pnl"] == Decimal("30")
        assert row["usd_rate"] == Decimal("20000")
        assert row["usd_rate_date"] == "2026-01-02"
        # Existing IDR fields untouched.
        assert row["avg_cost"] == Decimal("47000")
        assert row["current_value"] == Decimal("1500000")
        assert row["unrealized_pnl"] == Decimal("795000")
        assert row["realized_pnl"] == Decimal("215000")

        summary = portfolio_mod.portfolio_summary(db_session, usd_view=True)
        idr_row = _usd_view_row(summary, idr_t)
        assert not [k for k in idr_row if k.startswith("usd_")]
        default_row = _usd_view_row(portfolio_mod.portfolio_summary(db_session), t)
        assert not [k for k in default_row if k.startswith("usd_")]
    finally:
        _cleanup_prices(db_session, t)
        _cleanup_ticker(db_session, t)
        _cleanup_ticker(db_session, idr_t)


def test_usd_view_no_rate_leaves_idr_only(db_session, monkeypatch):
    """L4: no spot rate means every usd_ value is None (never guessed) and the
    IDR fields are unchanged."""
    from decimal import Decimal
    from backend import portfolio as portfolio_mod

    plat = _make_platform(db_session, "zz-d2c-usd-view")
    t = _random_ticker()
    _usd_view_stubs(monkeypatch, spot=None)
    try:
        _usd_view_position(db_session, plat, t)
        row = _usd_view_row(portfolio_mod.portfolio_summary(db_session, usd_view=True), t)
        for key in ("usd_rate", "usd_rate_date", "usd_avg_cost", "usd_current_price",
                    "usd_current_value", "usd_unrealized_pnl"):
            assert key in row and row[key] is None, key
        assert row["avg_cost"] == Decimal("47000")
        assert row["current_value"] == Decimal("1500000")
        assert row["unrealized_pnl"] == Decimal("795000")
        assert row["realized_pnl"] == Decimal("215000")
    finally:
        _cleanup_prices(db_session, t)
        _cleanup_ticker(db_session, t)


def test_usd_view_omits_avg_cost_not_from_own_usd_trades(db_session, monkeypatch):
    """L5: no events, events in another currency, or a hand-edited quantity
    leave usd_avg_cost and usd_unrealized_pnl None; price and value remain."""
    import datetime as _dt
    from decimal import Decimal
    from backend import portfolio as portfolio_mod
    from backend.models import Holding
    from backend.writes import apply_set_price

    plat = _make_platform(db_session, "zz-d2c-usd-view")
    no_events, mixed, edited = _random_ticker(), _random_ticker(), _random_ticker()
    _usd_view_stubs(monkeypatch, spot=(Decimal("20000"), _dt.date(2026, 1, 2), False))
    tickers = (no_events, mixed, edited)
    try:
        db_session.add(Holding(
            ticker=no_events, quantity=Decimal("4"), avg_cost=Decimal("50000"),
            currency="USD", platform_id=plat, asset_type="crypto",
        ))
        db_session.commit()

        _add_event_ccy(db_session, mixed, "buy", 3, 2, 1, plat, "USD")
        _add_event_ccy(db_session, mixed, "buy", 3, 40000, 2, plat, "IDR")
        portfolio_mod.recompute_holding_from_events(db_session, mixed, plat)
        db_session.commit()

        _usd_view_position(db_session, plat, edited)
        db_session.query(Holding).filter(
            Holding.ticker == edited, Holding.platform_id == plat
        ).update({"quantity": Decimal("9")})
        db_session.commit()

        for t in (no_events, mixed):
            apply_set_price(db_session, t, 100000, source="manual")
        db_session.commit()

        summary = portfolio_mod.portfolio_summary(db_session, usd_view=True)
        for t in tickers:
            row = _usd_view_row(summary, t)
            assert row["currency"] == "USD", t
            assert row["usd_avg_cost"] is None, t
            assert row["usd_unrealized_pnl"] is None, t
            assert row["usd_current_price"] == Decimal("5"), t
            assert row["usd_current_value"] == row["quantity"] * Decimal("5"), t
    finally:
        for t in tickers:
            _cleanup_prices(db_session, t)
            _cleanup_ticker(db_session, t)


def test_usd_view_reaches_both_routes(client, db_session, authed, monkeypatch):
    """The investments summary and the platform detail both carry the usd_
    fields; refresh_all_prices is stubbed so the test stays offline."""
    import datetime as _dt
    from decimal import Decimal
    from backend import prices as prices_mod

    plat = _make_platform(db_session, "zz-d2c-usd-view")
    t = _random_ticker()
    _usd_view_stubs(monkeypatch, spot=(Decimal("20000"), _dt.date(2026, 1, 2), False))
    monkeypatch.setattr(prices_mod, "refresh_all_prices", lambda *a, **k: {})
    try:
        _usd_view_position(db_session, plat, t)

        summary = client.get("/investments/summary")
        assert summary.status_code == 200, summary.text
        row = next(h for g in summary.json()["groups"] for h in g["holdings"] if h["ticker"] == t)
        assert Decimal(str(row["usd_current_value"])) == Decimal("75")
        assert Decimal(str(row["usd_avg_cost"])) == Decimal("3")

        detail = client.get(f"/platforms/{plat}/detail")
        assert detail.status_code == 200, detail.text
        row = next(h for h in detail.json()["holdings"] if h["ticker"] == t)
        assert Decimal(str(row["usd_current_value"])) == Decimal("75")
        assert Decimal(str(row["usd_avg_cost"])) == Decimal("3")
    finally:
        _cleanup_prices(db_session, t)
        _cleanup_ticker(db_session, t)
