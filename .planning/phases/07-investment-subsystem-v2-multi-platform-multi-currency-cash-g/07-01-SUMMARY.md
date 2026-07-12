---
phase: 07-investment-subsystem-v2-multi-platform-multi-currency-cash-g
plan: 01
subsystem: fx-adapter-registry
tags: [fx, currency, migration, decimal, ssrf]
status: complete
dependency-graph:
  requires: []
  provides:
    - backend/fx.py::get_rate
    - backend/fx.py::fetch_frankfurter_rate
    - backend/fx.py::FX_ADAPTERS
    - backend/models.py::FxRateCache
    - backend/models.py::PortfolioEvent.currency
    - alembic/versions/008_fx_rate_cache.py
  affects:
    - backend/portfolio.py (Plan 02 — cash/gold valuation, historical-at-purchase P&L)
    - backend/prices.py (TTL_BY_ASSET_TYPE extended for cash/gold)
tech-stack:
  added: []
  patterns:
    - "D-08 adapter registry, structurally cloned for FX (dict[str, Callable])"
    - "Immutable INSERT-only cache keyed by (rate_date, base_currency, quote_currency) — mirrors PriceCache's single-read-path design"
    - "Never-raise adapter contract: any HTTP/parse failure returns None, caller propagates"
key-files:
  created:
    - backend/fx.py
    - backend/tests/test_fx.py
    - alembic/versions/008_fx_rate_cache.py
  modified:
    - backend/models.py
    - backend/prices.py
decisions:
  - "USDT normalized to USD via a module-level _FX_ALIASES dict (one entry) before any lookup — not a frankfurter call, since frankfurter carries no crypto stablecoins"
  - "No walk-backward logic for weekend/holiday dates (Pitfall 3) — frankfurter already returns the nearest prior business-day rate; orchestrator decision, not re-litigated here"
  - "Cash gets an explicit TTL entry in prices.py purely to close Pitfall 1 (never silently falls to _DEFAULT_TTL); portfolio_summary (Plan 02) will special-case asset_type=='cash' to skip price_cache/is_stale entirely — the TTL value itself is unused for cash but documents intent"
  - "Migration 008 revision hash d3e4f5a6b7c8, down_revision c1d2e3f4a5b6 (verified against all 7 existing revision hashes for uniqueness before writing)"
metrics:
  duration: ~25m
  completed: 2026-07-12
---

# Phase 7 Plan 1: FX Adapter Registry + Immutable Rate Cache Summary

Built the FX foundation every downstream currency-aware valuation depends on: a `backend/fx.py`
adapter registry (structural clone of `backend/prices.py`, D-08) calling frankfurter.dev for
by-date historical USD/IDR-class rates, an immutable `(rate_date, base_currency, quote_currency)`
cache table (FX-05), and the `portfolio_events.currency` column for FX-04's "native cost + currency
on the event, rate re-derived by date" model. Closed Pitfall 1 by adding explicit `cash`/`gold` TTL
entries to `prices.py` so neither new asset type silently inherits the 7-day default.

## What Was Built

**Task 1 — `backend/fx.py` + `backend/tests/test_fx.py`:**
- `fetch_frankfurter_rate(base, quote, as_of)` — GET `https://api.frankfurter.dev/v1/{date}`,
  parses `rates[quote]` as `Decimal(str(...))`, wrapped in try/except returning `None` on any
  failure (HTTP error, malformed JSON, missing key) — never raises.
- `FX_ADAPTERS: dict[str, Callable]` registry (`{"frankfurter": fetch_frankfurter_rate}`), mirroring
  `PRICE_ADAPTERS`'s exact shape.
- `get_rate(base, quote, as_of, db)` — the single entry point every valuation caller uses:
  1. `base == quote` → `Decimal("1")` identity shortcut, no HTTP call.
  2. USDT normalized to USD via `_FX_ALIASES` before lookup (FX-02).
  3. `base`/`quote` validated against `^[A-Z]{3,4}$` **before** any HTTP call (SSRF guard, Pitfall 5) —
     an invalid code returns `None` with zero outbound requests.
  4. Cache HIT → returns the stored `Decimal`, adapter never called (FX-05, proven via
     `mock.assert_not_called`-style assertions in tests, not just assumed).
  5. Cache MISS → calls the adapter; a non-`None` result INSERTs exactly one immutable row keyed
     `(rate_date, base_currency, quote_currency)`.
  6. Adapter `None` (vendor outage) → `None`, never a fabricated `rate=1.0`.
- `backend/tests/test_fx.py` — 11 tests, all mocked (no live network): adapter success/HTTP-error/
  malformed-JSON, identity shortcut, invalid-currency SSRF guard, USDT normalization, cache hit
  (adapter not called), cache miss (exactly one row written, adapter called once), a full two-call
  round-trip proving no re-fetch on the second `get_rate` for the same pair/date, and a TTL-entry
  assertion for cash/gold.
- `backend/prices.py`: added explicit `"gold": timedelta(days=7)` (matches `mutual_fund`'s cadence)
  and `"cash": timedelta(days=7)` (documented as unused-in-practice — cash valuation is FX-driven,
  not `price_cache`-driven; the entry exists solely so neither type falls through to
  `_DEFAULT_TTL` silently).

**Task 2 — `FxRateCache` model + `PortfolioEvent.currency` + migration 008:**
- `backend/models.py::FxRateCache` — structural clone of `PriceCache` (`String(8)` currency codes,
  `String(32)` source, `DateTime(timezone=True) server_default=now()`), with `rate: Numeric(18, 6)`
  (wider scale than price's `Numeric(18, 2)` for FX sub-unit precision) and a `UniqueConstraint`
  named `uq_fx_rate_cache_date_pair` on `(rate_date, base_currency, quote_currency)` — this is the
  DB-level enforcement of FX-05 immutability.
- `backend/models.py::PortfolioEvent.currency` — `String(8)`, `server_default='IDR'`, nullable,
  mirroring `Holding.currency`'s idiom. Per orchestrator decision: each buy/sell event carries
  exactly one currency, validated against the parent holding's currency at write time (deferred to
  Plan 02's write-path work).
- `alembic/versions/008_fx_rate_cache.py` — revision `d3e4f5a6b7c8`, `down_revision = "c1d2e3f4a5b6"`
  (migration 007 head, verified unique against all 7 existing revision hashes before writing).
  `upgrade()`: `op.create_table` for `fx_rate_cache` (unique constraint + index on `rate_date`),
  then `op.add_column` for `portfolio_events.currency`. `downgrade()`: exact inverse order
  (drop the event column first, then drop the FX table) — AST-validated to confirm both
  `upgrade`/`downgrade` functions exist.

## Verification

- `cd backend && python -m pytest tests/test_fx.py -x` → **11 passed** (via `uv run
  --with-requirements backend/requirements.txt --with pytest`, since `python`/`python3.12` aren't on
  PATH in this environment but the project's documented `uv run --with-requirements` dev-runner
  convention works identically).
- `cd backend && python -m pytest tests/test_prices.py -x` → **13 passed** — TTL dict edit did not
  regress existing price-adapter tests.
- Migration 008 AST-checked: both `upgrade`/`downgrade` functions present.
- `grep -n 'down_revision' alembic/versions/008_fx_rate_cache.py` → `c1d2e3f4a5b6` (matches 007 head).
- `grep -n 'FX_ADAPTERS' backend/fx.py` → registry dict present, keyed by `"frankfurter"`.
- `backend/requirements.txt` unchanged (no new package installs this plan).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 — blocking] `python`/`python3.12` not on PATH; used the project's documented `uv run --with-requirements` dev-runner instead**
- **Found during:** Task 1 verification
- **Issue:** The plan's verify command (`python -m pytest ...`) failed with `python: command not found` — only `python3` (3.14, no project deps installed) and `uv` were available.
- **Fix:** Used `uv run --with-requirements backend/requirements.txt --with pytest python -m pytest ...`, which CLAUDE.md documents as the host dev runner. No source change — verification-tooling only.
- **Files modified:** none (test invocation only)
- **Commit:** N/A (no source change)

**2. [Rule 3 — blocking] `FxRateCache` model needed by `backend/fx.py`'s import, split from `PortfolioEvent.currency` for atomic per-task commits**
- **Found during:** Task 1 implementation
- **Issue:** `backend/fx.py` imports `FxRateCache` from `backend/models.py`, but the plan's file split assigns `FxRateCache` to Task 1's must-haves (`backend/models.py — FxRateCache model`) while `PortfolioEvent.currency` and the migration are Task 2's scope. Both land in `backend/models.py`.
- **Fix:** Added `FxRateCache` in Task 1's commit (required for `fx.py` to import), added `PortfolioEvent.currency` in Task 2's commit alongside migration 008 — two non-overlapping hunks in the same file, staged and committed separately to preserve atomic per-task history.
- **Files modified:** `backend/models.py` (across both commits)
- **Commit:** `6f6c9fe` (Task 1, FxRateCache), `2e5beb1` (Task 2, PortfolioEvent.currency + migration)

No other deviations — plan executed as written otherwise.

## Known Stubs

None. `fx.py`/`get_rate` is fully wired for the cache-first/immutable-write behavior; no valuation
call sites exist yet (that's Plan 02's scope, per the plan's explicit "no valuation wiring yet"
objective).

## Threat Flags

None beyond the plan's own `<threat_model>` — all threats (T-07-01-SSRF, T-07-01-DEG, T-07-01-INJ,
T-07-01-INT, T-07-01-IMM) were mitigated exactly as specified; no new surface introduced outside
those already registered.

## Self-Check: PASSED

- FOUND: backend/fx.py
- FOUND: backend/tests/test_fx.py
- FOUND: alembic/versions/008_fx_rate_cache.py
- FOUND: .planning/phases/07-investment-subsystem-v2-multi-platform-multi-currency-cash-g/07-01-SUMMARY.md
- FOUND commit: 6f6c9fe (Task 1)
- FOUND commit: 2e5beb1 (Task 2)
