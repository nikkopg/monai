"""proposals approval path: channel, stored code, attempt counter, status_changed_at

Revision ID: f5c8a2d7e319
Revises: e7f3b1a9c204
Create Date: 2026-10-04

Additive only; touches `proposals` and nothing else. Adds `channel`,
`supersedes_id` (plain self-reference, first used in Phase 32), `code` (the
stored MCP confirm code), `failed_attempts` and `status_changed_at`, a CHECK
over the four channels, and two indexes. Status values stay
pending/confirmed/rejected/expired; there is no `locked` status (D-04).

Arming: this revision deliberately has NO arming environment variable, unlike
`013`'s `MONAI_CLEANUP_013_APPLY`, because nothing is deleted (D-03, design
C-1 R2-21).

Idempotent: `backend/entrypoint.sh` runs `alembic upgrade head` under `set -e`
on every container start. ADD COLUMN / CREATE INDEX use IF NOT EXISTS, the
CHECK is added inside a pg_constraint-guarded DO block, and the backfill only
touches rows whose status_changed_at is still NULL, so a re-run is a no-op.
`alembic/env.py` runs the revision in one transaction, so an error rolls it
back fully.

Imports nothing from backend.*: raw SQL via op.execute only.

downgrade(): drops every added object; the data held in code, failed_attempts
and supersedes_id is lost.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "f5c8a2d7e319"
down_revision: Union[str, None] = "e7f3b1a9c204"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE proposals
            ADD COLUMN IF NOT EXISTS channel VARCHAR(16) NOT NULL DEFAULT 'chat',
            ADD COLUMN IF NOT EXISTS supersedes_id UUID NULL REFERENCES proposals(id),
            ADD COLUMN IF NOT EXISTS code VARCHAR(16) NULL,
            ADD COLUMN IF NOT EXISTS failed_attempts INTEGER NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS status_changed_at TIMESTAMPTZ NULL
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'ck_proposals_channel'
                  AND conrelid = 'proposals'::regclass
            ) THEN
                ALTER TABLE proposals ADD CONSTRAINT ck_proposals_channel
                    CHECK (channel IN ('chat','mcp','discord','upload'));
            END IF;
        END
        $$
        """
    )
    op.execute(
        "UPDATE proposals SET status_changed_at = COALESCE(confirmed_at, created_at) "
        "WHERE status_changed_at IS NULL"
    )
    op.execute("ALTER TABLE proposals ALTER COLUMN status_changed_at SET DEFAULT now()")
    op.execute("ALTER TABLE proposals ALTER COLUMN status_changed_at SET NOT NULL")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_proposals_status_changed_at "
        "ON proposals (status_changed_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_proposals_pending_expires "
        "ON proposals (expires_at) WHERE status = 'pending'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_proposals_pending_expires")
    op.execute("DROP INDEX IF EXISTS ix_proposals_status_changed_at")
    op.execute("ALTER TABLE proposals DROP CONSTRAINT IF EXISTS ck_proposals_channel")
    op.execute(
        """
        ALTER TABLE proposals
            DROP COLUMN IF EXISTS status_changed_at,
            DROP COLUMN IF EXISTS failed_attempts,
            DROP COLUMN IF EXISTS code,
            DROP COLUMN IF EXISTS supersedes_id,
            DROP COLUMN IF EXISTS channel
        """
    )
