"""
Unit/integration tests for alembic/versions/013_cleanup_e2e_rows.py's
cleanup_e2e_rows() (CLEAN-01, CLEAN-02, D-01/D-02/D-06/D-08/D-09).

Loaded via importlib (mirrors test_category_migration.py /
test_transfer_retro_pairing.py) since the module lives under
alembic/versions/, not an importable package.

Self-seeded, id-agnostic (Phase 12's lesson, restated by 011's docstring):
DB-backed tests create rows on a uniquely named test account and clean up
in a `finally` block. The live 14-row / 3,145,000-IDR figures are NEVER
asserted here — only the structural outcomes (pinned ids, JSON-safe
snapshot, dry run mutates nothing, apply audits + deletes, a second apply
writes zero additional audits, an empty target set is a clean no-op). Test
rows are seeded on a named test account and NEVER with account_id IS NULL,
so this file cannot poison plan 19-03's orphan-count tripwire.
"""

import datetime
import importlib.util
import json
import sys
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2] / "alembic" / "versions" / "013_cleanup_e2e_rows.py"
)
REPO_ROOT = MIGRATION_PATH.parents[2]


def _ensure_real_alembic_package() -> None:
    """Bypass this repo's own alembic/ scaffold (see test_category_migration.py
    for the full rationale) so `from alembic import op` resolves to the real
    pip-installed package rather than the local versions/ directory."""
    cached = sys.modules.get("alembic")
    if cached is not None and hasattr(cached, "op"):
        return
    if cached is not None:
        del sys.modules["alembic"]
    shadow_init = (REPO_ROOT / "alembic" / "__init__.py").resolve()
    original_path = list(sys.path)
    try:
        sys.path = [
            p for p in sys.path
            if (Path(p or ".") / "alembic" / "__init__.py").resolve() != shadow_init
        ]
        import alembic  # noqa: F401
    finally:
        sys.path = original_path
    if not hasattr(sys.modules.get("alembic"), "op"):
        raise ImportError(
            "could not resolve the installed alembic package (only found this "
            f"repo's own scaffold at {shadow_init})"
        )


@pytest.fixture(scope="module")
def migration():
    """Load 013_cleanup_e2e_rows.py standalone via importlib."""
    _ensure_real_alembic_package()
    spec = importlib.util.spec_from_file_location("migration_013", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load migration spec from {MIGRATION_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# DB fixtures — skip if Postgres not available (matches test_write_tools.py,
# test_transfer_retro_pairing.py)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def db_available():
    from backend.db import engine
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception as e:
        pytest.skip(f"Postgres not available: {e}")
    return True


@pytest.fixture()
def db_session(db_available):
    from backend.db import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Seed helpers — self-seeded, id-agnostic. NEVER seed account_id IS NULL
# (would poison plan 19-03's orphan tripwire).
# ---------------------------------------------------------------------------

_TEST_ACCOUNT_PREFIX = "zzCleanup013Test"


def _make_account(db) -> int:
    from backend.models import Account
    name = f"{_TEST_ACCOUNT_PREFIX}-{uuid.uuid4().hex[:8]}"
    acc = Account(name=name, type="liquid", currency="IDR")
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc.id


def _make_transaction(db, account_id: int, amount, on_date: datetime.date, merchant: str) -> int:
    from backend.models import Transaction
    tx = Transaction(
        date=datetime.datetime(on_date.year, on_date.month, on_date.day, 12, 0, 0),
        amount=amount,
        currency="IDR",
        merchant=merchant,
        account_id=account_id,
        is_transfer=False,
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)
    return tx.id


def _seed_three(db, acc_id: int) -> list[int]:
    return [
        _make_transaction(db, acc_id, Decimal("-30000.00"), datetime.date(2024, 5, 1), "TestMerchant"),
        _make_transaction(db, acc_id, Decimal("1000000.00"), datetime.date(2026, 5, 10), "Test Merchant CFS"),
        _make_transaction(db, acc_id, Decimal("-250000.00"), datetime.date(2026, 5, 10), "Test Merchant CFS"),
    ]


def _cleanup_txs_and_account(db, tx_ids: list[int], account_id: int | None) -> None:
    from backend.models import Account, Transaction
    for tx_id in tx_ids:
        tx = db.get(Transaction, tx_id)
        if tx is not None:
            db.delete(tx)
    db.commit()
    if account_id is not None:
        acc = db.get(Account, account_id)
        if acc is not None:
            db.delete(acc)
        db.commit()


def _cleanup_audit_rows(db, tx_ids: list[int]) -> None:
    if not tx_ids:
        return
    db.execute(
        text("DELETE FROM audit_log WHERE entity = 'transaction' AND entity_id = ANY(:ids)"),
        {"ids": tx_ids},
    )
    db.commit()


# ---------------------------------------------------------------------------
# 1. Pinned target list (D-01) — no database
# ---------------------------------------------------------------------------

def test_target_ids_are_pinned(migration):
    assert migration._TARGET_IDS == [
        5615, 5622, 5714, 5715, 5716, 5717, 5718, 5719, 5720, 5721, 5722,
        5723, 5724, 5725,
    ]
    assert len(migration._TARGET_IDS) == 14
    assert len(set(migration._TARGET_IDS)) == 14, "duplicate id in the pinned target list"
    assert 1455 not in migration._TARGET_IDS, (
        "D-02: 1455 is real user data (Indonesian driving-licence health "
        "check, 'test kesehatan SIM') — must never enter the pinned delete "
        "target list"
    )
    assert 5609 not in migration._TARGET_IDS, (
        "D-02: 5609 is a real purchase at Kopi Kenangan — must never enter "
        "the pinned delete target list"
    )
    assert all(isinstance(i, int) for i in migration._TARGET_IDS), (
        "target ids must be a pinned int literal list, never a query "
        "result, pattern match, or anything derived at runtime"
    )


# ---------------------------------------------------------------------------
# 2. Row snapshot survives json.dumps (Decimal / date hazard) — no database
# ---------------------------------------------------------------------------

def test_row_snapshot_is_json_serializable(migration):
    class _FakeRow:
        id = 999001
        date = datetime.date(2020, 1, 15)
        amount = Decimal("500000.00")
        currency = "IDR"
        category = "Test"
        raw_category = "test"
        merchant = "Test Merchant CFS"
        notes = None
        account_id = 1
        category_id = None
        transfer_pair_id = None
        is_transfer = False

    snapshot = migration._row_snapshot(_FakeRow())
    json.dumps(snapshot)  # must not raise (the Decimal/date -> jsonb hazard)

    assert snapshot["amount"] == "500000.00"
    assert snapshot["date"] == "2020-01-15"

    expected_keys = {
        "id", "date", "amount", "currency", "category", "raw_category",
        "merchant", "notes", "account_id", "category_id",
        "transfer_pair_id", "is_transfer",
    }
    missing = expected_keys - snapshot.keys()
    assert not missing, f"before snapshot is missing transaction column(s): {missing}"


# ---------------------------------------------------------------------------
# 3. Dry run deletes nothing (D-05) — self-seeded
# ---------------------------------------------------------------------------

def test_dry_run_deletes_nothing(migration, db_session):
    from backend.models import Transaction

    acc_id = _make_account(db_session)
    tx_ids: list[int] = []
    try:
        tx_ids = _seed_three(db_session, acc_id)

        with pytest.raises(RuntimeError, match="DRY RUN"):
            migration.cleanup_e2e_rows(db_session, dry_run=True, ids=tx_ids)
        db_session.rollback()

        for tx_id in tx_ids:
            assert db_session.get(Transaction, tx_id) is not None, (
                f"dry run must not delete transaction {tx_id}"
            )

        n_audit = db_session.execute(
            text(
                "SELECT count(*) FROM audit_log "
                "WHERE entity = 'transaction' AND entity_id = ANY(:ids)"
            ),
            {"ids": tx_ids},
        ).scalar()
        assert n_audit == 0, "dry run must not write audit_log rows"
    finally:
        _cleanup_txs_and_account(db_session, tx_ids, acc_id)


# ---------------------------------------------------------------------------
# 4. Apply deletes + audits, second apply is idempotent (D-09/D-08) —
#    self-seeded
# ---------------------------------------------------------------------------

def test_apply_deletes_audits_and_is_idempotent(migration, db_session):
    from backend.models import Transaction

    acc_id = _make_account(db_session)
    tx_ids: list[int] = []
    try:
        tx_ids = _seed_three(db_session, acc_id)

        migration.cleanup_e2e_rows(db_session, dry_run=False, ids=tx_ids)
        db_session.commit()
        db_session.expire_all()

        for tx_id in tx_ids:
            assert db_session.get(Transaction, tx_id) is None, f"transaction {tx_id} should be deleted"

        audit_rows = db_session.execute(
            text(
                "SELECT entity_id, before, after FROM audit_log "
                "WHERE entity = 'transaction' AND operation = 'delete' "
                "AND entity_id = ANY(:ids)"
            ),
            {"ids": tx_ids},
        ).fetchall()
        assert len(audit_rows) == 3
        for row in audit_rows:
            assert row.after["source"] == "e2e_cleanup_013"
            assert isinstance(row.before["amount"], str)

        # Idempotence (D-08/D-09): a second run over the same ids must not
        # double-write audit rows — the audit insert lives inside the
        # surviving-row loop, and there are zero surviving rows now.
        migration.cleanup_e2e_rows(db_session, dry_run=False, ids=tx_ids)
        db_session.commit()

        n_audit_second = db_session.execute(
            text(
                "SELECT count(*) FROM audit_log "
                "WHERE entity = 'transaction' AND entity_id = ANY(:ids)"
            ),
            {"ids": tx_ids},
        ).scalar()
        assert n_audit_second == 3, "second apply must write zero additional audit rows"
    finally:
        # Discard any uncommitted mutation before the cleanup helpers commit.
        # Without this, a mid-run raise (e.g. the blast-radius abort tripping
        # on a concurrent write) would leave the partial delete pending in the
        # session, and _cleanup_*'s own commit would persist it — against the
        # live database, since this project has no isolated test DB.
        db_session.rollback()
        _cleanup_audit_rows(db_session, tx_ids)
        _cleanup_txs_and_account(db_session, tx_ids, acc_id)


# ---------------------------------------------------------------------------
# 5. Empty target set is a clean no-op (T-19-21) — no real seeding needed
# ---------------------------------------------------------------------------

def test_empty_target_set_is_a_clean_no_op(migration, db_session):
    before_tx = db_session.execute(text("SELECT count(*) FROM transactions")).scalar()
    before_audit = db_session.execute(text("SELECT count(*) FROM audit_log")).scalar()

    report = migration.cleanup_e2e_rows(db_session, dry_run=True, ids=[-1])

    assert report["deleted"] == []

    after_tx = db_session.execute(text("SELECT count(*) FROM transactions")).scalar()
    after_audit = db_session.execute(text("SELECT count(*) FROM audit_log")).scalar()
    assert after_tx == before_tx, "empty target set must not mutate transactions"
    assert after_audit == before_audit, "empty target set must not write audit_log rows"

    db_session.rollback()


# ---------------------------------------------------------------------------
# 6. D-10 orphan tripwire — the ONE deliberate live-database invariant
# assertion in this file. Every other test above is self-seeded and
# id-agnostic (see module docstring); this one intentionally is not. Do NOT
# "fix" it into a seeded test — it exists to fail loudly the moment the
# orphan class returns, because orphaned transactions (account_id IS NULL)
# are invisible to account_balances()'s `accounts LEFT JOIN transactions`
# and therefore to net_worth(), but ARE counted by the cashflow_transactions
# view (its `NOT EXISTS` predicate matches nothing for a NULL account_id),
# silently reintroducing the phantom-cashflow parity break that Phase 22's
# baseline depends on staying at zero. Actually fixing the write path that
# mints orphans (apply_delete_account) is deferred to Phase 22 (D-DEF-01);
# this assertion is the agreed interim coverage (D-10).
# ---------------------------------------------------------------------------

def test_no_orphan_transactions(db_session):
    n = db_session.execute(
        text("SELECT count(*) FROM transactions WHERE account_id IS NULL")
    ).scalar()
    assert n == 0, (
        f"{n} orphaned transaction(s) with account_id IS NULL: these are "
        "invisible to account_balances()'s accounts LEFT JOIN transactions "
        "(and therefore to net_worth()), but ARE counted by the "
        "cashflow_transactions view — their return silently breaks Phase "
        "22's parity baseline."
    )
