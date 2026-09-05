---
phase: 17-ui-new-surfaces-records-tab-categories-manager
plan: 05
subsystem: ui
tags: [nextjs, react, investments, platform-detail, e2e]

# Dependency graph
requires:
  - phase: 17-ui-new-surfaces-records-tab-categories-manager (Plan 02)
    provides: RED e2e baseline (ui/e2e/platform-detail.spec.ts) locking the platform-detail route/copy/endpoint contract
  - phase: 17-ui-new-surfaces-records-tab-categories-manager (Plan 03)
    provides: GET /platforms/{id}/detail and GET /portfolio-events?platform_id= backend reads this page consumes
provides:
  - "ui/app/investments/[platformId]/page.tsx — Platform detail route: back-link, header, Subtotal/Realized/Unrealized stat cards, PnL/Buy & Sell segmented tabs, loading/error/404/empty states"
  - "ui/app/investments/page.tsx — group-header platform name links to /investments/{platform_id} when non-null; Unassigned stays plain text"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Money/qty/badge/pnl helper functions (fmtPlain, fmtSigned, pnlColor, fmtQty, badgeColor) are not exported from investments/page.tsx, so the new detail page copies them verbatim rather than importing — matches the plan's explicit 'reuse verbatim' instruction"
    - "Stat-card totals (Subtotal/Realized/Unrealized) are computed client-side by summing detail.holdings, since GET /platforms/{id}/detail returns only {subtotal, holdings} with no separate aggregate realized/unrealized fields"

key-files:
  created:
    - "ui/app/investments/[platformId]/page.tsx"
  modified:
    - "ui/app/investments/page.tsx"
    - "ui/e2e/platform-detail.spec.ts"

key-decisions:
  - "Realized/Unrealized stat-card totals reduce() over detail.holdings client-side (the backend group dict has no group-level aggregate field) — with the RED test's single-holding fixture this makes the stat-card total numerically identical to that holding's own PnL table row, which surfaced a genuine Playwright strict-mode locator collision (see Deviations)."
  - "HoldingModal (mentioned in the plan's key_links as a 'reuse verbatim' target) was NOT wired into this page — 17-UI-SPEC.md's Components 9-13 and the copywriting contract never spec a 'log event'/add-holding affordance on Platform detail, and platform-detail.spec.ts's 4 tests don't exercise one. Wiring it would be speculative scope not requested by the design contract or tests (YAGNI)."

requirements-completed: [PLAT-01]

coverage:
  - id: D1
    description: "Dynamic route /investments/[platformId] renders back-link, eyebrow, platform name+kind, and Subtotal/Realized/Unrealized stat cards fed by GET /api/platforms/{id}/detail + GET /api/portfolio-events?platform_id= (Promise.all)"
    requirement: "PLAT-01"
    verification:
      - kind: e2e
        ref: "ui/e2e/platform-detail.spec.ts — 'Platform detail shell (PLAT-01, D-08)'"
        status: pass
    human_judgment: false
  - id: D2
    description: "PnL/Buy & Sell segmented control (PnL default) switches between the holdings PnL table (Ticker/Qty/Avg cost/Price/Value/Realized/Unrealized) and the buy/sell event table (Date/Ticker/Side/Qty/Price), Side colored+Title-cased per event_type"
    requirement: "PLAT-01"
    verification:
      - kind: e2e
        ref: "ui/e2e/platform-detail.spec.ts — 'PnL tab (D-05, Component 11)' + 'Buy & Sell tab (D-05, Component 12)'"
        status: pass
    human_judgment: false
  - id: D3
    description: "Loading/error/404 states render the locked copy, with the back-link present on 404 so the user is never stranded"
    requirement: "PLAT-01"
    verification:
      - kind: e2e
        ref: "ui/e2e/platform-detail.spec.ts — 'Platform detail states (Component 13)'"
        status: pass
    human_judgment: false
  - id: D4
    description: "Investments page group-header platform name becomes a link only when platform_id is non-null; Unassigned bucket stays plain text"
    requirement: "PLAT-01"
    verification:
      - kind: other
        ref: "source review: ui/app/investments/page.tsx L524-561 (isUnassigned branch gates the Link vs. plain <span>)"
        status: pass
      - kind: e2e
        ref: "ui/e2e/platform-crud.spec.ts (3 tests, unaffected regression check)"
        status: pass
    human_judgment: false

duration: 55min
completed: 2026-08-02
status: complete
---

# Phase 17 Plan 05: Platform Detail Page Summary

**New `ui/app/investments/[platformId]/page.tsx` dynamic route composing the existing segmented control, stat-card grid, and investments-page money/badge/pnl helpers into a PnL/Buy & Sell drill-down for one platform, plus the Investments-page link-out — turning `platform-detail.spec.ts`'s 4 RED tests fully GREEN.**

## Performance

- **Duration:** ~55 min
- **Started:** 2026-08-02T17:2x (worktree spawn)
- **Completed:** 2026-08-02
- **Tasks:** 2 completed
- **Files modified:** 3 (1 created, 2 modified)

## Accomplishments

- `ui/app/investments/[platformId]/page.tsx`: `"use client"` page reading `platformId` via `useParams()`, fetching `GET /api/platforms/{id}/detail` + `GET /api/portfolio-events?platform_id=` in parallel via `Promise.all`. Renders the locked shell (back-link, "Platform" eyebrow, serif `<h1>` name + inline kind tag, 3-stat-card row) and the PnL/Buy & Sell segmented control (PnL default, ink-on-white active) copied verbatim from `TransactionModal.tsx`'s segmented-control markup.
- PnL tab: holdings table with the locked headers (Ticker/Qty/Avg cost/Price/Value/Realized/Unrealized), reusing `badgeColor()`/`fmtQty()`/`pnlColor()` (copied verbatim from `investments/page.tsx`, which doesn't export them) — Realized and Unrealized are explicit columns, not the main page's combined "Return" percentage.
- Buy & Sell tab: event table with the locked headers (Date/Ticker/Side/Qty/Price); Side renders `event_type` Title-cased ("Buy"/"Sell"/"Deposit"/"Withdrawal"/"Dividend"), colored green (buy/deposit), terracotta (sell/withdrawal), or ink (other).
- Loading ("Loading platform…"), error, and 404 ("Platform not found. It may have been deleted.") states all render with the back-link present above, so a bad `platformId` never strands the user (threat T-17-13).
- `ui/app/investments/page.tsx`: the group-header platform name is now a `<Link href="/investments/{platform_id}">` (cursor pointer, hover underline) when `platform_id` is non-null; the Unassigned bucket (`platform_id === null`) stays plain text, never a link.
- Both empty states ("No holdings on this platform yet." / "No buy/sell history on this platform yet.") wired per the copywriting contract.

## Task Commits

Each task was committed atomically:

1. **Task 1 + 2 (built together as one cohesive file): Dynamic route + shell + PnL/Buy&Sell tabs + Investments link-out** - `ceb82bc` (feat)
2. **Deviation: fix a pre-existing test-locator ambiguity uncovered by this implementation** - `714f95b` (test)

**Plan metadata:** (this commit)

## Files Created/Modified

- `ui/app/investments/[platformId]/page.tsx` (new) - platform detail route: shell, stat cards, segmented control, PnL table, Buy/Sell table, loading/error/404/empty states
- `ui/app/investments/page.tsx` - group-header platform name becomes a `Link` when `platform_id` is non-null
- `ui/e2e/platform-detail.spec.ts` - added `.first()` to 3 value assertions that collided under the single-holding fixture (see Deviations)

## Decisions Made

- The plan's two tasks (shell vs. tabs) were implemented as a single `Write` of the complete page component rather than two incremental edits, since the shell, tab state, and both tables live in one render function and splitting them into two artificial partial-file commits would have added no reviewability — Task 1's commit (`ceb82bc`) carries the full file; Task 2's distinct contribution was the test fix needed to get the full spec GREEN (`714f95b`).
- Platform-wide Realized/Unrealized stat-card totals are computed by summing `detail.holdings` client-side (`reduce()`), since `GET /platforms/{id}/detail` returns the raw `portfolio_summary()` group dict (`{platform_id, platform_name, kind, subtotal, holdings}`) with no separate aggregate PnL fields — confirmed against `backend/main.py:platform_detail` and `backend/portfolio.py:portfolio_summary`'s documented return shape.
- Did not wire `HoldingModal` into this page despite it being listed among the plan's `key_links` "reuse verbatim" targets — neither 17-UI-SPEC.md's Components 9-13 nor `platform-detail.spec.ts`'s 4 tests spec or exercise an add-holding/log-event affordance on Platform detail (that CTA lives on the parent Investments page). Adding it would be unrequested scope; noted here in case a future phase wants it.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Fixed a Playwright strict-mode locator collision in `platform-detail.spec.ts`**
- **Found during:** Task 1/2 verification (`npx playwright test e2e/platform-detail.spec.ts`)
- **Issue:** `platformDetailFixture()` (from 17-02) has exactly one holding, so `detail.subtotal` (6,000,000) is numerically identical to that holding's own `current_value` (6,000,000), and the stat-card `totalRealized`/`totalUnrealized` sums are identical to that same holding's `realized_pnl`/`unrealized_pnl` (200,000 / 1,000,000). Since the stat cards and the PnL table render simultaneously (PnL is the default tab), each of these three figures appears as two separate DOM elements with byte-identical text, and `expect(page.getByText(value)).toBeVisible()` (no `.first()`) throws a Playwright strict-mode "resolved to 2 elements" error — this is unavoidable given the fixture and the locked requirement that both the stat cards AND the PnL table show these dollar figures. The test file already uses `.first()` for the "Realized"/"Unrealized"/"BTC" **label** assertions for this exact same reason (documented in 17-02-SUMMARY.md's key-decisions) but hadn't applied it to the three **value** assertions.
- **Fix:** Added `.first()` to the `fmtPlain(6000000)`, `fmtSigned(200000)`, and `fmtSigned(1000000)` assertions, mirroring the established idiom already in the same file/test suite.
- **Files modified:** `ui/e2e/platform-detail.spec.ts`
- **Verification:** Full `platform-detail.spec.ts` suite (4 tests) passes after the fix; re-ran `platform-crud.spec.ts` (3 tests) to confirm no regression from the `investments/page.tsx` link-out change.
- **Committed in:** `714f95b`

---

**Total deviations:** 1 auto-fixed (Rule 3 — blocking test-locator ambiguity, not an implementation bug)
**Impact on plan:** No scope creep — a 3-line `.first()` addition to a test file's own existing pattern, required for the locked Component 9/11 dual-rendering requirement (stat cards + PnL table showing the same platform's Realized/Unrealized figures simultaneously) to be testable at all with a single-holding fixture.

## Issues Encountered

- **Playwright `webServer.reuseExistingServer: true` picked up the host's `monai-frontend` Docker container** (bound to port 3001 via `network_mode: host`) instead of starting a dev server from this worktree's own source — the container was serving the pre-Phase-17 build, so the new route 404'd on first test run. Worked around by: `docker stop monai-frontend` → `npm run dev -p 3001` from this worktree in the background → ran the verify suite → killed the worktree dev server → `docker start monai-frontend` to restore the container to its prior running state. This is a verification-environment workaround only; no code or config change was needed or made (`playwright.config.ts` untouched).
- `ui/node_modules` doesn't exist in this fresh worktree (same as 17-02's prior finding); symlinked to the main checkout's `ui/node_modules` to run the `<verify>` commands, then removed the symlink before committing — `node_modules/` is gitignored, so it left no trace in git.
- `npx tsc --noEmit` run over `ui/` reports zero errors after the new route + link-out change.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `platform-detail.spec.ts` is fully GREEN (4/4). PLAT-01 is functionally complete: a platform's detail page is reachable from the Investments list, shows scoped PnL and buy/sell history, and handles loading/error/404/empty states.
- No blockers for downstream plans. This plan touched only `ui/app/investments/[platformId]/page.tsx` (new), `ui/app/investments/page.tsx` (link-out), and `ui/e2e/platform-detail.spec.ts` (test-locator fix) — no backend, shared-component, or other-page changes, so it carries no risk to Plan 17-04 (Records page) or any other in-flight Phase 17 plan.
- Docker's `monai-frontend` container was stopped and restarted during this plan's verification; it is confirmed `Up` and running again post-verification.

---
*Phase: 17-ui-new-surfaces-records-tab-categories-manager*
*Completed: 2026-08-02*

## Self-Check: PASSED

- FOUND: ui/app/investments/[platformId]/page.tsx
- FOUND: ui/app/investments/page.tsx
- FOUND: ui/e2e/platform-detail.spec.ts
- FOUND: commit ceb82bc (Task 1/2 implementation)
- FOUND: commit 714f95b (test-locator fix deviation)
