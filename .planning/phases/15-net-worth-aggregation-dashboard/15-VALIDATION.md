---
phase: 15
slug: net-worth-aggregation-dashboard
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-31
---

# Phase 15 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest >=8.0 (backend); Playwright (ui/e2e, existing) |
| **Config file** | `backend/tests/` (pytest discovers `test_*.py`); no repo-root pytest.ini |
| **Quick run command** | `python -m pytest backend/tests/test_net_worth.py -q` |
| **Full suite command** | `python -m pytest backend/tests -q` |
| **Estimated runtime** | ~15–30 seconds (backend suite) |

---

## Sampling Rate

- **After every task commit:** Run the quick command for the touched test file.
- **After every plan wave:** Run the full backend suite.
- **Before `/gsd:verify-work`:** Full suite must be green.
- **Max feedback latency:** 30 seconds.

---

## Per-Task Verification Map

> Planner fills concrete Task IDs. The three invariants below are MANDATORY and
> map directly to the phase's Success Criteria (SC #1/#2/#3).

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 15-01-xx | 01 | 1 | NW-01 | — | net_worth = SUM(type='liquid' balances) + portfolio_summary.total_value; each account/holding counted exactly once | unit | `python -m pytest backend/tests/test_net_worth.py -q` | ❌ W0 | ⬜ pending |
| 15-01-xx | 01 | 1 | NW-01 | — | coverage assertion: liquid_count + investment_count == COUNT(*) accounts; unclassified/out-of-set type → raises ValueError (→422) | unit | `python -m pytest backend/tests/test_net_worth.py -q` | ❌ W0 | ⬜ pending |
| 15-01-xx | 01 | 1 | NW-02 | — | payload exposes combined total + liquid subtotal + investment subtotal + per-side breakdown; subtotals reconcile to combined | unit | `python -m pytest backend/tests/test_net_worth.py -q` | ❌ W0 | ⬜ pending |
| 15-0x-xx | 0x | 2 | NW-02 | — | /cashflow hero shows one net-worth number == liquid + investment (no double-count of investment-type accounts) | manual/e2e | see Manual-Only | n/a | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `backend/tests/test_net_worth.py` — new test file: correct one-count sum (NW-01), coverage-assertion raise on out-of-set type (SC #3), split reconciliation (NW-02).
- [ ] Reuse existing `backend/tests` fixtures/DB session pattern (see `test_write_tools.py`, `test_portfolio.py`) — no new framework install needed.

*Backend pytest + ui Playwright infrastructure already exists; only the new net-worth test file is added.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Dashboard hero renders one net-worth number with liquid/investment split + per-side breakdown | NW-02 | Visual layout on `/cashflow`; Browser-pane rAF gating makes automated visual checks unreliable (see project memory) | Rebuild + open `/cashflow`; confirm hero net worth == liquid subtotal + investment subtotal; confirm no investment-type account is added into the liquid subtotal |

*Coverage assertion (SC #3) and the one-count sum (SC #1) have automated verification; only the visual dashboard render is manual.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (`backend/tests/test_net_worth.py`)
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
