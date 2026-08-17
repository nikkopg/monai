---
phase: 18-ui-entry-points-for-balance-adjustment-liquid-investment-tra
plan: 03
subsystem: ui
tags: [nextjs, react, playwright, investments, e2e]
status: complete

# Dependency graph
requires:
  - phase: 13-shared-mutation-layer
    provides: "apply_add_funded_buy/apply_add_funded_sell atomic write primitives"
  - phase: 14-rest-agent-mcp-registration
    provides: "POST /portfolio-events/funded-buy and /portfolio-events/funded-sell REST endpoints (shipped + verified Phase 13/14)"
  - phase: 18-02
    provides: "investments/[platformId]/page.tsx post-Deposit-cash state (load() refactor, showDeposit) this plan extends alongside"
provides:
  - "HoldingModal.tsx funding selector: liquid-only 'Funding account' <select> routing Buy/Sell submits to funded-buy|sell while preserving the unfunded /api/portfolio-events escape hatch"
  - "cash_amount field defaulting to quantity x price, independently editable, funded preview line + CTA label switch"
  - "'+ Log event' btnDark trigger on the platform detail Buy & Sell tab, pre-selecting (not locking) the current platform via defaultPlatformId"
  - "funded-trade.spec.ts: locked e2e contract for XFER-03 (funded buy, funded sell, cash_amount default+edit, unfunded escape hatch)"
affects: [ui-review]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Modal-owned GET /api/accounts fetch, client-filtered to type === 'liquid' — reused verbatim from DepositCashModal/AdjustBalanceModal's established money-safety pattern (RESEARCH Pitfall 2)"
    - "A single isFunded boolean (fundingAccount set AND eventType !== 'dividend') is the one source of truth for routing, preview visibility, CTA label, and the cash_amount field's render/disable gating"
    - "Optional page-level fetch kept OUT of the page's required Promise.all — a failing/slow GET /api/platforms for the modal's Platform <select> can never break the platform detail view itself"

key-files:
  created:
    - ui/e2e/funded-trade.spec.ts
  modified:
    - ui/app/investments/HoldingModal.tsx
    - ui/app/investments/[platformId]/page.tsx

key-decisions:
  - "Kept HoldingModal's existing unassociated <label> convention for the new Funding account/Cash amount fields (mirrors the Platform select it extends) rather than introducing DepositCashModal's htmlFor/id convention mid-file; the e2e spec locates fields via the `label:text-is(...) + input|select` CSS adjacent-sibling combinator instead of getByLabel"
  - "isFunded excludes eventType === 'dividend' (no funded schema exists for it) — a chosen funding account is silently ignored and the unfunded path is used, per the plan's explicit dividend carve-out"
  - "Rule 2: added a client-side submit-disable when funded and cash_amount is not > 0, mirroring the backend's gt=0 Pydantic constraint on FundedBuyCreate/FundedSellCreate — not in the plan's literal action text but a correctness requirement to avoid a guaranteed 422 round-trip"
  - "load()'s new GET /api/platforms fetch (source for the modal's Platform <select>) is deliberately isolated in its own try/catch outside the required Promise.all, so an unmocked/failing platforms fetch can never cascade into breaking the platform-detail view — confirmed necessary by running the full pre-existing platform-detail.spec.ts suite before/after"

requirements-completed: [XFER-03]

coverage:
  - id: D1
    description: "HoldingModal's 'Funding account' <select> (liquid-only, GET /accounts) routes Buy to /api/portfolio-events/funded-buy and Sell to /api/portfolio-events/funded-sell with the full funded body (source_account_name, platform_id, ticker, quantity, price, cash_amount)"
    requirement: "XFER-03"
    verification:
      - kind: e2e
        ref: "ui/e2e/funded-trade.spec.ts#Test A: funded Buy routes to /api/portfolio-events/funded-buy with the full funded body"
        status: pass
      - kind: e2e
        ref: "ui/e2e/funded-trade.spec.ts#Test C: funded Sell routes to /api/portfolio-events/funded-sell"
        status: pass
    human_judgment: false
  - id: D2
    description: "cash_amount defaults to quantity x price, re-syncs only while untouched, and the edited value (not the recomputed default) is what gets posted"
    requirement: "XFER-03"
    verification:
      - kind: e2e
        ref: "ui/e2e/funded-trade.spec.ts#Test B: cash_amount defaults to quantity x price and an edited value is posted"
        status: pass
    human_judgment: false
  - id: D3
    description: "Leaving Funding account on '— none (unfunded) —' still POSTs the existing /api/portfolio-events path unchanged; funded-buy/funded-sell are never called"
    requirement: "XFER-03"
    verification:
      - kind: e2e
        ref: "ui/e2e/funded-trade.spec.ts#Test D: leaving Funding account on none still POSTs the unfunded /api/portfolio-events path"
        status: pass
    human_judgment: false
  - id: D4
    description: "The platform detail 'Buy & Sell' tab exposes a '+ Log event' btnDark trigger that mounts the funded-capable HoldingModal pre-selected (not locked) to the current platform and refetches on save; the 18-02 'Deposit cash' header action and platform-detail.spec.ts stay unregressed"
    requirement: "XFER-03"
    verification:
      - kind: e2e
        ref: "ui/e2e/platform-detail.spec.ts (all 4 tests)"
        status: pass
    human_judgment: false
  - id: D5
    description: "Live docker-compose UAT: a funded buy debits the chosen liquid account and records the holding/event in one atomic commit; a funded sell credits it"
    human_judgment: true
    verification: []
    rationale: "Requires a running docker-compose stack with real Postgres; e2e specs are route-mocked and cannot exercise the live dual-leg backend write path end-to-end."

duration: 20min
completed: 2026-08-17
---

# Phase 18 Plan 03: Funded Buy/Sell Entry Point Summary

**HoldingModal's "Funding account" selector routes Buy/Sell to `/api/portfolio-events/funded-buy|sell` with an editable qty×price-defaulted `cash_amount`, while the unfunded escape hatch and a new "+ Log event" platform-detail trigger both stay intact.**

## Performance

- **Duration:** ~20 min (commit-to-commit)
- **Started:** 2026-08-17T15:35:00+07:00 (approx, worktree setup + context read)
- **Completed:** 2026-08-17T15:54:20+07:00
- **Tasks:** 3
- **Files modified:** 3 (1 created, 2 modified)

## Accomplishments

- `HoldingModal.tsx` extended in place with a liquid-only "Funding account" `<select>` (modal-owned `GET /api/accounts` fetch, client-filtered `type === "liquid"`, never free text), an editable `cash_amount` field defaulting to `quantity × price`, a green/terracotta "Debits …"/"Credits …" preview, and a CTA label that switches to "Log funded Buy"/"Log funded Sell" — all while the existing unfunded `/api/portfolio-events` path stays byte-for-byte unchanged.
- A new "+ Log event" `btnDark` trigger sits at the top of the platform detail "Buy & Sell" tab, opening the same `HoldingModal` pre-selected (not locked) to the current platform via a new `defaultPlatformId` prop, and refetching platform detail on save.
- `funded-trade.spec.ts` authored RED (Task 1, 4 tests: funded Buy, cash_amount default+edit, funded Sell, unfunded escape hatch) then turned full GREEN (Task 3) — no backend endpoint, schema, or read was added or changed; XFER-03's Phase 13/14 backend was reused as-is.

## Task Commits

Each task was committed atomically:

1. **Task 1: Author the RED route-mocked e2e spec for funded (and unfunded) buy/sell (XFER-03)** - `3a939db` (test)
2. **Task 2: Extend HoldingModal with the funding selector, funded routing, cash_amount, preview, and defaultPlatformId (D-05, D-06, D-07)** - `8e85d3e` (feat)
3. **Task 3: Add the "+ Log event" funded trigger on the platform detail "Buy & Sell" tab (D-05)** - `1e29dfd` (feat)

**Plan metadata:** (this commit)

_Task 2 (`tdd="true"`): the RED gate is Task 1's commit; Task 2's single commit is the plan's own GREEN checkpoint for HoldingModal's routing/preview/CTA logic reached via the pre-Task-3 (partial) path — full-suite GREEN for `funded-trade.spec.ts` lands with Task 3's trigger, per the plan's documented sequencing note._

## Files Created/Modified

- `ui/e2e/funded-trade.spec.ts` - New Playwright spec: 4 tests (funded Buy / cash_amount default+edit / funded Sell / unfunded escape hatch) locking the XFER-03 UI contract
- `ui/app/investments/HoldingModal.tsx` - Added Funding account `<select>`, Cash amount field + resync logic, funded routing branch in `handleSubmit`, funded preview line, CTA label switch, `defaultPlatformId` prop
- `ui/app/investments/[platformId]/page.tsx` - Added "+ Log event" trigger + `HoldingModal` mount on the Buy & Sell tab; `load()` gained an isolated `GET /api/platforms` fetch for the modal's Platform select

## Decisions Made

- Kept HoldingModal's existing unassociated `<label>` convention for the two new fields (matches the file's own Platform-select pattern it extends) rather than mixing in DepositCashModal's `htmlFor`/`id` convention; the e2e spec instead locates fields via the `label:text-is(...) + input|select` CSS adjacent-sibling combinator.
- `isFunded` is a single boolean (`fundingAccount !== "" && eventType !== "dividend"`) reused for routing, preview visibility, CTA label, and the cash_amount field's render/disable gating — avoids four independent conditionals drifting out of sync.
- Rule 2 auto-add: submit is disabled when funded and `cash_amount` is not `> 0`, mirroring the backend's `gt=0` Pydantic constraint on `FundedBuyCreate`/`FundedSellCreate` — prevents a guaranteed 422 round-trip that the plan's literal text didn't call out but is a correctness requirement.
- The new `GET /api/platforms` fetch in `load()` is deliberately isolated in its own `try`/`catch`, outside the required `Promise.all` — verified necessary by running the pre-existing `platform-detail.spec.ts` suite (which doesn't mock `/api/platforms`) both before and after; an unmocked/failing platforms fetch inside the required `Promise.all` would have rejected the whole `load()` and broken every existing platform-detail test.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Client-side cash_amount > 0 guard on submit**
- **Found during:** Task 2
- **Issue:** The plan's `<action>` text didn't specify a disable condition for cash_amount validity; without one, a funded submit with an empty/zero cash_amount would round-trip to a guaranteed 422 from `FundedBuyCreate`/`FundedSellCreate`'s `gt=0` constraint.
- **Fix:** Added `(isFunded && !(parseFloat(cashAmount) > 0))` to the submit button's `disabled` expression.
- **Files modified:** `ui/app/investments/HoldingModal.tsx`
- **Verification:** Existing/new e2e tests unaffected (all fixtures use positive cash amounts); no new test added for the disabled-state edge case since UI-SPEC didn't lock its copy.
- **Committed in:** `8e85d3e` (Task 2 commit)

**2. [Rule 3 - Blocking] Isolated the new GET /api/platforms fetch outside the page's required Promise.all**
- **Found during:** Task 3
- **Issue:** Adding `fetch('/api/platforms')` directly into the existing `Promise.all([detailFetch, eventsFetch])` would make a rejected/unmocked platforms fetch (e.g., in `platform-detail.spec.ts`, which never mocks that route) reject the whole `load()`, breaking the platform detail view entirely.
- **Fix:** Moved the platforms fetch into its own `try`/`catch` after the required `Promise.all`, so its failure only leaves the modal's Platform `<select>` empty rather than blocking the page.
- **Files modified:** `ui/app/investments/[platformId]/page.tsx`
- **Verification:** Ran `platform-detail.spec.ts` (4/4 pass) and the full e2e suite (55/59 pass, pre-existing unrelated failures only) after the change.
- **Committed in:** `1e29dfd` (Task 3 commit)

---

**Total deviations:** 2 auto-fixed (1 missing-critical validation, 1 blocking-issue isolation)
**Impact on plan:** Both auto-fixes are correctness/robustness requirements uncovered while implementing the plan's literal text; no scope creep — no new UI surface, endpoint, or copy was added beyond what the plan and UI-SPEC specify.

## Issues Encountered

- **Environment-only, not a code issue:** per this session's `e2e_environment_notes`, `ui/playwright.config.ts` hardcodes port 3001 (bound to a stale `monai-frontend` Docker container) and a nonexistent `executablePath`. Verified against a temporary, untracked `ui/playwright.local.config.ts` (port 3459, the working Chromium binary at `/home/nikko/.cache/ms-playwright/chromium-1228/chrome-linux64/chrome`), deleted before every commit (`git status --short` confirmed clean each time). No tracked file was changed to work around this.
- `ui/node_modules` did not exist in this worktree (gitignored); ran `npm ci` once from the existing lockfile before any test could run. Not a plan deviation — standard worktree setup, no `package.json`/lockfile change.
- Ran the full e2e suite (`npx playwright test`) beyond the plan's required scope: 55/59 passed; the 4 failures are the pre-existing, out-of-scope `cashflow-crud.spec.ts` category-manager failures already logged in `.planning/phases/16-ui-extend-existing-components/deferred-items.md` — unrelated to this plan's changes.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- XFER-03 UI entry point ships complete and verified (route-mocked e2e); this closes out Phase 18's three UI entry points (ACCT-02 in 18-01, XFER-02 in 18-02, XFER-03 here).
- Live docker-compose UAT (a real funded buy/sell against real Postgres, confirming the atomic dual-leg write) remains a human-verify item per the plan's `<verification>` section — not automatable from this worktree's route-mocked e2e suite. Combine with 18-02's still-open UAT item for a single end-to-end UAT pass across both deposit and funded-trade flows.

---
*Phase: 18-ui-entry-points-for-balance-adjustment-liquid-investment-tra*
*Completed: 2026-08-17*

## Self-Check: PASSED

- FOUND: ui/e2e/funded-trade.spec.ts
- FOUND: ui/app/investments/HoldingModal.tsx
- FOUND: ui/app/investments/[platformId]/page.tsx
- FOUND: .planning/phases/18-ui-entry-points-for-balance-adjustment-liquid-investment-tra/18-03-SUMMARY.md
- FOUND commit: 3a939db (test)
- FOUND commit: 8e85d3e (feat)
- FOUND commit: 1e29dfd (feat)
