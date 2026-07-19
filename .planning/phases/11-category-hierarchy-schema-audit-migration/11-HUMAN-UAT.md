---
status: partial
phase: 11-category-hierarchy-schema-audit-migration
source: [11-VERIFICATION.md]
started: 2026-07-20
updated: 2026-07-20
---

## Current Test

[awaiting human testing]

**Prerequisite:** the backend container on :8001 served pre-Phase-11 code during
verification. Run `docker compose up -d --build` before testing, or these
screens will show stale behaviour.

## Tests

### 1. Settings > Categories tree walkthrough
expected: Top-level groups render collapsed by default with emoji + colour
swatch; expanding indents children by 20px per level; add / edit / delete work
inline; deleting a category that has transactions or child categories is
blocked with a reassign prompt showing counts; Transfer and Uncategorized show
a disabled delete with the lock note.
result: [pending]

### 2. Cashflow dashboard donut
expected: Donut shows the ~11 top-level groups (not 74 leaves); clicking a
slice drills into that group's subcategories; a "‹ Back" link appears only
while drilled; slice colours come from the 13-swatch palette with children
inheriting their parent's colour; no Transfer slice appears.
result: [pending]

### 3. Add/Edit Transaction category dropdown
expected: The dropdown lists real categories again (groups plus indented
children), not an empty list; selecting any level saves correctly; opening an
existing transaction pre-selects its current category; there is no
"+ New category" option (creation now lives in Settings > Categories).
result: [pending]

## Summary

total: 3
passed: 0
issues: 0
pending: 3
skipped: 0
blocked: 0

## Gaps
