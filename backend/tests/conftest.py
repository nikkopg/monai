"""
Shared pytest fixtures for the monai backend test suite.

Provides:
  client       — FastAPI TestClient for all HTTP-level tests (sync)
  async_client — httpx.AsyncClient for async endpoint tests (query-stream, proposals)
  api_key      — sets MONAI_API_KEY env var for tests that exercise write endpoints

Import-time note:
  backend.auth reads _CONFIGURED_KEY = os.environ.get("MONAI_API_KEY", "") at import
  time (module level). To override it in tests, either:
    1. Set the env var BEFORE importing backend.main (use monkeypatch + importlib.reload), or
    2. Patch backend.auth._CONFIGURED_KEY directly with monkeypatch.setattr().
  The api_key fixture uses option 2 (patch the already-loaded module attribute)
  so it works regardless of import order.
"""

import httpx
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from backend.main import app

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


# ---------------------------------------------------------------------------
# Session teardown: purge test-created platforms from the shared dev DB.
#
# The suite runs against the live dev DB and the various `_make_platform`
# helpers create Platform rows (plus holdings / value-history) but only clean
# up tickers — so every run used to leak Test*/*WTT/SnapPlat*/zz* platforms.
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
