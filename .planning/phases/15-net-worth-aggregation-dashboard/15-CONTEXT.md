# Phase 15: Net Worth Aggregation + Dashboard - Context

**Gathered:** 2026-07-31
**Status:** Ready for planning

> **Mode:** `--auto go with all recs`. Every decision below is the **recommended
> option**, auto-selected in a single pass. Any can be vetoed before planning.

<domain>
## Phase Boundary

Deliver **one trustworthy net-worth number** = liquid accounts + investment
platforms, with each real account/holding counted **exactly once**, plus the
**liquid vs investment split with a per-side breakdown** shown on the main
dashboard.

**In scope:** a net-worth aggregation read (backend) + its dashboard display;
the type-coverage assertion (SC #3). Requirements NW-01, NW-02.

**Out of scope (own phases):** account/platform manager CRUD, Records tab,
record-input modal, PnL/buy-sell history views (Phase 16); any new transfer or
funding write mechanics (Phase 13/14, already shipped).
</domain>

<decisions>
## Implementation Decisions

### Aggregation seam (where net worth is computed)
- **D-01:** Add a **new dedicated read** — a `net_worth` tool in `tools.py`
  plus a `GET /net-worth` endpoint — that **composes the two existing
  single-source reads** rather than re-summing rows: liquid side from the
  account-balance aggregation (filtered to `type='liquid'`), investment side
  from `portfolio.portfolio_summary(db).total_value`. Rationale: keeps
  `cashflow_summary` spending-scoped (it already notes the net-worth split is
  "Phase 15 discretion item D" in `account_balances`), gives one obvious home
  for the coverage assertion, and lets the same number be exposed as an agent /
  MCP read tool.
- **D-02:** Register `net_worth` on the **read-only surfaces**: add it to
  `READ_TOOL_NAMES` so it flows onto the MCP read server and the agent's read
  tools. It reads only; it never writes. (Keeps the 15→now read-tool safety
  contract intact — see the TOOLS-registry memory.)

### Liquid/investment partition (the double-count guard — SC #1)
- **D-03:** Partition **by `accounts.type`**, the DB-enforced binary closed set
  `IN ('liquid','investment')` from migration 010. **Liquid side** = SUM of
  derived balances (non-transfer transactions) for `type='liquid'` accounts
  only. **Investment side** = `portfolio_summary.total_value` (holdings × price,
  cash holdings via FX) — the single source of truth for investment value.
- **D-04:** `type='investment'` accounts (e.g. legacy account id 3
  "Investments") are **excluded from the liquid sum** — their money now lives on
  the investment side as holdings / portfolio events. Broker **cash** stays on
  the liquid side because it is typed `liquid` (e.g. Stockbit id 559). This is
  the "counted exactly once" rule **by construction**: an investment account's
  value comes from the portfolio, never from its own account balance, so it can
  never be double-added. Reuse the existing `type != 'liquid'` /
  `cashflow_transactions` discriminator pattern rather than inventing a new one.

### Coverage assertion (SC #3 — 100% of accounts classified)
- **D-05:** The `net_worth` read **asserts total coverage**: `liquid_count +
  investment_count == COUNT(*) accounts`, with **zero unclassified rows**. The
  DB `NOT NULL` + `ck_accounts_type` CHECK already guarantee every row is
  `liquid` or `investment`, so the assertion is cheap; it exists to fail
  **loudly** (raise `ValueError`, not silently drop/double-count) if the schema
  invariant is ever violated — consistent with the repo's correctness-by-
  construction, loud-raise precedent (Phase 13 D-04). Return an explicit
  `accounts_covered` / expected count in the payload so the assertion is visible
  and testable.
- **D-06:** Ship a **test** that (a) proves an all-liquid + all-investment mix
  sums to the exact expected net worth with each row counted once, and (b)
  proves an account with an out-of-set/unexpected type triggers the loud raise.

### Dashboard presentation (NW-02 — split + per-side breakdown)
- **D-07:** Surface net worth on the **existing main dashboard** — the
  `/cashflow` page (root `/` already redirects there), rescoping its summary to
  **lead with the net-worth headline**, not a brand-new page. Phase 16 extends
  the deeper component set.
- **D-08:** Show **combined net-worth headline** + a **two-side split** (liquid
  total / investment total) + a **per-side breakdown**: liquid = per-account
  balances (reuse the existing account-balance rows/cards); investment =
  per-platform subtotals from `portfolio_summary` groups. Reuse existing
  dashboard card/summary components — no new design system work.

### Claude's Discretion
- Exact payload field names / Pydantic schema shape for the `net_worth` read
  (planner + researcher decide, mirroring existing `CashflowSummary` /
  `PortfolioSummary` conventions).
- Whether the liquid per-account rows come from extending `account_balances`
  (to carry `type`) or a small dedicated query — planner's call; the constraint
  is that the liquid sum counts `type='liquid'` only.
- Frontend layout details of the headline/split cards within the existing
  dashboard styling.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & roadmap
- `.planning/REQUIREMENTS.md` — NW-01 (net worth = liquid + investment, each
  once), NW-02 (liquid vs investment split with per-side breakdown).
- `.planning/ROADMAP.md` §"Phase 15" — goal, depends-on (Phase 12 typed
  accounts, Phase 13 transfer/funding writes), 3 success criteria.
- `.planning/PROJECT.md` §"Current Milestone" — the single-net-worth,
  no-double-count design intent for v1.2.

### Prior locked decisions this phase builds on
- `alembic/versions/010_typed_accounts.py` — **the partition contract**:
  `accounts.type IN ('liquid','investment')`, NOT NULL, default `liquid`;
  `ACCOUNT_TYPE` backfill map (id 3 "Investments" → investment = the real
  double-count; id 559 Stockbit → liquid = broker cash); the
  `cashflow_transactions` view's `type != 'liquid'` exclusion pattern.
- `.planning/phases/13-shared-mutation-layer-transfer-buy-sell-with-funding-adjustm/13-CONTEXT.md`
  §"Liquid→investment transfer" (D-05) — investment money is **never** a
  synthetic `accounts` row; it lives as holdings / portfolio events (why the
  investment side reads the portfolio, not account balances).

### Existing code the read composes
- `backend/tools.py` `account_balances()` (~L474) — per-account derived balance;
  note its own comment deferring the liquid/investment split to Phase 15.
- `backend/portfolio.py` `portfolio_summary()` (~L174) — investment
  `total_value` (+ per-platform `groups`, `asset_type_groups`); the investment
  side source of truth.
- `backend/main.py` `cashflow_summary()` (~L699) — the sibling composed-read /
  endpoint pattern to mirror (period resolve → compose tools → typed response).
- `backend/tools.py` `TOOLS` / `READ_TOOL_NAMES` — registry the new read joins
  (read-only surface for MCP + agent).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `account_balances(period_start, period_end)` — already computes per-account
  derived balances from non-transfer transactions; the liquid breakdown reuses
  it (needs `type` to filter to `liquid`).
- `portfolio_summary(db)` — already returns `total_value` + per-platform
  `groups`; the investment total and breakdown come straight from it.
- `cashflow_summary` endpoint — the composed-read template (period resolve →
  compose → typed Pydantic response, open read, no `require_api_key`).
- Existing `/cashflow` dashboard page + its summary/card components — the
  headline and split render inside these.

### Established Patterns
- **Registry pattern:** new read goes in `TOOLS` and `READ_TOOL_NAMES`
  (read-only classification is what keeps it off the MCP write surface).
- **Correctness-by-construction + loud raise:** invariant violations raise
  `ValueError` (→ 422 at the API layer), never silent drops (Phase 13 D-04).
- **Parameterized SQL / no LLM SQL:** any query uses SQLAlchemy `text()` with
  bound params.
- **Derived balances:** account balances are always summed from transactions,
  never a stored column (Phase 13 D-07).

### Integration Points
- New `net_worth` tool → `TOOLS` + `READ_TOOL_NAMES` → MCP read server +
  agent read tools + `GET /net-worth`.
- Dashboard: `/cashflow` page consumes the new endpoint (or the extended
  cashflow payload) for the headline + split.

</code_context>

<specifics>
## Specific Ideas

- Reference model for the dashboard is BudgetBakers Wallet (captured
  2026-07-18) — net worth prominent, clean split. No new design system.
- The partition is intentionally the SAME discriminator the
  `cashflow_transactions` view already uses (`type='liquid'`), so cashflow and
  net worth can never disagree about what counts as liquid.

</specifics>

<deferred>
## Deferred Ideas

- Records tab, account/platform managers, record-input modal, PnL/buy-sell
  history — **Phase 16** (UI — Extend Existing Components).
- Net-worth history / trend-over-time chart — not in NW-01/NW-02; note for a
  future phase if wanted.

None else — discussion stayed within phase scope.

</deferred>

---

*Phase: 15-net-worth-aggregation-dashboard*
*Context gathered: 2026-07-31*
