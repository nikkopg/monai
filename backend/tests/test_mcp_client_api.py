"""Phase 41 /mcp-servers routes. Synthetic hosts and secrets; the isolated monai_test DB only."""
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from backend.db import SessionLocal

C1, C2, C3 = "zz-canary-secret-0001", "zz-canary-secret-0002", "zz-canary-secret-0003"


def _purge():
    with SessionLocal() as db:
        db.execute(text("DELETE FROM mcp_servers WHERE slug LIKE 'zz-%'"))
        db.execute(text("DELETE FROM audit_log WHERE entity = 'mcp_server' AND after->>'slug' LIKE 'zz-%'"))
        db.commit()


@pytest.fixture()
def env(client, api_key):
    _purge()
    yield SimpleNamespace(client=client, h={"MONAI_API_KEY": api_key})
    _purge()


def _http(slug="zz-notes", **over):
    body = {"slug": slug, "transport": "http", "url": f"https://notes.example.com/mcp?token={C1}",
            "headers": [{"name": "Authorization", "value": f"Bearer {C2}"}]}
    return {**body, **over}


def _stdio(slug="zz-local", **over):
    body = {"slug": slug, "transport": "stdio", "command": "npx", "args": ["@example/notes-mcp@1.2.3"],
            "env": [{"name": "ZZ_TOKEN", "value": C3}], "acknowledged_local_read": True}
    return {**body, **over}


def _add(env, body):
    return env.client.post("/mcp-servers", json=body, headers=env.h)


def _row(slug):
    with SessionLocal() as db:
        return db.execute(text(
            "SELECT id, transport, url, headers, command, args, env, enabled FROM mcp_servers WHERE slug = :s"),
            {"s": slug}).mappings().first()


def _audit():
    with SessionLocal() as db:
        return [dict(r) for r in db.execute(text(
            "SELECT operation, before, after FROM audit_log WHERE entity = 'mcp_server' "
            "AND after->>'slug' LIKE 'zz-%' ORDER BY id")).mappings()]


def test_crud_routes_need_the_api_key(env):
    c = env.client
    assert c.get("/mcp-servers").status_code == 401
    assert c.post("/mcp-servers", json=_http()).status_code == 401
    assert c.put("/mcp-servers/00000000-0000-0000-0000-000000000000", json={}).status_code == 401
    assert c.delete("/mcp-servers/00000000-0000-0000-0000-000000000000").status_code == 401


def test_crud_create_list_update_delete(env):
    r = _add(env, _http())
    assert r.status_code == 201 and r.json()["enabled"] is False
    sid = r.json()["id"]
    listed = env.client.get("/mcp-servers", headers=env.h).json()
    assert [s["slug"] for s in listed if s["slug"].startswith("zz-")] == ["zz-notes"]
    # slug and transport in a PUT body are dropped
    r = env.client.put(f"/mcp-servers/{sid}", headers=env.h,
                       json={"slug": "zz-other", "transport": "stdio", "url": "https://other.example.com/mcp"})
    assert r.status_code == 200 and r.json()["slug"] == "zz-notes" and r.json()["transport"] == "http"
    assert _row("zz-notes")["url"] == "https://other.example.com/mcp"
    missing = "00000000-0000-0000-0000-000000000000"
    assert env.client.put(f"/mcp-servers/{missing}", json={}, headers=env.h).status_code == 404
    assert env.client.delete(f"/mcp-servers/{missing}", headers=env.h).status_code == 404
    assert env.client.delete(f"/mcp-servers/{sid}", headers=env.h).json() == {"deleted": "zz-notes"}
    assert _row("zz-notes") is None
    assert "zz-notes" not in [s["slug"] for s in env.client.get("/mcp-servers", headers=env.h).json()]


def test_mask_hides_every_secret_and_keeps_stored_ones(env):
    r = _add(env, _http())
    sid = r.json()["id"]
    got = next(s for s in env.client.get("/mcp-servers", headers=env.h).json() if s["id"] == sid)
    assert got["url"] == "https://notes.example.com/mcp?••••"
    assert got["headers"] == [{"name": "Authorization", "value_masked": "••••0002"}]
    assert got["destination"] == "notes.example.com" and got["changed_count"] is None
    assert C1 not in json.dumps(got) and C2 not in json.dumps(got) and C1 not in r.text and C2 not in r.text
    before = _row("zz-notes")
    masked = {"headers": [{"name": "Authorization", "value": "••••0002"}]}
    assert env.client.put(f"/mcp-servers/{sid}", json=masked, headers=env.h).status_code == 200
    assert _row("zz-notes")["headers"] == before["headers"]
    new = {"headers": [{"name": "Authorization", "value": "Bearer zz-canary-secret-9999"}]}
    env.client.put(f"/mcp-servers/{sid}", json=new, headers=env.h)
    assert _row("zz-notes")["headers"] == {"Authorization": "Bearer zz-canary-secret-9999"}
    # a masked value for a header that was never stored is refused
    bad = {"headers": [{"name": "X-Other", "value": "••••0002"}]}
    assert env.client.put(f"/mcp-servers/{sid}", json=bad, headers=env.h).status_code == 422
    # omitting the row removes it
    env.client.put(f"/mcp-servers/{sid}", json={"headers": []}, headers=env.h)
    assert _row("zz-notes")["headers"] == {}


def test_mask_stdio_env_values(env):
    sid = _add(env, _stdio()).json()["id"]
    got = next(s for s in env.client.get("/mcp-servers", headers=env.h).json() if s["id"] == sid)
    assert got["env"] == [{"name": "ZZ_TOKEN", "value_masked": "••••0003"}]
    assert got["destination"] == "local command: npx @example/notes-mcp@1.2.3"
    assert C3 not in json.dumps(got)


def test_stdio_ack_needed_on_create_and_on_command_change(env):
    assert _add(env, _stdio(acknowledged_local_read=False)).status_code == 422
    assert _row("zz-local") is None
    sid = _add(env, _stdio()).json()["id"]
    put = lambda body: env.client.put(f"/mcp-servers/{sid}", json=body, headers=env.h)  # noqa: E731
    assert put({"args": ["@example/other-mcp@2.0.0"]}).status_code == 422
    assert put({"args": ["@example/other-mcp@2.0.0"], "acknowledged_local_read": True}).status_code == 200
    assert _row("zz-local")["args"] == ["@example/other-mcp@2.0.0"]
    # env alone needs no acknowledgement
    assert put({"env": [{"name": "ZZ_TOKEN", "value": "zz-new-value"}]}).status_code == 200


@pytest.mark.parametrize("body", [
    _stdio(command="bash"),
    _stdio(url="https://notes.example.com/mcp"),
    _stdio(args=[]),
    _http(url=None),
    _http(url="https://user:pw@notes.example.com/mcp"),
    _http(url="https://@notes.example.com/mcp"),
    _http(url="ftp://notes.example.com/mcp"),
    _http(url="notes.example.com"),
    _stdio(env=[{"name": "PATH", "value": "x"}]),
    _stdio(env=[{"name": "LD_PRELOAD", "value": "x"}]),
    _stdio(env=[{"name": "HOME", "value": "x"}]),
    _http(slug="zz_notes"),
    _http(slug="zz-" + "a" * 22),
    _stdio(headers=[{"name": "Authorization", "value": "x"}]),
    _http(env=[{"name": "ZZ_TOKEN", "value": "x"}]),
    _http(headers=[{"name": "Bad Name", "value": "x"}]),
    _http(headers=[{"name": "Authorization", "value": "••••0002"}]),
])
def test_validation_refuses_unsafe_input(env, body):
    assert _add(env, body).status_code == 422


def test_validation_duplicate_slug(env):
    assert _add(env, _http()).status_code == 201
    r = _add(env, _http())
    assert r.status_code == 422 and "already used" in r.json()["detail"]


def test_audit_rows_hold_names_and_counts_only(env):
    sid = _add(env, _http()).json()["id"]
    _add(env, _stdio())
    env.client.put(f"/mcp-servers/{sid}", headers=env.h,
                   json={"headers": [{"name": "Authorization", "value": "Bearer zz-canary-secret-8888"}]})
    env.client.delete(f"/mcp-servers/{sid}", headers=env.h)
    rows = _audit()
    assert [r["operation"] for r in rows] == ["create", "create", "update", "delete"]
    blob = json.dumps(rows)
    for secret in (C1, C2, C3, "zz-canary-secret-8888", "https://", "token="):
        assert secret not in blob
    assert rows[0]["after"]["header_names"] == ["Authorization"]
    assert rows[1]["after"]["acknowledged_local_read"] is True and rows[1]["after"]["arg_count"] == 1
