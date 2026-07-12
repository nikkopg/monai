"""multi-platform holdings: platform required, identity = (ticker, platform_id)

Revision ID: 8a4c2e6f91b3
Revises: 7f3a1c9e4d20
Create Date: 2026-07-11

Position identity moves from a global-unique `ticker` to the composite
`(ticker, platform_id)` (Quick 260711-rb2). `platform_id` becomes NOT NULL on
both `holdings` and `portfolio_events` — "Unassigned" is retired.

Order matters:
  1. holdings.platform_id -> NOT NULL (data is clean: all 11 holdings already
     have a platform; a stray NULL fails the migration loudly, which is
     correct — see step 1 below).
  2. Drop the old unique index on holdings.ticker (`ix_holdings_ticker`,
     created unique=True in 002_new_tables.py).
  3. Recreate ticker as a non-unique index (price refresh / lookups still
     filter by ticker alone).
  4. Add the composite unique constraint (ticker, platform_id).
  5. Add portfolio_events.platform_id (nullable first, so it can be backfilled).
  6. Backfill portfolio_events.platform_id from the (today one-per-ticker)
     holdings row.
  7. portfolio_events.platform_id -> NOT NULL, add FK + index.

downgrade() reverses in strict opposite order. NOTE: downgrade only succeeds
if no duplicate-ticker rows exist yet (restoring unique(ticker) fails
otherwise) — inherent to reversing a widened uniqueness constraint. Tested
immediately after upgrade, before any cross-platform duplicate is added.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "8a4c2e6f91b3"
down_revision: Union[str, None] = "7f3a1c9e4d20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. holdings.platform_id -> NOT NULL (data is clean today; a stray NULL
    #    fails this loudly rather than silently allowing "unassigned" back in).
    op.alter_column("holdings", "platform_id", nullable=False)

    # 2-3. Replace the global-unique ticker index with a non-unique one, AND
    #      drop the separate column-level unique constraint. 002_new_tables.py
    #      created the ticker column with `unique=True` (-> `holdings_ticker_key`
    #      constraint) AND a `unique=True` index (`ix_holdings_ticker`). BOTH
    #      enforce unique(ticker); both must go for a ticker to live on >1 platform.
    op.drop_index("ix_holdings_ticker", table_name="holdings")
    op.drop_constraint("holdings_ticker_key", "holdings", type_="unique")
    op.create_index("ix_holdings_ticker", "holdings", ["ticker"])

    # 4. Composite uniqueness: position identity is (ticker, platform_id).
    op.create_unique_constraint(
        "uq_holdings_ticker_platform", "holdings", ["ticker", "platform_id"]
    )

    # 5. Add portfolio_events.platform_id (nullable so it can be backfilled).
    op.add_column(
        "portfolio_events", sa.Column("platform_id", sa.Integer(), nullable=True)
    )

    # 6. Backfill from the (currently one-per-ticker) holding.
    op.execute(
        "UPDATE portfolio_events e SET platform_id = h.platform_id "
        "FROM holdings h WHERE h.ticker = e.ticker"
    )

    # 7. Lock down: NOT NULL + FK + index.
    op.alter_column("portfolio_events", "platform_id", nullable=False)
    op.create_foreign_key(
        "fk_portfolio_events_platform",
        "portfolio_events",
        "platforms",
        ["platform_id"],
        ["id"],
    )
    op.create_index(
        "ix_portfolio_events_platform_id", "portfolio_events", ["platform_id"]
    )


def downgrade() -> None:
    # Reverse step 7.
    op.drop_index("ix_portfolio_events_platform_id", table_name="portfolio_events")
    op.drop_constraint(
        "fk_portfolio_events_platform", "portfolio_events", type_="foreignkey"
    )
    op.alter_column("portfolio_events", "platform_id", nullable=True)

    # Reverse steps 5-6 (drop the column — no un-backfill needed).
    op.drop_column("portfolio_events", "platform_id")

    # Reverse step 4.
    op.drop_constraint("uq_holdings_ticker_platform", "holdings", type_="unique")

    # Reverse steps 2-3: restore unique(ticker) — both the unique index and the
    # column-level unique constraint. Fails if a duplicate-ticker row already
    # exists (inherent — see module docstring).
    op.drop_index("ix_holdings_ticker", table_name="holdings")
    op.create_index("ix_holdings_ticker", "holdings", ["ticker"], unique=True)
    op.create_unique_constraint("holdings_ticker_key", "holdings", ["ticker"])

    # Reverse step 1.
    op.alter_column("holdings", "platform_id", nullable=True)
