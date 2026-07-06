# Phase 5: Investment Subsystem - Context

**Gathered:** 2026-07-06
**Status:** Ready for planning

<domain>
## Phase Boundary

Grow the interim `/investments` skeleton (from Phase 3) into a real investment
tracker: holdings backed by a buy/sell/dividend event ledger, live prices with
per-instrument staleness, realized + unrealized P&L and total portfolio value in
IDR, platform (app/broker) grouping, and spending↔portfolio correlation queries
in chat.

This phase delivers:
- **Holdings** managed through a **buy/sell/dividend event ledger**
  (`portfolio_events` is the source of truth); position `quantity`/`avg_cost` are
  recomputed from events (INV-01, INV-07).
- **Live prices** routed per asset type (crypto→CoinGecko, IDX→yfinance `.JK`,
  funds/other→manual), all denominated in **IDR**, flowing through the single
  `price_cache` table, with a per-asset-type **staleness** badge (INV-02, INV-03,
  INV-05).
- **Manual price set/override** (INV-04).
- **Realized + unrealized P&L snapshot**, per-holding and total portfolio value
  with an "as of" timestamp (INV-06).
- **Platform grouping** — a managed `platforms` entity so holdings are grouped by
  the app/broker they live in.
- A **daily portfolio-value history collector** (per-holding snapshots) so the
  deferred v2 time-series chart has data (data collection only this phase).
- **Correlation queries** in chat: "since I bought BBCA, how has my eating-out
  spending changed?" (CHAT-03).

Out of scope (own phases / v2): the historical P&L **line chart** itself
(v2/INVX-01 — only its data collector ships now); automated reksadana NAV feed
(v2/INVX-02); multi-currency/FX normalization (parked project-wide); MCP server
(Phase 6); write tools over MCP. Page visual layout is delegated to
`/gsd-ui-phase`.

**Requirements covered:** INV-01, INV-02, INV-03, INV-04, INV-05, INV-06, INV-07,
CHAT-03.

</domain>

<decisions>
## Implementation Decisions

### Holdings ↔ Events Model (keystone)
- **D-01:** `portfolio_events` is the **source of truth** for trades.
  `holdings.quantity` and `holdings.avg_cost` are **recomputed from the event
  ledger** — the user records buy/sell/dividend events; the position falls out of
  them. `event_type ∈ {buy, sell, dividend}`.
- **D-02:** Cost basis = **average cost**. `avg_cost = total cost of open qty /
  open qty`; a sell realizes `(sell_price − avg_cost) × sold_qty` and leaves
  `avg_cost` unchanged. **Dividends are supported this phase** and fold into
  realized return. (FIFO explicitly rejected — see Deferred.)
- **D-03:** **Direct holding-override escape hatch.** Although the position is
  normally derived from events, a **direct manual edit/delete of the holding row**
  is allowed (e.g. seed an opening position without itemizing history, or
  force-correct). Overrides are **audit-logged** like every other write.
- **D-04:** INV-01 "add/edit/remove holdings" therefore means: normally
  record/edit/delete the underlying **events** (position recomputes); a holding
  whose net quantity reaches zero drops off the active list. The D-03 override is
  the exception path.

### P&L & Portfolio Value
- **D-05:** Ship a **realized + unrealized P&L snapshot** now. Unrealized =
  `(current price − avg_cost) × open qty`. Realized = from sell events
  (average-cost) + dividends. Also show **total portfolio value** with an
  **"as of" timestamp** (INV-06).
- **D-06:** The **historical time-series line chart** (P&L / value over time) is
  **deferred to v2 (INVX-01)**. Only its **data collector** ships now (D-13/D-14).

### Currency
- **D-07:** **Everything in IDR, no FX.** Fetch all prices directly in IDR
  (CoinGecko `vs_currency=idr`; yfinance `.JK` is native IDR). User enters
  buy/sell prices and `avg_cost` in IDR. `holdings.currency` stays IDR. Consistent
  with the project-wide "multi-currency parked" stance — no FX rate source, no
  conversion anywhere.

### Prices, Sources & Staleness
- **D-08:** Price **source is routed by `asset_type`**: crypto→CoinGecko,
  idx_stock→yfinance (`.JK`, best-effort with fallback), mutual_fund/other→manual.
  The Phase-3 global `price_data_source` setting becomes a **fallback/default**,
  not the per-holding selector. Implement as a **pluggable adapter registry**
  (mirror the `TOOLS` registry pattern); adapter-registry shape is Claude's
  discretion.
- **D-09:** Live prices are fetched **lazily on `/investments` load** for any
  ticker whose cached price is older than its TTL, **plus a manual "Refresh
  prices" button** that force-fetches all. All prices (fetched *and* manual) flow
  through the single `price_cache` table — one read path for "current price".
- **D-10:** **Per-asset-type staleness TTL defaults** (crypto ~minutes, IDX ~1
  day / intraday during market hours, mutual_fund/manual flagged stale after N
  days). Exact numbers are Claude's discretion / research-informed. Each price
  shows an **"as of [time]" badge** and a **visual stale indicator** once older
  than its TTL (INV-05).
- **D-11:** **Manual price override (INV-04)** writes `price_cache` with
  `source='manual'` and is immediately reflected in P&L. A manual price is treated
  as the **newest value and is REPLACED by the next successful live fetch** — so
  it persists naturally only for manual-only instruments (mutual funds/other,
  which have no live source); for crypto/IDX it is a temporary correction.

### Platform Grouping
- **D-12:** **Managed `platforms` entity** — a new table with its own CRUD
  (mirrors the Phase-4 account manager); `holdings.platform_id` references it. The
  Investments page groups holdings **by platform** with per-platform subtotals.
  Purely organizational — **no effect on P&L math**. (Driver: the user holds
  assets across different apps — crypto app, stock brokerage, reksadana app — and
  wants them grouped like cashflow accounts.)

### History Collection (feeds the deferred v2 chart)
- **D-13:** New **`portfolio_value_history`** table storing **one row per holding
  per day**: `snapshot_date`, holding/ticker, `quantity`, `market_value`,
  `cost_basis` (→ unrealized), `currency=IDR`. This per-holding granularity lets
  the future v2 chart split by **holding / platform / asset_type** or sum to a
  total; realized P&L over time derives from `portfolio_events`. History **cannot
  be backfilled** — collection starts this phase.
- **D-14:** Snapshots are written by an **in-process APScheduler** started in the
  **FastAPI app lifespan** (no new container, no host cron). It runs **daily** to
  guarantee ≥1 data point/day (→ week/month roll-ups), refreshing prices before
  snapshotting. This is the stack's **first always-on background component** —
  accept the new failure mode. Exact time-of-day is Claude's discretion.

### Correlation Queries (CHAT-03)
- **D-15:** Add **new read tool(s) to `backend/tools.py`** (LLM never emits SQL).
  For "since I bought X, how has my `<category>` spending changed?": resolve the
  pivot date as the **earliest buy event for that ticker in `portfolio_events`**,
  then compare category spending in the **equal-length window after vs before**
  that date (N = days since purchase). Return before/after totals + the delta so
  the agent can state a concrete number.

### Write Path & Schema
- **D-16:** Holdings, events, and platform CRUD use **direct auth-protected REST +
  the shared `backend/writes.py` helpers + `audit_log` + `Decimal`** (the Phase-4
  D-01/D-02 pattern) — the button click is the confirmation; the Phase-2
  propose→confirm token dance is not used on the direct UI path. (The chat agent
  may still *propose* holding writes via the existing propose→confirm path.)
- **D-17:** **Migration needed.** New tables `platforms`, `portfolio_value_history`;
  new column `holdings.platform_id` (FK). `holdings`, `portfolio_events`,
  `price_cache` already exist (Phase 1) and are reused as-is (`event_type` already
  a string that now carries `buy|sell|dividend`).

### Claude's Discretion
- Exact per-asset-type TTL numbers; price-adapter registry shape; `asset_type`
  enum exact values (e.g. `crypto` / `idx_stock` / `mutual_fund` / `other`);
  dividend/realized-return presentation; snapshot scheduler time-of-day; how
  per-platform subtotals render; Investments page visual layout (→ `/gsd-ui-phase`).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & requirements
- `.planning/ROADMAP.md` §"Phase 5: Investment Subsystem" — goal + 6 success
  criteria (holdings CRUD, live prices w/ staleness, per-source routing, manual
  override, total value + "as of", portfolio events enabling correlation).
- `.planning/REQUIREMENTS.md` — INV-01…INV-07 + CHAT-03 definitions; the
  "Out of Scope" table (multi-currency/FX parked; single-currency IDR holds) and
  v2 list (INVX-01 historical value, INVX-02 reksadana NAV) that this phase
  deliberately defers to.

### Prior decisions this phase builds on
- `.planning/phases/03-multi-page-ui-shell-settings/03-CONTEXT.md` — the
  `price_data_source` enum (`coingecko|yfinance|manual`) and base-currency
  settings in `app_settings`, `/investments` skeleton, `/api/[...proxy]` key
  injection, inline-styles + `ui/app/styles.ts`.
- `.planning/phases/04-cashflow-dashboard-crud/04-CONTEXT.md` — the direct-REST
  write pattern (D-01), shared `backend/writes.py` helpers (D-02), Recharts, and
  the **account manager (reassign-then-delete) that the `platforms` entity
  mirrors**.
- `.planning/codebase/ARCHITECTURE.md`, `CONVENTIONS.md`, `STACK.md`,
  `INTEGRATIONS.md` — layering, `ValueError`→422 error convention,
  parameterized-SQL rule, registry pattern, external-integration inventory.

### Key existing code (verified during scout)
- `backend/models.py` — `Holding` (L126), `PortfolioEvent` (L147),
  `PriceCache` (L176), `AppSetting` (L160). **Base investment tables already exist
  from Phase 1** — only `platforms`, `portfolio_value_history`, and
  `holdings.platform_id` are new.
- `backend/writes.py` — shared `apply_*` helpers + audit pattern; extend for
  holding/event/platform writes (one write path).
- `backend/tools.py` — read/aggregation tools + `resolve_period()`/`PERIODS`;
  add the correlation tool(s) here (D-15).
- `backend/settings.py` — `price_data_source` accessor (fallback for D-08).

### Research flag (carried from ROADMAP.md)
- Verify **yfinance `.JK` / IDX ticker coverage** and the manual-fallback path for
  **reksadana** before/while planning — free IDX/reksadana price APIs are weak;
  manual is the guaranteed fallback (INV-03/INV-04). CoinGecko crypto-in-IDR is
  well-supported.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `backend/writes.py` `apply_*` helpers + `audit_log` writes — extend the same
  pattern for holdings/events/platforms so every write is audited + `Decimal`.
- Phase-4 **AccountManager** (UI) + reassign-then-delete backend — the direct
  template for the new **platform manager** and its CRUD.
- `backend/tools.py` `resolve_period()` + spending aggregations — feed the
  correlation tool's before/after windows.
- `backend/models.py` `Holding` / `PortfolioEvent` / `PriceCache` — reuse as-is.
- `backend/settings.py` — read `price_data_source` as the routing fallback.
- Recharts (already a dep), `ui/app/styles.ts`, `ui/app/api/[...proxy]/route.ts`
  key injection.

### Established Patterns
- Direct REST writes go through `require_api_key`, raise `ValueError`→422, use
  parameterized SQL / SQLAlchemy ORM, store money as `Decimal`.
- Pydantic v2 schemas by role (`*Create`, `*Out`, `*Request`) in
  `backend/schemas.py`.
- **Registry pattern** (`TOOLS` dict in `tools.py`) — mirror it for the pluggable
  **price adapters** (D-08).
- `price_cache` is the single read path for "current price" (fetched or manual).
- Inline `React.CSSProperties` styling; no CSS framework.

### Integration Points
- `backend/main.py` — new holdings/events/platforms CRUD endpoints, a
  price-refresh endpoint, and the **APScheduler startup in the app lifespan**
  (D-14); correlation surfaces via the existing agent `/query` path (new tool).
- New price-adapter module (CoinGecko / yfinance / manual) keyed by `asset_type`.
- `alembic/versions/` — one new migration (D-17).
- `backend/schemas.py` — DTOs for holdings/events/platforms + P&L/portfolio
  payloads.
- `ui/app/investments/page.tsx` — grow the skeleton into the tracker (layout →
  `/gsd-ui-phase`).

</code_context>

<specifics>
## Specific Ideas

- The user holds assets **across multiple apps** (a crypto app, a stock
  brokerage, a reksadana app) — **platform grouping is a first-class part of this
  phase**, mirroring how cashflow "accounts" are real-world buckets.
- The user wants **both realized and unrealized** P&L visible, and eventually a
  P&L **line chart that can be split per platform** — which is exactly why the
  daily history is captured at **per-holding granularity now** (can't backfill).

</specifics>

<deferred>
## Deferred Ideas

- **INVX-01 — historical portfolio-value / P&L time-series line chart** (v2). Its
  **data collector ships now** (D-13/D-14); only the chart UI is deferred.
- **INVX-02 — automated reksadana NAV feed** (v2). Manual price is the fallback
  this phase.
- **Multi-currency / FX normalization** — parked project-wide; everything IDR (D-07).
- **FIFO cost basis** — rejected in favor of average cost (D-02).
- **Write tools over MCP to external clients** — Phase 6 exposes read-only tools.

None of the above belong in Phase 5 — discussion stayed within scope.

</deferred>

---

*Phase: 5-investment-subsystem*
*Context gathered: 2026-07-06*
