"""add audit_log, proposals, holdings, portfolio_events, price_cache + date_helpers view

Revision ID: 7b4e9f1a6c52
Revises: 3a1f8c2d9e04
Create Date: 2026-06-21

"""
from typing import Sequence, Union

import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision: str = "7b4e9f1a6c52"
down_revision: Union[str, None] = "3a1f8c2d9e04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# date_helpers view SQL — lifted verbatim from backend/db.py _DATE_HELPERS_VIEW (D-02).
# Moving it here makes the entire schema (tables + view) Alembic-managed.
_DATE_HELPERS_VIEW = """
CREATE OR REPLACE VIEW date_helpers AS SELECT
    date_trunc('month', now())::date                                      AS current_month_start,
    (date_trunc('month', now()) + interval '1 month - 1 day')::date       AS current_month_end,
    date_trunc('month', now() - interval '1 month')::date                 AS last_month_start,
    (date_trunc('month', now()) - interval '1 day')::date                 AS last_month_end,
    date_trunc('year', now())::date                                       AS current_year_start,
    (date_trunc('year', now()) + interval '3 month - 1 day')::date         AS q1_end,
    (date_trunc('year', now()) + interval '3 month')::date                 AS q2_start,
    (date_trunc('year', now()) + interval '6 month - 1 day')::date         AS q2_end,
    (date_trunc('year', now()) + interval '6 month')::date                 AS q3_start,
    (date_trunc('year', now()) + interval '9 month - 1 day')::date         AS q3_end,
    (date_trunc('year', now()) + interval '9 month')::date                 AS q4_start,
    (date_trunc('year', now()) + interval '12 month - 1 day')::date        AS q4_end;
"""


def upgrade() -> None:
    # date_helpers view — was created by init_db(); now owned by Alembic (D-02).
    # CREATE OR REPLACE is safe on the live DB where the view already exists.
    op.execute(_DATE_HELPERS_VIEW)

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("entity", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.Integer, nullable=True),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("before", JSONB, nullable=True),
        sa.Column("after", JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "proposals",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            default=uuid.uuid4,
        ),
        sa.Column("token", sa.String(64), nullable=False, unique=True),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_proposals_token", "proposals", ["token"], unique=True)

    op.create_table(
        "holdings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("ticker", sa.String(32), nullable=False, unique=True),
        sa.Column("quantity", sa.Numeric(28, 8), nullable=False),
        sa.Column("avg_cost", sa.Numeric(18, 2), nullable=False),
        sa.Column("purchase_date", sa.Date, nullable=True),
        sa.Column(
            "currency",
            sa.String(8),
            nullable=False,
            server_default="IDR",
        ),
        sa.Column("asset_type", sa.String(32), nullable=True),
    )
    op.create_index("ix_holdings_ticker", "holdings", ["ticker"], unique=True)

    op.create_table(
        "portfolio_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("ticker", sa.String(32), nullable=False),
        sa.Column("event_type", sa.String(16), nullable=False),
        sa.Column("quantity", sa.Numeric(28, 8), nullable=False),
        sa.Column("price", sa.Numeric(18, 2), nullable=False),
    )
    op.create_index("ix_portfolio_events_date", "portfolio_events", ["date"])
    op.create_index("ix_portfolio_events_ticker", "portfolio_events", ["ticker"])

    op.create_table(
        "price_cache",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("ticker", sa.String(32), nullable=False),
        sa.Column("price", sa.Numeric(18, 2), nullable=False),
        sa.Column(
            "currency",
            sa.String(8),
            nullable=False,
            server_default="IDR",
        ),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_price_cache_ticker_source", "price_cache", ["ticker", "source"])


def downgrade() -> None:
    op.drop_index("ix_price_cache_ticker_source", "price_cache")
    op.drop_table("price_cache")
    op.drop_index("ix_portfolio_events_ticker", "portfolio_events")
    op.drop_index("ix_portfolio_events_date", "portfolio_events")
    op.drop_table("portfolio_events")
    op.drop_index("ix_holdings_ticker", "holdings")
    op.drop_table("holdings")
    op.drop_index("ix_proposals_token", "proposals")
    op.drop_table("proposals")
    op.drop_table("audit_log")
    op.execute("DROP VIEW IF EXISTS date_helpers")
