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

import importlib.metadata
import inspect
import json
import os
from pathlib import Path

import pytest

from backend.tools import READ_TOOL_NAMES, TOOLS

_TOOL_SNAPSHOT = Path(__file__).with_name("agent_tool_surface.json")
_MCP_SNAPSHOT = Path(__file__).with_name("mcp_tool_surface.json")

MCP_WRITE_NAMES = {"propose_transactions", "propose_transfer", "confirm_proposal", "reject_proposal"}
_FORBIDDEN_PARAMS = {"channel", "db", "token", "session"}

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
    """MCP-02: tools/list holds the 16 read names plus the 4 curated writes
    (Phase 32); a tools/call result equals a direct TOOLS[name](...) dict."""
    with client:
        session_headers = _mcp_session(client, api_key)

        listed = _tools_list(client, session_headers)
        listed_names = {t["name"] for t in listed}
        assert set(READ_TOOL_NAMES) <= listed_names
        assert len(listed_names) == 20

        mcp_result = _tools_call(client, session_headers, "spending_total", {"period": "last_month"})
        assert mcp_result["isError"] is False
        mcp_dict = mcp_result["structuredContent"]

        direct_dict = TOOLS["spending_total"](period="last_month")
        assert mcp_dict == direct_dict


def test_agent_read_tools_count(api_key):
    """MCP-02/D-02: backend/query.py builds a read-tool list of length 16
    (parity with TOOLS; Phase 15 adds net_worth). AGENT-02/D-12: agent tool
    names must equal set(TOOLS) with no duplicates (len(agent.tools) ==
    len(TOOLS)) — the MCP half (tools/list == READ_TOOL_NAMES) is asserted
    separately in test_mcp_read_parity."""
    import backend.query as query_mod
    from backend.tools import TOOLS

    query_mod.reset_engine()
    workflow = query_mod._get_agent_workflow()
    agent = workflow.agents["Agent"]
    all_tool_names = [t.metadata.name for t in agent.tools]
    read_tool_names = [n for n in all_tool_names if not n.startswith("propose_")]
    assert len(read_tool_names) == 16
    assert set(read_tool_names) == set(READ_TOOL_NAMES)
    assert {t.metadata.name for t in agent.tools} == set(TOOLS)
    assert len(agent.tools) == len(TOOLS)
    query_mod.reset_engine()


def _norm_description(desc: str) -> str:
    """Strip the Python-version-dependent uniform indent from a tool description.

    Python 3.13+ dedents a function's docstring at compile time; 3.12 (CI,
    Docker) does not, so `FunctionTool.from_defaults`' generated description
    carries a different indentation depending on the interpreter running the
    test. `inspect.cleandoc` normalizes that away while still comparing word
    content, line breaks and relative indentation exactly.
    """
    first, sep, rest = desc.partition("\n")
    if not sep:
        return desc
    return first + sep + inspect.cleandoc(rest)


def test_tool_surface_snapshot():
    """AGENT-01: locks every agent tool's name, description and fn_schema in
    a checked-in JSON snapshot (backend/tests/agent_tool_surface.json), so a
    later registry refactor (26-02) or category-matching change (26-03) that
    alters what the LLM sees shows up as a reviewed diff instead of silent
    drift.

    Regenerate deliberately with:
        UPDATE_TOOL_SNAPSHOT=1 pytest backend/tests/test_mcp.py -k tool_surface_snapshot

    Every regeneration must land as its own reviewed commit (D-05) — this
    test never writes the file unless that env var is set.
    """
    import backend.query as query_mod

    query_mod.reset_engine()
    workflow = query_mod._get_agent_workflow()
    agent = workflow.agents["Agent"]
    entries = [
        {
            "name": t.metadata.name,
            "description": _norm_description(t.metadata.description),
            "fn_schema": t.metadata.fn_schema.model_json_schema(),
        }
        for t in agent.tools
    ]
    query_mod.reset_engine()

    rendered = json.dumps(entries, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    if os.environ.get("UPDATE_TOOL_SNAPSHOT") == "1":
        _TOOL_SNAPSHOT.write_text(rendered, encoding="utf-8")
        return

    if not _TOOL_SNAPSHOT.exists():
        pytest.fail(
            f"{_TOOL_SNAPSHOT} is missing. Regenerate deliberately with "
            "UPDATE_TOOL_SNAPSHOT=1 pytest backend/tests/test_mcp.py -k tool_surface_snapshot "
            "and review the diff before committing — this test never creates the file itself."
        )

    installed_version = importlib.metadata.version("llama-index-core")
    assert rendered == _TOOL_SNAPSHOT.read_text(encoding="utf-8"), (
        "The agent tool surface changed (name, description or fn_schema of at least "
        f"one tool). Installed llama-index-core=={installed_version} — check whether a "
        "dependency bump reformatted descriptions before assuming monai's code changed "
        "(Pitfall 1). If the change is real and reviewed, regenerate with "
        "UPDATE_TOOL_SNAPSHOT=1 pytest backend/tests/test_mcp.py -k tool_surface_snapshot."
    )


def _all_keys(node):
    """Yield every dict key anywhere in a nested dict/list structure."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from _all_keys(v)
    elif isinstance(node, list):
        for v in node:
            yield from _all_keys(v)


def test_mcp_surface_is_exact(client, api_key):
    """D-01..D-03, D-23: tools/list is exactly the 16 reads plus the 4 curated
    writes; no schema exposes channel/db/token/session; the writes are not in
    the chat registry; a chat propose_* name is still an unknown tool."""
    with client:
        session_headers = _mcp_session(client, api_key)
        listed = _tools_list(client, session_headers)
        assert {t["name"] for t in listed} == set(READ_TOOL_NAMES) | MCP_WRITE_NAMES
        for t in listed:
            bad = _FORBIDDEN_PARAMS & set(_all_keys(t["inputSchema"]))  # $defs too (TxnRow)
            assert not bad, f"{t['name']} exposes {bad}"
        assert not (MCP_WRITE_NAMES & set(TOOLS))

        result = _tools_call(client, session_headers, "propose_add_transaction", {})
        assert result["isError"] is True
        assert "Unknown tool" in result["content"][0]["text"]


def test_new_write_tools_registered_and_excluded(client, api_key):
    """Phase 14 CHAT-09 SC 2 & 3: the 5 new propose_* names must be present
    in TOOLS, ABSENT from READ_TOOL_NAMES, and ABSENT from the live MCP
    tools/list surface. Catches an accidental rename/removal the generic
    count/prefix checks (test_mcp_read_parity, test_mcp_surface_is_exact)
    would silently tolerate. RED until Plan 14-02 registers the tools (the
    TOOLS membership assertion fails today)."""
    new_tool_names = {
        "propose_add_transfer",
        "propose_add_investment_transfer",
        "propose_add_funded_buy",
        "propose_add_funded_sell",
        "propose_add_balance_adjustment",
    }
    for name in new_tool_names:
        assert name in TOOLS, f"{name} missing from TOOLS — not yet registered (RED until Plan 14-02)"
        assert name not in READ_TOOL_NAMES, f"{name} leaked into READ_TOOL_NAMES — MCP exclusion violated"

    with client:
        session_headers = _mcp_session(client, api_key)
        listed = _tools_list(client, session_headers)
        listed_names = {t["name"] for t in listed}
        leaked = new_tool_names & listed_names
        assert not leaked, f"write tool(s) leaked onto the MCP tools/list surface: {leaked}"


def test_mcp_tool_surface_snapshot(client, api_key):
    """D-24: locks every MCP tool's name, description and inputSchema in
    backend/tests/mcp_tool_surface.json (incl. the 'Never guess a code' wording).

    Regenerate deliberately with:
        UPDATE_MCP_SNAPSHOT=1 pytest backend/tests/test_mcp.py -k mcp_tool_surface_snapshot
    """
    with client:
        listed = _tools_list(client, _mcp_session(client, api_key))
    entries = sorted(
        (
            {
                "name": t["name"],
                "description": _norm_description(t["description"]),
                "inputSchema": t["inputSchema"],
            }
            for t in listed
        ),
        key=lambda e: e["name"],
    )
    rendered = json.dumps(entries, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    if os.environ.get("UPDATE_MCP_SNAPSHOT") == "1":
        _MCP_SNAPSHOT.write_text(rendered, encoding="utf-8")
        return

    if not _MCP_SNAPSHOT.exists():
        pytest.fail(
            f"{_MCP_SNAPSHOT} is missing, regenerate deliberately with UPDATE_MCP_SNAPSHOT=1 "
            "pytest backend/tests/test_mcp.py -k mcp_tool_surface_snapshot and review the diff."
        )
    assert rendered == _MCP_SNAPSHOT.read_text(encoding="utf-8"), (
        "The MCP tool surface changed. Installed fastmcp=="
        f"{importlib.metadata.version('fastmcp')}; if the change is real and reviewed, regenerate with "
        "UPDATE_MCP_SNAPSHOT=1 pytest backend/tests/test_mcp.py -k mcp_tool_surface_snapshot."
    )


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
