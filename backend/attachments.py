"""
Chat attachments (Phase 39): storage lifecycle.

Files are parsed once, at upload, in code (D-04); the model only ever sees the
stored text or rows. The raw bytes are kept for `RAW_RETENTION_DAYS` and then
purged (D-07) while `extracted_text`, `rows`, `meta` and any proposals made from
the file remain. Plans 39-04..06 add the parsers to this module.

pdfplumber and Pillow must only ever be imported inside functions here, never at
module level: main.py imports this module at startup and the 3.12 snapshot
image predates pdfplumber.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
RAW_RETENTION_DAYS = 7


def purge_expired(db: Session) -> int:
    """NULL `raw` and stamp `purged_at` on attachments older than the retention
    window that still hold bytes, then commit. Returns the number purged.

    Idempotent: a purged row has raw NULL and drops out of the WHERE. Called
    lazily at the top of the upload route, `read_attachment` and the thread
    detail, as well as by the daily scheduler job.
    """
    result = db.execute(
        text(
            "UPDATE attachments SET raw = NULL, purged_at = now() "
            "WHERE purged_at IS NULL AND raw IS NOT NULL "
            "AND created_at < now() - make_interval(days => :d)"
        ),
        {"d": RAW_RETENTION_DAYS},
    )
    db.commit()
    return result.rowcount
