"""chat attachments (Phase 39)

Revision ID: 22645aa717c0
Revises: edebc52384d8
Create Date: 2026-10-18

Adds `attachments`: one row per file a user attaches to a chat thread. The raw
bytes are kept for 7 days (then `raw` is NULLed and `purged_at` set by
backend/attachments.purge_expired); `extracted_text`, parsed `rows` and `meta`
stay. `thread_id` cascades with its thread; `message_id` and `account_id` are
SET NULL so deleting a message or an account never deletes the attachment row.
`parse_status` holds only what is stored (ok, refused, llm_read); a password
prompt is a response status and is never persisted.

Arming: no arming environment variable, additive, nothing is deleted or
rewritten.

Idempotent: `backend/entrypoint.sh` runs `alembic upgrade head` under `set -e`
on every container start, so every statement is IF NOT EXISTS.

Imports nothing from backend.*: raw SQL via op.execute only.

downgrade(): drops both indexes then the table; attachment bytes, extracted
text and parsed rows are lost, proposals are kept.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "22645aa717c0"
down_revision: Union[str, None] = "edebc52384d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE IF NOT EXISTS attachments ("
        "id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
        "thread_id UUID NOT NULL REFERENCES threads(id) ON DELETE CASCADE, "
        "message_id UUID NULL REFERENCES messages(id) ON DELETE SET NULL, "
        "filename TEXT NOT NULL, "
        "mime VARCHAR(64) NOT NULL, "
        "kind VARCHAR(16) NOT NULL "
        "CHECK (kind IN ('csv','pdf_text','pdf_scanned','image')), "
        "size_bytes INT NOT NULL, "
        "sha256 CHAR(64) NOT NULL, "
        "raw BYTEA NULL, "
        "extracted_text TEXT NOT NULL DEFAULT '', "
        "rows JSONB NOT NULL DEFAULT '[]'::jsonb, "
        "meta JSONB NOT NULL DEFAULT '{}'::jsonb, "
        "parse_status VARCHAR(16) NOT NULL "
        "CHECK (parse_status IN ('ok','refused','llm_read')), "
        "parse_note TEXT NULL, "
        "account_id INT NULL REFERENCES accounts(id) ON DELETE SET NULL, "
        "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
        "purged_at TIMESTAMPTZ NULL)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_attachments_thread_id ON attachments (thread_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_attachments_unpurged "
        "ON attachments (created_at) WHERE purged_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_attachments_unpurged")
    op.execute("DROP INDEX IF EXISTS ix_attachments_thread_id")
    op.execute("DROP TABLE IF EXISTS attachments")
