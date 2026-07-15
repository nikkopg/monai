---
phase: 6
slug: mcp-server
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-15
---

# Phase 6 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x |
| **Config file** | backend/pytest config (existing) |
| **Quick run command** | `pytest backend/test_mcp.py -q` |
| **Full suite command** | `pytest backend -q` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest backend/test_mcp.py -q`
- **After every plan wave:** Run `pytest backend -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 6-01-01 | 01 | 0 | MCP-01 | T-6-01 / — | fastmcp dependency installed; test_mcp.py stubs present | unit | `pytest backend/test_mcp.py -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*
*Full per-task map populated by planner from PLAN.md tasks.*

---

## Wave 0 Requirements

- [ ] `backend/test_mcp.py` — stubs for MCP-01..MCP-04 (enumerate, call-parity, no-writes, auth)
- [ ] `fastmcp>=3.4,<4` added to backend/requirements.txt + container rebuild
- [ ] Existing fixtures (`client`, `api_key`, `async_client`) reused — no new conftest needed

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| External MCP client (Claude Desktop) connects to `http://host:8001/mcp`, enumerates read-only tools, calls a read tool | MCP-01, MCP-02, MCP-04 | Requires a real external MCP client + live container; header/Bearer auth mechanism confirmed against actual client (research open question A2) | 1) Rebuild container. 2) Add monai MCP server to Claude Desktop with MONAI_API_KEY. 3) Confirm 15 read tools enumerate, 0 write tools. 4) Ask "spending total last month" — result matches web chat. 5) Confirm unauthenticated connection rejected. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
