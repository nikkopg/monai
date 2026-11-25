"""SBN bonds: holdings coupon terms, proposals 'schedule' channel, coupon category

Revision ID: e3a9c14b7d52
Revises: d7e2c5a81f04
Create Date: 2026-11-17

Additive: it adds six nullable holdings columns (with a NULL-safe CHECK and an
ON DELETE SET NULL FK), widens the proposals channel CHECK by one value, adds a partial
unique index and seeds one category. It reads no environment variable, has no data step
on existing holdings or proposals, cannot raise on existing rows and imports nothing from
backend.*, so it cannot abort boot (`backend/entrypoint.sh` runs `alembic upgrade head`
on every start).

The schedule index makes a duplicate coupon proposal impossible: at most one 'schedule'
proposal per payload key (`coupon:<platform>:<ticker>:<date>` / `maturity:...`).

downgrade(): drops the index, restores the old four-channel CHECK (which fails while any
'schedule' proposal exists; delete those first), then drops the holdings CHECK, FK and
columns. The seeded category is left in place; it is data and harmless.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e3a9c14b7d52"
down_revision: Union[str, None] = "d7e2c5a81f04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("holdings", sa.Column("coupon_rate", sa.Numeric(5, 2), nullable=True))
    op.add_column("holdings", sa.Column("coupon_floating", sa.Boolean(), nullable=True))
    op.add_column("holdings", sa.Column("coupon_day", sa.SmallInteger(), nullable=True))
    op.add_column("holdings", sa.Column("maturity_date", sa.Date(), nullable=True))
    op.add_column("holdings", sa.Column("coupon_tax_pct", sa.Numeric(5, 2), nullable=True))
    op.add_column("holdings", sa.Column("coupon_account_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_holdings_coupon_account", "holdings", "accounts",
        ["coupon_account_id"], ["id"], ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_holdings_bond_terms", "holdings",
        "(coupon_rate IS NULL OR (coupon_rate > 0 AND coupon_rate < 100)) AND "
        "(coupon_day IS NULL OR (coupon_day BETWEEN 1 AND 28)) AND "
        "(coupon_tax_pct IS NULL OR (coupon_tax_pct >= 0 AND coupon_tax_pct < 100))",
    )

    op.execute("ALTER TABLE proposals DROP CONSTRAINT IF EXISTS ck_proposals_channel")
    op.execute(
        "ALTER TABLE proposals ADD CONSTRAINT ck_proposals_channel "
        "CHECK (channel IN ('chat','mcp','discord','upload','schedule'))"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_proposals_schedule_key "
        "ON proposals ((payload->>'key')) WHERE channel = 'schedule'"
    )

    op.execute(
        "INSERT INTO categories (name, parent_id, kind, color, icon, is_system) "
        "SELECT 'Investment income', "
        "(SELECT id FROM categories WHERE name = 'Income' AND parent_id IS NULL LIMIT 1), "
        "'income', NULL, NULL, FALSE "
        "WHERE NOT EXISTS (SELECT 1 FROM categories WHERE name = 'Investment income')"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_proposals_schedule_key")
    op.execute("ALTER TABLE proposals DROP CONSTRAINT IF EXISTS ck_proposals_channel")
    op.execute(
        "ALTER TABLE proposals ADD CONSTRAINT ck_proposals_channel "
        "CHECK (channel IN ('chat','mcp','discord','upload'))"
    )
    op.drop_constraint("ck_holdings_bond_terms", "holdings", type_="check")
    op.drop_constraint("fk_holdings_coupon_account", "holdings", type_="foreignkey")
    for col in ("coupon_account_id", "coupon_tax_pct", "maturity_date",
                "coupon_day", "coupon_floating", "coupon_rate"):
        op.drop_column("holdings", col)
