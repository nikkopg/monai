---
phase: 16-ui-extend-existing-components
plan: 03
subsystem: ui
tags: [react, nextjs, playwright, forms]

# Dependency graph
requires:
  - phase: 16-01
    provides: platform-crud.spec.ts (new) and the extended cashflow-crud.spec.ts account-create assertion (RED baselines)
provides:
  - AccountManager.saveAdd posts type:"liquid" explicitly on POST /api/accounts (ACCT-01/D-07)
  - PlatformManager inline edit row edits both name and kind, reaching add/edit CRUD parity (PLAT-02/D-08)
affects: [16-ui-extend-existing-components wave-merge verification, any future phase touching AccountManager.tsx or PlatformManager.tsx]

# Tech tracking
tech-stack:
  added: []
  patterns: []

key-files:
  created: []
  modified:
    - ui/app/cashflow/AccountManager.tsx
    - ui/app/investments/PlatformManager.tsx

key-decisions:
  - "AccountManager.saveEdit stays name-only (unchanged) — account type is not user-editable this phase, per D-07/Pitfall 4"
  - "PlatformManager editKind state seeded from p.kind ?? \"\" in the same Edit-click handler that seeds editName, mirroring the Add-form's kind input exactly (same width/placeholder)"

patterns-established: []

requirements-completed: [ACCT-01, PLAT-02]

# Metrics
duration: 55min
completed: 2026-08-01
---

# Phase 16 Plan 03: Close AccountManager/PlatformManager CRUD-parity gaps Summary

**AccountManager posts type:"liquid" on account create; PlatformManager's inline edit row gained a kind input so edit reaches full add/edit parity — two surgical, single-line-class diffs over already-correct components.**

## Performance

- **Duration:** 55 min
- **Started:** 2026-08-01T11:15:00Z (approx, session start)
- **Completed:** 2026-08-01T12:10:28Z
- **Tasks:** 2/2
- **Files modified:** 2

## Accomplishments
- `AccountManager.saveAdd` POST body now includes `type: "liquid"`; `saveEdit` untouched (name-only, byte-identical)
- `PlatformManager` gained `editKind` state (seeded on Edit click, bound to a new edit-row input mirroring the Add-form's kind input), and `saveEdit`'s PUT body now carries `{ name, kind }`
- Verified end-to-end against a real dev server (not just structurally): the PUT request genuinely carries both `name` and `kind` when a platform is edited

## Task Commits

Each task was committed atomically:

1. **Task 1: AccountManager sends type:liquid on create (D-07/ACCT-01)** - `0944cad` (feat)
2. **Task 2: PlatformManager edit row edits kind too (D-08/PLAT-02)** - `c80b30d` (feat)

**Plan metadata:** (this commit)

## Files Created/Modified
- `ui/app/cashflow/AccountManager.tsx` - `saveAdd`'s JSON body gains `type: "liquid"`; nothing else changed
- `ui/app/investments/PlatformManager.tsx` - new `editKind` state, seeded on Edit click, bound to a second edit-row `<input>`; `saveEdit`'s PUT body gains `kind`

## Decisions Made
- Account `type` stays a create-only field this phase (edit remains name-only) — matches D-07 and the deferred-ideas list, no type picker added.
- `kind` sent as `null` when the edit input is empty (mirrors the Add-form's `newKind || null` convention already in `saveAdd`).

## Deviations from Plan

None — both diffs match the plan's `<action>` blocks exactly (AccountManager: one line; PlatformManager: `editKind` state + seed + edit-row input + PUT body change). No architectural changes, no scope creep.

## Issues Encountered

**Environment: e2e verification required temporarily stopping the deployed `monai-frontend` Docker container.**
Port 3001 was occupied by the already-running `monai-frontend` container (deployed image, code frozen at last rebuild — per project convention "deploy requires rebuild", committed source ≠ running container). Playwright's `webServer` config uses `reuseExistingServer: true`, so it silently reused that stale container instead of compiling my edits, and the first `Add account posts type:liquid` run failed with the *old* `{name}`-only body. Diagnosed via the trace's captured network payload (`{"name":"Wallet"}`, no `type`). Resolved by `docker compose stop frontend`, letting Playwright's own `npm run dev` spin up fresh against current source, running the suite, then `docker compose start frontend` to restore the container to its prior running state (not rebuilt — no source changes were pushed into the image; a rebuild is a separate, explicit user action per the existing convention, out of scope here).

**Spec bug (pre-existing, out of scope): `platform-crud.spec.ts`'s "Edit updates both name and kind" test cannot pass as literally written, independent of implementation correctness.**
- **Root cause:** `const binanceRow = page.locator("tr", { hasText: "Binance" })` is a lazy locator, re-evaluated on every subsequent `binanceRow.*` call. The moment the row enters edit mode, the plain-text "Binance" is replaced by `<input value="Binance">` — and Playwright's `hasText`/`:has-text()` matching does **not** consider `<input>` `value` (confirmed via an isolated repro: `page.locator("tr",{hasText:"Binance"}).count()` goes from `1` to `0` immediately after the Edit click, in both a synthetic minimal-HTML test and the real running app). This means `binanceRow.locator("input").first().fill(...)` on the next line can never resolve, for **any** implementation that swaps the name cell to an `<input>` on edit — a property already true of the pre-Plan-03 code (single input, no kind field), not something introduced by this plan's diff.
- **Why not fixed here:** the plan's explicit constraint is "Make them GREEN without editing the specs." The only non-hacky way to satisfy this exact locator pattern would be to keep a hidden duplicate text node containing the original name during edit mode purely to satisfy `hasText` — which directly contradicts UI-SPEC Component Contract 6 ("No other visual change — row layout... stay exactly as today") and PATTERNS.md's mandate that this be a structural mirror of AccountManager. Editing the spec file is out of scope for this plan (it's a Wave-0/Plan-16-01 deliverable).
- **Verification of actual correctness:** confirmed the underlying feature works exactly as intended by driving the same page/route-mocks with an index-based (non-`hasText`-dependent) locator strategy against the real dev server: clicking Edit seeds both inputs from the platform's current values, editing them and clicking "Save platform" issues `PUT /api/platforms/1` with body `{"name":"Binance Global","kind":"exchange"}` — both fields present and correct.
- **Other 3 pre-existing e2e failures** (category-mock shape, `+New category` affordance) in `cashflow-crud.spec.ts` are unrelated, already logged in `.planning/phases/16-ui-extend-existing-components/deferred-items.md`, and untouched by this plan.
- **Recommendation:** file a spec-fix follow-up for `platform-crud.spec.ts` line 107 — replace `page.locator("tr", { hasText: "Binance" })` with an index/`nth()`-based row locator computed once before the Edit click (or re-derive via `page.locator("tr").filter({has: page.getByText("Binance", {exact:true})})` computed fresh only for the initial click), since any inline-edit-to-input pattern breaks `hasText` continuity by design.

## Verification Results

- `cd ui && npx playwright test e2e/cashflow-crud.spec.ts -g "account"` — 2/2 GREEN (account create `type:liquid` assertion, reassign-then-delete flow) — confirmed against a freshly-compiled dev server after working around the stale-container issue above.
- `cd ui && npx playwright test e2e/platform-crud.spec.ts` — 2/3 GREEN (add name+kind, delete-with-reassign); 1 fails due to the pre-existing spec locator bug documented above, not an implementation defect (confirmed via direct end-to-end drive).
- `cd ui && npx tsc --noEmit -p tsconfig.json` — clean for both modified files; 4 pre-existing errors remain in `e2e/record-modal.spec.ts` (untouched file, introduced in Plan 16-02, unrelated to this plan's scope).
- `grep -c "liquid" ui/app/cashflow/AccountManager.tsx` → 1; the only `type:` key is in `saveAdd`'s body.
- `grep -c "editKind" ui/app/investments/PlatformManager.tsx` → 3 (state declaration, seed, input binding — plus onChange/PUT-body uses).
- `saveEdit`'s PUT body in `PlatformManager.tsx` includes `kind` alongside `name`.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Both CRUD-parity gaps (ACCT-01, PLAT-02) closed; AccountManager and PlatformManager now match the v1.2 typed-model contract without a rebuild.
- Wave-merge verification (`cd ui && npm run e2e` full suite) will still show the pre-existing unrelated failures (category mock, record-modal tsc) and the platform-crud locator-bug test documented above — none block Phase 16 completion since they're either pre-existing/deferred or a documented spec defect outside this plan's edit scope.
- Recommend a lightweight follow-up (quick task or Phase 17 note) to fix the `binanceRow` locator in `platform-crud.spec.ts`.

---
*Phase: 16-ui-extend-existing-components*
*Completed: 2026-08-01*
