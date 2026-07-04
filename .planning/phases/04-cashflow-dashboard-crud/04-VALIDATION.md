---
phase: 4
slug: cashflow-dashboard-crud
status: approved
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-04
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

Two test stacks run in this phase: pytest for the backend (existing `backend/tests/` suite) and Playwright for the frontend e2e specs (existing `ui/e2e/` suite from Phase 3).

| Property | Value |
|----------|-------|
| **Framework (backend)** | pytest >=8.0.0 — existing `backend/tests/` suite (9 files incl. `test_write_tools.py`, `test_proposals.py`, `test_tools.py`) |
| **Framework (frontend e2e)** | Playwright 1.61.1 — `ui/e2e/` (`smoke.spec.ts`, `settings.spec.ts` precedent) |
| **Config file (backend)** | `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths = ["backend/tests"]`, `asyncio_mode = "auto"`); fixtures in `backend/tests/conftest.py` |
| **Config file (frontend)** | `ui/playwright.config.ts` (existing) |
| **Quick run command (backend)** | `cd backend && python -m pytest tests/<module>.py -x -q` (per-module) |
| **Quick run command (frontend)** | `cd ui && npx tsc --noEmit -p tsconfig.json` (typecheck) |
| **Full suite command** | `cd backend && python -m pytest tests/ -x` and `cd ui && npm run e2e` |
| **Estimated runtime** | backend full suite ~20–30s; per-module ~2–5s; `npm run e2e` ~30–60s (dev server + Playwright) |

---

## Sampling Rate

- **After every task commit:** Run the task's own `<automated>` command (per-module pytest, or `npx tsc --noEmit` for UI tasks) — the relevant single-file command from the Per-Task Verification Map below.
- **After every plan wave:** Run `cd backend && python -m pytest tests/ -x` (full backend suite) plus, for waves 3–4, `cd ui && npm run e2e` (full Playwright suite).
- **Before `/gsd-verify-work`:** Full backend suite green INCLUDING `tests/test_proposals.py` + `tests/test_write_tools.py` (D-02 refactor regression gate), and `cd ui && npm run e2e` green.
- **Max feedback latency:** ~5s per-task (per-module pytest / tsc); ~60s per-wave (full suite + e2e).

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 04-01-01 | 01 | 1 | CASH-04/05/06/07 (write seam) | T-04-01 / T-04-02 / T-04-02b | apply_* helpers: parameterized rename/merge SQL, one AuditLog row each, reassign-aware audited delete, no db.commit() | unit (import) | `cd backend && python -c "import backend.writes as w; assert all(hasattr(w, n) for n in ['apply_add_transaction','apply_edit_transaction','apply_delete_transaction','apply_add_account','apply_edit_account','apply_delete_account','apply_rename_category','apply_merge_category'])"` | ❌ W0 (new module) | ⬜ pending |
| 04-01-02 | 01 | 1 | CASH-04/05/06/07 (regression) | T-04-02 / T-04-03 | propose→confirm path unchanged after extraction; entity_id populated; Decimal preserved | integration (regression) | `cd backend && python -m pytest tests/test_proposals.py tests/test_write_tools.py -x -q` | ✅ (existing) | ⬜ pending |
| 04-02-01 | 02 | 1 | CASH-01/02/03 | T-04-05 / T-04-07 | rolling >=6-month window (not calendar-year), parameterized read SQL, bounded month window | unit | `cd backend && python -m pytest tests/test_cashflow_summary.py -x -q` | ❌ W0 (new) | ⬜ pending |
| 04-02-02 | 02 | 1 | CASH-01/02/03 (DTOs) | T-04-12 | MoneyDecimal reused on write-path amount; partial-update schemas validate bodies | unit (import) | `cd backend && python -c "from backend.schemas import CashflowSummary, TransactionUpdate, AccountCreate, AccountUpdate, CategoryRenameRequest, CategoryMergeRequest, AffectedCountResponse"` | ❌ W0 (schemas new) | ⬜ pending |
| 04-02-03 | 02 | 1 | CASH-01/02/03 | T-04-05 | trend >=6-month guard; dual per-account balance guard | unit | `cd backend && python -m pytest tests/test_cashflow_summary.py -x -q` | ❌ W0 (new) | ⬜ pending |
| 04-03-01 | 03 | 2 | CASH-01/02/03 | T-04-05 / T-04-06 | GET /cashflow/summary open read; resolve_period once; >=6-month trend | unit + integration | `cd backend && python -m pytest tests/test_cashflow_summary.py -x -q` | ❌ W0 (new) | ⬜ pending |
| 04-03-02 | 03 | 2 | CASH-04/06/07 | T-04-08 / T-04-09 / T-04-10 | mutating routes carry require_api_key; category rename/merge via parameterized apply_* only; audit row per write; GET /categories reuses list_categories SQL | unit + integration | `cd backend && python -m pytest tests/test_transaction_crud.py tests/test_category_management.py -x -q` | ❌ W0 (new) | ⬜ pending |
| 04-03-03 | 03 | 2 | CASH-05 | T-04-08 / T-04-10 / T-04-11 | reassign-then-delete: 422+affected_count when unreassigned; reassignment audited inside apply_delete_account (no inline bulk update) | unit + integration | `cd backend && python -m pytest tests/test_account_crud.py -x -q` | ❌ W0 (new) | ⬜ pending |
| 04-04-01 | 04 | 3 | CASH-01/02/03 (styles/dep) | T-04-13 / T-04-SC | recharts APPROVED (audit table present, no postinstall); pinned ^3.9.2; existing style constants untouched | build (dependency + grep) | `cd ui && node -e "const p=require('./package.json'); if(!p.dependencies.recharts) throw new Error('recharts not in dependencies'); console.log('recharts', p.dependencies.recharts)" && grep -c "export const dangerBtn\|export const chartColors" app/styles.ts` | ❌ W0 (new dep/consts) | ⬜ pending |
| 04-04-02 | 04 | 3 | CASH-01/02/03 (charts) | T-04-15 | explicit 280px-height wrapper (no blank-render); income=green/expense=red contract | typecheck | `cd ui && npx tsc --noEmit -p tsconfig.json 2>&1 \| grep -E "charts/(CategoryDonut\|IncomeExpenseBar\|TrendChart)" \|\| echo "no type errors in chart components"` | ❌ W0 (new) | ⬜ pending |
| 04-04-03 | 04 | 3 | CASH-01/02/03 | T-04-14 | dashboard read via server-side proxy (API key never in browser); period refetch | typecheck + e2e | `cd ui && npx tsc --noEmit -p tsconfig.json 2>&1 \| grep -E "cashflow/page.tsx" \|\| echo "page.tsx typechecks"` (+ `cd ui && npm run e2e -- cashflow-dashboard.spec.ts`) | ❌ W0 (page grown; spec new) | ⬜ pending |
| 04-05-01 | 05 | 4 | CASH-04 | T-04-16 / T-04-17 | writes via proxy (server-side key); ConfirmDialog gates destructive actions | typecheck | `cd ui && npx tsc --noEmit -p tsconfig.json 2>&1 \| grep -E "cashflow/(TransactionModal\|ConfirmDialog).tsx" \|\| echo "modal components typecheck"` | ❌ W0 (new) | ⬜ pending |
| 04-05-02 | 05 | 4 | CASH-05/06/07/08 | T-04-16 / T-04-17 / T-04-18 | AccountManager reassign-then-delete (422 path); CategoryManager enumerates via GET /categories; CsvUpload reuses tested POST /import, surfaces skipped count | typecheck | `cd ui && npx tsc --noEmit -p tsconfig.json 2>&1 \| grep -E "cashflow/(AccountManager\|CategoryManager\|CsvUpload).tsx" \|\| echo "manager components typecheck"` | ❌ W0 (new) | ⬜ pending |
| 04-05-03 | 05 | 4 | CASH-04/05/06/07/08 | T-04-16 / T-04-17 | refetch-after-write (list + summary, no reload); all CRUD flows covered | typecheck + e2e | `cd ui && npx tsc --noEmit -p tsconfig.json 2>&1 \| grep -E "cashflow/page.tsx" \|\| echo "page.tsx typechecks after wiring"` (+ `cd ui && npm run e2e -- cashflow-crud.spec.ts`) | ❌ W0 (page wired; spec new) | ⬜ pending |
| (regression) | — | gate | CASH-04/05/06/07 | T-04-02 | propose→confirm path still green after D-02 refactor | integration | `cd backend && python -m pytest tests/test_proposals.py tests/test_write_tools.py -x` | ✅ (existing) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

New test files the plans create before their production code (created as failing stubs first, per the tdd-flagged tasks):

- [ ] `backend/tests/test_cashflow_summary.py` — covers CASH-01, CASH-02 (`test_trend_covers_six_months`), CASH-03 (`test_account_balances`) — created in Plan 02 Task 3, reuses existing `db_available`/`db_session` fixtures + `_make_account`/`_make_transaction` helpers from `test_write_tools.py`.
- [ ] `backend/tests/test_transaction_crud.py` — covers CASH-04 backend (PUT/DELETE + audit row) — created in Plan 03 Task 2.
- [ ] `backend/tests/test_account_crud.py` — covers CASH-05 backend incl. reassign-then-delete (`test_delete_blocked_without_reassign`, `test_reassign_then_delete` + audit assertion) — created in Plan 03 Task 3.
- [ ] `backend/tests/test_category_management.py` — covers CASH-06 (`test_rename`), CASH-07 (`test_merge`) — created in Plan 03 Task 2.
- [ ] `ui/e2e/cashflow-dashboard.spec.ts` — covers CASH-01/02/03 UI render + period refetch — created in Plan 04 Task 3.
- [ ] `ui/e2e/cashflow-crud.spec.ts` — covers CASH-04 UI reflection, CASH-05 UI reassign-then-delete, CASH-06/07 rename/merge, CASH-08 CSV upload result line — created in Plan 05 Task 3 (CSV upload is folded into this spec, not a separate `csv-upload.spec.ts`).

No new fixtures or framework installs are needed on the backend side — the existing `db_available`/`db_session` pattern in `backend/tests/conftest.py` + `test_write_tools.py` is reused directly. The only new dependency is `recharts@^3.9.2` (frontend, Plan 04 Task 1, APPROVED in RESEARCH.md Package Legitimacy Audit).

---

## Manual-Only Verifications

Chart rendering and live-refresh visual behavior can only be fully confirmed in a browser; the Playwright specs assert structural presence (heading, figure captions, a chart `svg`, request interception), but the following visual qualities are manual-only:

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Donut / bar / trend charts render with correct slices, income=green / expense=red flat fills, no blank ResponsiveContainer | CASH-01/02/03 | Visual correctness of SVG chart shapes and colors is not reliably assertable in headless Playwright beyond `svg` presence | Seed data, open `/cashflow`, confirm the donut shows category slices, the income/expense bar uses `#4ade80`/`#f87171`, and the trend shows >=6 month bars |
| Dashboard figures + per-account balances update WITHOUT a page reload after a write | CASH-04/05 | "No reload" refetch is best confirmed by eye; e2e asserts request re-issue but not the perceived live update | Create/edit/delete a transaction and watch totals + per-account balances change with no navigation |
| Account delete reassign flow (422 → destination `<select>` → complete) reads clearly | CASH-05 / D-06 | The 422→reassign UX and copy are judged visually | Delete an account with transactions, confirm the reassign `<select>` appears with the affected-count copy, pick a target, confirm deletion |
| CSV upload "Parsed · Inserted · Skipped" line with Skipped colored red when >0 | CASH-08 | Color-by-count of the skipped segment is a visual check | Upload a small CSV (with some skippable rows) and confirm the result line and the red Skipped segment |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify (every task has a per-module pytest or tsc command)
- [x] Wave 0 covers all MISSING references (6 new test/spec files enumerated above)
- [x] No watch-mode flags (all commands are single-run: `-x -q`, `--noEmit`, `npm run e2e -- <spec>`)
- [x] Feedback latency < 60s (per-task ~5s, per-wave ~60s)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-07-04
