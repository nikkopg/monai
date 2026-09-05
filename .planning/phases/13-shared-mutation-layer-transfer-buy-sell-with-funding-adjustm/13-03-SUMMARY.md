---
phase: 13-shared-mutation-layer-transfer-buy-sell-with-funding-adjustm
plan: 03
subsystem: backend
tags: [writes.py, sqlalchemy, postgres, transfers, guard]

# Dependency graph
requires:
  - phase: 12-typed-accounts-transfer-funding-schema-foundations
    provides: transactions.transfer_pair_id column (nullable Integer, indexed, no FK)
  - phase: 13-shared-mutation-layer-transfer-buy-sell-with-funding-adjustm
    plan: 01
    provides: RED tests pinning apply_add_transfer(db, leg_a_after, leg_b_after) and the allow_paired guard contract
provides:
  - "apply_add_transfer(db, leg_a_after, leg_b_after) -> (leg_a, leg_b): paired liquid->liquid transfer writer (XFER-01)"
  - "allow_paired: bool = False leg-protection guard on apply_edit_transaction and apply_delete_transaction (D-04)"
affects: [phase-14-confirm-endpoint, phase-17-records-tab]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Composition-then-mutate: call apply_add_transaction twice, then set transfer_pair_id on both returned ORM objects directly (no extra flush needed — both rows already flushed by the primitive)"
    - "Guard-at-top-of-function: transfer_pair_id check inserted immediately after the existing db.get null-check, before any field mutation"

key-files:
  created: []
  modified:
    - backend/writes.py

key-decisions:
  - "apply_add_transfer forces is_transfer=True on both legs via {**leg_after, \"is_transfer\": True} rather than trusting the caller's dict — matches PATTERNS.md's 'every composed function's after dict MUST include is_transfer: True explicitly' rule even though the plan-01 test already passes it"
  - "Guard message includes the literal word 'pair' (matches both RED tests' pytest.raises(ValueError, match=\"pair\"))"

requirements-completed: [XFER-01]

coverage:
  - id: D1
    description: "A liquid->liquid transfer writes two paired Transaction rows sharing transfer_pair_id in one caller commit"
    requirement: "XFER-01"
    verification:
      - kind: unit
        ref: "backend/tests/test_write_tools.py::test_apply_add_transfer_pairs_both_legs"
        status: pass
    human_judgment: false
  - id: D2
    description: "Editing or deleting a paired leg raises ValueError unless called with allow_paired=True"
    requirement: "XFER-01"
    verification:
      - kind: unit
        ref: "backend/tests/test_write_tools.py::test_paired_leg_edit_blocked"
        status: pass
      - kind: unit
        ref: "backend/tests/test_write_tools.py::test_paired_leg_delete_blocked"
        status: pass
    human_judgment: false

duration: 20min
completed: 2026-07-30
status: complete
---

# Phase 13 Plan 03: Shared Mutation Layer — Transfer Writer + Leg-Protection Guard Summary

**`apply_add_transfer` composes the existing `apply_add_transaction` primitive twice to write a paired liquid→liquid transfer under one caller commit, and a new `allow_paired` guard on `apply_edit_transaction`/`apply_delete_transaction` stops a single-leg edit or delete from silently orphaning a pair.**

## Performance

- **Duration:** 20 min
- **Completed:** 2026-07-30
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments
- `allow_paired: bool = False` guard added to both `apply_edit_transaction` and `apply_delete_transaction` — raises `ValueError` naming the transaction id and its `transfer_pair_id` when a paired row is touched without the override; default preserves every existing call-site (`main.py` L690/717/1033/1036) unchanged
- `apply_add_transfer(db, leg_a_after, leg_b_after)` added — composes `apply_add_transaction` twice, forces `is_transfer=True` on both legs, sets both legs' `transfer_pair_id` to leg A's own id (shared-group-id, matching migration 011's `min(id)` scheme) once both rows are flushed
- All three of plan 13-01's RED targets for this plan are GREEN: `test_apply_add_transfer_pairs_both_legs`, `test_paired_leg_edit_blocked`, `test_paired_leg_delete_blocked`
- No regression: `backend/tests/test_write_tools.py` full run stays at 34 passed (same pre-existing pass count as plan 13-01 left it, plus the 3 newly-GREEN tests replacing 3 of the prior RED failures) with only the 4 tests explicitly out of scope for 13-04/13-05 still RED (`test_apply_add_investment_transfer`, `test_apply_add_funded_buy_one_commit_boundary`, `test_funded_buy_dual_currency_legs`, `test_apply_add_balance_adjustment_delta`); `backend/tests/test_transaction_crud.py` (6/6) unaffected

## Task Commits

Each task was committed atomically:

1. **Task 1: Add allow_paired leg-protection guard (D-04)** - `bd53ffd` (feat)
2. **Task 2: Add apply_add_transfer (D-03/D-09)** - `395b64e` (feat)

## Files Created/Modified
- `backend/writes.py` — `allow_paired` param + guard on `apply_edit_transaction`/`apply_delete_transaction`; new `apply_add_transfer` function (inserted between `apply_delete_transaction` and `apply_add_account`)

## Decisions Made
- `apply_add_transfer` re-asserts `is_transfer=True` on both leg dicts via `{**leg_after, "is_transfer": True}` instead of relying on the caller to have set it — a defensive one-line correctness guarantee (PATTERNS.md's explicit-True rule) that costs nothing since the plan-01 test already passes it but a future Phase 14 caller might not.
- Guard raise message includes the word "pair" verbatim (both RED tests assert `pytest.raises(ValueError, match="pair")`), and names both the transaction id and its `transfer_pair_id` for operator debuggability.

## Deviations from Plan

None — plan executed exactly as written. No test files were edited to force a pass.

## Verification Results

- `pytest backend/tests/test_write_tools.py::test_paired_leg_edit_blocked backend/tests/test_write_tools.py::test_paired_leg_delete_blocked -x` — 2 passed
- `pytest backend/tests/test_write_tools.py::test_apply_add_transfer_pairs_both_legs -x` — 1 passed
- `pytest backend/tests/test_write_tools.py -q` — 34 passed, 4 failed (all 4 pre-documented RED for plans 13-04/13-05, out of scope here)
- `pytest backend/tests/test_transaction_crud.py -x` — 6 passed
- `grep -vE '^\s*#' backend/writes.py | grep -c 'db\.commit'` → `0` (never-commit contract intact)
- `grep -n "def apply_add_transfer" backend/writes.py` → matches, one definition
- No literal account id introduced — both legs resolve accounts by name via `_get_or_create_account` (inherited through `apply_add_transaction`)
- No leaked test rows — both tests' `finally` blocks call `_cleanup_account`/rollback; live DB confirmed clean

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- SC #1 met: a liquid→liquid transfer writes two paired transaction rows atomically under one caller commit; editing/deleting one leg outside the pair-aware path is blocked.
- Plan 13-04 (`apply_add_investment_transfer`, `apply_add_funded_buy`) and 13-05 (`apply_add_balance_adjustment`) remain the two outstanding RED targets in `test_write_tools.py` — unaffected by this plan, no blockers introduced.
- Phase 14's confirm/endpoint layer can now call `apply_add_transfer` directly for the liquid→liquid transfer flow, and pass `allow_paired=True` explicitly if it ever needs to edit/delete one leg of an existing pair through the pair-aware path.

## Self-Check: PASSED
- FOUND: backend/writes.py (apply_add_transfer defined, guard present on both functions)
- FOUND commit: bd53ffd
- FOUND commit: 395b64e

Re-verified via Bash before finalizing this SUMMARY:
- FOUND: backend/writes.py
- FOUND commit: bd53ffd
- FOUND commit: 395b64e

---
*Phase: 13-shared-mutation-layer-transfer-buy-sell-with-funding-adjustm*
*Completed: 2026-07-30*
