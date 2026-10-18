"""
In-process daily scheduler (D-13/D-14, Phase 39 D-07).

The stack's first always-on background component: an `AsyncIOScheduler` started
in the FastAPI lifespan (backend/main.py). Two daily jobs: the snapshot job
refreshes all prices then writes one `portfolio_value_history` row per holding
(history cannot be backfilled, D-13, so collection must start now), and the
attachment purge clears raw upload bytes older than 7 days.

APScheduler hardening (T-05-06-DOS, 05-RESEARCH.md Pattern 3 + Pitfall 3):
`misfire_grace_time=3600` + `coalesce=True` avoid a thundering catch-up after
downtime; `max_instances=1` never overlaps two runs; `replace_existing=True`
keeps startup idempotent. Timezone is Asia/Jakarta.
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)


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


def daily_attachment_purge_job() -> None:
    """Sync job: NULL the raw bytes of attachments past the retention window."""
    from backend.attachments import purge_expired
    from backend.db import get_session_sync

    with get_session_sync() as db:
        n = purge_expired(db)
    logger.info("attachment purge: %d raw file(s) cleared", n)


def build_scheduler() -> AsyncIOScheduler:
    """Build the AsyncIOScheduler with the daily snapshot and purge jobs registered.

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
    scheduler.add_job(
        daily_attachment_purge_job,
        trigger=CronTrigger(hour=3, minute=0),
        id="daily_attachment_purge",
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
        max_instances=1,
    )
    return scheduler
