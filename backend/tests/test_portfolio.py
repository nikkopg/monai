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

def test_recompute_holding_from_events():
    pytest.fail("not yet implemented — Plan 03/04 fills this")


def test_manual_price_override():
    pytest.fail("not yet implemented — Plan 03/04 fills this")


def test_staleness_ttl():
    pytest.fail("not yet implemented — Plan 03/04 fills this")


def test_avg_cost_realized_pnl():
    pytest.fail("not yet implemented — Plan 03/04 fills this")
