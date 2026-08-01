# Deferred Items — Phase 16 (ui-extend-existing-components)

Out-of-scope discoveries found while executing 16-02-PLAN.md (TransactionModal.tsx).
None of these were fixed — they are pre-existing and unrelated to this plan's
`files_modified` (`ui/app/cashflow/TransactionModal.tsx`).

## `ui/e2e/cashflow-crud.spec.ts` — 4 pre-existing failures

Confirmed pre-existing by inspecting code paths untouched by 16-02 (verified via
`git show b06868e:...` — the pre-16-02 baseline — and by tracing that the failing
assertions execute against logic this plan never modified):

1. **`Add transaction opens the modal and posts to /api/transactions`** (L87) and
   **`choosing + New category… reveals a text input and POSTs the typed name`** (L182)
   — both fail because `mockDashboard()`'s `/api/categories` route mock returns
   `{ categories: ["Food & Drinks", "Transport"] }` (a flat object), but
   `TransactionModal.tsx`'s `flattenCategories()` has expected a **tree** array
   (`CategoryNode[]` with `is_system`/`children`) since Phase 11's category
   rewrite. The mismatch throws inside the fetch effect's try/catch, silently
   degrading to an empty category list. Also, the "+ New category…" free-text
   add-a-category affordance the second test asserts does not exist in the
   component at all — it predates the Phase 11 category-tree rewrite and was
   never re-added. Fix belongs to whichever plan owns `cashflow-crud.spec.ts`'s
   category-mock maintenance, not 16-02.

2. **`Add account posts type:liquid to POST /api/accounts`** (L294) — RED
   baseline test added in `0b5edeb` (16-01 Wave 0 scaffolding) for D-07
   (`AccountManager.tsx` POST body gaining `type: "liquid"`). `AccountManager.tsx`
   is out of 16-02's `files_modified`; this lands with the plan that implements
   D-07 (per 16-PATTERNS.md, a separate plan from 16-02).

3. **`rename updates the category name with no confirm dialog`** (L390) and
   **`merge shows the ConfirmDialog with affected_count before posting`** (L419)
   — both assert a `CategoryManager` section on `/cashflow` that no longer
   exists; `ui/app/cashflow/page.tsx:835` documents category management moving
   to Settings > Categories in Phase 11 (D-16, plan 11-06). Stale test, unrelated
   to any Phase 16 work.

## `ui/e2e/platform-crud.spec.ts` — 1 pre-existing failure

4. **`Edit updates both name and kind via PUT /api/platforms/{id}`** (L88) —
   the test's own comment documents this: "D-08 gap: the edit row does not yet
   have a kind input — this locator is expected to fail to find a match until
   Plan 03 lands it." `PlatformManager.tsx` is out of 16-02's scope.

## Fixed (in-scope, not deferred)

For contrast — these WERE fixed as part of 16-02 because they were directly
caused by this plan's mandated changes:

- `cashflow-crud.spec.ts`'s 3 `getByPlaceholder("-25000")` locators, updated to
  `"25000"` (D-02 retires the signed placeholder/label; a plan-mandated,
  foreseeable collateral update, not a new bug).
- `record-modal.spec.ts`'s two `page.locator("form").filter({ hasText: "Add
  transaction" })` locators in the Transfer-create tests, which stopped
  matching once the CTA legitimately switched to "Add transfer" (UI-SPEC's
  distinct-copy requirement) — a locator-scoping bug exposed by, not caused
  by, spec-compliant behavior. No assertion/copy/endpoint/body-shape changed.
