# Phase 5: Investment Subsystem - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-06
**Phase:** 5-investment-subsystem
**Areas discussed:** P&L view, Holdings↔events model, Currency & P&L math, Price refresh & staleness, Portfolio-value history, Correlation queries, Platform grouping, Scheduler deployment, Price-source routing, Manual price override, Dividends

---

## P&L view (user-added: "live total P&L chart — realized + unrealized")

| Option | Description | Selected |
|--------|-------------|----------|
| Current snapshot, realized+unrealized split | Live figure of today's total P&L; no time axis; stays in Phase 5 | |
| P&L over time (time-series line) | Line chart across months; needs price history; = INVX-01 (v2) | |
| Both — snapshot now, time-series later | Snapshot ships now; historical line deferred to v2/INVX-01 | ✓ |

**User's choice:** Both — snapshot now, time-series later
**Notes:** Triggered the whole history-collection thread; realized needs sale prices from portfolio_events.

---

## Holdings ↔ events model

| Option | Description | Selected |
|--------|-------------|----------|
| Auto-derive from holdings CRUD | Holdings form writes events implicitly | |
| Explicit buy/sell entry, position derived | Events are source of truth; qty + avg_cost recomputed | ✓ |
| Hybrid: CRUD + optional 'record trade' | Direct position edit + separate event log | |

**User's choice:** Explicit buy/sell entry ("current avg cost and qty is auto updated") — confirmed = option 2.
**Notes:** Follow-ups → **Events ledger + direct holding override** (audit-logged escape hatch) for INV-01 edit/remove; **Average cost** basis (not FIFO).

---

## Currency & P&L math

| Option | Description | Selected |
|--------|-------------|----------|
| Everything in IDR, no FX | Fetch prices in IDR (CoinGecko vs_currency=idr; yfinance .JK native); enter costs in IDR | ✓ |
| Store native currency + convert with FX | Native currencies + FX rate; reintroduces parked multi-currency | |

**User's choice:** Everything in IDR, no FX

---

## Price refresh & staleness

| Option | Description | Selected |
|--------|-------------|----------|
| Lazy on page-load + manual refresh button | Fetch stale-past-TTL on load; button force-fetches | ✓ (+ scheduler) |
| Manual refresh only | Update only on click | |
| Background scheduler | Periodic fetch regardless of page | |

**User's choice:** Lazy on page-load + manual refresh — "but we also need background scheduler for chart time series."
**TTL granularity:** Per asset-type defaults (chosen) vs single global TTL.
**Notes:** The scheduler ask is about history collection, not live-price freshness — split out below.

---

## Portfolio-value history (feeds deferred v2 chart)

| Option | Description | Selected |
|--------|-------------|----------|
| Snapshot-on-visit (no scheduler) | Append history row on each price refresh | |
| Real background scheduler now | Interval snapshots regardless of visits | ✓ |
| Defer all history to v2 | No history table/collector this phase | |

**User's choice:** Real background scheduler now — "not to backfill, just to make sure we have data points for each day, week, and month."
**Snapshot granularity:** **Per-holding rows** (chosen) over per-platform or single-total — because the user asked whether platform grouping would split the P&L line chart; per-holding keeps that option open (can't backfill).

---

## Correlation queries (CHAT-03)

| Option | Description | Selected |
|--------|-------------|----------|
| Equal-length before vs after purchase | Compare category spend N days after vs N days before buy date | ✓ |
| Since-purchase-to-now vs same-length prior | To-now emphasis; near-identical | |
| Monthly averages before vs after | Normalized monthly averages | |

**User's choice:** Equal-length before vs after purchase
**Buy-date resolution:** **Earliest buy event in portfolio_events** (chosen) over holdings.purchase_date.

---

## Platform grouping (user-added: "I use different apps for different assets")

| Option | Description | Selected |
|--------|-------------|----------|
| Free-text platform label + group-by | Nullable string column, UI group-by | |
| Managed platform entity | platforms table + CRUD; holdings.platform_id | ✓ |
| Reuse asset_type only, no platform | Group by asset_type instead | |

**User's choice:** Managed platform entity
**Notes:** Beyond INV-01's literal field list; treated as in-scope organizing dimension mirroring cashflow accounts. No effect on P&L math.

---

## Scheduler deployment

| Option | Description | Selected |
|--------|-------------|----------|
| In-process APScheduler in FastAPI | Runs in app lifespan; no new container | ✓ |
| Separate worker service | Dedicated compose container | |
| Host/docker cron → internal endpoint | External cron hits endpoint | |

**User's choice:** In-process APScheduler in FastAPI

---

## Price-source routing

| Option | Description | Selected |
|--------|-------------|----------|
| Route by asset_type | crypto→CoinGecko, idx_stock→yfinance, fund/other→manual; global setting = fallback | ✓ |
| Per-holding source override field | Route by asset_type + explicit per-holding pin | |
| Global setting for all | Single Phase-3 price_data_source for everything | |

**User's choice:** Route by asset_type

---

## Manual price override

| Option | Description | Selected |
|--------|-------------|----------|
| Sticks until cleared | Manual price never auto-overwritten | |
| Replaced by next live fetch | Manual is newest value; next successful fetch overwrites | ✓ |

**User's choice:** Replaced by next live fetch
**Notes:** Persists naturally only for manual-only instruments (funds/other) with no live source.

---

## Dividends / event types

| Option | Description | Selected |
|--------|-------------|----------|
| Buy/sell only, defer dividends | event_type = buy \| sell; column forward-compatible | |
| Include dividends now | Support 'dividend' events, fold into realized return | ✓ |

**User's choice:** Include dividends now

---

## Claude's Discretion

- Exact per-asset-type TTL numbers; price-adapter registry shape; asset_type enum
  exact values; dividend/realized-return presentation; snapshot scheduler
  time-of-day; per-platform subtotal rendering; Investments page visual layout
  (→ /gsd-ui-phase).

## Deferred Ideas

- INVX-01 historical P&L/value time-series line chart (v2) — data collector ships now.
- INVX-02 automated reksadana NAV feed (v2).
- Multi-currency / FX normalization — parked project-wide.
- FIFO cost basis — rejected for average cost.
- Write tools over MCP — Phase 6 read-only.
