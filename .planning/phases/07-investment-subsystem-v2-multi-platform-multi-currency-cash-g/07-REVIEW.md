---
phase: 07-investment-subsystem-v2-multi-platform-multi-currency-cash-g
reviewed: 2026-07-12T00:00:00Z
depth: standard
files_reviewed: 12
files_reviewed_list:
  - backend/fx.py
  - backend/portfolio.py
  - backend/writes.py
  - backend/tools.py
  - backend/main.py
  - backend/models.py
  - backend/schemas.py
  - backend/prices.py
  - alembic/versions/008_fx_rate_cache.py
  - ui/app/investments/AllocationPieChart.tsx
  - ui/app/investments/ValueHistoryChart.tsx
  - ui/app/investments/page.tsx
findings:
  critical: 2
  warning: 3
  info: 2
  total: 7
resolved: [CR-01, CR-02, WR-01, WR-02, IN-01, IN-02]
deferred: [WR-03]
status: resolved
---

# Phase 07: Code Review Report

**Reviewed:** 2026-07-12
**Status:** resolved — 6 of 7 findings fixed; WR-03 deferred as a schema-migration design decision.

## Resolution Log (2026-07-12)

- **CR-01** ✅ `_realized_for_position` now FX-converts each event to IDR (mirrors `recompute_holding_from_events`); `portfolio_summary` null-guards `total_realized`. Regression test `test_summary_realized_pnl_fx_converted_for_non_idr_position` added (USD position → realized = 6,000,000 IDR, not raw 400).
- **CR-02** ✅ `get_rate()` now `db.flush()`es after the cache insert so same-request repeat lookups see the pending row (autoflush=False). Single-user app → cross-session race not applicable.
- **WR-01** ✅ `test_get_rate_second_call_same_pair_does_not_refetch` fake DB now models autoflush=False (SELECT reads only flushed rows) — a genuine regression guard for CR-02.
- **WR-02** ✅ `PortfolioEventCreate.price` docstring corrected to native-currency semantics.
- **IN-01** ✅ `update_holding` now maps `IntegrityError` → 422 on ticker-rename collision (mirrors `create_holding`).
- **IN-02** ✅ `confirm_proposal` now catches `ValueError`/`IntegrityError` → 422 before the broad `except Exception` → 500.
- **WR-03** ⏸ DEFERRED — widening `PortfolioEvent.price` / `Holding.avg_cost` from `Numeric(18,2)` to `Numeric(18,6)` requires a new migration and is a schema design decision for the user, not an auto-fix.

**Files Reviewed:** 12
**Original Status:** issues_found

## Summary

The FX adapter registry (`fx.py`) itself is well-built: the SSRF guard (regex validated
before any URL is built, alias table maps only to fixed safe values), the never-raise
adapter contract, and the None-propagation discipline (never fabricate `rate=1.0`) are
all correctly implemented and match the documented patterns. The chat write-path
delegation fix (CH-01, `_execute_proposal_payload` → `apply_add_holding`/`apply_edit_holding`)
is also correctly wired and matches the direct-REST code path exactly, closing the
regression it targeted.

However, two money-path bugs undermine the "correctness-by-construction" and "never
fabricate a number" guarantees this phase explicitly re-affirms:

1. `get_rate()`'s cache-insert is un-flushed within a session that has `autoflush=False`,
   so any single request that needs the *same* `(rate_date, base, quote)` FX rate more
   than once (two same-day same-currency events on one position; two same-currency cash
   holdings in one `portfolio_summary()`/`snapshot_all_holdings()` call) will insert a
   duplicate `FxRateCache` row and raise `IntegrityError` at flush/commit — a 500, not a
   graceful degrade.
2. `portfolio.py`'s private `_realized_for_position()` (the function `portfolio_summary`
   uses to compute each holding's `realized_pnl` and the portfolio's `total_realized_pnl`)
   was never updated for FX-03/FX-04 — it still sums `ev.price * ev.quantity` in the
   event's *native* currency and adds that directly into an IDR total, silently
   corrupting realized P&L for every non-IDR position. This is the same computation that
   `recompute_holding_from_events` correctly FX-converts a few functions above it.

Both are untested: the FX test suite for `recompute_holding_from_events` monkeypatches
`fx.get_rate` entirely (never exercises the real cache/session-flush path), and no test
calls `portfolio_summary`/`_realized_for_position` against a non-IDR position.

## Critical Issues

### CR-01: `_realized_for_position` omits FX conversion — realized P&L wrong for every non-IDR position

**File:** `backend/portfolio.py:439-472`
**Issue:** `recompute_holding_from_events` (lines 93-122) correctly converts each event's
native `price × quantity` to IDR via `fx.get_rate(ev_currency, "IDR", ev.date, db)` before
folding it into `total_cost`/`realized_pnl`/`dividend_total`. `_realized_for_position` —
the read-only twin used by `portfolio_summary` for the per-holding `realized_pnl` field
*and* summed into the portfolio's `total_realized_pnl` — is a near-verbatim copy of the
pre-FX accumulator (compare lines 459-470 to lines 108-122) but was never given the same
FX-conversion step. For a USD-denominated position, `ev.price` is a USD amount; this
function adds `(ev.price - avg_cost) * ev.quantity` and `ev.price * ev.quantity` straight
into `realized_pnl`/`dividend_total` as if they were IDR, then `portfolio_summary` sums
that directly into `total_realized += realized["realized_pnl"]` (line 252) — an IDR total
now containing raw USD magnitudes. This silently fabricates a wrong number, which is
exactly what this phase's own documented invariant ("never fabricate a number") forbids.
Also affects the per-holding `realized_pnl` shown in the UI (`page.tsx`'s `HoldingRow.realized_pnl`).
**Fix:** Apply the identical conversion `recompute_holding_from_events` uses — either
convert `_realized_for_position` in place (inject `rate = fx.get_rate(ev.currency or
holding_currency, "IDR", ev.date, db)` at the two `realized_pnl`/`dividend_total`
mutation sites, mirroring lines 93-122 exactly), or better, delete the duplicated
accumulator entirely and have `_realized_for_position` call
`recompute_holding_from_events` in a way that doesn't persist (e.g. run it against a
sub-transaction/no-commit call and discard the holding mutation) so the two P&L
computations can never drift again:
```python
def _realized_for_position(db: Session, ticker: str, platform_id: int) -> dict:
    events = db.scalars(
        select(PortfolioEvent)
        .where(PortfolioEvent.ticker == ticker, PortfolioEvent.platform_id == platform_id)
        .order_by(PortfolioEvent.date, PortfolioEvent.id)
    ).all()
    holding = db.query(Holding).filter(
        Holding.ticker == ticker, Holding.platform_id == platform_id
    ).one_or_none()
    default_currency = holding.currency if holding is not None else "IDR"

    qty = Decimal("0")
    total_cost = Decimal("0")
    realized_pnl = Decimal("0")
    dividend_total = Decimal("0")
    for ev in events:
        ev_currency = ev.currency or default_currency
        rate = fx.get_rate(ev_currency, "IDR", ev.date, db)
        if rate is None:
            return {"realized_pnl": None, "dividend_total": None}
        idr_amount = ev.price * ev.quantity * rate
        if ev.event_type == "buy":
            total_cost += idr_amount
            qty += ev.quantity
        elif ev.event_type == "sell":
            avg_cost = (total_cost / qty) if qty > 0 else Decimal("0")
            realized_pnl += (ev.price * rate - avg_cost) * ev.quantity
            total_cost -= avg_cost * ev.quantity
            qty -= ev.quantity
        elif ev.event_type == "dividend":
            realized_pnl += idr_amount
            dividend_total += idr_amount
    return {"realized_pnl": realized_pnl, "dividend_total": dividend_total}
```
And handle the new `None` case in `portfolio_summary`'s `total_realized += realized["realized_pnl"]`
(currently assumes always-Decimal; must null-guard like `total_unrealized` already does).

---

### CR-02: `fx.get_rate` cache-miss insert is never flushed — duplicate same-request FX lookups raise `IntegrityError` (500)

**File:** `backend/fx.py:107-127`, `backend/db.py:17` (`autoflush=False`)
**Issue:** `SessionLocal` is configured `autoflush=False` (`backend/db.py:17`). On a cache
miss, `get_rate()` does `db.add(FxRateCache(...))` (line 117) and returns — it never
calls `db.flush()`. `_latest_cache_row()` (line 75-82) issues a plain `SELECT`, which
with `autoflush=False` will **not** see the pending, unflushed `FxRateCache` object added
by an earlier call within the same session/request. Any code path that calls
`fx.get_rate()` more than once for the identical `(rate_date, base_currency,
quote_currency)` triple inside one request will:
  1. First call: cache miss → adapter call → `db.add(row)` (unflushed).
  2. Second call: `_latest_cache_row` SELECT misses the unflushed row → cache miss again
     → adapter called again → `db.add(row2)` with the **same** unique key.
  3. At the next `db.flush()`/`db.commit()`, the DB-level `uq_fx_rate_cache_date_pair`
     unique constraint raises `IntegrityError`, which is not a `ValueError`, so it is
     **not** mapped to 422 anywhere in `main.py` — it either bubbles up as an unhandled
     500 (`POST /portfolio-events`) or is caught by `confirm_proposal`'s broad `except
     Exception` and turned into a generic `500 Write failed` (`backend/main.py:839-841`).

Concretely reachable via:
  - `recompute_holding_from_events` (portfolio.py:93-122): a position with **two buy/sell
    events on the same trade date, same currency** (e.g. two USD buys logged the same
    day) calls `fx.get_rate("USD", "IDR", same_date, db)` twice in the same loop.
  - `portfolio_summary` (portfolio.py:214-226): **two cash holdings in the same
    currency** (e.g. two USD accounts on different platforms) both call
    `fx.get_rate(currency, "IDR", today, db)` on the same request.
  - `snapshot_all_holdings` (portfolio.py:351-359): same duplicate-currency-same-day
    scenario during the daily snapshot job.

This is untested: every FX test in `test_portfolio.py` (`test_recompute_fx_converts_...`,
`test_recompute_fx_d02_invariant_...`, etc.) monkeypatches `portfolio_mod.fx.get_rate`
directly, bypassing the real cache/session-flush path entirely, and
`test_fx.py::test_get_rate_second_call_same_pair_does_not_refetch` uses a hand-rolled
`_StatefulDb` fake whose `scalars()` reflects `self.added` **immediately** after
`db.add()` — i.e. it *simulates* autoflush-on behavior and therefore cannot catch this
bug (see WR-01).
**Fix:** Flush after the insert so same-session repeat lookups see the pending row:
```python
    rate, source = result
    db.add(
        FxRateCache(
            rate_date=as_of,
            base_currency=base_norm,
            quote_currency=quote_norm,
            rate=rate,
            source=source,
            fetched_at=datetime.now(timezone.utc),
        )
    )
    db.flush()  # LOAD-BEARING: autoflush=False — a same-session repeat lookup for
                # this (rate_date, base, quote) must see this row, not re-insert it
    return rate
```
This is the same `# LOAD-BEARING: ... flush ...` idiom already used throughout
`writes.py` for exactly this session-visibility reason.

## Warnings

### WR-01: `test_get_rate_second_call_same_pair_does_not_refetch` fake DB masks the CR-02 bug

**File:** `backend/tests/test_fx.py:195-235`
**Issue:** The test's `_StatefulDb.scalars()` returns `_FakeQuery(self.added[0] if
self.added else None)` — it treats anything in `self.added` (populated by `db.add()`) as
immediately queryable, i.e. it models an `autoflush=True` session. The real
`SessionLocal` is `autoflush=False` (`backend/db.py:17`). The test's own comment even
says "Simulates the real DB round-trip" (line 216-218), but it does not — a fake that
matched the real session's autoflush setting would have caught CR-02 immediately (the
second `get_rate` call would still show `call_count["n"] == 2`).
**Fix:** Make the fake only return added rows after an explicit `db.flush()` call (add a
`flushed` list separate from `added`, populate `scalars()` from `flushed`, and give the
fake a `flush()` method that moves `added` → `flushed`) — this converts the test into a
real regression test for CR-02's fix rather than a test that always passes regardless of
whether `get_rate` flushes.

---

### WR-02: `PortfolioEventCreate.price` docstring says "in IDR" but the field is now the native-currency price

**File:** `backend/schemas.py:135`
**Issue:** `price: MoneyDecimal = Field(..., gt=0, description="Price per unit (or
dividend amount) in IDR; positive")` — this description predates the FX-03/FX-04 work.
Since `currency` (line 139-141) is now an optional per-event field and
`recompute_holding_from_events` treats `ev.price` as a **native-currency** amount that it
then multiplies by `fx.get_rate(...)` (portfolio.py:105-106), the docstring is actively
wrong for any non-IDR event and will mislead both API consumers and the chat agent's
tool-calling model (which reads Pydantic field descriptions as part of its schema
understanding) into passing an IDR-converted price for a USD-denominated buy, double
FX-converting the cost basis.
**Fix:**
```python
price: MoneyDecimal = Field(
    ..., gt=0,
    description="Price per unit (or dividend amount) in the event's native currency "
                 "(see `currency`); converted to IDR internally at the trade-date FX rate.",
)
```

---

### WR-03: `portfolio_events.price` / `holdings.avg_cost` `Numeric(18, 2)` truncates sub-cent native-currency prices now that FX conversion is live

**File:** `backend/models.py:164, 194` (pre-existing columns, newly consequential with `PortfolioEvent.currency`)
**Issue:** `PortfolioEvent.price` and `Holding.avg_cost` are `Numeric(18, 2)` — two
decimal places. Before this phase, all prices were implicitly IDR (a currency with no
practical sub-unit use), so 2dp was sufficient. Now that `PortfolioEvent.currency` lets a
buy be denominated in USD (or any other currency), a native price like `$0.0035` (a
low-priced stablecoin/penny stock) or `$123.456` truncates to `$0.00`/`$123.46` **before**
FX conversion ever runs, silently degrading cost-basis precision for foreign-currency
positions. This is a pre-existing column definition, not new code added this phase, but
this phase is what makes the truncation newly reachable/consequential (native-currency
events did not exist before FX-04).
**Fix:** Widen `PortfolioEvent.price` (and consider `Holding.avg_cost`) to `Numeric(18, 6)`
or similar in a follow-up migration, matching `FxRateCache.rate`'s `Numeric(18, 6)`
precision choice made in this same phase (models.py:268) — the team already recognized 2dp
is insufficient for FX-adjacent decimals when sizing that column.

## Info

### IN-01: `apply_edit_holding` allows changing `ticker` with no duplicate-`(ticker, platform_id)` guard

**File:** `backend/writes.py:308-329`
**Issue:** `apply_edit_holding` lets a direct `PUT /holdings/{id}` (or a chat
`edit_holding` proposal) change `holding.ticker` freely (line 313-314). Since position
identity is `(ticker, platform_id)` (`uq_holdings_ticker_platform`), retargeting a
holding's ticker to one that already exists on the same platform will raise a DB-level
`IntegrityError` at commit — caught in `update_holding` only as a generic path (no
`IntegrityError` handler there, unlike `create_holding` which does catch it at
main.py:377-382) — so this endpoint will 500 instead of 422 on that collision. Separately,
changing `ticker` on a holding whose `portfolio_events` still reference the old ticker
silently orphans the ledger (future `recompute_holding_from_events(db, old_ticker,
platform_id)` calls would recreate a stale holding row).
**Fix:** Either reject `ticker` changes in `apply_edit_holding` (drop it from
`HoldingUpdate`/ignore it) since D-03's "direct override" escape hatch shouldn't need to
rename tickers, or add the same `IntegrityError` → 422 handling `create_holding` already
has to `update_holding`.

---

### IN-02: `confirm_proposal`'s broad `except Exception` maps `ValueError` (currency mismatch, bad range, etc.) to 500 instead of 422

**File:** `backend/main.py:834-841`
**Issue:** Unlike every direct REST write endpoint in this codebase (`create_portfolio_event`,
`create_holding`, `update_holding`, `investments_history`), which explicitly catch
`ValueError` and map it to `HTTPException(422)` per the project's documented
`ValueError → 422` convention (see CLAUDE.md "Error Handling" and this phase's own
07-PATTERNS.md "ValueError → 422 at the API boundary" section), `confirm_proposal` catches
`Exception` broadly and always returns 500. This is pre-existing code (not touched by this
phase's diff), but it is directly relevant to this phase's money paths — the two branches
this phase's fix delegates to (`apply_add_holding`/`apply_edit_holding` via
`_execute_proposal_payload`) can both raise `ValueError` (`apply_edit_holding`'s "Holding
{id} not found"), and CR-02's `IntegrityError` will also route through here for any
proposal-confirmed write. Flagged as info since it's an existing pattern this phase's
changes now interact with more, not a regression introduced by this phase.
**Fix (future, out of this phase's scope):** Catch `ValueError` explicitly before the
broad `except Exception` in `confirm_proposal`, matching the direct-endpoint convention.

---

_Reviewed: 2026-07-12_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
