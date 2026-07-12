"""portfolio_value_history: widen unique key to (snapshot_date, ticker, platform_id)

Revision ID: c1d2e3f4a5b6
Revises: 8a4c2e6f91b3
Create Date: 2026-07-12

Gap B of the multi-platform work (quick 260711-rb2 follow-up): the daily
snapshot job keyed value-history rows on (snapshot_date, ticker), so a ticker
held on two platforms recorded only ONE platform's value per day. Add
`platform_id` and swap the unique index to include it.

`platform_id` is nullable: pre-existing rows predate multi-platform. They are
backfilled best-effort from `holdings` ONLY where the ticker maps to exactly one
holding (unambiguous); any ambiguous ticker keeps NULL. New snapshots always
carry the holding's platform_id.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, None] = "8a4c2e6f91b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "portfolio_value_history",
        sa.Column("platform_id", sa.Integer(), nullable=True),
    )
    # Best-effort backfill: only when a ticker maps to exactly one holding.
    op.execute(
        "UPDATE portfolio_value_history vh SET platform_id = h.platform_id "
        "FROM holdings h WHERE h.ticker = vh.ticker "
        "AND (SELECT COUNT(*) FROM holdings h2 WHERE h2.ticker = vh.ticker) = 1"
    )
    op.create_foreign_key(
        "fk_pvh_platform", "portfolio_value_history", "platforms",
        ["platform_id"], ["id"],
    )
    op.create_index(
        "ix_portfolio_value_history_platform_id",
        "portfolio_value_history", ["platform_id"],
    )
    # Swap the unique index: (snapshot_date, ticker) -> (…, platform_id).
    op.drop_index(
        "ix_portfolio_value_history_date_ticker",
        table_name="portfolio_value_history",
    )
    op.create_index(
        "ix_portfolio_value_history_date_ticker_platform",
        "portfolio_value_history",
        ["snapshot_date", "ticker", "platform_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_portfolio_value_history_date_ticker_platform",
        table_name="portfolio_value_history",
    )
    op.create_index(
        "ix_portfolio_value_history_date_ticker",
        "portfolio_value_history",
        ["snapshot_date", "ticker"],
        unique=True,
    )
    op.drop_index(
        "ix_portfolio_value_history_platform_id",
        table_name="portfolio_value_history",
    )
    op.drop_constraint(
        "fk_pvh_platform", "portfolio_value_history", type_="foreignkey"
    )
    op.drop_column("portfolio_value_history", "platform_id")
