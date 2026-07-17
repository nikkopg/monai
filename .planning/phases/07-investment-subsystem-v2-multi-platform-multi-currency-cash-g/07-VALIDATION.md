---
phase: 07
slug: investment-subsystem-v2-multi-platform-multi-currency-cash-g
status: validated
nyquist_compliant: true
wave_0_complete: true
created: 2026-07-12
validated: 2026-07-17
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
| — | 01 | 1 | FX-01 | — | Frankfurter adapter returns Decimal rate by date; None on HTTP/JSON error (never fabricates) | unit (mocked HTTP) | `pytest backend/tests/test_fx.py -k frankfurter -q` | ✅ test_fx.py | ✅ green (3) |
| — | 01 | 1 | FX-02 | — | Arbitrary currency; USDT≈USD; invalid currency → no HTTP call | unit | `pytest backend/tests/test_fx.py -k "usdt or invalid_currency or identity" -q` | ✅ test_fx.py | ✅ green |
| — | 02 | — | FX-03 | — | Native cost → IDR at trade-date rate (Decimal, no drift); unrealized P&L includes FX; D-02 invariant across partial sell | unit | `pytest backend/tests/test_portfolio.py -k recompute_fx -q` | ✅ test_portfolio.py | ✅ green (3) |
| — | 02 | — | FX-04 | — | No per-event rate stored; re-fetched by date; None propagates, never fabricated to 1.0 | unit | `pytest backend/tests/test_portfolio.py -k "realized_pnl_fx or none_propagates" -q` | ✅ test_portfolio.py | ✅ green |
| — | 01 | 1 | FX-05 | — | `(date, currency_pair)` cache immutable: hit → no adapter call, miss → exactly one row, repeat → no refetch | unit | `pytest backend/tests/test_fx.py -k cache -q` | ✅ test_fx.py | ✅ green (3) |
| — | 03 | — | CG-01 | V5 Input Validation | Cash valued via FX with no `price_cache` row; snapshot writes history row; add-holding pass-through | unit/integration | `pytest backend/tests/test_portfolio.py -k cash -q; pytest backend/tests/test_write_tools.py -k cash_and_gold -q` | ✅ test_portfolio.py / test_write_tools.py | ✅ green |
| — | 03 | — | CG-02 | — | Gold = full ledger holding; P&L identical to crypto | unit | `pytest backend/tests/test_portfolio.py -k gold -q` | ✅ test_portfolio.py | ✅ green |
| — | 03 | — | CG-03 | — | Gold price manual per gram; cash/gold have explicit TTL entries (not default 7d) | unit | `pytest backend/tests/test_fx.py -k ttl -q` | ✅ test_fx.py | ✅ green |
| — | 04 | — | INVX-01 | — | Value-history row written per snapshot (chart data contract); visual render is manual | integration | `pytest backend/tests/test_portfolio.py -k snapshot_writes_history -q` | ✅ test_portfolio.py | ✅ green (visual = manual) |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] FX adapter + immutable `(date, currency_pair)` cache (FX-01/02/05) — shipped as `backend/tests/test_fx.py` (not the planned `test_fx_adapter.py`)
- [x] Historical-at-purchase P&L incl. FX gain/loss (FX-03/FX-04) — folded into `backend/tests/test_portfolio.py` (`test_recompute_fx_*`, `test_summary_realized_pnl_fx_*`) rather than a standalone `test_currency_valuation.py`
- [x] Cash direct-override (CG-01) + gold ledger holding (CG-02/03) — folded into `backend/tests/test_portfolio.py` (`test_cash_*`, `test_gold_*`) + `test_write_tools.py::test_apply_add_holding_cash_and_gold_pass_through`, not a standalone `test_cash_gold_positions.py`

*Existing infrastructure (pytest under `backend/tests/`) covered the run harness. The planned standalone stub files were consolidated into the existing `test_fx.py` / `test_portfolio.py` / `test_write_tools.py` suites during execution — same coverage, fewer files.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Allocation pie + historical line chart render correctly | INVX-01 | Visual/Recharts rendering | Open `/investments`, confirm pie toggles asset-type↔platform and line chart shows value + P&L views with range selector |

*Chart data contracts are automated; visual rendering is manual (deferred to `/gsd-ui-phase` for interaction spec).*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 60s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** validated 2026-07-17

---

## Validation Audit 2026-07-17

Retroactive audit (`/gsd-validate-phase 7`). State A. Full suite: **191 passed, 0 failed, 0 skipped** (DB up).

| Metric | Count |
|--------|-------|
| Requirements audited | 9 (FX-01…05, CG-01…03, INVX-01) |
| Gaps found | 0 |
| Resolved (test generated) | 0 |
| Escalated to manual-only | 0 |

The map originally held one placeholder row; it was expanded to the nine requirements Phase 7 actually shipped. All coverage exists and runs green — the planned standalone test files (`test_fx_adapter.py`, `test_currency_valuation.py`, `test_cash_gold_positions.py`) were consolidated into `test_fx.py` + `test_portfolio.py` + `test_write_tools.py` during execution. INVX-01's visual chart render remains the one Manual-Only item.
