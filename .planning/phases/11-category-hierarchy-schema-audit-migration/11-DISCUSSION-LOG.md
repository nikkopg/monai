# Phase 11: Category Hierarchy — Schema, Audit, Migration - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-18
**Phase:** 11-Category Hierarchy — Schema, Audit, Migration
**Areas discussed:** Hierarchy shape & assignment, Mapping review workflow, Chart & filter rollup behavior, Colors/icons & picker style

---

## Hierarchy shape & assignment

| Option | Description | Selected |
|--------|-------------|----------|
| Any level assignable | BudgetBakers-style; strings that are natural parents map directly, no artificial "General" leaves | ✓ |
| Leaf-only assignment | Cleaner rollup math, but every parent needs a catch-all child leaf | |
| Let Claude decide | | |

**User's choice:** Any level assignable

| Option | Description | Selected |
|--------|-------------|----------|
| BudgetBakers groups | Nest 74 strings under Wallet's standard top groups | ✓ |
| My own top-level scheme | User-defined top groups during mapping review | |
| Flat first, nest later | Migrate all 74 as top-level, build tree via UI later | |

**User's choice:** BudgetBakers groups

| Option | Description | Selected |
|--------|-------------|----------|
| Typed: expense vs income | Pickers filter by record type; matches BudgetBakers | ✓ |
| One shared tree, no typing | Any category on any record | |
| Let Claude decide | | |

**User's choice:** Typed: expense vs income

| Option | Description | Selected |
|--------|-------------|----------|
| "Uncategorized" node + Transfer category | NULLs map to a real category; system Transfer category created for Phase 13 | ✓ |
| Keep NULL allowed | category_id stays nullable; downstream NULL handling forever | |
| Let Claude decide | | |

**User's choice:** "Uncategorized" node + Transfer category

---

## Mapping review workflow

| Option | Description | Selected |
|--------|-------------|----------|
| Checked-in mapping file | Claude drafts YAML/CSV; user edits; migration reads it | |
| Draft file + chat walkthrough of ambiguous ones | Same file, plus chat review of uncertain strings | ✓ |
| Full chat walkthrough | All 74 reviewed in conversation | |

**User's choice:** Draft file + chat walkthrough of ambiguous ones

| Option | Description | Selected |
|--------|-------------|----------|
| Execution checkpoint | Executor drafts mid-phase, pauses for review, then migrates | ✓ |
| Before planning | Mapping approved before the plan is written | |
| Let Claude decide | | |

**User's choice:** Execution checkpoint

| Option | Description | Selected |
|--------|-------------|----------|
| Abort loudly | Unmatched strings listed; nothing partially migrated; re-runnable | ✓ |
| Map to Uncategorized + flag | Completes in one run but degrades silently on typos | |
| Let Claude decide | | |

**User's choice:** Abort loudly

| Option | Description | Selected |
|--------|-------------|----------|
| Dual-write until drop | New records write category_id + legacy string; trivial rollback | ✓ |
| Freeze the string column | Only category_id written post-migration | |
| Let Claude decide | | |

**User's choice:** Dual-write until drop

---

## Chart & filter rollup behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Top-level rollup + drill-down | Donut shows ~11 groups; click drills into subcategories | ✓ |
| Top-level rollup only | No drill-down this phase | |
| Keep leaf-level charts | Hierarchy only for pickers/management | |

**User's choice:** Top-level rollup + drill-down

| Option | Description | Selected |
|--------|-------------|----------|
| Parent includes descendants | spending tools roll up children; list_categories returns tree | ✓ |
| Exact-name match only | Smaller change, surprising chat answers | |
| Let Claude decide | | |

**User's choice:** Parent includes descendants

| Option | Description | Selected |
|--------|-------------|----------|
| Rework onto hierarchy | Rename edits row (FK follows); merge reassigns + deletes source | ✓ |
| Rename only; retire merge | Delete-with-reassign covers merge | |
| Let Claude decide | | |

**User's choice:** Rework onto hierarchy

| Option | Description | Selected |
|--------|-------------|----------|
| Exclude from totals | Transfers never count as spending/income; visible in lists | ✓ |
| Count them for now | Exclusion lands with Phase 13 | |
| Let Claude decide | | |

**User's choice:** Exclude from totals

**Notes:** User asked "are going to do migration? from where to where?" — clarified that this is an in-database Alembic data migration (free-string `transactions.category` → `categories` table + `transactions.category_id` FK), with `raw_category` untouched, abort-on-unknown, parity-asserted, and the column drop deferred. User confirmed and continued.

---

## Colors, icons & picker style

| Option | Description | Selected |
|--------|-------------|----------|
| Emoji | Text-stored emoji; zero dependencies; defaults pre-assigned in mapping | ✓ |
| Icon library (lucide-react) | Crisp line icons but a new dependency | |
| No icons this phase | Color dot only | |

**User's choice:** Emoji

| Option | Description | Selected |
|--------|-------------|----------|
| Curated palette + inherit | Swatches from paper tokens; subcategories inherit parent color, overridable | ✓ |
| Curated palette, no inheritance | Independent swatch per category | |
| Free color picker | Any hex value | |

**User's choice:** Curated palette + inherit

| Option | Description | Selected |
|--------|-------------|----------|
| Searchable grouped list | Dropdown with group headers, indented children, type-to-filter | ✓ |
| BudgetBakers two-pane | Groups left, subcategories right | |
| Chip grid | Colored icon chips grouped by parent | |

**User's choice:** Searchable grouped list

| Option | Description | Selected |
|--------|-------------|----------|
| Expandable tree | Groups collapsed by default; inline CRUD per node; block-or-reassign delete guard | ✓ |
| Grouped flat list | All visible under headers | |
| Let Claude decide | | |

**User's choice:** Expandable tree

## Claude's Discretion

- Schema details: FK naming, indexes, 3-level depth enforcement, expense/income typing storage
- Migration internals: Alembic revision structure, parity-report format, idempotency mechanism
- Which strings count as "ambiguous" for the chat walkthrough
- Emoji/color defaults in the mapping draft

## Deferred Ideas

None — discussion stayed within phase scope.
