"""closed_positions: a realized P&L record for a position sold to zero

Revision ID: e3b7a91c5d42
Revises: c4f2a8e61d93
Create Date: 2026-11-07

Additive: creates one table and nothing else. It reads no environment variable,
has no data step and cannot raise on existing rows, so it cannot abort boot
(`backend/entrypoint.sh` runs `alembic upgrade head` on every start). Existing
zero-quantity positions convert only through the hand-run script, never here.

`realized_pnl` is Numeric(28,8), the same precision recompute works in, so a
stored record never rounds away from the figure the summary already showed.
`platform_id` is SET NULL so deleting a platform keeps the record.

Imports nothing from backend.*.

downgrade(): drops the table; the records are lost.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e3b7a91c5d42"
down_revision: Union[str, None] = "c4f2a8e61d93"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "closed_positions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticker", sa.String(32), nullable=False),
        sa.Column("platform_id", sa.Integer(), sa.ForeignKey("platforms.id", ondelete="SET NULL"), nullable=True),
        sa.Column("realized_pnl", sa.Numeric(28, 8), nullable=False),
        sa.Column("close_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("closed_positions")
