"""
Nyquist Wave 0 scaffold for Phase 12 (ACCT-03) — typed accounts.

Encodes Criterion 1 (D-02 classification, zero NULL), the CHECK+default
constraint (`accounts.type` becomes a real discriminator), and Criterion 3
(transfer/funding pairing columns on transactions and portfolio_events).

All four tests run against the LIVE dev DB via the `backend.db.engine`
singleton (no fresh-migrate fixture exists in conftest.py). They are
INTENTIONALLY RED until migration 010_typed_accounts.py lands (Plan 02):
  - test_account_type_map lazy-loads the migration module INSIDE the test
    body, so collection succeeds today and the test simply fails
    (FileNotFoundError) until the file exists.
  - test_account_classification / test_pairing_columns query/introspect
    live state that migration 010 has not yet created — they fail on
    assertion, never on collection.
  - test_type_check_and_default proves the CHECK constraint and server
    default do not exist yet (IntegrityError does NOT raise pre-migration).
"""

import importlib.util
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from backend.db import engine

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2] / "alembic" / "versions" / "010_typed_accounts.py"
)
REPO_ROOT = MIGRATION_PATH.parents[2]


def _ensure_real_alembic_package() -> None:
    """Bypass this repo's own `alembic/` scaffold directory (env.py +
    versions/), which shares its top-level name with the pip-installed
    `alembic` package. pytest's import mode prepends the repo root onto
    sys.path (neither `backend/` nor `backend/tests/` reaches a directory
    lacking `__init__.py` until the repo root), so a plain `import alembic`
    resolves to the local scaffold (no `op` attribute) instead of the real
    package once test collection has run. Copied verbatim from
    test_category_migration.py's required workaround (Rule 3 — blocking
    import issue).
    """
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
        import alembic  # noqa: F401  (populates sys.modules["alembic"] correctly)
    finally:
        sys.path = original_path
    if not hasattr(sys.modules.get("alembic"), "op"):
        raise ImportError(
            "could not resolve the installed alembic package (only found this "
            f"repo's own scaffold at {shadow_init})"
        )


def _load_migration_010():
    """Load 010_typed_accounts.py as a standalone module via importlib.

    Called INSIDE the test body (not at module scope) so collection succeeds
    before the migration file exists — the RED-phase failure (missing file)
    surfaces as a test failure, not a collection error.
    """
    _ensure_real_alembic_package()
    spec = importlib.util.spec_from_file_location("migration_010", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load migration spec from {MIGRATION_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Criterion 1 — D-02 classification
# ---------------------------------------------------------------------------


def test_account_type_map():
    """The migration's audited backfill map matches D-02 exactly."""
    migration = _load_migration_010()
    assert migration.ACCOUNT_TYPE == {1: "liquid", 2: "liquid", 3: "investment", 559: "liquid"}


def test_account_classification():
    """Every live accounts row is classified: no NULLs, and the 4 audited
    ids land on the exact D-02 type."""
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, type FROM accounts")).fetchall()
    types_by_id = {row[0]: row[1] for row in rows}

    assert all(t in {"liquid", "investment"} for t in types_by_id.values()), (
        f"non-liquid/investment types present: {types_by_id}"
    )
    null_count = sum(1 for t in types_by_id.values() if t is None)
    assert null_count == 0, f"{null_count} accounts still have type IS NULL"

    assert types_by_id.get(1) == "liquid"
    assert types_by_id.get(2) == "liquid"
    assert types_by_id.get(559) == "liquid"
    assert types_by_id.get(3) == "investment"


# ---------------------------------------------------------------------------
# CHECK + server default
# ---------------------------------------------------------------------------


def test_type_check_and_default():
    """`type` is a real DB-enforced discriminator: CHECK rejects unknown
    values, and omitting it defaults to 'liquid'. Both probes roll back so
    the live DB is unchanged."""
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            with pytest.raises(IntegrityError):
                conn.execute(
                    text(
                        "INSERT INTO accounts (name, type, currency) "
                        "VALUES (:n, 'bogus', 'IDR')"
                    ),
                    {"n": "zz-typed-accounts-check-test"},
                )
        finally:
            trans.rollback()

    with engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.execute(
                text("INSERT INTO accounts (name, currency) VALUES (:n, 'IDR')"),
                {"n": "zz-typed-accounts-default-test"},
            )
            result = conn.execute(
                text("SELECT type FROM accounts WHERE name = :n"),
                {"n": "zz-typed-accounts-default-test"},
            ).scalar()
            assert result == "liquid"
        finally:
            trans.rollback()


# ---------------------------------------------------------------------------
# Criterion 3 — transfer/funding pairing columns
# ---------------------------------------------------------------------------


def test_pairing_columns():
    """transactions.transfer_pair_id and portfolio_events.source_account_id
    exist, are nullable, and are indexed."""
    insp = sa.inspect(engine)

    tx_cols = {c["name"]: c for c in insp.get_columns("transactions")}
    assert "transfer_pair_id" in tx_cols
    assert tx_cols["transfer_pair_id"]["nullable"] is True
    tx_indexed_cols = {
        col for idx in insp.get_indexes("transactions") for col in idx["column_names"]
    }
    assert "transfer_pair_id" in tx_indexed_cols

    pe_cols = {c["name"]: c for c in insp.get_columns("portfolio_events")}
    assert "source_account_id" in pe_cols
    assert pe_cols["source_account_id"]["nullable"] is True
    pe_indexed_cols = {
        col for idx in insp.get_indexes("portfolio_events") for col in idx["column_names"]
    }
    assert "source_account_id" in pe_indexed_cols
