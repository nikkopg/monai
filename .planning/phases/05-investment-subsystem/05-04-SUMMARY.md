---
phase: 05-investment-subsystem
plan: 04
subsystem: investments
tags: [prices, staleness, override, coingecko, yfinance, ssrf]
requires: ["05-03"]
provides:
  - backend/prices.py (PRICE_ADAPTERS registry, refresh_all_prices, is_stale)
  - POST /prices/refresh, POST /prices/override
  - server-computed per-holding is_stale in GET /investments/summary
  - StalenessBadge, PriceOverrideDialog UI
affects: [backend/portfolio.py, backend/main.py, backend/writes.py, backend/schemas.py, ui/app/investments/page.tsx]
tech-stack:
  added: [httpx (already pinned), yfinance (already pinned)]
  patterns: [adapter registry keyed by asset_type, graceful-degradation adapters (never raise), server-computed staleness]
key-files:
  created:
    - backend/prices.py
    - ui/app/investments/StalenessBadge.tsx
    - ui/app/investments/PriceOverrideDialog.tsx
  modified:
    - backend/writes.py
    - backend/schemas.py
    - backend/main.py
    - backend/portfolio.py
    - backend/tests/test_prices.py
    - backend/tests/test_portfolio.py
    - ui/app/investments/page.tsx
decisions:
  - "yfinance 1.5.1 current-price key confirmed live: fast_info['lastPrice'] (camelCase); last_price returns None (Task 0, Open Question #1 resolved)"
  - "Manual override writes a new price_cache row (source='manual') rather than mutating — newest-row-wins so it is naturally replaced by the next live fetch (D-11)"
  - "is_stale computed server-side in portfolio.py via prices.is_stale; frontend only renders the flag"
metrics:
  duration_minutes: 40
  completed: 2026-07-11
  tasks: 4
  files: 10
status: complete
---

# Phase 05 Plan 04: Live Prices + Staleness + Manual Override Summary

Pluggable `PRICE_ADAPTERS` registry (crypto→CoinGecko IDR, idx_stock→yfinance `.JK`, mutual_fund/other→manual) with graceful per-ticker degradation, lazy-refresh-on-load plus a working "Refresh prices" button, audited manual price override, and server-computed per-asset-type staleness surfaced by `StalenessBadge` — INV-02/03/04/05 all demonstrable.

## What Was Built

- **backend/prices.py** — `PRICE_ADAPTERS` dict keyed by `asset_type`; `fetch_crypto_price` (SSRF-safe fixed `TICKER_TO_COINGECKO_ID` map, httpx timeout, returns None on any HTTPError/KeyError/ValueError), `fetch_idx_price` (alphanumeric-validated ticker → `yfinance.Ticker(f"{ticker}.JK").fast_info["lastPrice"]`, broad `except Exception` → None), `fetch_manual_price` (always None). `TTL_BY_ASSET_TYPE` (crypto 5min / idx_stock 1day / mutual_fund+other 7day) + `is_stale`. `refresh_all_prices(db, *, force=False)` routes each holding through its adapter with per-ticker try/except and writes a fresh price_cache row on success.
- **backend/writes.py** — `apply_set_price` writes a new price_cache row (source='manual', Decimal(str)) + an AuditLog `entity="price_cache"` row (D-16).
- **backend/schemas.py** — `PriceOverrideRequest` (positive-Decimal `price` via `gt=0`).
- **backend/main.py** — `POST /prices/refresh` (auth, force=True, tolerates per-ticker failure) + `POST /prices/override` (auth, 422 on non-positive price); lazy `refresh_all_prices(force=False)` folded into `GET /investments/summary` (D-09).
- **backend/portfolio.py** — per-holding `is_stale` (via `prices.is_stale`) added to each summary row alongside the existing `price_source`/`price_fetched_at`.
- **UI** — `StalenessBadge` (dot colour + "stale" pill from the server flag, ~15-line relative-time helper, no npm dep), `PriceOverrideDialog` (maxWidth 360, POST /api/prices/override, refetch), and `page.tsx` wiring (Refresh button handler, per-row badge, "Set price" link, per-row degradation note).

## Verification Results

| Check | Result |
|-------|--------|
| adapters never raise / unknown crypto ticker → None | PASS (test_fetch_crypto_price) |
| yfinance raising → None fallback (INV-03) + non-alnum ticker → None | PASS (test_fetch_idx_price_fallback) |
| is_stale respects per-asset-type TTL (INV-05) | PASS (test_is_stale_respects_ttl) |
| manual override → source='manual', P&L uses it immediately (INV-04) | PASS (test_manual_price_override) |
| stale row surfaces is_stale=true in summary (INV-05) | PASS (test_staleness_ttl) |
| POST /prices/override without key → 401 | PASS (test_override_requires_api_key) |
| negative/zero price → 422 | PASS (test_override_rejects_nonpositive_price) |
| POST /prices/refresh with failing ticker does not 500 | PASS (test_refresh_tolerates_failing_ticker) |
| tsc --noEmit clean for the 3 UI files | PASS (no `error TS` project-wide) |

`pytest backend/tests/test_prices.py backend/tests/test_portfolio.py` → **13 passed**.

## Task 0 Resolution (Open Question #1)

The dev box **has outbound egress**. Live probe of `yfinance.Ticker("BBCA.JK").fast_info` on the pinned yfinance 1.5.1 returned key `lastPrice` = 6175.0 IDR; `last_price` (snake_case) returned None. The RESEARCH default (`lastPrice`) was correct and is documented in a comment above `fetch_idx_price`. **Resolved live — not deferred.**

## Deferred (Human UAT)

- **Task 0 human-check**: key already confirmed live; the in-code comment records it.
- **Task 3 browser walkthrough**: add a crypto + IDX holding, click "Refresh prices", confirm non-null IDR prices with recent "as of" timestamps; manually override a mutual-fund price and confirm P&L updates; let a price age past TTL and confirm the stale dot + pill + "stale" text appear. (Requires the app running via `docker compose up -d --build`; see MEMORY "Deploy requires rebuild".)

## Deviations from Plan

None — plan executed as written. (Test-side note: mocked `httpx.get`/`yfinance.Ticker` directly rather than via a module attribute, since prices.py imports both lazily inside the adapters.)

## Parallel-Safety

Did not touch `backend/tools.py` or `backend/tests/test_tools.py` (owned by concurrent Plan 05-05).

## Self-Check: PASSED

- backend/prices.py, StalenessBadge.tsx, PriceOverrideDialog.tsx — all exist.
- Commits 3332210, 9cbb0a5, c9a297c — all present in git log.
