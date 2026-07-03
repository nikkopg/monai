---
phase: 3
slug: multi-page-ui-shell-settings
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-03
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest >=8.0.0 (backend) / @playwright/test (frontend smoke — Wave 0 installs) |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`); Playwright config in `ui/` (Wave 0) |
| **Quick run command** | `pytest backend/tests/test_settings.py -x` |
| **Full suite command** | `pytest backend/tests -x` |
| **Estimated runtime** | ~10 seconds (backend suite) |

---

## Sampling Rate

- **After every task commit:** Run `pytest backend/tests/test_settings.py -x` (backend tasks) or `npx tsc --noEmit` in `ui/` (frontend tasks)
- **After every plan wave:** Run `pytest backend/tests -x` + `cd ui && npx tsc --noEmit`
- **Before `/gsd-verify-work`:** Full suite must be green + Playwright smoke spec passes
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

*To be filled by the planner — one row per task, mapping UI-01..UI-04 to automated commands per the Phase Requirements → Test Map in 03-RESEARCH.md.*

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| — | — | — | UI-01..UI-04 | — | — | — | — | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `backend/tests/test_settings.py` — stubs for UI-03/UI-04 (GET/PUT round-trip, masking, keep-existing-key, reset_engine trigger, persistence)
- [ ] `ui/e2e/smoke.spec.ts` (or similar) — Playwright smoke for UI-01/UI-02 (routes render, nav navigates client-side, active link highlights)
- [ ] `@playwright/test` devDependency in `ui/package.json` — no frontend test framework exists today

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Provider switch takes effect on next chat request against a real LLM | UI-03 | Requires a live Ollama/Claude/OpenAI provider responding | Change provider in Settings, save, ask a chat question, confirm response comes from new provider |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
