"""
Unit/integration tests for alembic/versions/011_retro_pair_transfers.py's
matching + pairing logic (XFER-05, D-11).

Loaded via importlib (mirrors test_category_migration.py) since the module
lives under alembic/versions/, not an importable package. These tests double
as the RED half of the TDD gate: they fail with a clear import error until
011_retro_pair_transfers.py exists (Task 2).

Self-seeded, id-agnostic (Phase 12's lesson): rows are created on uniquely
named test accounts and cleaned up at the end of every test — the live
326/16 counts from RESEARCH.md are NEVER asserted here, only the structural
outcomes (exactly-one -> paired, zero/multiple -> flagged NULL, idempotent).
"""

import datetime
import importlib.util
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2] / "alembic" / "versions" / "011_retro_pair_transfers.py"
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
    """Load 011_retro_pair_transfers.py standalone via importlib.

    Fails with FileNotFoundError/ImportError until the migration file
    exists — that is the intended RED-phase failure (module missing, not a
    bug in this test).
    """
    _ensure_real_alembic_package()
    spec = importlib.util.spec_from_file_location("migration_011", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load migration spec from {MIGRATION_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# DB fixtures — skip if Postgres not available (matches test_write_tools.py)
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
# Seed helpers
# ---------------------------------------------------------------------------

_TEST_ACCOUNT_PREFIX = "zzRetroPairTest"


def _make_account(db, suffix: str) -> int:
    from backend.models import Account
    name = f"{_TEST_ACCOUNT_PREFIX}-{suffix}"
    existing = db.query(Account).filter(Account.name == name).first()
    if existing:
        db.delete(existing)
        db.commit()
    acc = Account(name=name, type="liquid", currency="IDR")
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc.id


def _make_transfer_tx(db, account_id: int, amount, on_date: datetime.date) -> int:
    from backend.models import Transaction
    tx = Transaction(
        date=datetime.datetime(on_date.year, on_date.month, on_date.day, 12, 0, 0),
        amount=amount,
        currency="IDR",
        category="Transfer",
        merchant=None,
        account_id=account_id,
        is_transfer=True,
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)
    return tx.id


def _cleanup(db, tx_ids: list[int], account_ids: list[int]) -> None:
    from backend.models import Transaction, Account
    for tx_id in tx_ids:
        tx = db.get(Transaction, tx_id)
        if tx is not None:
            db.delete(tx)
    db.commit()
    for acc_id in account_ids:
        acc = db.get(Account, acc_id)
        if acc is not None:
            db.delete(acc)
    db.commit()


# ---------------------------------------------------------------------------
# exactly-one match -> paired
# ---------------------------------------------------------------------------

def test_exactly_one_match_pairs_both_legs(migration, db_session):
    from backend.models import Transaction

    day = datetime.date(2025, 3, 1)
    acc_a = _make_account(db_session, "ExactA")
    acc_b = _make_account(db_session, "ExactB")
    tx_ids: list[int] = []
    acc_ids = [acc_a, acc_b]
    try:
        leg_a = _make_transfer_tx(db_session, acc_a, -75000, day)
        leg_b = _make_transfer_tx(db_session, acc_b, 75000, day)
        tx_ids = [leg_a, leg_b]

        migration.retro_pair_transfers(db_session)
        db_session.commit()
        db_session.expire_all()

        a_row = db_session.get(Transaction, leg_a)
        b_row = db_session.get(Transaction, leg_b)
        expected_group = min(leg_a, leg_b)
        assert a_row.transfer_pair_id == expected_group
        assert b_row.transfer_pair_id == expected_group
    finally:
        _cleanup(db_session, tx_ids, acc_ids)


# ---------------------------------------------------------------------------
# zero match -> left NULL, flagged
# ---------------------------------------------------------------------------

def test_zero_match_stays_unpaired(migration, db_session):
    from backend.models import Transaction

    day = datetime.date(2025, 3, 2)
    acc_lone = _make_account(db_session, "LoneAcct")
    tx_ids: list[int] = []
    acc_ids = [acc_lone]
    try:
        lone = _make_transfer_tx(db_session, acc_lone, -42000, day)
        tx_ids = [lone]

        report = migration.retro_pair_transfers(db_session)
        db_session.commit()
        db_session.expire_all()

        lone_row = db_session.get(Transaction, lone)
        assert lone_row.transfer_pair_id is None
        assert lone in report["flagged_ids"]
    finally:
        _cleanup(db_session, tx_ids, acc_ids)


# ---------------------------------------------------------------------------
# multiple candidates -> ambiguous row left NULL, never guessed
# ---------------------------------------------------------------------------

def test_multiple_candidates_left_unpaired_never_guessed(migration, db_session):
    from backend.models import Transaction

    day = datetime.date(2025, 3, 3)
    acc_c = _make_account(db_session, "AmbigC")
    acc_a = _make_account(db_session, "AmbigA")
    acc_b = _make_account(db_session, "AmbigB")
    tx_ids: list[int] = []
    acc_ids = [acc_c, acc_a, acc_b]
    try:
        # C is a valid opposite-amount match for BOTH A and B -> ambiguous.
        tx_c = _make_transfer_tx(db_session, acc_c, 100000, day)
        tx_a = _make_transfer_tx(db_session, acc_a, -100000, day)
        tx_b = _make_transfer_tx(db_session, acc_b, -100000, day)
        tx_ids = [tx_c, tx_a, tx_b]

        migration.retro_pair_transfers(db_session)
        db_session.commit()
        db_session.expire_all()

        c_row = db_session.get(Transaction, tx_c)
        a_row = db_session.get(Transaction, tx_a)
        b_row = db_session.get(Transaction, tx_b)

        # The ambiguous row (2 candidates) is never guessed at.
        assert c_row.transfer_pair_id is None
        # Its would-be partners each had exactly one candidate (C), but since
        # C itself is ambiguous the pair is invalid on both sides -- neither
        # A nor B gets arbitrarily paired either.
        assert a_row.transfer_pair_id is None
        assert b_row.transfer_pair_id is None
    finally:
        _cleanup(db_session, tx_ids, acc_ids)


# ---------------------------------------------------------------------------
# idempotency
# ---------------------------------------------------------------------------

def test_rerunning_pairing_is_idempotent(migration, db_session):
    from backend.models import Transaction

    day = datetime.date(2025, 3, 4)
    acc_a = _make_account(db_session, "IdemA")
    acc_b = _make_account(db_session, "IdemB")
    tx_ids: list[int] = []
    acc_ids = [acc_a, acc_b]
    try:
        leg_a = _make_transfer_tx(db_session, acc_a, -30000, day)
        leg_b = _make_transfer_tx(db_session, acc_b, 30000, day)
        tx_ids = [leg_a, leg_b]

        first_report = migration.retro_pair_transfers(db_session)
        db_session.commit()
        assert first_report["pairs_backfilled"] >= 1

        second_report = migration.retro_pair_transfers(db_session)
        db_session.commit()
        db_session.expire_all()

        # Second pass touches zero already-paired rows.
        assert second_report["pairs_backfilled"] == 0
        assert leg_a not in second_report["flagged_ids"]
        assert leg_b not in second_report["flagged_ids"]

        a_row = db_session.get(Transaction, leg_a)
        b_row = db_session.get(Transaction, leg_b)
        expected_group = min(leg_a, leg_b)
        assert a_row.transfer_pair_id == expected_group
        assert b_row.transfer_pair_id == expected_group
    finally:
        _cleanup(db_session, tx_ids, acc_ids)
