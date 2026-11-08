"""usd prices and platform currency: portfolio_events.price to 12 decimals, platforms.currency

Revision ID: b8d4e2f09a17
Revises: e3b7a91c5d42
Create Date: 2026-11-08

Additive: it only alters one column type and adds one column with a constraint. It reads
no environment variable, has no data step, cannot raise on existing rows and imports
nothing from backend.*, so it cannot abort boot (`backend/entrypoint.sh` runs
`alembic upgrade head` on every start). Every stored value is numerically unchanged.

`portfolio_events.price` goes from Numeric(18,2) to Numeric(28,12): both keep 16 integer
digits, so no existing value can overflow, and a USD unit price (a coin worth a fraction
of a dollar) keeps its digits. `platforms.currency` is NOT NULL with server default 'IDR',
so every existing platform reads IDR; the CHECK is the same form as 020's
ck_accounts_currency.

downgrade(): drops the constraint and the column and narrows price back to (18,2). The
narrowing rounds any USD price to 2 decimals and is lossy.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8d4e2f09a17"
down_revision: Union[str, None] = "e3b7a91c5d42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "portfolio_events", "price",
        existing_type=sa.Numeric(18, 2), type_=sa.Numeric(28, 12), existing_nullable=False,
    )
    op.add_column(
        "platforms",
        sa.Column("currency", sa.String(8), nullable=False, server_default="IDR"),
    )
    op.create_check_constraint("ck_platforms_currency", "platforms", "currency IN ('IDR','USD')")


def downgrade() -> None:
    op.drop_constraint("ck_platforms_currency", "platforms", type_="check")
    op.drop_column("platforms", "currency")
    op.alter_column(
        "portfolio_events", "price",
        existing_type=sa.Numeric(28, 12), type_=sa.Numeric(18, 2), existing_nullable=False,
    )
