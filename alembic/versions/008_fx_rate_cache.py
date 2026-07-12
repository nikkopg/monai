"""fx_rate_cache: immutable historical FX rate cache + portfolio_events.currency

Revision ID: d3e4f5a6b7c8
Revises: c1d2e3f4a5b6
Create Date: 2026-07-12

FX foundation (Phase 7, FX-01/02/04/05): every currency-aware valuation
(cash, gold, historical-at-purchase P&L) calls `fx.get_rate()`, which reads
this table cache-first and INSERTs at most one row per (rate_date,
base_currency, quote_currency) — never UPDATEs — so a re-fetch for an
already-cached date always returns the previously-stored rate. This keeps
historical P&L reproducible even though FX-04 deliberately stores no
per-event rate column.

Also adds `portfolio_events.currency` (nullable, server_default 'IDR'):
each buy/sell event carries its native cost currency; the historical rate
for that date is re-derived from fx_rate_cache at compute time, not frozen
on the event (FX-04). Existing rows backfill to 'IDR' via the column
default — no explicit UPDATE needed since Phase 5 shipped IDR-only.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d3e4f5a6b7c8"
down_revision: Union[str, None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "fx_rate_cache",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rate_date", sa.Date(), nullable=False),
        sa.Column("base_currency", sa.String(length=8), nullable=False),
        sa.Column("quote_currency", sa.String(length=8), nullable=False),
        sa.Column("rate", sa.Numeric(18, 6), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column(
            "fetched_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.UniqueConstraint(
            "rate_date", "base_currency", "quote_currency",
            name="uq_fx_rate_cache_date_pair",
        ),
    )
    op.create_index(
        "ix_fx_rate_cache_rate_date", "fx_rate_cache", ["rate_date"],
    )
    op.add_column(
        "portfolio_events",
        sa.Column("currency", sa.String(length=8), server_default="IDR", nullable=True),
    )


def downgrade() -> None:
    op.drop_column("portfolio_events", "currency")
    op.drop_index("ix_fx_rate_cache_rate_date", table_name="fx_rate_cache")
    op.drop_table("fx_rate_cache")
