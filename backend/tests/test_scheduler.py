"""
Scheduler tests (Wave 0 RED target) — filled in by Plan 06.

  - test_snapshot_writes_one_row_per_holding — snapshot_all_holdings writes one
    portfolio_value_history row per holding for today with market_value =
    price × quantity and cost_basis = avg_cost × quantity.
  - test_snapshot_job_partial_failure_tolerant — the daily APScheduler snapshot
    job records what it can and tolerates a per-ticker fetch failure (does not
    abort the whole run) when writing portfolio_value_history rows.
  - test_snapshot_no_duplicate_same_day — running the snapshot twice for the
    same day does not create duplicate (snapshot_date, ticker) rows.

DB-touching stubs reuse module-level db_available / db_session fixtures (mirrors
test_portfolio.py) so they degrade to a skip when Postgres is down.
"""

import datetime as _dt
import random
from decimal import Decimal

import pytest
from sqlalchemy import text


# ---------------------------------------------------------------------------
# DB fixture — skip if Postgres not available (mirrors test_portfolio.py)
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


def _random_ticker() -> str:
    return f"TSTSCH{random.randint(100000, 999999)}"


def _add_holding(db, ticker, quantity, avg_cost, asset_type="other"):
    from backend.models import Holding, Platform
    # platform_id is NOT NULL since quick 260711-rb2 — get-or-create one test platform.
    plat = db.query(Platform).filter(Platform.name == "TestSchedulerPlatform").first()
    if plat is None:
        plat = Platform(name="TestSchedulerPlatform", kind="test")
        db.add(plat)
        db.flush()
    h = Holding(
        ticker=ticker,
        quantity=Decimal(str(quantity)),
        avg_cost=Decimal(str(avg_cost)),
        currency="IDR",
        asset_type=asset_type,
        platform_id=plat.id,
    )
    db.add(h)
    db.commit()
    return h


def _set_price(db, ticker, price, source="manual"):
    from backend.models import PriceCache
    db.add(
        PriceCache(
            ticker=ticker,
            price=Decimal(str(price)),
            currency="IDR",
            source=source,
            fetched_at=_dt.datetime.now(_dt.timezone.utc),
        )
    )
    db.commit()


def _history_rows(db, ticker):
    from backend.models import PortfolioValueHistory
    return (
        db.query(PortfolioValueHistory)
        .filter(PortfolioValueHistory.ticker == ticker)
        .filter(PortfolioValueHistory.snapshot_date == _dt.date.today())
        .all()
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_snapshot_writes_one_row_per_holding(db_session):
    from backend.portfolio import snapshot_all_holdings

    ticker = _random_ticker()
    _add_holding(db_session, ticker, quantity=3, avg_cost=100)
    _set_price(db_session, ticker, price=150)

    snapshot_all_holdings(db_session)
    db_session.commit()

    rows = _history_rows(db_session, ticker)
    assert len(rows) == 1
    row = rows[0]
    assert row.snapshot_date == _dt.date.today()
    assert row.quantity == Decimal("3")
    assert row.market_value == Decimal("450.00")   # 150 × 3
    assert row.cost_basis == Decimal("300.00")     # 100 × 3
    assert row.currency == "IDR"


def test_snapshot_job_partial_failure_tolerant(db_session, monkeypatch):
    """One ticker's price refresh raising must not abort the whole snapshot:
    the other holdings still get portfolio_value_history rows."""
    from backend import prices, portfolio

    good = _random_ticker()
    bad = _random_ticker()
    _add_holding(db_session, good, quantity=2, avg_cost=50)
    _add_holding(db_session, bad, quantity=1, avg_cost=10)
    _set_price(db_session, good, price=75)
    _set_price(db_session, bad, price=20)

    # Make snapshotting the "bad" ticker raise, mirroring a per-holding failure.
    orig_row = portfolio._latest_price

    def flaky(db, ticker):
        if ticker == bad:
            raise RuntimeError("boom")
        return orig_row(db, ticker)

    monkeypatch.setattr(portfolio, "_latest_price", flaky)

    # Must not raise despite the bad ticker exploding mid-loop.
    portfolio.snapshot_all_holdings(db_session)
    db_session.commit()

    assert len(_history_rows(db_session, good)) == 1     # good one survived
    assert len(_history_rows(db_session, bad)) == 0      # bad one skipped, no abort


def test_snapshot_no_duplicate_same_day(db_session):
    from backend.portfolio import snapshot_all_holdings

    ticker = _random_ticker()
    _add_holding(db_session, ticker, quantity=1, avg_cost=100)
    _set_price(db_session, ticker, price=100)

    snapshot_all_holdings(db_session)
    db_session.commit()
    snapshot_all_holdings(db_session)   # second run, same day
    db_session.commit()

    assert len(_history_rows(db_session, ticker)) == 1


def test_build_scheduler_registers_daily_job():
    from backend.scheduler import build_scheduler

    scheduler = build_scheduler()
    job = scheduler.get_job("daily_portfolio_snapshot")
    assert job is not None
    assert job.misfire_grace_time == 3600
    assert job.coalesce is True
    assert job.max_instances == 1


def test_snapshot_records_both_platforms_for_shared_ticker(db_session):
    """Gap B: a ticker held on TWO platforms produces TWO snapshot rows in one
    run — the value-history key is (snapshot_date, ticker, platform_id), so the
    second platform is no longer silently skipped."""
    from backend.portfolio import snapshot_all_holdings
    from backend.models import Holding, Platform, PortfolioValueHistory

    ticker = _random_ticker()
    plats = []
    for _ in range(2):
        p = Platform(name=f"SnapPlat{random.randint(100000, 999999)}", kind="test")
        db_session.add(p)
        db_session.flush()
        plats.append(p.id)
    for pid in plats:
        db_session.add(Holding(ticker=ticker, quantity=Decimal("2"), avg_cost=Decimal("100"),
                               currency="IDR", asset_type="crypto", platform_id=pid))
    db_session.commit()
    _set_price(db_session, ticker, price=150)  # price is shared per ticker

    try:
        snapshot_all_holdings(db_session)
        db_session.commit()
        rows = _history_rows(db_session, ticker)
        assert len(rows) == 2, "shared ticker on two platforms must snapshot both positions"
        assert {r.platform_id for r in rows} == set(plats)
    finally:
        db_session.query(PortfolioValueHistory).filter(PortfolioValueHistory.ticker == ticker).delete()
        db_session.query(Holding).filter(Holding.ticker == ticker).delete()
        db_session.commit()
        for pid in plats:
            p = db_session.get(Platform, pid)
            if p:
                db_session.delete(p)
        db_session.commit()
