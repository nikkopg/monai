"""typed accounts: accounts.type discriminator + transfer/funding pairing columns

Revision ID: f1a2b3c4d5e6
Revises: e5f6a7b8c9d0
Create Date: 2026-07-25

ACCT-03. Promotes `accounts.type` from decorative (nullable, no constraint)
to a DB-enforced liquid/investment discriminator (D-01), backfilled from a
hard-coded, human-audited map (D-02) — no auto-inference. Adds the two
additive pairing columns transfer/funding mechanics need (Phase 13), and
creates the `cashflow_transactions` exclusion view that makes the
investment-account double-count structurally impossible (D-06/D-07).

Order (idempotent — every step guarded, mirrors migration 009's idiom):
  1. backfill accounts.type from ACCOUNT_TYPE (bound params, non-clobbering
     WHERE type IS NULL) — must run BEFORE tightening to NOT NULL.
  2. abort-loudly: live account ids must equal exactly {1, 2, 3, 559}, and
     zero NULL types remain post-backfill — nothing partial, env.py's single
     online-migration transaction makes this a clean rollback.
  3. CHECK constraint ck_accounts_type (type IN ('liquid','investment')) —
     binary closed set (D-01), no richer subtypes.
  4. tighten: NOT NULL + server_default 'liquid' (D-05) — new/imported
     accounts auto-get liquid without an app-code change (importer.py
     unchanged, verified).
  5. additive columns: transactions.transfer_pair_id (nullable, indexed, NO
     FK — pairing semantics decided in Phase 13, RESEARCH Open Q2) and
     portfolio_events.source_account_id (nullable, FK->accounts.id, indexed).
  6. create cashflow_transactions AFTER step 5 so `t.*` is the full superset
     including transfer_pair_id. Predicate is NOT EXISTS keyed on
     a.type='investment' — this KEEPS NULL-account_id rows in the view and
     makes a mis-typed account over-include visibly rather than silently
     vanish (D-06/D-07). Never inner join, never bare NOT IN, never
     type != 'liquid'.

downgrade(): strict guarded reverse — drop view, drop pairing columns
(+ index/FK), drop CHECK, revert type to nullable/no-default. Backfilled
type VALUES are left in place (009 downgrade philosophy).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# D-02 locked audit map: id 3 "Investments" is the real double-count (typed
# investment, D-04); id 559 "Stockbit" stays liquid — it's broker CASH, not
# stock positions (D-03). No auto-inference; any drift from this exact set
# aborts the migration (see the abort-loudly assert below).
ACCOUNT_TYPE: dict[int, str] = {1: "liquid", 2: "liquid", 3: "investment", 559: "liquid"}


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # 1. Backfill, idempotent + non-clobbering.
    for account_id, acc_type in ACCOUNT_TYPE.items():
        conn.execute(
            sa.text("UPDATE accounts SET type = :t WHERE id = :id AND type IS NULL"),
            {"t": acc_type, "id": account_id},
        )

    # 2. Abort-loudly asserts — live account set must match D-02 exactly.
    live_ids = {r[0] for r in conn.execute(sa.text("SELECT id FROM accounts"))}
    if live_ids != set(ACCOUNT_TYPE):
        unexpected = live_ids - set(ACCOUNT_TYPE)
        missing = set(ACCOUNT_TYPE) - live_ids
        raise RuntimeError(
            "Typed-accounts migration abort — live accounts drifted from the "
            f"D-02 audit map. unexpected ids (not in ACCOUNT_TYPE): {sorted(unexpected)}, "
            f"missing ids (in ACCOUNT_TYPE but not live): {sorted(missing)}. "
            "Classify any new account in ACCOUNT_TYPE (D-02) before re-running."
        )
    null_types = conn.execute(
        sa.text("SELECT COUNT(*) FROM accounts WHERE type IS NULL")
    ).scalar()
    if null_types:
        raise RuntimeError(
            f"Typed-accounts migration left {null_types} accounts with NULL type"
        )

    # 3. CHECK constraint (D-01: binary closed set).
    if not any(
        c["name"] == "ck_accounts_type" for c in inspector.get_check_constraints("accounts")
    ):
        op.create_check_constraint(
            "ck_accounts_type", "accounts", "type IN ('liquid','investment')"
        )

    # 4. Tighten: NOT NULL + server_default 'liquid' (D-05).
    op.alter_column(
        "accounts", "type",
        existing_type=sa.String(64),
        nullable=False,
        server_default="liquid",
    )

    # 5a. transactions.transfer_pair_id — plain nullable Integer, NO FK
    # (pairing semantics decided in Phase 13, RESEARCH Open Q2).
    tx_columns = {c["name"] for c in inspector.get_columns("transactions")}
    if "transfer_pair_id" not in tx_columns:
        op.add_column(
            "transactions", sa.Column("transfer_pair_id", sa.Integer(), nullable=True)
        )
    tx_indexes = {ix["name"] for ix in inspector.get_indexes("transactions")}
    if "ix_transactions_transfer_pair_id" not in tx_indexes:
        op.create_index(
            "ix_transactions_transfer_pair_id", "transactions", ["transfer_pair_id"]
        )

    # 5b. portfolio_events.source_account_id — nullable FK -> accounts.id.
    pe_columns = {c["name"] for c in inspector.get_columns("portfolio_events")}
    if "source_account_id" not in pe_columns:
        op.add_column(
            "portfolio_events", sa.Column("source_account_id", sa.Integer(), nullable=True)
        )
    pe_fks = {fk["name"] for fk in inspector.get_foreign_keys("portfolio_events")}
    if "fk_portfolio_events_source_account" not in pe_fks:
        op.create_foreign_key(
            "fk_portfolio_events_source_account", "portfolio_events", "accounts",
            ["source_account_id"], ["id"],
        )
    pe_indexes = {ix["name"] for ix in inspector.get_indexes("portfolio_events")}
    if "ix_portfolio_events_source_account_id" not in pe_indexes:
        op.create_index(
            "ix_portfolio_events_source_account_id", "portfolio_events", ["source_account_id"]
        )

    # 6. Exclusion view, created AFTER step 5 so t.* includes transfer_pair_id.
    # NOT EXISTS keyed on a.type='investment' keeps NULL-account_id rows IN
    # and over-includes visibly on drift, never silently vanishes (D-06/D-07).
    inspector = sa.inspect(conn)
    if "cashflow_transactions" not in inspector.get_view_names():
        op.execute(
            "CREATE VIEW cashflow_transactions AS "
            "SELECT t.* FROM transactions t "
            "WHERE NOT EXISTS ("
            "SELECT 1 FROM accounts a WHERE a.id = t.account_id AND a.type = 'investment'"
            ")"
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    if "cashflow_transactions" in inspector.get_view_names():
        op.execute("DROP VIEW IF EXISTS cashflow_transactions")

    pe_indexes = {ix["name"] for ix in inspector.get_indexes("portfolio_events")}
    if "ix_portfolio_events_source_account_id" in pe_indexes:
        op.drop_index("ix_portfolio_events_source_account_id", table_name="portfolio_events")
    pe_fks = {fk["name"] for fk in inspector.get_foreign_keys("portfolio_events")}
    if "fk_portfolio_events_source_account" in pe_fks:
        op.drop_constraint(
            "fk_portfolio_events_source_account", "portfolio_events", type_="foreignkey"
        )
    pe_columns = {c["name"] for c in inspector.get_columns("portfolio_events")}
    if "source_account_id" in pe_columns:
        op.drop_column("portfolio_events", "source_account_id")

    tx_indexes = {ix["name"] for ix in inspector.get_indexes("transactions")}
    if "ix_transactions_transfer_pair_id" in tx_indexes:
        op.drop_index("ix_transactions_transfer_pair_id", table_name="transactions")
    tx_columns = {c["name"] for c in inspector.get_columns("transactions")}
    if "transfer_pair_id" in tx_columns:
        op.drop_column("transactions", "transfer_pair_id")

    op.alter_column(
        "accounts", "type",
        existing_type=sa.String(64),
        nullable=True,
        server_default=None,
    )
    check_constraints = {c["name"] for c in inspector.get_check_constraints("accounts")}
    if "ck_accounts_type" in check_constraints:
        op.drop_constraint("ck_accounts_type", "accounts", type_="check")
