---
phase: 18-ui-entry-points-for-balance-adjustment-liquid-investment-tra
plan: 01
subsystem: ui
tags: [nextjs, react, playwright, cashflow, accounts]
status: complete

# Dependency graph
requires:
  - phase: 13-shared-mutation-layer
    provides: apply_add_balance_adjustment (fresh unfiltered SUM delta, composes apply_add_transaction)
  - phase: 14-rest-agent-mcp-registration
    provides: POST /api/accounts/{id}/adjust-balance REST endpoint (shipped + verified Phase 13/14)
provides:
  - "Adjust balance" row action in AccountManager.tsx (between Edit and Delete)
  - AdjustBalanceModal.tsx: single target-balance input with live signed delta preview
  - balance-adjust.spec.ts (RED->GREEN, 2 tests: success payload + 422 error copy)
affects: [cashflow, accounts]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "AdjustBalanceModal mirrors HoldingModal's overlay shell + Cancel/Submit row verbatim (no ConfirmDialog second step per D-07)"
    - "Presentation-only delta preview (target - current_balance); authoritative delta always recomputed server-side"

key-files:
  created:
    - ui/app/cashflow/AdjustBalanceModal.tsx
    - ui/e2e/balance-adjust.spec.ts
  modified:
    - ui/app/cashflow/AccountManager.tsx

key-decisions:
  - "AdjustBalanceModal pre-fills the target-balance input with account.current_balance so the initial state is delta===0 (submit disabled, muted 'No change' copy) until the user actually edits it"
  - "AccountManager's Account type widened to require current_balance (not optional) — the only call site (cashflow/page.tsx) already passes summary.accounts rows that carry it"

patterns-established:
  - "Row-action money-write modals (AdjustBalanceModal) reuse the HoldingModal overlay shell + local fmtPlain Intl.NumberFormat helper per-file, no shared utils module"

requirements-completed: [ACCT-02]

duration: 25min
completed: 2026-08-17
---

# Phase 18 Plan 01: Balance Adjustment Entry Point Summary

**"Adjust balance" row action + AdjustBalanceModal in AccountManager.tsx with a live signed-delta preview, posting `{target_balance}` to the existing `POST /api/accounts/{id}/adjust-balance` endpoint.**

## Performance

- **Duration:** ~25 min
- **Tasks:** 2 completed
- **Files modified:** 3 (1 new modal, 1 new e2e spec, 1 modified component)

## Accomplishments

- Users can now click "Adjust balance" on any liquid account row in Cashflow > Accounts, type a target balance, see a live signed delta preview, and submit — turning the ACCT-02 requirement into a shipped UI entry point (the backend write path was already built and verified in Phase 13/14).
- The delta preview correctly renders all three D-07 copy states: positive (green, `+Rp …`), negative (terracotta, `−Rp …` with U+2212 minus), and zero (muted, submit disabled).
- `balance-adjust.spec.ts` RED->GREEN across two tasks, exercising both the 201 success path (exact `{target_balance}` payload, summary refetch) and the 422 error path (standard error copy, modal stays open).

## Task Commits

Each task was committed atomically:

1. **Task 1: Author the RED route-mocked e2e spec for balance adjustment (ACCT-02)** - `91c730d` (test)
2. **Task 2: Build AdjustBalanceModal + the AccountManager "Adjust balance" row action (D-01, D-02, D-07)** - `e381a52` (feat)

_TDD task (Task 2, `tdd="true"`): the RED gate is Task 1's commit; Task 2's single commit is the GREEN gate (no separate refactor commit needed — implementation was correct on first pass)._

## Files Created/Modified

- `ui/app/cashflow/AdjustBalanceModal.tsx` - New overlay modal: single "Target balance" number input, live signed delta preview, Cancel/Save adjustment button row, posts to `/api/accounts/{id}/adjust-balance`
- `ui/app/cashflow/AccountManager.tsx` - Widened `Account` type to require `current_balance`; inserted "Adjust balance" row action (muted3, non-destructive) between Edit and Delete; mounted `AdjustBalanceModal` conditionally
- `ui/e2e/balance-adjust.spec.ts` - New Playwright spec, 2 tests (success payload/preview/refetch + 422 error copy)

## Decisions Made

- **AdjustBalanceModal pre-fills the target input with `account.current_balance`** rather than starting empty. This makes the initial render naturally satisfy the "delta === 0 -> submit disabled, muted 'No change' copy" contract from D-07/UI-SPEC without a separate empty-state branch, and matches the literal `delta = parseFloat(target || "0") - currentBalance` formula from 18-PATTERNS.md exactly.
- **`Account.current_balance` made required, not optional**, since the only call site (`cashflow/page.tsx:836`) already passes the richer `summary.accounts` (`AccountBalance[]`) rows — no defensive optional-chaining needed and it keeps the modal's prop type simple.

## Deviations from Plan

None - plan executed exactly as written. No Rule 1-4 auto-fixes were needed; the plan's `<action>` and `<behavior>` blocks were followed directly.

## Issues Encountered

- **Local dev-server port conflict during verification (not a plan/code issue):** a pre-existing root-owned Next.js process was already bound to port 3001 (the port `playwright.config.ts`'s `webServer` targets with `reuseExistingServer: true`), which would have made Playwright silently test against a stale server unrelated to this worktree's changes. Verified locally by temporarily pointing `playwright.config.ts` at port 3099 (`git checkout -- ui/playwright.config.ts` reverted it immediately after both the isolated `balance-adjust.spec.ts` run and the full-suite run completed) — no net change to the committed diff. Also symlinked `ui/node_modules` from the main worktree for the same local-verification purpose only (gitignored, removed before this summary).
- Ran the full e2e suite (`npx playwright test`) as an extra check beyond the plan's required scope: 48/52 passed; the 4 failures are the pre-existing, out-of-scope `cashflow-crud.spec.ts` category-manager failures already logged in `.planning/phases/16-ui-extend-existing-components/deferred-items.md` (stale `/api/categories` mock shape + CategoryManager moved to Settings in Phase 11) — unrelated to this plan's changes, not touched per plan instruction.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- ACCT-02 is done; Plans 18-02 (XFER-02 deposit-cash) and 18-03 (XFER-03 funded buy/sell) in this phase are independent (wave 1, no `depends_on`) and can proceed without any change here.
- Manual human-UAT against the live docker-compose stack (an adjust-balance submit produces a visible "Adjustment" record and the derived balance reconciles) is still open per the plan's `<verification>` section — not automatable, flagged for the phase's overall UAT pass.

---
*Phase: 18-ui-entry-points-for-balance-adjustment-liquid-investment-tra*
*Completed: 2026-08-17*

## Self-Check: PASSED

- FOUND: ui/app/cashflow/AdjustBalanceModal.tsx
- FOUND: ui/e2e/balance-adjust.spec.ts
- FOUND: .planning/phases/18-ui-entry-points-for-balance-adjustment-liquid-investment-tra/18-01-SUMMARY.md
- FOUND commit: 91c730d
- FOUND commit: e381a52
- FOUND commit: e4d0a66
