---
phase: 16-ui-extend-existing-components
plan: 02
subsystem: ui
tags: [react, nextjs, playwright, typescript, cashflow, transfers]

# Dependency graph
requires:
  - phase: 16-ui-extend-existing-components (Plan 01, Wave 0)
    provides: ui/e2e/record-modal.spec.ts (frozen RED contract for REC-04)
provides:
  - Expense/Income/Transfer segmented control on TransactionModal (D-01)
  - Unsigned-amount entry with segment-derived sign (D-02)
  - Transfer create routed to the Phase-13 atomic-pair endpoint via an
    explicit-whitelist body (D-03)
  - Currency field defaulting IDR on both transaction and transfer bodies (D-05)
  - "Save & add another" fast-entry flow, create-mode only (D-06)
  - Edit-transfer-leg lock preventing orphan-pair creation on edit (RESEARCH
    Pitfall 1 / UI-SPEC Interaction States #7)
affects: [cashflow, mcp-tools-using-transactions-transfer, phase-17-new-surfaces]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Segmented control copied verbatim from settings/page.tsx (UIR-07) into a second consumer"
    - "Ref (not state) to carry which submit button fired across the click->submit event pair, avoiding a stale-closure gap"
    - "Explicit field whitelist for a cross-endpoint POST body, never a spread of general form state"

key-files:
  created: []
  modified:
    - ui/app/cashflow/TransactionModal.tsx
    - ui/e2e/record-modal.spec.ts
    - ui/e2e/cashflow-crud.spec.ts

key-decisions:
  - "Edit-transfer-leg submit preserves the row's original stored sign (via an originalSign param on signedAmount) rather than re-deriving it from the locked 'transfer' display segment — UI-SPEC 7 requires sign stay untouched on that path"
  - "locked (isEdit && editingTx.is_transfer) computed once and reused for segment-disable, category-visibility exception, and is_transfer:true on submit — single source of truth for the edit-lock state"
  - "Fixed two locator-scoping bugs (not behavior/copy changes) exposed by legitimate, spec-mandated UI text changes: record-modal.spec.ts's hasText:'Add transaction' filter went stale once the CTA correctly switched to 'Add transfer'; cashflow-crud.spec.ts's three getByPlaceholder('-25000') locators went stale once the placeholder was retired per D-02"

patterns-established:
  - "signedAmount(magnitude, segment, originalSign) helper — sign derivation point for all money-amount submits in this modal"

requirements-completed: [REC-04]

# Metrics
duration: ~110min
completed: 2026-08-01
---

# Phase 16 Plan 2: Extend TransactionModal for Expense/Income/Transfer Summary

**Single TransactionModal now covers Expense/Income/Transfer via a segmented control, deriving amount sign from the segment instead of manual +/-, routing Transfer through the atomic-pair endpoint with an explicit whitelist body, and locking the segment when editing an existing transfer leg so it can never spawn an orphan pair.**

## Performance

- **Duration:** ~110 min (across a connection-interrupted session)
- **Started:** 2026-08-01T11:00:00Z (approx, per STATE.md session start)
- **Completed:** 2026-08-01T11:41:12Z
- **Tasks:** 3/3
- **Files modified:** 3 (1 production component, 2 e2e specs — collateral locator fixes only)

## Accomplishments
- Expense/Income/Transfer segmented control (copied verbatim from settings/page.tsx's UIR-07 provider selector), Expense default on create, locked+disabled when editing an existing transfer leg
- Amount field retired the "negative = expense" convention: unsigned entry, sign derived from segment via a single `signedAmount()` helper; edit mode reverse-maps a stored signed amount to its absolute magnitude
- Transfer (create-mode only) swaps to From/To account selects, hides Category/Merchant, and POSTs an explicit-whitelist body to `/api/transactions/transfer` (the Phase-13 atomic-pair endpoint) — same-account submissions are blocked client-side with an inline error
- Currency field (plain text, default "IDR") added to both the transaction and transfer request bodies
- "Save & add another" (create-mode only): resets amount/category/merchant/notes, keeps segment/account(s)/date/currency sticky, always fires `onSaved()` for background refetch, keeps the modal open
- Editing an existing transfer leg is hard-locked to the legacy single-leg `PUT /api/transactions/{id}` path with `is_transfer: true` explicit in the body — the create-only pair endpoint is structurally unreachable from any edit path (`showFromTo = segment === "transfer" && !isEdit`)
- Full `record-modal.spec.ts` suite (8/8, the Wave-0 frozen contract) is GREEN

## Task Commits

Each task was committed atomically:

1. **Task 1: Segmented control + tokens import + unsigned amount/sign derivation + currency + category visibility** - `61af50a` (feat)
2. **Task 2: Transfer branch — From/To selects, whitelist body, same-account guard, remove is_transfer checkbox** - `e589f09` (feat)
3. **Task 3: Save & add another + edit-leg transfer lock** - `30f4bdb` (feat)

**Plan metadata:** (this commit, pending)

## Files Created/Modified
- `ui/app/cashflow/TransactionModal.tsx` — extended in place (D-01): segmented control, sign-derivation helper, currency field, Transfer submit branch, Save & add another, edit-transfer-leg lock
- `ui/e2e/record-modal.spec.ts` — 2 locator-scoping fixes (no assertion/copy/endpoint/body-shape change)
- `ui/e2e/cashflow-crud.spec.ts` — 3 stale-placeholder locator fixes (collateral of D-02's placeholder retirement)

## Decisions Made
- Edit-transfer-leg submit preserves the row's original stored sign (`originalSign` param) instead of re-deriving from the locked "transfer" display segment, per UI-SPEC 7 ("sign untouched")
- `locked` (`isEdit && editingTx.is_transfer`) is the single source of truth reused across segment-disable, the category-visibility exception, and `is_transfer: true` on submit
- Category cell stays visible in the edit-transfer-lock state (exception to the "hidden on Transfer" rule) since the row may carry pre-Phase-16 category data that hiding would silently drop
- `fromAccountId`/`toAccountId` default to the first two distinct accounts so the same-account guard never trips before the user interacts

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Fixed a locator-scoping bug in `record-modal.spec.ts`'s two Transfer-create tests**
- **Found during:** Task 2 verification
- **Issue:** `const form = page.locator("form").filter({ hasText: "Add transaction" })` stopped matching any element once the primary CTA legitimately switched to "Add transfer" after selecting the Transfer segment (Playwright locators re-evaluate on every action; UI-SPEC mandates this distinct copy). Every subsequent `form.getByLabel(...)`/`.click()` in those two tests then timed out against zero matched elements, even though the DOM (verified via Playwright's error-context page snapshot) was 100% spec-compliant: From/To selects present with correct options, Category hidden, "Add transfer" button rendered.
- **Fix:** Dropped the stale `hasText` filter (`page.locator("form")` — only one `<form>` renders while the modal is open). No assertion, copy, endpoint, or body-shape changed.
- **Files modified:** ui/e2e/record-modal.spec.ts
- **Verification:** All 8 record-modal.spec.ts tests pass
- **Committed in:** e589f09 (Task 2 commit)

**2. [Rule 3 - Blocking] Fixed 3 stale `getByPlaceholder("-25000")` locators in `cashflow-crud.spec.ts`**
- **Found during:** Task 3 wave-merge full-suite verification
- **Issue:** D-02 (this plan) retires the "-25000" signed placeholder in favor of "25000" (unsigned). Three pre-existing tests in the unrelated `cashflow-crud.spec.ts` file hardcoded the old placeholder text to locate the Amount field, breaking as a direct, foreseeable consequence of the plan-mandated UI change.
- **Fix:** Updated the 3 locators to `getByPlaceholder("25000")` and the typed values to the unsigned magnitude `"10000"` (Expense is still the default segment, so the posted amount is unaffected).
- **Files modified:** ui/e2e/cashflow-crud.spec.ts
- **Verification:** `(no category) POSTs a null category` now passes; full suite re-run confirms no new failures
- **Committed in:** 30f4bdb (Task 3 commit)

---

**Total deviations:** 2 auto-fixed (both Rule 3 — blocking test-harness issues exposed by, not caused by, correct spec-compliant implementation)
**Impact on plan:** Both fixes are narrowly-scoped locator/placeholder updates with zero change to test assertions, copy, endpoints, or body shapes. No scope creep.

## Issues Encountered
- **Docker port conflict during verification:** `docker ps` showed a `monai-frontend` container already listening on :3001, serving a July-18 production build (`x-nextjs-cache: HIT`). Playwright's `webServer.reuseExistingServer: true` latched onto that stale server instead of starting a fresh `npm run dev`, so early test runs showed the OLD modal UI (checkbox, "Amount (negative = expense)") despite correct source changes. Resolved by `docker stop monai-frontend` before test runs, `docker start monai-frontend` afterward to restore state. **Follow-up for the user:** the running `monai-frontend` Docker container still serves the pre-Phase-16 build — run `docker compose up -d --build` before any live/human UAT of this modal (matches the existing `deploy-requires-rebuild` project memory).
- **6 pre-existing, out-of-scope e2e failures** discovered during full-suite verification (unrelated to this plan's `files_modified`), logged to `.planning/phases/16-ui-extend-existing-components/deferred-items.md`: a stale `/api/categories` mock shape in `cashflow-crud.spec.ts` predating Phase 11's category-tree rewrite (2 tests), a removed "+ New category…" affordance the same file still asserts, a Plan-03-owned D-07 `AccountManager` RED baseline, a Plan-03-owned D-08 `PlatformManager` RED baseline (explicitly self-documented in the test's own comment), and 2 stale `CategoryManager`-on-`/cashflow` tests for a section moved to Settings in Phase 11 (D-16). None fixed — out of this plan's scope per the deviation rules' scope boundary.

## User Setup Required

None — no external service configuration required. See "Issues Encountered" above for the Docker rebuild note before UAT.

## Next Phase Readiness
- REC-04 is fully implemented and verified GREEN against its frozen Wave-0 contract (`record-modal.spec.ts`, 8/8)
- The atomic-pair Transfer endpoint (Phase 13) now has a real UI entry point; the CASH-deposit-sentinel decision from Phase 14 remains a separate, already-flagged item (unrelated to this plan)
- `deferred-items.md` lists 4 pre-existing gaps (D-07 `AccountManager`, D-08 `PlatformManager`, stale category mock, removed "+New category…") that belong to a different, not-yet-executed plan in this phase — worth confirming that plan's `files_modified` covers them before closing the phase
- Before human UAT: rebuild the Docker frontend (`docker compose up -d --build`) since the running container still serves a pre-Phase-16 build

---
*Phase: 16-ui-extend-existing-components*
*Completed: 2026-08-01*

## Self-Check: PASSED

- FOUND: ui/app/cashflow/TransactionModal.tsx
- FOUND: ui/e2e/record-modal.spec.ts
- FOUND: ui/e2e/cashflow-crud.spec.ts
- FOUND: .planning/phases/16-ui-extend-existing-components/deferred-items.md
- FOUND commit: 61af50a
- FOUND commit: e589f09
- FOUND commit: 30f4bdb
