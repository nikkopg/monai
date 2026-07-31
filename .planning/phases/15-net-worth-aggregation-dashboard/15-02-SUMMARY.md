---
phase: 15-net-worth-aggregation-dashboard
plan: 02
subsystem: ui
tags: [nextjs, react, typescript, dashboard]

# Dependency graph
requires:
  - phase: 15-net-worth-aggregation-dashboard (plan 01)
    provides: "GET /net-worth endpoint returning {total, liquid_total, investment_total, liquid_accounts, investment_groups, accounts_covered, accounts_total}"
provides:
  - "/cashflow hero net-worth number sourced from GET /net-worth (client-side double-count removed)"
  - "Liquid/Investment split row (two stat cards)"
  - "Liquid accounts breakdown card (per-account, server-filtered type='liquid')"
  - "Investment platforms breakdown card (per-platform subtotal, no delta)"
  - "Widened breakdown-row gate (renders on balance-without-activity)"
  - "422-distinct coverage-error copy on the hero"
affects: [16-liquids-and-investments-ui-extend-existing-components]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Fetch-once-on-mount for non-period-scoped data (loadNetWorth mirrors loadTxs, not loadSummary which reruns per period)"
    - "Inline conditional replacing a value with an error string in place (hero number -> netWorthError text) instead of a separate banner, to keep the distinct-copy requirement local to the affected number"

key-files:
  created: []
  modified:
    - ui/app/cashflow/page.tsx

key-decisions:
  - "netWorthData is fetched once on mount (useEffect with [] deps) + refreshed by refreshAll after writes — it is NOT re-fetched on period change like summary, since net worth is a point-in-time snapshot, not period-scoped"
  - "On netWorthError, the hero number is replaced in-place by the error copy (no separate banner) — keeps the 422-vs-network distinction visible exactly where the previously-wrong number was, without adding new layout"
  - "Category chart card renders even when hasActivity is false as long as the widened gate passes (liquid accounts or investment platforms exist) — categoryData will simply be empty; no extra gate added since UI-SPEC only prescribes the two breakdown cards' empty states, not hiding the (untouched, out-of-scope) category card"

requirements-completed: [NW-01, NW-02]

# Metrics
duration: ~15min
completed: 2026-07-31
---

# Phase 15 Plan 02: Net Worth Dashboard (Frontend) Summary

**`/cashflow` hero now reads net worth from `GET /net-worth` (fixing the client-side double-count), with a new Liquid/Investment split row and per-side breakdown cards (Liquid accounts, Investment platforms) reusing existing statCard/row markup.**

## Performance

- **Duration:** ~15 min
- **Completed:** 2026-07-31
- **Tasks:** 2/2 code tasks (Task 3 is a human-verify checkpoint, auto-approved per pipeline mode — see below)
- **Files modified:** 1

## Accomplishments
- Hero "Net worth" number is bound to `netWorthData.total` from `GET /net-worth`; the old client-side `reduce` over `summary.accounts` (the live double-count bug, since it summed BOTH liquid and investment-type account rows) is fully removed — confirmed by grep, zero `netWorth`/`reduce` matches remain
- The ▲/▼ hero delta chip is deleted (net-worth trend explicitly deferred per D-07/UI-SPEC — not invented)
- New Split row: "Liquid" and "Investment" stat cards with singular/plural account/platform-count subtext, reusing `statCard`/`statLabel`/`statValue` verbatim in neutral ink (not green)
- Breakdown row: "Accounts" renamed to "Liquid accounts", sourced from `netWorthData.liquid_accounts` (server-filtered `type='liquid'`); new third card "Investment platforms" sourced from `netWorthData.investment_groups`, same row shell, no delta line
- Breakdown-row gate widened: renders on `hasActivity || liquid_accounts.length>0 || investment_groups.length>0`, so a balance-only account with zero period transactions still shows
- Empty states ("No liquid accounts yet." / "No investment platforms yet.") and the 422-distinct coverage-error copy implemented verbatim per UI-SPEC's Copywriting Contract
- `cd ui && npx tsc --noEmit` clean; `npm run build` also clean (optional heavier gate, run for extra confidence)

## Task Commits

Each task was committed atomically:

1. **Task 1: Fetch GET /net-worth, source hero from it, remove client-side net-worth calc + delta chip** - `418e655` (feat)
2. **Task 2: Add split row + per-side breakdowns with gate + empty/error states** - `5dd4d7b` (feat)

**Plan metadata:** this SUMMARY.md, committed next (docs)

_Note: Task 3 (human-verify checkpoint) was auto-approved per the executing pipeline's `--auto` mode — see "Deferred Human Verification" below. No code changes for Task 3._

## Files Created/Modified
- `ui/app/cashflow/page.tsx` - Added `NetWorth`/`InvestmentGroup` types; `netWorthData`/`netWorthError` state + `loadNetWorth()` (fetch-once-on-mount + refreshAll); removed the client-side net-worth/delta `reduce`s and the delta chip block; hero number now binds to `netWorthData.total` with 422-distinct error copy shown in place; new Split row (Liquid/Investment stat cards); "Accounts" card renamed to "Liquid accounts" sourced from `netWorthData.liquid_accounts` with an empty state; new "Investment platforms" card sourced from `netWorthData.investment_groups` with an empty state; breakdown-row gate widened to include net-worth data presence independent of `hasActivity`

## Decisions Made
- `loadNetWorth()` fetches once on mount (like `loadTxs`), not on period change (like `loadSummary`) — net worth is a point-in-time snapshot, not period-scoped, per D-08/UI-SPEC
- 422 coverage-assertion error and generic network/backend-down error render distinct copy strings, both surfacing in place of the hero number (no separate banner) — keeps the fix local to the number that was wrong
- Reused only existing tokens/style objects (`statCard`/`statLabel`/`statValue`, `card`, `tokens.color.*`) — zero new design tokens, zero new components, per D-08 lock

## Deviations from Plan

None — plan executed exactly as written. No Rule 1-4 auto-fixes were needed; the existing code's `account_balances`/`AccountBalance` shape and the `GET /net-worth` payload (shipped in plan 15-01) lined up with the plan's prescribed field names with no gaps.

## Issues Encountered
- `ui/node_modules` was not present in this worktree (fresh checkout); ran `npm ci` before `npx tsc --noEmit` could execute. Not a plan deviation — a one-time environment setup step, not a code change.

## User Setup Required
None - no external service configuration required.

## Deferred Human Verification (Task 3)

Task 3 is a `checkpoint:human-verify` (visual dashboard confirmation) with `autonomous: false`. Per the orchestrating pipeline's `--auto` mode, this checkpoint is auto-approved for plan completion, but the actual **visual** verification (rebuild the stack, open `/cashflow`, eyeball the hero/split/breakdown) has NOT been performed by a human and could not be automated from within this worktree (no running dev stack). This surfaces as a **HUMAN-UAT item** for phase verification:

- Rebuild the stack (`docker compose up -d --build`) and open `http://localhost:3001/`.
- Confirm the hero "Net worth" number equals liquid total + investment total shown in the split row.
- Confirm no `type='investment'` account (e.g. legacy "Investments") appears in the Liquid subtotal or under "Liquid accounts" — its value should only appear under "Investment platforms".
- Confirm no ▲/▼ delta chip on the hero.
- Confirm split + breakdown still render for an account with a balance but no transactions this period.

What WAS verified automatically in this session:
- `cd ui && npx tsc --noEmit` — clean (strict typecheck, no errors).
- `cd ui && npm run build` — clean production build (optional heavier gate from the plan's `<verification>` section).
- Source-level assertions (via grep): hero binds to `netWorthData.total`; no client-side net-worth `reduce` remains; delta chip block removed; "Liquid accounts"/"Investment platforms" card titles and data sources present; widened gate references `netWorthData.liquid_accounts.length`/`investment_groups.length`; both empty-state strings and the 422 error string present verbatim.

## Next Phase Readiness
- NW-01 (UI) and NW-02 (UI) are code-complete and typecheck/build clean; live visual confirmation (Task 3) is deferred to phase-level HUMAN-UAT per the auto-pipeline's checkpoint-autonomy instruction.
- No blockers. Phase 16 (account/platform managers, record modal) can proceed independently — this plan touched only the `/cashflow` page's display, not CRUD surfaces.

---
*Phase: 15-net-worth-aggregation-dashboard*
*Completed: 2026-07-31*

## Self-Check: PASSED
- FOUND: ui/app/cashflow/page.tsx
- FOUND: .planning/phases/15-net-worth-aggregation-dashboard/15-02-SUMMARY.md
- FOUND: commit 418e655
- FOUND: commit 5dd4d7b
