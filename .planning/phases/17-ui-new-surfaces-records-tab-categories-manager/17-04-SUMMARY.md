---
phase: 17-ui-new-surfaces-records-tab-categories-manager
plan: 04
subsystem: ui
tags: [nextjs, react, playwright, records, transfer-pairs, bulk-actions, inline-styles]

# Dependency graph
requires:
  - phase: 17-ui-new-surfaces-records-tab-categories-manager (Plan 02)
    provides: ui/e2e/records.spec.ts — RED baseline locking the Records ledger's copy/interaction/endpoint contract
  - phase: 17-ui-new-surfaces-records-tab-categories-manager (Plan 03)
    provides: extended GET /transactions (filters + paging + transfer_pair_id), POST /transactions/bulk-delete, POST /transactions/bulk-recategorize
  - phase: 16-ui-extend-existing-components
    provides: TransactionModal (transfer-leg-locked edit mode), ConfirmDialog, styles.ts tokens, pair-aware single DELETE endpoint
provides:
  - ui/app/records/page.tsx — date-grouped ledger, daily net (excludes transfer pairs), full filter bar, transfer-pair collapse, multi-select bulk delete/recategorize, load-more paging
  - ui/app/components/Nav.tsx — "Records" nav entry (href /records, ledger glyph) inserted after Cashflow
affects: [17-05 (Platform detail — independent, shares no files)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Row-scoping locator pattern: when a Playwright div:has-text() idiom needs to isolate ONE row, every wrapper ABOVE the row (page root, card, day-group) must NOT be a <div> (use <section> instead), and every wrapper INSIDE the row must NOT be a <div> either (use <span> with display overrides) — otherwise .first()/.last() resolves to an ancestor/descendant instead of the row, since hasText matches every div in the text's ancestor chain, not just the narrowest one."

key-files:
  created:
    - ui/app/records/page.tsx
  modified:
    - ui/app/components/Nav.tsx
    - ui/e2e/records.spec.ts

key-decisions:
  - "Tasks 1-3 committed as a single feat commit for records/page.tsx (plus a separate Nav.tsx commit) rather than three incremental commits — the filter shell, date-grouping, and bulk-select all share one render tree in one new file; a true per-task split would require authoring and re-verifying artificial intermediate states with no independent value."
  - "collapseTransferPairs() copied verbatim from 17-RESEARCH.md; From/To in a collapsed row resolved by amount sign (negative leg = From/outgoing, positive leg = To/incoming), not by legA/legB array order, since collapseTransferPairs' legA is whichever leg the server returned first."
  - "'Showing {shown} of {total}' (17-UI-SPEC Copywriting Contract) omitted — GET /transactions returns a bare list with no total-count field, and fabricating a total would violate the project's never-fabricate-a-number principle (CLAUDE.md Core Value). Not covered by any records.spec.ts assertion."
  - "flattenCategories() duplicated locally (not imported) — it exists as an unexported local helper in TransactionModal.tsx and a differently-shaped flattenAll in CategoryManager.tsx; neither is a shared module, so replicating the small (10-line) pure function here matches the existing project convention of no cross-file component-internal sharing rather than introducing a new shared module for this plan alone."

requirements-completed: [REC-01, REC-02, REC-03, REC-05]

duration: ~35min
completed: 2026-08-02
status: complete
---

# Phase 17 Plan 04: Records Ledger Page Summary

**Date-grouped transaction ledger (`ui/app/records/page.tsx`) with a transfer-excluding daily net, a debounced server-side filter bar, transfer-pair row collapse, persistent multi-select bulk delete/recategorize, and load-more paging — pure composition of the 17-03 backend contract and Phase 16's TransactionModal/ConfirmDialog, turning `records.spec.ts`'s 7 RED tests GREEN.**

## Performance

- **Duration:** ~35 min
- **Tasks:** 3 completed (committed as 2 code commits + 1 test-fix commit, see below)
- **Files modified:** 3 (1 new, 2 modified)

## Accomplishments

- Nav gained a "Records" entry (ledger-glyph icon) between Cashflow and Chat.
- `ui/app/records/page.tsx`: locked header + "+ Add record" (TransactionModal create mode); filter bar (search/account/category/type/min/max/show-transfers) debounced 300ms, offset always resets to 0 on change, maps to the 17-03 query-param contract, `limit=100` + "Load 100 more" paging (hidden on a short page).
- Local-calendar-date grouping with a per-day "Net {signed}" header that sums only `transfer_pair_id IS NULL` rows (a collapsed transfer pair, or a degraded single visible leg, always contributes zero) — verified against the RED spec's fixture (Today: −25,000 excluding the 302/303 pair; Yesterday: +50,000; 10-days-ago: +185,000 including an Adjustment row).
- `collapseTransferPairs()` (copied verbatim from 17-RESEARCH) renders a shared `transfer_pair_id` as one "Transfer: From → To" row (tintNeutral, unsigned ink amount); degrades to a normal row + muted "(transfer)" tag when a filtered view only surfaces one leg — never throws on a missing sibling.
- Persistent 28px-gutter checkboxes on every row; selecting a collapsed pair selects both leg ids. Bulk bar: immediate `POST /transactions/bulk-recategorize` (partial-skip note surfaced), `ConfirmDialog`-gated `POST /transactions/bulk-delete`. Transfer-pair Edit opens `TransactionModal` in the Phase-16 locked mode; Delete (single or pair) always routes through the pair-aware DELETE endpoint — no single-leg edit path exists.
- Full `records.spec.ts` suite: 7/7 passing.

## Task Commits

Each task was committed atomically:

1. **Task 1 (Nav portion): Records nav entry** — `5e18555` (feat)
2. **Tasks 1-3 (page portion): Records ledger page — filter bar/shell, date-grouped ledger + daily net + transfer-pair collapse, multi-select bulk actions** — `4e12737` (feat) — see Decisions Made for why these three tasks share one commit
3. **records.spec.ts locator/visibility bug fixes (Rule 3, blocking)** — `938e78c` (fix)

**Plan metadata:** (this commit)

## Files Created/Modified

- `ui/app/records/page.tsx` (new) — Records ledger page: filter bar, date-grouped ledger + daily net, transfer-pair collapse, multi-select + bulk bar
- `ui/app/components/Nav.tsx` — added the "Records" nav entry + ledger-glyph icon case
- `ui/e2e/records.spec.ts` — two locator/assertion bugs fixed (see Deviations)

## Decisions Made

See `key-decisions` in frontmatter (Task-commit consolidation, From/To resolution by sign, omitted "Showing X of Y", duplicated `flattenCategories`).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `records.spec.ts` asserted visibility of native `<option>` text — unfixable via implementation, fixed at the test's locator level**
- **Found during:** Task 1 (filter bar verification)
- **Issue:** `getByText("All accounts"/"All categories"/"All types", { exact: true }).toBeVisible()` targets an `<option>` element. Verified empirically (standalone Playwright script against this project's exact `PLAYWRIGHT_CHROMIUM_PATH=/usr/bin/google-chrome` binary) that a selected `<option>` inside a closed native `<select>` is never reported visible by Playwright — this is genuine browser/DOM behavior (the option has no box while the select is closed), not an implementation defect. The 17-UI-SPEC explicitly mandates native `<select>` controls (matching every other picker in the app), so switching to a custom dropdown to make the label "visible" would have been a much larger, inconsistent architectural change.
- **Fix:** Changed the 3 assertions to `page.locator("select").filter({ hasText: "All accounts" })` (etc.) — asserts the same default-label text exists AND that the (genuinely visible) `<select>` itself is visible, preserving intent without weakening the check.
- **Files modified:** `ui/e2e/records.spec.ts`
- **Verification:** `records.spec.ts` "filter bar" test passes.
- **Committed in:** `938e78c`

**2. [Rule 3 - Blocking] `records.spec.ts`'s row-checkbox locator used `.first()` where the app shell's structure requires `.last()`**
- **Found during:** Task 3 (bulk-action verification)
- **Issue:** `page.locator("div", { hasText: "Warung Sate" }).first()` was intended to grab the specific ledger row's checkbox. Playwright's `hasText` filter matches every ANCESTOR `<div>` wrapping the text, not just the narrowest one, and `layout.tsx` (out of this plan's scope) wraps every page in two persistent shell `<div>`s — so `.first()` always resolved to a shell div spanning the whole page (confirmed: `.locator('input[type="checkbox"]')` inside it matched all 6 checkboxes on the page, not just the row's one).
- **Fix:** Restructured `records/page.tsx` so every wrapper between the app shell and a ledger row (page root, ledger card, day-group) is a `<section>` (not `<div>`), and every wrapper inside a row (primary/meta text) is a `<span>` — leaving each row as the sole `<div>` in its own subtree. With that, switched both occurrences of `.first()` to `.last()` in `records.spec.ts` (the row is now correctly the innermost/deepest — i.e. last-in-document-order — matching div, after the two unavoidable shell divs).
- **Files modified:** `ui/app/records/page.tsx` (structural, not behavioral), `ui/e2e/records.spec.ts` (locator fix)
- **Verification:** `records.spec.ts` "Warung Sate" checkbox-selection and "Transfer: Cash → Bank" pair-row assertions both pass (the latter needed the same span/section restructuring — its own `.last()` was previously resolving to the primary-text-only span instead of the whole row before the fix).
- **Committed in:** `4e12737` (structural page.tsx change), `938e78c` (spec locator change)

---

**Total deviations:** 2 auto-fixed (both Rule 3 — blocking test-authoring/browser-semantics issues, not code bugs in the feature itself)
**Impact on plan:** No scope creep. Both fixes are mechanical (locator-strategy corrections matching genuine, verified browser/DOM behavior) — no assertion's *intent*, no locked copy, and no endpoint contract changed. `records.spec.ts` remains a faithful GREEN target for REC-01/02/03/05.

## Issues Encountered

- **Port 3001 collision with a sibling worktree agent.** Playwright's `webServer.reuseExistingServer: true` reused a dev server already running on `127.0.0.1:3001` from a different, concurrently-executing worktree agent (17-05's plan, in a sibling `.claude/worktrees/` checkout under the same orchestrating session) — that server served the OLD build (no `/records` route), producing a 404 that looked like a routing failure. Diagnosed via `ss -ltnp` + `ps aux` (confirmed the PID belonged to a sibling worktree's `npm run dev`, not mine). Resolved by running a scratch `playwright.local.config.ts` (isolated port 3011, own `webServer`) for all verification in this plan — never committed, deleted before the final state was reached. No changes were needed to the canonical `playwright.config.ts`.
- **`Set`/`Map` spread (`[...selectedIds]`, `[...map.entries()]`) failed `tsc --noEmit`** (`TS2802`, no `--downlevelIteration`/ES2015+ target configured in `ui/tsconfig.json`) — switched to `Array.from(...)`, matching the fact that no existing file in the codebase spreads a `Set`/`Map` literal.
- The worktree had no `ui/node_modules` (fresh checkout) — symlinked to the main checkout's `ui/node_modules` purely to run `tsc`/Playwright locally, then removed before the final commit (gitignored, left no trace).

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Plan 17-05 (Platform detail page) is fully independent — no shared files, no shared state; its own `platform-detail.spec.ts` RED baseline is untouched by this plan.
- `ui/app/components/Nav.tsx` now has 5 entries; `smoke.spec.ts`'s "shows exactly four nav links" tests remain valid (they scope to a hardcoded 4-name regex, not "all nav links", so they pass unaffected).
- Pre-existing, out-of-scope failures confirmed unrelated to this plan's changes (already logged in `.planning/STATE.md` Blockers/Concerns and `16-.../deferred-items.md`): 4 `cashflow-crud.spec.ts` failures (stale `/api/categories` mock shape / removed `+New category` affordance / category-management-moved-to-Settings tests). `platform-detail.spec.ts`'s 4 failures are 17-05's own not-yet-built scope, not a regression from this plan.

---
*Phase: 17-ui-new-surfaces-records-tab-categories-manager*
*Completed: 2026-08-02*

## Self-Check: PASSED

- FOUND: ui/app/records/page.tsx
- FOUND: ui/app/components/Nav.tsx
- FOUND: commit 5e18555 (Nav entry)
- FOUND: commit 4e12737 (Records ledger page)
- FOUND: commit 938e78c (records.spec.ts locator fixes)
