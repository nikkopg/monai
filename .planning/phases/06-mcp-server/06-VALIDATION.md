---
phase: 6
slug: mcp-server
status: validated
nyquist_compliant: true
wave_0_complete: true
created: 2026-07-15
audited_at: 2026-07-16
audited_by: gsd-validate-phase
---

# Phase 6 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x |
| **Config file** | backend/pytest config (existing) |
| **Quick run command** | `pytest backend/tests/test_mcp.py -q` |
| **Full suite command** | `pytest backend/tests -q` |
| **Estimated runtime** | ~3 seconds (MCP file) |

---

## Sampling Rate

- **After every task commit:** Run `pytest backend/tests/test_mcp.py -q`
- **After every plan wave:** Run `pytest backend/tests -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Requirement | Behavior | Test Type | Test | Automated Command | Status |
|-------------|----------|-----------|------|-------------------|--------|
| MCP-01 | Finance tools exposed via a single co-mounted MCP server; `/mcp` handshake is not 404 | integration | `test_mcp_endpoint_mounted` | `pytest backend/tests/test_mcp.py::test_mcp_endpoint_mounted -q` | ✅ green |
| MCP-02 | Web chat agent and MCP clients share one tool source; `tools/list` == 15 `TOOLS`, `tools/call` result == direct `TOOLS[name](...)`; agent read-tool list length 15 | integration | `test_mcp_read_parity`, `test_agent_read_tools_count` | `pytest backend/tests/test_mcp.py::test_mcp_read_parity backend/tests/test_mcp.py::test_agent_read_tools_count -q` | ✅ green |
| MCP-03 | Read-only surface only; no `propose_*` in `tools/list`; calling one is unknown-tool | integration | `test_mcp_no_write_tools` | `pytest backend/tests/test_mcp.py::test_mcp_no_write_tools -q` | ✅ green |
| MCP-04 | Auth required; `/mcp` request without the key → 401 (503 if key unset) | integration | `test_mcp_requires_key` | `pytest backend/tests/test_mcp.py::test_mcp_requires_key -q` | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

**Coverage:** 4/4 requirements COVERED by green automated tests (`5 passed in 3.05s`, run 2026-07-16). No MISSING or PARTIAL gaps.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Status |
|----------|-------------|------------|--------|
| External MCP client (Claude Desktop) connects to `http://host:8001/mcp`, enumerates 15 read-only tools / 0 write tools, calls a read tool matching web chat, unauthenticated rejected | MCP-01, MCP-02, MCP-04 | Requires a real external MCP client + live container; header/Bearer auth confirmed against actual client (research A2) | ✅ Verified live in UAT (commit `839d25a` — 5/5 passed, live external MCP clients) |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references — none remain
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** NYQUIST-COMPLIANT — 4/4 requirements automated & green; sole manual item verified live in UAT.

---

## Validation Audit 2026-07-16

| Metric | Count |
|--------|-------|
| Requirements | 4 |
| Covered (green automated) | 4 |
| Partial | 0 |
| Missing | 0 |
| Gaps found | 0 |
| Tests generated | 0 (all pre-existing) |

Audited State A. Corrected the plan-time draft: test path `backend/test_mcp.py` → `backend/tests/test_mcp.py`; populated the per-task map from the executed `test_mcp.py` (5 tests, `5 passed in 3.05s`); flipped `nyquist_compliant`/`wave_0_complete` to true and status to `validated`. No test generation needed — every MCP-01..MCP-04 requirement already has a dedicated green test.
