"""
In-process daily portfolio-value snapshot scheduler (D-13/D-14).

The stack's first always-on background component: an `AsyncIOScheduler` started
in the FastAPI lifespan (backend/main.py). One daily job refreshes all prices
then writes one `portfolio_value_history` row per holding — history cannot be
backfilled (D-13), so collection must start now.

APScheduler hardening (T-05-06-DOS, 05-RESEARCH.md Pattern 3 + Pitfall 3):
`misfire_grace_time=3600` + `coalesce=True` avoid a thundering catch-up after
downtime; `max_instances=1` never overlaps two runs; `replace_existing=True`
keeps startup idempotent. Timezone is Asia/Jakarta.
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger


def daily_portfolio_snapshot_job() -> None:
    """Sync job — APScheduler runs non-coroutine jobs in its own thread pool, so
    this safely reuses the existing sync `get_session_sync()` path without
    blocking the asyncio event loop.

    Refreshes all prices (force=True — the snapshot wants today's freshest
    values), writes per-holding history rows, then commits. Both callees are
    per-ticker try/except internally, so one failing source never aborts the run.
    """
    from backend.db import get_session_sync
    from backend.portfolio import snapshot_all_holdings
    from backend.prices import refresh_all_prices

    with get_session_sync() as db:
        refresh_all_prices(db, force=True)
        snapshot_all_holdings(db)
        db.commit()


def build_scheduler() -> AsyncIOScheduler:
    """Build the AsyncIOScheduler with the daily snapshot job registered.

    Returns an un-started scheduler; the caller (the FastAPI lifespan) owns
    start()/shutdown(). 01:00 Asia/Jakarta is a low-traffic window (D-14 leaves
    the time to Claude's discretion).
    """
    scheduler = AsyncIOScheduler(timezone="Asia/Jakarta")
    scheduler.add_job(
        daily_portfolio_snapshot_job,
        trigger=CronTrigger(hour=1, minute=0),
        id="daily_portfolio_snapshot",
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
        max_instances=1,
    )
    return scheduler
