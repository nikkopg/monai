---
status: partial
phase: 06-mcp-server
source: [06-01-SUMMARY.md, 06-02-SUMMARY.md]
started: 2026-07-16T00:56:30Z
updated: 2026-07-16T01:05:00Z
---

## Current Test

[testing complete — 1 item blocked on live deploy (human)]

## Tests

### 1. Cold Start Smoke Test
expected: Rebuild + restart the stack (`docker compose up -d --build`). Backend boots cleanly; both "Scheduler started" and "StreamableHTTP session manager started" appear in logs; a basic API call (e.g. homepage / existing endpoint) returns live data.
result: blocked
blocked_by: server
reason: "Requires a fresh Docker rebuild + running deployment (deploy-requires-rebuild). Cannot be exercised without the live stack; deferred to human live UAT."

### 2. MCP Endpoint Reachable + Tool Enumeration
expected: An external MCP client (or curl JSON-RPC) connecting to `http://host:8001/mcp` with the `MONAI_API_KEY` header (or `Authorization: Bearer <key>`) can enumerate tools and sees exactly 15 read tools — and zero `propose_*` write tools.
result: pass
verified_by: "backend/tests/test_mcp.py::test_mcp_endpoint_mounted (200 + mcp-session-id), ::test_mcp_read_parity (tools/list == READ_TOOL_NAMES, len==15), ::test_mcp_no_write_tools (no propose_* in list). Run 2026-07-16, 5 passed. Real streamable-HTTP JSON-RPC handshake against co-mounted /mcp."

### 3. Read Parity — MCP answer matches web chat
expected: Calling a read tool over MCP (e.g. `spending_total` for `last_month`) returns the same number the web chat agent gives for the same question. No fabricated/differing figures.
result: pass
verified_by: "backend/tests/test_mcp.py::test_mcp_read_parity — MCP tools/call structuredContent byte-equal to direct TOOLS['spending_total'](period='last_month'). ::test_agent_read_tools_count confirms web agent surface == 15 == READ_TOOL_NAMES (D-02 parity)."

### 4. Write Tools Blocked over MCP
expected: Attempting to call a write tool over MCP (e.g. `propose_add_transaction`) fails — returns an error like "Unknown tool" rather than mutating any data.
result: pass
verified_by: "backend/tests/test_mcp.py::test_mcp_no_write_tools — propose_add_transaction over MCP returns isError:true / 'Unknown tool'; no propose_* names in tools/list."

### 5. Auth Required
expected: An MCP request to `/mcp` with a missing or wrong key is rejected (401) before reaching any tool. No tool enumeration or data leaks without a valid key.
result: pass
verified_by: "backend/tests/test_mcp.py::test_mcp_requires_key — initialize with no MONAI_API_KEY header against a configured key returns 401 (outer middleware, before session manager)."

## Summary

total: 5
passed: 4
issues: 0
pending: 0
skipped: 0
blocked: 1

## Gaps

[none yet]
