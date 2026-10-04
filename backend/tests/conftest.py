"""
Shared pytest fixtures for the monai backend test suite.

Provides:
  client       — FastAPI TestClient for all HTTP-level tests (sync)
  async_client — httpx.AsyncClient for async endpoint tests (query-stream, proposals)
  api_key      — sets MONAI_API_KEY env var for tests that exercise write endpoints
  approver_key — sets MONAI_APPROVER_KEY for approve/reject tests; differs from api_key

Import-time note:
  backend.auth reads _CONFIGURED_KEY (from the MONAI_API_KEY env var, default
  "") at import time (module level). To override it in tests, either:
    1. Set the env var BEFORE importing backend.main (use monkeypatch + importlib.reload), or
    2. Patch backend.auth._CONFIGURED_KEY directly with monkeypatch.setattr().
  The api_key fixture uses option 2 (patch the already-loaded module attribute)
  so it works regardless of import order.

Test database:
  DATABASE_URL defaults to monai_test (never the live monai DB). The suite
  refuses to run if it resolves to exactly "monai" — no env var or flag can
  bypass this. monai_test is created (if missing) and migrated to head once
  per pytest process, before backend.main (and its engine) is imported. The
  three live-audit-only files (test_reconstruction.py,
  test_investment_reconstruction.py, test_net_worth_history.py) live outside
  this guard, in backend/tests_live_audit/, and are invoked manually against
  the live monai DB — never through this conftest.py.
"""

import os
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import make_url

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_TEST_URL = "postgresql+psycopg://monai:monai@localhost:5434/monai_test"
os.environ.setdefault("DATABASE_URL", _DEFAULT_TEST_URL)

_TEST_DB = make_url(os.environ["DATABASE_URL"])
# A query-string dbname= replaces the path database at connect time (the
# psycopg dialect merges url.query over it), so the path name checked below
# would not be the database actually used. Refuse it with any value — make_url
# silently drops an empty ?dbname=, hence the raw parse as well.
if "dbname" in _TEST_DB.query or "dbname" in parse_qs(
    urlsplit(os.environ["DATABASE_URL"]).query, keep_blank_values=True
):
    raise SystemExit(
        "Refusing to run: DATABASE_URL overrides the database with a "
        "query-string dbname=. Name the test database in the URL path only."
    )
if _TEST_DB.database == "monai":
    raise SystemExit(
        "Refusing to run the backend test suite against the live 'monai' "
        "database. Unset DATABASE_URL (it defaults to monai_test) or point "
        "it at a test database."
    )
if not _TEST_DB.database or not re.fullmatch(r"[A-Za-z0-9_]+", _TEST_DB.database):
    raise SystemExit(
        f"Refusing to run: DATABASE_URL names an invalid database "
        f"{_TEST_DB.database!r}. Database names must match [A-Za-z0-9_]+."
    )


def _ensure_test_database() -> None:
    """Create the test database on the compose Postgres if it doesn't exist yet.

    Runs CREATE DATABASE on an autocommit connection to the `postgres`
    maintenance database — Postgres refuses CREATE DATABASE inside a
    transaction block.
    """
    admin_engine = create_engine(
        _TEST_DB.set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    try:
        with admin_engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"),
                {"n": _TEST_DB.database},
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{_TEST_DB.database}"'))
    finally:
        admin_engine.dispose()


def _migrate_to_head() -> None:
    """Run `alembic upgrade head` against DATABASE_URL, once per pytest process.

    Imports the real, pip-installed alembic package rather than this repo's
    own alembic/ scaffold directory (env.py + versions/), which shares its
    top-level name and would otherwise shadow it once pytest has put the
    repo root on sys.path — mirrors test_category_migration.py's
    `_ensure_real_alembic_package` workaround for the identical problem.
    """
    cached = sys.modules.get("alembic")
    if cached is None or not hasattr(cached, "op"):
        if cached is not None:
            del sys.modules["alembic"]
        shadow_init = (_REPO_ROOT / "alembic" / "__init__.py").resolve()
        original_path = list(sys.path)
        try:
            sys.path = [
                p for p in sys.path
                if (Path(p or ".") / "alembic" / "__init__.py").resolve() != shadow_init
            ]
            import alembic  # noqa: F401 — repopulates sys.modules["alembic"] correctly
        finally:
            sys.path = original_path

    from alembic.config import Config
    from alembic import command

    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "alembic"))
    # Pass the raw, already-checked string — str(URL) renders the password as
    # *** in SQLAlchemy 2, which would break the connection.
    cfg.attributes["sqlalchemy.url"] = os.environ["DATABASE_URL"]
    command.upgrade(cfg, "head")


_ensure_test_database()
_migrate_to_head()

# --- only now is it safe to import the app: backend/db.py builds its engine
# from DATABASE_URL at import time, and that URL is now checked + migrated ---

import httpx
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from backend.main import app
from backend.db import engine as _app_engine

# Asks the server which database the app's engine is really connected to —
# the URL can say one thing while the connection lands elsewhere.
with _app_engine.connect() as _conn:
    _actual_db = _conn.execute(text("SELECT current_database()")).scalar()
if _actual_db == "monai" or _actual_db != _TEST_DB.database:
    raise SystemExit(
        f"Refusing to run: the app engine is connected to {_actual_db!r}, "
        f"expected the test database {_TEST_DB.database!r}."
    )

# ---------------------------------------------------------------------------
# Core fixture: one TestClient shared across the test session
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def client() -> TestClient:
    """Return a TestClient wrapping the monai FastAPI app."""
    return TestClient(app)


# ---------------------------------------------------------------------------
# Async fixture: httpx.AsyncClient for async endpoint tests
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def async_client():
    """httpx AsyncClient for testing async endpoints (query-stream, proposals)."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# Auth helper: patches _CONFIGURED_KEY on the already-loaded auth module
# ---------------------------------------------------------------------------

_TEST_API_KEY = "test-monai-api-key-fixture"


@pytest.fixture()
def api_key(monkeypatch: pytest.MonkeyPatch) -> str:
    """
    Set a known API key for the duration of a test.

    Patches backend.auth._CONFIGURED_KEY directly (the module-level singleton)
    so the require_api_key dependency sees a valid non-empty key.

    Returns the key string so tests can include it in request headers.
    """
    import backend.auth as auth_mod

    monkeypatch.setattr(auth_mod, "_CONFIGURED_KEY", _TEST_API_KEY)
    return _TEST_API_KEY


_TEST_APPROVER_KEY = "test-approver-key-fixture"


@pytest.fixture()
def approver_key(monkeypatch: pytest.MonkeyPatch) -> str:
    """Set a known MONAI_APPROVER_KEY (differs from the api_key fixture value)."""
    import backend.auth as auth_mod

    monkeypatch.setattr(auth_mod, "_CONFIGURED_APPROVER_KEY", _TEST_APPROVER_KEY)
    return _TEST_APPROVER_KEY


# ---------------------------------------------------------------------------
# Session teardown: purge test-created platforms from the shared monai_test DB.
#
# The suite runs against the shared monai_test DB and the various
# `_make_platform` helpers create Platform rows (plus holdings / value-history)
# but only clean up tickers — so every run used to leak Test*/*WTT/SnapPlat*/zz*
# platforms.
# This one autouse fixture removes them all after the session, regardless of
# which test file created them or how. Deletes run in FK order
# (value_history -> events -> holdings -> platforms) and are fully guarded:
# an unavailable DB never fails the suite.
# ---------------------------------------------------------------------------

# Name LIKE patterns + kind used exclusively by test-created platforms. Real
# platforms (Bibit/Binance/Bitget/Pluang/Stockbit) match none of these.
_TEST_PLATFORM_NAME_PATTERNS = ("Test%", "%WTT%", "MultiPlatform%", "SnapPlat%", "zz%", "ZZ%")


@pytest.fixture(scope="session", autouse=True)
def _purge_test_platforms():
    """Delete every test-created platform (and its dependents) after the run."""
    yield  # run all tests first
    try:
        from sqlalchemy import text
        from backend.db import SessionLocal
    except Exception:
        return

    try:
        db = SessionLocal()
    except Exception:
        return
    try:
        name_clause = " OR ".join(f"name LIKE :p{i}" for i in range(len(_TEST_PLATFORM_NAME_PATTERNS)))
        params = {f"p{i}": pat for i, pat in enumerate(_TEST_PLATFORM_NAME_PATTERNS)}
        ids = db.execute(
            text(f"SELECT id FROM platforms WHERE kind = 'test' OR {name_clause}"), params
        ).scalars().all()
        if not ids:
            return
        for tbl in ("portfolio_value_history", "portfolio_events", "holdings", "platforms"):
            col = "id" if tbl == "platforms" else "platform_id"
            db.execute(text(f"DELETE FROM {tbl} WHERE {col} = ANY(:ids)"), {"ids": ids})
        db.commit()
    except Exception:
        db.rollback()  # test-DB hygiene must never fail the suite
    finally:
        db.close()
