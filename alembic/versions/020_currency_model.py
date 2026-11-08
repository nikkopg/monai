"""currency model: IDR/USD enforced in the database + the transactions_idr view

Revision ID: c4f2a8e61d93
Revises: 20116eb89bff
Create Date: 2026-10-25

CUR-03 / FXR-01 (Phase 42). The database itself now refuses any account or
transaction currency outside IDR/USD, and any transaction whose currency
differs from its account's (composite FK). `transactions_idr` converts every
row to IDR using the latest cached USD->IDR rate dated within 7 days before
the transaction (inclusive); NULL when none exists, never a default rate.

Order (idempotent; every step guarded, 010's idiom):
  1. drop cashflow_transactions + transactions_idr (always rebuilt at the end,
     so `t.*` is never stale and a second run is a no-op).
  2. backfill NULL/blank currency to IDR on accounts and transactions. This
     is the only data this revision writes; nothing is deleted.
  3. preflight: abort with counts and row ids only (no names, notes,
     merchants or amounts; these land in container logs) when a currency is
     outside IDR/USD or a transaction's currency differs from its account's.
     Empty tables match nothing, so a fresh DB passes. env.py runs the whole
     upgrade in one transaction, so an abort rolls everything back.
  4. NOT NULL + server_default 'IDR' (accounts); server_default 'IDR'
     (transactions, already NOT NULL).
  5. ck_accounts_currency, ck_transactions_currency: currency IN ('IDR','USD').
  6. uq_accounts_id_currency UNIQUE (id, currency) on accounts: the target the
     composite FK needs.
  7. fk_transactions_account_currency (account_id, currency) ->
     accounts (id, currency). MATCH SIMPLE: account_id NULL rows are not
     checked. The existing single-column account_id FK stays. Lives here only,
     not on the ORM models (two FK paths make SQLAlchemy mappers ambiguous).
  8. fx_rate_cache.rate_effective_date DATE NULL: the vendor's business date
     when it differs from the requested date. Existing rows stay NULL.
  9. transactions_idr, then cashflow_transactions rebuilt on top of it.

No arming flag: nothing is deleted.

Imports nothing from backend.*.

downgrade(): drops both views, the FK, the UNIQUE, both CHECKs, the new
column; accounts.currency back to nullable/no default; transactions.currency
default dropped; recreates 010's cashflow_transactions. Backfilled values stay.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4f2a8e61d93"
down_revision: Union[str, None] = "20116eb89bff"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (label, id SQL, count SQL body). Static SQL, no bound parameters.
_PREFLIGHT = (
    (
        "accounts with a currency outside IDR/USD",
        "SELECT id FROM accounts WHERE currency NOT IN ('IDR','USD') ORDER BY id LIMIT 20",
        "SELECT count(*) FROM accounts WHERE currency NOT IN ('IDR','USD')",
    ),
    (
        "transactions with a currency outside IDR/USD",
        "SELECT id FROM transactions WHERE currency NOT IN ('IDR','USD') ORDER BY id LIMIT 20",
        "SELECT count(*) FROM transactions WHERE currency NOT IN ('IDR','USD')",
    ),
    (
        "transactions whose currency differs from their account's",
        "SELECT t.id FROM transactions t JOIN accounts a ON a.id = t.account_id "
        "WHERE t.currency != a.currency ORDER BY t.id LIMIT 20",
        "SELECT count(*) FROM transactions t JOIN accounts a ON a.id = t.account_id "
        "WHERE t.currency != a.currency",
    ),
)

_TRANSACTIONS_IDR = """
CREATE VIEW transactions_idr AS
SELECT t.*,
       CASE WHEN t.currency = 'IDR' THEN t.amount ELSE t.amount * r.rate END AS amount_idr,
       CASE WHEN t.currency = 'IDR' THEN 1 ELSE r.rate END AS fx_rate,
       CASE WHEN t.currency = 'IDR' THEN NULL
            ELSE COALESCE(r.rate_effective_date, r.rate_date) END AS fx_rate_date
FROM transactions t
LEFT JOIN LATERAL (
    SELECT c.rate, c.rate_date, c.rate_effective_date
    FROM fx_rate_cache c
    WHERE t.currency = 'USD'
      AND c.base_currency = 'USD' AND c.quote_currency = 'IDR'
      AND c.rate_date BETWEEN t.date::date - 7 AND t.date::date
    ORDER BY c.rate_date DESC
    LIMIT 1
) r ON true
"""

_NOT_INVESTMENT = (
    "WHERE NOT EXISTS ("
    "SELECT 1 FROM accounts a WHERE a.id = t.account_id AND a.type = 'investment')"
)


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # 1.
    op.execute("DROP VIEW IF EXISTS cashflow_transactions")
    op.execute("DROP VIEW IF EXISTS transactions_idr")

    # 2.
    op.execute("UPDATE accounts SET currency = 'IDR' WHERE currency IS NULL OR btrim(currency) = ''")
    op.execute("UPDATE transactions SET currency = 'IDR' WHERE currency IS NULL OR btrim(currency) = ''")

    # 3. Ids and counts only.
    for label, ids_sql, count_sql in _PREFLIGHT:
        count = conn.execute(sa.text(count_sql)).scalar()
        if count:
            ids = [r[0] for r in conn.execute(sa.text(ids_sql))]
            raise RuntimeError(
                f"Currency model migration abort: {count} {label} "
                f"(first ids: {ids}). Nothing was changed. Fix or remove these rows, then re-run."
            )

    # 4.
    op.alter_column(
        "accounts", "currency",
        existing_type=sa.String(8), nullable=False, server_default="IDR",
    )
    op.alter_column(
        "transactions", "currency",
        existing_type=sa.String(8), existing_nullable=False, server_default="IDR",
    )

    # 5.
    for table, name in (("accounts", "ck_accounts_currency"), ("transactions", "ck_transactions_currency")):
        if not any(c["name"] == name for c in inspector.get_check_constraints(table)):
            op.create_check_constraint(name, table, "currency IN ('IDR','USD')")

    # 6. Guard on the constraint, not get_indexes.
    if not any(u["name"] == "uq_accounts_id_currency" for u in inspector.get_unique_constraints("accounts")):
        op.create_unique_constraint("uq_accounts_id_currency", "accounts", ["id", "currency"])

    # 7.
    if not any(f["name"] == "fk_transactions_account_currency" for f in inspector.get_foreign_keys("transactions")):
        op.create_foreign_key(
            "fk_transactions_account_currency", "transactions", "accounts",
            ["account_id", "currency"], ["id", "currency"],
        )

    # 8.
    op.execute("ALTER TABLE fx_rate_cache ADD COLUMN IF NOT EXISTS rate_effective_date DATE")

    # 9. After every column change so t.* is complete.
    op.execute(_TRANSACTIONS_IDR)
    op.execute(f"CREATE VIEW cashflow_transactions AS SELECT t.* FROM transactions_idr t {_NOT_INVESTMENT}")


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    op.execute("DROP VIEW IF EXISTS cashflow_transactions")
    op.execute("DROP VIEW IF EXISTS transactions_idr")

    if any(f["name"] == "fk_transactions_account_currency" for f in inspector.get_foreign_keys("transactions")):
        op.drop_constraint("fk_transactions_account_currency", "transactions", type_="foreignkey")
    if any(u["name"] == "uq_accounts_id_currency" for u in inspector.get_unique_constraints("accounts")):
        op.drop_constraint("uq_accounts_id_currency", "accounts", type_="unique")
    for table, name in (("transactions", "ck_transactions_currency"), ("accounts", "ck_accounts_currency")):
        if any(c["name"] == name for c in inspector.get_check_constraints(table)):
            op.drop_constraint(name, table, type_="check")

    op.alter_column("accounts", "currency", existing_type=sa.String(8), nullable=True, server_default=None)
    op.alter_column(
        "transactions", "currency",
        existing_type=sa.String(8), existing_nullable=False, server_default=None,
    )
    op.execute("ALTER TABLE fx_rate_cache DROP COLUMN IF EXISTS rate_effective_date")

    # 010's definition, so a revert to 019 leaves the view the app reads.
    op.execute(f"CREATE VIEW cashflow_transactions AS SELECT t.* FROM transactions t {_NOT_INVESTMENT}")
