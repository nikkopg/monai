"""Tests for the 7-day attachment raw purge (D-07). Synthetic values only."""
from datetime import datetime, timedelta, timezone

import pytest

from backend.db import get_session_sync
from backend.models import Attachment, Thread


def _att(thread_id, *, days_old, raw=b"zz", text="zz39 text"):
    return Attachment(
        thread_id=thread_id,
        filename="zz39.csv",
        mime="text/csv",
        kind="csv",
        size_bytes=2,
        sha256="0" * 64,
        raw=raw,
        extracted_text=text,
        rows=[{"amount": "1.00"}],
        meta={"k": "v"},
        parse_status="ok",
        created_at=datetime.now(timezone.utc) - timedelta(days=days_old),
    )


@pytest.fixture()
def seeded():
    with get_session_sync() as db:
        thread = Thread(title="zz39-purge")
        db.add(thread)
        db.flush()
        a, b, c = _att(thread.id, days_old=8), _att(thread.id, days_old=1), _att(thread.id, days_old=8, raw=None)
        db.add_all([a, b, c])
        db.commit()
        ids = (thread.id, a.id, b.id, c.id)
    yield ids
    with get_session_sync() as db:
        db.delete(db.get(Thread, ids[0]))  # cascades to attachments
        db.commit()


def test_purge_expired_clears_only_old_raw_and_is_idempotent(seeded):
    from backend.attachments import purge_expired

    _, a, b, c = seeded
    with get_session_sync() as db:
        assert purge_expired(db) >= 1  # >= : the shared test DB may hold other old rows
        assert purge_expired(db) == 0
        db.expire_all()
        ra, rb, rc = (db.get(Attachment, i) for i in (a, b, c))
        assert ra.raw is None and ra.purged_at is not None
        assert (ra.extracted_text, ra.rows, ra.meta) == ("zz39 text", [{"amount": "1.00"}], {"k": "v"})
        assert rb.raw == b"zz" and rb.purged_at is None
        assert rc.raw is None and rc.purged_at is None


def test_daily_job_purges_through_its_own_session(seeded):
    from backend.scheduler import daily_attachment_purge_job

    daily_attachment_purge_job()
    with get_session_sync() as db:
        assert db.get(Attachment, seeded[1]).raw is None
