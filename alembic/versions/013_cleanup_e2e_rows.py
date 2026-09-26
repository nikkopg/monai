"""delete pinned e2e/test transaction rows polluting production cashflow

Revision ID: d4b7c2e9a516
Revises: c2a9f1e6b8d3
Create Date: 2026-09-05

Data-only cleanup (no schema change). Removes a concrete artifact left over
from prior e2e/manual testing: 14 transaction rows (12 with `account_id IS
NULL`, 2 written against the real Cash account) carrying synthetic
`TestMerchant` / `Test Merchant CFS` markers, verified live 2026-09-05. Net
effect of removal: +3,145,000 IDR of phantom cashflow taken out of the
ledger.

Why the orphans matter (not cosmetic): `account_balances()`
(`backend/tools.py:474`) reads `accounts LEFT JOIN transactions`, so a row
with `account_id IS NULL` is invisible to balances and therefore to
`net_worth()`. But `cashflow_transactions`'s `NOT EXISTS (... a.id =
t.account_id AND a.type='investment')` predicate matches nothing for a NULL
account_id, so `NOT EXISTS` evaluates TRUE and the orphan IS counted by
`spending_total`/`income_total`/`monthly_trend`. Left in place these rows
guarantee a permanent, unexplainable parity failure once Phase 22 asserts
`composed_series_latest == net_worth()`.

SOURCE OF THE ID LIST (important, verified live 2026-09-05): the 14 ids were
enumerated by hand from a live database inspection, not derived from any
`LIKE`/`ILIKE` pattern, and are pinned as a literal list (`_TARGET_IDS`) that
this migration never widens at runtime. That pinning is not incidental
caution: a `merchant ILIKE '%test%' OR notes ILIKE '%test%'` sweep over this
same dataset also matches two rows that are real user data —

  - 1455 (2025-04-11, -65,000, "test kesehatan SIM") — Indonesian for a
    driving-licence health check; "test" here is the medical test, not an
    e2e marker.
  - 5609 (2026-06-20, -25,000, "kopi kenangan", notes "test entry") — a real
    purchase at a national coffee-chain merchant (Kopi Kenangan).

Both are user-confirmed real (2026-09-05) and PRESERVED — they are simply
absent from `_TARGET_IDS`, so no code path in this file can delete them. The
heuristic above is run anyway, purely to print what it would have destroyed
(2 out of 4 matches on account 1 are real), which is exactly why the target
set must stay pinned rather than pattern-matched.

Scope: `_TARGET_IDS` names all 14 rows —
5615, 5622, 5714-5723 (`account_id IS NULL`, dates 2024-05-01 to 2026-05-10)
plus 5724 and 5725 (`account_id = 1` / Cash, dates 2020-01-15 and
2024-06-15), all carrying the same synthetic marker, user-confirmed DELETE
2026-09-05 despite sitting on a real account. `_PRESERVED_IDS` (1455, 5609)
are report-only and never fed to a delete branch.

D-03 (account-side, verification only): accounts 2307-2320 were already
deleted 2026-09-03 and audited (`audit_log` rows 6300-6304); this migration
performs NO account delete. It only asserts their absence and reports the
matched audit rows so that evidence travels with every run.

Idempotent: the surviving-target set is SELECTed before anything else runs;
on a second `upgrade()` that SELECT returns zero rows, so the per-row
snapshot/audit/delete loop body never executes and the audit-row count for
these ids never grows past 14. When the surviving-target set is empty this
migration is a clean no-op — it prints a message and RETURNS NORMALLY even
in dry-run mode, rather than raising. This is load-bearing:
`backend/entrypoint.sh` runs `alembic upgrade head` under `set -e` on every
backend container start, so an unconditional dry-run abort would
permanently brick startup on any database with nothing to clean (a fresh
clone, a recreated `monai_pgdata` volume, CI, a new dev machine).

Report-only (never auto-fixed, mirrors 011/012's flagged-ids idiom): the
`%test%` heuristic described above is printed for visibility and is not a
delete predicate under any circumstances.

PARITY / BLAST-RADIUS ABORT: a per-table row count is captured before and
after the mutation (every base table in `public`, enumerated from
`information_schema.tables`, never hand-listed). The only permitted deltas
are `transactions` == -N and `audit_log` == +N, where N is the number of
rows actually deleted this run; any other table changing, or a table
appearing/disappearing between the two captures, raises `RuntimeError` and
rolls back — `alembic/env.py`'s `run_migrations_online` runs the online
migration inside one transaction, so the raise is a full rollback.

Arming: `upgrade()` defaults to a dry run (report + abort, deletes nothing
in the committed sense) unless the environment variable
`MONAI_CLEANUP_013_APPLY` is set to exactly `"1"`. This direction — safe by
default, explicit opt-in for the destructive path — is deliberate because
`backend/entrypoint.sh` runs `alembic upgrade head` unattended on every
container start; an arming-by-default migration would delete production
rows the first time anyone rebuilds the image.

downgrade(): documented no-op (009/010/011/012 posture). The deleted rows
are recoverable from each audit_log row's `before` snapshot and from
`monai_backup_2026-09-05.sql`; there is no schema object to revert.
"""
from typing import Sequence, Union

import json
import os

import sqlalchemy as sa
from alembic import op

revision: str = "d4b7c2e9a516"
down_revision: Union[str, None] = "c2a9f1e6b8d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CLEANUP_SOURCE = "e2e_cleanup_013"

# Pinned, explicit target list (D-01) — never derived from a pattern match.
# 5615-5723: the 12 account_id IS NULL orphans. 5724/5725: 2 e2e strays that
# landed on the real Cash account (account_id=1), user-confirmed DELETE
# 2026-09-05 despite sitting on a live account.
_TARGET_IDS = [
    5615, 5622, 5714, 5715, 5716, 5717, 5718, 5719, 5720, 5721, 5722, 5723,
    5724, 5725,
]

# Real user rows a naive %test% sweep also matches — reported, never acted
# on (D-02). Both user-confirmed real on 2026-09-05.
_PRESERVED_IDS = (1455, 5609)

_LIST_BASE_TABLES = """
    SELECT table_name FROM information_schema.tables
    WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
    ORDER BY table_name
"""

_COUNT_STALE_ACCOUNTS = """
    SELECT count(*) FROM accounts WHERE id BETWEEN 2307 AND 2320
"""

_AUDITED_ACCOUNT_DELETES = """
    SELECT id FROM audit_log
    WHERE entity = 'account' AND operation = 'delete'
      AND entity_id BETWEEN 2307 AND 2320
    ORDER BY id
"""

_SELECT_TARGET_TRANSACTIONS = """
    SELECT id, date, amount, currency, category, raw_category, merchant,
           notes, account_id, category_id, transfer_pair_id, is_transfer
    FROM transactions
    WHERE id = ANY(:ids)
    ORDER BY id
"""

_DELETE_TRANSACTION = """
    DELETE FROM transactions WHERE id = :tid
"""

_INSERT_AUDIT = """
    INSERT INTO audit_log (entity, entity_id, operation, before, after)
    VALUES ('transaction', :tid, 'delete', CAST(:before AS jsonb), CAST(:after AS jsonb))
"""

# print-only — must never feed a DELETE
_TEST_HEURISTIC_MATCHES = """
    SELECT id, date, amount, merchant, notes FROM transactions
    WHERE merchant ILIKE '%test%' OR notes ILIKE '%test%'
    ORDER BY id
"""


def _row_snapshot(row) -> dict:
    """Full-row snapshot of a transaction, safe for json.dumps. Accepts
    anything exposing the transaction columns as attributes (a SQLAlchemy
    Row from _SELECT_TARGET_TRANSACTIONS, or a fake object in tests).
    `amount` (Decimal) -> str, `date` (date/datetime) -> isoformat(); every
    other column passes through unchanged (the Decimal/date-to-jsonb
    conversion is the known hazard this migration must not repeat)."""
    return {
        "id": row.id,
        "date": row.date.isoformat(),
        "amount": str(row.amount),
        "currency": row.currency,
        "category": row.category,
        "raw_category": row.raw_category,
        "merchant": row.merchant,
        "notes": row.notes,
        "account_id": row.account_id,
        "category_id": row.category_id,
        "transfer_pair_id": row.transfer_pair_id,
        "is_transfer": row.is_transfer,
    }


def _table_counts(conn) -> dict[str, int]:
    """Per-table row count for every public base table (D-06), discovered
    via information_schema rather than hand-listed so an un-remembered table
    is still covered. Table names come from this migration's own catalog
    query, never from user input or the id list, so building one
    `count(*)` statement per discovered name (SQL identifiers cannot be
    bound as query parameters) carries no injection surface."""
    tables = [r[0] for r in conn.execute(sa.text(_LIST_BASE_TABLES))]
    counts: dict[str, int] = {}
    for t in tables:
        counts[t] = conn.execute(sa.text('SELECT count(*) FROM "' + t + '"')).scalar()
    return counts


def cleanup_e2e_rows(conn, *, dry_run: bool = False, ids: list[int] | None = None) -> dict:
    """Delete the pinned e2e transaction rows (D-01), auditing each one
    (D-09), and prove blast radius via an enumerated per-table count diff
    (D-06). Accepts a raw Connection (op.get_bind()) or an ORM Session — same
    contract as 012's backfill_opening_events(conn). `ids` defaults to the
    pinned _TARGET_IDS; it is a test seam only, upgrade() never passes it.
    Idempotent: a second run's SELECT finds zero surviving rows, so the
    per-row snapshot/audit/delete loop (and the audit insert inside it)
    never executes again. Aborts (raises) in dry-run mode UNLESS there is
    nothing to delete, in which case it always returns normally (T-19-21).
    """
    target_ids = list(ids) if ids is not None else list(_TARGET_IDS)

    baseline = _table_counts(conn)

    # D-03: account-side assertion only — this migration performs NO
    # account delete. Accounts 2307-2320 must already be gone.
    stale_accounts = conn.execute(sa.text(_COUNT_STALE_ACCOUNTS)).scalar()
    if stale_accounts:
        raise RuntimeError(
            f"Cleanup 013 ABORT: {stale_accounts} account(s) still present "
            "in the already-deleted 2307-2320 range — this database does "
            "not match the one this migration was written against. "
            "Rolling back."
        )
    audited_account_deletes = [
        r[0] for r in conn.execute(sa.text(_AUDITED_ACCOUNT_DELETES))
    ]

    surviving = list(
        conn.execute(sa.text(_SELECT_TARGET_TRANSACTIONS), {"ids": target_ids})
    )

    deleted_rows: list[dict] = []
    for row in surviving:
        before = _row_snapshot(row)
        after = {
            "source": _CLEANUP_SOURCE,
            "reason": "pinned e2e artifact (D-01), user-confirmed 2026-09-05",
        }
        conn.execute(sa.text(_INSERT_AUDIT), {
            "tid": row.id,
            "before": json.dumps(before),
            "after": json.dumps(after),
        })
        conn.execute(sa.text(_DELETE_TRANSACTION), {"tid": row.id})
        deleted_rows.append(before)

    # D-02: report-only preserved-rows check. This can never feed a delete —
    # matched ids are simply printed, never joined into a mutation.
    heuristic_matches = list(conn.execute(sa.text(_TEST_HEURISTIC_MATCHES)))
    preserved_report = [
        {
            "id": r.id, "date": r.date.isoformat(), "amount": str(r.amount),
            "merchant": r.merchant, "notes": r.notes,
        }
        for r in heuristic_matches if r.id not in target_ids
    ]

    after_counts = _table_counts(conn)
    n_deleted = len(deleted_rows)
    count_diff: dict[str, int] = {}
    for table in sorted(set(baseline) | set(after_counts)):
        before_n = baseline.get(table)
        after_n = after_counts.get(table)
        if before_n is None or after_n is None:
            raise RuntimeError(
                f"Cleanup 013 BLAST-RADIUS ABORT: table '{table}' appeared "
                f"or disappeared between baseline and post-mutation capture "
                f"(before={before_n}, after={after_n}). Rolling back."
            )
        delta = after_n - before_n
        count_diff[table] = delta
        if table == "transactions":
            expected = -n_deleted
        elif table == "audit_log":
            expected = n_deleted
        else:
            expected = 0
        if delta != expected:
            raise RuntimeError(
                f"Cleanup 013 BLAST-RADIUS ABORT: table '{table}' changed "
                f"by {delta} (before={before_n}, after={after_n}), expected "
                f"{expected}. Rolling back."
            )

    print(
        f"Cleanup 013: {n_deleted} target row(s) deleted; "
        f"{len(preserved_report)} preserved-row(s) matched a naive %test% "
        "heuristic and were NOT deleted (D-02)."
    )
    print("  TARGET ROWS (id, date, amount, merchant, account_id):")
    for r in deleted_rows:
        print(
            f"    {r['id']}  {r['date']}  {r['amount']:>14}  "
            f"{r['merchant']}  account_id={r['account_id']}"
        )
    print(f"  PRESERVED (report-only, D-02 — e.g. 1455/5609 real user data): {preserved_report}")
    print(f"  PER-TABLE COUNT DIFF (after - before): {count_diff}")
    if audited_account_deletes:
        print(f"  D-03: audited 2026-09-03 account-delete rows confirmed present: {audited_account_deletes}")

    report = {
        "deleted": deleted_rows,
        "preserved": preserved_report,
        "count_diff": count_diff,
        "audited_account_deletes": audited_account_deletes,
    }

    if n_deleted == 0:
        print("Cleanup 013: nothing to clean — no-op.")
        return report

    if dry_run:
        raise RuntimeError(
            f"Cleanup 013 DRY RUN: printed the report above for {n_deleted} "
            "row(s); nothing is committed. Set "
            "MONAI_CLEANUP_013_APPLY=1 to perform the real delete. "
            "Rolling back."
        )

    return report


def upgrade() -> None:
    cleanup_e2e_rows(
        op.get_bind(),
        dry_run=os.environ.get("MONAI_CLEANUP_013_APPLY") != "1",
    )


def downgrade() -> None:
    # No-op by design — see module docstring (009/010/011/012 downgrade
    # posture). Deleted rows are recoverable from audit_log before-snapshots
    # and from monai_backup_2026-09-05.sql; there is no schema object to
    # revert.
    pass
