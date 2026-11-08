"""trade fees: portfolio_events.fee and fee_kind

Revision ID: d7e2c5a81f04
Revises: b8d4e2f09a17
Create Date: 2026-11-08

Additive: it only adds two nullable columns and a CHECK. It reads no environment
variable, has no data step, cannot raise on existing rows and imports nothing from
backend.*, so it cannot abort boot (`backend/entrypoint.sh` runs `alembic upgrade head`
on every start). Every existing row has both columns null, which the CHECK allows, and
no stored value changes.

`fee` is Numeric(28,8), like `quantity`, so net = filled - fee stays exact. `fee_kind` is
'coin' (the fee is in units of the asset) or 'cash' (it is in the position's currency).
The CHECK says: both null, or fee > 0 with a kind (NULL-safe: a CHECK passes on an unknown).

downgrade(): drops the constraint and both columns, which forgets any recorded fee.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d7e2c5a81f04"
down_revision: Union[str, None] = "b8d4e2f09a17"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("portfolio_events", sa.Column("fee", sa.Numeric(28, 8), nullable=True))
    op.add_column("portfolio_events", sa.Column("fee_kind", sa.String(8), nullable=True))
    op.create_check_constraint(
        "ck_portfolio_events_fee", "portfolio_events",
        "(fee IS NULL AND fee_kind IS NULL) OR "
        "(fee IS NOT NULL AND fee > 0 AND fee_kind IS NOT NULL AND fee_kind IN ('coin','cash'))",
    )


def downgrade() -> None:
    op.drop_constraint("ck_portfolio_events_fee", "portfolio_events", type_="check")
    op.drop_column("portfolio_events", "fee_kind")
    op.drop_column("portfolio_events", "fee")
