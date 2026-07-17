---
phase: 5
slug: investment-subsystem
status: validated
nyquist_compliant: true
wave_0_complete: true
created: 2026-07-06
validated: 2026-07-17
---

# Phase 5 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `05-RESEARCH.md` § Validation Architecture.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest >=8.0.0 (`backend/requirements.txt`), `asyncio_mode = "auto"` |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` — `testpaths = ["backend/tests"]` |
| **Quick run command** | `pytest backend/tests/test_portfolio.py backend/tests/test_prices.py -x` |
| **Full suite command** | `pytest backend/tests` (requires live Postgres — existing `db_available` fixture skips gracefully if down) |
| **Estimated runtime** | ~15–30 seconds (quick), ~60s (full with DB) |

---

## Sampling Rate

- **After every task commit:** Run `pytest backend/tests/test_portfolio.py backend/tests/test_prices.py -x`
- **After every plan wave:** Run `pytest backend/tests` (needs `docker compose up -d db`)
- **Before `/gsd:verify-work`:** Full suite green + manual `alembic upgrade head` / `alembic downgrade -1` round-trip
- **Max feedback latency:** ~30 seconds

---

## Per-Task Verification Map

| Requirement | Behavior | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|-------------|----------|------------|-----------------|-----------|-------------------|-------------|--------|
| INV-01 | Add/edit/remove holding via events; holding recomputes correctly | — | N/A | unit | `pytest backend/tests/test_portfolio.py::test_recompute_holding_from_events -x` | ✅ test_portfolio.py | ✅ green |
| INV-01 | Direct holding override (D-03) writes audit_log | T-5 Repudiation | Every `apply_*` writes AuditLog before/after | unit | `pytest backend/tests/test_write_tools.py::test_propose_edit_holding_creates_proposal -x` | ✅ test_write_tools.py | ✅ green |
| INV-02 | CoinGecko adapter returns Decimal price for a known coin id | T-5 SSRF | Ticker→coin-id via fixed server map | unit (mocked HTTP) | `pytest backend/tests/test_prices.py::test_fetch_crypto_price -x` | ✅ test_prices.py | ✅ green (+3 coin-id variants) |
| INV-03 | yfinance adapter degrades to None on any exception (fallback contract) | — | Never propagate 500; fall back to cache | unit (mocked yfinance) | `pytest backend/tests/test_prices.py::test_fetch_idx_price_fallback -x` | ✅ test_prices.py | ✅ green |
| INV-04 | Manual price override writes `price_cache` `source='manual'`, reflected in P&L | V5 Input Validation | Positive Decimal at schema layer | integration | `pytest backend/tests/test_portfolio.py::test_manual_price_override -x` | ✅ test_portfolio.py | ✅ green |
| INV-05 | Staleness badge flips to "stale" once `fetched_at` exceeds asset-type TTL | — | N/A | unit | `pytest backend/tests/test_portfolio.py::test_staleness_ttl -x` | ✅ test_portfolio.py | ✅ green |
| INV-06 | Realized + unrealized P&L match hand-computed values for buy→sell→dividend | — | N/A | unit | `pytest backend/tests/test_portfolio.py::test_avg_cost_realized_pnl -x` | ✅ test_portfolio.py | ✅ green |
| INV-07 | `portfolio_events` row created on every buy/sell/dividend write | V5 Input Validation | `event_type` constrained to Literal set | integration | `pytest backend/tests/test_write_tools.py -k apply_add_portfolio_event -x` | ✅ test_write_tools.py | ✅ green (renamed `test_apply_add_portfolio_event_*`) |
| CHAT-03 | Correlation tool returns correct before/after totals for a known pivot date | — | N/A | unit | `pytest backend/tests/test_tools.py -k spending_before_after_purchase -x` | ✅ test_tools.py | ✅ green |
| D-14 | Daily job runs without raising even if one ticker's fetch fails | T-5 DoS | `max_instances=1` + misfire grace | integration | `pytest backend/tests/test_scheduler.py::test_snapshot_job_partial_failure_tolerant -x` | ✅ test_scheduler.py | ✅ green |
| D-17 | `alembic upgrade head` applies cleanly on `9c1a4f7d2b8e`, reversible | — | N/A | manual/smoke | `alembic upgrade head && alembic downgrade -1` on dev DB copy | manual-only | 🔵 manual (see Manual-Only) |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky · 🔵 manual*

---

## Wave 0 Requirements

- [ ] `backend/tests/test_portfolio.py` — covers INV-01/04/05/06 (recompute algorithm, manual override, staleness, P&L math)
- [ ] `backend/tests/test_prices.py` — covers INV-02/03 (adapter contract: returns `(Decimal, str) | None`, never raises)
- [ ] `backend/tests/test_scheduler.py` — covers D-14 (job registration + partial-failure tolerance; test the job function directly, no cron tick wait)
- [ ] Extend `backend/tests/test_write_tools.py` — holding/portfolio_event/platform propose-creates-row cases (template: existing `test_propose_edit_holding_creates_proposal`)
- [ ] Extend `backend/tests/test_tools.py` — `test_spending_before_after_purchase` (template: existing `spending_in_category` test)
- [ ] **yfinance `fast_info` smoke test** — verify the exact current-price attribute/key casing against pinned yfinance 1.5.1 before the crypto/IDX adapters are finalized (Open Question #1 from research)
- [ ] No framework install needed — pytest, `db_available` skip-fixture, and `testpaths` config already apply to new test files automatically.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Alembic migration applies + reverses cleanly | D-17 | No automated DB-migration test harness in repo yet (Phase 1 also verified migrations manually) | `alembic upgrade head` on a copy of dev DB, confirm `platforms`/`portfolio_value_history`/`holdings.platform_id` present, then `alembic downgrade -1` to confirm reversibility |
| Investments page renders holdings grouped by platform with P&L, staleness badge, refresh button | INV-02/05/06 | Visual/interaction layout (delegated to UI-SPEC) — requires browser | Human browser-verify against UI-SPEC after execution (see Phase human-verify checkpoint) |
| Live price fetch actually returns IDR values from CoinGecko / yfinance | INV-02/03 | External API behavior not mocked in prod smoke | Add a crypto + an IDX holding, click "Refresh prices", confirm non-null IDR prices with recent "as of" timestamps |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (`test_portfolio.py`, `test_prices.py`, `test_scheduler.py`)
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** validated 2026-07-17

---

## Validation Audit 2026-07-17

Retroactive audit (`/gsd-validate-phase 5`). State A. Full suite: **191 passed, 0 failed, 0 skipped** (DB up).

| Metric | Count |
|--------|-------|
| Requirements audited | 9 automated (INV-01…07, CHAT-03, D-14) + 1 manual (D-17) |
| Gaps found | 0 |
| Resolved (test generated) | 0 |
| Escalated to manual-only | 0 |

All planned test files (`test_portfolio.py`, `test_prices.py`, `test_scheduler.py`) exist and run green. Two rows had their command corrected to match shipped names: INV-07 → `test_apply_add_portfolio_event_*`, CHAT-03 → `-k spending_before_after_purchase`. D-17 (migration up/down) stays manual-only by design; the three visual/live-API items in Manual-Only remain manual.
