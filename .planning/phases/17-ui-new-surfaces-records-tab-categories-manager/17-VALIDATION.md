---
phase: 17
slug: ui-new-surfaces-records-tab-categories-manager
status: planned
nyquist_compliant: true
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

*Analogs: backend `backend/tests/test_write_endpoints.py` / `test_write_tools.py` / `test_portfolio.py`; frontend `ui/e2e/cashflow-crud.spec.ts`, `record-modal.spec.ts`, `platform-crud.spec.ts`. Wave 1 = RED scaffolds (Plans 01/02), Wave 2 = backend impl (Plan 03), Wave 3 = frontend surfaces (Plans 04/05). e2e commands assume `cd ui` with `PLAYWRIGHT_CHROMIUM_PATH=/usr/bin/google-chrome`.*

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 17-01-01 | 01 | 1 | REC-01/02/05 | pytest | `cd backend && python -m pytest tests/test_write_endpoints.py -k 'transactions_filter or transaction_paging or category_filter_hierarchy or transfer_pair_id_exposed'` | ❌ creates (RED) | ⬜ pending |
| 17-01-02 | 01 | 1 | REC-03/05 | pytest | `cd backend && python -m pytest tests/test_write_endpoints.py -k 'bulk_delete or bulk_recategorize'; python -m pytest tests/test_write_tools.py -k pair_aware_delete` | ❌ creates (RED) | ⬜ pending |
| 17-01-03 | 01 | 1 | PLAT-01 | pytest | `cd backend && python -m pytest tests/test_portfolio.py -k 'platform_detail or portfolio_events_by_platform'` | ❌ creates (RED) | ⬜ pending |
| 17-02-01 | 02 | 1 | REC-01/02/03/05 | e2e | `npx playwright test e2e/records.spec.ts` | ❌ creates (RED) | ⬜ pending |
| 17-02-02 | 02 | 1 | PLAT-01 | e2e | `npx playwright test e2e/platform-detail.spec.ts` | ❌ creates (RED) | ⬜ pending |
| 17-03-01 | 03 | 2 | REC-01/02/05 | pytest | `cd backend && python -m pytest tests/test_write_endpoints.py -k 'transactions_filter or transaction_paging or category_filter_hierarchy or transfer_pair_id_exposed'` | ✅ from 17-01 | ⬜ pending |
| 17-03-02 | 03 | 2 | REC-03/05 | pytest | `cd backend && python -m pytest tests/test_write_endpoints.py -k 'bulk_delete or bulk_recategorize'; python -m pytest tests/test_write_tools.py -k pair_aware_delete` | ✅ from 17-01 | ⬜ pending |
| 17-03-03 | 03 | 2 | PLAT-01 | pytest | `cd backend && python -m pytest tests/test_portfolio.py -k 'platform_detail or portfolio_events_by_platform'` | ✅ from 17-01 | ⬜ pending |
| 17-04-01 | 04 | 3 | REC-01/02 | e2e | `npx playwright test e2e/records.spec.ts -g "filter"` | ✅ from 17-02 | ⬜ pending |
| 17-04-02 | 04 | 3 | REC-01/05 | e2e | `npx playwright test e2e/records.spec.ts -g "transfer pair"; npx playwright test e2e/records.spec.ts -g "date-grouped"` | ✅ from 17-02 | ⬜ pending |
| 17-04-03 | 04 | 3 | REC-03/05 | e2e | `npx playwright test e2e/records.spec.ts -g "bulk"` | ✅ from 17-02 | ⬜ pending |
| 17-05-01 | 05 | 3 | PLAT-01 | e2e | `npx playwright test e2e/platform-detail.spec.ts -g "shell\|stat\|not found"` | ✅ from 17-02 | ⬜ pending |
| 17-05-02 | 05 | 3 | PLAT-01 | e2e | `npx playwright test e2e/platform-detail.spec.ts` | ✅ from 17-02 | ⬜ pending |

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
