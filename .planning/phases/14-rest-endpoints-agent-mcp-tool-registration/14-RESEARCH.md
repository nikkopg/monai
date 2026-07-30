# Phase 14: REST Endpoints + Agent/MCP Tool Registration - Research

**Researched:** 2026-07-30
**Domain:** FastAPI REST wiring + LlamaIndex agentic tool registration + MCP read-only surface exclusion, on top of Phase 13's shared mutation layer
**Confidence:** HIGH

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CHAT-09 | User can perform the new operations (records, transfers, funded buy/sell, category changes) via chat with the existing confirm-before-write flow; new write tools registered on the agent and kept off the MCP read-only surface | Records + category changes are ALREADY wired (propose_add/edit/delete_transaction, propose_rename/merge_category exist and are registered today). The only genuinely new surface is the 5 Phase-13 `apply_*` functions (transfer, investment-transfer, funded-buy, funded-sell, balance-adjustment) — this research maps every registration point they must touch: `tools.py` TOOLS dict, `query.py` FunctionTool list, `main.py` `_execute_proposal_payload` dispatch, `main.py` REST endpoints + `schemas.py` request models, and confirms `READ_TOOL_NAMES`/MCP exclusion happens automatically by construction as long as the new tools are named `propose_*` and added to the existing `TOOLS.update()` call. |
</phase_requirements>

## Summary

Phase 13 left five new mutation primitives in `backend/writes.py` — `apply_add_transfer`, `apply_add_investment_transfer`, `apply_add_funded_buy`, `apply_add_funded_sell`, `apply_add_balance_adjustment` — fully tested but **called from nowhere**. Phase 14 is pure wiring: no new business logic, no new schema, no new packages. It must (1) add five `propose_*` tool functions to `backend/tools.py` that build `Proposal` payloads the same way the eleven existing `propose_*` functions do, (2) extend `_execute_proposal_payload`'s operation dispatch in `backend/main.py` to call the five new `apply_*` functions, (3) register the five new tools in BOTH `tools.py`'s `TOOLS.update()` call and `query.py`'s `FunctionTool` list (the documented dual-registration gotcha), and (4) add direct (non-agent) REST endpoints for the same five operations, using the exact `apply_add_account`-style pattern (`apply_*(db, ...)` → `db.commit()` → `db.refresh()` → `reset_engine()`).

The codebase already has a **structurally sound MCP-exclusion mechanism** that requires zero new code to keep write tools off the external MCP surface: `READ_TOOL_NAMES = frozenset(TOOLS)` (`tools.py:628`) is captured immediately after the 15 read tools are defined and BEFORE `TOOLS.update({...11 write tools...})` runs at the bottom of the file (`tools.py:1124`). As long as the five new tools are (a) named with the `propose_` prefix and (b) added to that same trailing `TOOLS.update()` dict — not inserted before line 628 — they are automatically excluded from `READ_TOOL_NAMES`, from `mcp_server.py`'s `build_mcp()` loop, and from `test_mcp_no_write_tools` (which asserts generically on `startswith("propose_")`, no per-tool update needed) and `test_agent_read_tools_count` (which filters `not n.startswith("propose_")` and asserts the remainder still equals the 15-name `READ_TOOL_NAMES` set). This is the single most important correctness fact for this phase: **do the registration in the right place and three separate tests pass for free; do it in the wrong place (e.g. add to the initial `TOOLS = {...}` dict) and a write tool silently leaks onto the external MCP surface** — a standing exclusion in `.planning/REQUIREMENTS.md` ("Write tools over MCP to external clients").

**Primary recommendation:** Add the five `propose_*` functions immediately before the existing `TOOLS.update()` call at `tools.py:1124` (after `propose_delete_holding`), add their names to that same `.update()` dict, add matching imports + `FunctionTool.from_defaults(...)` entries to `query.py`'s existing write-tools block (`query.py:108-190`), add five `elif operation == "..."` branches to `main.py:_execute_proposal_payload` (`main.py:1014-1073`), and add five direct-write REST endpoints following the `create_account`/`create_transaction` pattern exactly (import from `backend.writes`, `db.commit()`, `db.refresh()`, `reset_engine()`, `require_api_key` dependency). No new package, no new architectural layer — everything routes through the five already-tested `apply_*` primitives.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Transfer / funded-buy / funded-sell / adjustment business logic (Decimal handling, `is_transfer` tagging, audit rows) | API / Backend (`backend/writes.py`) | — | Already built in Phase 13; Phase 14 must NOT reimplement any of it — only call it |
| Confirm-before-write proposal creation (agent path) | API / Backend (`backend/tools.py` `propose_*` + `_make_proposal`) | Database (`Proposal` row) | Mirrors the 11 existing `propose_*` functions exactly — payload built in Python, persisted, token returned to caller |
| Proposal execution dispatch | API / Backend (`backend/main.py` `_execute_proposal_payload`) | — | Single `if/elif` chain keyed on `payload["operation"]`; already the pattern for all 11 existing operations |
| Direct (non-agent) REST write | API / Backend (`backend/main.py` route handlers) | — | Parallel, simpler call path with no confirm step — same `apply_*` primitive, `require_api_key` gate instead of proposal token |
| Agent tool visibility | API / Backend (`backend/query.py` `_get_agent_workflow`) | — | LLM only sees tools explicitly added to the `FunctionTool` list — the dual-registration gotcha lives here |
| External MCP read-only surface | API / Backend (`backend/mcp_server.py` `build_mcp`) | — | Iterates `READ_TOOL_NAMES` (a pre-mutation snapshot), never `TOOLS` directly — correctness is structural, not enforced by this phase's new code |
| Request validation for direct REST bodies | API / Backend (`backend/schemas.py` new Pydantic models) | — | Follows `AccountCreate`/`PortfolioEventCreate` conventions (MoneyDecimal, `Literal` where a value set is closed) |

## Standard Stack

### Core

No new libraries. This phase extends existing modules using patterns already established in the same files:

| Library | Version (installed) | Purpose | Why Standard (already in use here) |
|---------|---------|---------|--------------|
| FastAPI | >=0.110.0 (`backend/requirements.txt`) [CITED: backend/requirements.txt] | REST route registration | Every existing write endpoint uses `@app.post/put/delete(..., dependencies=[Depends(require_api_key)])` |
| Pydantic v2 | bundled with FastAPI [ASSUMED — version not independently pinned in requirements.txt, inherited from fastapi] | Request body schemas | `MoneyDecimal` (`schemas.py:16-20`) is the mandatory money-field type for any new schema |
| LlamaIndex Core (`llama_index.core.tools.FunctionTool`, `llama_index.core.agent.FunctionAgent`) | >=0.10.0 [CITED: backend/requirements.txt] | Agent tool exposure | `query.py:_get_agent_workflow` builds `read_tools + write_tools`, both plain Python lists of `FunctionTool.from_defaults(fn=...)` |
| FastMCP | version not pinned independently, imported as `fastmcp` [CITED: backend/mcp_server.py:14] | External MCP read-only server | `build_mcp()` already isolates the read surface via `READ_TOOL_NAMES` — Phase 14 adds zero code here if registration order is followed |

### Supporting

No supporting libraries needed — this is a pure application-code phase.

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Extending `_execute_proposal_payload`'s `if/elif` chain | A dispatch dict `{"add_transfer": apply_add_transfer, ...}` | Existing 11 operations are hand-written `elif` branches (some need special before/after unpacking); switching only the 5 new ones to a dict would fragment the pattern for no functional gain — stay consistent with the existing file |
| Naming new propose tools `propose_add_transfer` etc. | A single generic `propose_composed_write(operation, **kwargs)` | Breaks LlamaIndex's per-function docstring/parameter introspection (the LLM picks tools by name+signature+docstring); every existing write tool is single-purpose — no precedent for a generic dispatcher |

**Installation:** None — no new packages this phase.

**Version verification:** N/A — no new dependency versions to check.

## Package Legitimacy Audit

**Not applicable.** This phase installs no new external packages (confirmed: no new imports outside `backend/writes.py`, `backend/tools.py`, `backend/query.py`, `backend/main.py`, `backend/schemas.py` — all already-imported modules). No `npm install` / `pip install` / `cargo add` occurs. Skip the legitimacy gate.

## Architecture Patterns

### System Architecture Diagram

```
                     ┌─────────────────────────────┐
                     │   User (chat or REST client) │
                     └───────────────┬──────────────┘
                                     │
              ┌──────────────────────┼───────────────────────┐
              │ (A) Agent/chat path  │        (B) Direct REST path
              ▼                      │                        ▼
   POST /query-stream (SSE)          │           POST /transactions/transfer
              │                      │           POST /transactions/investment-transfer
              ▼                      │           POST /portfolio-events/funded-buy
   query.py: FunctionAgent picks     │           POST /portfolio-events/funded-sell
   propose_add_transfer(...)         │           POST /accounts/{id}/adjust-balance
   (etc.) from its FunctionTool list │                        │
              │                      │                        │
              ▼                      │                        ▼
   tools.py: propose_add_transfer    │           main.py route handler:
     builds after-dict(s),           │             apply_*(db, ...) directly
     _make_proposal() inserts a      │             (no Proposal row — REST is
     pending Proposal row, returns   │             already API-key-gated,
     {proposal_id, proposal_token}   │             confirm step is chat-only)
              │                      │                        │
              ▼                      │                        │
   SSE answer event carries          │                        │
   proposal_id + token to the        │                        │
   originating chat session          │                        │
              │                      │                        │
              ▼                      │                        │
   User confirms in chat UI:         │                        │
   POST /proposals/{id}/confirm      │                        │
   {token}                           │                        │
              │                      │                        │
              ▼                      │                        │
   main.py: confirm_proposal()       │                        │
     validates status/expiry/token   │                        │
              │                      │                        │
              ▼                      │                        │
   main.py: _execute_proposal_payload(db, proposal)            │
     dispatch on payload["operation"]│                        │
     -> apply_add_transfer(db, ...)  │◄───────────────────────┘
        / apply_add_investment_transfer(db, ...)
        / apply_add_funded_buy(db, ...)
        / apply_add_funded_sell(db, ...)
        / apply_add_balance_adjustment(db, ...)
              │
              ▼
   backend/writes.py (Phase 13, UNCHANGED):
     apply_* composes apply_add_transaction / apply_add_portfolio_event,
     writes AuditLog row(s), never commits
              │
              ▼
   single db.commit() — owned by confirm_proposal() (agent path)
   or by the REST route handler (direct path)
              │
              ▼
         PostgreSQL

   ─────────────────────────────────────────────────────────────
   Separately, at import time (module load, not per-request):

   tools.py:  TOOLS = {...15 read...}
              READ_TOOL_NAMES = frozenset(TOOLS)   <- captured HERE, before writes exist
              TOOLS.update({...11+5 propose_* write tools...})

   mcp_server.py: build_mcp() iterates READ_TOOL_NAMES only
              -> external MCP client (tools/list) never sees any propose_* name
```

### Recommended Project Structure

No new files or directories. All changes are additions inside existing modules:

```
backend/
├── writes.py     # UNCHANGED — Phase 13 already complete, only imported from
├── tools.py      # + 5 propose_* functions, + 5 entries in TOOLS.update()
├── query.py      # + 5 imports, + 5 FunctionTool.from_defaults() entries, + system-prompt mention (optional)
├── schemas.py    # + request models for the 5 new REST bodies
├── main.py       # + 5 imports from backend.writes, + 5 elif branches in _execute_proposal_payload,
│                 #   + 5 REST route handlers
└── tests/
    ├── test_write_tools.py   # UNCHANGED — apply_* already unit-tested in Phase 13
    ├── test_proposals.py     # + propose→confirm integration tests for the 5 new operations
    ├── test_agent.py         # optionally + assertion that new tool names appear in agent.tools
    └── test_mcp.py           # UNCHANGED — startswith("propose_") assertions already generalize
```

### Pattern 1: `propose_*` write-tool function (agent-facing)

**What:** A plain Python function with typed keyword args and a docstring (LlamaIndex reads both for tool-choice), which builds a `payload` dict, calls `_make_proposal(operation, payload)`, and returns a structured `{"tool", "proposal_id", "proposal_token", "summary", "before", "after"}` dict. Never touches the target tables directly.

**When to use:** For every one of the five new operations (transfer, investment-transfer, funded-buy, funded-sell, balance-adjustment).

**Example (transfer, following `propose_add_transaction`'s shape at `tools.py:708-740`):**
```python
# Source: backend/tools.py:708-740 pattern (propose_add_transaction), adapted for two legs
def propose_add_transfer(
    from_account: str,
    to_account: str,
    amount: float,
    currency: str = "IDR",
    date: str | None = None,
    notes: str | None = None,
) -> dict:
    """Propose a transfer between two liquid accounts. Returns a proposal for
    user confirmation. Does NOT move any money — user must approve."""
    leg_a_after = {
        "account": from_account, "amount": -abs(amount), "currency": currency,
        "date": date, "notes": notes,
    }
    leg_b_after = {
        "account": to_account, "amount": abs(amount), "currency": currency,
        "date": date, "notes": notes,
    }
    payload = {
        "operation": "add_transfer",
        "rows": [{"before": None, "after": {"leg_a": leg_a_after, "leg_b": leg_b_after}}],
    }
    proposal_id, proposal_token = _make_proposal("add_transfer", payload)
    return {
        "tool": "propose_add_transfer",
        "proposal_id": proposal_id,
        "proposal_token": proposal_token,
        "summary": f"Transfer {amount} {currency} from {from_account} to {to_account}",
        "before": None,
        "after": {"leg_a": leg_a_after, "leg_b": leg_b_after},
    }
```
`is_transfer=True` is NOT set here — `apply_add_transfer` forces it defensively on both legs (`writes.py:150-168`, per the phase-13 explicit-True rule). Do not duplicate the flag in the tool if the primitive already forces it, but it is harmless to include for clarity in the `after` dict shown to the user.

**Balance adjustment does NOT use before/after row shape** — it follows the `propose_rename_category`/`propose_merge_category` precedent (`tools.py:916-1013`) of custom payload keys, since `apply_add_balance_adjustment(db, account_id, target_balance)` takes positional scalars, not a before/after dict:
```python
# Source: backend/tools.py:916-940 pattern (propose_rename_category), adapted
def propose_add_balance_adjustment(account_id: int, target_balance: float) -> dict:
    """Propose reconciling an account's balance to target_balance. The stored
    delta becomes a visible 'Adjustment' record. Returns a proposal for user
    confirmation. Does NOT change any data — user must approve."""
    from backend.models import Account
    with get_session_sync() as db:
        acc = db.get(Account, account_id)
        if acc is None:
            return {"tool": "propose_add_balance_adjustment", "error": f"Account {account_id} not found"}
    payload = {
        "operation": "add_balance_adjustment",
        "rows": [{"account_id": account_id, "target_balance": str(target_balance)}],
    }
    proposal_id, proposal_token = _make_proposal("add_balance_adjustment", payload)
    return {
        "tool": "propose_add_balance_adjustment",
        "proposal_id": proposal_id,
        "proposal_token": proposal_token,
        "summary": f"Adjust account #{account_id} ({acc.name}) balance to {target_balance}",
        "before": None,
        "after": {"account_id": account_id, "target_balance": str(target_balance)},
    }
```
Note: `target_balance` is coerced to `str()` in the payload for the same JSON-serialization reason documented in `writes.py` — `Proposal.payload` is a JSONB column and a raw `Decimal`/float precision artifact should not be trusted through a JSON round-trip; `apply_add_balance_adjustment` re-applies `Decimal(str(x))` itself.

### Pattern 2: `_execute_proposal_payload` dispatch branch

**What:** One `elif operation == "...":` branch per operation inside `main.py:_execute_proposal_payload` (`main.py:1014-1073`), unpacking the payload's `rows[0]` shape into the matching `apply_*` call.

**Example:**
```python
# Source: backend/main.py:1014-1073 pattern, extended
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
Ordering inside the `if/elif` chain does not matter functionally — append after the existing `add_holding`/`edit_holding`/`delete_holding` branches, before the final `else: raise ValueError(...)`.

### Pattern 3: Dual/triple registration checklist (the documented gotcha)

**What:** Every new agent-facing write tool must appear in exactly these three places, or two known project incidents recur (`chat-tool-dual-registration`, `TOOLS registry mutates to 26` — both in project memory).

**When to use:** For each of the 5 new tools, verify all three:

1. `backend/tools.py` — inside the `TOOLS.update({...})` call at the bottom of the file (currently `tools.py:1124-1136`), NOT inside the initial `TOOLS = {...}` dict at the top (`tools.py:605-620`) — that dict is what `READ_TOOL_NAMES` snapshots.
2. `backend/query.py` — inside `_get_agent_workflow`'s `from backend.tools import (...)` block (`query.py:96-111`) AND inside the `write_tools = [...]` list (`query.py:164-190`), each as `FunctionTool.from_defaults(fn=propose_add_transfer)` (or with an explicit `description=` override if the docstring alone under-specifies units/signs, matching how `propose_rename_category`/`propose_merge_category` get an explicit description at `query.py:170-187`).
3. `backend/main.py` — imported from `backend.writes` in the `from backend.writes import (...)` block (`main.py:58-78`, currently missing all 5 new names) AND referenced in a REST route handler.

**Verification command for reviewers/planner (mirrors Phase 13's `grep -c` idiom):**
```bash
# Every propose_* name defined in tools.py must also appear in query.py's FunctionTool block
for fn in propose_add_transfer propose_add_investment_transfer propose_add_funded_buy propose_add_funded_sell propose_add_balance_adjustment; do
  grep -q "$fn" backend/tools.py || echo "MISSING in tools.py: $fn"
  grep -q "$fn" backend/query.py || echo "MISSING in query.py: $fn"
done
```

### Pattern 4: Direct REST write endpoint (non-agent path)

**What:** A plain FastAPI route, `require_api_key`-gated, that calls the `apply_*` primitive directly (no `Proposal` row, no confirm step — REST callers are already API-key-authenticated, unlike the chat UI where an LLM cannot be trusted to write without a human-in-the-loop confirm).

**Example (following `create_account`, `main.py:217-225`, exactly):**
```python
# Source: backend/main.py:217-225 pattern (create_account), adapted
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
The `ValueError → HTTPException(422)` mapping is the project-wide error-handling convention (`update_account`, `main.py:229-244`, does the same). `reset_engine()` after every write follows the identical pattern in `create_account`/`create_transaction`/`update_account` — every existing write endpoint invalidates the cached query engine singleton after mutating data.

### Anti-Patterns to Avoid

- **Registering a new write tool inside the initial `TOOLS = {...}` dict (`tools.py:605-620`) instead of the trailing `TOOLS.update()` call:** silently leaks the tool onto `READ_TOOL_NAMES` and therefore onto the external MCP surface — the exact standing exclusion the project forbids ("Write tools over MCP to external clients").
- **Adding a `propose_*` function to `tools.py` but forgetting the `query.py` import/`FunctionTool` entry:** the tool becomes callable via direct Python import and via REST if separately wired, but the LLM literally cannot see it — this is the documented `chat-tool-dual-registration` incident recurring.
- **Building a new generic `apply_*` dispatcher or hand-rolled SQL for the REST endpoints instead of calling the existing Phase-13 `apply_*` functions:** violates SC #4 explicitly and duplicates Decimal/audit-log/`is_transfer` logic that Phase 13 already got right and tested.
- **Letting the REST endpoint or the confirm-dispatch branch call `db.commit()` more than once, or call it inside the `apply_*` function:** breaks the never-commit contract (D-01) that gives multi-row atomicity "for free." All 5 `apply_*` functions are verified (`grep -c db.commit` = 0) to never commit — the wiring code in Phase 14 must preserve that by committing exactly once, in the route handler or in `confirm_proposal`, never both.
- **Re-deriving the balance-adjustment delta in the REST endpoint or the propose tool instead of passing `target_balance` straight through to `apply_add_balance_adjustment`:** the fresh unfiltered-SUM delta computation is inside `writes.py` for a reason (Finding 2 — `tools.py:account_balances` would give the wrong number); Phase 14 code should never compute or reference a balance itself, only pass the user's stated target through.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Transfer / funded-buy/-sell / investment-transfer / adjustment mutation logic | New SQL, new ORM inserts, a new "unified write" abstraction | `backend.writes.apply_add_transfer` / `apply_add_investment_transfer` / `apply_add_funded_buy` / `apply_add_funded_sell` / `apply_add_balance_adjustment` | Already built, audited, and unit-tested in Phase 13; reimplementing risks silently diverging Decimal handling, `is_transfer` tagging, or audit-log shape between the agent and REST call paths — the exact bug class the shared mutation layer exists to prevent |
| Proposal creation / token / expiry machinery | A new proposal type, a new confirm endpoint, a new token scheme | `_make_proposal(operation, payload)` + the existing `/proposals/{id}/confirm` endpoint | Token generation (`secrets.token_urlsafe`), 15-minute expiry, single-use enforcement, and audit are already correct and tested (`test_proposals.py`) — the 5 new operations are just 5 more `operation` string values flowing through the same machinery |
| Read-tool / write-tool separation for MCP | A new allowlist, a new tool-filtering decorator | `READ_TOOL_NAMES = frozenset(TOOLS)` snapshot mechanism, already in `tools.py:628` | Correct by construction as long as new tools are added after the snapshot; adding a parallel mechanism risks the two allowlists drifting apart |
| Holding / position recomputation for funded buy/sell | Direct `UPDATE holdings SET ...` | `apply_add_portfolio_event` (internally calls `recompute_holding_from_events`) | Already the sole updater per D-06; `apply_add_funded_buy`/`_sell` already call it — Phase 14 must not touch `holdings` directly |

**Key insight:** This entire phase is wiring, not logic. Every "don't hand-roll" item above already exists and is tested; the risk in Phase 14 is 100% concentrated in registration completeness (are all 5 tools in all the right lists?) and payload-shape correctness (does the `propose_*` function build an `after` dict whose keys exactly match what the `apply_*` function expects?), not in algorithmic correctness.

## Common Pitfalls

### Pitfall 1: Registering a write tool before the `READ_TOOL_NAMES` snapshot line
**What goes wrong:** A new `propose_*` entry added to the initial `TOOLS = {...}` dict (or added via a second early `.update()` call before `tools.py:628`) becomes part of `READ_TOOL_NAMES`, and `mcp_server.py:build_mcp()` then registers it as an MCP tool visible to external clients.
**Why it happens:** The file has two dict-construction points 500+ lines apart (`605` and `1124`); it's easy to add a new function definition near the top of the write-tools section and forget the registry entry belongs at the bottom.
**How to avoid:** Always add new `propose_*` tool entries to the trailing `TOOLS.update({...})` call only. Never touch the initial `TOOLS = {...}` dict or the `READ_TOOL_NAMES` line.
**Warning signs:** `test_mcp_read_parity` fails asserting `len(listed_names) == 15` (would now be 16+), or `test_mcp_no_write_tools`'s `not any(n.startswith("propose_") ...)` fails.

### Pitfall 2: Tool defined in `tools.py`, never added to `query.py`'s `FunctionTool` list
**What goes wrong:** The tool works when called directly in Python/tests, and shows up in `TOOLS` (so any code iterating `TOOLS` sees it), but the LLM's `FunctionAgent` never learns about it — chat requests for that operation get refused ("I can't compute that reliably...") or mis-routed to a different tool.
**Why it happens:** `query.py` maintains its own separate import list and `FunctionTool.from_defaults(...)` list — nothing enforces parity with `tools.py`'s `TOOLS` dict automatically. This is the exact `chat-tool-dual-registration` incident from project memory.
**How to avoid:** Treat every new propose tool as a 2-file change from the start; use the verification grep loop in Pattern 3 before considering the task done.
**Warning signs:** Manual chat test says "I can't do that" for an operation that should work; `test_agent_read_tools_count`-style introspection of `agent.tools` doesn't list the new name.

### Pitfall 3: Payload key mismatch between `propose_*` and the `apply_*` signature
**What goes wrong:** `apply_add_transfer(db, leg_a_after, leg_b_after)` takes two positional dict args; `apply_add_investment_transfer(db, cash_leg_after, event_after)` takes two differently-shaped dicts; `apply_add_funded_buy(db, after)`/`apply_add_funded_sell(db, after)` take ONE dict with a specific flat key set (`source_account_name`, `cash_amount`, `cash_currency`, `ticker`, `quantity`, `price`, `platform_id`, `event_currency`, `date`, `notes`, `asset_type`). If the `propose_*` tool's `payload["rows"][0]["after"]` dict uses different key names (e.g. `account` instead of `source_account_name`), `_execute_proposal_payload`'s dispatch call raises a `KeyError`, NOT a clean `ValueError → 422` — it becomes an unhandled 500.
**Why it happens:** Four different apply_* functions have four different `after`-dict shapes (unlike the uniform `{id, before, after}` shape of the 11 existing simple CRUD operations) — Phase 13's composed functions were designed around convenience for the caller who already has the right shape, not around a single generic contract.
**How to avoid:** Read the exact `after["..."]` key accesses inside each target `apply_*` function in `writes.py` before writing the corresponding `propose_*` function's payload-building code — do not guess key names from the REST `PortfolioEventCreate`/`TransactionCreate` schemas, which use different field names (`account` vs `source_account_name`, `amount` vs `cash_amount`).
**Warning signs:** A propose→confirm integration test 500s inside `confirm_proposal` with a `KeyError` traceback instead of cleanly asserting on the resulting rows.

### Pitfall 4: `apply_add_funded_buy`/`_sell` cash-leg sign convention
**What goes wrong:** `apply_add_funded_buy` internally does `cash_amount = -abs(after["cash_amount"])` (always debits) and `apply_add_funded_sell` does `cash_amount = abs(after["cash_amount"])` (always credits) — regardless of what sign the caller passed in `after["cash_amount"]`. If the `propose_*` tool or REST schema also tries to apply a sign convention (e.g. accepting a signed `amount` field and passing it straight through), the double-negation either cancels out correctly by luck or silently produces the wrong sign depending on which function ends up abs()-ing what.
**Why it happens:** The primitive already normalizes sign — callers are expected to pass an unsigned magnitude in `cash_amount`.
**How to avoid:** Design the `propose_add_funded_buy`/`propose_add_funded_sell` and their REST schema counterparts to accept an always-positive `cash_amount` (document it in the docstring/`Field(..., gt=0)`), never a signed amount — let the `apply_*` primitive own the sign.
**Warning signs:** A funded-sell test shows a negative cash-leg amount (money leaving instead of arriving) or vice versa for a funded-buy.

### Pitfall 5: Decimal → JSON round-trip inside `Proposal.payload`
**What goes wrong:** `Proposal.payload` is a JSONB column. If a `propose_*` tool puts a raw `Decimal` object into the `after` dict (instead of `str(Decimal(...))`), SQLAlchemy/psycopg's JSON serialization of the dict either raises `TypeError: Object of type Decimal is not JSON serializable` at `_make_proposal`'s `db.add(proposal)` / `db.commit()`, or (if caught elsewhere) produces a proposal that can never be confirmed.
**Why it happens:** This exact class of bug already bit Phase 13 (`AuditLog.after` Decimal-JSON gotcha, in project memory) — `Proposal.payload` has the identical JSONB-column risk, one layer earlier in the pipeline (proposal creation, not just proposal execution).
**How to avoid:** In every new `propose_*` function, build `after`-dict money fields as `str(amount)` / `str(Decimal(str(amount)))`, mirroring `propose_add_transaction`'s `"amount": str(Decimal(str(amount)))` at `tools.py:723`. Never place a bare `Decimal`, `float` that could carry binary artifacts unconverted, or any non-JSON-native type into a `payload` dict.
**Warning signs:** `_make_proposal` raises during `db.commit()`, or (worse) a proposal is created successfully but `_execute_proposal_payload` later fails deserializing an unexpected type from `proposal.payload` (JSONB round-trips through `str`/`float`/`int`/`bool`/`None`/`dict`/`list` only).

### Pitfall 6: `apply_add_investment_transfer`'s `event_type="deposit"` — no established production ticker convention
**What goes wrong:** `apply_add_investment_transfer` calls `apply_add_portfolio_event(db, event_after)`, which requires `event_after["ticker"]` and inserts it verbatim into `portfolio_events.ticker` (a plain, non-enum `String(32)` column — no CHECK constraint enforces `event_type ∈ {buy,sell,dividend}` at this layer; that enum is only enforced by the REST-only `PortfolioEventCreate` Pydantic schema, which `apply_add_portfolio_event` is NOT gated behind when called from the propose/confirm or a hand-built direct-REST path). Phase 13's own test (`test_apply_add_investment_transfer`, `test_write_tools.py:1331`) uses a placeholder ticker (`"ZZ13DEPOSIT"`) — there is no real convention documented anywhere for what ticker a liquid→investment "deposit" event should carry in production data, and this event would show up in `find_transactions`/portfolio views mixed in with real buy/sell/dividend rows under a made-up ticker.
**Why it happens:** Phase 13's scope was the mutation primitive, not the UX/data-model question of how a cash-deposit-into-a-platform should be represented in the ticker-keyed `portfolio_events` ledger.
**How to avoid:** This is a genuine open design question the planner should resolve explicitly (with the user, or via `CONTEXT.md` if `/gsd-discuss-phase` runs) before choosing a ticker convention — e.g., a fixed sentinel ticker per platform's base currency, or descoping `propose_add_investment_transfer`/its REST endpoint from Phase 14 if XFER-02 chat/REST exposure isn't actually required by CHAT-09's wording (CHAT-09 says "transfers" and "funded buy/sell" — plain investment-transfer/deposit exposure is a plausible in-scope 5th operation but is the least specified of the five).
**Warning signs:** No test or doc anywhere defines the ticker string for a deposit event; if the planner picks one silently, flag it for human review.

## Code Examples

Verified patterns from the actual codebase (all line numbers current as of 2026-07-30):

### Existing simple write-tool pattern (model for the 4 non-adjustment new tools)
```python
# Source: backend/tools.py:708-740 (propose_add_transaction, verified current)
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

### `READ_TOOL_NAMES` snapshot mechanism (do not modify, only respect ordering)
```python
# Source: backend/tools.py:605-628, verified current
TOOLS = {
    "spending_total": spending_total, "income_total": income_total, "net_total": net_total,
    # ... 12 more read tools ...
}
READ_TOOL_NAMES: frozenset[str] = frozenset(TOOLS)   # <- snapshot BEFORE write tools merge in

# ... (helper functions, all propose_* function definitions) ...

TOOLS.update({
    "propose_add_transaction": propose_add_transaction,
    # ... 10 more existing write tools ...
    # NEW 5 ENTRIES GO HERE, at the end of this same dict literal
})
```

### `_execute_proposal_payload` operation dispatch (add new elif branches at the end)
```python
# Source: backend/main.py:1014-1073, verified current
def _execute_proposal_payload(db: Session, proposal: Proposal) -> None:
    payload = proposal.payload
    operation = payload.get("operation", "")
    rows = payload.get("rows", [])
    for row in rows:
        before = row.get("before")
        after = row.get("after")
        if operation == "add_transaction":
            apply_add_transaction(db, after)
        # ... 10 more existing elif branches ...
        else:
            raise ValueError(f"Unknown proposal operation: {operation!r}")
```

### Direct REST write following the established `require_api_key` + commit + reset_engine idiom
```python
# Source: backend/main.py:217-225, verified current (create_account)
@app.post("/accounts", response_model=AccountOut, status_code=201, dependencies=[Depends(require_api_key)])
def create_account(payload: AccountCreate, db: Session = Depends(get_session)):
    acc = apply_add_account(db, payload.model_dump(mode="json"))
    db.commit()
    db.refresh(acc)
    from backend.query import reset_engine
    reset_engine()
    return acc
```

### MoneyDecimal schema convention (use for every new REST body's money field)
```python
# Source: backend/schemas.py:16-20, verified current
MoneyDecimal = Annotated[
    Decimal,
    PlainSerializer(lambda x: float(x), return_type=float, when_used="json"),
]
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| Hand-rolled inserts per write endpoint | Shared `apply_*` mutation layer (`writes.py`) called from BOTH the confirm-dispatch and direct REST endpoints | Phase 13 (2026-07-30) | Phase 14 must route every new endpoint/tool through `apply_*`, never write raw SQL/ORM inserts itself — this is the whole point of the phase ordering (13 before 14) per the roadmap rationale in `STATE.md` |
| `accounts.type` inferred / decorative | DB-enforced `liquid`/`investment` discriminator | Phase 12 | Not directly relevant to Phase 14's wiring, but the new transfer/adjustment endpoints operate on already-typed accounts — no new type-inference logic needed |

**Deprecated/outdated:** None — Phase 14 operates entirely within the current, just-completed Phase 13 architecture. No prior pattern is being replaced.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | REST endpoint URL/method naming (`POST /transactions/transfer`, `/transactions/investment-transfer`, `/portfolio-events/funded-buy`, `/portfolio-events/funded-sell`, `/accounts/{id}/adjust-balance`) — these are proposed by this research, not dictated by any existing convention beyond the `/categories/rename`, `/categories/merge` precedent of verb-suffixed POST routes | Architecture Patterns, Pattern 4 | Low — purely a naming/routing choice; wrong names are a cheap rename, not a correctness risk. Planner has full discretion here. |
| A2 | Direct REST endpoints should skip the confirm-proposal flow entirely (write immediately behind `require_api_key`, like every other existing direct REST write) rather than also going through a Proposal | Summary, Architecture Patterns Pattern 4 | Medium — if the intended design is actually "REST also requires confirm," every existing REST write endpoint (`create_account`, `create_transaction`, etc.) already contradicts that, so this is a strong precedent-based inference, not a guess, but it's not explicitly restated as a rule anywhere in Phase 13/14 docs |
| A3 | The five new `propose_*` tool names (`propose_add_transfer`, `propose_add_investment_transfer`, `propose_add_funded_buy`, `propose_add_funded_sell`, `propose_add_balance_adjustment`) — chosen by this research to mirror `apply_*` names 1:1, no existing doc mandates these exact strings | Architecture Patterns Pattern 1, Code Examples | Low — internal naming choice; LLM tool-selection quality depends on clear names/docstrings more than the exact string, and dual-registration verification (Pattern 3) works regardless of the chosen name as long as it starts with `propose_` |
| A4 | Production ticker convention for `apply_add_investment_transfer`'s `event_type="deposit"` PortfolioEvent — no real value is defined anywhere in the codebase, only a test placeholder (`"ZZ13DEPOSIT"`) | Common Pitfalls, Pitfall 6 | High — if the planner invents a convention without user sign-off, it could pollute the ticker-keyed portfolio_events ledger with data that has no clear query/display story in Phase 17's PnL/history tabs. Recommend flagging for explicit user decision or considering investment-transfer REST/chat exposure a stretch item within Phase 14, since CHAT-09's text ("transfers, funded buy/sell") does not explicitly name plain liquid→investment deposit-transfers as a requirement. |
| A5 | LlamaIndex Core version `>=0.10.0` and FastAPI `>=0.110.0` pins in `backend/requirements.txt` are current/unchanged since last verified (not re-checked against PyPI this session — no new dependency work in this phase) | Standard Stack | Low — this phase adds no dependency, so version drift here has zero bearing on Phase 14's correctness |

## Open Questions (RESOLVED)

> **Resolution (2026-07-30, autonomous run — plan-checker W1):**
> **Q1 → (a) wire all 5 `apply_*`, including `apply_add_investment_transfer`.** Rationale: the phase goal is "*every* new write from Phase 13 is reachable"; descoping would leave a tested Phase-13 primitive unwired. The deposit PortfolioEvent uses a documented sentinel — `ticker="CASH"`, `event_type="deposit"`, `asset_type="cash"`, `price=1`, `quantity=amount` — consistent with the existing `asset_type=="cash"` 1:1-valuation convention in `portfolio.py`/`prices.py` (a real convention, not invented). This is a forward-affecting data-model choice on RESEARCH-flagged HIGH-risk territory (A4/Pitfall 6); it pollutes nothing until a user actually triggers the write through the confirm-before-write flow, so it is flagged for the user in the loop's final summary for a one-line confirmation before first production use.
> **Q2 → `platform_id: int`** (account-id precedent; LLM resolves names→ids via the existing `find_platforms` read tool). No new platform-resolution helper.

1. **Should the plain liquid→investment "deposit" transfer (`apply_add_investment_transfer`, XFER-02) get chat/REST exposure in Phase 14 at all?**
   - What we know: The `apply_*` primitive exists and is tested; CHAT-09's literal wording lists "transfers, funded buy/sell, category changes" — funded buy/sell and liquid↔liquid transfers are unambiguous, but a bare liquid→investment "deposit with no matching buy/sell" is a third, less-discussed shape.
   - What's unclear: Whether there's a real user workflow for "just move cash into Stockbit without immediately buying anything" versus whether every real liquid→investment movement in practice always accompanies a funded buy (in which case `apply_add_investment_transfer` might not need its own tool/endpoint at all in this milestone).
   - Recommendation: Planner should explicitly decide (ideally via `/gsd-discuss-phase` or a direct question to the user) whether to (a) wire all 5 apply_* functions, or (b) wire only 4 (transfer, funded-buy, funded-sell, balance-adjustment) and defer investment-transfer exposure, noting `apply_add_investment_transfer` remains available for a future phase. If (a), resolve the ticker-convention question in Pitfall 6 first.

2. **Should `propose_add_funded_buy`/`propose_add_funded_sell` accept a `platform_id` (int, requiring the LLM to have already called `find_platforms`) or a `platform_name` (str, resolved server-side)?**
   - What we know: `apply_add_funded_buy`/`_sell` require `after["platform_id"]` (int) — `apply_add_portfolio_event` has no by-name resolution helper analogous to `_get_or_create_account` for accounts (platforms are matched by exact id, never created implicitly — `Platform` has no `_get_or_create_platform` equivalent found in `importer.py` or `writes.py`).
   - What's unclear: Whether adding a `_get_or_create_platform`-style helper is in scope for Phase 14, or whether the propose tool should require an id and rely on the agent's existing `find_platforms` read tool + its own system-prompt reasoning to resolve names to ids first (the same pattern `find_accounts`/`propose_edit_account` already establishes for accounts, where account is looked up by id, not created by name inside the write tool).
   - Recommendation: Follow the account precedent — require `platform_id: int` in the propose tool signature (not a name), and rely on the LLM calling `find_platforms` first (already an existing read tool, per the RULES section of `query.py`'s system prompt, item 2: "use the minimum number of tool calls needed"). No new platform-resolution helper needed. Mirror the same choice for the REST schema (`platform_id: int`, required).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| PostgreSQL (Docker, port 5434) | All new endpoints/tools (writes hit the DB) | ✓ | postgres:16-alpine, `monai-db` container healthy | — |
| Docker Compose stack (`monai-backend`, `monai-db`, `monai-frontend`) | Live verification of new endpoints | ✓ | `monai-backend`/`monai-db`/`monai-frontend` all `Up` | — |
| Python backend deps (fastapi, sqlalchemy, llama-index) on HOST | Running `pytest`/uvicorn directly on the host (not in Docker) | ✗ (host Python 3.14.4 has no `fastapi` installed) | — | Run tests/backend via the `monai-backend` Docker container, or `uv run --with-requirements backend/requirements.txt` per `CLAUDE.md`'s documented dev runner — do not assume a bare `pytest backend/tests/` works on host without one of these |
| `uv` (dev runner) | Alternative host-side dependency execution | ✓ | 0.11.17 | — |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:** Host-installed backend Python packages — use `uv run --with-requirements backend/requirements.txt -- pytest backend/tests/...` (documented project convention) or exec into the running `monai-backend` container, per the `deploy-requires-rebuild` project memory: code changes require `docker compose up -d --build` before live/manual verification against the running stack.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest >=8.0.0 [CITED: backend/requirements.txt] |
| Config file | none — bare `pytest.ini`/`pyproject.toml` config not found; tests run via `pytest backend/tests/` with live-Postgres fixtures (`db_available` skip-if-unreachable pattern, used throughout `test_write_tools.py`, `test_proposals.py`, `test_mcp.py`) |
| Quick run command | `pytest backend/tests/test_proposals.py backend/tests/test_mcp.py backend/tests/test_agent.py -x` (or via `uv run --with-requirements backend/requirements.txt -- pytest ...` on host) |
| Full suite command | `pytest backend/tests/ -q` (256 passed / 1 pre-existing unrelated failure as of Phase 13 close — `test_settings.py::test_put_settings_requires_key`, documented out-of-scope) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CHAT-09 | propose_add_transfer → confirm → both legs written, paired via `transfer_pair_id` | integration | `pytest backend/tests/test_proposals.py::test_confirm_transfer_writes_both_legs -x` | ❌ Wave 0 — new test to add |
| CHAT-09 | propose_add_funded_buy → confirm → cash leg debited + portfolio_event + holding recomputed | integration | `pytest backend/tests/test_proposals.py::test_confirm_funded_buy_writes_both_sides -x` | ❌ Wave 0 |
| CHAT-09 | propose_add_funded_sell → confirm → cash leg credited + portfolio_event | integration | `pytest backend/tests/test_proposals.py::test_confirm_funded_sell_writes_both_sides -x` | ❌ Wave 0 |
| CHAT-09 | propose_add_balance_adjustment → confirm → single Adjustment transaction, correct delta | integration | `pytest backend/tests/test_proposals.py::test_confirm_balance_adjustment -x` | ❌ Wave 0 |
| CHAT-09 | New propose_* names present in `TOOLS` AND absent from `READ_TOOL_NAMES` | unit | `pytest backend/tests/test_mcp.py::test_mcp_no_write_tools -x` (generic — no change needed, already passes if registration is correct) | ✅ existing, generalizes |
| CHAT-09 | New propose_* names present in agent's `FunctionTool` list | unit | `pytest backend/tests/test_mcp.py::test_agent_read_tools_count -x` (generic filter, no change needed) | ✅ existing, generalizes |
| CHAT-09 | Direct REST endpoints (non-agent) route through apply_* and reject bad input with 422 | integration | `pytest backend/tests/test_write_endpoints.py -x` (new file) | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest backend/tests/test_proposals.py backend/tests/test_mcp.py -x`
- **Per wave merge:** `pytest backend/tests/ -q`
- **Phase gate:** Full suite green (or only the pre-existing, documented `test_settings.py` failure) before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `backend/tests/test_proposals.py` — add propose→confirm integration tests for the 5 new operations (extend existing file; fixtures `client`/`api_key`/`db_session` already present and reusable, per Phase 13's `test_write_tools.py` seed-helper idiom — `_make_account`, unique `zz14test-`-prefixed names, `finally`-block cleanup)
- [ ] `backend/tests/test_write_endpoints.py` (new file, or extend `test_account_crud.py`/`test_transaction_crud.py`-style pattern) — direct REST endpoint tests for the 5 new routes, following `test_account_crud.py`'s `TestClient` + `require_api_key` header pattern
- [ ] Optionally: an assertion in `test_agent.py` (or a small addition to `test_mcp.py`) that explicitly names the 5 new tools by string, so a future accidental rename/removal is caught immediately rather than relying only on the generic count/prefix checks

*(No framework install needed — pytest, the `client`/`api_key`/`db_session` fixtures, and the live-Postgres skip-if-unavailable pattern are already fully established across `test_proposals.py`, `test_write_tools.py`, `test_mcp.py`.)*

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | Indirect | `MONAI_API_KEY` header (`backend/auth.py:require_api_key`) gates every write endpoint and the MCP mount — unchanged this phase, but every new REST endpoint MUST include `dependencies=[Depends(require_api_key)]` exactly like all 20+ existing write routes |
| V3 Session Management | No | Single-user app, no session/cookie auth in scope |
| V4 Access Control | Yes | Single-user app has no per-resource ACL, but the confirm-proposal flow's `hmac.compare_digest(req.token, proposal.token)` (`main.py:1101`) is the closest analog to access control — new operations reuse this unchanged; do not add a parallel confirm mechanism |
| V5 Input Validation | Yes | New Pydantic schemas for REST bodies MUST use `MoneyDecimal` for amount/price/quantity fields (`Field(..., gt=0)` where the domain requires positivity, e.g. transfer `amount`, funded-buy/sell `cash_amount`/`quantity`/`price`) and MUST NOT accept a literal `account_id`/`platform_id` without existence validation delegated to the `apply_*` primitive's `db.get(...)` null-check + `ValueError` → `HTTPException(422)` mapping |
| V6 Cryptography | Indirect | Proposal token generation/comparison (`secrets.token_urlsafe(32)`, `hmac.compare_digest`) is unchanged infrastructure this phase reuses — never hand-roll a new token scheme for the 5 new operations |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Proposal replay (confirming the same token twice) | Repudiation / Tampering | Already mitigated by `proposal.status != "pending"` → 409 check (`main.py:1097-1098`) — the 5 new operations flow through the same `confirm_proposal` endpoint, no new code needed here |
| Double-count leak (a new transfer/adjustment leg missing `is_transfer=True`) | Tampering (data integrity) | `apply_add_transfer`/`apply_add_investment_transfer`/`apply_add_funded_buy`/`apply_add_funded_sell` already force `is_transfer=True` defensively inside `writes.py` (T-13-07, closed in Phase 13's security audit) — Phase 14's `propose_*`/REST code does not need to (and should not attempt to) re-derive this flag; passing it explicitly in the `after` dict is harmless but redundant |
| KeyError → unhandled 500 instead of clean 422 on malformed proposal payload (Pitfall 3 above) | Tampering / Information Disclosure (stack trace leak) | Wrap the new `_execute_proposal_payload` `elif` branches' dict access in the SAME `try/except ValueError` the confirm endpoint already has (`main.py:~1113`, `except ValueError as e: raise HTTPException(422, ...)`) — a malformed/missing key should ideally be normalized to a `ValueError` inside the `apply_*` call chain rather than surfacing as a raw `KeyError`; verify each new `apply_*` primitive already raises `ValueError` (not `KeyError`) for its required-field checks, matching the existing `Transaction {tx_id} not found during confirm`-style messages |
| New write tool exposed on external MCP surface (this phase's core risk) | Elevation of Privilege | `READ_TOOL_NAMES` snapshot mechanism (Pattern 3 / Pitfall 1) — verify via `test_mcp_no_write_tools` and `test_mcp_read_parity`'s `len(listed_names) == 15` assertion after adding the 5 new tools |
| Unbounded/negative amounts in new REST bodies (e.g. a negative `cash_amount` bypassing the primitive's `abs()` intent) | Tampering | Use `Field(..., gt=0)` on `TransferCreate.amount`, `FundedBuyCreate.cash_amount`/`quantity`/`price`, etc. in `schemas.py` — reject negative/zero at the schema boundary before the primitive's sign-normalization logic ever runs, matching `PortfolioEventCreate`'s existing `gt=0` convention |

## Sources

### Primary (HIGH confidence)
- `backend/writes.py` (full read, lines 1-410) — the 5 target `apply_*` functions, their exact signatures, docstrings, and the never-commit contract
- `backend/tools.py` (full read, lines 605-1192) — `TOOLS` dict construction, `READ_TOOL_NAMES` snapshot, all 11 existing `propose_*` functions as direct analogs
- `backend/main.py` (targeted reads, lines 58-135, 217-260, 647-672, 990-1145) — REST route conventions, `_execute_proposal_payload`, `confirm_proposal`
- `backend/query.py` (lines 1-200) — `_get_agent_workflow`, system prompt, `FunctionTool` registration
- `backend/mcp_server.py` (full read) — `build_mcp()`'s `READ_TOOL_NAMES`-only iteration, verified current
- `backend/schemas.py` (lines 1-400) — `MoneyDecimal`, existing request-model conventions
- `backend/tests/test_mcp.py` (full read) — `test_mcp_read_parity`, `test_agent_read_tools_count`, `test_mcp_no_write_tools` exact assertions
- `backend/tests/test_proposals.py` (lines 1-220) — propose→confirm integration test pattern to extend
- `backend/tests/test_write_tools.py` (lines 1277-1560) — Phase 13's own RED tests for the 5 target `apply_*` functions, confirming exact expected input shapes (e.g. `event_type="deposit"` placeholder ticker convention gap)
- `.planning/phases/13-.../13-05-SUMMARY.md`, `13-PATTERNS.md`, `13-SECURITY.md`, `13-CONTEXT.md` — Phase 13's own documented decisions and explicit hand-off note ("REST/agent/MCP registration for all new writes is explicitly Phase 14")
- `.planning/REQUIREMENTS.md`, `.planning/STATE.md` — CHAT-09 wording, roadmap rationale for the 13-before-14 ordering
- `graphify query` traversals (agent registration, MCP surface, apply_ functions, propose_ flow) — used for initial orientation before targeted file reads, per repository convention

### Secondary (MEDIUM confidence)
- None — every claim in this research was verified directly against current source in this session; no external web search was needed for a pure internal-wiring phase.

### Tertiary (LOW confidence)
- None.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependencies, all patterns read directly from current source
- Architecture: HIGH — every registration point (TOOLS dict, FunctionTool list, READ_TOOL_NAMES, _execute_proposal_payload, REST routes) was located and read in full this session
- Pitfalls: HIGH for registration-mechanics pitfalls (directly observed in source + existing tests); MEDIUM-going-on-LOW for the investment-transfer ticker-convention pitfall (genuinely undecided in the codebase, correctly flagged as an assumption/open question rather than asserted as fact)

**Research date:** 2026-07-30
**Valid until:** Effectively pinned to Phase 13's exact `writes.py` state — revalidate this research if `backend/writes.py`'s 5 target function signatures change before Phase 14 executes (unlikely; Phase 13 is `status: verified`, closed). No external time-decay risk (no third-party API/library surface in scope).
