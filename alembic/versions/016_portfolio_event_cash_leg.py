"""portfolio_events.transaction_id: link a funded buy/sell to its cash-leg transaction

Revision ID: b6e2d9f4a170
Revises: f5c8a2d7e319
Create Date: 2026-10-10

Additive only; touches `portfolio_events` and nothing else. A funded buy/sell
writes a cash-leg Transaction plus a PortfolioEvent, but until now only
`source_account_id` tied them together, which cannot identify the cash row.
`transaction_id` (nullable FK, ON DELETE SET NULL) does, so editing or deleting
an event can keep its cash leg in step. The unique index is deliberate: deleting
an event deletes its cash leg, so one cash row must never back two events
(Postgres allows many NULLs).

Backfill links existing funded events only when event and cash row match each
other one-to-one (same account, same day, category 'Investment', is_transfer,
sign matching buy/sell, not already claimed). Anything ambiguous stays NULL;
the two-way uniqueness also means the unique index can never be violated here.

Arming: no arming environment variable, because nothing is deleted and the
backfill only fills NULLs.

Idempotent: `backend/entrypoint.sh` runs `alembic upgrade head` under `set -e`
on every container start. ADD COLUMN / CREATE INDEX use IF NOT EXISTS and the
backfill only touches rows whose transaction_id is still NULL. On an empty DB
the candidate set is empty, so it is a no-op.

Imports nothing from backend.*: raw SQL via op.execute only.

downgrade(): drops the index and the column; the links are lost.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "b6e2d9f4a170"
down_revision: Union[str, None] = "f5c8a2d7e319"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE portfolio_events "
        "ADD COLUMN IF NOT EXISTS transaction_id INTEGER NULL "
        "REFERENCES transactions(id) ON DELETE SET NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_portfolio_events_transaction_id "
        "ON portfolio_events (transaction_id)"
    )
    op.execute(
        """
        WITH cand AS (
            SELECT e.id AS eid, t.id AS tid
            FROM portfolio_events e
            JOIN transactions t
              ON t.account_id = e.source_account_id
             AND t.date::date = e.date
             AND t.category = 'Investment'
             AND t.is_transfer
             AND ((e.event_type = 'buy' AND t.amount < 0)
               OR (e.event_type = 'sell' AND t.amount > 0))
            WHERE e.source_account_id IS NOT NULL
              AND e.transaction_id IS NULL
              AND e.event_type IN ('buy', 'sell')
              AND NOT EXISTS (SELECT 1 FROM portfolio_events p WHERE p.transaction_id = t.id)
        ),
        uniq AS (
            SELECT eid, tid FROM (
                SELECT eid, tid,
                       count(*) OVER (PARTITION BY eid) AS ce,
                       count(*) OVER (PARTITION BY tid) AS ct
                FROM cand
            ) x
            WHERE ce = 1 AND ct = 1
        )
        UPDATE portfolio_events pe
        SET transaction_id = u.tid
        FROM uniq u
        WHERE pe.id = u.eid
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_portfolio_events_transaction_id")
    op.execute("ALTER TABLE portfolio_events DROP COLUMN IF EXISTS transaction_id")
