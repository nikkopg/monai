"""Phase 41 /mcp-servers routes. Synthetic hosts and secrets; the isolated monai_test DB only."""
import json
import uuid
from types import SimpleNamespace

import pytest
from fastmcp.client.transports import FastMCPTransport
from sqlalchemy import text

from backend import chat_service, mcp_client
from backend.db import SessionLocal
from backend.evals import ext_test_server

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


# ── Task 2: test, enable, policy, selection ─────────────────────────────────

@pytest.fixture()
def live(env, monkeypatch):
    """Serve the synthetic in-memory server; `live.variant` picks what it offers."""
    live = SimpleNamespace(**vars(env), variant="base", fail=False, threads=[])

    def fake_transport(spec):
        if live.fail:
            raise OSError("boom https://secret.example.com/path")
        return FastMCPTransport(ext_test_server.build(live.variant))

    monkeypatch.setattr(mcp_client, "build_transport", fake_transport)
    yield live
    with SessionLocal() as db:
        for t in live.threads:
            db.execute(text("DELETE FROM threads WHERE id = :i"), {"i": t})
        db.commit()


def _server(live):
    return _add(live, _http()).json()["id"]


def _test(live, sid):
    return live.client.post(f"/mcp-servers/{sid}/test", headers=live.h)


def _enable(live, sid, **body):
    return live.client.put(f"/mcp-servers/{sid}/enabled", json={"enabled": True, **body}, headers=live.h)


def _state(slug):
    with SessionLocal() as db:
        return db.execute(text(
            "SELECT enabled, approved_tools, tool_policies, changed_count FROM mcp_servers WHERE slug = :s"),
            {"s": slug}).mappings().first()


def test_route_test_lists_every_tool_and_stores_nothing(live):
    sid = _server(live)
    r = _test(live, sid)
    assert r.status_code == 200
    body = r.json()
    names = {t["name"] for t in body["tools"]}
    assert {"echo", "add", "lookup", "send", "env_dump", "slow", "nested", "bare"} <= names
    assert {t["status"] for t in body["tools"]} == {"new"} and all(t["usable_name"] for t in body["tools"])
    echo = next(t for t in body["tools"] if t["name"] == "echo")
    assert echo["description"] == "Echo the text back." and echo["input_schema"]["properties"]["text"]
    assert body["removed"] == [] and body["policies"] == {} and len(body["tools_hash"]) == 64
    st = _state("zz-notes")
    assert st["enabled"] is False and st["approved_tools"] == [] and st["changed_count"] is None


def test_enable_binds_to_the_hash_and_stores_the_reviewed_list(live):
    sid = _server(live)
    first = _test(live, sid).json()
    assert _enable(live, sid, tools_hash=first["tools_hash"]).status_code == 200
    st = _state("zz-notes")
    assert st["enabled"] is True and st["changed_count"] == 0
    by_name = {a["name"]: a for a in st["approved_tools"]}
    assert set(by_name) == {t["name"] for t in first["tools"]}
    echo = next(t for t in first["tools"] if t["name"] == "echo")
    assert by_name["echo"]["sha256"] and by_name["echo"]["description"] == echo["description"]
    assert by_name["echo"]["inputSchema"] == echo["input_schema"]
    listed = next(s for s in live.client.get("/mcp-servers", headers=live.h).json() if s["id"] == sid)
    assert listed["enabled"] is True and listed["changed_count"] == 0


def test_hash_mismatch_is_409_and_stores_nothing(live):
    sid = _server(live)
    old = _test(live, sid).json()["tools_hash"]
    _enable(live, sid, tools_hash=old)
    live.variant = "changed"
    t = _test(live, sid).json()
    assert {x["name"]: x["status"] for x in t["tools"]}["echo"] == "changed"
    assert [x["name"] for x in t["tools"] if x["status"] != "unchanged"] == ["echo"]
    assert _state("zz-notes")["changed_count"] == 1
    before = _state("zz-notes")["approved_tools"]
    r = _enable(live, sid, tools_hash=old)
    assert r.status_code == 409 and _state("zz-notes")["approved_tools"] == before
    assert _enable(live, sid, tools_hash=t["tools_hash"]).status_code == 200
    assert _state("zz-notes")["changed_count"] == 0


def test_changed_extra_tool_is_new_and_a_lost_tool_is_removed(live):
    sid = _server(live)
    _enable(live, sid, tools_hash=_test(live, sid).json()["tools_hash"])
    live.variant = "extra"
    t = _test(live, sid).json()
    assert {x["name"]: x["status"] for x in t["tools"]}["zz_new"] == "new"
    with SessionLocal() as db:
        db.execute(text(
            "UPDATE mcp_servers SET approved_tools = approved_tools || "
            "'[{\"name\": \"gone\", \"description\": \"\", \"inputSchema\": {}, \"sha256\": \"x\"}]'::jsonb "
            "WHERE slug = 'zz-notes'"))
        db.commit()
    assert _test(live, sid).json()["removed"] == ["gone"]


def test_enable_edge_cases(live):
    sid = _server(live)
    assert _enable(live, sid).status_code == 422
    _enable(live, sid, tools_hash=_test(live, sid).json()["tools_hash"])
    live.fail = True  # disabling never connects
    r = live.client.put(f"/mcp-servers/{sid}/enabled", json={"enabled": False}, headers=live.h)
    assert r.status_code == 200 and _state("zz-notes")["enabled"] is False
    ops = [a["operation"] for a in _audit()]
    assert ops == ["create", "enable", "disable"]
    missing = "00000000-0000-0000-0000-000000000000"
    assert live.client.put(f"/mcp-servers/{missing}/enabled", json={"enabled": False}, headers=live.h).status_code == 404
    assert live.client.post(f"/mcp-servers/{missing}/test", headers=live.h).status_code == 404


def test_route_test_failure_copy_has_no_url(live):
    sid = _server(live)
    live.fail = True
    r = _test(live, sid)
    assert r.status_code == 502 and r.json()["detail"] == "Couldn't connect (OSError)"
    assert "example.com" not in r.text and "boom" not in r.text
    live.fail, live.variant = False, "many"
    r = _test(live, sid)
    assert r.status_code == 422 and r.json()["detail"] == "This server offers more than 200 tools."


def test_policy_per_tool_with_audit(live):
    sid = _server(live)
    put = lambda tool, policy: live.client.put(  # noqa: E731
        f"/mcp-servers/{sid}/tools/{tool}", json={"policy": policy}, headers=live.h)
    assert put("echo", "always").status_code == 200
    assert _state("zz-notes")["tool_policies"] == {"echo": "always"}
    assert put("echo", "deny").status_code == 200 and put("add", "ask").status_code == 200
    assert put("echo", "sometimes").status_code == 422
    missing = "00000000-0000-0000-0000-000000000000"
    r = live.client.put(f"/mcp-servers/{missing}/tools/echo", json={"policy": "ask"}, headers=live.h)
    assert r.status_code == 404
    assert live.client.put(f"/mcp-servers/{sid}/tools/{'t' * 129}", json={"policy": "ask"},
                           headers=live.h).status_code == 422
    rows = [a for a in _audit() if a["operation"] == "policy"]
    assert [(r["before"]["policy"], r["after"]["policy"]) for r in rows] == [
        ("ask", "always"), ("always", "deny"), ("ask", "ask")]
    assert live.client.get(f"/mcp-servers/{sid}/tools/echo", headers=live.h).status_code == 405
    assert live.client.put(f"/mcp-servers/{sid}/tools/echo", json={"policy": "ask"}).status_code == 401


def _thread(live):
    tid = uuid.uuid4()
    with SessionLocal() as db:
        db.execute(text("INSERT INTO threads (id, title) VALUES (:i, 'ZZ selection')"), {"i": tid})
        db.commit()
    live.threads.append(tid)
    return tid


def _links(tid):
    with SessionLocal() as db:
        return [str(r[0]) for r in db.execute(
            text("SELECT server_id FROM thread_mcp_servers WHERE thread_id = :t"), {"t": tid})]


def test_selection_put_replaces_and_get_returns_it(live):
    sid, tid = _server(live), _thread(live)
    r = live.client.put(f"/threads/{tid}/mcp-servers", json={"server_ids": [sid]}, headers=live.h)
    assert r.status_code == 200 and r.json() == {"server_ids": [sid]}
    assert live.client.get(f"/threads/{tid}", headers=live.h).json()["mcp_server_ids"] == [sid]
    bad = live.client.put(f"/threads/{tid}/mcp-servers", headers=live.h,
                          json={"server_ids": [sid, str(uuid.uuid4())]})
    assert bad.status_code == 422 and _links(tid) == [sid]
    missing = str(uuid.uuid4())
    assert live.client.put(f"/threads/{missing}/mcp-servers", json={"server_ids": []},
                           headers=live.h).status_code == 404
    assert live.client.put(f"/threads/{tid}/mcp-servers", json={"server_ids": []}, headers=live.h).json() == {"server_ids": []}
    assert _links(tid) == []
    assert live.client.put(f"/threads/{tid}/mcp-servers", json={"server_ids": []}).status_code == 401


def test_selection_on_a_new_thread_turn_is_stored_with_it(live):
    sid = uuid.UUID(_server(live))
    tid = uuid.uuid4()
    live.threads.append(tid)
    chat_service._begin_turn(tid, True, "ZZ first question", None, (), [sid])
    assert _links(tid) == [str(sid)]
    # an existing thread ignores the ids
    other = _thread(live)
    chat_service._begin_turn(other, False, "ZZ later question", None, (), [sid])
    assert _links(other) == []


def test_selection_unknown_id_on_a_new_thread_stores_nothing(live):
    tid = uuid.uuid4()
    live.threads.append(tid)
    with pytest.raises(ValueError, match="Unknown MCP server"):
        chat_service._begin_turn(tid, True, "ZZ first question", None, (), [uuid.uuid4()])
    with SessionLocal() as db:
        assert db.execute(text("SELECT count(*) FROM threads WHERE id = :t"), {"t": tid}).scalar() == 0
        assert db.execute(text("SELECT count(*) FROM messages WHERE thread_id = :t"), {"t": tid}).scalar() == 0
