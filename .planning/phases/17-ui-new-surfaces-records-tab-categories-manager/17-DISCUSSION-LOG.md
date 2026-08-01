# Phase 17: UI — New Surfaces - Discussion Log

> **Audit trail only.** Not consumed by downstream agents (they read CONTEXT.md).

**Date:** 2026-08-01
**Phase:** 17-ui-new-surfaces-records-tab-categories-manager
**Mode:** `--auto` (autonomous single pass — recommended option auto-selected per area)
**Areas discussed:** Scope correction (categories), Filter seam, Pair-id exposure, Bulk seam, Pair-aware delete, Platform detail reads, Records tab, Transfer-pair display, Platform detail view

---

## Scope correction — "Categories Manager"

| Option | Description | Selected |
|--------|-------------|----------|
| Build a new category manager | As the stale roadmap title implies | |
| Reuse the Phase-11 CategoryManager | Already a full tree manager; no CAT req in Phase 17 | ✓ |

**Choice:** Reuse — the category tree manager shipped in Phase 11; Phase 17's requirements are Records + Platform detail only.

---

## Filter seam (REC-01/02)

| Option | Description | Selected |
|--------|-------------|----------|
| Server-side filter params, client-side day-grouping | Extend GET /transactions; group in the page | ✓ |
| Client-side filter of a bulk fetch | Fetch all, filter in JS | |

**Choice:** Server-side params (data-scoping), client-side grouping (presentation).

---

## Bulk seam (REC-03)

| Option | Description | Selected |
|--------|-------------|----------|
| Bulk endpoints (atomic + audited) | POST /transactions/bulk-delete + bulk-recategorize | ✓ |
| Client loops single DELETE/PUT | N round-trips, no atomicity | |

**Choice:** Bulk endpoints — one transaction, audit-logged, matches money-app write-safety.

---

## Transfer pairs (REC-05)

| Option | Description | Selected |
|--------|-------------|----------|
| Expose transfer_pair_id + collapse to one row + pair-aware delete | Single ledger line; delete both legs atomically; single-leg edit blocked | ✓ |
| Show both legs separately | Looks like double-counting | |

**Choice:** Collapse pairs; reuse Phase-13 pair-aware delete + Phase-16 transfer-leg lock.

---

## Platform detail reads (PLAT-01)

| Option | Description | Selected |
|--------|-------------|----------|
| Reuse portfolio_summary group for PnL + new GET events-by-platform | Minimal new backend; PnL already computed | ✓ |
| Build a bespoke per-platform PnL recompute | Duplicates portfolio.py logic | |

**Choice:** Reuse portfolio_summary; add only a GET for the event ledger.

---

## Frontend surfaces (D-06/07/08)

New "Records" nav item + `records/page.tsx` (grouped ledger, filter bar, multi-select bulk bar);
transfer pairs as one collapsed row; new `investments/[platformId]/page.tsx` with PnL + Buy/Sell tabs
(segmented control reused). All within the inline-style `styles.ts` convention; reuse TransactionModal,
ConfirmDialog, CategoryManager picker, HoldingModal.

---

## Claude's Discretion

- Platform-detail route shape, filter-bar layout, recategorize picker (tree vs flat), pagination style, backend DTO reuse vs bespoke.

## Deferred Ideas

- New category-manager UI (shipped Phase 11); recurring-charge detection / period comparison / streaming (v2 backlog); funding legs in records ledger; MCP exposure of new platform reads.

## Note to planner

Large phase (5 reqs, backend + two frontend surfaces) — consider a wave or phase split (Records vs Platform detail are largely independent).
