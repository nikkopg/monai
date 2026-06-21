"""baseline: accounts + transactions (existing schema)

Revision ID: 3a1f8c2d9e04
Revises:
Create Date: 2026-06-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "3a1f8c2d9e04"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # IMPORTANT: This migration is NEVER run against the existing live database.
    # On the live monai_pgdata volume, run:
    #   alembic stamp 3a1f8c2d9e04
    # This marks the baseline as applied WITHOUT executing any SQL, preserving
    # the existing 5,609 transactions and 3 accounts.
    #
    # This upgrade() body exists ONLY for fresh-database setup from scratch.
    # Running it against the live DB will fail with "relation already exists".
    # See README.md "Database migrations" for the full runbook.
    # -------------------------------------------------------------------------

    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("type", sa.String(64), nullable=True),
        sa.Column("currency", sa.String(8), nullable=True),
    )
    op.create_index("ix_accounts_name", "accounts", ["name"], unique=True)

    op.create_table(
        "transactions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("date", sa.DateTime, nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("category", sa.String(255), nullable=True),
        sa.Column("raw_category", sa.String(255), nullable=True),
        sa.Column("merchant", sa.String(512), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("account_id", sa.Integer, sa.ForeignKey("accounts.id"), nullable=True),
        sa.Column("is_transfer", sa.Boolean, nullable=False),
    )
    op.create_index("ix_transactions_date", "transactions", ["date"])
    op.create_index("ix_transactions_account_id", "transactions", ["account_id"])
    op.create_index("ix_transactions_is_transfer", "transactions", ["is_transfer"])


def downgrade() -> None:
    op.drop_index("ix_transactions_is_transfer", "transactions")
    op.drop_index("ix_transactions_account_id", "transactions")
    op.drop_index("ix_transactions_date", "transactions")
    op.drop_table("transactions")
    op.drop_index("ix_accounts_name", "accounts")
    op.drop_table("accounts")
