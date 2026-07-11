"""add holdings.coingecko_id (Tier 1 crypto disambiguation)

Revision ID: 7f3a1c9e4d20
Revises: b2e6d4a19f73
Create Date: 2026-07-11

Adds an optional per-holding CoinGecko coin-id so crypto price refresh can
disambiguate tickers that map to multiple CoinGecko coins (e.g. TAO). A
missing value falls back to the fixed TICKER_TO_COINGECKO_ID symbol map —
existing holdings need no backfill.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "7f3a1c9e4d20"
down_revision: Union[str, None] = "b2e6d4a19f73"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "holdings",
        sa.Column("coingecko_id", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("holdings", "coingecko_id")
