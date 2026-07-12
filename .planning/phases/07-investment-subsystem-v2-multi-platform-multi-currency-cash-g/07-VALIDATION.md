---
phase: 07
slug: investment-subsystem-v2-multi-platform-multi-currency-cash-g
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-12
---

# Phase 07 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x |
| **Config file** | none — repo uses `pytest` from `backend/requirements.txt`; tests live under `backend/tests/` |
| **Quick run command** | `uv run --with-requirements backend/requirements.txt pytest backend/tests -q` |
| **Full suite command** | `uv run --with-requirements backend/requirements.txt pytest backend/tests` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run quick run command
- **After every plan wave:** Run full suite command
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

> Filled by the planner/executor from RESEARCH.md "Validation Architecture". Money-math (FX conversion, average-cost, P&L) and migration correctness are the priority verification targets.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 07-01-01 | 01 | 1 | INV-01 | — | native cost → IDR conversion at trade-date rate is exact (Decimal, no float drift) | unit | `pytest backend/tests/test_fx_adapter.py -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `backend/tests/test_fx_adapter.py` — FX adapter + immutable `(date, currency_pair)` cache (FX-05)
- [ ] `backend/tests/test_currency_valuation.py` — historical-at-purchase P&L incl. FX gain/loss (FX-03/FX-04)
- [ ] `backend/tests/test_cash_gold_positions.py` — cash direct-override (CG-01) + gold ledger holding (CG-02/03)

*Existing infrastructure (pytest under `backend/tests/`) covers the run harness; the files above are new stubs.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Allocation pie + historical line chart render correctly | INVX-01 | Visual/Recharts rendering | Open `/investments`, confirm pie toggles asset-type↔platform and line chart shows value + P&L views with range selector |

*Chart data contracts are automated; visual rendering is manual (deferred to `/gsd-ui-phase` for interaction spec).*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
