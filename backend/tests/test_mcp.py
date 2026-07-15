"""
MCP server tests — Wave 1 (MCP-01..MCP-04).

Fixtures reused verbatim from conftest.py (no new fixtures defined here):
  client       — FastAPI TestClient
  api_key      — monkeypatch-patched MONAI_API_KEY (_TEST_API_KEY)

The MCP endpoint speaks streamable-HTTP JSON-RPC (initialize -> notifications/
initialized -> tools/list | tools/call), so every test that needs the mounted
session goes through the same handshake helper below. `client` (the module-
level TestClient fixture) is used as a context manager here so the app's
combined lifespan actually starts/stops the FastMCP session manager for the
duration of each test — a plain (non-context-managed) TestClient never runs
FastAPI lifespan events, and the MCP session manager raises "Task group is
not initialized" without it.
"""

import json

import pytest

from backend.tools import READ_TOOL_NAMES, TOOLS

_MCP_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


def _sse_json(resp) -> dict:
    """Extract the JSON payload from a single-event SSE response body."""
    for line in resp.text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[len("data:"):].strip())
    raise AssertionError(f"no SSE 'data:' line in response: {resp.text!r}")


def _mcp_session(client, api_key: str):
    """Run the MCP initialize handshake; return headers carrying the session id."""
    headers = {**_MCP_HEADERS, "MONAI_API_KEY": api_key}
    init_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "monai-test", "version": "0.1"},
        },
    }
    r = client.post("/mcp", json=init_payload, headers=headers, follow_redirects=True)
    assert r.status_code == 200, r.text
    sid = r.headers["mcp-session-id"]
    session_headers = {**headers, "mcp-session-id": sid}
    notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    client.post("/mcp", json=notif, headers=session_headers, follow_redirects=True)
    return session_headers


def _tools_list(client, session_headers) -> list[dict]:
    payload = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    r = client.post("/mcp", json=payload, headers=session_headers, follow_redirects=True)
    assert r.status_code == 200, r.text
    return _sse_json(r)["result"]["tools"]


def _tools_call(client, session_headers, name: str, arguments: dict) -> dict:
    payload = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }
    r = client.post("/mcp", json=payload, headers=session_headers, follow_redirects=True)
    assert r.status_code == 200, r.text
    return _sse_json(r)["result"]


def test_mcp_endpoint_mounted(client, api_key):
    """MCP-01: /mcp handshake with a valid key is not 404 (single co-mounted server)."""
    with client:
        headers = {**_MCP_HEADERS, "MONAI_API_KEY": api_key}
        init_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "monai-test", "version": "0.1"},
            },
        }
        r = client.post("/mcp", json=init_payload, headers=headers, follow_redirects=True)
        assert r.status_code != 404
        assert r.status_code == 200
        assert "mcp-session-id" in r.headers


def test_mcp_read_parity(client, api_key):
    """MCP-02: tools/list == the 15 TOOLS names; a tools/call result equals a direct TOOLS[name](...) dict."""
    with client:
        session_headers = _mcp_session(client, api_key)

        listed = _tools_list(client, session_headers)
        listed_names = {t["name"] for t in listed}
        assert listed_names == set(READ_TOOL_NAMES)
        assert len(listed_names) == 15

        mcp_result = _tools_call(client, session_headers, "spending_total", {"period": "last_month"})
        assert mcp_result["isError"] is False
        mcp_dict = mcp_result["structuredContent"]

        direct_dict = TOOLS["spending_total"](period="last_month")
        assert mcp_dict == direct_dict


def test_agent_read_tools_count(api_key):
    """MCP-02/D-02: backend/query.py builds a read-tool list of length 15 (parity with TOOLS)."""
    import backend.query as query_mod

    query_mod.reset_engine()
    workflow = query_mod._get_agent_workflow()
    agent = workflow.agents["Agent"]
    all_tool_names = [t.metadata.name for t in agent.tools]
    read_tool_names = [n for n in all_tool_names if not n.startswith("propose_")]
    assert len(read_tool_names) == 15
    assert set(read_tool_names) == set(READ_TOOL_NAMES)
    query_mod.reset_engine()


def test_mcp_no_write_tools(client, api_key):
    """MCP-03: no propose_* name appears in tools/list; calling one is unknown-tool."""
    with client:
        session_headers = _mcp_session(client, api_key)

        listed = _tools_list(client, session_headers)
        listed_names = {t["name"] for t in listed}
        assert not any(n.startswith("propose_") for n in listed_names)

        result = _tools_call(client, session_headers, "propose_add_transaction", {})
        assert result["isError"] is True
        assert "Unknown tool" in result["content"][0]["text"]


def test_mcp_requires_key(client, api_key):
    """MCP-04: /mcp request WITHOUT the MONAI_API_KEY header returns 401.

    Uses the api_key fixture (mirrors test_auth.py's missing-key pattern) so
    _CONFIGURED_KEY is set — a request with no header must be rejected
    because the key doesn't match, not merely because the server itself is
    unconfigured (that's the separate 503 fail-closed path, already covered
    by test_auth.py::test_empty_configured_key_returns_503).
    """
    with client:
        init_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "monai-test", "version": "0.1"},
            },
        }
        r = client.post("/mcp", json=init_payload, headers=_MCP_HEADERS, follow_redirects=True)
        assert r.status_code == 401
