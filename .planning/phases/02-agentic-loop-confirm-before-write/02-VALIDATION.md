---
phase: 2
slug: agentic-loop-confirm-before-write
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-21
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from 02-RESEARCH.md § Validation Architecture.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + pytest-asyncio (`asyncio_mode = "auto"`) |
| **Config file** | none yet — Wave 0 adds `[tool.pytest.ini_options]` (or `pytest.ini`) with `asyncio_mode = "auto"` |
| **Quick run command** | `uv run --with-requirements backend/requirements.txt pytest backend/tests/ -x -q` |
| **Full suite command** | `uv run --with-requirements backend/requirements.txt pytest backend/tests/ -v` |
| **Estimated runtime** | ~30 seconds (mock-LLM unit tests fast; proposal integration tests hit DB) |

---

## Sampling Rate

- **After every task commit:** Run `uv run --with-requirements backend/requirements.txt pytest backend/tests/ -x -q`
- **After every plan wave:** Run `uv run --with-requirements backend/requirements.txt pytest backend/tests/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** ~30 seconds

---

## Per-Task Verification Map

> Task IDs are assigned by the planner. This map binds each phase requirement to its
> automated proof; the planner/executor backfills the `Task ID` column as plans are written.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD | TBD | 0 | — | — | pytest-asyncio configured | infra | `pytest backend/tests/ --collect-only` | ❌ W0 | ⬜ pending |
| TBD | TBD | — | CHAT-01 | — | Agent chains 2+ tools in one turn | unit (mock LLM) | `pytest backend/tests/test_agent.py::test_multi_step_chain -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | — | CHAT-02 | T-no-sql | Agent refuses to emit raw SQL | unit (mock LLM) | `pytest backend/tests/test_agent.py::test_no_sql_emission -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | — | CHAT-04 | T-write-guard | Write tool creates proposal, no DB mutation | unit | `pytest backend/tests/test_write_tools.py::test_propose_creates_row -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | — | CHAT-05 | T-token-replay | Second confirm with same token → 409 | integration | `pytest backend/tests/test_proposals.py::test_token_single_use -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | — | CHAT-05 | T-expiry | Confirm after expiry → 410 | integration | `pytest backend/tests/test_proposals.py::test_expired_proposal -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | — | CHAT-06 | T-audit | Confirm writes audit_log row(s) | integration | `pytest backend/tests/test_proposals.py::test_audit_on_confirm -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | — | CHAT-07 | T-write-guard | All write tools produce proposals (add/edit/delete × entities) | unit | `pytest backend/tests/test_write_tools.py -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | — | CHAT-08 | — | Agent returns honest refusal for unknown questions | unit (mock LLM) | `pytest backend/tests/test_agent.py::test_honest_refusal -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | — | D-06 | T-orphan | Orphan-delete blocked + explained | unit | `pytest backend/tests/test_write_tools.py::test_orphan_delete_blocked -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `pytest.ini` or `pyproject.toml [tool.pytest.ini_options]` with `asyncio_mode = "auto"` — needed for async agent/endpoint tests
- [ ] `backend/tests/conftest.py` — add `async_client` fixture using `httpx.AsyncClient` + `ASGITransport`
- [ ] `backend/tests/test_agent.py` — stubs for CHAT-01, CHAT-02, CHAT-08 (mock LLM)
- [ ] `backend/tests/test_write_tools.py` — stubs for CHAT-04, CHAT-07, D-06
- [ ] `backend/tests/test_proposals.py` — stubs for CHAT-05, CHAT-06 (requires DB)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Tool-call metadata visible in chat response | CHAT-01 | End-to-end UI surfacing best confirmed visually | Ask a 2-tool question in chat; confirm tool calls appear in response metadata |
| Real-LLM honest refusal quality | CHAT-08 | Mock LLM proves the path; phrasing quality needs a live model | Ask an unanswerable question against the configured provider; confirm no fabricated number |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
