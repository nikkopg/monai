"""chat threads and messages; proposals.turn_id and message_id

Revision ID: edebc52384d8
Revises: b6e2d9f4a170
Create Date: 2026-10-11

Adds `threads` (one row per conversation) and `messages` (ordered turns, one
user and one assistant row per exchange, with a `status` of complete, error or
cancelled so a failed or stopped turn is never stored as an answer). Proposals
are ledger and audit artefacts, so `proposals.message_id` is a SET NULL foreign key:
deleting a thread removes its messages and never a proposal. `proposals.turn_id`
(nullable, indexed) groups the proposals one chat turn created.

`threads.summary` / `summary_upto_seq` ship now so Phase 38 compaction needs no
second owner rehearsal; per-thread tool and archive columns are deliberately
absent (D-02).

Arming: no arming environment variable, nothing is deleted or rewritten.

Idempotent: `backend/entrypoint.sh` runs `alembic upgrade head` under `set -e`
on every container start, so every statement is IF NOT EXISTS.

Imports nothing from backend.*: raw SQL via op.execute only.

downgrade(): drops ix_proposals_turn_id, proposals.message_id, proposals.turn_id,
messages, threads, in that order; thread history is lost, proposals are kept.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "edebc52384d8"
down_revision: Union[str, None] = "b6e2d9f4a170"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE IF NOT EXISTS threads ("
        "id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
        "title TEXT NOT NULL DEFAULT '', "
        "summary TEXT NULL, "
        "summary_upto_seq INT NOT NULL DEFAULT 0, "
        "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
        "updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_threads_updated_at ON threads (updated_at DESC)"
    )
    op.execute(
        "CREATE TABLE IF NOT EXISTS messages ("
        "id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
        "thread_id UUID NOT NULL REFERENCES threads(id) ON DELETE CASCADE, "
        "seq INT NOT NULL, "
        "role VARCHAR(16) NOT NULL CHECK (role IN ('user','assistant')), "
        "content TEXT NOT NULL DEFAULT '', "
        "status VARCHAR(16) NOT NULL DEFAULT 'complete' "
        "CHECK (status IN ('complete','error','cancelled')), "
        "parts JSONB NOT NULL DEFAULT '{}'::jsonb, "
        "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
        "CONSTRAINT uq_messages_thread_seq UNIQUE (thread_id, seq))"
    )
    op.execute("ALTER TABLE proposals ADD COLUMN IF NOT EXISTS turn_id UUID NULL")
    op.execute(
        "ALTER TABLE proposals ADD COLUMN IF NOT EXISTS message_id UUID NULL "
        "REFERENCES messages(id) ON DELETE SET NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_proposals_turn_id ON proposals (turn_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_proposals_turn_id")
    op.execute("ALTER TABLE proposals DROP COLUMN IF EXISTS message_id")
    op.execute("ALTER TABLE proposals DROP COLUMN IF EXISTS turn_id")
    op.execute("DROP TABLE IF EXISTS messages")
    op.execute("DROP TABLE IF EXISTS threads")
