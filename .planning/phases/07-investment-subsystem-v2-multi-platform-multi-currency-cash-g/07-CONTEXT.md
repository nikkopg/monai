# Phase 7: Investment Subsystem v2 (multi-platform, multi-currency, cash, gold, viz) - Context

**Gathered:** 2026-07-12
**Status:** Ready for planning

<domain>
## Phase Boundary

Make the portfolio reflect how the user **actually** holds assets, and surface
allocation + history at a glance. Six scope items:

1. **Multi-platform holdings** — same asset on multiple platforms as distinct
   positions. **ALREADY SHIPPED** pre-discussion (quick task `260711-rb2`,
   migration 006: identity `ticker → (ticker, platform_id)`, `platform_id NOT
   NULL`, `portfolio_events.platform_id`; migration 007 widened the snapshot
   key). The **only** remaining thread is the chat write-path ripple (item 6
   below / CH-01).
2. **Multi-currency + FX** — cost basis stored in the currency the asset was
   bought in, converted to IDR for display/P&L. Reverses Phase 5's "everything
   IDR, no FX" stance (D-07).
3. **Cash** as a first-class position (idle IDR / USDT balances).
4. **Physical gold** as a first-class position (grams × price).
5. **Allocation pie chart** — allocation at a glance (Recharts).
6. **Historical value/P&L line chart** — pulled in from the deferred v2 item
   **INVX-01** during this discussion (2026-07-12). Its data pipeline
   (`portfolio_value_history` + daily snapshot scheduler) already shipped in
   Phase 5 (D-13/D-14); only the chart UI was deferred.

Plus the leftover chat ripple from item 1 (CH-01).

**Note:** No SPEC.md was run (ROADMAP suggested `/gsd-spec-phase 7` first). The
currency model was the reason for that suggestion; it is pinned down below, so
discuss covers it. Requirements are derived here, not from a SPEC.

</domain>

<decisions>
## Implementation Decisions

### Currency & FX model (scope item 2 — the keystone)
- **FX-01:** USD→IDR rate comes from a **live FX API**, implemented as an
  **adapter routed through the same registry pattern as price adapters** (Phase 5
  D-08). It MUST support **by-date historical rate lookups** (not just current
  spot) — required by FX-03. The specific free API is a **research task** (must
  cover IDR + historical; candidates: exchangerate.host, frankfurter — verify IDR
  coverage, ECB-based sources may lack IDR).
- **FX-02:** **Arbitrary per-holding currency.** Holdings carry a general
  `currency` column; any currency convertible to IDR is allowed (not restricted
  to USD+IDR). USDT is treated as ≈1:1 USD.
- **FX-03:** **Historical-at-purchase P&L semantics.** Cost basis is converted at
  the **trade-date** rate; current value at the **current** rate. Unrealized P&L
  therefore **includes FX gain/loss** — a true IDR return, not just the asset's
  native-currency move.
- **FX-04:** **No per-event FX-rate column.** Store only **native cost +
  currency** on the event; the historical rate is **re-fetched by date** from the
  FX cache at compute time. (User accepted the tradeoff that P&L then depends on
  the FX cache rather than a frozen per-event number.)
- **FX-05 (guard for FX-04):** The FX adapter MUST **cache historical by-date
  rates immutably**, keyed by `(date, currency_pair)` (mirroring `price_cache`),
  so a re-fetch returns the previously-stored value rather than re-hitting the
  vendor. This is what keeps historical P&L **stable/reproducible** despite the
  no-column choice — planner must not skip it.

### Cash & gold positions (scope items 3 & 4)
- **CG-01:** **Cash = directly-set balance.** New `asset_type=cash`; the balance
  is set/edited directly via the Phase-5 **D-03 holding-override path** (no
  buy/sell event itemization). IDR value = `amount × FX-to-IDR` (FX-01). No cost
  basis / no unrealized gain **except** FX movement.
- **CG-02:** **Gold = normal ledger holding.** New `asset_type=gold`,
  `quantity` = grams, price = **per-gram**. Full cost basis + unrealized P&L,
  exactly like any other ledger position (Phase 5 D-01/D-02).
- **CG-03:** **Gold price is manual per gram**, written to `price_cache` with
  `source='manual'` and refreshed like reksadana manual prices. A **live gold
  spot adapter is deferred** — addable later via the D-08 registry.

### Allocation pie chart (scope item 5)
- **VZ-01:** Recharts **pie**, value basis = **current IDR market value**, with a
  **toggle: asset-type ↔ platform** (both groupings already exist on the page).
  Exact placement on `/investments` → `/gsd-ui-phase`.

### Historical line chart (scope item 6 — INVX-01, pulled into this phase)
- **VZ-02:** Source = `portfolio_value_history` (stores `market_value` +
  `cost_basis` in IDR per position per day). **Two views, "like Bitget":**
  (a) **total portfolio value over time**, and (b) **unrealized P&L over time**
  (`market_value − cost_basis`, both already snapshotted), with a **time-range
  selector**. Realized P&L still derives from `portfolio_events` separately.
  History **starts at collector go-live — no backfill** (Phase 5 D-13). Exact
  interactions / range presets / splitting → `/gsd-ui-phase`.

### Chat multi-platform ripple (leftover from scope item 1)
- **CH-01:** Add a **`find_platforms`** (list-with-id) read tool mirroring
  `find_transactions` / the needed `find_accounts`. The agent **resolves the
  platform and asks the user which one** when unspecified/ambiguous, then includes
  `platform_id` in the proposal so `propose_add_holding` /
  `_execute_proposal_payload`'s `add_holding` branch satisfies the new NOT NULL
  constraint (fixes the STATE-logged chat-write regression). **Also add the
  analogous `find_accounts` read tool** — it fixes the parallel account-id gap
  logged in STATE.md "Pending Todos" (would otherwise block chat "delete my BCA
  account").

### Claude's Discretion / research-informed
- Specific free **FX API** (must support IDR + historical by-date) — research.
- New **`asset_type` enum values** (`cash`, `gold`) exact strings; extends the
  Phase-5 set (`crypto` / `idx_stock` / `mutual_fund` / `other`).
- **Migration & backfill:** add `holdings.currency` (default `IDR`); existing
  IDR holdings/avg_costs stay as-entered. Cash-position storage shape.
- Pie/line **placement, range presets, toggle rendering** → `/gsd-ui-phase`.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & requirements
- `.planning/ROADMAP.md` §"Phase 7: Investment Subsystem v2" — 6 scope items
  (item 6 / line chart added 2026-07-12 during this discussion).
- `.planning/REQUIREMENTS.md` — INV-01…INV-07, CHAT-03, and **INVX-01**
  (historical value chart — now in-scope, was v2).

### Prior decisions this phase builds on / revises
- `.planning/phases/05-investment-subsystem/05-CONTEXT.md` — **the** reference.
  Reuses: D-01/D-02 (event ledger, average cost), **D-03 (direct holding
  override — CG-01 rides this)**, **D-08 (pluggable adapter registry — FX and
  gold adapters extend it)**, D-09 (`price_cache` single current-price path),
  D-12 (platforms), **D-13/D-14 (`portfolio_value_history` + daily snapshot
  scheduler — VZ-02's data source)**. **REVISES D-07** (IDR-only/no-FX is
  deliberately reversed by FX-01…FX-05).
- `.planning/phases/04-cashflow-dashboard-crud/04-CONTEXT.md` — direct-REST
  audited write pattern; Recharts usage.

### State & the two open ripples
- `.planning/STATE.md` — "Deferred Items" (item-1 chat ripple → CH-01; INVX-01)
  and "Pending Todos" (missing `find_accounts` id tool → CH-01).
- `.planning/phases/05-investment-subsystem/quick/260711-rb2-multi-platform-holdings-same-asset-on-mu/`
  — the multi-platform implementation this phase completes.

### Codebase maps
- `.planning/codebase/ARCHITECTURE.md`, `CONVENTIONS.md`, `INTEGRATIONS.md`,
  `STACK.md` — layering, `ValueError`→422, parameterized-SQL, registry pattern,
  external-integration inventory.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `backend/writes.py` `apply_*` + `audit_log` + `Decimal` — extend for cash
  balances, gold holdings/events, and the currency-aware cost path.
- `backend/tools.py` — add `find_platforms` + `find_accounts` read tools (CH-01);
  correlation tool already here.
- **Price-adapter registry (D-08)** — add the **FX adapter** (FX-01) and, later,
  an optional gold spot adapter (CG-03 deferred).
- `price_cache` — single read path; gold manual prices (CG-03) and the FX
  historical cache (FX-05) follow its shape.
- `portfolio_value_history` (migrations 006/007) — VZ-02's data source, already
  per `(date, ticker, platform_id)`.
- Recharts (dep), `ui/app/investments/page.tsx`, `ui/app/styles.ts`,
  `ui/app/api/[...proxy]/route.ts` key injection.

### Established Patterns
- Direct REST writes: `require_api_key`, `ValueError`→422, parameterized SQL,
  money as `Decimal`; Pydantic v2 `*Create`/`*Out`/`*Request` schemas.
- Registry pattern (`TOOLS` dict, price adapters) — FX/gold adapters mirror it.
- Agent write path = propose→confirm; read tools resolve name→id first (CH-01).

### Integration Points
- `alembic/versions/` — migration(s): `holdings.currency`, new `asset_type`
  values, cash-position storage. Follow the migration-007 reversible pattern.
- `backend/main.py` — currency-aware holding/event endpoints; pie + line-chart
  data endpoints (or extend the summary/history endpoints).
- New **FX adapter module**; extend valuation to convert native cost→IDR by date.
- `ui/app/investments/page.tsx` — pie (VZ-01) + line chart (VZ-02); layout →
  `/gsd-ui-phase`.

</code_context>

<specifics>
## Specific Ideas

- The line chart should be **"like Bitget"** — a portfolio-value curve **and** a
  P&L curve with a time-range selector (VZ-02).
- The user genuinely holds assets in **multiple currencies across multiple apps**;
  crypto avg-costs are entered in **USD** — hence the full multi-currency model
  (arbitrary currency, historical-at-purchase) rather than a shortcut.

</specifics>

<deferred>
## Deferred Ideas

- **Live gold spot adapter** — manual per-gram ships now (CG-03); a spot adapter
  is a later add via the D-08 registry.
- **INVX-02 — automated reksadana NAV feed** — still v2; manual price remains the
  fallback.
- **FIFO cost basis** — still rejected in favor of average cost (Phase 5 D-02).
- **INVX-01 line chart** — **no longer deferred**; pulled into this phase as
  scope item 6 (VZ-02).

</deferred>

---

*Phase: 7-investment-subsystem-v2*
*Context gathered: 2026-07-12*
