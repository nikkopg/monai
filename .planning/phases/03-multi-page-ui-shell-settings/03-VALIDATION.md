---
phase: 3
slug: multi-page-ui-shell-settings
status: approved
nyquist_compliant: true
wave_0_complete: true
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

Backfilled at phase close-out (2026-07-04) from executed plans; all rows verified green in the post-merge gate and 03-VERIFICATION.md.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 03-01-01 | 01 | 1 | UI-01/02 | T-03-SC | @playwright/test legitimacy verified (Microsoft-published) | checkpoint | npm ls @playwright/test | ✅ | ✅ green |
| 03-01-02 | 01 | 1 | UI-01/02 | — | — | e2e (RED) | cd ui && npx playwright test e2e/smoke.spec.ts | ✅ | ✅ green |
| 03-01-03 | 01 | 1 | UI-02 | — | — | build | cd ui && npx tsc --noEmit | ✅ | ✅ green |
| 03-01-04 | 01 | 1 | UI-01/02 | — | proxy route.ts unchanged (SSE blast radius) | e2e (GREEN) | cd ui && npx playwright test e2e/smoke.spec.ts (10/10) | ✅ | ✅ green |
| 03-02-01 | 02 | 1 | UI-03/04 | — | — | unit (RED) | pytest backend/tests/test_settings.py | ✅ | ✅ green |
| 03-02-02 | 02 | 1 | UI-03/04 | T-03-12 | blank key never clobbers stored key | unit+migration | alembic upgrade head; pytest backend/tests/test_settings.py | ✅ | ✅ green |
| 03-02-03 | 02 | 1 | UI-03/04 | T-03-10/11/13 | masked-only GET; PUT auth-gated; reset_engine on LLM change | integration (GREEN) | pytest backend/tests -q (58 passed) | ✅ | ✅ green |
| 03-03-01 | 03 | 2 | UI-03/04 | — | — | e2e (RED) | cd ui && npx playwright test e2e/settings.spec.ts | ✅ | ✅ green |
| 03-03-02 | 03 | 2 | UI-03/04 | T-03-20/21 | masked placeholder; blank-keeps-current hint | e2e (GREEN) | cd ui && npx playwright test (15/15) | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `backend/tests/test_settings.py` — 7 tests covering UI-03/UI-04 (GET/PUT round-trip, masking, keep-existing-key, reset_engine trigger, persistence)
- [x] `ui/e2e/smoke.spec.ts` — 10 Playwright smoke tests for UI-01/UI-02 (+ `ui/e2e/settings.spec.ts`, 5 tests)
- [x] `@playwright/test@1.61.1` devDependency in `ui/package.json` (legitimacy checkpoint passed)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Provider switch takes effect on next chat request against a real LLM | UI-03 | Requires a live Ollama/Claude/OpenAI provider responding | Change provider in Settings, save, ask a chat question, confirm response comes from new provider |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 60s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-07-04 (backfilled at phase close-out per plan-checker warning 3)
