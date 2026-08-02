---
phase: 17-ui-new-surfaces-records-tab-categories-manager
verified: 2026-08-02T11:14:51Z
status: passed
score: 5/5 must-haves verified
behavior_unverified: 0
overrides_applied: 0
---

# Phase 17: UI — New Surfaces (Records Tab, Platform Detail) Verification Report

**Phase Goal:** The user can browse, filter, and bulk-manage their full transaction history, and drill into a platform's performance, on new purpose-built screens.
**Verified:** 2026-08-02T11:14:51Z
**Status:** passed
**Re-verification:** No — initial verification

**Naming note:** the phase directory slug says "categories-manager," but no CAT-* requirement is mapped to Phase 17 in REQUIREMENTS.md (CAT-01..04 belong to Phase 11, already complete) and none of the 5 plans deliver a categories manager. This is a stale directory name only — verified against the 5 actual success criteria and requirement IDs (REC-01/02/03/05, PLAT-01), per the orchestrator's explicit note.

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | User can browse all records in a date-grouped ledger showing a daily net per group | VERIFIED | `ui/app/records/page.tsx` groups rows by local calendar date (`localDateKey`/`dayLabel`), renders a "{Label} / Net {signed}" header per group, and the net sum explicitly filters `transfer_pair_id == null` (L786-788) so transfer legs contribute zero. e2e `records.spec.ts:141` ("day-group headers use the locked labels and the daily net excludes collapsed transfer-pair rows") passes against a live dev server. |
| 2 | User can filter records by search, account, category, record type, amount range, and transfer visibility | VERIFIED | Filter bar renders all 7 controls (search input, account select, category select, type select, min/max amount, Show-transfers checkbox) at `records/page.tsx` L630-700, feeding a 300ms-debounced `GET /api/transactions` with `q/account_id/category/type/amount_min/amount_max/include_transfers`, offset reset to 0 on any change. Backend `GET /transactions` (`backend/main.py:698-776`) implements every param as a parameterized SQLAlchemy filter, category filter resolves parent→descendants via `_find_category_node`/`_descendant_ids` (hierarchy, not exact-string). e2e `records.spec.ts:163` passes. |
| 3 | User can select multiple records and bulk delete or bulk recategorize | VERIFIED | Checkbox-per-row + bulk bar (`records/page.tsx` L703-755) call `POST /api/transactions/bulk-delete` (via ConfirmDialog) and `POST /api/transactions/bulk-recategorize`. Backend endpoints (`main.py:978`, `main.py:1016`) are api-key-gated, atomic (single `db.commit()` for the batch), audit-logged per entity, return `{deleted\|recategorized, skipped:[{id,reason}]}`, capped at 500 ids. e2e `records.spec.ts:219` and `:260` both pass, asserting the exact ids POSTed. |
| 4 | Transfer pairs display as one logical unit; editing or deleting affects both legs atomically (single-leg edits blocked in the UI) | VERIFIED | `collapseTransferPairs()` (records/page.tsx L55-71) collapses same-`transfer_pair_id` rows into one "Transfer: From → To" row; a lone surviving leg degrades to a normal row tagged "(transfer)" without throwing. Delete (single + bulk) routes through `writes.apply_delete_transaction_or_pair` (`backend/writes.py:166-186`), which looks up the sibling by `transfer_pair_id` and deletes both legs in one transaction — verified directly in source, and exercised by 3 backend RED-turned-GREEN tests. Edit opens `TransactionModal` with `locked = isEdit && editingTx.is_transfer` (`TransactionModal.tsx:111`), which disables the segment control and pins category — no single-leg edit path exists. e2e `records.spec.ts:202` (collapse) passes. |
| 5 | User can open a platform detail view with a PnL tab and a buy/sell history tab | VERIFIED | `ui/app/investments/[platformId]/page.tsx` is a dynamic route reached via `Link href={/investments/${platform_id}}` on the Investments page (only when `platform_id !== null`; "Unassigned" stays plain text — `investments/page.tsx` L536-565). Renders back-link, eyebrow, name+kind, 3 stat cards (Subtotal/Realized/Unrealized) from `GET /api/platforms/{id}/detail`, and a PnL/Buy & Sell segmented control (PnL default) backed by `GET /api/portfolio-events?platform_id=`. Back-link stays present on the 404 path so the user is never stranded. All 4 e2e tests in `platform-detail.spec.ts` pass (shell, PnL tab, Buy & Sell tab, 404 state). |

**Score:** 5/5 truths verified (0 present, behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/main.py` (list_transactions, bulk_delete_transactions, bulk_recategorize_transactions, platform_detail, list_portfolio_events) | Extended/new endpoints per must_haves | VERIFIED | All 5 endpoints present, read in full, match must_haves exactly (filters, hierarchy, transfer_pair_id semantics, atomic bulk ops, 404 on bad platform id). |
| `backend/schemas.py` | `TransactionOut.transfer_pair_id` | VERIFIED | `transfer_pair_id: int \| None = None` present (L48). |
| `backend/writes.py` | NOT modified this phase (pair cascade lives at endpoint layer, reused from Phase 16) | VERIFIED | `git log` confirms writes.py's last touch (`3ffe59a`) predates Phase 17's first commit (`a16362d`); no writes.py changes in any Phase 17 commit. |
| `backend/tools.py` | New reads NOT added to TOOLS/READ_TOOL_NAMES (D-05, agent/MCP surface unchanged) | VERIFIED | `grep` for `platform_detail`, `list_portfolio_events`, `bulk_delete`, `bulk_recategorize`, `list_transactions` against `backend/tools.py` returns zero hits. |
| `ui/app/records/page.tsx` | Records ledger page | VERIFIED | Exists (868 lines), substantive, fully wired — read in full. |
| `ui/app/investments/[platformId]/page.tsx` | Platform detail page | VERIFIED | Exists (538 lines), substantive, fully wired — read in full. |
| `ui/app/components/Nav.tsx` | Records nav entry | VERIFIED | `{ href: "/records", label: "Records", icon: "records" }` inserted immediately after Cashflow (L19), with a dedicated ledger-glyph `<svg>` icon. |
| `ui/app/investments/page.tsx` | Platform group-header becomes a link when `platform_id != null` | VERIFIED | `Link href={/investments/${g.platform_id}}` gated by `!isUnassigned`; Unassigned renders a plain `<span>`. |
| `ui/e2e/records.spec.ts` / `ui/e2e/platform-detail.spec.ts` | RED→GREEN e2e coverage | VERIFIED | Both files exist, and both were independently re-run (see Behavioral Spot-Checks). |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| `records/page.tsx` | `GET /api/transactions` | `fetch` + debounced filter state | WIRED | `buildParams()`/`load()`, offset resets to 0 on filter change. |
| `records/page.tsx` | `POST /api/transactions/bulk-delete`, `bulk-recategorize` | `doBulkDelete`/`doBulkRecategorize` | WIRED | Confirmed request bodies match backend's `BulkDeleteRequest`/`BulkRecategorizeRequest` shape; e2e asserts POSTed ids. |
| `records/page.tsx` | `TransactionModal` (transfer-leg-locked) | `editingTx`/`modalOpen` props | WIRED | Reused verbatim; `locked` derives from `editingTx.is_transfer`. |
| `investments/[platformId]/page.tsx` | `GET /api/platforms/{id}/detail` + `GET /api/portfolio-events?platform_id=` | `Promise.all` on mount | WIRED | Parallel fetch, 404 branch handled distinctly from generic error. |
| `investments/page.tsx` | `investments/[platformId]/page.tsx` | `<Link>` | WIRED | Confirmed gated on non-null `platform_id`. |
| `backend/main.py` bulk endpoints | `backend/writes.py apply_delete_transaction_or_pair` / `apply_edit_transaction` | direct function call | WIRED | Read in full; pair-aware, atomic, audit-logged. |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Backend test suite for this phase (76 tests: test_write_endpoints.py, test_portfolio.py, test_write_tools.py) | `pytest backend/tests/test_write_endpoints.py backend/tests/test_portfolio.py backend/tests/test_write_tools.py -q` against live Postgres (monai-db) | `76 passed, 1 warning in 8.23s` | PASS (independently re-run, not just trusted from SUMMARY) |
| Frontend e2e — Records ledger (7 tests) + Platform detail (4 tests) | `npx playwright test e2e/records.spec.ts e2e/platform-detail.spec.ts` against a **freshly started** `npm run dev` on :3001 | `11 passed (20.1s)` | PASS (see Notes — first attempt gave a false 10/11 FAIL because Playwright's `reuseExistingServer: true` silently attached to the running `monai-frontend` Docker container instead of starting a dev server) |
| `tsc --noEmit` on merged `ui/` tree | `npx tsc --noEmit` | No output (clean) | PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| REC-01 | 17-03, 17-04 | Browse all records in a date-grouped ledger with daily net | SATISFIED | Truth #1 |
| REC-02 | 17-03, 17-04 | Filter by search/account/category/type/amount/transfers | SATISFIED | Truth #2 |
| REC-03 | 17-03, 17-04 | Bulk delete / bulk recategorize | SATISFIED | Truth #3 |
| REC-05 | 17-03, 17-04 | Transfer pairs as one unit, atomic edit/delete | SATISFIED | Truth #4 |
| PLAT-01 | 17-03, 17-05 | Platform detail view — PnL + buy/sell tabs | SATISFIED | Truth #5 |

**Orphaned requirements check:** `.planning/REQUIREMENTS.md` maps exactly these 5 IDs to Phase 17 (lines 100-109). REC-04 (Phase 16) and CAT-01..04 (Phase 11) are mapped to other, already-complete phases — no orphaned requirements for Phase 17.

### Anti-Patterns Found

None. Scanned `backend/main.py`, `backend/schemas.py`, `ui/app/records/page.tsx`, `ui/app/investments/[platformId]/page.tsx`, `ui/app/components/Nav.tsx`, `ui/app/investments/page.tsx` for `TBD|FIXME|XXX|TODO|HACK|PLACEHOLDER`/stub patterns. The only `placeholder` hits are legitimate HTML `placeholder=` input attributes, not debt markers.

### Human Verification Required

None. All 5 truths resolved to VERIFIED via direct code inspection plus independently re-executed automated tests (backend pytest, frontend Playwright, tsc).

## Notes

**Deploy-staleness caught during verification (not a code gap):** The live `monai-frontend` Docker container (`network_mode: host`, port 3001, `npm run start` against whatever was last built into the image) was running throughout this verification and does **not** yet serve `/records` or `/investments/[platformId]` (confirmed 404 via `curl http://127.0.0.1:3001/records`) — it predates this phase's commits. My first e2e run silently hit this stale container because Playwright's `webServer.reuseExistingServer: true` attaches to anything already listening on :3001 instead of starting a fresh dev server, producing a false 10/11 FAIL. Stopping the container forced Playwright to start its own `npm run dev`, and all 11 tests passed. The container was restarted afterward to restore its prior running state. **This matches the project's own recorded gotcha** ("Deploy requires rebuild" — committed code ≠ deployed). Recommend `docker compose up -d --build frontend` before any human/browser UAT of Phase 17's surfaces at the deployed URL; this does not affect the codebase-level goal-achievement verdict above.

---

_Verified: 2026-08-02T11:14:51Z_
_Verifier: Claude (gsd-verifier)_
