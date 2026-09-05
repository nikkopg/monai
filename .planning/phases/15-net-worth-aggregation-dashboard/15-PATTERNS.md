# Phase 15: Net Worth Aggregation + Dashboard - Pattern Map

**Mapped:** 2026-07-31
**Files analyzed:** 8
**Analogs found:** 8 / 8

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `backend/tools.py` (extend `account_balances`, add `net_worth`) | service (read tool) | CRUD-aggregation | `backend/tools.py:474-510` (`account_balances`) + `backend/portfolio.py:174` (`portfolio_summary`) | exact (self-extension + composition) |
| `backend/query.py` (register `net_worth` FunctionTool) | provider (agent tool registry) | request-response | `backend/query.py:104,162` (`account_balances` FunctionTool entry) | exact |
| `backend/main.py` (`GET /net-worth`) | route/controller | request-response | `backend/main.py:698-728` (`cashflow_summary`) | exact |
| `backend/schemas.py` (`NetWorth` model) | model (DTO) | transform | `backend/schemas.py` `CashflowSummary` (~L82), `PortfolioSummary` (~L295) | exact |
| `backend/portfolio.py` (`portfolio_summary`, unchanged) | service | CRUD-aggregation | — (source of truth, read-only call site) | n/a — no changes |
| `backend/tests/test_net_worth.py` | test | CRUD-aggregation | `backend/tests/test_cashflow_summary.py:1-90` | exact |
| `ui/app/cashflow/page.tsx` (hero fix + split row + breakdown rename/add) | component | request-response | same file's existing hero/stat/breakdown blocks (self-analog) | exact |
| `ui/app/styles.ts` | config (tokens) | n/a | no new tokens — reuse `card`, `statCard`/`statLabel`/`statValue`, `tokens.color.*` | n/a — no changes expected |

## Pattern Assignments

### `backend/tools.py` — extend `account_balances()` + add `net_worth()` (service, CRUD-aggregation)

**Analog:** `backend/tools.py:474-510` (`account_balances`), composed with `backend/portfolio.py:174` (`portfolio_summary`)

**Current `account_balances` SQL** (tools.py:474-510) — extend `SELECT`/`GROUP BY` only, don't filter rows out:
```python
def account_balances(period_start=None, period_end=None) -> dict:
    ...
    sql = (
        "SELECT a.id, a.name, "                                   # add "a.type, " here
        "COALESCE(SUM(t.amount), 0) AS current_balance, "
        f"COALESCE(SUM(t.amount) FILTER (WHERE true{period_predicate}), 0) AS period_net "
        "FROM accounts a "
        "LEFT JOIN transactions t ON t.account_id = a.id AND t.is_transfer = false "
        "GROUP BY a.id, a.name ORDER BY a.name"                   # add "a.type" to GROUP BY
    )
    with engine.connect() as c:
        rows = [
            {"id": r[0], "name": r[1], "current_balance": float(r[2]), "period_net": float(r[3])}
            for r in c.execute(text(sql), p).fetchall()
        ]
    return {"tool": "account_balances", "rows": rows}
```
Additive field only (`type`) — do not remove/rename existing keys (Pitfall 2: this feeds `CashflowSummary.accounts` and the frontend `AccountBalance` type).

**Registry pattern to copy** (tools.py:604-621, before the freeze):
```python
TOOLS = {
    "spending_total": spending_total,
    ...
    "account_balances": account_balances,
    "net_worth": net_worth,          # ADD before line ~620
}
READ_TOOL_NAMES: frozenset[str] = frozenset(TOOLS)   # net_worth flows to MCP automatically via this snapshot
```

**Session-handling shim (Pitfall 3 — required by D-02):** `net_worth` must accept `db: Session | None = None` and open its own session when called with no args (agent/MCP path), matching no existing tools.py precedent but required because it calls `portfolio_summary(db)`:
```python
def net_worth(db: Session | None = None) -> dict:
    """..."""
    from backend.db import SessionLocal
    owns_session = db is None
    db = db or SessionLocal()
    try:
        # liquid side: reuse extended account_balances() rows, filter type == "liquid" in Python
        rows = account_balances()["rows"]
        liquid_rows = [r for r in rows if r["type"] == "liquid"]
        investment_rows = [r for r in rows if r["type"] == "investment"]
        liquid_total = sum(r["current_balance"] for r in liquid_rows)

        # investment side: single source of truth
        from backend.portfolio import portfolio_summary
        pf = portfolio_summary(db)
        investment_total = float(pf["total_value"])

        # coverage assertion — D-05, loud raise, Phase 13 D-04 precedent
        if len(liquid_rows) + len(investment_rows) != len(rows):
            raise ValueError(
                f"net_worth coverage gap: {len(liquid_rows) + len(investment_rows)}/{len(rows)} "
                "accounts classified — refusing to silently drop or double-count"
            )
        return {
            "tool": "net_worth",
            "total": liquid_total + investment_total,
            "liquid_total": liquid_total,
            "investment_total": investment_total,
            "liquid_accounts": liquid_rows,
            "investment_groups": pf["groups"],
            "accounts_covered": len(liquid_rows) + len(investment_rows),
            "accounts_total": len(rows),
        }
    finally:
        if owns_session:
            db.close()
```
(Field names/shape are Claude's discretion per CONTEXT.md — mirror `CashflowSummary`/`PortfolioSummary` naming conventions shown above.)

**Anti-pattern to avoid** (per RESEARCH.md): never re-sum `holdings`/`portfolio_events` inside `net_worth` — always call `portfolio_summary(db).total_value`. Never filter liquid accounts by name/id — only `type == 'liquid'`.

---

### `backend/query.py` — register `net_worth` FunctionTool (provider, request-response)

**Analog:** `backend/query.py:97-115` (import block), `:119-163` (`read_tools` list)

**Import pattern** (query.py ~L104):
```python
from backend.tools import (
    ...
    monthly_trend, account_balances,
    net_worth,                      # ADD
    ...
)
```
**Registration pattern** (query.py ~L162, sibling of `account_balances`):
```python
read_tools = [
    ...
    FunctionTool.from_defaults(fn=account_balances),
    FunctionTool.from_defaults(fn=net_worth),   # ADD — this is the manual step MCP does NOT need (mcp_server.py loops READ_TOOL_NAMES automatically)
]
```
**Critical:** adding to `TOOLS`/`READ_TOOL_NAMES` alone does NOT surface the tool to the agent — this file's explicit list is a separate, manual registration (memory: `chat-tool-dual-registration`).

---

### `backend/main.py` — `GET /net-worth` (route/controller, request-response)

**Analog:** `backend/main.py:698-728` (`cashflow_summary`) — composed-read, open read, try/except → 422

```python
# Template to mirror exactly (main.py:698-728)
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
    ...
    return CashflowSummary(...)
```
New endpoint:
```python
@app.get("/net-worth", response_model=NetWorth)
def net_worth_endpoint(db: Session = Depends(get_session)):
    """Composed net-worth payload (D-01/D-02/D-05) — open read, no require_api_key.
    liquid side = account_balances() filtered to type='liquid'; investment side =
    portfolio_summary(db).total_value. Raises 422 if the coverage assertion fails
    (schema invariant violated) — never silently drops/double-counts.
    """
    try:
        result = net_worth(db)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return NetWorth(**result)
```
No `require_api_key` dependency — matches `investments_summary` (main.py:573) and `cashflow_summary` (main.py:698), both open reads. Import `net_worth` lazily inside the handler or at top alongside other `backend.tools` imports (repo convention is mixed; module-level import matches `cashflow_summary`'s existing `account_balances`/`monthly_trend` imports at top of main.py — check existing import block before adding).

---

### `backend/schemas.py` — `NetWorth` model (model/DTO, transform)

**Analog:** `CashflowSummary` (loosely-typed `list`/`dict` fields), `PortfolioSummary` (typed `MoneyDecimal`)

```python
# Mirrors CashflowSummary's loose-list convention (schemas.py ~L82) —
# consistent with A1 in RESEARCH.md (no strict extra="forbid" validation observed)
class NetWorth(BaseModel):
    """Single composed payload for GET /net-worth (D-01, D-05, NW-01/NW-02)."""

    total: float
    liquid_total: float
    investment_total: float
    liquid_accounts: list      # rows from account_balances filtered to type='liquid'
    investment_groups: list    # rows from portfolio_summary.groups
    accounts_covered: int
    accounts_total: int
```
Use plain `float`/`list` fields matching `CashflowSummary`'s loose style (not `MoneyDecimal`) since `account_balances`/`net_worth` already returns `float`, not `Decimal` — consistent with the existing tool's float-cast pattern (tools.py:505: `float(r[2])`).

---

### `backend/tests/test_net_worth.py` (test, CRUD-aggregation)

**Analog:** `backend/tests/test_cashflow_summary.py:1-90` — fixture/seed-helper style

Reuse verbatim: `db_available` fixture (module-scoped, skips if Postgres down), `db_session` fixture (rollback via `db.close()`), and the `_make_account`/`_make_transaction` helper shape — but this new test file needs a `_make_account(db, name, type="liquid")` variant (param added) to also seed `type="investment"` accounts, since the existing helper hardcodes `type="liquid"` (test_cashflow_summary.py `_make_account`):

```python
def _make_account(db, name: str = "Test Account NW", type: str = "liquid") -> int:
    from backend.models import Account
    existing = db.query(Account).filter(Account.name == name).first()
    if existing:
        db.delete(existing)
        db.commit()
    acc = Account(name=name, type=type, currency="IDR")
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc.id
```

Per RESEARCH.md Open Question 2: do NOT try to insert a genuinely out-of-set `type` (DB CHECK constraint blocks it) — instead unit-test the coverage assertion by monkeypatching/stubbing `net_worth`'s internal row list so `len(liquid)+len(investment) != len(rows)` is forced, and assert `pytest.raises(ValueError)`.

Required test cases (D-06): `test_sum_counts_each_row_once` (all-liquid + all-investment mix sums correctly, no double-count), `test_unclassified_type_raises` (stubbed coverage gap → `ValueError`), `test_split_reconciles_to_total` (liquid_total + investment_total == total).

---

### `ui/app/cashflow/page.tsx` — hero fix + split row + breakdown changes (component, request-response)

**Analog:** self — reuses this file's own `statCard`/`card` blocks

**Bug to replace** (page.tsx:179-186 — DELETE this client-side reduce):
```typescript
const netWorth = (summary?.accounts ?? []).reduce((s, a) => s + a.current_balance, 0);
const netWorthDelta = (summary?.accounts ?? []).reduce((s, a) => s + a.period_net, 0);
```
Replace with a new `netWorthData` fetched from `GET /net-worth` (new `useEffect`/`useState` pair, mirroring the existing `summary`/`summaryError` fetch pattern already in this file for `/cashflow/summary`). Hero card (page.tsx ~274-350): swap `money(netWorth)` for `money(netWorthData.total)`; **delete** the ▲/▼ delta chip block (page.tsx:316-348) entirely per UI-SPEC — no period delta on net worth.

**Split row (NEW)** — copy the "Stat cards" grid shape verbatim (page.tsx:419-446):
```tsx
<div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 200px), 1fr))", gap: 18, marginBottom: 18 }}>
  <div style={statCard}>
    <div style={statLabel}>Liquid</div>
    <div style={{ ...statValue, color: tokens.color.ink }}>{money(netWorthData.liquid_total)}</div>
    <div style={{ fontSize: 13, color: tokens.color.muted }}>{netWorthData.liquid_accounts.length} account(s)</div>
  </div>
  <div style={statCard}>
    <div style={statLabel}>Investment</div>
    <div style={{ ...statValue, color: tokens.color.ink }}>{money(netWorthData.investment_total)}</div>
    <div style={{ fontSize: 13, color: tokens.color.muted }}>{netWorthData.investment_groups.length} platform(s)</div>
  </div>
</div>
```

**Breakdown row** — rename "Accounts" → "Liquid accounts" (page.tsx:511-513) and filter `.map` source to `netWorthData.liquid_accounts` instead of `summary.accounts`; row markup (page.tsx:515-575, initials avatar + name + balance/delta) is copied byte-identical, just the data source changes. New third card "Investment platforms" — copy the same row shell (avatar badge via `initials()`, name, right-aligned value) but source from `netWorthData.investment_groups`, dropping the `period_net` delta line (platforms carry no period-net equivalent):

```tsx
{netWorthData.investment_groups.map((g) => (
  <div key={g.platform_id} style={{ display: "flex", alignItems: "center", gap: 12, padding: "11px 0", borderTop: `1px solid ${tokens.color.borderInner}` }}>
    <span style={{ width: 34, height: 34, borderRadius: 10, background: tokens.color.sidebar, display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: 13, fontWeight: 600, color: tokens.color.muted3 }}>
      {initials(g.platform_name)}
    </span>
    <div style={{ flex: 1 }}>
      <div style={{ fontSize: 14, fontWeight: 500 }}>{g.platform_name}</div>
    </div>
    <div style={{ fontSize: 14, fontWeight: 600, fontVariantNumeric: "tabular-nums", color: tokens.color.ink }}>
      {money(g.subtotal)}
    </div>
  </div>
))}
```

Grid becomes 3-up automatically (`auto-fit, minmax(300px)` already handles it, per UI-SPEC — no manual breakpoint math needed).

**Empty states** — copy the existing "No transactions yet." pattern (page.tsx ~607-616: 16px/600 heading + 14px muted body, no border) for "No liquid accounts yet." / "No investment platforms yet." per UI-SPEC copy contract.

**Gate extension:** `hasActivity` (page.tsx ~173-178) currently gates the whole breakdown row; extend so the breakdown row also renders when `netWorthData.liquid_accounts.length > 0 || netWorthData.investment_groups.length > 0`, independent of period activity (net worth is not period-scoped).

---

## Shared Patterns

### Composed-read endpoint template
**Source:** `backend/main.py:698-728` (`cashflow_summary`)
**Apply to:** `GET /net-worth`
```python
try:
    s, e = resolve_period(period, start_date, end_date)
except ValueError as exc:
    raise HTTPException(status_code=422, detail=str(exc))
```
Same try/except-to-422 mapping applies to the coverage-assertion `ValueError` inside `net_worth()` — never let it bubble as a raw 500 (memory: `apply-fk-integrityerror-not-422`, T-14-07 precedent).

### Registry + dual manual registration
**Source:** `backend/tools.py:604-628`, `backend/query.py:97-163`, `backend/mcp_server.py:77-92`
**Apply to:** `net_worth` — add to `TOOLS` dict (before `READ_TOOL_NAMES` freeze) AND separately add `FunctionTool.from_defaults(fn=net_worth)` to `query.py`'s `read_tools` list. MCP (`mcp_server.py`) needs zero manual edits — it loops `READ_TOOL_NAMES` automatically.

### Loud-raise coverage assertion
**Source:** Phase 13 D-04 precedent, `alembic/versions/010_typed_accounts.py:88-97` (CHECK constraint)
**Apply to:** `net_worth()` — raise `ValueError` (not silent drop) if `liquid_count + investment_count != total_accounts`; API layer catches and maps to `HTTPException(422)`.

### Dashboard card reuse (no new design system)
**Source:** `ui/app/cashflow/page.tsx` `statCard`/`statLabel`/`statValue` objects (page-local, ~L754-769) + `card` from `ui/app/styles.ts`
**Apply to:** split row and breakdown row — reuse verbatim, no new tokens, no new component library (per UI-SPEC D-08 lock).

## No Analog Found

None — every file in scope has a strong, cited in-repo analog (composed-read siblings `cashflow_summary`/`investments_summary`, existing `account_balances`/`portfolio_summary` tools, existing dashboard card patterns).

## Metadata

**Analog search scope:** `backend/tools.py`, `backend/main.py`, `backend/schemas.py`, `backend/query.py`, `backend/portfolio.py`, `backend/tests/test_cashflow_summary.py`, `ui/app/cashflow/page.tsx`
**Files scanned:** 7 (all read directly, exact line ranges cited above)
**Pattern extraction date:** 2026-07-31
