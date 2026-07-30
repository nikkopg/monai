---
phase: 13-shared-mutation-layer-transfer-buy-sell-with-funding-adjustm
verified: 2026-07-30T14:10:00Z
status: passed
score: 6/6 must-haves verified
behavior_unverified: 0
overrides_applied: 0
---

# Phase 13: Shared Mutation Layer — Transfer, Buy/Sell-with-Funding, Adjustment Writes Verification Report

**Phase Goal:** Every new kind of money movement (transfer, funded buy/sell, balance adjustment, category edit) can be written atomically through one trusted layer (`backend/writes.py`). Backend mutation layer + one migration only — REST/agent/MCP wiring is Phase 14 and MUST NOT be present.
**Verified:** 2026-07-30T14:10:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Liquid→liquid transfer writes two paired Transaction rows via `transfer_pair_id` in one DB transaction; editing/deleting one leg is blocked outside pair-aware functions | ✓ VERIFIED | `apply_add_transfer` (writes.py:150-167) composes `apply_add_transaction` twice, sets both legs' `transfer_pair_id = leg_a.id`, never commits. `apply_edit_transaction`/`apply_delete_transaction` (writes.py:110-148) raise `ValueError` mentioning "pair" when `transfer_pair_id is not None` and `allow_paired` is not True. Behavioral test `test_apply_add_transfer_pairs_both_legs` PASSED; `test_paired_leg_edit_blocked` / `test_paired_leg_delete_blocked` PASSED (full run, this session) |
| 2 | Liquid→investment transfer writes a Transaction linked to a portfolio deposit event via `source_account_id` in one transaction; investment money never becomes an accounts row | ✓ VERIFIED | `apply_add_investment_transfer` (writes.py:170-190) composes `apply_add_transaction` + `apply_add_portfolio_event`, sets `ev.source_account_id = tx.account_id` directly, no `Account` row created. Test `test_apply_add_investment_transfer` asserts `accounts_before == accounts_after` — PASSED |
| 3 | Funded buy/sell writes the cash-leg Transaction + holding/portfolio-event update together, one commit — never two round trips; reuses `recompute_holding_from_events` | ✓ VERIFIED (buy proven; sell code-reviewed, untested — see gap note) | `apply_add_funded_buy`/`apply_add_funded_sell` (writes.py:193-266) compose `apply_add_transaction` + `apply_add_portfolio_event` (which internally calls `recompute_holding_from_events`, writes.py:459); zero internal `db.commit()`. `test_apply_add_funded_buy_one_commit_boundary` PASSED. `apply_add_funded_sell` has no dedicated unit test — SUMMARY.md 13-04 discloses this openly ("near-mirror... even though only the buy path has a plan-01 RED test") rather than hiding it |
| 4 | Setting an account balance produces a visible "Adjustment" record reflecting the delta; balance stays derived; delta uses an UNFILTERED SUM(amount), NOT `tools.py:account_balances` | ✓ VERIFIED | `apply_add_balance_adjustment` (writes.py:79-107) computes `delta` via raw `SELECT COALESCE(SUM(amount),0) FROM transactions WHERE account_id=:id` — no `is_transfer` filter, confirmed distinct from `tools.py:account_balances` (L502) which explicitly joins `AND t.is_transfer = false`. Tags row `category="Adjustment"`, `is_transfer=True`. No stored balance column touched. `test_apply_add_balance_adjustment_delta` PASSED |
| 5 | Cross-currency entries accept dual amounts via the two rows; no write path forces a live-only FX rate (uses `fx.get_rate` historical cache) | ✓ VERIFIED | `apply_add_transfer` test seeds leg A=IDR, leg B=USD independently (`test_apply_add_transfer_pairs_both_legs`, PASSED). `apply_add_funded_buy`'s `cash_currency`/`event_currency` stored independently — `test_funded_buy_dual_currency_legs` PASSED. `grep -nE "get_rate|import.*fx" backend/writes.py` → **no match**: writes.py never calls a live FX rate |
| 6 | Historical imported transfer rows retro-paired by migration 011 (match date+amount); unmatched flagged, not guessed; non-destructive + idempotent | ✓ VERIFIED | `alembic/versions/011_retro_pair_transfers.py` `retro_pair_transfers()` matches same-date + opposite-amount + distinct-account pairs with a mutual touch-count guard (zero/multiple candidates → left `NULL`, flagged, never guessed). `downgrade()` is a documented no-op (non-destructive). Idempotent by construction (`WHERE transfer_pair_id IS NULL` guard on both select and update). Tests: `test_exactly_one_match_pairs_both_legs`, `test_zero_match_stays_unpaired`, `test_multiple_candidates_left_unpaired_never_guessed`, `test_rerunning_pairing_is_idempotent` — all 4 PASSED |

**Score:** 6/6 truths verified (0 present-but-behavior-unverified at the truth level; one sub-path — `apply_add_funded_sell` — lacks a dedicated behavioral test, noted as a minor gap below, not blocking since it is a near-identical composition of two independently-tested primitives)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/writes.py` | New `apply_*` functions for transfer/investment-transfer/funded buy/sell/adjustment, never-commit contract intact | ✓ VERIFIED | 823 lines. `grep -vE '^\s*#' backend/writes.py \| grep -c 'db\.commit'` → **0**. No hard-coded account/platform ids in new functions (`grep -nE 'account_id\s*=\s*[0-9]+\|platform_id\s*=\s*[0-9]+' backend/writes.py` → no match) |
| `alembic/versions/011_retro_pair_transfers.py` | Retro-pairing migration, revision chain to 010 | ✓ VERIFIED | `revision="a7c3e9f2b4d1"`, `down_revision="f1a2b3c4d5e6"` — confirmed `f1a2b3c4d5e6` is 010's own `revision` value (chain intact). No hard-coded account ids (purely relational `a.account_id <> b.account_id`) |
| `backend/tests/test_write_tools.py` (Phase 13 additions) | RED→GREEN tests for all 5 new functions + leg guard | ✓ VERIFIED | All Phase-13-tagged tests present and passing (see spot-checks below) |
| `backend/tests/test_transfer_retro_pairing.py` | Standalone migration-logic tests | ✓ VERIFIED | 281 lines, 4 tests, all passing |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `apply_add_transfer` | `apply_add_transaction` | direct call, twice | ✓ WIRED | Both legs flushed, `.id` populated, `transfer_pair_id` set post-hoc |
| `apply_add_investment_transfer` / `apply_add_funded_buy` / `apply_add_funded_sell` | `apply_add_portfolio_event` → `recompute_holding_from_events` | direct call | ✓ WIRED | `recompute_holding_from_events` call confirmed at writes.py:459, inside `apply_add_portfolio_event`, invoked by all three composers |
| `apply_add_balance_adjustment` | raw unfiltered `SUM(amount)` query | direct `db.execute(text(...))` | ✓ WIRED | Confirmed distinct from `tools.py:account_balances`'s filtered join |
| Migration 011 | `compute_pairing()` pure function | direct call inside `retro_pair_transfers()` | ✓ WIRED | Mutual touch-count guard verified by dedicated unit tests |

### Scope Fence Check (Phase 14 boundary — MUST be absent)

| Check | Result |
|-------|--------|
| New REST endpoints in `backend/main.py` referencing transfer/funded/adjustment functions | **NONE FOUND** — grep for transfer/funded/adjustment/apply_add_transfer/apply_add_investment_transfer/apply_add_funded_*/apply_add_balance_adjustment in main.py returns only unrelated pre-existing `is_transfer` field passthroughs and category-system-row text |
| New agent tool registrations in `backend/query.py` FunctionTool list | **NONE FOUND** — no reference to any Phase 13 `apply_*` function |
| New tool registrations in `backend/tools.py` TOOLS registry | **NONE FOUND** — no reference to any Phase 13 `apply_*` function |

Scope fence holds: the functions exist and are tested in isolation; nothing calls them from an endpoint or an agent/MCP tool yet. This is correct per the phase's explicit "backend mutation layer + one migration only" boundary.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|---|---|---|---|---|
| XFER-01 | 13-01, 13-03 | Liquid→liquid paired transfer + leg protection | ✓ SATISFIED | `apply_add_transfer`, guard on edit/delete, tests pass |
| XFER-02 | 13-01, 13-04 | Liquid→investment transfer via `source_account_id` | ✓ SATISFIED | `apply_add_investment_transfer`, test passes |
| XFER-03 | 13-01, 13-04 | Funded buy/sell, one commit boundary | ✓ SATISFIED | `apply_add_funded_buy` proven; `apply_add_funded_sell` code-mirrors it (minor test gap, see below) |
| XFER-04 | 13-01, 13-04 | Dual-currency, no forced live FX | ✓ SATISFIED | Independent currency fields verified; no `get_rate`/fx import in writes.py |
| XFER-05 | 13-02 | Retro-pairing migration | ✓ SATISFIED | Migration 011 + 4 passing tests |
| ACCT-02 | 13-01, 13-05 | Balance adjustment, unfiltered delta, derived balance | ✓ SATISFIED | `apply_add_balance_adjustment`, unfiltered SUM confirmed, test passes |

REQUIREMENTS.md and ROADMAP.md both already mark all six as `[x]` / Complete — matches codebase evidence (not just trusted as-is; independently re-derived above).

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `backend/writes.py` | 370 | `ponytail: reject colliding reassignment; position-merge is a later feature.` | ℹ️ Info | Pre-existing (Phase ≤12, `apply_delete_platform`), not part of this phase's new code; a documented, intentional scope note, not a debt marker (no TBD/FIXME/XXX/TODO/HACK) |

No TBD/FIXME/XXX/TODO/HACK/PLACEHOLDER markers found in any Phase-13-authored file (`backend/writes.py`'s new functions, `alembic/versions/011_retro_pair_transfers.py`, `backend/tests/test_transfer_retro_pairing.py`).

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Never-commit contract | `grep -vE '^\s*#' backend/writes.py \| grep -c 'db\.commit'` | `0` | ✓ PASS |
| No hard-coded account ids | `grep -nE 'account_id\s*=\s*[0-9]+\|platform_id\s*=\s*[0-9]+' backend/writes.py` | no match | ✓ PASS |
| No live FX call in writes.py | `grep -nE "get_rate\|import.*fx" backend/writes.py` | no match | ✓ PASS |
| Migration 011 chains to 010 | `grep "^revision\|^down_revision" alembic/versions/010_typed_accounts.py alembic/versions/011_retro_pair_transfers.py` | 010 revision `f1a2b3c4d5e6` == 011's `down_revision` | ✓ PASS |
| Full backend test suite (run once) | `uv run --with-requirements backend/requirements.txt --with pytest --with httpx python3 -m pytest backend/tests/ -q` | `1 failed, 256 passed` | ✓ PASS (the 1 failure is `test_settings.py::test_put_settings_requires_key`, 503 vs 401 — a documented pre-existing, unrelated failure per the phase brief, NOT a Phase 13 regression) |
| Commit hashes exist in history | `git log --oneline -- backend/writes.py alembic/versions/011_retro_pair_transfers.py` | bd53ffd, 395b64e, f94959b, 00f5077, 7d275b8, dd4a8c4 all present, in order | ✓ PASS |

### Human Verification Required

None. This phase produces no user-facing surface (backend-only mutation layer + migration); all six success criteria are mechanically verifiable via code inspection and the automated test suite, which was run directly in this verification pass (not merely trusted from SUMMARY.md).

### Gaps Summary

No blocking gaps. One minor, disclosed, non-blocking observation:

- **`apply_add_funded_sell` has no dedicated unit test.** The function is a near-identical mirror of `apply_add_funded_buy` (credits instead of debits, `event_type="sell"` instead of `"buy"`), built from the same two already-independently-tested primitives (`apply_add_transaction`, `apply_add_portfolio_event`). The 13-04 SUMMARY.md discloses this itself rather than hiding it. Given SC #3 says "funded buy/sell" as one criterion and the buy half is fully proven with the sell half sharing 100% of its composition logic and zero new logic of its own, this does not block phase-goal achievement — recommend a follow-up test be added in Phase 14 when the confirm-endpoint wiring exercises both directions, or as a quick addition now if the team wants belt-and-suspenders before Phase 14 begins.

---

_Verified: 2026-07-30T14:10:00Z_
_Verifier: Claude (gsd-verifier)_
