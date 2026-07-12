# Phase 7: Investment Subsystem v2 (multi-platform, multi-currency, cash, gold, viz) - Research

**Researched:** 2026-07-12
**Domain:** Multi-currency FX conversion, cash/gold position modeling, historical price/rate caching, Recharts data-viz endpoints, Alembic reversible migrations
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Currency & FX model (scope item 2 — the keystone)**
- **FX-01:** USD→IDR rate comes from a **live FX API**, implemented as an **adapter routed through the same registry pattern as price adapters** (Phase 5 D-08). It MUST support **by-date historical rate lookups** (not just current spot) — required by FX-03. The specific free API is a **research task** (must cover IDR + historical; candidates: exchangerate.host, frankfurter — verify IDR coverage, ECB-based sources may lack IDR).
- **FX-02:** **Arbitrary per-holding currency.** Holdings carry a general `currency` column; any currency convertible to IDR is allowed (not restricted to USD+IDR). USDT is treated as ≈1:1 USD.
- **FX-03:** **Historical-at-purchase P&L semantics.** Cost basis is converted at the **trade-date** rate; current value at the **current** rate. Unrealized P&L therefore **includes FX gain/loss** — a true IDR return, not just the asset's native-currency move.
- **FX-04:** **No per-event FX-rate column.** Store only **native cost + currency** on the event; the historical rate is **re-fetched by date** from the FX cache at compute time. (User accepted the tradeoff that P&L then depends on the FX cache rather than a frozen per-event number.)
- **FX-05 (guard for FX-04):** The FX adapter MUST **cache historical by-date rates immutably**, keyed by `(date, currency_pair)` (mirroring `price_cache`), so a re-fetch returns the previously-stored value rather than re-hitting the vendor. This is what keeps historical P&L **stable/reproducible** despite the no-column choice — planner must not skip it.

**Cash & gold positions (scope items 3 & 4)**
- **CG-01:** **Cash = directly-set balance.** New `asset_type=cash`; the balance is set/edited directly via the Phase-5 **D-03 holding-override path** (no buy/sell event itemization). IDR value = `amount × FX-to-IDR` (FX-01). No cost basis / no unrealized gain **except** FX movement.
- **CG-02:** **Gold = normal ledger holding.** New `asset_type=gold`, `quantity` = grams, price = **per-gram**. Full cost basis + unrealized P&L, exactly like any other ledger position (Phase 5 D-01/D-02).
- **CG-03:** **Gold price is manual per gram**, written to `price_cache` with `source='manual'` and refreshed like reksadana manual prices. A **live gold spot adapter is deferred** — addable later via the D-08 registry.

**Allocation pie chart (scope item 5)**
- **VZ-01:** Recharts **pie**, value basis = **current IDR market value**, with a **toggle: asset-type ↔ platform** (both groupings already exist on the page). Exact placement on `/investments` → `/gsd-ui-phase`.

**Historical line chart (scope item 6 — INVX-01, pulled into this phase)**
- **VZ-02:** Source = `portfolio_value_history` (stores `market_value` + `cost_basis` in IDR per position per day). **Two views, "like Bitget":** (a) **total portfolio value over time**, and (b) **unrealized P&L over time** (`market_value − cost_basis`, both already snapshotted), with a **time-range selector**. Realized P&L still derives from `portfolio_events` separately. History **starts at collector go-live — no backfill** (Phase 5 D-13). Exact interactions / range presets / splitting → `/gsd-ui-phase`.

**Chat multi-platform ripple (leftover from scope item 1)**
- **CH-01:** Add a **`find_platforms`** (list-with-id) read tool mirroring `find_transactions` / the needed `find_accounts`. The agent **resolves the platform and asks the user which one** when unspecified/ambiguous, then includes `platform_id` in the proposal so `propose_add_holding` / `_execute_proposal_payload`'s `add_holding` branch satisfies the new NOT NULL constraint (fixes the STATE-logged chat-write regression). **Also add the analogous `find_accounts` read tool** — it fixes the parallel account-id gap logged in STATE.md "Pending Todos" (would otherwise block chat "delete my BCA account").

### Claude's Discretion
- Specific free **FX API** (must support IDR + historical by-date) — research (RESOLVED below: frankfurter.dev).
- New **`asset_type` enum values** (`cash`, `gold`) exact strings; extends the Phase-5 set (`crypto` / `idx_stock` / `mutual_fund` / `other`).
- **Migration & backfill:** add `holdings.currency` (default `IDR`); existing IDR holdings/avg_costs stay as-entered. Cash-position storage shape.
- Pie/line **placement, range presets, toggle rendering** → `/gsd-ui-phase`.

### Deferred Ideas (OUT OF SCOPE)
- **Live gold spot adapter** — manual per-gram ships now (CG-03); a spot adapter is a later add via the D-08 registry.
- **INVX-02 — automated reksadana NAV feed** — still v2; manual price remains the fallback.
- **FIFO cost basis** — still rejected in favor of average cost (Phase 5 D-02).
- **INVX-01 line chart** — **no longer deferred**; pulled into this phase as scope item 6 (VZ-02).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| INV-01 | User can add, edit, and remove holdings (ticker, quantity, avg cost, purchase date, currency) | Already shipped (Phase 5). This phase extends `currency` to be meaningful (FX-02) and adds `cash`/`gold` as `asset_type` values on the same CRUD path. |
| INV-02 | System fetches current market prices for crypto holdings | Unaffected — `fetch_crypto_price` stays IDR-native (crypto avg-costs entered in USD per CONTEXT still route through the new FX conversion at the valuation layer, not the price adapter). |
| INV-03 | System fetches current market prices for IDX stock holdings | Unaffected — IDX stays IDR-native. |
| INV-04 | User can manually set/override a holding's price | CG-03 reuses this exact path (`apply_set_price`, `source='manual'`) for gold per-gram price. |
| INV-05 | Each displayed price shows its as-of time and a staleness indicator | New `asset_type` values (`cash`, `gold`) need TTL entries in `TTL_BY_ASSET_TYPE` (see Pitfall 1 below) or they silently fall back to `_DEFAULT_TTL`. |
| INV-06 | Investment page shows current portfolio value and per-holding profit/loss | `portfolio_summary()` in `backend/portfolio.py` is the hook point for currency-aware valuation (FX-03) — see Architecture Patterns. |
| INV-07 | Portfolio events (buys/sells) are recorded, enabling correlation queries | `PortfolioEvent` needs a `currency` column (native cost) per FX-04; `recompute_holding_from_events` needs FX-aware cost aggregation when mixed-currency buys exist for one position. |
| CHAT-03 | User can ask spending↔portfolio correlation questions | Unaffected by this phase — no FX/cash/gold changes touch `spending_before_after_purchase`. |
| INVX-01 | Historical portfolio value over time (not just current snapshot) | VZ-02 — `portfolio_value_history` already has the data (D-13/D-14 shipped); this phase adds the read endpoint + chart. |
</phase_requirements>

## Summary

This phase is mostly a **valuation-layer and migration** exercise, not a new-subsystem build — Phase 5's event ledger (D-01/D-02), price-adapter registry (D-08), `price_cache` (D-09), platforms (D-12), and `portfolio_value_history` + scheduler (D-13/D-14) are already live and correct. Verified directly against the running code: `holdings.currency` **already exists** (`String(8)`, default `'IDR'`, NOT NULL) and `asset_type` is **already a free-string column** (`String(32)`, nullable) — not a DB enum. This means FX-02's "arbitrary currency" and CG-01/CG-02's new `asset_type` values (`cash`, `gold`) require **zero schema migration** for those two columns; only a data-default backfill (already-shipped rows are all `'IDR'`, which is correct as-is) and, if the planner wants a `PortfolioEvent.currency` column (recommended, see below), one new migration.

The keystone new build is the **FX adapter**. Live-verified against the running frankfurter.dev API during this research (not just docs): it covers IDR at `/v1/latest` and `/v1/{date}` with no API key, no daily/monthly cap, ECB-sourced, open-source and self-hostable. This reverses the CONTEXT.md worry that "ECB-based sources may lack IDR" — frankfurter **does** carry IDR (ECB publishes an IDR reference rate; frankfurter's own currency list confirms it). `exchangerate.host` has meanwhile become an APILayer-branded product requiring signup/API key — no longer the frictionless option CONTEXT assumed. **Recommendation: frankfurter.dev**, implemented as a new `fx.py` module mirroring `prices.py`'s adapter-registry shape, with a new `fx_rate_cache` table mirroring `price_cache`'s columns but keyed on `(date, base, quote)` for immutability (FX-05).

The second-most load-bearing finding is that **CH-01's bug exists in two places, not one**: `backend/tools.py:propose_add_holding` doesn't even accept a `platform_id` parameter, AND `backend/main.py:_execute_proposal_payload`'s inline `add_holding`/`edit_holding` branches **duplicate** (rather than call) `apply_add_holding`/`apply_edit_holding` from `writes.py` — both omit `platform_id` when constructing the `Holding` row. The planner must fix both call sites or the confirm-path write will still 500/constraint-violate even after `propose_add_holding` is patched.

**Primary recommendation:** Build the FX adapter as `backend/fx.py` (frankfurter.dev, immutable `fx_rate_cache` table), extend `portfolio_summary`/`recompute_holding_from_events` to convert native-currency cost at trade-date rate and current value at today's rate, add `cash`/`gold` to the existing free-string `asset_type` column (no enum migration needed), route both through the existing D-03 override / D-08 registry patterns, fix `propose_add_holding` + the duplicated `_execute_proposal_payload` branch together, and add two new read-only endpoints (`GET /investments/history`, extend `GET /investments/summary` grouping) for the Recharts pie/line UI.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| FX rate fetch + immutable cache | API / Backend | Database / Storage | Mirrors `price_cache`; a new `backend/fx.py` adapter module + `fx_rate_cache` table, no browser/CDN involvement |
| Native-cost → IDR conversion (FX-03) | API / Backend | — | Pure valuation math in `backend/portfolio.py`; must never leak into the frontend (correctness-by-construction) |
| Cash position CRUD | API / Backend | Database / Storage | Rides existing D-03 direct-override REST path (`HoldingCreate`/`apply_add_holding`) — no new endpoint |
| Gold position CRUD + pricing | API / Backend | Database / Storage | Normal ledger holding (D-01/D-02) + manual `price_cache` write (D-11) — no new code pattern, just new `asset_type` value |
| Chat read tools (`find_platforms`, `find_accounts`) | API / Backend | AI query layer | New functions in `backend/tools.py`, registered in `TOOLS` dict; consumed by `backend/query.py` router, not the browser |
| Pie chart (VZ-01) | Browser / Client | API / Backend | Recharts renders client-side from `GET /investments/summary` (already returns platform + asset_type groupable data) — no new endpoint strictly required, only response shape review |
| Line chart (VZ-02) | Browser / Client | API / Backend | New `GET /investments/history` endpoint (Backend) aggregates `portfolio_value_history`; Recharts renders client-side |
| Migration (currency, asset_type values, cash storage) | Database / Storage | API / Backend | Alembic-only for any new column; `asset_type`/`currency` values need no migration (already free-string columns) |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| httpx | >=0.27.0 (already in `backend/requirements.txt`) | HTTP client for the FX adapter | Already the project's sole HTTP client (used by `fetch_crypto_price`); zero new dependency |
| Recharts | ^3.9.2 (already in `ui/package.json`) | Pie chart (VZ-01) + line chart (VZ-02) | Already installed, unused on `/investments` — confirmed via `grep` that no chart code exists yet on the page; this is greenfield UI work using an existing dep |
| Alembic | (already in repo, `alembic/versions/`) | New migration(s) for `fx_rate_cache` table + optional `PortfolioEvent.currency` | Existing, mandatory pattern (FND-01); NOT "Alembic-less" — CONTEXT.md's parenthetical was resolved: the repo has 7 migrations already |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| (none new) | — | — | This phase adds zero new pip/npm packages — every capability is covered by already-installed deps |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| frankfurter.dev | exchangerate.host (APILayer) | Now requires signup + API key (confirmed via WebSearch, 2026); loses the "frictionless free" property CONTEXT.md wanted |
| frankfurter.dev | exchangerate-api.com (open.er-api.com) | Free tier has **no historical rates at all** (paid-only, $9.99/mo+) — fails FX-01's hard historical-lookup requirement outright |
| frankfurter.dev | Bank Indonesia (BI) official rate API | Not investigated this session — would be the "most correct" IDR reference rate but adds a second vendor/format for zero benefit over frankfurter's ECB rate, which is standard practice for retail FX display |

**Installation:** No new packages. If the planner adds a `fx_rate_cache` table, it is a plain Alembic migration — no library install.

**Version verification:** `httpx>=0.27.0` and `recharts ^3.9.2` confirmed present in `backend/requirements.txt` / `ui/package.json` respectively via direct file grep — both are `[VERIFIED: local codebase]`, not registry lookups (no new package to verify against npm/PyPI this phase).

## Package Legitimacy Audit

**No new external packages are introduced by this phase.** The FX capability is built entirely on the existing `httpx` dependency calling a public HTTP API (frankfurter.dev) — this is an API integration, not a package install, so the Package Legitimacy Gate (designed for npm/PyPI/crates installs) does not apply. No `npm install` / `pip install` step exists in this phase's plan.

**Packages removed due to [SLOP] verdict:** none (no packages were proposed).
**Packages flagged as suspicious [SUS]:** none.

## Architecture Patterns

### System Architecture Diagram

```
Browser (/investments page)
   │  fetch("/api/investments/summary")  fetch("/api/investments/history?range=...")
   ▼
Next.js rewrite proxy (unchanged)
   ▼
FastAPI (backend/main.py)
   ├─ GET /investments/summary  ──► portfolio.portfolio_summary()
   │                                   │
   │                                   ├─► for each holding: recompute cost/value in native currency
   │                                   ├─► fx.get_rate(currency, "IDR", as_of=purchase_date)   [cost basis]
   │                                   ├─► fx.get_rate(currency, "IDR", as_of=today)            [current value]
   │                                   └─► price_cache read (existing D-09 path, unchanged)
   │
   ├─ GET /investments/history  ──► portfolio.value_history_series()  [NEW]
   │                                   └─► reads portfolio_value_history (D-13, already populated daily)
   │
   ├─ POST/PUT holdings, portfolio_events  (existing D-03/D-01 write paths)
   │      + cash: asset_type='cash' via D-03 override (no event ledger)
   │      + gold: asset_type='gold' via normal event ledger (D-01/D-02)
   │
   ├─ POST /price-cache (manual override, D-11)  ── reused verbatim for gold per-gram price (CG-03)
   │
   └─ backend/fx.py  [NEW — mirrors backend/prices.py]
          FX_ADAPTERS = {"frankfurter": fetch_frankfurter_rate}
          fetch_frankfurter_rate(base, quote, as_of_date) -> (Decimal, "frankfurter") | None
          get_rate(...) reads fx_rate_cache first (immutable, FX-05); on miss, calls adapter,
          writes ONE row, never overwrites an existing (date, base, quote) row.
                 │
                 ▼
          https://api.frankfurter.dev/v1/{date}?base={base}&symbols=IDR   (no API key)

Agent chat path (unaffected by FX, extended by CH-01):
   backend/query.py:route() → TOOLS["find_platforms"] / TOOLS["find_accounts"]
        → agent resolves platform_id/account_id → propose_add_holding(..., platform_id=X)
        → Proposal row → user confirms → _execute_proposal_payload() → apply_add_holding()
        (BOTH call sites must pass platform_id — see Pitfall 2)
```

### Recommended Project Structure
```
backend/
├── fx.py                  # NEW — FX adapter registry + fx_rate_cache read/write (mirrors prices.py)
├── prices.py               # unchanged — asset price adapters (crypto/idx/manual), extend TTL map for cash/gold
├── portfolio.py             # extend: recompute_holding_from_events, portfolio_summary, + new value_history_series()
├── writes.py                 # extend: apply_add_holding/apply_edit_holding already accept currency/asset_type — verify cash/gold pass through unchanged
├── tools.py                  # extend: find_platforms, find_accounts; fix propose_add_holding to accept+pass platform_id
├── main.py                   # extend: GET /investments/history; fix _execute_proposal_payload add_holding/edit_holding branches (call writes.py helpers instead of duplicating)
├── models.py                  # extend: new FxRateCache model; optionally PortfolioEvent.currency column
alembic/versions/
└── 008_fx_rate_cache.py        # NEW migration (+ optional 009 for portfolio_events.currency)
ui/app/investments/
├── page.tsx                    # extend: render pie + line chart components (layout → /gsd-ui-phase)
├── AllocationPieChart.tsx        # NEW (placement/interactions deferred to UI phase)
└── ValueHistoryChart.tsx         # NEW (placement/interactions deferred to UI phase)
```

### Pattern 1: FX Adapter Registry (mirrors D-08)
**What:** A `dict[str, Callable]` registry exactly like `PRICE_ADAPTERS`, keyed by provider name (only one entry needed now: `"frankfurter"`), returning `(Decimal, source) | None` and never raising.
**When to use:** Every FX conversion in the valuation path goes through one `get_rate(base, quote, as_of)` function — never call the adapter directly from `portfolio.py`.
**Example:**
```python
# Source: backend/prices.py (existing pattern, verified in this repo)
FX_ADAPTERS: dict[str, Callable[[str, str, date], tuple[Decimal, str] | None]] = {
    "frankfurter": fetch_frankfurter_rate,
}

def fetch_frankfurter_rate(base: str, quote: str, as_of: date) -> tuple[Decimal, str] | None:
    """https://api.frankfurter.dev/v1/{date}?base={base}&symbols={quote} — no API key.
    Verified live 2026-07-12: api.frankfurter.dev/v1/2024-01-15?base=USD&symbols=IDR
    -> {"amount":1.0,"base":"USD","date":"2024-01-15","rates":{"IDR":15561}}
    Returns None on ANY failure (HTTP error, missing key, 404 for pre-ECB dates) —
    NEVER raises, mirroring fetch_crypto_price's contract.
    """
    import httpx
    if base.upper() == quote.upper():
        return Decimal("1"), "identity"
    try:
        resp = httpx.get(
            f"https://api.frankfurter.dev/v1/{as_of.isoformat()}",
            params={"base": base.upper(), "symbols": quote.upper()},
            timeout=10.0,
        )
        resp.raise_for_status()
        rate = resp.json().get("rates", {}).get(quote.upper())
        if rate is None:
            return None
        return Decimal(str(rate)), "frankfurter"
    except (httpx.HTTPError, KeyError, ValueError):
        return None
```

### Pattern 2: Immutable FX Rate Cache (FX-05)
**What:** A `fx_rate_cache` table mirroring `price_cache`'s shape but keyed uniquely on `(rate_date, base_currency, quote_currency)` — INSERT-only, never UPDATE, so a re-fetch for an already-cached date always returns the stored value.
**When to use:** Every historical-at-purchase conversion (FX-03) reads this cache first; only a genuine cache miss calls the adapter.
**Example:**
```python
# Source: mirrors backend/models.py PriceCache shape (this repo)
class FxRateCache(Base):
    __tablename__ = "fx_rate_cache"
    __table_args__ = (
        UniqueConstraint("rate_date", "base_currency", "quote_currency",
                          name="uq_fx_rate_date_pair"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    rate_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    base_currency: Mapped[str] = mapped_column(String(8), nullable=False)
    quote_currency: Mapped[str] = mapped_column(String(8), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()", nullable=False)
```
```python
def get_rate(db: Session, base: str, quote: str, as_of: date) -> Decimal | None:
    """Cache-first, immutable-write (FX-05). Never overwrites an existing row."""
    if base.upper() == quote.upper():
        return Decimal("1")
    existing = db.scalars(
        select(FxRateCache).where(
            FxRateCache.rate_date == as_of,
            FxRateCache.base_currency == base.upper(),
            FxRateCache.quote_currency == quote.upper(),
        )
    ).first()
    if existing is not None:
        return existing.rate
    result = fetch_frankfurter_rate(base, quote, as_of)
    if result is None:
        return None  # caller must handle: valuation shows "rate unavailable", never fabricates
    rate, source = result
    db.add(FxRateCache(rate_date=as_of, base_currency=base.upper(),
                        quote_currency=quote.upper(), rate=rate, source=source))
    return rate
```

### Pattern 3: USDT ≈ 1:1 USD (FX-02 special case)
**What:** CONTEXT.md specifies USDT treated as ≈1:1 USD — this is a **hardcoded identity mapping inside the FX layer**, not a call to frankfurter (which doesn't carry crypto stablecoins).
**When to use:** Before calling `get_rate`, normalize `USDT` → `USD` as the FX base currency (the ledger still stores `currency="USDT"` for display, but the conversion path treats it as `USD`).
**Example:**
```python
_FX_ALIASES = {"USDT": "USD"}  # ponytail: one entry now; extend the dict if more stablecoins appear
def _normalize_fx_base(currency: str) -> str:
    return _FX_ALIASES.get(currency.upper(), currency.upper())
```

### Anti-Patterns to Avoid
- **Duplicating the confirm-path write logic (existing bug in this repo):** `backend/main.py:_execute_proposal_payload` reimplements `apply_add_holding`/`apply_edit_holding` inline instead of calling `backend/writes.py`'s functions. This is a **pre-existing divergence** (ARCHITECTURE.md already flags "Anti-patterns / Notable Deviations" for similar patterns) that CH-01 must not extend — fix by having `_execute_proposal_payload` call the `writes.py` helpers directly instead of patching both copies.
- **Per-event FX-rate column:** CONTEXT.md (FX-04) explicitly rejects this — do not add `portfolio_events.fx_rate`. Only `portfolio_events.currency` (native cost currency) if the planner decides mixed-currency buys on one position need per-event currency (see Open Questions).
- **Converting at read-time without caching:** Every valuation read (e.g. loading `/investments` twice in one day) must hit `fx_rate_cache`, not frankfurter directly — this is FX-05's entire point (stability + rate-limit friendliness).
- **Silently defaulting missing FX rates to 1.0:** If `get_rate()` returns `None` (adapter failure + cache miss), the valuation math MUST surface "rate unavailable" (mirroring `unrealized_pnl`'s existing `None`-propagation pattern for missing prices) — never fabricate a 1:1 rate or silently skip the FX conversion (correctness-by-construction, CLAUDE.md).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| FX rate fetching | A custom scraper or spreadsheet-based rate table | frankfurter.dev's existing REST API | Free, ECB-sourced, no key, ~30-year history, already verified live against IDR in this session |
| FX rate caching/staleness | A bespoke TTL/staleness system for FX | Reuse `price_cache`'s exact shape (immutable insert-only, mirrored in `fx_rate_cache`) | The project already solved "one read path for current value" for prices — FX needs the identical shape, not a new design |
| Cash balance tracking | A new "cash_accounts" table or bespoke balance model | The existing D-03 direct holding-override path (`asset_type='cash'`) | CONTEXT.md (CG-01) explicitly decided this; it also means cash automatically participates in `portfolio_summary`/pie/line charts for free |
| Gold position math | Custom weight/purity conversion logic | The existing average-cost ledger (D-01/D-02) with `quantity`=grams, `price`=per-gram | Gold is "just another `asset_type`" — no new accounting logic, only a new manual-price write path reusing D-11 |

**Key insight:** Every non-FX capability in this phase (cash, gold, pie/line data) is a **new `asset_type` value flowing through existing machinery**, not new machinery. The only genuinely new subsystem is the FX adapter + its cache — and even that is a structural clone of the already-shipped, already-tested price-adapter registry.

## Runtime State Inventory

> Not a rename/refactor/migration-of-existing-data phase in the traditional sense, but this phase changes the *meaning* of two existing columns (`holdings.currency`, `holdings.asset_type`) and adds new valuation math that reads them — included for completeness since existing data must remain valid under the new interpretation.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | All existing `holdings.currency` values are `'IDR'` (server default, Phase 5 shipped IDR-only, D-07). All existing `portfolio_events` have no currency concept (implicitly IDR). | No data migration needed — `currency='IDR'` self-converts at rate 1.0 for any FX-aware code path (base==quote short-circuit in Pattern 2). Verify this short-circuit is unconditional so IDR-only historical holdings incur zero behavior change. |
| Live service config | None — no external service holds config referencing "currency" or "asset_type" outside the DB. | None. |
| OS-registered state | None — the daily snapshot scheduler (D-14, APScheduler in-process) needs no reconfiguration; it already calls `refresh_all_prices`/`snapshot_all_holdings`, which will pick up new `asset_type` values automatically once `TTL_BY_ASSET_TYPE`/`PRICE_ADAPTERS` are extended. | Extend `TTL_BY_ASSET_TYPE` and `PRICE_ADAPTERS` dicts for `cash`/`gold` (see Pitfall 1) — a code edit, not a data migration. |
| Secrets/env vars | frankfurter.dev requires **no API key** — no new secret to provision. | None. |
| Build artifacts | None — no new pip/npm package installed this phase. | None. |

**Nothing found in "stored data" that requires an UPDATE statement** — verified via direct model read that `holdings.currency` already defaults to `'IDR'` for every row (Phase 5's D-07 IDR-only stance means no row was ever anything else).

## Common Pitfalls

### Pitfall 1: New `asset_type` values silently bypass staleness/price routing
**What goes wrong:** `cash` and `gold` holdings get `is_stale()` always returning `True` (falls to `_DEFAULT_TTL` = 7 days, which may be wrong for cash — its "price" is really the FX rate, which should probably be treated as fresh/always-current) and `refresh_all_prices` routes them to `fetch_manual_price` (via the `PRICE_ADAPTERS.get(h.asset_type or "other", fetch_manual_price)` fallback) which is actually correct for gold (CG-03: manual) but semantically odd for cash (cash has no "price" — its value is FX-rate-driven, not `price_cache`-driven).
**Why it happens:** `TTL_BY_ASSET_TYPE` and `PRICE_ADAPTERS` are both keyed dicts that silently fall back rather than erroring on an unknown key — by design (never breaks the batch), but it means a forgotten dict entry produces plausible-looking-but-wrong behavior rather than a loud failure.
**How to avoid:** Explicitly decide and add `cash`/`gold` entries (or explicit exclusions) to both dicts during planning, don't rely on the fallback. For `cash`, the "price" concept may not apply at all — the planner should decide whether cash holdings even attempt a `price_cache` read, or whether `portfolio_summary` special-cases `asset_type == 'cash'` to skip price lookup and instead compute value as `quantity × fx_rate(currency, 'IDR', today)` directly.
**Warning signs:** A cash holding showing a "stale price" badge, or a gold holding's staleness badge using the wrong TTL window (gold spot moves slowly — day-scale TTL like `mutual_fund`'s 7 days is reasonable, but confirm during planning rather than defaulting silently).

### Pitfall 2: The CH-01 fix must land in TWO call sites, not one
**What goes wrong:** Patching only `backend/tools.py:propose_add_holding` (adding a `platform_id` param) fixes the proposal's `after` dict, but `backend/main.py:_execute_proposal_payload`'s `add_holding`/`edit_holding` branches construct `Holding(...)` **inline**, independently of `writes.py:apply_add_holding` — they never read `after.get("platform_id")` at all in the reviewed code. Even with a correct proposal payload, the confirm-time write still omits `platform_id` and hits the NOT NULL constraint.
**Why it happens:** This is a pre-existing code duplication (not introduced by this phase) — `_execute_proposal_payload`'s branches were written before `writes.py:apply_add_holding`/`apply_edit_holding` existed (or diverged since), so they never picked up the D-03 `platform_id`/`coingecko_id` fields that `writes.py`'s versions already handle correctly.
**How to avoid:** During planning, task the `_execute_proposal_payload` branches to **call** `apply_add_holding(db, after)` / `apply_edit_holding(db, row["id"], after, before)` from `writes.py` instead of duplicating the field-by-field construction — this is a strict simplification (deletes ~35 lines) and automatically inherits `platform_id`/`coingecko_id` handling, fixing CH-01 and removing a maintenance hazard in one change.
**Warning signs:** A test that mocks `propose_add_holding` + confirms it still 500s with "null value in column platform_id violates not-null constraint" even after `tools.py` looks fixed.

### Pitfall 3: FX rate for a weekend/holiday date returns 404, not a stale-but-valid rate
**What goes wrong:** frankfurter.dev (ECB-sourced) only publishes rates on ECB business days — a `purchase_date` falling on a weekend or a bank holiday returns no data for that exact date (verified: pre-1999 dates 404; ECB doesn't publish on non-trading days either). Naively treating "no rate for this date" as "FX conversion failed" would make weekend purchases show `unrealized_pnl = None` forever.
**Why it happens:** FX-04 stores no per-event rate — the historical rate is always re-derived from the date, so a "gap date" is a real, recurring case (any trade made on a Saturday).
**How to avoid:** frankfurter's own historical semantics: querying a non-trading date typically returns the **most recent prior trading day's rate** for range queries, but the single-date endpoint (`/v1/{date}`) may 404 or return an empty `rates` object depending on how far back the date is. The planner must verify this exact behavior for a few representative weekend dates during implementation and decide the fallback (most likely: walk backward day-by-day, capped at N days, until a rate is found — mirroring how a "last known price" fallback already works for `price_cache`).
**Warning signs:** A test using a Saturday `purchase_date` produces `unrealized_pnl: null` where a weekday date of the same week produces a real number.

### Pitfall 4: Mixed-currency buys on ONE position break simple average-cost math
**What goes wrong:** `recompute_holding_from_events` (D-02) currently sums `total_cost = Σ(price × quantity)` in a single currency (IDR). If a user buys the same ticker on the same platform in two different currencies over time (unusual but not prevented by the schema), summing raw `price` values across currencies produces a nonsensical blended cost basis.
**Why it happens:** FX-04 puts `currency` on the event (if the planner adds `portfolio_events.currency`), but the existing average-cost accumulator has no currency-awareness — it was written under D-07's IDR-only assumption.
**How to avoid:** Either (a) convert every event's `price × quantity` to IDR at that event's trade-date rate *before* accumulating into `total_cost` (making `avg_cost` an IDR-blended average — matches FX-03's "historical-at-purchase" spirit and is the recommended approach), or (b) constrain a single (ticker, platform_id) position to one currency at write-time (simpler, but a product restriction CONTEXT.md doesn't explicitly rule on). Flag this as a planning decision — see Open Questions.
**Warning signs:** `avg_cost` for a position that has both a USD-denominated and IDR-denominated buy event produces an obviously-wrong number (e.g. summing `50000 IDR + 200 USD` as `50200`).

### Pitfall 5: SSRF discipline must extend to the FX adapter
**What goes wrong:** The existing `fetch_crypto_price`/`fetch_idx_price` adapters have explicit SSRF mitigations (fixed ticker map, alnum validation) documented in `prices.py`'s module docstring (T-05-04-SSRF). A naive FX adapter that interpolates a user-supplied `currency` string directly into the frankfurter URL path/params without validation reopens this exact class of risk if `holdings.currency` (FX-02's "arbitrary currency") is ever attacker-influenced (low risk in a single-user app, but the project's own convention demands it).
**Why it happens:** FX-02 explicitly wants "arbitrary per-holding currency" (not a fixed enum like crypto tickers) — this is in tension with the SSRF-mitigation pattern used elsewhere.
**How to avoid:** Validate `currency` as a 3-letter ISO-4217-shaped code (`^[A-Z]{3,4}$`, allowing USDT) before interpolating into the frankfurter URL — frankfurter itself will 404/error on a bogus code, but validating first avoids sending arbitrary strings to an external host at all. This is a cheap, one-line regex guard, not a fixed lookup table (unlike crypto's `TICKER_TO_COINGECKO_ID`), since currency codes are a much smaller, well-known keyspace and frankfurter's `/v1/currencies` endpoint could even be used to validate against the live supported-currency list at startup if the planner wants belt-and-suspenders (optional, not required).
**Warning signs:** None yet — this is a preventive pitfall, not an observed bug.

## Code Examples

Verified patterns from official sources and live API calls made during this research session:

### Frankfurter historical rate — live-verified request/response shape
```
GET https://api.frankfurter.dev/v1/2024-01-15?base=USD&symbols=IDR
-> {"amount":1.0,"base":"USD","date":"2024-01-15","rates":{"IDR":15561}}
```
```
GET https://api.frankfurter.dev/v1/latest?base=USD&symbols=IDR
-> {"amount":1.0,"base":"USD","date":"2026-07-10","rates":{"IDR":18077}}
```
```
GET https://api.frankfurter.dev/v1/1990-01-01?base=USD&symbols=IDR
-> HTTP 404  (pre-ECB-era date, expected — ECB history starts 1999)
```
Source: live `curl` calls made 2026-07-12 during this research session against `api.frankfurter.dev` (public, no key). `[VERIFIED: live API call]`

### Existing D-08 price adapter registry (pattern to mirror for FX)
```python
# Source: backend/prices.py (this repo, verified via Read)
PRICE_ADAPTERS: dict[str, Callable[[str], tuple[Decimal, str] | None]] = {
    "crypto": fetch_crypto_price,
    "idx_stock": fetch_idx_price,
    "mutual_fund": fetch_manual_price,
    "other": fetch_manual_price,
}
```

### Existing D-03 override write path (cash rides this unchanged)
```python
# Source: backend/writes.py:264-285 (this repo, verified via Read)
def apply_add_holding(db: Session, after: dict) -> Holding:
    holding = Holding(
        ticker=after["ticker"],
        quantity=Decimal(str(after["quantity"])),
        avg_cost=Decimal(str(after["avg_cost"])),
        purchase_date=date.fromisoformat(after["purchase_date"]) if after.get("purchase_date") else None,
        currency=after.get("currency", "IDR"),
        asset_type=after.get("asset_type"),
        platform_id=after.get("platform_id"),
        coingecko_id=after.get("coingecko_id"),
    )
    db.add(holding)
    db.flush()
    db.add(AuditLog(entity="holding", entity_id=holding.id, operation="add", before=None, after=after))
    return holding
```
Note: this function ALREADY correctly passes `platform_id` — it is the direct-REST path (POST /investments/holdings). Only the chat propose→confirm path (Pitfall 2) is broken.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Everything IDR, no FX (D-07, Phase 5) | Arbitrary currency, historical-at-purchase FX conversion (FX-01…FX-05) | This phase (2026-07-12 discussion) | Every valuation read (`portfolio_summary`, future snapshot writer) gains an FX-conversion step; `PortfolioEvent`/`Holding` currency becomes load-bearing rather than vestigial |
| `exchangerate.host` as a "free, no-key" option (CONTEXT.md's assumption) | `exchangerate.host` is now an APILayer-gated product requiring signup | Observed during this research (2026-07-12 WebSearch) | The CONTEXT.md candidate list is partially stale — frankfurter.dev is the correct pick, not a fallback |

**Deprecated/outdated:**
- CONTEXT.md's framing "ECB-based sources may lack IDR" — live-verified false for frankfurter.dev; ECB does publish an IDR reference rate and frankfurter's `/v1/currencies` list includes it.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | frankfurter.dev's rate-limiting is "generous enough" for a single-user app's daily snapshot job + occasional page loads (no documented hard numeric cap found, only "no monthly/daily caps" language from secondary sources) | Standard Stack / Architecture Patterns | If frankfurter silently throttles under sustained load, the daily snapshot job (which calls the adapter once per distinct currency per day, likely 1-3 calls) would rarely be affected — low risk, but flagging since no official numeric rate-limit was found in an authoritative source, only WebSearch summaries |
| A2 | frankfurter.dev's non-trading-date behavior (weekend/holiday `purchase_date`) — whether `/v1/{date}` 404s or silently returns the prior business day's rate — was not empirically tested for a weekend date in this session (only a pre-1999 date was tested for the 404 case) | Common Pitfalls (Pitfall 3) | If it 404s (rather than falling back), the planner's fallback-walk-backward logic is mandatory, not optional, for correctness on any weekend trade date |
| A3 | Cash holdings' "value" computation bypassing `price_cache` entirely (using FX rate directly instead) is the right design — CONTEXT.md doesn't explicitly say this, it's inferred from CG-01's "IDR value = amount × FX-to-IDR" wording | Common Pitfalls (Pitfall 1) | If wrong, cash holdings might need a synthetic `price_cache` row instead (price = FX rate), which is a different code path than proposed |
| A4 | Mixed-currency buys on a single (ticker, platform_id) position are an edge case the planner should explicitly decide on, not something CONTEXT.md rules out or permits definitively | Common Pitfalls (Pitfall 4) | If the planner assumes "one currency per position always" without stating it, a real user mixing currencies on one ticker would get silently wrong average cost |

**If this table is empty:** N/A — see entries above; all are flagged for planner/discuss-phase confirmation, none block starting the plan.

## Open Questions

1. **Does `portfolio_events` need its own `currency` column, or does the event inherit the holding's `currency`?**
   - What we know: FX-04 says "store only native cost + currency on the event" — this reads as `portfolio_events.currency` being a new column, not reuse of `holdings.currency`. But `Holding.currency` already exists and could be treated as authoritative for the (ticker, platform_id) position if the planner decides one position = one currency always.
   - What's unclear: Whether the phase should allow mixed-currency buys on the same position (see Pitfall 4) — this determines whether `portfolio_events.currency` is a new migration or whether the existing `holdings.currency` suffices.
   - Recommendation: Add `portfolio_events.currency` (new migration, nullable defaulting to the position's current `holdings.currency` at write time) for forward-compatibility and because FX-04's wording explicitly says "on the event" — but let the planner make the final call, since it's a genuine scope/complexity tradeoff (see Pitfall 4).

2. **Should cash holdings skip `price_cache` entirely, or get a synthetic price_cache row?**
   - What we know: CG-01 says cash value = `amount × FX-to-IDR`. The existing `portfolio_summary` reads `_latest_price(db, ticker)` unconditionally for every holding.
   - What's unclear: Whether to special-case `asset_type == 'cash'` in `portfolio_summary` (skip price lookup, compute value directly from FX) or to write a synthetic `price_cache` row per cash "ticker" (e.g. treat the currency itself as the "ticker", price = FX rate) so the existing code path needs zero branching.
   - Recommendation: Special-case in `portfolio_summary` — cleaner separation of concerns (cash isn't really "priced", it's "converted") and avoids polluting `price_cache` with FX-rate-as-price rows that would confuse the existing crypto/IDX staleness semantics.

3. **What is the FX-01 provider fallback if frankfurter.dev has an outage?**
   - What we know: Every adapter in this codebase (`fetch_crypto_price`, `fetch_idx_price`) has a documented "never raises, returns None, caller falls back to cache" contract (D-08's core guarantee).
   - What's unclear: For FX specifically, a cache miss + adapter failure means "no rate available for this date" — should the valuation layer walk backward to the nearest cached/fetchable date, or surface `None`/"unavailable" immediately? The existing `unrealized_pnl` pattern already tolerates `None` gracefully, so surfacing `None` is consistent — but a walk-backward fallback would be more user-friendly for the "weekend trade" case (Pitfall 3).
   - Recommendation: Implement the null-propagation path first (consistent, simple, matches existing conventions); add the walk-backward fallback only if Pitfall 3's weekend-date testing shows it's actually needed (frankfurter may already return the prior business day for range queries — verify empirically during implementation before adding extra logic).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Internet egress to api.frankfurter.dev | FX-01 adapter | ✓ (verified via live `curl` during this research session) | n/a (public REST API) | On outage: cached rates still serve any already-fetched date; new dates surface "rate unavailable" (see Open Question 3) |
| PostgreSQL (existing) | New `fx_rate_cache` table | ✓ (already running per STATE.md — 150 tests green, live DB on :5434) | 16-alpine | — |
| httpx (existing dependency) | FX adapter HTTP calls | ✓ (`backend/requirements.txt:13`) | >=0.27.0 | — |
| Recharts (existing dependency) | VZ-01/VZ-02 charts | ✓ (`ui/package.json:15`) | ^3.9.2 | — |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none — everything required is already present in the repo or is a public, keyless API confirmed reachable.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest >=8.0.0 (existing, `backend/tests/`) |
| Config file | none dedicated — pytest defaults; existing suite has 150 tests per STATE.md |
| Quick run command | `cd backend && python -m pytest tests/test_prices.py tests/test_portfolio.py -x` |
| Full suite command | `cd backend && python -m pytest` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| FX-01/FX-05 | FX adapter returns correct rate; cache is immutable (same date/pair never re-fetched) | unit (mocked httpx, mirrors `test_fetch_crypto_price`) | `pytest tests/test_fx.py -x` | ❌ Wave 0 — new file, mirror `test_prices.py`'s mock pattern |
| FX-03 | Cost basis converts at trade-date rate; current value at today's rate; unrealized P&L includes FX movement | unit | `pytest tests/test_portfolio.py::test_fx_aware_pnl -x` | ❌ Wave 0 — extend existing `test_portfolio.py` |
| FX-04 | No `portfolio_events.fx_rate` column exists; rate is always re-derived by date | schema/unit assertion | `pytest tests/test_portfolio.py -x` | ❌ Wave 0 |
| CG-01 | Cash holding (`asset_type='cash'`) values as `amount × fx_rate`, no cost basis P&L except FX movement | unit | `pytest tests/test_portfolio.py::test_cash_valuation -x` | ❌ Wave 0 |
| CG-02 | Gold holding full ledger P&L (grams × per-gram price) — reuses D-01/D-02 math, only needs an `asset_type='gold'` fixture | unit | `pytest tests/test_portfolio.py -x` (extend existing average-cost tests with a gold fixture) | ⚠️ Partial — existing average-cost tests cover the math; add one gold-specific fixture |
| CG-03 | Manual gold price write via `apply_set_price(..., source='manual')` | unit (already covered pattern) | `pytest tests/test_write_tools.py -x` | ✅ Existing test file covers `apply_set_price`; add a gold-ticker case |
| CH-01 | `propose_add_holding` includes `platform_id`; confirm-path write succeeds; `find_platforms`/`find_accounts` resolve name→id | integration (existing pattern: `test_proposals.py`) | `pytest tests/test_proposals.py tests/test_tools.py -x` | ⚠️ Partial — extend existing files, don't create new ones |
| INVX-01/VZ-02 | `GET /investments/history` returns correct aggregation from `portfolio_value_history` | integration | `pytest tests/test_portfolio.py -x` (new endpoint test) | ❌ Wave 0 — new endpoint needs a new test function |
| VZ-01 | `GET /investments/summary` groups correctly by asset_type (new grouping alongside existing platform grouping) | unit | `pytest tests/test_portfolio.py -x` | ⚠️ Partial — extend `portfolio_summary`'s existing test coverage |

### Sampling Rate
- **Per task commit:** `cd backend && python -m pytest tests/test_fx.py tests/test_portfolio.py tests/test_tools.py tests/test_proposals.py -x` (targeted, <30s)
- **Per wave merge:** `cd backend && python -m pytest` (full 150+ test suite)
- **Phase gate:** Full suite green before `/gsd-verify-work`; additionally a live-DB smoke test for at least one real frankfurter.dev call (not mocked) to confirm the adapter works against the real vendor, mirroring how Phase 5 live-verified yfinance/CoinGecko.

### Wave 0 Gaps
- [ ] `backend/tests/test_fx.py` — new file, mirrors `test_prices.py`'s mocked-httpx pattern for `fetch_frankfurter_rate` (success, unknown currency, HTTP error, weekend-date/404 case)
- [ ] `backend/tests/conftest.py` — verify existing fixtures support a `FxRateCache` row factory (check if a generic seed helper exists or needs adding)
- [ ] Extend `backend/tests/test_portfolio.py` — FX-aware `recompute_holding_from_events`/`portfolio_summary` cases (cash, gold, mixed-currency-position if Pitfall 4 is in scope)
- [ ] Extend `backend/tests/test_tools.py` — `find_platforms`, `find_accounts` new read tools
- [ ] Extend `backend/tests/test_proposals.py` — `propose_add_holding` with `platform_id`; confirm-path integration test proving the FIX for both call sites (Pitfall 2) — this test should fail against the current code and pass after the fix, proving the regression is closed

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Single-user app, no auth system (existing project stance) |
| V3 Session Management | no | N/A |
| V4 Access Control | yes | Existing `require_api_key` dependency on all write routes (FND-02) — new endpoints (`GET /investments/history`) should be open-read like `GET /investments/summary`; any new write route (none anticipated) must carry `Depends(require_api_key)` |
| V5 Input Validation | yes | Pydantic v2 schemas (existing `HoldingCreate`/`HoldingUpdate` pattern); new `currency` values must be validated as ISO-4217-shaped codes (Pitfall 5) before being sent to the FX adapter |
| V6 Cryptography | no | No new crypto surface — no secrets, no API keys for frankfurter.dev |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SSRF via unvalidated currency code interpolated into FX vendor URL | Tampering | Validate `currency`/`base`/`quote` against a `^[A-Z]{3,4}$` regex (or the live frankfurter `/v1/currencies` list) before building the request URL — mirrors the existing crypto/IDX ticker validation pattern (Pitfall 5) |
| Confident-wrong FX-converted P&L number (money-app correctness mandate) | Tampering / Repudiation (data integrity) | Never let a failed FX lookup silently default to rate=1.0 or skip conversion — propagate `None`/"unavailable" exactly like the existing `unrealized_pnl` None-propagation for missing prices (Anti-Patterns section) |
| Chat write-path constraint violation (CH-01's existing regression) | Denial of Service (500 on a legitimate user action) | Fix both `propose_add_holding` and `_execute_proposal_payload`'s duplicated branch to pass `platform_id` (Pitfall 2) — an unhandled `IntegrityError` on the confirm endpoint is itself a minor DoS on that feature |

## Sources

### Primary (HIGH confidence)
- Live HTTP calls to `api.frankfurter.dev/v1/latest`, `/v1/2024-01-15`, `/v1/1990-01-01` (made directly during this research session, 2026-07-12) — confirms IDR coverage, historical-by-date lookup, no-API-key requirement, and pre-1999 404 boundary. `[VERIFIED: live API call]`
- Direct `Read`/`grep` of `backend/models.py`, `backend/prices.py`, `backend/portfolio.py`, `backend/writes.py`, `backend/tools.py`, `backend/main.py`, `backend/schemas.py`, `backend/scheduler.py`, `alembic/versions/007_value_history_per_platform.py`, `ui/package.json`, `backend/requirements.txt` (this repo, 2026-07-12). `[VERIFIED: local codebase]`

### Secondary (MEDIUM confidence)
- frankfurter.dev official docs (frankfurter.dev, frankfurter.dev/v1/) — currency list, rate-limit description, self-hosting via Docker. `[CITED: frankfurter.dev]`
- exchangerate-api.com free-tier docs (exchangerate-api.com/docs/free) — confirms no historical rates on the free/open endpoint. `[CITED: exchangerate-api.com]`

### Tertiary (LOW confidence)
- WebSearch summaries characterizing exchangerate.host's current APILayer-gated signup requirement (not independently confirmed via a direct HTTP call in this session, unlike frankfurter). `[ASSUMED — recommend planner spot-check exchangerate.host/pricing directly if considering it as a second option]`

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages, all existing deps directly verified in repo files; FX provider choice backed by live HTTP calls, not just docs
- Architecture: HIGH — every pattern (FX registry, immutable cache, D-03 override reuse) is a direct structural mirror of already-shipped, already-tested code read directly from this repo
- Pitfalls: HIGH for Pitfall 1/2/5 (all directly observed in the actual source code during this session); MEDIUM for Pitfall 3/4 (logically derived from FX-03/FX-04's stated semantics, not yet empirically tested against a live weekend-date frankfurter call or a real mixed-currency fixture)

**Research date:** 2026-07-12
**Valid until:** 2026-08-11 (30 days — stable domain: FX API behavior, migration patterns, and the codebase's own architecture change slowly; frankfurter.dev's free-tier terms could in principle change, so re-verify if this research is used after that date)
