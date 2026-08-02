---
phase: 17
slug: ui-new-surfaces-records-tab-categories-manager
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-08-01
---

# Phase 17 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Backend** | pytest (`backend/tests/`) — existing suite covers endpoints/writes/portfolio |
| **Frontend** | Playwright e2e (route-mocked) under `ui/e2e/` — no unit-test framework in `ui/` |
| **Backend run** | `cd backend && python -m pytest` (or the repo's `uv run` runner) |
| **Frontend run** | `cd ui && PLAYWRIGHT_CHROMIUM_PATH=/usr/bin/google-chrome npx playwright test <spec>` |
| **Env note** | `/opt/pw-browsers` chromium absent in this env → set `PLAYWRIGHT_CHROMIUM_PATH=/usr/bin/google-chrome` |
| **Estimated runtime** | backend ~seconds; e2e ~30–90s |

---

## Sampling Rate

- **After every task commit:** run the relevant pytest module or Playwright spec
- **After every plan wave:** full backend pytest + the phase's e2e specs
- **Before `/gsd:verify-work`:** both suites green
- **Max feedback latency:** ~90 seconds

---

## Per-Task Verification Map

*Planner populates this table. Analogs: backend `backend/tests/test_write_tools.py` / `test_portfolio.py`; frontend `ui/e2e/cashflow-crud.spec.ts`, `record-modal.spec.ts`, `platform-crud.spec.ts`.*

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 17-01-01 | 01 | 1 | REC-01/02 | pytest | `cd backend && python -m pytest tests/ -k transactions_filter` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 / test-scaffolding Requirements

- [ ] Backend: filter/bulk/pair-delete/platform-detail endpoint tests (REC-01/02/03/05, PLAT-01) — extend `backend/tests/`
- [ ] Frontend: `ui/e2e/records.spec.ts` (grouped ledger, filters, multi-select bulk, transfer-pair collapse) + `ui/e2e/platform-detail.spec.ts` (PnL + Buy/Sell tabs)
- [ ] Confirm hierarchy-aware category filter matches dashboard rollups (no undercount)

*Backend pytest + Playwright infra already present — no framework install; verify `ui/playwright.config.ts` and the chromium path in Wave 0.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Bulk-delete of a real multi-row selection incl. a transfer pair, against live Postgres | REC-03/05 | Destructive real-data op; atomic pair cascade best confirmed live | Select several records incl. a transfer, bulk-delete, confirm both legs gone + balances correct |

*Automated tests use route mocks / test DB; the destructive real-data run is the manual item.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
