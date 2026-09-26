"""net-worth-corrections backfill: history-only recovery of 177 missing rows

Revision ID: e7f3b1a9c204
Revises: d4b7c2e9a516
Create Date: 2026-09-06

Data-only backfill into a brand-new side table. This revision creates
`net_worth_corrections` and inserts exactly 177 rows recovered from the
2026-07 data-loss event that removed the "Investements" account. It touches
NOTHING else: `transactions` and `accounts` are read-only inputs to the
transfer-pair-closure check below and are never written by this migration.

WHY THIS MATTERS: most of the apparent historical drift in the liquid
accounts was one dated, recoverable data-loss event (a dropped Wallet account
whose transfer counter-legs vanished with it), not years of unattributable
under-recording. Restoring those legs into a history-only side table lets the
net-worth trend be rebuilt honestly without touching the live ledger.

SOURCE OF THE CORRECTIONS: the user's own Wallet export (`report_*.csv`,
repo root, gitignored), anti-joined against live `transactions` on
`(date, amount)`. The resulting subset is written to
`alembic/data/corrections_260620.csv` by
`alembic/data/derive_corrections_260620.py`. That file is PERSONAL FINANCIAL
DATA: it is gitignored and never committed.

Missing fixture: on a database that never had the dropped account (any fresh
install), the fixture does not exist. `upgrade()` then creates the empty table
and skips the backfill; every consumer treats an empty table as "no
corrections".

This revision writes ONLY to `net_worth_corrections` and `audit_log`. It does
NOT restore the dropped account and does NOT re-home any row into the live
ledger (RECON-01, D-01, D-16).

Idempotent: a second `upgrade()` finds the rows already present under
`source = 'corrections_260620'` and returns normally without inserting.

PARITY / BLAST-RADIUS ABORT: the row-count assertion
(`assert_expected_shape`), the transfer-pair closure assertion
(`transfer_pair_closure` — every recovered transfer pair must sum to
exactly zero), and the per-table count diff (`_table_counts`, before vs.
after) each raise `RuntimeError` on any mismatch. `alembic/env.py` runs
online migrations inside one transaction, so any raise here is a full
rollback — no partial-apply state to clean up.

Arming: this revision deliberately has NO arming environment variable,
unlike `013`'s `MONAI_CLEANUP_013_APPLY`. `013` needed one because it
deletes production rows; `014` only ever inserts into a table it creates in
this same revision, so there is no destructive branch to gate.
`backend/entrypoint.sh` runs `alembic upgrade head` unattended under `set -e`
on every container start, so this revision must return normally both on a
fresh empty database (net_worth_corrections doesn't exist yet -> created,
then populated from the local fixture if present, or left empty if
not) and on an already-migrated one (idempotent no-op above).

downgrade(): drops the indexes and the table. Schema reverts are allowed
here; only *data* reverts follow the 009-013 documented no-op posture — but
since this revision also creates the table, there is no separate data-revert
question: dropping the table removes both the schema object and its rows.

PROHIBITIONS (enforced by Task 3's static test,
`test_no_live_importer_or_write_calls`): this revision imports nothing from
the application package (`backend.*`), constructs no ORM row objects, and
issues no INSERT, UPDATE or DELETE against the live ledger or account
tables. The application's CSV import path (`backend.importer.insert_rows` /
`_get_or_create_account`) has no dedup key and would duplicate the whole
archival export into production (D-12) — it is never imported here.
"""
from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Sequence, Union

import csv
import json

import sqlalchemy as sa
from alembic import op

revision: str = "e7f3b1a9c204"
down_revision: Union[str, None] = "d4b7c2e9a516"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Local-only fixture (gitignored personal data), resolved relative to this file
# (not cwd) — Docker/CI/dev all differ on invoking cwd, matching 009's idiom.
_CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "corrections_260620.csv"

_SOURCE = "corrections_260620"
_EXPECTED_TOTAL = 177

_LIST_BASE_TABLES = """
    SELECT table_name FROM information_schema.tables
    WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
    ORDER BY table_name
"""

_SELECT_EXISTING_COUNT = """
    SELECT count(*) FROM net_worth_corrections WHERE source = :source
"""

_INSERT_CORRECTION = """
    INSERT INTO net_worth_corrections
        (source, orig_account, date, amount, category, is_transfer)
    VALUES
        (:source, :orig_account, :date, :amount, :category, :is_transfer)
"""

_INSERT_AUDIT = """
    INSERT INTO audit_log (entity, entity_id, operation, before, after)
    VALUES ('net_worth_correction', NULL, 'backfill', NULL, CAST(:after AS jsonb))
"""


def load_corrections(csv_path) -> list[dict]:
    """Load the local 177-row fixture. Comma-delimited (unlike the
    semicolon-delimited archival source). Raises FileNotFoundError naming the
    resolved path if the fixture is absent, before any SQL runs. Raises
    ValueError naming the offending row on any empty or unparseable field."""
    if not Path(csv_path).exists():
        raise FileNotFoundError(
            f"corrections_260620.csv not found at {csv_path} — run "
            "alembic/data/derive_corrections_260620.py against your own "
            "Wallet export."
        )
    rows: list[dict] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for i, row in enumerate(csv.DictReader(f)):
            orig_account = row.get("orig_account") or ""
            if not orig_account:
                raise ValueError(f"corrections_260620.csv row {i} has empty orig_account: {row!r}")
            raw_date = row.get("date") or ""
            raw_amount = row.get("amount") or ""
            if not raw_date or not raw_amount:
                raise ValueError(f"corrections_260620.csv row {i} has empty date/amount: {row!r}")
            try:
                parsed_date = date.fromisoformat(raw_date)
            except ValueError as e:
                raise ValueError(f"corrections_260620.csv row {i} has unparseable date: {row!r}") from e
            try:
                amount = Decimal(raw_amount)
            except InvalidOperation as e:
                raise ValueError(f"corrections_260620.csv row {i} has unparseable amount: {row!r}") from e
            rows.append({
                "orig_account": orig_account,
                "date": parsed_date,
                "amount": amount,
                "category": row.get("category") or None,
                "is_transfer": row.get("is_transfer") == "true",
            })
    return rows


def assert_expected_shape(rows: list[dict]) -> None:
    """Raise RuntimeError naming actual-vs-expected unless the row count
    exactly matches the verified baseline."""
    total = len(rows)
    if total != _EXPECTED_TOTAL:
        raise RuntimeError(
            f"Recon backfill 014 SHAPE ABORT: got {total} row(s), expected "
            f"exactly {_EXPECTED_TOTAL}. Rolling back."
        )


def transfer_pair_closure(rows: list[dict]) -> list[dict]:
    """D-05.2. Match every transfer-flagged row to a counter-leg on
    `(date, -amount)` carrying a different `orig_account`, consuming each
    counter-leg at most once. Returns the legs that found no counter-leg —
    the fixture must yield an empty list (every transfer leg resolves into a
    disjoint pair summing to exactly Decimal('0.00'))."""
    transfer_rows = [r for r in rows if r["is_transfer"]]
    n = len(transfer_rows)
    used = [False] * n
    unmatched: list[dict] = []
    for i in range(n):
        if used[i]:
            continue
        leg = transfer_rows[i]
        target_amount = -leg["amount"]
        match_idx = None
        for j in range(i + 1, n):
            if used[j]:
                continue
            other = transfer_rows[j]
            if (
                other["date"] == leg["date"]
                and other["amount"] == target_amount
                and other["orig_account"] != leg["orig_account"]
            ):
                match_idx = j
                break
        if match_idx is None:
            unmatched.append(leg)
            continue
        used[i] = True
        used[match_idx] = True
        pair_sum = leg["amount"] + transfer_rows[match_idx]["amount"]
        if pair_sum != Decimal("0.00"):
            raise RuntimeError(
                f"Recon backfill 014 PAIR-CLOSURE ABORT: matched pair "
                f"{leg} / {transfer_rows[match_idx]} sums to {pair_sum}, "
                "expected exactly 0.00. Rolling back."
            )
    return unmatched


def _table_counts(conn) -> dict[str, int]:
    """Per-table row count for every public base table, discovered via
    information_schema rather than hand-listed (copied verbatim from 013's
    `_table_counts`) — table names come from this migration's own catalog
    query, never from user input, so no injection surface."""
    tables = [r[0] for r in conn.execute(sa.text(_LIST_BASE_TABLES))]
    counts: dict[str, int] = {}
    for t in tables:
        counts[t] = conn.execute(sa.text('SELECT count(*) FROM "' + t + '"')).scalar()
    return counts


def build_audit_payload(rows: list[dict]) -> dict:
    """Pure builder for the audit_log `after` payload (and the report's
    by_account block). LOAD-BEARING (D-13, T-20-05): every money value is
    rendered with str(Decimal) before it can reach json.dumps — a raw Decimal
    is not JSON-serializable and this codebase has been bitten by exactly that
    before. Extracted as a pure helper so the test suite can assert
    JSON-serializability without touching the database."""
    by_account = dict(Counter(r["orig_account"] for r in rows))
    sums: dict[str, Decimal] = {}
    for r in rows:
        sums[r["orig_account"]] = sums.get(r["orig_account"], Decimal("0.00")) + r["amount"]
    return {
        "source": _SOURCE,
        "row_count": len(rows),
        "revision": revision,
        "by_account": {
            account: {"count": by_account[account], "sum": str(sums[account])}
            for account in sorted(by_account)
        },
    }


def backfill_corrections(conn) -> dict:
    """Insert the 177 local correction rows plus one summary audit row.
    Idempotent (never raises on an already-populated table); loud abort on
    any shape/closure/blast-radius mismatch. Accepts a raw Connection
    (op.get_bind()) or a Session (tests, mirrors 012/013's contract)."""
    baseline = _table_counts(conn)

    existing = conn.execute(sa.text(_SELECT_EXISTING_COUNT), {"source": _SOURCE}).scalar()
    if existing == _EXPECTED_TOTAL:
        print(f"Recon backfill 014: source='{_SOURCE}' already holds {existing} rows — no-op.")
        return {"inserted": 0, "already_present": True, "by_account": {}}

    if not _CSV_PATH.exists():
        # Fresh install with no dropped account: nothing to recover. Must not
        # raise — entrypoint.sh runs this unattended under `set -e`.
        print(f"Recon backfill 014: no fixture at {_CSV_PATH} — table left empty.")
        return {"inserted": 0, "already_present": False, "by_account": {}}

    rows = load_corrections(_CSV_PATH)
    assert_expected_shape(rows)
    unmatched = transfer_pair_closure(rows)
    if unmatched:
        raise RuntimeError(
            f"Recon backfill 014 PARITY ABORT: {len(unmatched)} transfer "
            f"leg(s) found no counter-leg: {unmatched}. Rolling back."
        )

    for row in rows:
        conn.execute(sa.text(_INSERT_CORRECTION), {
            "source": _SOURCE,
            "orig_account": row["orig_account"],
            "date": row["date"],
            "amount": row["amount"],
            "category": row["category"],
            "is_transfer": row["is_transfer"],
        })

    # by_account counts/sums and the JSON-safe audit payload are built by the
    # pure build_audit_payload helper so the test suite can assert
    # JSON-serializability (D-13, T-20-05) without a database.
    after_payload = build_audit_payload(rows)
    conn.execute(sa.text(_INSERT_AUDIT), {"after": json.dumps(after_payload)})

    after_counts = _table_counts(conn)
    for table in sorted(set(baseline) | set(after_counts)):
        before_n = baseline.get(table)
        after_n = after_counts.get(table)
        if before_n is None or after_n is None:
            raise RuntimeError(
                f"Recon backfill 014 BLAST-RADIUS ABORT: table '{table}' "
                f"appeared or disappeared between baseline and post-mutation "
                f"capture (before={before_n}, after={after_n}). Rolling back."
            )
        delta = after_n - before_n
        if table == "net_worth_corrections":
            expected = len(rows)
        elif table == "audit_log":
            expected = 1
        else:
            expected = 0
        if delta != expected:
            raise RuntimeError(
                f"Recon backfill 014 BLAST-RADIUS ABORT: table '{table}' "
                f"changed by {delta} (before={before_n}, after={after_n}), "
                f"expected {expected}. Rolling back."
            )

    print(f"Recon backfill 014: inserted {len(rows)} correction row(s) (source={_SOURCE}).")
    for account, info in after_payload["by_account"].items():
        print(f"  {account}: {info['count']} rows, sum {info['sum']}")

    return {
        "inserted": len(rows),
        "already_present": False,
        "by_account": after_payload["by_account"],
    }


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "net_worth_corrections" not in inspector.get_table_names():
        op.create_table(
            "net_worth_corrections",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("source", sa.String(64), nullable=False),
            # orig_account deliberately carries NO sa.ForeignKey("accounts.id")
            # and no FK of any kind — the dropped account does not exist and
            # must not be recreated (D-10, RECON-01); this column is free text
            # holding the original Wallet account labels.
            sa.Column("orig_account", sa.String(64), nullable=False),
            sa.Column("date", sa.Date(), nullable=False),
            sa.Column("amount", sa.Numeric(18, 2), nullable=False),
            sa.Column("category", sa.String(255), nullable=True),
            sa.Column("is_transfer", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column(
                "created_at", sa.DateTime(timezone=True),
                server_default=sa.func.now(), nullable=False,
            ),
        )
        op.create_index(
            "ix_net_worth_corrections_date_amount",
            "net_worth_corrections", ["date", "amount"],
        )
        op.create_index(
            "ix_net_worth_corrections_source",
            "net_worth_corrections", ["source"],
        )
    backfill_corrections(conn)


def downgrade() -> None:
    # Schema revert is allowed here — only *data* reverts follow the
    # 009-013 documented no-op posture (see module docstring). Since this
    # revision creates net_worth_corrections in the same file it populates,
    # dropping the table removes both the schema object and its data.
    op.drop_index("ix_net_worth_corrections_source", table_name="net_worth_corrections")
    op.drop_index("ix_net_worth_corrections_date_amount", table_name="net_worth_corrections")
    op.drop_table("net_worth_corrections")
