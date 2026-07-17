---
phase: 05-investment-subsystem
verified: 2026-07-16T20:30:00+07:00
status: passed
score: 6/6
method: agent-run UAT (automated) + live probes + integration cross-check
overrides_applied: 0
human_verification:
  - INV-05 staleness badge pixel rendering (dot/pill) — visual only
  - CHAT-03 live-LLM agent tool-selection in /chat — non-deterministic (also tracked in Phase 7 human-verify)
---

# Phase 5: Investment Subsystem — Verification Report

Retroactive verification produced during the v1.0 milestone audit (the phase shipped
6/6 plans on 2026-07-11 but never received a VERIFICATION.md). Evidence is from an
agent-run UAT: 95/95 targeted backend tests green in-container, live read-only API
probes, and live external price-adapter calls — cross-referenced against the Phase-6
integration check. Several INV requirements were additionally re-verified by Phase 7.

## Goal Achievement — 6 Success Criteria

| # | Success Criterion | Status | Evidence |
|---|-------------------|--------|----------|
| 1 | Add / edit / delete a holding (ticker, qty, avg cost, date, currency, asset type) | ✓ VERIFIED | test_write_tools apply_add/edit/delete_holding + apply_add_portfolio_event → recompute_holding_from_events, all audited. Re-verified in Phase 7 (INV-01). |
| 2 | Per-holding current price, value, P&L (IDR), P&L%, staleness badge + "as of" | ✓ VERIFIED | Live `GET /investments/summary` 200 returns current_value / unrealized_pnl / realized_pnl / price_source / price_fetched_at / is_stale per holding (e.g. ABF ID value 5,354,861.51, pnl −135,523.74). test_portfolio unrealized_pnl + test_prices is_stale pass. Badge pixel render = human-verify. |
| 3 | Crypto → live CoinGecko; IDX → live yfinance(.JK) w/ fallback; mutual funds → manual | ✓ VERIFIED | Live: fetch_crypto_price("BTC")→(1,131,343,438, coingecko), ETH→(32,789,556, coingecko); fetch_idx_price("BBCA")→(6475, yfinance), TLKM→(2660, yfinance); fetch_manual_price→None by design. Adapters return None on any error → fallback path. |
| 4 | Manually set/override any holding's price from UI, reflected immediately in P&L | ✓ VERIFIED | test_write_tools apply_set_price writes price_cache(source='manual', Decimal) + AuditLog(entity='price_cache'); POST /prices/override guarded + 422-on-nonpositive. Summary recomputes from latest price row. |
| 5 | Total portfolio value figure with an "as of" timestamp | ✓ VERIFIED | Summary groups[].subtotal + portfolio-total banner with "as of" caption (05-03 page.tsx). Live 200. |
| 6 | Portfolio buy/sell events recorded → agent answers correlation ("since I bought X…") | ✓ VERIFIED | portfolio_events written by apply_add_portfolio_event (INV-07). test_tools::test_spending_before_after_purchase passes (pivot_date, window_days, before/after totals, delta, delta_pct, no-buy error path). Tool dual-registered in TOOLS + query.py agent list. Live-LLM tool-selection = human-verify. |

**Score: 6/6 success criteria verified.**

## Behavioral Spot-Checks (independently re-run, not trusted from SUMMARY)

- `pytest test_portfolio test_prices test_scheduler test_write_tools test_tools` in monai-backend → **95 passed** (8.93s).
- Boot log: APScheduler `daily_portfolio_snapshot_job` registered → `Scheduler started` → `Application startup complete` (D-13/D-14 lifespan wiring).
- Live external network: CoinGecko + yfinance both reachable and returning realistic IDR-denominated prices with correct `source` tags.
- `GET /investments/summary` → HTTP 200 with real multi-platform portfolio payload.

## Requirements Coverage

| Requirement | Description | Status | Evidence |
|-------------|-------------|--------|----------|
| INV-01 | Holdings CRUD | ✓ SATISFIED | Criterion 1; re-verified Phase 7 |
| INV-02 | Crypto live prices | ✓ SATISFIED | Criterion 3 (live CoinGecko) |
| INV-03 | IDX live prices (best-effort + fallback) | ✓ SATISFIED | Criterion 3 (live yfinance) |
| INV-04 | Manual price override | ✓ SATISFIED | Criterion 4 |
| INV-05 | As-of time + staleness indicator | ✓ SATISFIED (badge render human-verify) | Criterion 2; is_stale/TTL tests |
| INV-06 | Portfolio value + per-holding P&L | ✓ SATISFIED | Criteria 2 & 5; re-verified Phase 7 |
| INV-07 | Portfolio events recorded | ✓ SATISFIED | Criterion 6; re-verified Phase 7 |
| CHAT-03 | Spending↔portfolio correlation | ✓ SATISFIED (live-agent human-verify) | Criterion 6; tool test passes |

No orphaned requirements. All 8 Phase-5 REQ-IDs trace to implementing plans and are verified above.

## Anti-Patterns Found

None blocking. `fetch_manual_price` returning None is intended (manual-fallback contract), not a stub. Per-ticker try/except in refresh + snapshot is deliberate degradation tolerance, not swallowed error.

## Gaps Summary

No code gaps. 6/6 success criteria and 8/8 requirements verified via automated UAT +
live probes. Two surfaces deferred to human eyes (not code gaps): the staleness badge's
visual rendering (INV-05) and the live-LLM agent's tool-selection behavior for the
correlation query (CHAT-03) — the latter is already tracked in Phase 7's human-verify list.

## VERIFICATION PASSED
