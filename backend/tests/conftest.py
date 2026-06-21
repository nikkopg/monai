"""
Shared pytest fixtures for the monai backend test suite.

Provides:
  client    — FastAPI TestClient for all HTTP-level tests
  api_key   — sets MONAI_API_KEY env var for tests that exercise write endpoints

Import-time note:
  backend.auth reads _CONFIGURED_KEY = os.environ.get("MONAI_API_KEY", "") at import
  time (module level). To override it in tests, either:
    1. Set the env var BEFORE importing backend.main (use monkeypatch + importlib.reload), or
    2. Patch backend.auth._CONFIGURED_KEY directly with monkeypatch.setattr().
  The api_key fixture uses option 2 (patch the already-loaded module attribute)
  so it works regardless of import order.
"""

import pytest
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
