# Phase 5: Investment Subsystem - Research

**Researched:** 2026-07-06
**Domain:** Multi-source price fetching (crypto/IDX/manual), average-cost portfolio accounting, APScheduler-in-FastAPI background jobs, Alembic migration extension
**Confidence:** HIGH (in-repo verification) / MEDIUM (external APIs — yfinance IDX coverage, CoinGecko rate limits)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** `portfolio_events` is the **source of truth** for trades. `holdings.quantity` and `holdings.avg_cost` are **recomputed from the event ledger** — the user records buy/sell/dividend events; the position falls out of them. `event_type ∈ {buy, sell, dividend}`.
- **D-02:** Cost basis = **average cost**. `avg_cost = total cost of open qty / open qty`; a sell realizes `(sell_price − avg_cost) × sold_qty` and leaves `avg_cost` unchanged. **Dividends are supported this phase** and fold into realized return. (FIFO explicitly rejected.)
- **D-03:** **Direct holding-override escape hatch.** A **direct manual edit/delete of the holding row** is allowed (e.g. seed an opening position, or force-correct). Overrides are **audit-logged** like every other write.
- **D-04:** INV-01 "add/edit/remove holdings" means: normally record/edit/delete the underlying **events** (position recomputes); a holding whose net quantity reaches zero drops off the active list. D-03 override is the exception path.
- **D-05:** Ship a **realized + unrealized P&L snapshot** now. Unrealized = `(current price − avg_cost) × open qty`. Realized = from sell events (average-cost) + dividends. Also show **total portfolio value** with an **"as of" timestamp** (INV-06).
- **D-06:** The **historical time-series line chart** is **deferred to v2 (INVX-01)**. Only its **data collector** ships now (D-13/D-14).
- **D-07:** **Everything in IDR, no FX.** Fetch all prices directly in IDR (CoinGecko `vs_currency=idr`; yfinance `.JK` is native IDR). User enters buy/sell prices and `avg_cost` in IDR. `holdings.currency` stays IDR.
- **D-08:** Price **source is routed by `asset_type`**: crypto→CoinGecko, idx_stock→yfinance (`.JK`, best-effort with fallback), mutual_fund/other→manual. The Phase-3 global `price_data_source` setting becomes a **fallback/default**, not the per-holding selector. Implement as a **pluggable adapter registry** (mirror the `TOOLS` registry pattern); adapter-registry shape is Claude's discretion.
- **D-09:** Live prices are fetched **lazily on `/investments` load** for any ticker whose cached price is older than its TTL, **plus a manual "Refresh prices" button** that force-fetches all. All prices (fetched *and* manual) flow through the single `price_cache` table.
- **D-10:** **Per-asset-type staleness TTL defaults** (crypto ~minutes, IDX ~1 day / intraday during market hours, mutual_fund/manual flagged stale after N days). Exact numbers are Claude's discretion / research-informed. Each price shows an **"as of [time]" badge** and a **visual stale indicator** once older than its TTL (INV-05).
- **D-11:** **Manual price override (INV-04)** writes `price_cache` with `source='manual'` and is immediately reflected in P&L. A manual price is treated as the **newest value and is REPLACED by the next successful live fetch** — persists naturally only for manual-only instruments; for crypto/IDX it is a temporary correction.
- **D-12:** **Managed `platforms` entity** — a new table with its own CRUD (mirrors the Phase-4 account manager); `holdings.platform_id` references it. The Investments page groups holdings **by platform** with per-platform subtotals. Purely organizational — **no effect on P&L math**.
- **D-13:** New **`portfolio_value_history`** table storing **one row per holding per day**: `snapshot_date`, holding/ticker, `quantity`, `market_value`, `cost_basis` (→ unrealized), `currency=IDR`. History **cannot be backfilled** — collection starts this phase.
- **D-14:** Snapshots are written by an **in-process APScheduler** started in the **FastAPI app lifespan** (no new container, no host cron). Runs **daily** to guarantee ≥1 data point/day, refreshing prices before snapshotting. This is the stack's **first always-on background component**. Exact time-of-day is Claude's discretion.
- **D-15:** Add **new read tool(s) to `backend/tools.py`** (LLM never emits SQL). For "since I bought X, how has my `<category>` spending changed?": resolve the pivot date as the **earliest buy event for that ticker in `portfolio_events`**, then compare category spending in the **equal-length window after vs before** that date. Return before/after totals + the delta.
- **D-16:** Holdings, events, and platform CRUD use **direct auth-protected REST + the shared `backend/writes.py` helpers + `audit_log` + `Decimal`** (the Phase-4 D-01/D-02 pattern) — button click is the confirmation; propose→confirm is NOT used on the direct UI path. (Chat agent may still *propose* holding writes via propose→confirm.)
- **D-17:** **Migration needed.** New tables `platforms`, `portfolio_value_history`; new column `holdings.platform_id` (FK). `holdings`, `portfolio_events`, `price_cache` already exist (Phase 1) and are reused as-is (`event_type` already a string that now carries `buy|sell|dividend`).

### Claude's Discretion

- Exact per-asset-type TTL numbers; price-adapter registry shape; `asset_type` enum exact values (e.g. `crypto` / `idx_stock` / `mutual_fund` / `other`); dividend/realized-return presentation; snapshot scheduler time-of-day; how per-platform subtotals render; Investments page visual layout (→ `/gsd-ui-phase`).

### Deferred Ideas (OUT OF SCOPE)

- **INVX-01 — historical portfolio-value / P&L time-series line chart** (v2). Its **data collector ships now** (D-13/D-14); only the chart UI is deferred.
- **INVX-02 — automated reksadana NAV feed** (v2). Manual price is the fallback this phase.
- **Multi-currency / FX normalization** — parked project-wide; everything IDR (D-07).
- **FIFO cost basis** — rejected in favor of average cost (D-02).
- **Write tools over MCP to external clients** — Phase 6 exposes read-only tools.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| INV-01 | User can add, edit, and remove holdings (ticker, quantity, avg cost, purchase date, currency) | Event-ledger recompute algorithm (see Code Examples); direct REST + `writes.py` pattern already established (Phase 4) |
| INV-02 | System fetches current market prices for crypto holdings | CoinGecko `/simple/price?vs_currency=idr` — verified endpoint shape and free-tier limits |
| INV-03 | System fetches current market prices for IDX stock holdings (best-effort, with fallback) | yfinance `.JK` suffix convention; fallback-to-manual pattern documented in Pitfalls |
| INV-04 | User can manually set/override a holding's price (fallback for mutual funds/no-API instruments) | `price_cache` single-table read path; D-11 replace-on-next-fetch semantics |
| INV-05 | Each displayed price shows its as-of time and staleness indicator | Per-asset-type TTL table; staleness badge computation pattern |
| INV-06 | Investment page shows current portfolio value and per-holding P&L | Average-cost realized/unrealized formulas (Code Examples) |
| INV-07 | Portfolio events (buys/sells) recorded, enabling correlation queries | `portfolio_events` ledger already exists; D-15 correlation tool design |
| CHAT-03 | User can ask spending↔portfolio correlation questions | New `tools.py` tool: earliest-buy-event pivot + before/after window compare |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- **Tech stack lock-in:** FastAPI + PostgreSQL + Next.js App Router — build on it, no re-platform.
- **AI layer:** LlamaIndex abstraction, multi-provider (`Settings` singleton in `backend/config.py`) — the correlation tool must be added to `backend/tools.py`'s `TOOLS` registry, never emit raw SQL.
- **Safety:** All agent writes require explicit user confirmation before applying (propose→confirm); validated; audit-logged. Direct UI writes (this phase, D-16) use the button-click-as-confirmation exception already established in Phase 4.
- **Schema:** New `holdings`/`portfolio_events` tables + column additions need "a migration story (no Alembic today)" per CLAUDE.md text — **this statement is STALE.** Verified in-repo: Alembic was introduced in Phase 1 (`alembic/versions/001_baseline.py`) and is the actively-used mechanism; `002_new_tables.py` (revision `7b4e9f1a6c52`) already created `holdings`, `portfolio_events`, `price_cache`, `audit_log`, `proposals`; `003_app_settings.py` (revision `9c1a4f7d2b8e`, current head) added `app_settings`. Phase 5's new migration must set `down_revision = "9c1a4f7d2b8e"`. See Runtime State Inventory below.
- **Currency:** Single-currency (IDR) assumption holds for spending; investments may span instruments/currencies — Phase 5 resolves this by fetching everything directly in IDR (D-07), so no FX conversion code is needed.
- **Money as Decimal:** All new write paths and money math must use `Decimal` end-to-end (FND-03, already enforced in `backend/writes.py` and `backend/models.py` Numeric columns).
- **Money math note:** `Holding.avg_cost` and `PriceCache.price` are `Numeric(18,2)` (2 decimal places) — sufficient for IDR (no minor-unit fractions in practice) but be aware `Numeric(18,2)` rounds sub-cent price precision; crypto quantities use `Numeric(28,8)` for fractional-unit precision.

## Summary

Phase 5 extends an already-scaffolded investment schema (`holdings`, `portfolio_events`,
`price_cache` were created in Phase 1's `002_new_tables.py` migration but never wired to
any business logic) into a working tracker. The core technical shape is: (1) a
pluggable price-adapter registry keyed by `asset_type`, mirroring the existing `TOOLS`
dict pattern in `backend/tools.py`; (2) an average-cost recompute function that folds
an ordered `portfolio_events` ledger into `holdings.quantity`/`avg_cost`, with realized
P&L captured at sell/dividend time; (3) an in-process APScheduler daily job registered
in a new FastAPI `lifespan` context manager (the app currently has none — `app =
FastAPI(...)` is unadorned); (4) two new tables (`platforms`, `portfolio_value_history`)
plus a `holdings.platform_id` FK, delivered via a **fourth** Alembic migration chained
onto the existing `9c1a4f7d2b8e` head — not a "first" Alembic introduction, contrary to
the stale CLAUDE.md text.

The two external price sources are asymmetric in reliability. CoinGecko's free
`/simple/price` endpoint natively supports `vs_currencies=idr` and is well-documented,
but its `coins/list` symbol→id mapping has real collisions (~12,900 assets vs. ~10,600
unique symbols) — the adapter needs an explicit ticker→coin-id lookup table, not
runtime symbol search. yfinance's `.JK` suffix reliably returns IDX tickers priced
natively in IDR, but yfinance is an unofficial, scraping-based library with no SLA or
documented rate limits — the adapter must catch failures and fall back to the last
`price_cache` row (or flag stale) rather than propagate an exception. Reksadana
(mutual fund) NAV has no reliable free public API — confirmed by search: only
unofficial single-maintainer scrapers of Bibit's undocumented endpoints exist — so
manual entry is not just "the fallback," it is correctly the *only* viable path this
phase, exactly as CONTEXT.md's D-08 and INVX-02 deferral already assume.

**Primary recommendation:** Build the price layer as a `PRICE_ADAPTERS: dict[str,
Callable]` registry in a new `backend/prices.py` module (mirrors `TOOLS`), each
adapter returning `(price: Decimal, source: str) | None` so failures degrade to "use
last `price_cache` row, mark stale" rather than raising. Recompute `holdings` from
`portfolio_events` with a single ordered-scan function callable both after every event
write and idempotently from the daily snapshot job. Start the scheduler in a
`@asynccontextmanager lifespan(app)` function passed to `FastAPI(lifespan=lifespan)`,
registering one daily job that calls (synchronous) refresh-all-prices then
snapshot-all-holdings, each wrapped in try/except so one ticker's failure doesn't
abort the whole run.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Holdings/events/platforms CRUD | API / Backend | Browser / Client (forms) | Direct REST + `writes.py`, same as Phase 4 accounts; browser only renders forms and calls the API |
| Position recompute (qty/avg_cost from events) | API / Backend | Database | Pure Python function operating on ORM rows inside a request or job transaction; not pushed to SQL views (keeps the average-cost algorithm testable and swappable) |
| Live price fetching (CoinGecko/yfinance) | API / Backend | — | External HTTP calls must happen server-side (API keys/rate limits, and the browser must never call third-party finance APIs directly) |
| Price cache read/write | Database | API / Backend | `price_cache` table is the single read path; backend owns writes to it |
| Staleness badge computation | API / Backend | Browser / Client (render) | TTL-vs-`fetched_at` comparison is business logic computed server-side and returned as a flag; browser only renders the badge/color |
| P&L (realized + unrealized) | API / Backend | Database | Computed from `holdings` + `portfolio_events` + `price_cache` at request time; not stored/materialized (matches "as of" timestamp semantics) |
| Daily portfolio-value snapshot | API / Backend (in-process scheduler) | Database | APScheduler lives inside the FastAPI process (lifespan-managed); writes to `portfolio_value_history` |
| Correlation query (CHAT-03) | API / Backend (tools.py) | Database | New read-only tool in the `TOOLS` registry; agent never emits SQL, tool does parameterized queries across `portfolio_events` + `transactions` |
| Platform grouping/subtotals | API / Backend | Browser / Client (render) | Backend returns grouped/subtotaled payload; browser renders sections — no client-side aggregation logic |
| Investments page UI | Browser / Client | Frontend Server (SSR) | Next.js App Router; likely needs `"use client"` for refresh button + modals, unlike the Phase-3 skeleton (server component, no interactivity) |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `yfinance` | 1.5.1 [VERIFIED: PyPI registry] | IDX stock price fetch via `.JK` suffix | Most widely used free Yahoo Finance wrapper in Python; already the implicit assumption behind the Phase-3 `price_data_source` enum value `yfinance` |
| `pycoingecko` | 3.2.0 [VERIFIED: PyPI registry] | CoinGecko API client (or hand-rolled `httpx` call — see Alternatives) | Thin wrapper over CoinGecko's public REST API; matches Phase-3 enum value `coingecko` |
| `APScheduler` | 3.11.3 [VERIFIED: PyPI registry] | In-process daily job scheduler in the FastAPI lifespan | The de facto standard Python job scheduler (17 years old, 59 releases); `AsyncIOScheduler` integrates cleanly with FastAPI's asyncio event loop |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `httpx` | already a dependency (>=0.27.0) | Direct CoinGecko REST calls if skipping `pycoingecko` | If the adapter needs custom retry/timeout control beyond what `pycoingecko` exposes |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `pycoingecko` | Hand-rolled `httpx.get("https://api.coingecko.com/api/v3/simple/price", ...)` | `pycoingecko` (3.2.0, last released Nov 2024) may lag CoinGecko API changes; a raw `httpx` call against the documented `/simple/price` endpoint is ~10 lines and avoids a dependency entirely — **recommended** given the endpoint is trivial and the wrapper adds no real value beyond convenience |
| `yfinance` | Direct Yahoo Finance internal API scraping | `yfinance` already handles the scraping/anti-bot quirks; hand-rolling loses that maintenance for no benefit |
| `APScheduler` | `asyncio.create_task` + manual `while True: await sleep(86400)` loop | APScheduler gives misfire handling, `coalesce`, `max_instances`, and a declarative job API for near-zero extra code; the manual loop reinvents this poorly |

**Installation:**
```bash
pip install yfinance>=1.5.1 apscheduler>=3.11.3 httpx>=0.27.0
# pycoingecko optional — see Alternatives Considered; a raw httpx call is recommended instead
```

**Version verification:** Verified live against PyPI JSON API (`https://pypi.org/pypi/<pkg>/json`) on 2026-07-06:
- `yfinance` latest 1.5.1, first released 2019-05-26, 147 releases — mature, actively maintained.
- `apscheduler` latest 3.11.3, first released 2009-08-01, 59 releases — the canonical Python scheduler.
- `pycoingecko` latest 3.2.0, first released 2019-01-10, 18 releases, **last release Nov 2024** — slower-moving; confirms the recommendation to consider a raw `httpx` call instead for the single endpoint this phase needs.

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|--------------|---------|-------------|
| `yfinance` | PyPI | 7 yrs (first release 2019-05-26, 147 releases) | unknown via seam (downloads API unavailable) | github.com/ranaroussi/yfinance | SUS (seam) → **OK (manual override)** | Approved — seam's "too-new" signal checked only the *latest version's* publish timestamp (2026-06-28), not package age; first release predates this session by 7 years |
| `apscheduler` | PyPI | 17 yrs (first release 2009-08-01, 59 releases) | unknown via seam | no repo URL returned by seam (actual: github.com/agronholm/apscheduler) | SUS (seam) → **OK (manual override)** | Approved — same "too-new latest version" false signal; APScheduler is the de facto standard Python scheduler |
| `pycoingecko` | PyPI | 7 yrs (first release 2019-01-10, 18 releases) | unknown via seam | github.com/man-c/pycoingecko | SUS (seam) → **OK (manual override)**, but **deprioritized in favor of raw `httpx`** | Approved if used, but Standard Stack recommends a hand-rolled `httpx` call to `/simple/price` instead (see Alternatives Considered) — last release Nov 2024 is stale relative to the other two |

**Packages removed due to [SLOP] verdict:** none.
**Packages flagged as suspicious [SUS]:** all three packages were flagged `SUS` by the automated `package-legitimacy check` seam, but in every case the sole reason was `too-new` / `unknown-downloads` — a checker limitation where it read only the **latest version's** publish date (all three happened to receive routine maintenance releases around 2026-06-28) rather than the package's first-ever release. Manual verification via PyPI's full release history (see Version Verification above) confirms all three are long-established (7–17 years old, 18–147 releases) with real GitHub source repos (except APScheduler, whose repo URL the seam simply failed to resolve — it exists at github.com/agronholm/apscheduler). **The planner should still add one `checkpoint:human-verify` task before the first `pip install` of these three packages**, per protocol, but the research finding is that they are legitimate, not slopsquatted.

*yfinance and pycoingecko were discovered via WebSearch/training knowledge (package names), then cross-checked against the live PyPI registry and full release history — this is stronger than a bare `npm view`/`pip index versions` existence check, but is still tagged `[ASSUMED]` for the package **choice** (there could be a better-fit alternative library neither of us searched for) even though the package's **legitimacy** is verified.*

## Architecture Patterns

### System Architecture Diagram

```
Browser (/investments page, "use client")
   |
   |  GET /investments/summary            POST /holdings, /portfolio-events, /platforms
   |  POST /prices/refresh                PUT/DELETE .../{id}
   v
FastAPI (backend/main.py)
   |
   |-- require_api_key (write routes only, same as Phase 4)
   |
   +--> backend/writes.py:apply_add_holding / apply_add_portfolio_event / apply_add_platform
   |        |
   |        +--> recompute_holding_from_events(ticker)  [new: backend/portfolio.py]
   |        |        reads ordered portfolio_events -> writes holdings.quantity/avg_cost
   |        |
   |        +--> AuditLog row (before/after, D-16)
   |
   +--> backend/prices.py: PRICE_ADAPTERS[asset_type](ticker) -> (Decimal, source) | None
   |        |
   |        +--> crypto    -> CoinGecko  /simple/price?ids=...&vs_currencies=idr
   |        +--> idx_stock -> yfinance   Ticker(f"{ticker}.JK").fast_info / .history()
   |        +--> other/mutual_fund -> None (manual only; no live source)
   |        |
   |        writes result into price_cache (source='coingecko'|'yfinance'|'manual')
   |        on failure: fall back to latest price_cache row for that ticker, flag stale
   |
   +--> backend/tools.py (agent-facing, read-only)
   |        |
   |        +--> propose_add_holding / propose_edit_holding / propose_delete_holding (existing)
   |        +--> [NEW] correlation tool: earliest buy event -> before/after window compare
   |                 reads portfolio_events (pivot date) + transactions (category spend)
   |
   +--> FastAPI lifespan (new, wraps app = FastAPI(lifespan=lifespan))
            |
            +--> AsyncIOScheduler.start() on startup
            +--> daily job: refresh_all_prices() -> snapshot_all_holdings()
            |         writes portfolio_value_history (one row per holding per day)
            +--> AsyncIOScheduler.shutdown(wait=False) on shutdown

PostgreSQL: holdings <-1:N- portfolio_events
            holdings -N:1-> platforms (new FK)
            price_cache (ticker, source, price, fetched_at) -- one row per (ticker, source)
            portfolio_value_history (new: snapshot_date, ticker, quantity, market_value, cost_basis)
```

A user request traces: browser click -> REST endpoint -> `writes.py` helper (audited,
Decimal) -> `recompute_holding_from_events` -> response. A price refresh traces:
button click or daily scheduler tick -> `prices.py` adapter routed by `asset_type` ->
`price_cache` write -> next `/investments` read picks up the new row. A chat
correlation question traces: user message -> agent -> new `tools.py` tool -> reads
`portfolio_events` for pivot date + `transactions` for before/after windows -> returns
a number the agent states (never raw SQL, never fabricated).

### Recommended Project Structure
```
backend/
├── models.py            # Holding, PortfolioEvent, PriceCache (existing) + Platform, PortfolioValueHistory (new)
├── prices.py             # NEW: PRICE_ADAPTERS registry + CoinGecko/yfinance/manual adapter functions
├── portfolio.py           # NEW: recompute_holding_from_events(), realized/unrealized P&L calculators
├── scheduler.py           # NEW: build_scheduler() + the daily snapshot job function
├── writes.py              # extend: apply_add_holding, apply_edit_holding (already has propose_* variants), apply_add_portfolio_event, apply_add_platform, apply_edit_platform, apply_delete_platform
├── tools.py                # extend: correlation tool (D-15) added to TOOLS registry
├── schemas.py              # extend: HoldingCreate/Out, PortfolioEventCreate/Out, PlatformCreate/Out, PortfolioSummary
├── main.py                 # extend: lifespan=lifespan on FastAPI(...), new REST routes, price-refresh endpoint
alembic/versions/
└── 004_investment_platforms.py   # NEW: platforms, portfolio_value_history, holdings.platform_id FK
ui/app/investments/
└── page.tsx               # grow from Phase-3 server-component skeleton into a "use client" tracker
```

### Pattern 1: Pluggable Price-Adapter Registry (D-08)
**What:** A `dict[str, Callable[[str], tuple[Decimal, str] | None]]` keyed by
`asset_type`, mirroring `TOOLS` in `backend/tools.py`.
**When to use:** Any time the caller needs "the current price for this ticker" —
called from the lazy-load-on-page-view path and from the daily scheduler job.
**Example:**
```python
# backend/prices.py
from decimal import Decimal
from typing import Callable

def fetch_crypto_price(ticker: str) -> tuple[Decimal, str] | None:
    """CoinGecko simple/price, vs_currency=idr. ticker must already be a
    resolved CoinGecko coin id (e.g. 'bitcoin'), NOT a symbol like 'BTC' —
    symbols collide (~12,900 coins, ~10,600 unique symbols; see Pitfall 2).
    Maintain a static TICKER_TO_COINGECKO_ID map, do not resolve at runtime."""
    import httpx
    coin_id = TICKER_TO_COINGECKO_ID.get(ticker)
    if coin_id is None:
        return None
    try:
        resp = httpx.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": coin_id, "vs_currencies": "idr"},
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
        price = data.get(coin_id, {}).get("idr")
        if price is None:
            return None
        return Decimal(str(price)), "coingecko"
    except (httpx.HTTPError, KeyError, ValueError):
        return None  # caller falls back to latest price_cache row


def fetch_idx_price(ticker: str) -> tuple[Decimal, str] | None:
    """yfinance .JK suffix — native IDR. Best-effort: yfinance is an
    unofficial scraper with no documented rate limits/SLA; any exception
    or empty result means fall back to price_cache (INV-03 requirement)."""
    import yfinance as yf
    try:
        yk = yf.Ticker(f"{ticker}.JK")
        price = yk.fast_info.get("lastPrice")
        if price is None:
            return None
        return Decimal(str(price)), "yfinance"
    except Exception:
        return None


def fetch_manual_price(ticker: str) -> tuple[Decimal, str] | None:
    """No live source — mutual_fund/other always resolve to the last
    manually-set price_cache row; this function is a registry placeholder
    that always returns None so the caller's fallback path (read price_cache)
    is the only path taken."""
    return None


PRICE_ADAPTERS: dict[str, Callable[[str], tuple[Decimal, str] | None]] = {
    "crypto": fetch_crypto_price,
    "idx_stock": fetch_idx_price,
    "mutual_fund": fetch_manual_price,
    "other": fetch_manual_price,
}
```

### Pattern 2: Average-Cost Recompute from Event Ledger (D-01/D-02)
**What:** A single function that scans a ticker's `portfolio_events` in date order
and derives `quantity`/`avg_cost`, returning realized P&L as a byproduct.
**When to use:** Called after every `apply_add_portfolio_event` / edit / delete write,
and idempotently re-callable (safe to call redundantly from the daily snapshot job).
**Example:**
```python
# backend/portfolio.py
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.models import PortfolioEvent, Holding

def recompute_holding_from_events(db: Session, ticker: str) -> dict:
    """D-01/D-02: portfolio_events is the source of truth. Scans events in
    date order (then id order as a tiebreak for same-day events), derives
    running quantity + average cost, and returns realized P&L + dividend
    total as a byproduct. Writes/updates the holdings row; if resulting
    quantity == 0, the holding is left as a zero-qty row (D-04: "drops off
    the active list" is a query-time filter, not a delete)."""
    events = db.scalars(
        select(PortfolioEvent)
        .where(PortfolioEvent.ticker == ticker)
        .order_by(PortfolioEvent.date, PortfolioEvent.id)
    ).all()

    qty = Decimal("0")
    total_cost = Decimal("0")   # sum of cost basis for currently-open quantity
    realized_pnl = Decimal("0")
    dividend_total = Decimal("0")

    for ev in events:
        if ev.event_type == "buy":
            total_cost += ev.price * ev.quantity
            qty += ev.quantity
        elif ev.event_type == "sell":
            avg_cost = (total_cost / qty) if qty > 0 else Decimal("0")
            realized_pnl += (ev.price - avg_cost) * ev.quantity
            total_cost -= avg_cost * ev.quantity   # avg_cost UNCHANGED by a sell (D-02)
            qty -= ev.quantity
        elif ev.event_type == "dividend":
            # Dividends fold into realized return (D-02); they do not touch qty/cost.
            realized_pnl += ev.price * ev.quantity   # convention: quantity=1, price=amount for lump-sum dividends
            dividend_total += ev.price * ev.quantity

    avg_cost = (total_cost / qty) if qty > 0 else Decimal("0")

    holding = db.query(Holding).filter(Holding.ticker == ticker).one_or_none()
    if holding is None:
        holding = Holding(ticker=ticker, quantity=qty, avg_cost=avg_cost, currency="IDR")
        db.add(holding)
    else:
        holding.quantity = qty
        holding.avg_cost = avg_cost

    return {
        "ticker": ticker,
        "quantity": qty,
        "avg_cost": avg_cost,
        "realized_pnl": realized_pnl,
        "dividend_total": dividend_total,
    }
```
**Realized P&L note:** the formula above keeps `avg_cost` unchanged across a sell (per
D-02's explicit wording: "a sell realizes `(sell_price − avg_cost) × sold_qty` and
leaves `avg_cost` unchanged") by reducing `total_cost` by `avg_cost × sold_qty` rather
than recomputing `avg_cost` from a smaller pool — mathematically these are equivalent
since avg_cost is a ratio, but expressing it this way makes the "unchanged" invariant
explicit in code rather than an accidental algebraic fact.

### Pattern 3: APScheduler in FastAPI Lifespan (D-14)
**What:** Replace `app = FastAPI(title=..., version=...)` with a `lifespan` context
manager that starts the scheduler before `yield` and shuts it down after.
**When to use:** This is the stack's first always-on background component — apply
exactly this shape, do not use `@app.on_event("startup")` (deprecated in modern
FastAPI in favor of `lifespan`).
**Example:**
```python
# backend/main.py
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

scheduler = AsyncIOScheduler(timezone="Asia/Jakarta")

def daily_portfolio_snapshot_job() -> None:
    """Sync function — APScheduler runs non-coroutine jobs in its own
    thread pool executor, so this can safely use the existing sync
    get_session_sync() pattern without blocking the asyncio event loop."""
    from backend.db import get_session_sync
    from backend.prices import refresh_all_prices
    from backend.portfolio import snapshot_all_holdings

    with get_session_sync() as db:
        refresh_all_prices(db)          # best-effort; per-ticker try/except inside
        snapshot_all_holdings(db)       # writes portfolio_value_history rows
        db.commit()

@asynccontextmanager
async def lifespan(app: "FastAPI"):
    scheduler.add_job(
        daily_portfolio_snapshot_job,
        trigger=CronTrigger(hour=1, minute=0),  # 01:00 Asia/Jakarta — low-traffic window
        id="daily_portfolio_snapshot",
        replace_existing=True,
        misfire_grace_time=3600,   # tolerate up to 1h late (container restarts) before skipping
        coalesce=True,             # if multiple runs were missed, run once, not N times
        max_instances=1,           # never overlap two snapshot runs
    )
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)

app = FastAPI(title="monai", version="0.1.0", lifespan=lifespan)
```
**Failure modes and mitigations:**
- **Job overlap** (a slow snapshot run still going when the next day's tick fires):
  `max_instances=1` — APScheduler skips/logs rather than running concurrently.
- **Misfire** (container was down at 01:00): `misfire_grace_time=3600` + `coalesce=True`
  runs it once on next startup if within the grace window, otherwise skips to next tick
  — acceptable since D-13 already documents "history cannot be backfilled."
- **DB session handling inside jobs:** reuse `get_session_sync()` (already exists,
  used by `tools.py`) — do NOT create a second session-management path.
- **Blocking the event loop:** `AsyncIOScheduler`'s non-coroutine jobs run in a
  `ThreadPoolExecutor` by default (not on the asyncio loop thread), so the fully
  synchronous SQLAlchemy engine (`create_engine`, not async) used here is safe as-is.
- **Multi-worker duplication:** N/A for this stack — `backend/entrypoint.sh` runs a
  single `uvicorn backend.main:app` process with no `--workers` flag; the
  file-lock/leader-election concern documented for Gunicorn multi-worker deployments
  does not apply. If a future phase adds multiple workers, this becomes a hard
  requirement to revisit (flag as a note, not an action item now).

### Anti-Patterns to Avoid
- **Resolving CoinGecko ticker→id at request time via `/search` or fuzzy match:**
  Symbol collisions (BTC vs multiple "BIT"-symbol coins) make this nondeterministic.
  Maintain a static `TICKER_TO_COINGECKO_ID` dict seeded from the user's actual
  holdings, not a dynamic lookup.
- **Letting a price-fetch exception propagate to the request handler:** INV-03
  explicitly requires "best-effort, with fallback" — every adapter call must be
  wrapped so failure degrades to "show last known price_cache row + stale badge,"
  never a 500.
- **Recomputing `avg_cost` by re-deriving it from a "reduced pool" after a sell:**
  Produces the same number as the total-cost-reduction approach above but obscures
  the "avg_cost unchanged by a sell" invariant D-02 explicitly calls out — prefer the
  explicit form for auditability.
- **`@app.on_event("startup")`/`("shutdown")`:** deprecated pattern; use `lifespan`.
- **Materializing P&L into a stored column:** P&L is computed at request time from
  `holdings` + `portfolio_events` + `price_cache`, consistent with the "as of
  timestamp" semantics (D-05) — do not cache/store a stale P&L number.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Daily background job scheduling | A custom `asyncio.create_task` + `while True: sleep()` loop | `APScheduler` `AsyncIOScheduler` | Misfire handling, `coalesce`, `max_instances`, cron-style triggers, and graceful `.shutdown()` are non-trivial to get right; APScheduler is 17 years mature and handles all of this |
| Cost-basis accounting | A hand-rolled running-average calculator with ad-hoc edge cases | The explicit ordered-scan algorithm in Pattern 2 (still hand-written, but following the textbook average-cost formula precisely, including the "avg_cost unchanged by sell" invariant) | Average-cost has known edge cases (selling more than held, zero-quantity avg_cost division) that are easy to get subtly wrong without following the formula literally |
| Ticker/symbol → CoinGecko coin-id resolution | Runtime fuzzy-matching or calling `/search` per request | A static `TICKER_TO_COINGECKO_ID` map seeded once for the user's actual holdings | CoinGecko's own docs/community confirm symbol collisions (~2,300 duplicate symbols) — deterministic behavior requires a fixed mapping, not a runtime guess |
| Yahoo Finance scraping/anti-bot handling | Direct HTTP calls to Yahoo Finance's internal endpoints | `yfinance` | `yfinance` already absorbs Yahoo's endpoint/anti-bot churn; hand-rolling loses that maintenance |
| CoinGecko HTTP client boilerplate (optional) | N/A — either `pycoingecko` or ~10 lines of `httpx` is acceptable | `httpx` direct call (recommended, see Alternatives Considered) | The `/simple/price` endpoint is trivial enough that a dependency isn't clearly justified, but this is a judgment call, not a hard rule |

**Key insight:** The two domains with real hand-rolling risk in this phase are (1)
background job orchestration — where APScheduler's edge-case handling (misfires,
overlap, timezone-aware cron) is exactly the kind of thing that "seems simple" until a
container restarts mid-job — and (2) financial ticker resolution, where the
CoinGecko symbol-collision issue is a documented, real footgun that a naive
implementation would hit on the very first ambiguous symbol a user enters.

## Runtime State Inventory

> This is a schema-extension phase (new tables + new FK column via Alembic), not a
> rename/refactor/migration phase in the sense the template describes (no renaming of
> existing identifiers). The categories below are answered for completeness since
> Phase 5 does touch already-existing tables (`holdings`) with a new column.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `holdings`, `portfolio_events`, `price_cache` tables already exist (created by `002_new_tables.py`, revision `7b4e9f1a6c52`) but contain **zero rows** in production — Phase 1 created the schema, nothing has ever written to it. No existing holdings/events data to migrate or reconcile. | None — this is greenfield data population, not a migration of existing rows. |
| Live service config | None. No external service (n8n, Datadog, etc.) references these table/column names. | None. |
| OS-registered state | None. No OS-level task scheduler, cron, or process manager references investment tables. This phase *introduces* the first such component (APScheduler), it doesn't inherit one. | None — but see Common Pitfalls for the new-component failure mode this introduces. |
| Secrets/env vars | None new. CoinGecko free tier needs no API key for `/simple/price`; yfinance needs no key. No SOPS/env var renames. | None. |
| Build artifacts | `backend/requirements.txt` currently lacks `yfinance`, `apscheduler`, `httpx` is already present. Docker image will need a rebuild after the dependency addition (per the project memory note "deploy-requires-rebuild" — `docker compose up -d --build`, not just `up -d`). | Add deps to `requirements.txt`; rebuild the `monai-backend` image before verification (do not rely on a stale running container, per prior Phase-4 lesson). |

**Migration mechanism (the ambiguity this research resolves):** CLAUDE.md's schema
constraint text ("New `holdings` and `portfolio_events` tables + any column additions
need a migration story (no Alembic today)") is **stale** — verified in-repo:
- `alembic/versions/001_baseline.py` — baseline revision (introduced in Phase 1).
- `alembic/versions/002_new_tables.py` — revision `7b4e9f1a6c52`, `down_revision =
  "3a1f8c2d9e04"` — created `audit_log`, `proposals`, `holdings`, `portfolio_events`,
  `price_cache` **and** the `date_helpers` view.
- `alembic/versions/003_app_settings.py` — revision `9c1a4f7d2b8e`, `down_revision =
  "7b4e9f1a6c52"` — created `app_settings` (Phase 3). **This is the current head.**
- `backend/entrypoint.sh` runs `alembic upgrade head` before every `uvicorn` start —
  idempotent, already the established deploy-time migration path.
- **Recommendation for D-17:** add `alembic/versions/004_investment_platforms.py`
  with `down_revision = "9c1a4f7d2b8e"`, creating `platforms`,
  `portfolio_value_history`, and `op.add_column("holdings", sa.Column("platform_id",
  sa.Integer, sa.ForeignKey("platforms.id"), nullable=True))` (nullable so existing —
  currently zero — holding rows don't break; `nullable=True` also lets a holding be
  "unassigned to any platform" which is a reasonable default state). See Code Examples
  for the full migration skeleton.

## Common Pitfalls

### Pitfall 1: CoinGecko symbol collisions silently mispricing a holding
**What goes wrong:** Building a `symbol -> coin_id` map at runtime (e.g. searching
`coins/list` for the first row matching `BTC`) can resolve to the wrong coin if two
different assets share a symbol, silently showing a wrong price with no error.
**Why it happens:** CoinGecko has ~12,900 coins but only ~10,600 unique symbols —
duplicates are a documented, acknowledged platform characteristic, not an edge case.
**How to avoid:** Maintain a static, explicitly-reviewed `TICKER_TO_COINGECKO_ID` dict
built once for the specific tickers the user actually holds (small, known set — a
single-user app doesn't need to support arbitrary symbol search).
**Warning signs:** A holding's live price looks implausible (off by 10-1000x, or a
totally different asset's price) compared to the user's manually-known value.

### Pitfall 2: yfinance failures propagating as 500s instead of degrading gracefully
**What goes wrong:** yfinance is an unofficial scraper of Yahoo Finance with no SLA;
Yahoo can rate-limit, change page structure, or return empty data at any time. If the
price-fetch call isn't wrapped, an exception during a batch refresh can abort the
whole `/investments` page load or the daily scheduler job.
**Why it happens:** Treating an external, best-effort data source as if it were a
reliable internal call.
**How to avoid:** Every adapter function returns `None` on any exception (broad
`except Exception`, matching this project's existing convention in `ask()`/`/query`
of intentionally broad exception handling to avoid propagating to the user) and the
caller falls back to the latest `price_cache` row, marking it stale if past TTL.
**Warning signs:** `/investments` page returns 500 or hangs; scheduler job logs show
an unhandled exception aborting the snapshot for all remaining holdings, not just the
one problem ticker.

### Pitfall 3: APScheduler job silently not running after a container restart
**What goes wrong:** `misfire_grace_time` too small (or default of 1 second) means a
job scheduled for 01:00 that the container missed (e.g. redeployed at 01:05) is
treated as misfired and skipped entirely — silently, no error, no data collected for
that day, and per D-13 **that day's data point cannot be backfilled**.
**Why it happens:** APScheduler's default `misfire_grace_time` is very small; nobody
tunes it until they notice missing data days later.
**How to avoid:** Set an explicit, generous `misfire_grace_time` (e.g. 3600s = 1
hour) and `coalesce=True`; also consider logging every scheduler tick (success or
skip) so silent misses are visible in container logs, not just absent from
`portfolio_value_history`.
**Warning signs:** Gaps in `portfolio_value_history.snapshot_date` with no
corresponding log entry explaining why.

### Pitfall 4: `avg_cost` recomputed incorrectly after a sell
**What goes wrong:** A common bug is to recompute `avg_cost` as `(total_cost -
sell_proceeds) / remaining_qty` instead of leaving `avg_cost` numerically unchanged
and only reducing `total_cost` proportionally — these produce different (wrong)
numbers if `sell_price != avg_cost`.
**Why it happens:** Confusing "cash proceeds from the sale" with "cost basis removed
from the pool" — average-cost method removes cost basis at `avg_cost`, not at the
sale price, regardless of whether the sale was profitable.
**How to avoid:** Follow Pattern 2's formula literally: reduce `total_cost` by
`avg_cost × sold_qty` (not `sell_price × sold_qty`), and realize
`(sell_price − avg_cost) × sold_qty` as a separate `realized_pnl` accumulator.
**Warning signs:** Realized P&L numbers that don't match manual back-of-envelope
math for a simple two-event (buy then sell) test case.

### Pitfall 5: Adding `"use client"` to the Investments page without checking Phase-3's server-component pattern
**What goes wrong:** The Phase-3 skeleton is deliberately a server component ("no
client state, no `use client`" per its own header comment, citing "RESEARCH.md
Pitfall 5" from Phase 3's research). Growing it into an interactive tracker (refresh
button, modals, live-updating P&L) requires becoming a client component, and doing
this incompletely (e.g. only some handlers wired) can silently break SSR/hydration.
**Why it happens:** Copy-pasting the existing skeleton without revisiting why it was
server-only.
**How to avoid:** Explicitly convert to `"use client"` at the top of the file (like
`ui/app/cashflow/page.tsx` already does per Phase 4), matching the established
pattern for pages with forms/interactivity, rather than trying to keep it a server
component with client "islands."
**Warning signs:** Next.js build/hydration warnings; refresh button or modals not
responding to clicks.

## Code Examples

### Correlation tool (D-15 / CHAT-03)
```python
# backend/tools.py — new addition to the TOOLS registry
from datetime import timedelta

def spending_before_after_purchase(ticker: str, category: str) -> dict:
    """CHAT-03: 'since I bought BBCA, how has my eating-out spending changed?'

    Pivot date = earliest 'buy' event for this ticker in portfolio_events
    (D-15). Compares category spending in the N days before vs N days after
    that date, where N = days elapsed since the purchase (equal-length
    windows, so the comparison isn't skewed by an arbitrarily longer
    'after' window as time passes).

    Reuses spending_in_category()'s existing period="custom" + explicit
    start_date/end_date contract — no new date-range SQL needed.
    """
    with engine.connect() as c:
        pivot = c.execute(
            text(
                "SELECT MIN(date) FROM portfolio_events "
                "WHERE ticker = :ticker AND event_type = 'buy'"
            ),
            {"ticker": ticker},
        ).scalar()

    if pivot is None:
        return {
            "tool": "spending_before_after_purchase",
            "error": f"No buy event found for ticker '{ticker}' — nothing to compare against.",
        }

    today = date.today()
    n_days = (today - pivot).days
    if n_days < 1:
        return {
            "tool": "spending_before_after_purchase",
            "error": f"Purchase of {ticker} was today or in the future — no 'after' window yet.",
        }

    before_start = pivot - timedelta(days=n_days)
    before_end = pivot - timedelta(days=1)
    after_start = pivot
    after_end = today

    before = spending_in_category(category, period="custom",
                                   start_date=before_start.isoformat(),
                                   end_date=before_end.isoformat())
    after = spending_in_category(category, period="custom",
                                  start_date=after_start.isoformat(),
                                  end_date=after_end.isoformat())

    delta = after["total"] - before["total"]
    return {
        "tool": "spending_before_after_purchase",
        "ticker": ticker,
        "category": category,
        "pivot_date": pivot.isoformat(),
        "window_days": n_days,
        "before_total": before["total"],
        "after_total": after["total"],
        "delta": delta,
        "delta_pct": (delta / before["total"] * 100) if before["total"] else None,
    }

# Registered in TOOLS dict alongside spending_in_category, spending_total, etc.
```

### Migration skeleton (D-17)
```python
# alembic/versions/004_investment_platforms.py
"""add platforms, portfolio_value_history, holdings.platform_id FK

Revision ID: <generate via `alembic revision`>
Revises: 9c1a4f7d2b8e
Create Date: <today>
"""
from alembic import op
import sqlalchemy as sa

revision = "<new>"
down_revision = "9c1a4f7d2b8e"   # current head — chains onto 003_app_settings.py
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platforms",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("kind", sa.String(32), nullable=True),  # e.g. "crypto_app" | "brokerage" | "fund_app" | "other"
    )

    op.add_column(
        "holdings",
        sa.Column("platform_id", sa.Integer, sa.ForeignKey("platforms.id"), nullable=True),
    )

    op.create_table(
        "portfolio_value_history",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("snapshot_date", sa.Date, nullable=False),
        sa.Column("ticker", sa.String(32), nullable=False),
        sa.Column("quantity", sa.Numeric(28, 8), nullable=False),
        sa.Column("market_value", sa.Numeric(18, 2), nullable=False),
        sa.Column("cost_basis", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False, server_default="IDR"),
    )
    op.create_index(
        "ix_portfolio_value_history_date_ticker",
        "portfolio_value_history",
        ["snapshot_date", "ticker"],
        unique=True,   # D-13: one row per holding per day — enforce at the DB level
    )


def downgrade() -> None:
    op.drop_index("ix_portfolio_value_history_date_ticker", "portfolio_value_history")
    op.drop_table("portfolio_value_history")
    op.drop_column("holdings", "platform_id")
    op.drop_table("platforms")
```

### CoinGecko simple/price call shape (verified endpoint contract)
```python
# GET https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=idr
# Response: {"bitcoin": {"idr": 1234567890}}
# Free tier (no API key / "Demo" plan): ~10,000 calls/month, rate limit varies
# 5-15 calls/min unauthenticated vs up to 100 calls/min with a free Demo API key —
# register a Demo key (free) rather than calling fully anonymously if rate limits
# become an issue; not required to ship the phase.
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| `@app.on_event("startup")` / `("shutdown")` for background job registration in FastAPI | `lifespan` async context manager passed to `FastAPI(lifespan=...)` | FastAPI deprecated `on_event` some time ago in favor of `lifespan` (well-established by the FastAPI version already pinned, `>=0.110.0`) | This phase should use `lifespan` from the start — there is no legacy code to migrate away from since the scheduler is new |
| FIFO or specific-identification cost basis | Average cost (this project's explicit D-02 choice) | N/A — this is a deliberate, already-locked project decision, not an industry shift | Simpler to implement and reason about than FIFO lot-tracking; do not second-guess this in planning |

**Deprecated/outdated:** None specific to this phase's stack — `yfinance`, `APScheduler`,
and CoinGecko's `/simple/price` endpoint are all current, actively-maintained
interfaces as of this research date.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `yfinance`, `apscheduler`, `pycoingecko` are the correct/best-fit package choices (vs. some untried alternative) | Standard Stack | Low — all three are verified-legitimate, long-established, and match the Phase-3 `price_data_source` enum's implicit assumptions (`coingecko`, `yfinance`); an alternative library would need a compelling reason to prefer over the incumbent, obvious choice |
| A2 | CoinGecko free-tier unauthenticated rate limit is roughly 5-15 calls/min (vs. 100 calls/min with a free Demo API key) | Standard Stack / Code Examples | Low-medium — if the unauthenticated limit is stricter than found, the lazy-load-on-page-view + manual-refresh-button pattern (D-09) naturally limits call volume for a single-user app anyway; registering a free Demo key is a trivial mitigation if needed |
| A3 | yfinance `.fast_info["lastPrice"]` is the correct attribute for current price (vs. `.history()` or `.info["currentPrice"]`) — based on training knowledge of the yfinance API surface, not directly verified against yfinance 1.5.1's changelog this session | Architecture Patterns / Code Examples | Medium — yfinance's API surface has shifted across major versions before; the planner/implementer should do a quick smoke-test (`python -c "import yfinance; print(yfinance.Ticker('BBCA.JK').fast_info)"`) against the actual pinned 1.5.1 version before writing the adapter, and treat this as a Wave 0 verification step, not a locked assumption |
| A4 | No reliable free reksadana NAV API exists (confirms CONTEXT.md's own INVX-02 deferral) | Summary / Don't Hand-Roll | Low — this matches the already-locked project decision; only unofficial single-maintainer GitHub scrapers of Bibit's undocumented endpoints were found, reinforcing rather than contradicting the existing plan |
| A5 | 01:00 Asia/Jakarta is a reasonable default time-of-day for the daily snapshot job | Architecture Patterns (Pattern 3) | Low — explicitly called out in CONTEXT.md as "Claude's discretion"; any low-traffic hour works equally well for a single-user self-hosted app |

**If this table is empty:** N/A — see entries above; all are LOW-MEDIUM risk and none block planning.

## Open Questions

1. **Exact yfinance attribute for "current price" on `.JK` tickers**
   - What we know: `.JK` suffix reliably returns IDX tickers priced in IDR;
     `fast_info` is the modern, fast-path attribute bundle in recent yfinance
     versions.
   - What's unclear: Whether `fast_info["lastPrice"]` vs `fast_info["last_price"]`
     (snake_case vs camelCase key naming has changed across yfinance versions) is
     correct for the pinned 1.5.1, and whether it returns delayed or real-time data
     for IDX specifically (Yahoo Finance shows "Jakarta delayed quotes" per search
     results — likely 15-20 min delayed, which is fine for a personal tracker but
     worth documenting so the user isn't surprised).
   - Recommendation: Wave 0 / first implementation task should do a live smoke-test
     against a real `.JK` ticker (e.g. `BBCA.JK`) with the pinned version before
     wiring the full adapter, and cache the actual response shape in a code comment.

2. **CoinGecko Demo API key registration**
   - What we know: unauthenticated calls are rate-limited to roughly 5-15/min; a
     free "Demo" account raises this to ~100/min + 10,000/month.
   - What's unclear: Whether the user wants to register a free CoinGecko account for
     a Demo key (adds an `app_settings`/env var) or accept the lower unauthenticated
     limit, which is almost certainly sufficient given D-09's lazy-load + manual-
     refresh pattern for a single-user app with a small number of crypto holdings.
   - Recommendation: Ship without a Demo key first (simplest — zero new config);
     only add key registration if real-world rate-limit errors are observed.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| PostgreSQL | All persistence (holdings, events, price_cache, new tables) | ✓ (per docker-compose, port 5434) | 16-alpine | — |
| Outbound internet access (CoinGecko API) | INV-02 crypto price fetch | Assumed ✓ (self-hosted Docker Compose with `network_mode: host`) | — | Falls back to manual price entry if network egress is blocked in the user's deployment environment |
| Outbound internet access (Yahoo Finance, via yfinance) | INV-03 IDX price fetch | Assumed ✓ | — | Falls back to manual price entry (INV-04) — this is already the designed behavior, not an environment gap |
| PyPI package availability (`yfinance`, `apscheduler`) | Backend dependency install | ✓ — confirmed resolvable via `uv pip install --dry-run` this session | yfinance 1.5.1, apscheduler 3.11.3 | — |

**Missing dependencies with no fallback:** None — every external dependency in this
phase (CoinGecko, yfinance, reksadana NAV) already has a designed fallback to manual
price entry per the locked D-08/D-11 decisions.

**Missing dependencies with fallback:** Live price sources generally — by design,
this phase treats "no live price available" as an expected, handled state, not an
error condition.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest >=8.0.0 (`backend/requirements.txt`), `asyncio_mode = "auto"` |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` — `testpaths = ["backend/tests"]` |
| Quick run command | `pytest backend/tests/test_portfolio.py -x` (new file, see Wave 0 Gaps) |
| Full suite command | `pytest backend/tests` (requires live Postgres — existing `db_available` fixture pattern skips gracefully if not up) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| INV-01 | Add/edit/remove holding via events; holding recomputes correctly | unit | `pytest backend/tests/test_portfolio.py::test_recompute_holding_from_events -x` | ❌ Wave 0 |
| INV-01 | Direct holding override (D-03) writes audit_log | unit | `pytest backend/tests/test_write_tools.py::test_propose_edit_holding_creates_proposal -x` (extend existing file) | ✅ existing (extend) |
| INV-02 | CoinGecko adapter returns Decimal price for a known coin id | unit (mocked HTTP) | `pytest backend/tests/test_prices.py::test_fetch_crypto_price -x` | ❌ Wave 0 |
| INV-03 | yfinance adapter degrades to `None` on any exception (fallback contract) | unit (mocked yfinance) | `pytest backend/tests/test_prices.py::test_fetch_idx_price_fallback -x` | ❌ Wave 0 |
| INV-04 | Manual price override writes `price_cache` with `source='manual'`, reflected in P&L immediately | integration | `pytest backend/tests/test_portfolio.py::test_manual_price_override -x` | ❌ Wave 0 |
| INV-05 | Staleness badge flips to "stale" once `fetched_at` exceeds the asset-type TTL | unit | `pytest backend/tests/test_portfolio.py::test_staleness_ttl -x` | ❌ Wave 0 |
| INV-06 | Realized + unrealized P&L match hand-computed values for a buy→sell→dividend sequence | unit | `pytest backend/tests/test_portfolio.py::test_avg_cost_realized_pnl -x` | ❌ Wave 0 |
| INV-07 | `portfolio_events` row created on every buy/sell/dividend write | integration | `pytest backend/tests/test_write_tools.py::test_propose_add_portfolio_event -x` (extend existing file) | ✅ existing (extend) |
| CHAT-03 | Correlation tool returns correct before/after totals for a known pivot date | unit | `pytest backend/tests/test_tools.py::test_spending_before_after_purchase -x` (extend existing file) | ✅ existing (extend) |
| D-14 (scheduler) | Daily job runs without raising even if one ticker's price fetch fails | integration | `pytest backend/tests/test_scheduler.py::test_snapshot_job_partial_failure_tolerant -x` | ❌ Wave 0 |
| D-17 (migration) | `alembic upgrade head` applies cleanly on top of the current `9c1a4f7d2b8e` head without touching existing data | manual/smoke | `alembic upgrade head` against a copy of the dev DB, then `alembic downgrade -1` to confirm reversibility | manual-only — justified: no automated DB-migration test harness exists in this repo yet (Phase 1 also relied on manual verification for its migration) |

### Sampling Rate
- **Per task commit:** `pytest backend/tests/test_portfolio.py backend/tests/test_prices.py -x` (fast, scoped to new modules)
- **Per wave merge:** `pytest backend/tests` (full suite, requires `docker compose up -d db`)
- **Phase gate:** Full suite green + manual `alembic upgrade head`/`downgrade -1` round-trip before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `backend/tests/test_portfolio.py` — covers INV-01/04/05/06 (recompute algorithm, manual override, staleness, P&L math)
- [ ] `backend/tests/test_prices.py` — covers INV-02/03 (adapter contract: returns `(Decimal, str) | None`, never raises)
- [ ] `backend/tests/test_scheduler.py` — covers D-14 (job registration, partial-failure tolerance; can test the job function directly without actually waiting for a cron tick)
- [ ] Extend `backend/tests/test_write_tools.py` — add holding/portfolio_event/platform propose-creates-row cases following the existing pattern (`test_propose_edit_holding_creates_proposal` already exists as a template)
- [ ] Extend `backend/tests/test_tools.py` — add `test_spending_before_after_purchase` following the existing `spending_in_category` test pattern
- [ ] No framework install needed — pytest, the `db_available` skip-fixture pattern, and `testpaths` config all already exist and apply to new test files automatically.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-------------------|
| V2 Authentication | No (new surface) | Existing `MONAI_API_KEY` / `require_api_key` dependency, unchanged — reused as-is on all new write routes |
| V3 Session Management | No | Single-user, stateless API-key auth; no session concept introduced |
| V4 Access Control | Yes | All new holdings/events/platforms write endpoints MUST carry `dependencies=[Depends(require_api_key)]`, matching every existing write route (Phase 1/4 pattern) — read endpoints (`GET /investments/summary`, etc.) can remain unauthenticated, consistent with existing `GET /accounts`, `GET /transactions` |
| V5 Input Validation | Yes | Pydantic v2 schemas (`HoldingCreate`, `PortfolioEventCreate`, `PlatformCreate`) validate all new inputs at the API boundary — same pattern as `TransactionCreate`/`AccountCreate`; `event_type` should be constrained to the literal set `{"buy","sell","dividend"}` (Pydantic `Literal` or enum), not a free string, to prevent the recompute function from silently ignoring an unrecognized event type |
| V6 Cryptography | No | No new secrets/crypto — CoinGecko free tier needs no API key; yfinance needs none |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|----------------------|
| SSRF via user-controlled ticker string passed into an external HTTP call (CoinGecko/yfinance) | Tampering / Information Disclosure | Tickers are looked up against a fixed, server-side `TICKER_TO_COINGECKO_ID` map (crypto) or passed through `yfinance.Ticker(f"{ticker}.JK")` where `ticker` should be validated against `holdings.ticker` (already-stored, alphanumeric, `String(32)`) rather than accepting arbitrary user input directly into the outbound request — this is a natural consequence of D-08's design (adapters are keyed by `asset_type` + looked-up ticker, not a free-text URL param), not a new control to add |
| Unbounded `portfolio_events` growth or malformed event data corrupting the recompute algorithm | Tampering | `event_type` constrained via Pydantic `Literal["buy","sell","dividend"]`; `quantity`/`price` validated as positive `Decimal` at the schema layer before `apply_add_portfolio_event` ever runs the recompute (never trust the recompute function to sanity-check inputs it receives) |
| Scheduler job as a privilege-escalation or DoS vector (a background job running with elevated/implicit trust vs. an authenticated request) | Denial of Service | The daily job only reads/writes `price_cache` and `portfolio_value_history` using the same `get_session_sync()` path as authenticated request handlers — no new trust boundary is created; `max_instances=1` + `misfire_grace_time` prevent runaway concurrent job execution from exhausting DB connections |
| Audit log completeness for the new direct-override escape hatch (D-03) | Repudiation | Every `apply_*` write for holdings/events/platforms MUST write an `AuditLog` row (before/after), including the D-03 direct holding-override path — do not add a "quick" write path that skips `writes.py`'s established audit pattern |

## Sources

### Primary (HIGH confidence)
- PyPI JSON API (`https://pypi.org/pypi/<pkg>/json`) — verified `yfinance` 1.5.1 (first release 2019-05-26, 147 releases), `apscheduler` 3.11.3 (first release 2009-08-01, 59 releases), `pycoingecko` 3.2.0 (first release 2019-01-10, 18 releases) — checked live this session via `curl`.
- In-repo verification via `Read`/`Bash grep` (per graphify-first protocol, after graphify orientation): `alembic/versions/002_new_tables.py`, `003_app_settings.py`, `backend/models.py`, `backend/db.py`, `backend/writes.py`, `backend/settings.py`, `backend/entrypoint.sh`, `backend/Dockerfile`, `ui/app/investments/page.tsx`, `pyproject.toml` pytest config, `backend/tests/test_write_tools.py`.
- `gsd-tools query package-legitimacy check --ecosystem pypi yfinance apscheduler pycoingecko` — automated seam check (all three flagged SUS on a checker limitation, manually resolved via PyPI history above).
- `uv pip install --dry-run yfinance apscheduler pycoingecko` — confirms all three resolve cleanly with no conflicting transitive dependencies against this project's existing pinned versions.

### Secondary (MEDIUM confidence)
- WebSearch: CoinGecko `/simple/price` free-tier rate limits (Demo plan ~100 calls/min/10k monthly vs. unauthenticated ~5-15 calls/min) — cross-referenced across `support.coingecko.com` and `docs.coingecko.com` result snippets.
- WebSearch: CoinGecko `coins/list` symbol-collision issue (~12,900 coins vs. ~10,600 unique symbols) — corroborated by two independent community sources (`BittyTax/BittyTax#238`, `buchen/portfolio#2464`).
- WebSearch: yfinance `.JK` suffix confirmed via Yahoo Finance's own `BBCA.JK` quote page showing IDR currency and "Jakarta delayed quotes."
- WebSearch: APScheduler + FastAPI `lifespan` integration pattern, `coalesce`/`misfire_grace_time`/`max_instances` semantics — cross-referenced across FastAPI's own docs (`fastapi.tiangolo.com/advanced/events/`) and multiple tutorial sources.
- WebSearch: Indonesian reksadana NAV — no official free API found; only unofficial scrapers (`risan/indonesia-market`, `risan/bibit-reksadana` on GitHub) surfaced, confirming the CONTEXT.md's own assumption behind D-08/INVX-02.

### Tertiary (LOW confidence)
- yfinance `fast_info["lastPrice"]` attribute name and exact key casing — based on training knowledge of the yfinance API surface, not verified against a live call this session (WebSearch for this specific detail was unavailable). Flagged in Open Questions/Assumptions Log as a Wave-0 smoke-test item, not a locked assumption.
- Average-cost basis formula (textbook finance knowledge, not project-specific) — standard and uncontroversial, but not fetched from an authoritative external source this session since it directly restates the already-locked D-02 wording.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all three packages verified live against PyPI's JSON API (existence, version, full release history); legitimacy-check false-positives manually resolved with evidence.
- Architecture: HIGH — every pattern (adapter registry, recompute algorithm, lifespan scheduler) is directly derived from in-repo conventions already established in Phases 1-4 (`TOOLS` registry, `writes.py` audit pattern, `get_session_sync`), not invented from scratch.
- Pitfalls: MEDIUM-HIGH — CoinGecko symbol collisions and APScheduler misfire semantics are corroborated by multiple independent sources; yfinance's exact `fast_info` key casing is the one genuinely LOW-confidence implementation detail, explicitly flagged for Wave-0 verification.
- Migration ambiguity (CLAUDE.md vs. D-17): HIGH — resolved by direct inspection of `alembic/versions/`, not inference; CLAUDE.md's "no Alembic today" text is demonstrably stale.

**Research date:** 2026-07-06
**Valid until:** 2026-08-05 (30 days — external API surfaces (CoinGecko, yfinance) can shift faster than this; re-verify adapter behavior if implementation is delayed beyond a few weeks)
