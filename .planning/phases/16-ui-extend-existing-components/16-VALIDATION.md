---
phase: 16
slug: ui-extend-existing-components
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-08-01
---

# Phase 16 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Playwright e2e (route-mocked backend) — no unit-test framework in `ui/` |
| **Config file** | `ui/playwright.config.ts` (verify during Wave 0) |
| **Quick run command** | `cd ui && npx playwright test <spec>` |
| **Full suite command** | `cd ui && npx playwright test` |
| **Estimated runtime** | ~30–90 seconds |

---

## Sampling Rate

- **After every task commit:** Run the relevant Playwright spec (`npx playwright test <spec>`)
- **After every plan wave:** Run the full Playwright suite
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** ~90 seconds

---

## Per-Task Verification Map

*Planner populates this table. Closest existing analog: `ui/e2e/cashflow-crud.spec.ts` (route-mocked CRUD). No `platform-crud.spec.ts` exists yet — Wave 0 gap.*

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 16-01-01 | 01 | 0 | REC-04 | — | N/A (scaffold) | e2e | `cd ui && npx playwright test e2e/record-modal.spec.ts --list` | ❌ W0 creates | ⬜ pending |
| 16-01-02 | 01 | 0 | REC-04 | T-16-02, T-16-03 | Transfer body whitelist + edit-leg-lock asserted | e2e | `cd ui && npx playwright test e2e/record-modal.spec.ts --list` | ❌ W0 creates | ⬜ pending |
| 16-01-03 | 01 | 0 | PLAT-02, ACCT-01 | — | N/A (scaffold) | e2e | `cd ui && npx playwright test e2e/platform-crud.spec.ts e2e/cashflow-crud.spec.ts --list` | ❌ W0 creates | ⬜ pending |
| 16-02-01 | 02 | 1 | REC-04 | T-16-04 | Client sign-derivation; backend remains source of truth | e2e | `cd ui && npx playwright test e2e/record-modal.spec.ts -g "segment\|Expense\|Income\|currency\|reverse"` | ✅ (after 16-01) | ⬜ pending |
| 16-02-02 | 02 | 1 | REC-04 | T-16-03 | Transfer POST body built from explicit field whitelist | e2e | `cd ui && npx playwright test e2e/record-modal.spec.ts -g "ransfer\|different"` | ✅ (after 16-01) | ⬜ pending |
| 16-02-03 | 02 | 1 | REC-04 | T-16-02 | Edit-leg lock → PUT /transactions, never pair endpoint | e2e | `cd ui && npx playwright test e2e/record-modal.spec.ts` | ✅ (after 16-01) | ⬜ pending |
| 16-03-01 | 03 | 1 | ACCT-01 | T-16-06 | Account create sends type:liquid; edit stays name-only | e2e | `cd ui && npx playwright test e2e/cashflow-crud.spec.ts -g "account"` | ✅ (after 16-01) | ⬜ pending |
| 16-03-02 | 03 | 1 | PLAT-02 | T-16-07 | Platform kind free-text, React-escaped on render | e2e | `cd ui && npx playwright test e2e/platform-crud.spec.ts` | ✅ (after 16-01) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] Extend `ui/e2e/cashflow-crud.spec.ts` (or add `record-modal.spec.ts`) — segmented Expense/Income/Transfer, sign derivation, transfer From/To → POST /transactions/transfer, currency field, "Save & add another" (REC-04)
- [ ] Add `ui/e2e/platform-crud.spec.ts` — add/edit(incl. kind)/delete-with-reassign parity (PLAT-02)
- [ ] Confirm `type: "liquid"` sent on account create (ACCT-01)

*Playwright infra already present (`ui/e2e/`); no framework install needed — verify config path in Wave 0.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Visual parity of segmented control with Settings UIR-07 | REC-04 | Pixel/style match is subjective | Open record modal, compare segmented control look to Settings provider selector |

*Automated e2e covers behavior; the visual-match check is the only manual item.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
