---
phase: 17-ui-new-surfaces-records-tab-categories-manager
plan: 03
subsystem: api
tags: [fastapi, sqlalchemy, transactions, bulk-endpoints, transfer-pairs, portfolio, audit-log]

# Dependency graph
requires:
  - phase: 17-ui-new-surfaces-records-tab-categories-manager (Plan 01)
    provides: RED backend test baseline (test_write_endpoints.py, test_portfolio.py, test_write_tools.py) pinning the exact endpoint contract this plan implements
  - phase: 16-ui-extend-existing-components
    provides: apply_delete_transaction_or_pair (pair-aware delete primitive, Phase 16 UAT#3) reused directly by bulk-delete
provides:
  - GET /transactions extended with q/account_id/category/type/amount_min/amount_max/include_transfers/date_from/date_to/offset (server-side parameterized filters + paging)
  - TransactionOut.transfer_pair_id (D-02/REC-05)
  - POST /transactions/bulk-delete and POST /transactions/bulk-recategorize (atomic, audit-logged, api-key-gated, pair-aware, 500-id blast-radius cap)
  - GET /platforms/{id}/detail and GET /portfolio-events?platform_id= (platform-scoped PnL + buy/sell history reads)
affects: [17-04 (Records tab consumes GET /transactions + bulk endpoints), 17-05 (Platform detail page consumes the two new reads)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Reuse apply_delete_transaction_or_pair (already pair-aware since Phase 16 UAT#3) for bulk-delete instead of hand-rolling sibling lookup in the endpoint — the single DELETE endpoint was already retrofitted, so this plan's D-04 'retrofit' requirement was already satisfied by prior work"
    - "type=expense/income gates on sign AND transfer_pair_id IS NULL AND (is_transfer==False OR category IN ('Adjustment','Investment')) — the category carve-out distinguishes the two known is_transfer=true-but-unpaired bookkeeping tags from an unclassified/ambiguous is_transfer row, resolving a genuine conflict between two RED tests (see Deviations)"
    - "date_to is treated as an inclusive calendar day (widened internally to an exclusive next-day bound) so a same-day afternoon timestamp isn't dropped"

key-files:
  created: []
  modified:
    - backend/main.py
    - backend/schemas.py
    - backend/tests/test_write_endpoints.py

key-decisions:
  - "type=expense/income filter requires (is_transfer==False OR category IN ('Adjustment','Investment')) in addition to sign + transfer_pair_id IS NULL — a plain is_transfer=true row with no pair id and an unrecognized category is excluded from both buckets, not surfaced under expense/income by sign alone; needed to satisfy both test_transactions_filter (excludes a bare is_transfer=true row) and test_transfer_pair_id_exposed (includes an is_transfer=true, category='Adjustment' row) simultaneously"
  - "GET /transactions date_from/date_to are parsed as datetime and date_to is widened by +1 day internally (caller passes an inclusive calendar date) — matches the RED test's expectation that date_to=2024-06-03 includes a 12:00 timestamp on that day"
  - "Bulk-delete reuses writes.apply_delete_transaction_or_pair directly (added in Phase 16 UAT#3, after 17-RESEARCH.md was written) rather than the RESEARCH doc's older manual-sibling-lookup pattern — simpler, and the single DELETE /transactions/{id} endpoint was already retrofitted pair-aware by that same Phase 16 fix, so no changes were needed there this plan"

requirements-completed: [REC-01, REC-02, REC-03, REC-05, PLAT-01]

coverage:
  - id: D1
    description: "GET /transactions honors q/account_id/category(hierarchy)/type/amount_min/amount_max/include_transfers/date_from/date_to/offset, each a parameterized SQLAlchemy filter, date-desc, 500-row hard cap"
    requirement: "REC-01"
    verification:
      - kind: integration
        ref: "backend/tests/test_write_endpoints.py#test_transactions_filter"
        status: pass
      - kind: integration
        ref: "backend/tests/test_write_endpoints.py#test_transaction_paging"
        status: pass
      - kind: integration
        ref: "backend/tests/test_write_endpoints.py#test_category_filter_hierarchy"
        status: pass
    human_judgment: false
  - id: D2
    description: "transfer_pair_id exposed on TransactionOut; type=expense/income/transfer bucket correctly (Adjustment row under expense, real pair leg under transfer, Adjustment excluded from transfer)"
    requirement: "REC-02"
    verification:
      - kind: integration
        ref: "backend/tests/test_write_endpoints.py#test_transfer_pair_id_exposed"
        status: pass
    human_judgment: false
  - id: D3
    description: "POST /transactions/bulk-delete and POST /transactions/bulk-recategorize — atomic, audit-logged, api-key-gated, 500-id blast-radius cap, transfer-leg cascade/skip"
    requirement: "REC-03"
    verification:
      - kind: integration
        ref: "backend/tests/test_write_endpoints.py#test_bulk_delete"
        status: pass
      - kind: integration
        ref: "backend/tests/test_write_endpoints.py#test_bulk_delete_missing_api_key_401"
        status: pass
      - kind: integration
        ref: "backend/tests/test_write_endpoints.py#test_bulk_recategorize"
        status: pass
      - kind: integration
        ref: "backend/tests/test_write_endpoints.py#test_bulk_recategorize_missing_api_key_401"
        status: pass
      - kind: other
        ref: "manual TestClient probe: bulk-delete/bulk-recategorize with 501 ids -> 422, no mutation"
        status: pass
    human_judgment: false
  - id: D4
    description: "Deleting one leg of a transfer pair (single DELETE and bulk-delete) removes both legs, no orphan"
    requirement: "REC-05"
    verification:
      - kind: integration
        ref: "backend/tests/test_write_tools.py#test_pair_aware_delete"
        status: pass
    human_judgment: false
  - id: D5
    description: "GET /platforms/{id}/detail (404 on bad id, scoped PnL group) and GET /portfolio-events?platform_id= (that platform's events, date-desc); neither registered on backend/tools.py TOOLS"
    requirement: "PLAT-01"
    verification:
      - kind: integration
        ref: "backend/tests/test_portfolio.py#test_platform_detail"
        status: pass
      - kind: integration
        ref: "backend/tests/test_portfolio.py#test_portfolio_events_by_platform"
        status: pass
      - kind: other
        ref: "grep -c 'platform_detail|list_portfolio_events' backend/tools.py -> 0"
        status: pass
    human_judgment: false

duration: 23min
completed: 2026-08-02
status: complete
---

# Phase 17 Plan 03: Backend Plumbing for Records Tab + Platform Detail Summary

**Extended `GET /transactions` with 10 server-side parameterized filters + offset paging and `transfer_pair_id` exposure, added atomic audit-logged `POST /transactions/bulk-delete`/`bulk-recategorize` (reusing the existing pair-aware `apply_delete_transaction_or_pair` primitive), and two new platform-detail reads (`GET /platforms/{id}/detail`, `GET /portfolio-events?platform_id=`) — all composition of existing SQLAlchemy/FastAPI/writes.py/portfolio.py primitives, zero new dependencies, `writes.py`/`tools.py` untouched.**

## Performance

- **Duration:** 23 min
- **Started:** 2026-08-02T16:57:46+07:00
- **Completed:** 2026-08-02T17:19:48+07:00
- **Tasks:** 3
- **Files modified:** 3 (backend/main.py, backend/schemas.py, backend/tests/test_write_endpoints.py)

## Accomplishments

- `GET /transactions` accepts `q`, `account_id`, `category`, `type`, `amount_min`, `amount_max`, `include_transfers`, `date_from`, `date_to`, `limit`, `offset` — each one parameterized `.filter()`, still querying the base `transactions` table (not `cashflow_transactions`), date-desc, 500-row hard cap.
- Category filter resolves a parent name to node + all descendants via `tools.py`'s `_find_category_node`/`_descendant_ids` (hierarchy-aware, matches `spending_in_category`'s semantics), falling back to exact-string match when no node resolves.
- `type=expense`/`income` gate on sign + `transfer_pair_id IS NULL`; `type=transfer` gates on `transfer_pair_id IS NOT NULL` (not `is_transfer`) — a real transfer-pair leg only shows under `type=transfer`, an Adjustment row shows under `type=expense`/`income` by sign.
- `TransactionOut.transfer_pair_id: int | None` added — the field already existed on the model, this just surfaces it.
- `POST /transactions/bulk-delete` and `POST /transactions/bulk-recategorize`: api-key-gated, one `db.commit()` per batch, 500-id blast-radius cap (422 before any mutation), bad ids reported in `skipped[{id, reason}]` never a 500. Bulk-delete reuses `apply_delete_transaction_or_pair` so a selected transfer leg cascades to its un-listed sibling; bulk-recategorize skips transfer legs (system-categorized) into `skipped[]`, never mutating or raising on them.
- `GET /platforms/{id}/detail`: 404 on a missing platform, else the scoped `portfolio_summary()` group (subtotal + holdings with `realized_pnl`/`unrealized_pnl`/`current_value`) — no new DTO, raw dict passthrough.
- `GET /portfolio-events?platform_id=`: that platform's buy/sell/dividend events, date-desc, reusing `PortfolioEventOut`.
- Neither platform-detail read, nor either bulk endpoint, is registered on `backend/tools.py`'s `TOOLS`/`READ_TOOL_NAMES` — agent/MCP surface unchanged (confirmed via `git diff --name-only` excluding `writes.py`/`tools.py` and a zero-match grep).

## Task Commits

Each task was committed atomically:

1. **Task 1: Extend GET /transactions (filters + paging) and expose transfer_pair_id** - `77ead74` (feat)
2. **Task 2: Bulk endpoints + pair-aware delete (bulk and single-delete retrofit)** - `d3efba6` (feat, includes a test-file bug fix — see Deviations)
3. **Task 3: Platform-detail reads — GET /platforms/{id}/detail and GET /portfolio-events** - `7515d66` (feat)

**Plan metadata:** (this commit)

## Files Created/Modified

- `backend/main.py` - extended `list_transactions`, added `bulk_delete_transactions`/`bulk_recategorize_transactions`/`platform_detail`/`list_portfolio_events`, added `_tx_before_dict` helper + `_NON_PAIR_TRANSFER_CATEGORIES`/`_BULK_ACTION_MAX_IDS` module constants
- `backend/schemas.py` - `TransactionOut.transfer_pair_id`, new `BulkDeleteRequest`/`BulkRecategorizeRequest`/`BulkActionResponse`
- `backend/tests/test_write_endpoints.py` - added `api_key` fixture to two 401 tests that were missing it (RED-authoring oversight from 17-01)

## Decisions Made

- **`type=expense`/`income` needs a category carve-out, not just `transfer_pair_id IS NULL`.** 17-RESEARCH.md's Pattern 1 and the plan's own `<action>` text describe `type=expense/income := sign AND transfer_pair_id IS NULL`. Under that rule alone, a plain `is_transfer=True` row with no pair id and no category (the exact fixture `test_transactions_filter` constructs) would incorrectly appear under `type=expense`, but that test asserts exact-set exclusion. Meanwhile `test_transfer_pair_id_exposed` explicitly requires an `is_transfer=True, category='Adjustment'` row to appear under `type=expense`. The only field distinguishing the two fixtures is `category`, and Pitfall 5's own prose names `category='Adjustment'`/`category='Investment'` as the actual production tags for these rows (`writes.py:104`, `writes.py:256`). Implemented `amount<0/>0 AND transfer_pair_id IS NULL AND (is_transfer==False OR category IN ('Adjustment','Investment'))` — satisfies both RED tests and matches the real-world set of non-pair is_transfer rows the app's write primitives actually produce.
- **Bulk-delete reuses `apply_delete_transaction_or_pair` instead of a manual sibling-lookup loop.** 17-RESEARCH.md's Pattern 2 (written before Phase 16's UAT#3 fix) hand-rolls the sibling lookup inline in the endpoint. Since `writes.apply_delete_transaction_or_pair` already exists and does exactly this (added in the interim to fix the Phase 16 UAT transfer-delete bug), reusing it is simpler, DRYer, and the single `DELETE /transactions/{id}` endpoint was *already* retrofitted to use it — so this plan's "retrofit the single-delete endpoint" requirement was already satisfied by prior work; no change was needed there.
- **`date_to` is treated as an inclusive calendar day.** The RED test expects `date_to=2024-06-03` to include a `2024-06-03 12:00:00` row. A naive `Transaction.date <= date_to` (comparing a timestamp column to a bare date string) would exclude it. Implemented as `Transaction.date < (date_to + 1 day)`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Fixed missing `api_key` fixture on two 17-01 RED tests**
- **Found during:** Task 2 (bulk endpoints)
- **Issue:** `test_bulk_delete_missing_api_key_401` and `test_bulk_recategorize_missing_api_key_401` (added in Plan 17-01) call the bulk endpoints with no `MONAI_API_KEY` header and expect 401, but don't request the `api_key` fixture that sets `backend.auth._CONFIGURED_KEY`. With no key configured at all, `require_api_key` returns 503 ("server misconfigured") before it ever reaches the missing-header 401 check — this happens regardless of the endpoint implementation. The sibling, already-passing `test_transfer_missing_api_key_401` uses the `api_key` fixture for exactly this reason.
- **Fix:** Added `api_key` to both test signatures, matching `test_transfer_missing_api_key_401`'s pattern exactly.
- **Files modified:** `backend/tests/test_write_endpoints.py`
- **Verification:** Both tests pass (401, not 503) after the fix; full `test_write_endpoints.py` + `test_write_tools.py` suite (58 tests) green.
- **Committed in:** `d3efba6` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 3 — blocking test bug, not code)
**Impact on plan:** No scope creep — a 2-line fixture-parameter fix to a test file's own internal inconsistency, verified against the sibling test's identical pattern. Endpoint implementation was correct and unaffected.

## Issues Encountered

- Two RED tests in the same file (`test_transactions_filter` and `test_transfer_pair_id_exposed`) implicitly encode conflicting requirements for `type=expense`/`income` semantics when read as pure `transfer_pair_id`-based rules (see Decisions Made above). Resolved by adding the `is_transfer==False OR category IN (...)` carve-out, which satisfies both without weakening the `type=transfer` semantics (still strictly `transfer_pair_id IS NOT NULL`, unaffected).
- `backend/tests/test_settings.py::test_put_settings_requires_key` and `backend/tests/test_typed_accounts.py::test_account_classification` fail on the full `backend/tests/` run — both pre-existing and unrelated to this plan's changes (the first is a documented pre-existing 503-vs-401 issue per `.planning/STATE.md`'s Blockers/Concerns; the second is a live-DB data-state assertion about `accounts.type` classification that this plan's Transactions/Portfolio endpoints never touch). Confirmed by scoping to the plan's own verification command (`test_write_endpoints.py`, `test_portfolio.py`, `test_write_tools.py` — 76/76 pass) and by `git diff --name-only` showing no `accounts`/`settings`-related code touched.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 17-04 (Records tab) can now consume the extended `GET /transactions` (filters, paging, `transfer_pair_id`) and both bulk endpoints directly.
- Plan 17-05 (Platform detail page) can now consume `GET /platforms/{id}/detail` and `GET /portfolio-events?platform_id=` directly.
- No blockers. `backend/writes.py` and `backend/tools.py` are untouched — the agent/MCP tool surface and the shared mutation-primitive layer are unaffected by this plan.

---
*Phase: 17-ui-new-surfaces-records-tab-categories-manager*
*Completed: 2026-08-02*

## Self-Check: PASSED

- FOUND: backend/main.py
- FOUND: backend/schemas.py
- FOUND: backend/tests/test_write_endpoints.py
- FOUND: .planning/phases/17-ui-new-surfaces-records-tab-categories-manager/17-03-SUMMARY.md
- FOUND: commit 77ead74 (Task 1)
- FOUND: commit d3efba6 (Task 2)
- FOUND: commit 7515d66 (Task 3)
