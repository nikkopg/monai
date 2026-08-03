---
phase: 18
slug: ui-entry-points-for-balance-adjustment-liquid-investment-tra
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-08-03
---

# Phase 18 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Playwright (route-mocked e2e) — `ui/` has no unit-test framework |
| **Config file** | `ui/playwright.config.ts` |
| **Quick run command** | `cd ui && npx playwright test <spec>` |
| **Full suite command** | `cd ui && npx playwright test` |
| **Estimated runtime** | ~30–60 seconds (mocked routes, no live backend) |

---

## Sampling Rate

- **After every task commit:** Run the task's Playwright spec (`npx playwright test <spec>`)
- **After every plan wave:** Run the full `ui/e2e/` suite
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** ~60 seconds

---

## Per-Task Verification Map

> Planner fills exact task IDs/commands. Each entry point below is UI-observable and
> route-mockable (mock the write endpoint, assert the request payload + success refetch).

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 18-01-xx | 01 | 1 | ACCT-02 | — | Adjust-balance modal POSTs `{target_balance}` to `/accounts/{id}/adjust-balance`; delta preview matches target − current_balance | e2e | `cd ui && npx playwright test e2e/balance-adjust.spec.ts` | ❌ W0 | ⬜ pending |
| 18-02-xx | 02 | 1 | XFER-02 | — | "Deposit cash" modal POSTs `{from_account, platform_id, amount}` to `/transactions/investment-transfer`; account field is a `<select>` (never free text) | e2e | `cd ui && npx playwright test e2e/investment-transfer.spec.ts` | ❌ W0 | ⬜ pending |
| 18-03-xx | 03 | 1 | XFER-03 | — | Funded HoldingModal POSTs `{source_account_name, platform_id, ticker, quantity, price, cash_amount}` to `/portfolio-events/funded-buy|sell`; cash_amount defaults to qty×price and is editable; unfunded path still POSTs `/portfolio-events` | e2e | `cd ui && npx playwright test e2e/funded-trade.spec.ts` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `ui/e2e/balance-adjust.spec.ts` — route-mocked spec for ACCT-02 entry point
- [ ] `ui/e2e/investment-transfer.spec.ts` — route-mocked spec for XFER-02 entry point
- [ ] `ui/e2e/funded-trade.spec.ts` — route-mocked spec for XFER-03 (funded + unfunded paths)

*Playwright is already installed and configured (`ui/e2e/`); no framework install needed — only the new specs above.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live end-to-end write against real Postgres (balance delta record appears; deposit event shows on platform ledger; funded trade debits/credits the liquid account) | ACCT-02, XFER-02, XFER-03 | Mocked e2e proves the UI request shape but not the backend dual-leg write against real data | Run each entry point against the docker-compose stack; confirm the Adjustment record, the deposit event on platform detail, and the liquid-account balance change |

*Route-mocked e2e covers the UI contract; the live dual-leg write is the human-UAT surface.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (the three new specs)
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
