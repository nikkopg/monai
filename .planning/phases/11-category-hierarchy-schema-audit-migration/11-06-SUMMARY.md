---
phase: 11-category-hierarchy-schema-audit-migration
plan: 06
subsystem: ui
tags: [nextjs, react, category-hierarchy, settings, design-tokens]

requires:
  - phase: 11-category-hierarchy-schema-audit-migration (plan 03)
    provides: "Tree-shaped GET /categories, POST/PUT/DELETE /categories with block-or-reassign delete guard, /categories/{name}/affected-count"
provides:
  - "categoryPalette — 13-swatch closed color palette exported from ui/app/styles.ts (D-14)"
  - "ui/app/settings/CategoryManager.tsx — recursive tree manager with inline add/edit, block-or-reassign delete, merge, system-row locks"
  - "Settings > Categories card hosting the tree manager"
affects: []

tech-stack:
  added: []
  patterns:
    - "Recursive renderRow(node, depth) closure over component state — no tree-view library, per UI-SPEC's Don't Hand-Roll guidance for ~100 rows"
    - "Discriminated-union flow state (EditFlow/DeleteFlow/MergeFlow) mirroring the existing AccountManager reassign-flow pattern"
    - "Presentational components (CategoryManager) render as a fragment, not a self-wrapped card/section, so the hosting page supplies card chrome — new convention vs. the old cashflow managers which self-wrapped"

key-files:
  created:
    - ui/app/settings/CategoryManager.tsx
  modified:
    - ui/app/styles.ts
    - ui/app/settings/page.tsx
    - ui/app/cashflow/page.tsx
  deleted:
    - ui/app/cashflow/CategoryManager.tsx

key-decisions:
  - "Per-node inline Edit (name/color/icon) routes through PUT /categories/{id} rather than the legacy POST /categories/rename — PUT is a strict superset (built in plan 11-03 specifically for this UI) and avoids splitting one Save click into two requests when both name and color/icon change together."
  - "Merge (D-11, explicitly retained) keeps targeting POST /categories/merge via a per-row 'Merge into…' action, since it combines two DIFFERENT categories' transaction history — something the newer per-node PUT/DELETE cannot express."
  - "When DELETE returns 422 with child_count > 0, the UI shows a non-actionable error banner (not a reassign ConfirmDialog) — the real backend contract (11-03) unconditionally blocks deleting a category with subcategories even with reassign_to (reassign_to only ever moves transactions), so offering a 'Reassign & delete' CTA in that case would just resubmit into the same 422. The message still surfaces both affected_count and child_count per the UI-SPEC's dual-count copy, worded as a corrective instruction (remove/re-parent subcategories first) instead of an actionable choice."
  - "Root-level 'Add category' includes a Type (expense/income) select not specified in the UI-SPEC's row-action description, since CategoryCreate requires kind at root (parent_id=None) — omitted client-side field would leave root-add permanently broken."

requirements-completed: [CAT-02, CAT-04]

duration: "~35min wall"
completed: "2026-07-19"
status: complete
---

# Phase 11 Plan 06: Settings Category Tree Manager Summary

**Recursive, dependency-free tree manager in Settings > Categories implementing the full UI-SPEC Component 1 contract — collapsed-by-default expand/collapse, inline add/edit with a 13-swatch inheritable color palette, the two-count block-or-reassign delete guard, and system-row locks — replacing the old flat rename/merge table that lived on the Cashflow page.**

## Performance

- **Duration:** ~35 min
- **Tasks:** 3
- **Files modified:** 4 (1 created, 3 modified, 1 deleted)

## Accomplishments
- `categoryPalette` (13 named swatches) exported from `ui/app/styles.ts`, reusing 8 existing tokens (gold, terracotta, sage, sageLight, muted3, greenDark, muted2, muted, chartColors[5]) and adding 4 new same-family tints — one closed palette, no duplication (D-14)
- `ui/app/settings/CategoryManager.tsx`: recursive `renderRow(node, depth)` tree from `GET /api/categories`, collapsed top groups by default, 20px/level indent, 36px row height, emoji chip at 16%-opacity swatch background, hover-revealed Add subcategory / Edit / Delete actions, depth-3 cap enforced by hiding "Add subcategory" at depth 2
- Inline add/edit swaps the row into an input + 13-swatch picker (+ "inherit" option for non-root nodes) + emoji field, Save/Cancel — no modal
- Delete flow: `DELETE /api/categories/{id}`; reads both `affected_count` and `child_count` from the 422 detail; `child_count > 0` → non-actionable error banner (backend hard-blocks this case regardless of `reassign_to`); `affected_count > 0` and no children → reassign `ConfirmDialog` with a destination `<select>` excluding the node's own subtree (computed client-side via `descendantIds`)
- System rows (Transfer, Uncategorized): Delete rendered disabled/grayed with the exact copy "System category — can't be deleted."; Edit still allowed but the name input is replaced with static text
- Merge (D-11) retained as a per-row "Merge into…" action against `/api/categories/merge`, unchanged confirmation copy
- Settings page: new "Categories" card using the existing `cardTitle` (15px/600) pattern; Cashflow page's `CategoryManager` import/render site removed; old `ui/app/cashflow/CategoryManager.tsx` deleted (superseded, preserved in git history)

## Task Commits

1. **Task 1: Add categoryPalette to the token layer** - `b8ec4d4` (feat)
2. **Task 2: Recursive tree manager component in Settings** - `58064d0` (feat)
3. **Task 3: Mount in Settings, remove from Cashflow** - `adbebf0` (feat)

## Files Created/Modified
- `ui/app/styles.ts` - added `categoryPalette` export (13 entries), no existing token changed
- `ui/app/settings/CategoryManager.tsx` - new recursive tree manager (688 lines): fetch/render tree, inline add/edit, block-or-reassign delete, merge, system-row locks
- `ui/app/settings/page.tsx` - new Categories card mounting `CategoryManager`
- `ui/app/cashflow/page.tsx` - removed `CategoryManager` import and render site (AccountManager/CsvUpload untouched)
- `ui/app/cashflow/CategoryManager.tsx` - deleted (fully superseded)

## Decisions Made
See `key-decisions` in frontmatter: PUT-for-edit vs. legacy rename endpoint, merge retained separately, non-actionable error for the child_count>0 case, and the root-add Type selector needed for `CategoryCreate`'s server-side requirement.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Set iteration required downlevelIteration**
- **Found during:** Task 2 tsc verification
- **Issue:** `for (const id of someSet)` fails under this project's tsconfig (no explicit `target`, defaults below ES2015) with `TS2802: Type 'Set<number>' can only be iterated through when using the '--downlevelIteration' flag`.
- **Fix:** Replaced the `for...of` over `Set<number>` in `descendantIds` with `.forEach(...)`, which doesn't require the flag.
- **Files modified:** ui/app/settings/CategoryManager.tsx
- **Verification:** `cd ui && npx tsc --noEmit` exits 0
- **Committed in:** `58064d0` (Task 2 commit)

**2. [Rule 1 - Bug] Verify-command grep false-positive from a doc comment**
- **Found during:** Task 3 verification
- **Issue:** The plan's verify command greps for the literal string `cashflow/CategoryManager` across `app/**/*.tsx` to confirm no references remain; a design-intent comment in the new file's header happened to contain that exact substring, tripping the check even though it wasn't a real import.
- **Fix:** Reworded the comment to describe the move without repeating the literal path string.
- **Files modified:** ui/app/settings/CategoryManager.tsx
- **Verification:** verify command now prints "move complete"
- **Committed in:** `adbebf0` (Task 3 commit)

**3. [Rule 1 - Bug] CategoryManager double-wrapped in a card, and Settings lacked a build-tool bootstrap**
- **Found during:** Task 3 (mounting into Settings)
- **Issue:** The Task 2 component self-wrapped in `<section style={card}>` + a small 12px `label`, matching the OLD cashflow-page convention. But the plan's Task 3 explicitly wants a Settings-native "Categories" card using the 15px/600 `cardTitle` pattern (matching Provider/Keys/Preferences) — nesting the component's own card inside another card would double the border/padding.
- **Fix:** `CategoryManager` now returns a fragment (no self-wrapping card/label); `settings/page.tsx` supplies the `card` + `cardTitle` chrome, consistent with the page's other three cards.
- **Files modified:** ui/app/settings/CategoryManager.tsx, ui/app/settings/page.tsx
- **Verification:** `cd ui && npx tsc --noEmit` exits 0; visual nesting matches the other Settings cards
- **Committed in:** `adbebf0` (Task 3 commit)

---

**Total deviations:** 3 auto-fixed (1 blocking/tooling, 1 verify-script false-positive, 1 bug/structural)
**Impact on plan:** No scope creep — all three are correctness fixes needed to satisfy the plan's own stated acceptance criteria (tsc clean, verify command output, cardTitle pattern per Task 3's action text).

## Issues Encountered

**Docker rebuild deferred.** The plan's Task 3 action calls for `docker compose up -d --build` for live verification. This worktree's `docker-compose.yml` uses `network_mode: host` for the backend/frontend services, and `docker ps` showed `monai-frontend`/`monai-backend`/`monai-db` already running — this is a single shared, host-network-bound stack, not one scoped to this worktree. Running the rebuild here would restart that shared stack while the parallel 11-05 agent (owning `backend/writes.py`/`main.py`/`importer.py` in a sibling worktree) may still be mid-verification against it, risking a disruptive restart of a resource I don't exclusively own. Per the plan's own acceptance criteria, this live check is explicitly flagged `(human-check during phase UAT: expand/collapse, add/edit/delete, reassign flow, system lock)` — deferring it to the coordinated post-wave rebuild is the safe call rather than one parallel agent unilaterally restarting a shared container stack. `tsc --noEmit` and the static verify command (file deletion + no dangling references) both pass, which is everything this plan's automated gate requires.

## Next Phase Readiness

- Settings > Categories is the live management surface for the hierarchy (ROADMAP criterion 3); Cashflow page no longer hosts category management.
- The searchable grouped category picker (D-15, UI-SPEC Component 2) remains a locked design contract only — its component build is explicitly out of scope for this phase (deferred to Phase 16/17 per RESEARCH's Architectural Responsibility Map).
- Live UAT (docker compose rebuild + browser walkthrough of expand/collapse, add/edit/delete, reassign flow, system lock, merge) is the one remaining verification step, to run once the wave's parallel plans have landed and the shared stack is free to restart.
- No blockers for subsequent plans in this phase.

## Self-Check: PASSED

- `ui/app/styles.ts` — FOUND, contains `categoryPalette` export
- `ui/app/settings/CategoryManager.tsx` — FOUND
- `ui/app/cashflow/CategoryManager.tsx` — CONFIRMED DELETED
- Commit `b8ec4d4` (feat: categoryPalette) — FOUND
- Commit `58064d0` (feat: tree manager component) — FOUND
- Commit `adbebf0` (feat: mount/remove) — FOUND
- Commit `e8c6bb3` (docs: this summary) — FOUND
- `cd ui && npx tsc --noEmit` → clean (0 errors) — VERIFIED
- Verify command (`test ! -f ... && ! grep -rn ...`) → printed "move complete" — VERIFIED
