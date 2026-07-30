# Phase 14: REST Endpoints + Agent/MCP Tool Registration - Pattern Map

**Mapped:** 2026-07-30
**Files analyzed:** 5 modified (no new files)
**Analogs found:** 5 / 5 (all pattern assignments have exact same-file analogs — this phase is pure wiring, extending existing modules with existing conventions)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog (same file, existing code) | Match Quality |
|---|---|---|---|---|
| `backend/tools.py` (+5 `propose_*` fns, +5 `TOOLS.update()` entries) | service (agent tool) | request-response (proposal creation) | `propose_add_transaction` (tools.py:708-740, simple shape) + `propose_rename_category` (tools.py:916-940, custom-payload shape) | exact |
| `backend/query.py` (+5 imports, +5 `FunctionTool.from_defaults`) | provider (agent tool registration) | request-response | existing `write_tools = [...]` block, query.py:96-190 | exact |
| `backend/main.py` `_execute_proposal_payload` (+5 `elif` branches) | controller (dispatch) | CRUD | existing `elif operation == "add_transaction":` chain, main.py:1014-1073 | exact |
| `backend/main.py` (+5 REST route handlers) | route/controller | request-response (direct write) | `create_account` (main.py:217-225), `create_transaction` (main.py:648) | exact |
| `backend/schemas.py` (+5 `*Create` Pydantic models) | model (DTO) | CRUD | `PortfolioEventCreate` (schemas.py:146-179), `AccountCreate` (schemas.py:107) | exact |
| `backend/tests/test_proposals.py` (+5 integration tests) | test | request-response | existing propose→confirm tests in same file | exact |
| `backend/tests/test_write_endpoints.py` (new file) | test | request-response | `test_account_crud.py`-style `TestClient` + `require_api_key` pattern | role-match |

## Pattern Assignments

### `backend/tools.py` — 5 new `propose_*` functions + registry entries

**Analog A (simple before/after shape):** `propose_add_transaction`, tools.py:708-740
```python
def propose_add_transaction(
    date: str, amount: float, account: str, category: str | None = None,
    merchant: str | None = None, notes: str | None = None,
    currency: str = "IDR", is_transfer: bool = False,
) -> dict:
    after = {
        "date": date, "amount": str(Decimal(str(amount))), "account": account,
        "category": category, "merchant": merchant, "notes": notes,
        "currency": currency, "is_transfer": is_transfer,
    }
    payload = {"operation": "add_transaction", "rows": [{"before": None, "after": after}]}
    proposal_id, proposal_token = _make_proposal("add_transaction", payload)
    return {
        "tool": "propose_add_transaction", "proposal_id": proposal_id,
        "proposal_token": proposal_token,
        "summary": f"Add transaction: {amount} {currency} on {date}",
        "before": None, "after": after,
    }
```
Use this shape for `propose_add_transfer`, `propose_add_investment_transfer`, `propose_add_funded_buy`, `propose_add_funded_sell` — two-leg operations nest `{"leg_a": ..., "leg_b": ...}` or `{"cash_leg": ..., "event": ...}` inside `after` (see RESEARCH.md Pattern 1 for exact key names each `apply_*` expects — **do not guess**, read `backend/writes.py` signatures directly since key names diverge from REST schema field names, e.g. `source_account_name` not `account`, `cash_amount` not `amount`).

**Analog B (custom-payload, non-row shape):** `propose_rename_category`, tools.py:916-940 — model for `propose_add_balance_adjustment` (scalar args, no before/after row).

**Registry snapshot ordering (critical, do not modify — only respect placement):**
```python
# tools.py:628
READ_TOOL_NAMES: frozenset[str] = frozenset(TOOLS)   # snapshot BEFORE write tools merge in

# tools.py:1124
TOOLS.update({
    "propose_add_transaction": propose_add_transaction,
    # ... existing 10 more ...
    # <- ADD the 5 new entries HERE, inside this same .update() call, nowhere else
})
```
Money fields: always `str(Decimal(str(amount)))` in payloads — never a raw `Decimal`/unconverted float (JSONB serialization gotcha, see project memory `auditlog-decimal-json-gotcha`; same risk applies to `Proposal.payload`).

---

### `backend/query.py` — agent tool registration (dual-registration gotcha)

**Analog:** existing `write_tools = [...]` list and `from backend.tools import (...)` block, query.py:96-190. Existing category tools get explicit `description=` overrides (query.py:170-187) when the docstring alone under-specifies — follow that precedent for the 5 new tools' sign conventions (e.g. funded-buy/-sell always-positive `cash_amount`).

```python
# query.py:96-111 style import block extension
from backend.tools import (
    ...,
    propose_add_transfer,
    propose_add_investment_transfer,
    propose_add_funded_buy,
    propose_add_funded_sell,
    propose_add_balance_adjustment,
)

# query.py:164-190 style write_tools list extension
write_tools = [
    ...,
    FunctionTool.from_defaults(fn=propose_add_transfer),
    FunctionTool.from_defaults(fn=propose_add_investment_transfer),
    FunctionTool.from_defaults(fn=propose_add_funded_buy),
    FunctionTool.from_defaults(fn=propose_add_funded_sell),
    FunctionTool.from_defaults(fn=propose_add_balance_adjustment),
]
```
**This is the exact `chat-tool-dual-registration` incident from project memory** — every propose_* function added to `tools.py` MUST also get an entry here or the LLM literally cannot see it.

---

### `backend/main.py` — `_execute_proposal_payload` dispatch (5 new `elif` branches)

**Analog:** existing chain at main.py:1014-1073.
```python
elif operation == "add_transfer":
    row = rows[0]
    after = row["after"]
    apply_add_transfer(db, after["leg_a"], after["leg_b"])

elif operation == "add_investment_transfer":
    row = rows[0]
    after = row["after"]
    apply_add_investment_transfer(db, after["cash_leg"], after["event"])

elif operation == "add_funded_buy":
    apply_add_funded_buy(db, rows[0]["after"])

elif operation == "add_funded_sell":
    apply_add_funded_sell(db, rows[0]["after"])

elif operation == "add_balance_adjustment":
    row = rows[0]
    apply_add_balance_adjustment(db, row["account_id"], row["target_balance"])
```
Append after the existing `add_holding`/`edit_holding`/`delete_holding` branches, before the final `else: raise ValueError(...)`. Requires new imports from `backend.writes` in the `from backend.writes import (...)` block at main.py:58-78 (currently missing all 5 new names).

---

### `backend/main.py` — 5 direct REST route handlers

**Analog:** `create_account`, main.py:217-225 (and `create_transaction`, main.py:648):
```python
@app.post("/accounts", response_model=AccountOut, status_code=201, dependencies=[Depends(require_api_key)])
def create_account(payload: AccountCreate, db: Session = Depends(get_session)):
    acc = apply_add_account(db, payload.model_dump(mode="json"))
    db.commit()
    db.refresh(acc)
    from backend.query import reset_engine
    reset_engine()
    return acc
```
Full transfer example from RESEARCH.md:
```python
@app.post("/transactions/transfer", status_code=201, dependencies=[Depends(require_api_key)])
def create_transfer(payload: TransferCreate, db: Session = Depends(get_session)):
    """Direct (non-agent) transfer between two liquid accounts (CHAT-09, XFER-01)."""
    leg_a_after = {"account": payload.from_account, "amount": str(-abs(payload.amount)),
                    "currency": payload.currency, "date": payload.date, "notes": payload.notes}
    leg_b_after = {"account": payload.to_account, "amount": str(abs(payload.amount)),
                    "currency": payload.currency, "date": payload.date, "notes": payload.notes}
    try:
        leg_a, leg_b = apply_add_transfer(db, leg_a_after, leg_b_after)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    db.commit()
    db.refresh(leg_a)
    db.refresh(leg_b)
    from backend.query import reset_engine
    reset_engine()
    return {"leg_a_id": leg_a.id, "leg_b_id": leg_b.id, "transfer_pair_id": leg_a.transfer_pair_id}
```
Error handling: `ValueError → HTTPException(422)` (project-wide convention, also in `update_account`, main.py:229-244). Commit exactly once per handler; `apply_*` primitives never commit internally (verified `grep -c db.commit` = 0 across `writes.py`).

---

### `backend/schemas.py` — 5 new `*Create` Pydantic request models

**Analog:** `PortfolioEventCreate`, schemas.py:146-179, and `MoneyDecimal` type, schemas.py:18-20:
```python
MoneyDecimal = Annotated[
    Decimal,
    PlainSerializer(lambda x: float(x), return_type=float, when_used="json"),
]

class PortfolioEventCreate(BaseModel):
    ...
    quantity: MoneyDecimal = Field(..., gt=0, description="Units; must be positive")
    price: MoneyDecimal = Field(...)
```
Use `MoneyDecimal` for every money field on the 5 new schemas (`TransferCreate`, `InvestmentTransferCreate`, `FundedBuyCreate`, `FundedSellCreate`, `BalanceAdjustmentCreate`). Use `Field(..., gt=0)` for amounts that must be positive magnitudes (transfer `amount`, funded-buy/-sell `cash_amount`/`quantity`/`price`) — the `apply_*` primitives own sign normalization internally (funded-buy always debits, funded-sell always credits); schemas must reject negative/zero input, never pass a signed value through.

---

### `backend/tests/test_proposals.py` and new `backend/tests/test_write_endpoints.py`

**Analog:** existing propose→confirm integration tests in `test_proposals.py` (fixtures `client`/`api_key`/`db_session` already present); `test_write_tools.py`'s seed-helper idiom (`_make_account`, unique `zz14test-`-prefixed names, `finally`-block cleanup). New REST endpoint tests follow `test_account_crud.py`-style `TestClient` + `require_api_key` header pattern.

## Shared Patterns

### Dual/triple registration checklist (the documented gotcha)
**Source:** project memory `chat-tool-dual-registration`, `TOOLS registry mutates to 26`
**Apply to:** all 5 new `propose_*` tools
Every new agent-facing write tool must appear in exactly 3 places:
1. `backend/tools.py` — inside the trailing `TOOLS.update({...})` call (tools.py:1124), NOT the initial `TOOLS = {...}` dict (tools.py:605-620, which `READ_TOOL_NAMES` snapshots at line 628).
2. `backend/query.py` — both the import block AND the `write_tools = [...]` list (query.py:96-190).
3. `backend/main.py` — imported from `backend.writes` (main.py:58-78) AND referenced in a REST route handler.

Verification grep loop (from RESEARCH.md):
```bash
for fn in propose_add_transfer propose_add_investment_transfer propose_add_funded_buy propose_add_funded_sell propose_add_balance_adjustment; do
  grep -q "$fn" backend/tools.py || echo "MISSING in tools.py: $fn"
  grep -q "$fn" backend/query.py || echo "MISSING in query.py: $fn"
done
```

### Error handling
**Source:** `main.py:229-244` (`update_account`)
**Apply to:** all 5 new REST route handlers
`ValueError → HTTPException(422)`. Wrap the new `_execute_proposal_payload` elif branches' dict access in the same `try/except ValueError` the confirm endpoint already has, so a malformed/missing payload key surfaces as 422, not an unhandled 500 (Pitfall 3 in RESEARCH.md — `apply_*` functions should raise `ValueError`, not let a `KeyError` escape).

### Never-commit contract
**Source:** `backend/writes.py` (Phase 13, unchanged)
**Apply to:** all 5 new dispatch branches and REST handlers
`apply_*` functions never call `db.commit()`. Commit exactly once — in the route handler (REST path) or in `confirm_proposal` (agent path). Never both, never inside `apply_*`.

### `reset_engine()` after every write
**Source:** `create_account`/`create_transaction`/`update_account`, main.py
**Apply to:** all 5 new REST route handlers
```python
from backend.query import reset_engine
reset_engine()
```
Invalidates the cached query engine singleton after mutating data — call after `db.commit()`/`db.refresh()`, before returning the response.

### Money-field JSON round-trip safety
**Source:** project memory `auditlog-decimal-json-gotcha`; `tools.py:723` (`str(Decimal(str(amount)))`)
**Apply to:** all 5 new `propose_*` functions
`Proposal.payload` is a JSONB column — never place a raw `Decimal` or unconverted float into a payload dict; always `str(Decimal(str(x)))`.

## No Analog Found

None — every file/change in this phase has a same-file exact-match analog since it is a pure wiring/extension phase (no new architectural layer, no new packages, per RESEARCH.md).

## Open Items Deferred to Planner (not pattern gaps, but flagged per RESEARCH.md)

- **Investment-transfer scope (RESEARCH.md Open Question 1):** whether to wire all 5 `apply_*` functions or defer `propose_add_investment_transfer`/its REST endpoint — no production ticker convention exists yet for the "deposit" event type. Planner must decide before assigning this file to a plan.
- **`platform_id` vs `platform_name` (RESEARCH.md Open Question 2):** `propose_add_funded_buy`/`_sell` should require `platform_id: int` (not name), mirroring the account-lookup-by-id precedent — no `_get_or_create_platform` helper exists or is needed.

## Metadata

**Analog search scope:** `backend/tools.py`, `backend/query.py`, `backend/main.py`, `backend/schemas.py`, `backend/writes.py`, `backend/tests/` (all already read in full during RESEARCH.md's session per its Sources section; line numbers re-verified current in this session via targeted grep)
**Files scanned:** 5 (all modified, no new source files; 1 new test file)
**Pattern extraction date:** 2026-07-30
