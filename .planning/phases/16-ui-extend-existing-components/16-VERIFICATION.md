---
phase: 16-ui-extend-existing-components
verified: 2026-08-01T19:30:00Z
status: passed
human_verified: 2026-08-03T05:50:00Z  # all 3 human_verification items confirmed in 16-HUMAN-UAT.md (3/3 passed)
score: 8/8 must-haves verified
behavior_unverified: 0
overrides_applied: 0
human_verification:
  - test: "Open the record modal and visually compare the Expense/Income/Transfer segmented control against the Settings LLM-provider selector (UIR-07)."
    expected: "Same pill container, active-state white background + shadow, inactive muted/transparent — visually indistinguishable style."
    why_human: "Grep/structural checks confirm the JSX was copied verbatim, but pixel-level visual consistency needs an eye, not a selector match."
  - test: "Run `docker compose up -d --build` for the frontend service before any live/human click-through."
    expected: "The running monai-frontend container serves the current (Phase 16) build, not the stale pre-Phase-16 build this verifier found and worked around during automated checks."
    why_human: "Deployment step (project memory: deploy-requires-rebuild), not a code correctness gap — flagged so a human doesn't UAT against stale UI and file a false bug."
  - test: "In the live app (after rebuild), add a real Transfer record between two liquid accounts and confirm both legs appear correctly and account balances update as expected."
    expected: "Balances move atomically; no orphan leg; UI reflects the Phase-13 atomic-pair guarantee end-to-end."
    why_human: "Atomicity is a backend (Phase 13) guarantee re-confirmed structurally + via route-mocked tests here, but a real click-through against live Postgres data is the strongest signal before trusting this UI with real records."
---

# Phase 16: UI — Extend Existing Components Verification Report

**Phase Goal:** The account manager, platform manager, and transaction entry modal cover the full set of new record types without being rebuilt.
**Verified:** 2026-08-01T19:30:00Z
**Status:** passed — human verification complete 2026-08-03 (see 16-HUMAN-UAT.md, 3/3 passed)
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria + PLAN must_haves, merged)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | User can add, edit, and remove liquid accounts in the account manager (ACCT-01) | ✓ VERIFIED | `AccountManager.tsx` unchanged add/edit/remove + 422→reassign flow (byte-identical structure); `saveAdd` POST body now sends `{name, type:"liquid"}` (L48); `saveEdit` stays name-only (L73, D-07/Pitfall-4 honored). Behavioral: `cashflow-crud.spec.ts` "Add account posts type:liquid" and "account reassign-then-delete" both pass (2/2, run live against current source). |
| 2 | Platform manager reaches CRUD parity with the account manager (PLAT-02) | ✓ VERIFIED | `PlatformManager.tsx` gained `editKind` state (L35), seeded on Edit click (L223), bound to a second edit-row input (L174-179), `saveEdit` PUT body now carries `{name, kind}` (L75). Structural mirror of AccountManager retained (422→reassign flow untouched). Behavioral: `platform-crud.spec.ts` all 3 tests pass (add name+kind, edit name+kind via PUT, delete-with-reassign). |
| 3 | User can add a record via a modal with Expense/Income/Transfer segmented form — amount+currency, account, category picker, date-time, note, "add another" (REC-04) | ✓ VERIFIED | `TransactionModal.tsx`: 3-way segmented control (L360-397, Expense default L116), unsigned-amount→signed-value helper `signedAmount()` (L89-98), Currency field defaulting IDR (L128, L448-458), Category picker conditional on segment (L459-478), Date/Notes fields present, "Save & add another" button create-mode-only (L600-611). Behavioral: `record-modal.spec.ts` 8/8 pass, including the two state-transition-dependent scenarios (Save & add another stays-open/resets/preserves; edit-leg lock never routes to pair endpoint). |
| 4 | Transfer routes to the Phase-13 atomic-pair endpoint via an explicit whitelist body, never `is_transfer:true` on create (D-03) | ✓ VERIFIED | `handleSubmit`'s `showFromTo` branch (L219-256) builds `body` from an explicit named-field object (`from_account`, `to_account`, `amount`, `currency`, `date`, `notes` — no spread), POSTs to `/api/transactions/transfer`. Behavioral: Transfer-branch test asserts POST body shape and absence of category field; passes. |
| 5 | Editing an existing transfer leg locks the segment and never fires the create-only pair endpoint (RESEARCH Pitfall 1, T-16-02 mitigation) | ✓ VERIFIED (behavioral) | `locked = isEdit && editingTx.is_transfer` (L111) drives disabled segment control (L376, `onClick={locked?undefined:...}`), forces legacy single Account select (`showFromTo=false` when `isEdit`, L206), routes submit to `PUT /api/transactions/{id}` with `is_transfer: locked` explicit (L283, L292-295). This is a state-invariant claim — verified via the single named behavioral test `record-modal.spec.ts:324` ("editing a transfer-tinted row locks the segment... never routes to the pair endpoint"), run live against current source: **PASS**. |
| 6 | Same-account transfer guard blocks submit client-side (Pattern 5 safeguard) | ✓ VERIFIED | Guard at L212-215; behavioral test `record-modal.spec.ts:298` passes (no request issued, inline error shown). |
| 7 | Currency field defaults IDR and is sent on both transaction and transfer bodies (D-05) | ✓ VERIFIED | `currency` state default `"IDR"` (L128), included in both body objects (L229, L280). Asserted by Expense/Income tests. |
| 8 | Components extended in place, not rebuilt (roadmap constraint "without being rebuilt") | ✓ VERIFIED | `git log --stat`: AccountManager.tsx 1-line diff; PlatformManager.tsx +16/-6 line diff; TransactionModal.tsx three incremental commits (+42/-4, then further diffs) — all diffs are additive extensions of the pre-existing file, not full-file rewrites/replacements. |

**Score:** 8/8 truths verified (0 present-but-behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `ui/app/cashflow/TransactionModal.tsx` | Extended with segment/sign/currency/transfer/add-another/edit-lock | ✓ VERIFIED | All must-have behaviors present, substantive (620 lines, real logic not stubs), wired (mounted from `cashflow/page.tsx`, confirmed via graphify traversal), data flows (real `accounts`/`categories` props, real fetch calls) |
| `ui/app/cashflow/AccountManager.tsx` | `type:"liquid"` on create | ✓ VERIFIED | 1-line diff present, `saveEdit` correctly untouched |
| `ui/app/investments/PlatformManager.tsx` | `kind` editable on edit row | ✓ VERIFIED | `editKind` state/seed/input/PUT-body all present (`grep -c "editKind"` = 4 occurrences) |
| `ui/e2e/record-modal.spec.ts` | 8 REC-04 scenarios | ✓ VERIFIED | Exists, compiles (`tsc --noEmit` clean), 8/8 tests discovered and passing live |
| `ui/e2e/platform-crud.spec.ts` | 3 PLAT-02 scenarios | ✓ VERIFIED | Exists, compiles, 3/3 tests discovered and passing live (the SUMMARY-documented `hasText` locator bug was fixed — spec now uses a stable positional locator, confirmed by reading current source and a live green run) |
| `ui/e2e/cashflow-crud.spec.ts` | ACCT-01 type:liquid assertion added | ✓ VERIFIED | Extended, `type:liquid` test present and passing |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `TransactionModal.tsx` Expense/Income branch | `POST/PUT /api/transactions` | `fetch(url, {method})` L297 | ✓ WIRED | Confirmed in source + behavioral test |
| `TransactionModal.tsx` Transfer branch (create only) | `POST /api/transactions/transfer` | `fetch("/api/transactions/transfer", ...)` L233 | ✓ WIRED | Explicit whitelist body confirmed; behavioral test confirms body shape and that Expense/Income path is never hit for transfers |
| `TransactionModal.tsx` edit-transfer-leg | `PUT /api/transactions/{id}` (never the pair endpoint) | `locked` computed once, reused for segment-disable + submit routing | ✓ WIRED (behaviorally verified) | Named test `record-modal.spec.ts:324` passes live |
| `AccountManager.tsx saveAdd` | `POST /api/accounts` | body includes `type:"liquid"` | ✓ WIRED | Confirmed in source + passing test |
| `PlatformManager.tsx saveEdit` | `PUT /api/platforms/{id}` | body includes `kind` | ✓ WIRED | Confirmed in source + passing test |
| `ui/app/cashflow/page.tsx` | `<TransactionModal>` / `<AccountManager>` | mount points (graphify-confirmed, unchanged this phase) | ✓ WIRED | Per RESEARCH.md and graphify traversal — no new mount point needed this phase |

### Behavioral Spot-Checks (Step 7b — named tests run live, not `--list`)

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full record-modal.spec.ts (8 scenarios incl. state-transition/invariant tests) | `PLAYWRIGHT_CHROMIUM_PATH=/usr/bin/google-chrome npx playwright test e2e/record-modal.spec.ts` | 8/8 passed | ✓ PASS |
| Full platform-crud.spec.ts (3 scenarios) | same runner | 3/3 passed | ✓ PASS |
| cashflow-crud.spec.ts ACCT-01 scenarios | `... -g "account"` | 2/2 passed | ✓ PASS |
| `tsc --noEmit` (whole `ui/`) | `npx tsc --noEmit -p tsconfig.json` | exit 0 | ✓ PASS |
| Full cashflow-crud.spec.ts (regression check, all 10 tests) | full run | 6 passed, 4 failed | ⚠️ 4 pre-existing failures (see Deferred) |

All tests above were re-run live by this verifier against current source (not `--list`, not trusted from SUMMARY) after stopping the stale `monai-frontend` Docker container that was shadowing port 3001 with a July build, letting Playwright's own `npm run dev` compile current source, then restoring the container afterward.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| ACCT-01 | 16-01, 16-03 | Add/edit/remove liquid accounts in dedicated account manager | ✓ SATISFIED | REQUIREMENTS.md marked `[x]`, phase-map row "ACCT-01 \| Phase 16 \| Complete"; source + tests confirm |
| PLAT-02 | 16-01, 16-03 | Platform manager reaches CRUD parity with account manager | ✓ SATISFIED | REQUIREMENTS.md marked `[x]`, phase-map row "PLAT-02 \| Phase 16 \| Complete"; source + tests confirm |
| REC-04 | 16-01, 16-02 | Add a record via Expense/Income/Transfer segmented modal (amount+currency, account, category, date-time, note, add-another) | ✓ SATISFIED | REQUIREMENTS.md marked `[x]`, phase-map row "REC-04 \| Phase 16 \| Complete"; source + tests confirm |

No orphaned requirements — REQUIREMENTS.md's Phase 16 mapping (ACCT-01, PLAT-02, REC-04) exactly matches the union of `requirements:` fields declared across 16-01/16-02/16-03-PLAN.md frontmatter.

### Anti-Patterns Found

None. Grep for `TBD|FIXME|XXX|TODO|HACK|PLACEHOLDER|not yet implemented|coming soon` across the three modified components returned zero matches. No empty handlers, no hardcoded-empty stubs on the money paths. The one user-facing "not yet available" string (`"This is one leg of a transfer — full pair editing isn't available yet."`) is a deliberate, spec-mandated caption documenting Phase 17 scope, not a code-completeness debt marker.

### Deferred Items (not phase 16 gaps)

Pre-existing, unrelated e2e failures in `ui/e2e/cashflow-crud.spec.ts`, independently reproduced live by this verifier (4 failures, exactly matching `deferred-items.md`'s documented list):

| # | Test | Root cause | Owner |
|---|------|-----------|-------|
| 1 | `Add transaction opens the modal and posts to /api/transactions` | `mockDashboard()`'s `/api/categories` mock returns a flat shape; `flattenCategories()` has expected a tree since Phase 11 | Phase 11 category-mock maintenance, not Phase 16 |
| 2 | `choosing + New category… reveals a text input and POSTs the typed name` | The "+ New category…" affordance predates Phase 11's category-tree rewrite and was never re-added | Phase 11-adjacent, not Phase 16 |
| 3 | `rename updates the category name with no confirm dialog` | Asserts a `CategoryManager` section on `/cashflow` that moved to Settings in Phase 11 (D-16) | Stale test, not Phase 16 |
| 4 | `merge shows the ConfirmDialog with affected_count before posting` | Same as #3 | Stale test, not Phase 16 |

None of `TransactionModal.tsx`, `AccountManager.tsx`, or `PlatformManager.tsx` (this phase's `files_modified`) touch category-mock shape or the `/cashflow` `CategoryManager` mount — these are correctly out of Phase-16's blast radius and are not required by ROADMAP Phase 16's 3 success criteria. No later-phase match needed since these are legacy/Phase-11-owned, not forward-deferred work; documented here for completeness per the phase's own `deferred-items.md`.

## Human Verification Required

All 8 automated must-haves are VERIFIED (8/8) with no gaps — every truth in this table resolved to VERIFIED, not FAILED. Status is `human_needed` (not `passed`) solely because this touches real money-entry UI and the items below require a human eye / a rebuilt live deploy / a real-DB click-through, none of which a grep or route-mocked test can certify:

### 1. Visual segmented-control parity with Settings

**Test:** Open the record modal and visually compare the Expense/Income/Transfer segmented control against the Settings LLM-provider selector (UIR-07).
**Expected:** Same pill container, active-state white background + shadow, inactive muted/transparent — visually indistinguishable style.
**Why human:** Grep/structural checks confirm the JSX was copied verbatim, but pixel-level visual consistency needs an eye, not a selector match.

### 2. Deploy rebuild before human UAT

**Test:** Before any live/human click-through, run `docker compose up -d --build` for the frontend service.
**Expected:** The running `monai-frontend` container serves the current (Phase 16) build, not the July-dated stale build this verifier found and worked around.
**Why human:** This is a deployment step (already logged in project memory `deploy-requires-rebuild`), not a code correctness gap — flagged so a human doesn't UAT against stale UI and file a false bug.

### 3. End-to-end manual click-through of the CASH-deposit-sentinel-adjacent Transfer flow

**Test:** In the live app, add a real Transfer record between two liquid accounts and confirm both legs appear correctly (one debit, one credit) and account balances update as expected.
**Expected:** Balances move atomically; no orphan leg.
**Why human:** Atomicity is a backend (Phase 13) guarantee re-confirmed structurally here, but a real click-through against live Postgres data is the strongest signal before trusting this UI with real records.

---

_Verified: 2026-08-01T19:30:00Z_
_Verifier: Claude (gsd-verifier)_
