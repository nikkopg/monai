---
phase: 07-investment-subsystem-v2-multi-platform-multi-currency-cash-g
plan: 05
subsystem: api
tags: [chat-agent, tools, proposals, fastapi, sqlalchemy, ch-01-regression]

# Dependency graph
requires:
  - phase: 07 (plans 01-04, especially the multi-platform migration 006/rb2)
    provides: platforms table, holdings.platform_id NOT NULL constraint
provides:
  - find_platforms + find_accounts read tools (name→id resolution for the agent)
  - propose_add_holding accepting platform_id
  - _execute_proposal_payload delegating add_holding/edit_holding to writes.py
affects: [chat-agentic-loop, mcp-server, phase-2-verification-account-delete]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "find_platforms/find_accounts mirror find_transactions exactly (ILIKE filter, max(1,min(int(limit),50)) clamp, ids-first)"
    - "Delegate-to-writes.py, don't duplicate: confirm-time write paths (_execute_proposal_payload) call the same apply_* helpers as the direct REST endpoints"

key-files:
  created: []
  modified:
    - backend/tools.py
    - backend/main.py
    - backend/tests/test_tools.py
    - backend/tests/test_proposals.py

key-decisions:
  - "find_accounts built via SQLAlchemy ORM query (Account.name.ilike) rather than raw SQL text(), since it reuses the existing _account_to_dict(acc) which expects an ORM object, not a row tuple"
  - "find_platforms uses raw SQL + a new _platform_to_dict(row) taking a row tuple, matching find_transactions's raw-SQL convention since no ORM-object helper existed for platforms yet"
  - "Deleted ~35 lines of inline Holding(...)/AuditLog(...) construction from _execute_proposal_payload; replaced with apply_add_holding(db, after) / apply_edit_holding(db, row.get('id'), after, before) — the two-site CH-01 fix (site 1: propose_add_holding param, site 2: confirm-time delegation, the actual root cause)"

patterns-established:
  - "Read-tool ids-first shape (find_platforms/find_accounts) extends the find_transactions convention to two more entities, closing the STATE.md Pending Todos account-id gap"

requirements-completed: [CHAT-03, INV-07]

# Metrics
duration: 25min
completed: 2026-07-12
---

# Phase 07 Plan 05: CH-01 Chat Write-Path Regression Fix + Read Tools Summary

**Closed the CH-01 chat write-path regression (add_holding via chat 500'd on the new platform_id NOT NULL constraint) with its full two-site fix, and added find_platforms/find_accounts read tools so the agent can resolve platform/account names to ids before proposing writes.**

## Performance

- **Duration:** 25 min
- **Started:** 2026-07-12T11:19:01Z
- **Completed:** 2026-07-12T11:27:50Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- `find_platforms` + `find_accounts` read tools added and registered in `TOOLS`, mirroring `find_transactions`'s shape (ILIKE filter, clamped limit, ids-first rows)
- `propose_add_holding` now accepts and forwards `platform_id` into the proposal's `after` dict (CH-01 fix site 1 of 2)
- `_execute_proposal_payload`'s `add_holding`/`edit_holding` branches now delegate to `apply_add_holding`/`apply_edit_holding` from `writes.py` instead of duplicating inline `Holding(...)` construction — deleted ~35 lines, automatically inherits `platform_id`/`coingecko_id` handling (CH-01 fix site 2 of 2, the actual root cause)
- Regression closed: a chat-initiated add_holding proposal carrying `platform_id`, confirmed via `_execute_proposal_payload`, now writes a `Holding` with `platform_id` set — no more NOT NULL `IntegrityError`
- `require_api_key` + propose→confirm token flow + `audit_log` write-through all verified preserved by the delegation via integration tests

## Task Commits

Each task was committed atomically:

1. **Task 1: find_platforms + find_accounts read tools; propose_add_holding accepts platform_id** - `925f1b4` (feat)
2. **Task 2: _execute_proposal_payload delegates to writes.py (CH-01 fix site 2)** - `21357e4` (fix)

**Plan metadata:** (this commit)

## Files Created/Modified
- `backend/tools.py` - added `find_platforms`, `find_accounts`, `_platform_to_dict`; registered both in `TOOLS`; `propose_add_holding` gained `platform_id: int | None` param, included in `after`
- `backend/main.py` - `_execute_proposal_payload`'s `add_holding`/`edit_holding` branches replaced with `apply_add_holding(db, after)` / `apply_edit_holding(db, row.get("id"), after, before)` calls
- `backend/tests/test_tools.py` - `find_platforms`/`find_accounts` read-tool tests (id presence, ILIKE filter, limit clamping) + `TOOLS` registry membership test + `propose_add_holding` platform_id-forwarding test
- `backend/tests/test_proposals.py` - `test_confirm_add_holding_persists_platform_id` (the CH-01 regression-closure test: fails against the pre-fix inline branch, passes after delegation) + `test_confirm_edit_holding_via_delegation`, both asserting audit_log rows are written

## Decisions Made
- `find_accounts` uses the ORM (`db.query(Account).filter(Account.name.ilike(...))`) to reuse the existing `_account_to_dict(acc)` helper (expects an ORM object); `find_platforms` uses raw SQL + a new `_platform_to_dict(row)` (expects a row tuple), matching `find_transactions`'s existing raw-SQL convention since platforms had no prior read-tool helper to reuse.
- Test assertion for the edited holding's quantity uses `Decimal("5")` comparison rather than `str(...) == "5"`, since `Numeric(18, 8)` returns `"5.00000000"` from Postgres — not a functional bug, just a stringification mismatch caught by the acceptance test itself.

## Deviations from Plan

### Auto-fixed Issues

None requiring Rule 1-4 escalation. One test-authoring correction (Decimal string-format assertion, caught and fixed in the same task before commit, not a deviation from the plan's intent).

**Total deviations:** 0
**Impact on plan:** None — plan executed as written, both CH-01 fix sites landed exactly per the PATTERNS.md-supplied code shape.

## Issues Encountered
- Full-suite run surfaced one **out-of-scope** pre-existing failure: `backend/tests/test_settings.py::test_put_settings_requires_key` fails with `503 != 401` when `MONAI_API_KEY` is unset in the shell running pytest (the existing fail-closed guard from Quick 260703-ja8 returns 503 before reaching the 401 auth-check path). `test_settings.py` is not in this plan's `files_modified` and the failure is unrelated to the CH-01 delegation change — logged to `deferred-items.md`, not fixed (scope boundary).
- One test-seed collision during iteration: a platform row from a failed first test-run attempt (before the Decimal-format fix) collided with a hardcoded unique platform name on rerun. Fixed by appending a `secrets.token_hex(4)` suffix to test-seeded platform names in `_make_platform()`, and manually cleaned the one leftover row from the live dev DB. No production code affected.

## TDD Gate Compliance

Both tasks in this plan carried `tdd="true"`, but were executed as single `feat`/`fix` commits containing both the implementation and its tests together, rather than separate `test(...)` (RED) → `feat(...)` (GREEN) commits. This matches `tdd_mode: false` in `.planning/config.json` (plan-level TDD gate is off this milestone) — tests were written and verified failing-then-passing during development, but git history shows one commit per task rather than a RED/GREEN pair. No gate violation; documenting per the standard TDD Gate Compliance convention since the plan frontmatter marks tasks `tdd="true"`.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- CH-01 regression fully closed; chat-initiated `add_holding` now works end-to-end with the multi-platform schema
- `find_accounts` closes the STATE.md "Pending Todos" account-id gap — chat "delete my BCA account" is now unblocked (agent can resolve name→id)
- No blockers for the remaining Phase 07 plans (07-02, 07-03 — FX/cash model, independent of this plan's scope)
- Deferred: `test_settings.py::test_put_settings_requires_key` environment-dependent failure (see `deferred-items.md`) — recommend re-running with `MONAI_API_KEY` exported before declaring the full backend suite green

---
*Phase: 07-investment-subsystem-v2-multi-platform-multi-currency-cash-g*
*Completed: 2026-07-12*
