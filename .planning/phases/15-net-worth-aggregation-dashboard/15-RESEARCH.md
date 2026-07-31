# Phase 15: Net Worth Aggregation + Dashboard - Research

**Researched:** 2026-07-31
**Domain:** Composed read aggregation (FastAPI + SQLAlchemy) over an existing typed-accounts schema; Next.js dashboard card composition
**Confidence:** HIGH — every recommendation below is grounded in code read directly from this repo (file:line cited), not external libraries. No new dependencies, no external API research needed.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
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

### Deferred Ideas (OUT OF SCOPE)
- Records tab, account/platform managers, record-input modal, PnL/buy-sell
  history — **Phase 16** (UI — Extend Existing Components).
- Net-worth history / trend-over-time chart — not in NW-01/NW-02; note for a
  future phase if wanted.

None else — discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-------------------|
| NW-01 | User sees a main dashboard where net worth = liquid accounts + investment platforms, each counted exactly once | New `net_worth()` tool composes `account_balances` (filtered `type='liquid'`) + `portfolio_summary().total_value`; coverage assertion (D-05) enforced with a loud `ValueError` raise; see Architecture Patterns, Pitfall 1 (fixes the live client-side double-count bug), Pitfall 3 (Session-handling requirement), Pitfall 4 (CASH sentinel is investment-side only) |
| NW-02 | User sees the liquid vs investment split with per-side breakdowns on the dashboard | `net_worth()` response returns liquid per-account rows (extended `account_balances` with `type`) and investment per-platform groups (`portfolio_summary.groups`); frontend renders both beside the existing hero card per D-07/D-08; see Code Examples, Validation Architecture |
</phase_requirements>

## Summary

Phase 15 is a **composition** phase, not a new-capability phase: every primitive it needs already exists and is already correctly typed. `account_balances()` (`backend/tools.py:474`) computes per-account derived balances; `portfolio_summary()` (`backend/portfolio.py:174`) computes the investment total; `accounts.type` is already a DB-enforced `CHECK ck_accounts_type IN ('liquid','investment')` column (migration `010_typed_accounts.py`) with **zero** possible unclassified rows today. The work is: (1) get `type` into the liquid-side computation so it can be filtered, (2) compose the two existing reads into one new `net_worth` tool + `GET /net-worth` endpoint mirroring the `cashflow_summary` template exactly, (3) add the loud coverage assertion the DB already structurally guarantees but the read must still verify defensively, (4) register the new tool on both read surfaces (`TOOLS`/`READ_TOOL_NAMES` auto-flows to MCP; `query.py`'s explicit `FunctionTool` list does NOT auto-flow and needs a manual add), and (5) fix a **real, currently-shipping double-count bug** in the frontend: `ui/app/cashflow/page.tsx:179-186` already computes and renders a "Net worth" hero card, but it naively sums `current_balance` over **every** row from `account_balances` — including `type='investment'` accounts (e.g. legacy account id 3 "Investments") whose value is now *also* counted via the portfolio. This phase's success criteria are, in effect, a formal fix to a bug already visible in production.

**Primary recommendation:** Add `net_worth()` to `backend/tools.py` that (a) extends `account_balances`-style SQL with an added `a.type` column and a `type = 'liquid'` filter (new small query or a `type` param on `account_balances` — see Architecture Patterns), (b) calls `portfolio.portfolio_summary(db)` for the investment side, (c) asserts `liquid_count + investment_count == total_account_count` and raises `ValueError` if not, (d) returns a `NetWorth` Pydantic response mirroring `CashflowSummary`'s shape. Wire `GET /net-worth` in `main.py` next to `cashflow_summary` (main.py:698). Register in `TOOLS` (tools.py:605-621, before the `READ_TOOL_NAMES` freeze at line 628) and manually add a `FunctionTool.from_defaults(fn=net_worth)` to `query.py`'s `read_tools` list (query.py:119-163). Frontend: replace the client-side `netWorth`/`netWorthDelta` reduce (page.tsx:179-186) with values from the new endpoint's payload, and add a liquid/investment split + per-side breakdown card set beside the existing hero card (page.tsx:273-349).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Liquid balance aggregation (SUM by type='liquid') | API / Backend (`tools.py`) | Database (CHECK constraint on `accounts.type`) | Parameterized SQL over `transactions`/`accounts`; DB enforces the closed type set, backend enforces the business filter |
| Investment total aggregation | API / Backend (`portfolio.py`) | — | Already the single source of truth (`portfolio_summary.total_value`); net_worth composes it, never re-derives it |
| Coverage assertion (100% of accounts classified) | API / Backend (`tools.py` new `net_worth`) | Database (`ck_accounts_type` + `NOT NULL`) | DB structurally prevents violation; backend asserts defensively and raises loudly per repo's correctness-by-construction precedent (Phase 13 D-04) |
| Net-worth headline + split rendering | Browser / Client (`ui/app/cashflow/page.tsx`) | — | Pure presentation of a server-computed number; no client-side aggregation logic should remain (that's the current bug) |
| MCP / agent read exposure | API / Backend (`tools.py` registry + `mcp_server.py` + `query.py`) | — | Registry-driven; `mcp_server.py` reads `READ_TOOL_NAMES` automatically, `query.py` requires an explicit added line |

## Standard Stack

No new libraries. This phase composes existing in-repo functions only.

### Core (existing, reused)
| Component | Location | Purpose | Why reuse |
|-----------|----------|---------|-----------|
| `account_balances()` | `backend/tools.py:474` | Per-account derived balance (current_balance, period_net) | Already correct derived-balance logic (non-transfer, LEFT JOIN); only missing `type` in SELECT |
| `portfolio_summary()` | `backend/portfolio.py:174` | Investment total_value, per-platform groups, asset_type_groups | Single source of truth for investment value (D-03); never re-sum holdings elsewhere |
| `resolve_period()` | `backend/tools.py:41` | Period string → (start, end) tuple | Same period-resolution pattern `cashflow_summary` uses |
| SQLAlchemy `text()` bound params | throughout `tools.py` | Parameterized SQL | Repo convention — no ORM query-building for aggregations, no raw string interpolation |

### Supporting
| Component | Location | Purpose | When to use |
|-----------|----------|---------|-------------|
| `Session` / `get_session` dependency | `backend/db.py` | Per-request DB session | `portfolio_summary(db)` needs a `Session`, not a raw connection — `net_worth` tool signature should accept `db: Session` too if it calls `portfolio_summary` internally, unlike the connection-based `tools.py` reads |
| `find_accounts()` / `_account_to_dict()` | `backend/tools.py:587,676` | Already returns `{id, name, type, currency}` per account | Reference for the exact `type` field name/values to reuse — do not invent a different casing/enum |

### Alternatives Considered
| Instead of | Could use | Tradeoff |
|------------|-----------|----------|
| Small dedicated liquid-only query | Extend `account_balances()` with a `type` column + optional `account_type` filter param | Extending risks breaking the existing `account_balances` MCP/agent tool contract (its docstring explicitly defers the split to "Phase 15"); a dedicated query is more isolated but duplicates the JOIN. **Recommendation: extend `account_balances()` to also SELECT `a.type`** (additive field, doesn't break existing consumers reading `id/name/current_balance/period_net`) and do the `type='liquid'` filtering/summing in the new `net_worth()` function, not in SQL — keeps one query, one JOIN, and the existing tool's output is a strict superset (no backward-incompat break for `CashflowSummary.accounts` or the frontend `AccountBalance` type). |
| Raising inside `net_worth()` | Raising inside a separate `assert_account_coverage()` helper | Unnecessary indirection for a single call site; repo pattern (Phase 13 D-04) raises inline where the invariant is checked, not in a separate validator module |

**Installation:** None — no new packages.

## Package Legitimacy Audit

**Not applicable.** This phase installs zero external packages; it composes existing first-party code only (`backend/tools.py`, `backend/portfolio.py`, `backend/main.py`, `backend/schemas.py`, `ui/app/cashflow/page.tsx`). Skip the legitimacy gate.

## Architecture Patterns

### System Architecture Diagram

```
GET /net-worth (main.py, mirrors cashflow_summary @ L698)
        |
        v
tools.net_worth()  [NEW — backend/tools.py]
        |
        +--> account_balances(type='liquid' filter)  [EXTENDED — tools.py:474]
        |         SELECT a.id, a.name, a.type, SUM(t.amount) ...
        |         FROM accounts a LEFT JOIN transactions t
        |         WHERE t.is_transfer = false
        |         -> filter rows where type == 'liquid' in Python (or SQL WHERE)
        |
        +--> portfolio.portfolio_summary(db)  [REUSED, UNCHANGED — portfolio.py:174]
        |         iterates Holding rows, latest price_cache per ticker,
        |         cash holdings (asset_type='cash') valued via FX rate
        |         -> total_value, groups (per-platform subtotals)
        |
        +--> COVERAGE ASSERTION:
        |     liquid_count + investment_count == COUNT(*) accounts
        |     else raise ValueError -> HTTPException(422) at API layer
        |
        v
NetWorth response {total, liquid_total, investment_total,
                    liquid_accounts: [...], investment_groups: [...],
                    accounts_covered, accounts_total}
        |
        v
ui/app/cashflow/page.tsx  [MODIFIED]
   - replaces client-side netWorth/netWorthDelta reduce (L179-186)
   - hero card (L273-349) reads server total instead
   - new split cards: liquid total (per-account rows, reuse existing
     "Accounts" card pattern L511+) + investment total (per-platform
     subtotals, reuse portfolio_summary.groups shape)
```

### Recommended Project Structure

No new files needed. Modify in place:
```
backend/
├── tools.py         # extend account_balances() SELECT; add net_worth()
├── main.py          # add GET /net-worth endpoint next to cashflow_summary (~L698)
├── schemas.py        # add NetWorth response model near CashflowSummary (~L82) / PortfolioSummary (~L295)
├── query.py          # add net_worth import + FunctionTool.from_defaults(fn=net_worth) to read_tools list (~L104, ~L162)
└── tests/
    └── test_net_worth.py   # new — mirrors test_cashflow_summary.py fixture style

ui/app/cashflow/
└── page.tsx          # replace client netWorth calc; add split/breakdown cards
```

### Pattern 1: Composed-read endpoint (mirror `cashflow_summary`)
**What:** A `GET` endpoint with no `require_api_key` dependency (open read) that resolves inputs, calls one or more `tools.py`/`portfolio.py` functions, and returns a single typed Pydantic response — never emits its own SQL beyond what the composed functions already run.
**When to use:** Exactly the `net_worth` case — do not write new raw SQL for balances or holdings inside `main.py`.
**Example:**
```python
# Source: backend/main.py:698-728 (cashflow_summary — the template to mirror)
@app.get("/cashflow/summary", response_model=CashflowSummary)
def cashflow_summary(
    period: str = "this_month",
    start_date: str | None = None,
    end_date: str | None = None,
    db: Session = Depends(get_session),
):
    try:
        s, e = resolve_period(period, start_date, end_date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    totals = {...}
    accounts = account_balances(s, e)["rows"]
    ...
    return CashflowSummary(totals=totals, by_category=by_category, accounts=accounts, trend=trend)
```
`GET /net-worth` should follow this exact shape: try/except around anything that can raise `ValueError` (period resolution AND the new coverage assertion), map to `HTTPException(422)`, return a typed response. `investments_summary` (main.py:573-589) is the second sibling pattern — note it takes `db: Session = Depends(get_session)` because `portfolio_summary(db)` needs an ORM session, unlike the connection-based `tools.py` reads. `net_worth()` will need to accept `db: Session` too (breaking from the plain-function `tools.py` idiom) since it must call `portfolio_summary(db)` internally — precedent for a `tools.py` function taking `db` exists nowhere yet; **recommend defining `net_worth(db: Session, ...)` directly in `tools.py`** (it can still live in the `TOOLS` registry/MCP surface — MCP's `FastMCP` will just need `db` supplied at call time, same open question `portfolio_summary`'s design already had to solve since it's NOT in `TOOLS` today). See Pitfall 3 below — this is the single trickiest wiring decision in the phase.

### Pattern 2: DB-enforced discriminator, backend-enforced defensive assertion
**What:** The type partition is already a closed set by CHECK constraint; the coverage assertion in `net_worth()` is a belt-and-suspenders check, not the primary correctness mechanism.
**When to use:** Any aggregation that partitions by `accounts.type`.
**Example:**
```python
# Source: alembic/versions/010_typed_accounts.py:88-97 (the CHECK constraint)
op.create_check_constraint(
    "ck_accounts_type", "accounts", "type IN ('liquid','investment')"
)
op.alter_column("accounts", "type", existing_type=sa.String(64), nullable=False, ...)
```
```python
# The read-side assertion to write (new code, matching Phase 13 D-04's loud-raise precedent):
if liquid_count + investment_count != total_accounts:
    raise ValueError(
        f"net_worth coverage gap: {liquid_count + investment_count}/{total_accounts} "
        f"accounts classified — refusing to silently drop or double-count"
    )
```

### Pattern 3: Registry + dual manual registration (MCP auto, agent manual)
**What:** Adding a name to the `TOOLS` dict literal (before the `READ_TOOL_NAMES = frozenset(TOOLS)` line) makes it flow automatically onto the MCP read server via `mcp_server.py`'s `for name in READ_TOOL_NAMES: fn = TOOLS[name]` loop. It does **NOT** automatically appear in the agent's LLM-visible tool list — `query.py` builds that list by explicit `FunctionTool.from_defaults(fn=...)` calls, one per import.
**When to use:** Always, for any new read tool. This is exactly the failure mode the project memory `chat-tool-dual-registration` already documents.
**Example:**
```python
# Source: backend/tools.py:604-628 — MUST add net_worth here, above the freeze line
TOOLS = {
    "spending_total": spending_total,
    ...
    "account_balances": account_balances,
    "net_worth": net_worth,          # <-- ADD HERE, before line 628
}
READ_TOOL_NAMES: frozenset[str] = frozenset(TOOLS)   # tools.py:628 — snapshot freezes here
```
```python
# Source: backend/query.py:97-115, 119-163 — MUST separately add net_worth here
from backend.tools import (
    ..., account_balances, net_worth,   # <-- add import
)
read_tools = [
    ...,
    FunctionTool.from_defaults(fn=account_balances),
    FunctionTool.from_defaults(fn=net_worth),   # <-- add FunctionTool entry
]
```
```python
# Source: backend/mcp_server.py:77-92 — confirms MCP needs NO manual edit
def build_mcp() -> FastMCP:
    mcp = FastMCP("monai finance (read-only)")
    for name in READ_TOOL_NAMES:      # net_worth flows through here automatically
        fn = TOOLS[name]
        mcp.tool(name=name, description=MCP_DESCRIPTIONS.get(name, fn.__doc__ or name))(fn)
```
`mcp_server.py` also has an optional `MCP_DESCRIPTIONS` dict (mcp_server.py:70-74) for tool-specific descriptions surfaced to MCP clients — worth adding a `net_worth` entry there for a clearer external-client description than the raw docstring, matching `find_accounts`'/`find_transactions`' existing entries.

### Anti-Patterns to Avoid
- **Re-summing holdings or transactions from scratch in `net_worth()`:** Don't write new SQL against `holdings` or `portfolio_events` — always call `portfolio_summary(db).total_value`. Re-deriving would risk diverging from the FX/cash/realized-PnL logic already correctly handled there (CG-01 cash special-case, portfolio.py:214-226).
- **Filtering liquid accounts by NAME or ID instead of `type`:** The whole point of migration 010 was moving off ad-hoc lists (`ACCOUNT_TYPE` backfill map was a one-time migration artifact, not a runtime lookup). `net_worth()` must filter on `accounts.type = 'liquid'` at query time, nothing else.
- **Trusting the client-side `netWorth` reduce as "close enough":** It is not — it is the literal bug (see Common Pitfalls #1). Do not port it forward or leave it running alongside the new endpoint; replace it entirely.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Investment valuation (price × qty, FX cash, PnL) | A simplified "sum holdings" query in `net_worth()` | `portfolio.portfolio_summary(db)` | Already handles per-ticker latest price, cash-as-FX special case (CG-01), zero-qty holdings, platform grouping — reimplementing loses correctness guarantees silently |
| Period resolution / date parsing | Custom date logic in the new endpoint | `resolve_period()` (tools.py:41) | Net worth is a point-in-time snapshot (no period needed for the totals), but if a period param is kept for `account_balances`' `period_net` compatibility, reuse the existing resolver — never hand-roll date math |
| Type-safety on the partition | App-level `if acc.type not in {...}` scattered checks | The DB `ck_accounts_type` CHECK constraint (already in place) + one assertion at the read boundary | The DB is the enforcement point; the read-layer assertion is a "trust but verify," not the primary defense |

**Key insight:** This phase has almost nothing to hand-roll — its entire craft is *not* re-deriving numbers that already have a correct, tested source of truth elsewhere in the codebase, and *not* leaving two sources of truth (client sum vs. server sum) disagreeing, which is the exact bug currently live in `page.tsx`.

## Common Pitfalls

### Pitfall 1: The existing frontend net-worth card is ALREADY wrong (double-count in production)
**What goes wrong:** `ui/app/cashflow/page.tsx:179-186` computes `netWorth` as `summary.accounts.reduce((s, a) => s + a.current_balance, 0)` over **every** row `account_balances()` returns — which includes `type='investment'` accounts. If account id 3 ("Investments," typed `investment` per migration 010's backfill map) still has any transaction-derived balance, that same money is counted a second time by `portfolio_summary.total_value`.
**Why it happens:** `account_balances()` was written before Phase 15 existed and deliberately does not filter by type (its own docstring at tools.py:496 says "The liquid/investment net-worth split is Phase 15"); the frontend was never updated to account for the type split introduced in Phase 12.
**How to avoid:** The new `net_worth()` backend read must filter to `type='liquid'` only for the liquid sum; the frontend hero card (page.tsx:273-315) and the `netWorth`/`netWorthDelta` derivations (page.tsx:179-186) must be replaced with values sourced from `GET /net-worth`, not derived client-side from the raw `accounts` array anymore.
**Warning signs:** If after this phase ships, the dashboard's "Net worth" number still moves in lockstep with `summary.accounts` reduces rather than the new endpoint's response, the bug has been reintroduced.

### Pitfall 2: `account_balances()` is a shared/public contract — don't break its callers
**What goes wrong:** `account_balances()` is registered in `TOOLS`, exposed to the MCP read server AND the agent (query.py:104,162), and its `rows` shape (`id/name/current_balance/period_net`) is the literal TypeScript `AccountBalance` type consumed by the frontend (page.tsx:28-33) and by `CashflowSummary.accounts` (schemas.py:87). Adding `type` to its SELECT is safe (additive field); removing/renaming/filtering existing rows out by default is NOT — it would silently change `cashflow_summary`'s account list and any agent/MCP client already depending on it.
**Why it happens:** Easy to reach for "just filter this function to liquid" since that's the intuitive fix, but `account_balances()` is intentionally the FULL per-account list (including investment-typed legacy accounts, so their raw balance is still visible for audit/debugging).
**How to avoid:** Extend the SELECT to also return `a.type`, keep the function returning ALL accounts unfiltered (backward compatible), and do the `type == 'liquid'` filtering *inside* the new `net_worth()` function, not inside `account_balances()` itself.
**Warning signs:** `test_cashflow_summary.py` or `test_tools.py` tests asserting on `account_balances()` row *count* start failing after this phase's changes.

### Pitfall 3: `net_worth()` needs a DB `Session`, breaking the plain-connection idiom
**What goes wrong:** Every other function in `tools.py`'s `TOOLS` registry takes plain args and opens its own `engine.connect()` (e.g. `account_balances(period_start=None, period_end=None)` at tools.py:474). But `portfolio_summary(db: Session)` requires an ORM `Session`, not a raw connection (portfolio.py:174). `net_worth()` must call `portfolio_summary(db)`, so it needs a `Session` passed in — a first for a `tools.py`-registered read tool.
**Why it happens:** `portfolio_summary` was designed for `main.py`'s `Depends(get_session)` FastAPI DI, not for the `TOOLS` registry's plain-function-call convention used by the agent (`query.py`'s tool-calling loop) and MCP (`mcp_server.py`'s `mcp.tool()(fn)`).
**How to avoid:** Two viable resolutions — planner should pick one explicitly, not leave it ambiguous:
  1. Give `net_worth()` a default `db: Session | None = None` param that opens its own session (`from backend.db import SessionLocal; db = db or SessionLocal()`) when called without one — keeps it callable from the agent/MCP loop with zero args, while `main.py`'s endpoint still passes its request-scoped session explicitly.
  2. Keep `net_worth()` DB-session-based only (like `portfolio_summary`) and accept that, like `portfolio_summary` itself today, it is **not** registered in `TOOLS`/agent/MCP — but this directly contradicts locked decision D-02 ("register `net_worth` on READ_TOOL_NAMES").
  Given D-02 is locked, **option 1 is required** — the planner must include a task for exactly this session-handling shim, or the agent/MCP call path will crash on `db=None`.
**Warning signs:** MCP or agent invocation of `net_worth` throws `AttributeError`/`TypeError` on a missing `db` argument at runtime — this will not show up in a plain `pytest` unit test that calls `net_worth(db=test_session)` directly, only in an end-to-end MCP/agent smoke test.

### Pitfall 4: Forgetting the CASH sentinel holding is investment-side, not liquid-side
**What goes wrong:** A liquid→investment deposit creates a `ticker='CASH', asset_type='cash'` holding (tools.py:1165-1213, `propose_add_investment_transfer`) that lives in the `holdings` table, gets valued via `fx.get_rate` inside `portfolio_summary` (portfolio.py:214-226), and is summed into `total_value`. It has NO corresponding `accounts` row. A naive re-implementation that tries to "also credit the liquid side because it's cash" would double-count it.
**Why it happens:** The word "cash" is overloaded — broker cash sitting in a `type='liquid'` account (e.g. Stockbit id 559) is genuinely liquid; the `CASH` sentinel holding representing money already moved INTO the investment side is not.
**How to avoid:** Trust `portfolio_summary.total_value` as the complete, correct investment total (it already includes CASH sentinel holdings via the `asset_type=='cash'` branch); never add a separate "investment cash" line item on the liquid side.
**Warning signs:** Net worth total exceeds the sum of (liquid accounts' raw balances + portfolio total_value) — a sign something is being counted an extra time.

## Code Examples

### Existing composed-read endpoint template (mirror exactly)
```python
# Source: backend/main.py:698-728
@app.get("/cashflow/summary", response_model=CashflowSummary)
def cashflow_summary(
    period: str = "this_month",
    start_date: str | None = None,
    end_date: str | None = None,
    db: Session = Depends(get_session),
):
    try:
        s, e = resolve_period(period, start_date, end_date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    totals = {
        "income": income_total(period, start_date, end_date)["total"],
        "expense": spending_total(period, start_date, end_date)["total"],
        "net": net_total(period, start_date, end_date)["net"],
    }
    by_cat_result = spending_by_category(period, start_date, end_date, limit=10)
    by_category = _category_rollup(db, by_cat_result["rows"], by_cat_result["children"])
    accounts = account_balances(s, e)["rows"]
    trend = monthly_trend(6)["rows"]
    return CashflowSummary(totals=totals, by_category=by_category, accounts=accounts, trend=trend)
```

### Existing type-partition view (the pattern to reuse for liquid filtering)
```sql
-- Source: alembic/versions/010_typed_accounts.py:138-144
CREATE VIEW cashflow_transactions AS
SELECT t.* FROM transactions t
WHERE NOT EXISTS (
  SELECT 1 FROM accounts a WHERE a.id = t.account_id AND a.type = 'investment'
)
```

### Existing account_balances SQL (extend with `a.type`)
```python
# Source: backend/tools.py:474-510 (current — add "a.type" to the SELECT list)
sql = (
    "SELECT a.id, a.name, a.type, "                       # <-- add a.type here
    "COALESCE(SUM(t.amount), 0) AS current_balance, "
    f"COALESCE(SUM(t.amount) FILTER (WHERE true{period_predicate}), 0) AS period_net "
    "FROM accounts a "
    "LEFT JOIN transactions t ON t.account_id = a.id AND t.is_transfer = false "
    "GROUP BY a.id, a.name, a.type ORDER BY a.name"        # <-- add a.type to GROUP BY
)
```

### Existing portfolio_summary return shape (the investment-side source of truth)
```python
# Source: backend/portfolio.py:302-309
return {
    "groups": ordered,                    # [{platform_id, platform_name, kind, subtotal, holdings:[...]}]
    "asset_type_groups": asset_type_groups,
    "total_value": total_value,
    "total_unrealized_pnl": total_unrealized,
    "total_realized_pnl": total_realized,
    "as_of": datetime.now(timezone.utc).isoformat(),
}
```

### Existing frontend bug to replace
```typescript
// Source: ui/app/cashflow/page.tsx:179-186 — REPLACE, do not extend
const netWorth = (summary?.accounts ?? []).reduce(
  (s, a) => s + a.current_balance,
  0
);
const netWorthDelta = (summary?.accounts ?? []).reduce(
  (s, a) => s + a.period_net,
  0
);
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| Frontend client-side sum of ALL `account_balances` rows for "net worth" | Backend-computed, type-partitioned `net_worth` read | This phase (15) | Fixes a live double-count bug for any account still typed `investment` with a nonzero transaction-derived balance |
| `accounts.type` nullable, no constraint | `accounts.type` NOT NULL + `ck_accounts_type CHECK IN ('liquid','investment')` | Phase 12 (migration 010) | Makes the coverage assertion in `net_worth()` nearly unfalsifiable in practice — it exists as a loud-raise safety net, not the primary defense |

**Deprecated/outdated:**
- The `ACCOUNT_TYPE` backfill map in `010_typed_accounts.py:49` was a one-time migration seed, not a runtime lookup — never reference it from `net_worth()`; query `accounts.type` live instead.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Extending `account_balances()`'s SELECT to add `a.type` is backward-compatible with all existing consumers (agent tool description, `CashflowSummary.accounts`, frontend `AccountBalance` type) because it's an additive field, not a removed/renamed one | Standard Stack / Alternatives, Pitfall 2 | If any consumer does strict schema validation rejecting unknown extra fields (Pydantic `extra="forbid"` or a frontend type mismatch), the added field could break a caller — verify `CashflowSummary.accounts: list` (schemas.py:87, untyped `list`, not `list[AccountOut]`) has no strict validation; confirmed loose-typed as of this research, so risk is LOW but should be spot-checked during planning |
| A2 | `net_worth()` should live in `tools.py` (not `portfolio.py` or a new module) despite needing a `Session` unlike its siblings | Pitfall 3 | If the planner instead creates a new `net_worth.py` module, that's also defensible — but it fragments the registry import surface (`query.py`'s import block already imports everything from `backend.tools`); recommend keeping it in `tools.py` for import-path consistency, but this is Claude's-discretion-level, not a hard blocker |
| A3 | The frontend split/breakdown cards should be built as new inline JSX blocks within `page.tsx` reusing existing `card`/`statCard` style objects, not as new extracted components | Architecture Patterns / Recommended Project Structure | Locked decision D-08 says "reuse existing dashboard card/summary components — no new design system work," consistent with this assumption, but the exact card boundaries (one combined split card vs. two separate liquid/investment cards) are Claude's discretion per CONTEXT.md — planner should decide layout specifics |

## Open Questions

1. **Does `net_worth()`'s Session-handling shim (Pitfall 3, option 1) belong in `tools.py` or should `portfolio_summary` itself gain a no-session convenience wrapper?**
   - What we know: `portfolio_summary(db: Session)` is currently only called from `main.py` (`investments_summary`) and would be called a second time from `net_worth()`.
   - What's unclear: Whether a shared `_get_session_or_default(db)` helper already exists elsewhere in the codebase (not found in this research pass) or should be newly introduced.
   - Recommendation: Add the minimal shim directly in `net_worth()` (`from backend.db import SessionLocal; db = db or SessionLocal()`, with a `finally: db.close()` if it opened its own) — don't refactor `portfolio_summary`'s signature, which is shared and tested (`test_portfolio.py`) independent of this phase.

2. **Should the coverage assertion's `ValueError` message/shape be tested via `main.py`'s HTTP 422 path, or only unit-tested at the `tools.py` function level?**
   - What we know: D-06 requires "a test proving an out-of-set type triggers the loud raise." The `ck_accounts_type` CHECK makes inserting a genuinely out-of-set type impossible through normal app code — the test will likely need to bypass the ORM (raw `INSERT ... type='bogus'` inside a transaction that's rolled back, or `conn.execute` with `sa.text` and an explicit rollback) to even construct the violating state, similar to `test_type_check_and_default`'s pattern noted in STATE.md (Phase 12 Plan 01: "both new test files... explicitly rolls back both probe inserts so the live accounts table is never mutated").
   - Recommendation: Unit-test `net_worth()` directly by monkeypatching/mocking the query result rather than trying to insert a real CHECK-violating row (which the DB will reject) — assert the function raises when `liquid_count + investment_count != total` is forced via a stubbed row set, not via a live DB state that structurally cannot exist.

## Environment Availability

Skipped — this phase has no new external dependencies (PostgreSQL, the only relevant dependency, is already required and running for all prior phases; no new tool/service/runtime is introduced).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest >=8.0.0 (`backend/requirements.txt`), no config file beyond default discovery |
| Config file | none — see `backend/tests/` directory convention (module-scoped `db_available` fixture per test file, per `test_cashflow_summary.py:25-33`) |
| Quick run command | `cd backend && python -m pytest tests/test_net_worth.py -x` |
| Full suite command | `cd backend && python -m pytest tests/ -x` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| NW-01 | Net worth = liquid + investment, each account/holding counted once | unit (DB-backed, live Postgres) | `pytest backend/tests/test_net_worth.py::test_sum_counts_each_row_once -x` | ❌ Wave 0 |
| NW-01 (SC #3) | Coverage assertion raises `ValueError` on an unclassified/out-of-set type | unit | `pytest backend/tests/test_net_worth.py::test_unclassified_type_raises -x` | ❌ Wave 0 |
| NW-02 | Liquid vs investment split totals reconcile to the combined total | unit | `pytest backend/tests/test_net_worth.py::test_split_reconciles_to_total -x` | ❌ Wave 0 |
| NW-02 | `GET /net-worth` returns the composed payload (endpoint-level) | integration | `pytest backend/tests/test_net_worth.py::test_get_net_worth_endpoint -x` (or an added case in `test_cashflow_view.py` if that file already covers `main.py` GET endpoints) | ❌ Wave 0 |
| NW-01/NW-02 | Dashboard renders headline + split without using the old client-side reduce | manual-only (UAT) — no frontend test framework detected in `ui/` (`package.json` has no `jest`/`vitest`/`playwright` script) | manual UAT via `/gsd-verify-work` | N/A |

### Sampling Rate
- **Per task commit:** `cd backend && python -m pytest tests/test_net_worth.py -x`
- **Per wave merge:** `cd backend && python -m pytest tests/ -x`
- **Phase gate:** Full backend suite green before `/gsd-verify-work`; UAT covers the frontend rendering (no automated frontend test infra exists in this repo — confirmed via `ui/package.json`, no test script present).

### Wave 0 Gaps
- [ ] `backend/tests/test_net_worth.py` — covers NW-01, NW-02 (new file; reuse `db_available`/`db_session` fixture + `_make_account`/`_make_transaction` seed-helper style from `test_cashflow_summary.py:25-80`)
- [ ] No new fixtures needed — `_make_account(db, name, type=...)` in `test_cashflow_summary.py:69-80` currently hardcodes `type="liquid"`; the new test file needs a variant (or a param) that can also seed a `type="investment"` account to test the double-count-guard and coverage assertion
- [ ] Framework install: none — pytest already present

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-------------------|
| V2 Authentication | No | `GET /net-worth` is an open read, matching `cashflow_summary`/`investments_summary` (main.py:710: "an open read (no require_api_key), matching existing GET reads") — single-user, self-hosted app; consistent with existing convention |
| V3 Session Management | No | No session state introduced |
| V4 Access Control | No | Read-only endpoint; no new write path; `net_worth` is explicitly excluded from `TOOLS.update()`'s write-tool block (tools.py:1333-1350) |
| V5 Input Validation | Marginal | If a `period` param is kept on the endpoint (for consistency with `account_balances`' `period_net`), reuse `resolve_period()`'s existing validation (raises `ValueError` → 422) — do not add new unvalidated query params |
| V6 Cryptography | No | Not applicable |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|----------------------|
| SQL injection via account/type filters | Tampering | Parameterized `text()` with bound params only — no string-formatted SQL identifiers (the `type = 'liquid'` filter should be a bound param or a hardcoded literal, never interpolated from a request) |
| Information disclosure via unhandled exception (500 leaking stack trace) | Information Disclosure | Existing repo pattern: catch `ValueError` and map to `HTTPException(422, detail=str(exc))` at the API layer (main.py:712-718); the new coverage-assertion `ValueError` must be caught the same way, not allowed to bubble as a raw 500 — this repo has a documented precedent of an unguarded FK/invariant violation leaking a 500 (`apply-fk-integrityerror-not-422` memory note, Phase 14 T-14-07) |

## Sources

### Primary (HIGH confidence — read directly from this repo)
- `backend/tools.py:474-628,1320-1350` — `account_balances()`, `find_accounts()`/`_account_to_dict()`, `TOOLS`/`READ_TOOL_NAMES` registry mechanics
- `backend/portfolio.py:174-309` — `portfolio_summary()` full implementation and return shape
- `backend/main.py:573-589,698-728` — `investments_summary()` and `cashflow_summary()` endpoint templates
- `backend/schemas.py:82-89,295-308` — `CashflowSummary`, `PortfolioSummary` Pydantic shapes
- `backend/query.py:92-163` — agent `FunctionTool` registration (manual, separate from `TOOLS`)
- `backend/mcp_server.py:77-92` — MCP auto-registration from `READ_TOOL_NAMES`
- `alembic/versions/010_typed_accounts.py:1-152` — `accounts.type` CHECK constraint, backfill map, `cashflow_transactions` view SQL
- `ui/app/cashflow/page.tsx:1-100,160-190,240-350,400-540` — current dashboard structure, the existing (buggy) client-side net-worth calculation, hero card and Accounts card render locations
- `backend/tests/test_cashflow_summary.py:1-100` — DB-backed test fixture pattern (`db_available`, `db_session`, `_make_account`, `_make_transaction`)
- `.planning/phases/15-net-worth-aggregation-dashboard/15-CONTEXT.md` — locked decisions D-01 through D-08
- `.planning/STATE.md` — Phase 12/13 decision history (typed accounts, transfer pairing, loud-raise precedent)

### Secondary (MEDIUM confidence)
- None used — all findings verified against source in this session.

### Tertiary (LOW confidence)
- None — no WebSearch was needed; this phase has zero external-library or ecosystem research surface.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new libraries; every function cited was read directly
- Architecture: HIGH — composed-read pattern is an established, twice-precedented convention (`cashflow_summary`, `investments_summary`) in this exact codebase
- Pitfalls: HIGH — Pitfall 1 (frontend double-count bug) was found live in the current source, not hypothesized; Pitfall 3 (Session handling) is a genuine gap the planner must resolve explicitly

**Research date:** 2026-07-31
**Valid until:** Indefinite for the architectural patterns (internal code, doesn't drift like an external library); re-verify file:line citations if `backend/tools.py`, `backend/main.py`, or `ui/app/cashflow/page.tsx` are touched by any other in-flight phase before Phase 15 executes.
