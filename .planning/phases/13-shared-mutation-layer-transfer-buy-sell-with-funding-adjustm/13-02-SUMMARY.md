---
phase: 13-shared-mutation-layer-transfer-buy-sell-with-funding-adjustm
plan: 02
subsystem: database
tags: [alembic, migration, postgres, transfers, backfill]

# Dependency graph
requires:
  - phase: 12-typed-accounts-transfer-funding-schema-foundations
    provides: transactions.transfer_pair_id column (nullable Integer, indexed, no FK)
provides:
  - "alembic migration 011: transfer_pair_id backfilled on 652/668 live is_transfer rows (326 groups), 16 flagged unmatched"
  - "retro_pair_transfers(conn) + compute_pairing() reusable matching/pairing logic, unit-tested against exactly-one/zero/multiple-candidate/idempotency cases"
affects: [phase-13-plan-03-transfer-writes, phase-17-records-tab]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Mutual count-guard pairing: a candidate pair (a,b) is only committed when BOTH a and b individually touch exactly one candidate match — prevents a half-pair when one side's sole candidate is itself ambiguous"
    - "Report-only flagged-row marker: no new DB column — a flagged row is simply is_transfer=true AND transfer_pair_id IS NULL, printed during upgrade() (mirrors 009's assert_parity loud-reporting)"

key-files:
  created:
    - alembic/versions/011_retro_pair_transfers.py
    - backend/tests/test_transfer_retro_pairing.py
  modified: []

key-decisions:
  - "Pairing convention: both legs share transfer_pair_id = min(id) of the pair (shared-group-id), matching writes.py's runtime convention for new transfers"
  - "Ambiguous-row mutual guard: a candidate pair is only paired when BOTH sides have exactly one touching candidate — an ambiguous row's would-be partners are also left unpaired, not arbitrarily latched onto it"
  - "downgrade() is a documented no-op: this revision owns no schema object (transfer_pair_id/its index came from migration 010) and per 009/010's downgrade posture, backfilled data values are left in place on downgrade"

requirements-completed: [XFER-05]

coverage:
  - id: D1
    description: "Historical is_transfer=true rows matching exactly one opposite-amount, same-date, distinct-account counterpart are paired via shared transfer_pair_id"
    requirement: "XFER-05"
    verification:
      - kind: unit
        ref: "backend/tests/test_transfer_retro_pairing.py::test_exactly_one_match_pairs_both_legs"
        status: pass
      - kind: unit
        ref: "backend/tests/test_transfer_retro_pairing.py::test_rerunning_pairing_is_idempotent"
        status: pass
    human_judgment: false
  - id: D2
    description: "Rows with zero or multiple candidate matches are left transfer_pair_id NULL and flagged (printed), never guessed"
    requirement: "XFER-05"
    verification:
      - kind: unit
        ref: "backend/tests/test_transfer_retro_pairing.py::test_zero_match_stays_unpaired"
        status: pass
      - kind: unit
        ref: "backend/tests/test_transfer_retro_pairing.py::test_multiple_candidates_left_unpaired_never_guessed"
        status: pass
    human_judgment: false
  - id: D3
    description: "Migration 011 applied to the live DB, non-destructively and idempotently (upgrade -> downgrade -> upgrade round-trip)"
    requirement: "XFER-05"
    verification:
      - kind: integration
        ref: "alembic upgrade head / alembic downgrade -1 / alembic upgrade head (manual verification this session)"
        status: pass
    human_judgment: false

duration: 25min
completed: 2026-07-30
status: complete
---

# Phase 13 Plan 02: Retro-Pair Historical Transfer Transactions Summary

**Alembic migration 011 backfills `transfer_pair_id` on 652 of 668 live imported-transfer rows (326 groups) via a strict date+opposite-amount+distinct-account match with a mutual count-guard; 16 unmatched rows are left NULL and printed as flagged, never guessed.**

## Performance

- **Duration:** 25 min
- **Completed:** 2026-07-30
- **Tasks:** 2
- **Files modified:** 2 (both new)

## Accomplishments
- `alembic/versions/011_retro_pair_transfers.py` — one-time, idempotent, non-destructive data-only migration (no schema change; `transfer_pair_id` column/index already exist from migration 010)
- `backend/tests/test_transfer_retro_pairing.py` — 4 tests, self-seeded on uniquely named test accounts (id-agnostic), covering exactly-one-match, zero-match, multiple-candidate (ambiguous), and idempotency
- Applied to the live DB: **652/668 `is_transfer` rows paired into 326 groups; 16 rows flagged unmatched** — exact match to RESEARCH.md's point-in-time audit (ids 4977, 5480, 5489, 6284, 6286, 6287, 6292, 6295, 6296, 6297, 6300, 6305, 6319, 6320, 6322, 6325)
- Verified `upgrade -> downgrade -1 -> upgrade head` round-trip: downgrade is a documented no-op (data stays in place, matching 009/010's downgrade posture), re-upgrade reports 0 new pairs (idempotent)

## Task Commits

Each task was committed atomically:

1. **Task 1: RED unit test for the retro-pairing matching logic** - `351061e` (test)
2. **Task 2: Implement migration 011 and apply it to the live DB** - `dd4a8c4` (feat)

**Plan metadata:** (this commit)

## Files Created/Modified
- `alembic/versions/011_retro_pair_transfers.py` - `retro_pair_transfers(conn)` + pure `compute_pairing()` helper; `upgrade()` calls the former; `downgrade()` is a documented no-op
- `backend/tests/test_transfer_retro_pairing.py` - importlib-loads the migration module standalone (mirrors `test_category_migration.py`), drives `retro_pair_transfers` against a real `db_session` with self-seeded rows

## Decisions Made
- **Mutual count-guard** (not in the plan's literal wording, but required for correctness): a candidate pair `(a, b)` is only committed when BOTH `a` and `b` individually touch exactly one candidate match in the current unpaired set. Without this, a row with a single candidate whose *counterpart* is itself ambiguous (e.g. row C matches both A and B on the same date/amount) would get silently latched onto the ambiguous row from one side only, producing a dangling half-pair. The mutual check correctly leaves all three rows (A, B, and the ambiguous C) unpaired — verified by `test_multiple_candidates_left_unpaired_never_guessed`.
- **No new DB column for the "flagged" marker** (per RESEARCH's resolved Open Question 1) — a flagged row is simply `is_transfer=true AND transfer_pair_id IS NULL`, already fully queryable. Flagged ids are printed during `upgrade()`.
- **`downgrade()` is a documented no-op** — this revision makes zero structural schema changes (the column/index/FK were added by migration 010), and 009/010's precedent is to leave backfilled data values in place on downgrade, reverting only schema objects. There is nothing structural here to revert.

## Deviations from Plan

None — plan executed exactly as written. The mutual count-guard above is an implementation detail within Task 2's specified "COUNT(*)-per-row guard" requirement, not a deviation from scope.

## Issues Encountered
None. `alembic upgrade head` applied cleanly on the first attempt against the live DB; the downgrade/re-upgrade round-trip was verified manually and behaved as designed.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- SC #6 (historical transfer retro-pairing) is closed: 652/668 live transfer rows are now paired, 16 correctly flagged unmatched.
- Plan 13-03 (writes.py `apply_add_transfer`) can now rely on the same shared-group-id (`transfer_pair_id = min(id)`) convention this migration used for historical rows — no reconciliation needed between historical and newly-created pairs.
- Two pre-existing, unrelated failures observed while running the full suite (both out of this plan's scope, confirmed via git blame / docstrings before this plan touched anything):
  - `backend/tests/test_settings.py::test_put_settings_requires_key` — pre-existing 503-vs-401 mismatch, already logged in STATE.md blockers.
  - 7 tests in `backend/tests/test_write_tools.py` (`test_apply_add_transfer_pairs_both_legs`, `test_apply_add_investment_transfer`, `test_apply_add_funded_buy_one_commit_boundary`, `test_funded_buy_dual_currency_legs`, `test_apply_add_balance_adjustment_delta`, `test_paired_leg_edit_blocked`, `test_paired_leg_delete_blocked`) and `backend/tests/test_cashflow_summary.py::test_adjustment_excluded_from_cashflow` — all explicitly documented as RED tests awaiting Plan 13-03/04/05's `writes.py` functions (not yet implemented); this plan never touched `writes.py` or these test files.

## Self-Check: PASSED
- FOUND: alembic/versions/011_retro_pair_transfers.py
- FOUND: backend/tests/test_transfer_retro_pairing.py
- FOUND commit 351061e (test)
- FOUND commit dd4a8c4 (feat)

---
*Phase: 13-shared-mutation-layer-transfer-buy-sell-with-funding-adjustm*
*Completed: 2026-07-30*
