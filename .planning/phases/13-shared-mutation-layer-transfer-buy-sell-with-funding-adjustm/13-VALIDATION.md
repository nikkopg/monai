---
phase: 13
slug: shared-mutation-layer-transfer-buy-sell-with-funding-adjustm
status: validated
nyquist_compliant: true
wave_0_complete: true
created: 2026-07-30
validated: 2026-07-30
---

# Phase 13 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Reconstructed from artifacts (VALIDATION.md was an unfilled template) and audited 2026-07-30.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (asyncio_mode = auto) |
| **Config file** | `pyproject.toml` → `[tool.pytest.ini_options]`, `testpaths = ["backend/tests"]` |
| **Quick run command** | `.venv/bin/python -m pytest backend/tests/test_write_tools.py -q` |
| **Full suite command** | `.venv/bin/python -m pytest -q` |
| **Estimated runtime** | ~3 seconds (phase-13 files); requires a live PostgreSQL — tests self-skip via `db_available` when unreachable |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/python -m pytest backend/tests/test_write_tools.py -q`
- **After every plan wave:** Run `.venv/bin/python -m pytest backend/tests/test_write_tools.py backend/tests/test_transfer_retro_pairing.py backend/tests/test_cashflow_summary.py -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** ~3 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 13-03 | 03 | — | XFER-01 | T-13-01 / T-13-07 | Both transfer legs persist under one caller commit; both `is_transfer=True` so they drop out of spending/income/net | unit | `pytest backend/tests/test_write_tools.py -k test_apply_add_transfer_pairs_both_legs` | ✅ | ✅ green |
| 13-03 | 03 | — | XFER-01 / D-04 | T-13-02 | Single-leg edit of a paired row raises ValueError (no orphaned leg) | unit | `pytest backend/tests/test_write_tools.py -k test_paired_leg_edit_blocked` | ✅ | ✅ green |
| 13-03 | 03 | — | XFER-01 / D-04 | T-13-02 | Single-leg delete of a paired row raises ValueError | unit | `pytest backend/tests/test_write_tools.py -k test_paired_leg_delete_blocked` | ✅ | ✅ green |
| 13-04 | 04 | — | XFER-02 | T-13-10 | Liquid→investment funding link via `PortfolioEvent.source_account_id`; accounts resolved by name | unit | `pytest backend/tests/test_write_tools.py -k test_apply_add_investment_transfer` | ✅ | ✅ green |
| 13-04 | 04 | — | XFER-03 (buy) | T-13-01 | Funded buy debits liquid source, records 'buy' event, one commit boundary | unit | `pytest backend/tests/test_write_tools.py -k test_apply_add_funded_buy_one_commit_boundary` | ✅ | ✅ green |
| 13-04 | 04 | — | XFER-03 (sell) | T-13-01 | Funded sell CREDITS liquid destination (positive), records 'sell' event, one commit boundary | unit | `pytest backend/tests/test_write_tools.py -k test_apply_add_funded_sell_one_commit_boundary` | ✅ | ✅ green |
| 13-04 | 04 | — | XFER-04 / D-09 | T-13-05 | Cash-leg and event currencies stored independently; no forced live FX | unit | `pytest backend/tests/test_write_tools.py -k test_funded_buy_dual_currency_legs` | ✅ | ✅ green |
| 13-02 | 02 | — | XFER-05 | T-13-06 | Historical transfer rows retro-paired via shared `transfer_pair_id`; ambiguous rows left unpaired, never guessed | unit | `pytest backend/tests/test_transfer_retro_pairing.py` | ✅ | ✅ green (4 tests) |
| 13-05 | 05 | — | ACCT-02 / D-07 | T-13-05 | Adjustment delta = target − SUM(ALL rows incl. transfers); unfiltered SUM | unit | `pytest backend/tests/test_write_tools.py -k test_apply_add_balance_adjustment_delta` | ✅ | ✅ green |
| 13-05 | 05 | — | ACCT-02 / D-08 | T-13-07 | Adjustment row (`is_transfer=True`) excluded from cashflow totals | unit | `pytest backend/tests/test_cashflow_summary.py -k test_adjustment_excluded_from_cashflow` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Existing infrastructure covers all phase requirements. Plan 13-01 was itself a RED-first scaffold: it wrote the failing tests for all five `apply_*` functions + the leg-protection guard + the adjustment cashflow-exclusion *before* Plans 13-03/04/05 implemented them (classic red→green). No separate framework install was needed — pytest + the `db_available`/`db_session` fixtures already existed.

---

## Manual-Only Verifications

All phase behaviors have automated verification.

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (none remained — RED-first scaffold in 13-01)
- [x] No watch-mode flags
- [x] Feedback latency < 5s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-07-30

---

## Validation Audit 2026-07-30

| Metric | Count |
|--------|-------|
| Gaps found | 1 |
| Resolved | 1 |
| Escalated | 0 |

Gap: `apply_add_funded_sell` (writes.py:236) — implemented for symmetry with funded-buy but never RED-pinned (flagged as a "minor test gap" in 13-VERIFICATION.md). Resolved by adding `test_apply_add_funded_sell_one_commit_boundary` (asserts the positive-credit sign that distinguishes sell from buy, `event_type='sell'`, and `source_account_id` linkage under one commit). Full phase suite: **55 passed** after the addition.
