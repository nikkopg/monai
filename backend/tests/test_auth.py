"""
Auth tests — require_api_key dependency.

Tests:
  (a) POST /transactions without header → 401
  (b) POST /transactions with wrong key → 401
  (c) POST /transactions with correct key → not 401 (422 from body validation, proves key accepted)
  (d) GET /accounts without key → 200 (public)
  (e) POST /query without key → not 401 (public)

Note on test (c): We POST with an incomplete body to trigger 422 from body validation rather
than writing to the live DB. A valid key yields 422 (body rejected before DB), while a wrong
or missing key yields 401 (auth rejects before body is inspected). This proves the key was
accepted without mutating any data.

Note on _CONFIGURED_KEY: backend.auth reads _CONFIGURED_KEY at import time from os.environ.
The `api_key` fixture (conftest.py) patches backend.auth._CONFIGURED_KEY directly after import
so the dependency sees a valid non-empty key regardless of import order.
"""

import pytest


# ---------------------------------------------------------------------------
# (a) Missing header → 401
# ---------------------------------------------------------------------------


def test_post_transactions_missing_key_returns_401(client, api_key):
    """No MONAI_API_KEY header → auth dependency raises 401."""
    resp = client.post("/transactions", json={"some": "data"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# (b) Wrong header value → 401
# ---------------------------------------------------------------------------


def test_post_transactions_wrong_key_returns_401(client, api_key):
    """Wrong MONAI_API_KEY value → 401 (hmac.compare_digest constant-time)."""
    resp = client.post(
        "/transactions",
        json={"some": "data"},
        headers={"MONAI_API_KEY": "wrong-key-value"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# (c) Correct key + incomplete body → 422 (proves key was accepted, not 401)
# ---------------------------------------------------------------------------


def test_post_transactions_valid_key_not_401(client, api_key):
    """
    Correct key → auth passes; incomplete body → 422 from Pydantic validation.
    Asserts status_code != 401 to confirm the key was accepted.
    Does NOT send a complete payload — avoids writing to the live DB.
    """
    resp = client.post(
        "/transactions",
        json={},  # Intentionally incomplete — triggers 422, not a DB write
        headers={"MONAI_API_KEY": api_key},
    )
    assert resp.status_code != 401
    # 422 is expected (body validation fails), but the key was accepted
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# (d) GET /accounts without key → 200 (public read)
# ---------------------------------------------------------------------------


def test_get_accounts_public_no_key(client):
    """GET endpoints require no API key — reads stay public (D-06)."""
    resp = client.get("/accounts")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# (e) POST /query without key → not 401 (public, D-06)
# ---------------------------------------------------------------------------


def test_post_query_public_no_key(client, api_key):
    """
    POST /query is a read-only operation and MUST remain public (D-06).
    No key header → must not return 401.
    We use api_key fixture only to ensure _CONFIGURED_KEY is non-empty (fail-closed guard);
    the request deliberately omits the header to verify /query has no auth gate.
    """
    resp = client.post("/query", json={"question": "health check"})
    assert resp.status_code != 401


# ---------------------------------------------------------------------------
# (f) POST /import without key → 401
# ---------------------------------------------------------------------------


def test_post_import_missing_key_returns_401(client, api_key):
    """POST /import is a write endpoint — must require auth (D-06)."""
    resp = client.post("/import", files={"file": ("test.csv", b"data", "text/csv")})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# (g) POST /import with wrong key → 401
# ---------------------------------------------------------------------------


def test_post_import_wrong_key_returns_401(client, api_key):
    """Wrong key on /import → 401."""
    resp = client.post(
        "/import",
        files={"file": ("test.csv", b"data", "text/csv")},
        headers={"MONAI_API_KEY": "wrong-key"},
    )
    assert resp.status_code == 401
