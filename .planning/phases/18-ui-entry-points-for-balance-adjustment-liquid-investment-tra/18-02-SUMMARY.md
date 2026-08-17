---
phase: 18-ui-entry-points-for-balance-adjustment-liquid-investment-tra
plan: 02
subsystem: ui
tags: [nextjs, react, playwright, investments, e2e]

# Dependency graph
requires:
  - phase: 14
    provides: "POST /transactions/investment-transfer (XFER-02 backend), CASH sentinel convention for the investment-side deposit event"
  - phase: 17
    provides: "investments/[platformId]/page.tsx platform detail shell (PLAT-01) this plan adds the header action to"
provides:
  - "DepositCashModal.tsx: liquid-only account <select> + neutral-ink money preview + single atomic submit for liquid->investment transfers"
  - "'Deposit cash' header action on the platform detail page, wired to onSaved={load} refetch"
  - "investment-transfer.spec.ts: locked e2e contract for the XFER-02 UI surface (select-only account, payload shape, preview copy, error/empty-state copy)"
affects: [xfer-03-funded-buy-sell, ui-review]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Modal-owned GET /api/accounts fetch, client-filtered to type === 'liquid' — every account-selection field is a <select>, never free text (money-safety, RESEARCH Pitfall 2)"
    - "Page load() extracted from an inline useEffect IIFE into a named function (backed by a useRef cancellation flag) so a child modal's onSaved prop can trigger the same refetch"

key-files:
  created:
    - ui/app/investments/DepositCashModal.tsx
    - ui/e2e/investment-transfer.spec.ts
  modified:
    - ui/app/investments/[platformId]/page.tsx

key-decisions:
  - "Refactored the platform-detail page's fetch-on-mount effect into a named load() function (useRef-backed cancellation) rather than duplicating the fetch logic in a second effect, so DepositCashModal.onSaved={load} reuses the exact same fetch/parse/error-handling path"
  - "Field labels use htmlFor/id pairs (matching TransactionModal's tx-from-account convention) so Playwright's getByLabel resolves reliably, rather than HoldingModal's unassociated <label> convention"

requirements-completed: [XFER-02]

coverage:
  - id: D1
    description: "'Deposit cash' header action opens a modal with a liquid-only account <select>, neutral-ink preview, and submits to /api/transactions/investment-transfer, refetching platform detail on success"
    requirement: "XFER-02"
    verification:
      - kind: e2e
        ref: "ui/e2e/investment-transfer.spec.ts#submits a liquid-only transfer and refetches platform detail on success"
        status: pass
    human_judgment: false
  - id: D2
    description: "422 error shows 'Couldn't deposit cash: {detail}. Nothing was changed.' and the modal stays open"
    requirement: "XFER-02"
    verification:
      - kind: e2e
        ref: "ui/e2e/investment-transfer.spec.ts#shows the standard error copy and keeps the modal open on 422"
        status: pass
    human_judgment: false
  - id: D3
    description: "Zero liquid accounts shows the empty-state copy and disables submit"
    requirement: "XFER-02"
    verification:
      - kind: e2e
        ref: "ui/e2e/investment-transfer.spec.ts#shows the empty-state copy and disables submit with zero liquid accounts"
        status: pass
    human_judgment: false
  - id: D4
    description: "Live docker-compose UAT: a real deposit produces a Deposit event on the platform ledger and debits the chosen liquid account against real Postgres"
    human_judgment: true
    verification: []
    rationale: "Requires a running docker-compose stack with real Postgres; e2e specs are route-mocked and cannot exercise the live backend write path end-to-end."

duration: 8min
completed: 2026-08-17
status: complete
---

# Phase 18 Plan 02: Deposit Cash Transfer Entry Point Summary

**"Deposit cash" header action + DepositCashModal on the platform detail page — liquid-only `<select>` sourced from a modal-owned `GET /api/accounts` fetch, neutral-ink money preview, single atomic POST to `/api/transactions/investment-transfer`.**

## Performance

- **Duration:** ~8 min (commit-to-commit)
- **Started:** 2026-08-17T15:11:00+07:00 (approx, worktree setup)
- **Completed:** 2026-08-17T15:26:15+07:00
- **Tasks:** 2
- **Files modified:** 3 (2 created, 1 modified)

## Accomplishments
- New `DepositCashModal.tsx`: liquid-filtered account `<select>` (never free text — money-safety hard rule), neutral-ink "Moves Rp {amount} from {account} into {platform}." preview, plain `<input type="date">` sent as-is, empty-state + 422 error copy exactly per `18-UI-SPEC.md` Surface 2.
- "Deposit cash" primary-button header action added to `investments/[platformId]/page.tsx`, next to the platform `<h1>`, mounting the modal and refetching platform detail via `onSaved={load}` on success.
- `investment-transfer.spec.ts` authored RED (Task 1, 3 tests: success/422/empty-state) then turned GREEN (Task 2) — no backend endpoint, schema, or read was added or changed; XFER-02's Phase 13/14 backend was reused as-is.

## Task Commits

Each task was committed atomically:

1. **Task 1: Author the RED route-mocked e2e spec for the Deposit cash transfer (XFER-02)** - `ac956ad` (test)
2. **Task 2: Build DepositCashModal + the platform-detail "Deposit cash" action (D-03, D-04, D-07)** - `39d7d64` (feat)

**Plan metadata:** (this commit)

## Files Created/Modified
- `ui/app/investments/DepositCashModal.tsx` - New modal: liquid-only account select, amount/currency/date/notes fields, neutral-ink preview, submit to investment-transfer endpoint
- `ui/app/investments/[platformId]/page.tsx` - Added "Deposit cash" header button + modal mount; extracted `load()` from an inline effect so the modal's `onSaved` can refetch
- `ui/e2e/investment-transfer.spec.ts` - New Playwright spec: 3 tests (success/422/empty-state) locking the XFER-02 UI contract

## Decisions Made
- Reused `TransactionModal`'s `htmlFor`/`id` label-association convention (not `HoldingModal`'s unassociated `<label>`) so the e2e spec can use Playwright's `getByLabel` reliably — a pre-existing, established pattern in the same codebase, not a new one.
- Extracted the platform-detail page's fetch-on-mount logic into a named `load()` function backed by a `useRef` cancellation flag (rather than a `useState` cancel flag or a duplicated fetch), so the exact same fetch/parse/error path is reused both on mount and as the modal's `onSaved` callback.

## Deviations from Plan

None — plan executed exactly as written. Both tasks matched their acceptance criteria without needing a Rule 1-4 deviation.

## Issues Encountered

- **Environment-only, not a code issue:** `ui/playwright.config.ts` hardcodes port 3001 and `reuseExistingServer: true`; during this wave's parallel worktree execution, another sibling worktree's dev server was already bound to port 3001, so early GREEN verification runs against the tracked config silently exercised the *sibling's* stale build (missing the new button) instead of this worktree's code. Diagnosed via the Playwright page-snapshot (no "Deposit cash" button, despite the source clearly containing it) and confirmed by `EADDRINUSE` when starting a second dev server on 3001 from this worktree. Worked around by running a temporary, untracked `ui/playwright.local.config.ts` pointed at port 3457 for verification only; deleted before every commit (confirmed via `git status --short` showing a clean tree after each removal). No tracked file was changed to work around this — `ui/playwright.config.ts` is unmodified in this plan's diff.
- `ui/node_modules` did not exist in this worktree (gitignored, not checked out); ran `npm ci` once to install from the existing lockfile before any test could run. Not a plan deviation — standard worktree setup, no `package.json`/lockfile change.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- XFER-02 UI entry point ships complete and verified (route-mocked e2e); ready for Plan 03 (XFER-03 funded buy/sell) which extends `HoldingModal.tsx` with the same liquid-account-fetch pattern established here.
- Live docker-compose UAT (a real deposit against real Postgres) remains a human-verify item per the plan's `<verification>` section — not automatable from this worktree's route-mocked e2e suite.

---
*Phase: 18-ui-entry-points-for-balance-adjustment-liquid-investment-tra*
*Completed: 2026-08-17*

## Self-Check: PASSED

- FOUND: ui/app/investments/DepositCashModal.tsx
- FOUND: ui/app/investments/[platformId]/page.tsx
- FOUND: ui/e2e/investment-transfer.spec.ts
- FOUND: 18-02-SUMMARY.md
- FOUND commit: ac956ad (test)
- FOUND commit: 39d7d64 (feat)
- FOUND commit: 31bd39d (docs)
