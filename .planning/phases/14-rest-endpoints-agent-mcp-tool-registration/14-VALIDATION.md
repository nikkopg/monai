---
phase: 14
slug: rest-endpoints-agent-mcp-tool-registration
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-30
---

# Phase 14 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x |
| **Config file** | backend/pytest.ini (or pyproject) |
| **Quick run command** | `cd backend && python -m pytest -q` |
| **Full suite command** | `cd backend && python -m pytest` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `cd backend && python -m pytest -q`
- **After every plan wave:** Run `cd backend && python -m pytest`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 14-01-01 | 01 | 1 | CHAT-09 | — | New write tools stay off MCP read-only surface | unit | `cd backend && python -m pytest -q` | ✅ | ⬜ pending |

*Planner refines this map per task during planning. Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

*Existing pytest infrastructure covers all phase requirements — Phase 13 left tested `apply_*` primitives; Phase 14 is wiring verified through endpoint + registration tests.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Chat-driven proposal→confirm→apply for a real write | CHAT-09 | Requires live LLM + human confirm interaction | Ask chat to record a transfer; confirm the proposal; verify the row lands |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
