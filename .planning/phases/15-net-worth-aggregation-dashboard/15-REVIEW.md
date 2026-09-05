---
phase: 15-net-worth-aggregation-dashboard
reviewed: 2026-07-31T00:00:00Z
depth: standard
files_reviewed: 8
files_reviewed_list:
  - backend/tools.py
  - backend/schemas.py
  - backend/main.py
  - backend/query.py
  - backend/mcp_server.py
  - backend/tests/test_net_worth.py
  - backend/tests/test_mcp.py
  - ui/app/cashflow/page.tsx
findings:
  critical: 0
  warning: 2
  info: 2
  total: 4
status: issues_found
---

# Phase 15: Code Review Report

**Reviewed:** 2026-07-31
**Depth:** standard
**Files Reviewed:** 8
**Status:** issues_found

## Summary

Phase 15 adds a read-only net-worth aggregation (`net_worth()` tool + `GET /net-worth`
endpoint + dashboard hero). The core correctness goals hold up under adversarial
inspection:

- **Partition / double-count fix is correct-by-construction.** `net_worth()` sums
  only `type == 'liquid'` accounts for the liquid side and takes
  `portfolio_summary(db)["total_value"]` for the investment side — two disjoint
  data sources (accounts vs. holdings/portfolio_events), so no row is counted
  twice. Investment-typed accounts are excluded from the liquid sum, which is the
  historical bug.
- **Coverage assertion → 422 is wired correctly.** `net_worth()` raises `ValueError`
  on a classification gap; `net_worth_endpoint` catches `ValueError` → `HTTPException(422)`,
  never a raw 500. The DB CHECK `ck_accounts_type` (`type IN ('liquid','investment')`)
  + `NOT NULL` + `server_default 'liquid'` (alembic 010) makes the gap
  unreachable in normal operation, so the assertion is defensive-only (good).
- **Read-only contract holds.** `net_worth` is in the pre-mutation `READ_TOOL_NAMES`
  frozenset and never in the `propose_*` write set; MCP registers only
  `READ_TOOL_NAMES`, agent registers it explicitly (dual-registration honored).
- **No SQL injection.** No new raw SQL in `net_worth`; it composes the already
  parameterized `account_balances()` + `portfolio_summary()`.
- **Session shim is correct.** `owns_session = db is None`; only self-opened
  sessions are closed in `finally`; the request-scoped session passed by the
  endpoint is left for `get_session` to manage.

Two WARNING-level defects were found (both confirmed empirically), plus two INFO items.

## Warnings

### WR-01: Internal `db` Session parameter leaks onto both LLM-facing tool schemas

**File:** `backend/tools.py:518` (registered via `backend/query.py:163` and `backend/mcp_server.py:95-97`)
**Issue:** `net_worth(db=None)` is registered verbatim as an agent `FunctionTool`
(`FunctionTool.from_defaults(fn=net_worth)`) and as an MCP tool (`mcp.tool(...)(fn)`).
Because `db` is an ordinary positional parameter in the signature, it is exposed as a
tool input on **both** external surfaces. Confirmed empirically against the project venv:

- LlamaIndex: `FunctionTool.from_defaults(fn=net_worth).metadata.get_parameters_dict()`
  → `properties: ['db']`
- FastMCP: `build_mcp()` → `get_tool('net_worth').parameters` → `properties: ['db']`

The docstring and MCP description both state this tool is meant to be called with
zero args (D-02), but the advertised schema invites the model to fill `db`. If the
agent/external LLM hallucinates a value (e.g. `db="session"`), `owns_session` becomes
`False`, the fresh-session branch is skipped, and `portfolio_summary(<non-session>)`
raises — surfacing as a tool error instead of a net-worth number. This is the one tool
in the registry that leaks an internal SQLAlchemy Session onto the public contract.
**Fix:** Register a zero-arg wrapper on the tool surfaces and keep `db` internal to the
endpoint path, e.g.:
```python
def net_worth(db=None) -> dict:      # endpoint calls net_worth(db)
    ...

def net_worth_tool() -> dict:        # what agent + MCP register (no db in schema)
    """Single trustworthy net worth = liquid accounts + investment platforms..."""
    return net_worth()
```
Then register `net_worth_tool` in `TOOLS`/`read_tools`/MCP under the name `net_worth`
(or add `net_worth` to a FunctionTool with an explicit `fn_schema` that omits `db`).

### WR-02: Dashboard "Liquid accounts" per-account delta always equals the balance (misleading)

**File:** `ui/app/cashflow/page.tsx:624-635` (data from `backend/tools.py:541` → `account_balances()` called with no period)
**Issue:** `net_worth()` calls `account_balances()` with **no** `period_start/period_end`.
With no period predicate, the SQL computes
`period_net = COALESCE(SUM(t.amount) FILTER (WHERE true), 0)`, which is identical to
`current_balance = COALESCE(SUM(t.amount), 0)`. The dashboard's "Liquid accounts" card
renders both: `money(a.current_balance)` as the large figure and `signed(a.period_net)`
as a colored (green/terracotta) secondary line that reads as "net change this period."
Because the card is sourced from `netWorthData.liquid_accounts` (unscoped) rather than
the period-scoped `summary.accounts`, that secondary line is always exactly the balance
again. A user who selects "Week" sees the account's all-time balance where a weekly
delta is implied — a duplicated, misleading number on a "never fabricate a number" app.
**Fix:** Don't display `period_net` from the net-worth payload (it is not period-scoped),
or drop the field. If a period delta is wanted per liquid account, source that row from
the period-scoped `summary.accounts` instead. Simplest: remove the
`signed(a.period_net)` line from the net-worth-sourced liquid card
(`ui/app/cashflow/page.tsx:624-635`).

## Info

### IN-01: Net-worth investment total uses stale price cache; can diverge from Investments page

**File:** `backend/tools.py:551` vs `backend/main.py:589`
**Issue:** `net_worth()` calls `portfolio_summary(db)` directly with no price refresh,
while `GET /investments/summary` first calls `refresh_all_prices(db, force=False)` (lazy
refresh of stale tickers) before composing the same summary. As a result the dashboard
net-worth investment figure can reflect an older cached price than the Investments page
shows for the same instant. The number is real (cached), not fabricated, so severity is
low, but the two surfaces can disagree.
**Fix:** If cross-surface consistency matters, have the `/net-worth` endpoint also call
`refresh_all_prices(db, force=False)` before `net_worth(db)` (accepting the added
latency), or document that net-worth reflects last-snapshot prices.

### IN-02: `accounts_covered` and `accounts_total` are always equal by construction

**File:** `backend/tools.py:561-562`
**Issue:** The coverage assertion (`tools.py:544`) raises unless
`len(liquid_rows) + len(investment_rows) == len(rows)`, so by the time the return dict is
built, `accounts_covered` (== that sum) always equals `accounts_total` (== `len(rows)`).
The two fields carry no additional signal to any consumer. Harmless, but the frontend
never uses them either — dead payload surface.
**Fix:** Keep for debuggability, or drop one field. Low priority.

---

_Reviewed: 2026-07-31_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
