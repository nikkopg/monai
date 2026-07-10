"""add platforms, holdings.platform_id, portfolio_value_history (D-17)

Revision ID: b2e6d4a19f73
Revises: 9c1a4f7d2b8e
Create Date: 2026-07-10

Adds the shared Phase-5 schema substrate:
  - platforms                — investment platform/broker/exchange registry
  - holdings.platform_id     — nullable FK so existing (unassigned) rows survive
  - portfolio_value_history  — daily per-holding value snapshot (one row per
                               holding per day, unique on (snapshot_date, ticker))

Only ADDs objects — never drops/renames existing tables (D-17, T-05-01-MIG).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b2e6d4a19f73"
down_revision: Union[str, None] = "9c1a4f7d2b8e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "platforms",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("kind", sa.String(32), nullable=True),
    )
    op.create_index("ix_platforms_name", "platforms", ["name"], unique=True)

    # Nullable FK — existing/unassigned holding rows remain valid (T-05-01-MIG).
    op.add_column(
        "holdings",
        sa.Column(
            "platform_id",
            sa.Integer,
            sa.ForeignKey("platforms.id"),
            nullable=True,
        ),
    )
    op.create_index("ix_holdings_platform_id", "holdings", ["platform_id"])

    op.create_table(
        "portfolio_value_history",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("snapshot_date", sa.Date, nullable=False),
        sa.Column("ticker", sa.String(32), nullable=False),
        sa.Column("quantity", sa.Numeric(28, 8), nullable=False),
        sa.Column("market_value", sa.Numeric(18, 2), nullable=False),
        sa.Column("cost_basis", sa.Numeric(18, 2), nullable=False),
        sa.Column(
            "currency",
            sa.String(8),
            nullable=False,
            server_default="IDR",
        ),
    )
    op.create_index(
        "ix_portfolio_value_history_ticker",
        "portfolio_value_history",
        ["ticker"],
    )
    # One row per holding per day (D-13).
    op.create_index(
        "ix_portfolio_value_history_date_ticker",
        "portfolio_value_history",
        ["snapshot_date", "ticker"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_portfolio_value_history_date_ticker", "portfolio_value_history"
    )
    op.drop_index(
        "ix_portfolio_value_history_ticker", "portfolio_value_history"
    )
    op.drop_table("portfolio_value_history")
    op.drop_index("ix_holdings_platform_id", "holdings")
    op.drop_column("holdings", "platform_id")
    op.drop_index("ix_platforms_name", "platforms")
    op.drop_table("platforms")
