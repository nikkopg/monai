"""
MCP server tests — Wave 0 scaffold (stubs) for MCP-01..MCP-04.

These five tests are skipped in Wave 0 (this plan, 06-01): fastmcp is installed
but the MCP server/mount does not exist yet (06-02 wires it). Wave 1 removes the
skip markers and fills in the assertions described in each docstring.

Fixtures reused verbatim from conftest.py (no new fixtures defined here):
  client       — FastAPI TestClient
  api_key      — monkeypatch-patched MONAI_API_KEY (_TEST_API_KEY)
"""

import pytest


def test_mcp_endpoint_mounted(client, api_key):
    """MCP-01: /mcp handshake with a valid key is not 404 (single co-mounted server)."""
    pytest.skip(reason="Wave 1 (06-02) wires the MCP server")


def test_mcp_read_parity(client, api_key):
    """MCP-02: tools/list == the 15 TOOLS names; a tools/call result equals a direct TOOLS[name](...) dict."""
    pytest.skip(reason="Wave 1 (06-02) wires the MCP server")


def test_agent_read_tools_count(api_key):
    """MCP-02/D-02: backend/query.py builds a read-tool list of length 15 (parity with TOOLS)."""
    pytest.skip(reason="Wave 1 (06-02) wires the MCP server")


def test_mcp_no_write_tools(client, api_key):
    """MCP-03: no propose_* name appears in tools/list; calling one is unknown-tool."""
    pytest.skip(reason="Wave 1 (06-02) wires the MCP server")


def test_mcp_requires_key(client):
    """MCP-04: /mcp request WITHOUT the MONAI_API_KEY header returns 401."""
    pytest.skip(reason="Wave 1 (06-02) wires the MCP server")
