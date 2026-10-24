"""
Auth tests — require_api_key dependency.

Tests:
  (a) POST /transactions without header → 401
  (b) POST /transactions with wrong key → 401
  (c) POST /transactions with correct key → not 401 (422 from body validation, proves key accepted)
  (d) GET /accounts requires the key: 401 without/wrong, 200 with, 503 unconfigured (Phase 40.1)
  (e) POST /query-stream requires the key (401 without/wrong, 503 unconfigured; agent stream stubbed)
  (h) POST /transactions with empty _CONFIGURED_KEY → 503 JSON error (fail-closed misconfiguration)
  (i) GET /health is the only open route and returns exactly {"status": "ok"} (Phase 40.1)
  (j) a walker over every APIRoute, including included routers, fails closed for any route
      that lacks a key dependency (Phase 40.1)

Note on test (c): We POST with an incomplete body to trigger 422 from body validation rather
than writing to the live DB. A valid key yields 422 (body rejected before DB), while a wrong
or missing key yields 401 (auth rejects before body is inspected). This proves the key was
accepted without mutating any data.

Note on _CONFIGURED_KEY: backend.auth reads _CONFIGURED_KEY at import time from os.environ.
The `api_key` fixture (conftest.py) patches backend.auth._CONFIGURED_KEY directly after import
so the dependency sees a valid non-empty key regardless of import order.
"""

import json

import pytest
from fastapi.routing import APIRoute


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
# (d) GET /accounts requires the key (Phase 40.1 supersedes the v1.0 public GETs)
# ---------------------------------------------------------------------------


def test_get_accounts_requires_key(client, api_key, monkeypatch):
    """401 without/wrong key, 200 with it, 503 when unconfigured; auth runs before validation."""
    import backend.auth as auth_mod

    assert client.get("/accounts").status_code == 401
    assert client.get("/accounts", headers={"MONAI_API_KEY": "wrong"}).status_code == 401
    assert client.get("/accounts", headers={"MONAI_API_KEY": api_key}).status_code == 200
    # Auth runs before query validation: a bad query is 401, not 422.
    assert client.get("/cashflow/networth-history?months=0").status_code == 401

    monkeypatch.setattr(auth_mod, "_CONFIGURED_KEY", "")
    assert client.get("/accounts", headers={"MONAI_API_KEY": api_key}).status_code == 503


# ---------------------------------------------------------------------------
# (e) POST /query-stream requires the key (REL-08, D-18)
# ---------------------------------------------------------------------------


def test_post_query_stream_requires_key(client, api_key, monkeypatch):
    """The chat stream is no longer a public LLM/DB endpoint (D-18).

    agent_stream is stubbed so no LLM or network is touched.
    """
    import backend.auth as auth_mod
    import backend.query as query_mod

    monkeypatch.setattr(query_mod, "_ACTIVE", {})
    monkeypatch.setattr(query_mod, "_LAST", {})

    async def _stub_stream(question, **kw):
        yield "data: " + json.dumps({
            "type": "answer",
            "text": "stub answer",
            "trace": [],
            "proposals": [],
            "proposal_id": None,
            "proposal_token": None,
        }) + "\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr("backend.query.agent_stream", _stub_stream)
    body = {"question": "health check"}

    assert client.post("/query-stream", json=body).status_code == 401
    assert client.post(
        "/query-stream", json=body, headers={"MONAI_API_KEY": "wrong"}
    ).status_code == 401

    resp = client.post("/query-stream", json=body, headers={"MONAI_API_KEY": api_key})
    assert resp.status_code == 200
    assert '"type": "thread"' in resp.text
    assert '"type": "run"' in resp.text
    assert "stub answer" in resp.text
    assert "[DONE]" in resp.text

    monkeypatch.setattr(auth_mod, "_CONFIGURED_KEY", "")
    assert client.post(
        "/query-stream", json=body, headers={"MONAI_API_KEY": api_key}
    ).status_code == 503


def test_cancel_requires_key(client, api_key, monkeypatch):
    import uuid

    import backend.query as query_mod

    monkeypatch.setattr(query_mod, "_ACTIVE", {})
    monkeypatch.setattr(query_mod, "_LAST", {})
    url = f"/query-stream/{uuid.uuid4()}/cancel"

    assert client.post(url).status_code == 401
    assert client.post(url, headers={"MONAI_API_KEY": api_key}).status_code == 404
    assert client.post(
        "/query-stream/not-a-uuid/cancel", headers={"MONAI_API_KEY": api_key}
    ).status_code == 422


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


# ---------------------------------------------------------------------------
# (h) Empty _CONFIGURED_KEY (server misconfigured) → 503 JSON error
# ---------------------------------------------------------------------------


def test_empty_configured_key_returns_503(client, monkeypatch):
    """
    Server misconfigured (MONAI_API_KEY unset/empty) → require_api_key raises
    HTTPException(503) with a JSON detail, not an opaque text/plain 500.

    Needs no DB: the empty-key guard is the FIRST check in require_api_key
    and rejects the request before any route handler or DB access runs.
    """
    import backend.auth as auth_mod

    monkeypatch.setattr(auth_mod, "_CONFIGURED_KEY", "")

    resp = client.post(
        "/transactions",
        json={},
        headers={"MONAI_API_KEY": "anything"},
    )
    assert resp.status_code == 503
    assert "misconfigured" in resp.json()["detail"].lower()


def test_thread_routes_require_key(client, api_key, monkeypatch):
    import uuid

    import backend.auth as auth_mod

    tid = uuid.uuid4()
    calls = [
        ("get", "/threads"),
        ("get", f"/threads/{tid}"),
        ("patch", f"/threads/{tid}"),
        ("delete", f"/threads/{tid}"),
        ("get", f"/threads/{tid}/stream"),
        ("post", f"/threads/{tid}/compact"),
        ("post", f"/threads/{tid}/clear"),
    ]
    for method, url in calls:
        kw = {"json": {"title": "ZZTest t"}} if method == "patch" else {}
        assert getattr(client, method)(url, **kw).status_code == 401, (method, url)
        assert getattr(client, method)(
            url, headers={"MONAI_API_KEY": "wrong"}, **kw
        ).status_code == 401, (method, url)

    monkeypatch.setattr(auth_mod, "_CONFIGURED_KEY", "")
    assert client.get("/threads", headers={"MONAI_API_KEY": api_key}).status_code == 503


def test_every_thread_route_depends_on_api_key():
    from backend.auth import require_api_key
    from backend.main import app

    routes = [r for r in app.routes if getattr(r, "path", "").startswith("/threads")]
    assert len(routes) == 7
    for r in routes:
        assert require_api_key in [d.call for d in r.dependant.dependencies], r.path


# ---------------------------------------------------------------------------
# (i) /health is open and carries no ledger data
# ---------------------------------------------------------------------------


def test_health_is_open_and_carries_no_ledger_data(client, monkeypatch):
    import backend.auth as auth_mod

    monkeypatch.setattr(auth_mod, "_CONFIGURED_KEY", "")
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# (j) Guard walker: every route needs a key, except the allowlist
# ---------------------------------------------------------------------------

_OPEN = {("GET", "/health")}
# Starlette routes that are not APIRoutes: schema/docs pages carry no ledger data
# (Phase 40.1 OQ-1), and /mcp is a mount with its own middleware guard.
_NON_API = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc", "/mcp"}


def _api_routes(routes, inherited=()):
    for r in routes:
        inner = getattr(r, "original_router", None)  # FastAPI >= 0.14x _IncludedRouter wrapper
        if inner is not None:
            ctx = getattr(r, "include_context", None)
            yield from _api_routes(
                inner.routes, (*inherited, *(getattr(ctx, "dependencies", None) or []))
            )
        elif isinstance(r, APIRoute):  # older FastAPI flattens, so this covers both shapes
            yield r, inherited


def _calls(dep):
    yield dep.call
    for d in dep.dependencies:
        yield from _calls(d)


def test_every_route_requires_a_key_or_is_allowlisted():
    import backend.auth as auth
    from backend.main import app

    # optional_approver never raises, so it is deliberately not in this set.
    auth_deps = {auth.require_api_key, auth.require_approver_key, auth.require_reject_scope}
    seen, bad = 0, []
    for r, inherited in _api_routes(app.routes):
        seen += 1
        calls = set(_calls(r.dependant)) | {d.dependency for d in inherited}
        if not calls & auth_deps:
            bad += [(m, r.path) for m in r.methods if (m, r.path) not in _OPEN]
    assert seen > 60, "walker lost the included routers"
    assert not bad, f"unauthenticated routes: {sorted(bad)}"
    others = {
        getattr(r, "path", None)
        for r in app.routes
        if not isinstance(r, APIRoute) and getattr(r, "original_router", None) is None
    }
    assert others <= _NON_API, others - _NON_API
