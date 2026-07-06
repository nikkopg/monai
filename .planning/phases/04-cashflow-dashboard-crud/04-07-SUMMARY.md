---
phase: 04-cashflow-dashboard-crud
plan: 07
type: summary
gap_closure: true
requirements: [CASH-04, CASH-06]
status: complete
tasks_completed: 2
tasks_total: 2
---

# Plan 04-07 Summary — Category select in the Transaction modal

> **Note:** This SUMMARY was authored by the execute-phase orchestrator. The executor
> agent completed and committed both implementation tasks but hit its session limit
> before writing this file. Both commits are present on `main`; the code was verified
> post-merge (frontend `tsc --noEmit` clean).

## Objective

Close UAT gap 2 (minor, test 10): the Category field in the Add/Edit Transaction modal
was a free-text input, so a spelling/case variant (`jajan` vs `Jajan`) silently created a
duplicate category and fragmented spending. Per the user-chosen fix direction in
`04-UAT.md`, replace the free-text field with a select populated from `GET /categories`,
keeping a deliberate **+ New category…** affordance for genuinely new categories. No data
migration and no backend/schema change — existing duplicates are consolidated with the
already-shipped category merge feature (Plan 05 / D-09).

## Tasks

| # | Task | Commit |
|---|------|--------|
| 1 | Replace free-text category with a select sourced from `/categories` | `6cadea0` feat(04-07): replace free-text category with select from /categories |
| 2 | Drive the select in the e2e create/edit specs + new-category affordance spec | `0b1599f` test(04-07): drive select-based category field in cashflow-crud spec |

Merged to `main` via `de3c449` (`chore: merge executor worktree 04-07`).

## What shipped

- **`ui/app/cashflow/TransactionModal.tsx`**
  - `useEffect` fetches `GET /api/categories` on mount (through the Next.js proxy);
    on failure it degrades to an empty list so the field stays usable.
  - Category is now a `<select>` with three tiers of options: `(no category)` (value `""`),
    the stored names from the fetch, and a `+ New category…` sentinel option.
  - A non-printable sentinel (`" __new_category__"`) is used for the new-category option so
    it can never collide with a real stored name. Selecting it reveals a text input.
  - `categoryOptions` unshifts the edit target's current category when it is not in the
    fetched list, so opening the edit modal never blanks or mutates the current category —
    holds even when the fetch is slow or the name has since been merged away.
  - Submit preserves the existing category-or-null contract byte-for-byte: sentinel →
    trimmed new name or `null`; `""` → `null`; otherwise the exact stored name. No case
    variant can be introduced by a normal pick.
- **`ui/e2e/cashflow-crud.spec.ts`** — create/edit specs updated to drive the select;
  added a spec exercising the `+ New category…` affordance.

## must_haves verified

- Category field is a select sourced from `/api/categories`, with `(no category)` and
  `+ New category…` options. ✅ (`TransactionModal.tsx:235-247`)
- Picking an existing category submits the exact stored name; `(no category)` submits
  `null`. ✅ (`TransactionModal.tsx:129-132`)
- `+ New category…` reveals a text input for a deliberately-typed new name. ✅ (`:248-255`)
- Edit mode pre-selects the current category even if it is missing from the fetched list
  or the fetch is slow. ✅ (`categoryOptions`, `:111-116`)
- Submit body keeps the category-or-null contract — no backend or schema change. ✅

## Verification

- `npx tsc --noEmit` (ui/) — **clean, exit 0** (post-merge).
- e2e specs updated; they require a running stack + Playwright browsers to execute
  (`ui/e2e/cashflow-crud.spec.ts`). Not run headless in this session — flagged for the
  human browser-verify checkpoint.

## Deviations

None in the implementation. The only orchestrator-side deviation: this SUMMARY.md was
written by the orchestrator rather than the executor (executor session-limited after
committing both tasks). The scratch files the executor left in its worktree
(`ui/node_modules`, `ui/playwright.wt.config.ts`) were untracked and discarded with the
worktree — not merged.

## Follow-ups

- Human browser-verify of the create/edit category flow remains part of the Phase 4
  UAT checkpoint.
