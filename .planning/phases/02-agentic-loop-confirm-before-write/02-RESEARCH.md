# Phase 2: Agentic Loop + Confirm-Before-Write — Research

**Researched:** 2026-06-21
**Domain:** LlamaIndex multi-step agents, FastAPI SSE streaming, confirm-before-write proposal lifecycle
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**D-01:** Approve/reject happens via an inline chat card inside the existing chat/ask box
(`ui/app/page.tsx`) with Approve/Reject buttons — user never leaves the conversation.

**D-02:** Proposal card shows a before→after diff. Edits render changed fields as `old → new`;
creates show the full new row; deletes show the row being removed.

**D-03:** A single proposal can cover multiple rows (batch op). One Approve applies the whole
batch atomically, writing N `audit_log` rows. The single-use token gates the entire batch.
`proposals.payload` JSONB must represent a batch operation.

**D-04:** All of CHAT-07 ships in Phase 2 — write tools for transactions (add/edit/delete),
accounts (add/edit/delete), categories (rename/merge), and holdings (add/edit/delete). All
live in `tools.py`.

**D-05:** Holdings = row CRUD only. No `portfolio_events` writes (Phase 5).

**D-06:** Destructive writes with dependent data are blocked + explained. Agent refuses to
create the proposal; no proposal row is created. Category rename/merge is allowed (non-orphaning).

**D-07:** Chat shows synthesized answer prominently plus collapsible tool-call trace. Full
tool-call trace is always returned in API response metadata.

**D-08:** Chat shows progressive step updates while the agent works (coarse events: "calling
spending_total… → synthesizing…"). This means a streaming transport must be wired in Phase 2.
Transport choice (SSE vs WebSocket) is a research item — STATE.md recommends SSE.
Scope guard: token-by-token text streaming (QRY-03) stays deferred.

**D-09:** Proposal token TTL = ~15 minutes. Approving after expiry is a no-op.

**D-10:** Expiry is visible in the UI. Card greys out and shows "Expired — ask again." Expiry
enforced server-side on confirm.

**D-11:** Confirm token is single-use and operation-scoped. A second confirm with the same
token is rejected. Token is the separate secret `proposals.token` column, never the UUID `id`.

### Claude's Discretion

- **Agent framework:** `FunctionAgent` vs `ReActAgent` — depends on Ollama function-calling
  support. (Research resolved: FunctionAgent — see findings below.)
- **Streaming transport:** SSE vs WebSocket for progressive step updates. (Research resolved:
  SSE via `StreamingResponse` — see findings below.)
- **Agent guardrails:** max_iterations / loop protection. (Research resolved: default 20,
  recommend 10 for financial tools — see findings.)
- **Target-row disambiguation:** how agent identifies WHICH transaction an edit/delete refers
  to when vague (e.g. multiple "Starbucks" rows).
- **Refusal tone/wording** for CHAT-08.
- **Exact `proposals.payload` / `audit_log` JSONB shapes** — derive from decisions.
- **Confirm/reject API surface** beyond `POST /proposals/{id}/confirm`.

### Deferred Ideas (OUT OF SCOPE)

- Token-by-token answer streaming (QRY-03) — v2.
- Spending↔portfolio correlation queries (CHAT-03) — Phase 5.
- `portfolio_events` recording (INV-07) — Phase 5.
- Category management UI (CASH-06/07) — Phase 4.
- Write tools over MCP — out of scope all cycle.
- Period comparison (QRY-02), recurring-charge detection (QRY-01) — v2.
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CHAT-01 | Multi-step reasoning agent that plans and chains multiple tools within a single turn | FunctionAgent + AgentWorkflow in llama-index-core 0.14.22; verified below |
| CHAT-02 | Agent only invokes named tools — never emits raw SQL | System prompt + tool-only registry; FunctionAgent never emits free text when tool-calling; ReActAgent fallback also supported |
| CHAT-04 | Agent shows exact proposed change; writes nothing until user approves | Proposal model already in DB (Phase 1); write tools create proposal rows, not mutations |
| CHAT-05 | Approval is single-use and operation-scoped | `proposals.token` unique index enforced at DB level; server checks expiry + marks confirmed_at on first use |
| CHAT-06 | Every applied write recorded in audit log | `audit_log` table + ORM model already in DB (Phase 1); confirm endpoint writes N rows atomically |
| CHAT-07 | Add/edit/delete for transactions, accounts, categories, holdings via confirm flow | Write tool functions in `tools.py`; all produce proposal dicts, not mutations |
| CHAT-08 | Honest refusal when no tool maps to request | Existing `ask()` pattern extended to agent; tool-not-found path preserved in system prompt + agent early stopping |
</phase_requirements>

---

## Summary

Phase 2 replaces the single-shot `route()`/`ask()` function in `backend/query.py` with a
LlamaIndex `FunctionAgent` + `AgentWorkflow` that can chain the existing 9 read tools across
multiple steps per turn. The same infrastructure adds write tools that produce `Proposal` rows
rather than mutating data directly; a confirm endpoint then executes the write atomically with
full audit logging.

All three LLM providers in the project (Ollama `gemma4:31b-cloud`, Claude, OpenAI) expose
`FunctionCallingLLM` in their LlamaIndex wrappers AND the running Ollama model reports native
`tools` capability. This resolves the open question in STATE.md: **use `FunctionAgent`, not
`ReActAgent`**. The fallback to `ReActAgent` can be a config flag but is not the default.

Streaming is implemented with FastAPI `StreamingResponse` (`media_type="text/event-stream"`)
and the `WorkflowHandler.stream_events()` async generator exposed by LlamaIndex 0.14.22. No
new Python package is required. The Next.js catch-all proxy at
`ui/app/api/[...proxy]/route.ts` currently buffers the entire response body via
`upstream.arrayBuffer()`, which breaks SSE passthrough; the proxy route handler must be
updated to stream the response body using `ReadableStream` for the `/api/query-stream`
endpoint.

The `proposals` and `audit_log` tables were created in Phase 1 (migration 002). No new
migration is required for the core confirm-before-write loop. The Alembic pattern is
established and reusable if any field is found missing.

**Primary recommendation:** Use `FunctionAgent` (not `ReActAgent`), SSE via
`StreamingResponse`, `proposals.payload` as a batch JSONB array, and keep write tools in
`tools.py` as proposal-producers that never mutate directly.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Multi-step agent loop | API/Backend (`query.py`) | — | Agent runs server-side; LLM calls are I/O-bound async operations |
| Tool registry (read + write) | API/Backend (`tools.py`) | — | Correctness-by-construction mandate; single source of truth for MCP Phase 6 |
| SSE event stream | API/Backend (`main.py`) | Frontend Server (Next.js proxy) | Backend emits; proxy must passthrough without buffering |
| Proposal creation | API/Backend (`tools.py` write tools) | — | Write tools produce proposal rows; never mutate data directly |
| Proposal confirm/reject | API/Backend (`main.py` confirm endpoint) | — | Server-side: token validation, expiry check, atomic write + audit |
| Proposal card UI | Browser/Client (`ui/app/page.tsx`) | — | Inline card rendered client-side; reads proposal from SSE response metadata |
| Step progress updates | Browser/Client | Frontend Server (proxy passthrough) | Coarse events rendered as SSE arrives |
| Audit log writes | API/Backend (confirm endpoint) | — | All writes must be audited server-side; never delegated to client |

---

## Standard Stack

### Core (all already in requirements.txt — NO new packages)

| Library | Installed Version | Purpose | Why Standard |
|---------|------------------|---------|--------------|
| `llama-index-core` | 0.14.22 [VERIFIED: uv run] | `FunctionAgent`, `AgentWorkflow`, `FunctionTool`, `WorkflowHandler.stream_events()` | Already in project; provides all agent primitives |
| `llama-index-llms-ollama` | 0.10.1 [VERIFIED: uv run] | Ollama LLM wrapper — confirmed `FunctionCallingLLM` subclass | Already in project; `gemma4:31b-cloud` reports `tools` capability |
| `llama-index-llms-anthropic` | 0.11.6 [VERIFIED: uv run] | Claude LLM wrapper — confirmed `FunctionCallingLLM` subclass | Already in project |
| `llama-index-llms-openai` | 0.7.9 [VERIFIED: uv run] | OpenAI LLM wrapper — confirmed `FunctionCallingLLM` subclass | Already in project |
| `fastapi` | 0.138.0 [VERIFIED: uv run] | `StreamingResponse` for SSE; `async def` endpoint | Already in project |
| `sqlalchemy` | 2.0.51 [VERIFIED: uv run] | ORM; `Proposal`, `AuditLog`, `Transaction`, `Account`, `Holding` models | Already in project |
| `alembic` | 1.18.4 [VERIFIED: uv run] | Migrations if any schema tweak needed | Already in project; pattern established in Phase 1 |
| `pytest-asyncio` | 1.4.0 [VERIFIED: uv run] | Async test support for `async def` endpoints and agents | Already installed (transitive dep) |
| `httpx` | 0.28.1 [VERIFIED: uv run] | `AsyncClient` for testing async endpoints | Already in requirements.txt |

### No New Python Packages Required

All functionality is achievable with the existing dependency set:
- SSE: `fastapi.responses.StreamingResponse` (built into Starlette)
- Proposal token: `secrets.token_urlsafe(32)` (stdlib)
- UUID: `uuid.uuid4()` (stdlib)
- Expiry: `datetime.now(timezone.utc) + timedelta(minutes=15)` (stdlib)

### New Frontend Dependencies

The inline proposal card and SSE consumption require no new npm packages — the existing
React 18 / Next.js 14 can handle `EventSource` and component state natively.

**No installation command needed — all dependencies already present.**

---

## Package Legitimacy Audit

No new packages are being installed in this phase. All packages referenced are existing
project dependencies already verified during Phase 1 installation.

| Package | Registry | Disposition |
|---------|----------|-------------|
| `llama-index-core` | PyPI | Approved (Phase 1 verified) |
| `fastapi` | PyPI | Approved (Phase 1 verified) |
| `sqlalchemy` | PyPI | Approved (Phase 1 verified) |
| `pytest-asyncio` | PyPI | Approved (already installed as transitive dep) |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

*slopcheck was unavailable at research time — all packages above are pre-existing project
dependencies installed and running in Phase 1, not newly introduced by this phase.*

---

## Architecture Patterns

### System Architecture Diagram

```
User question
    │
    ▼
POST /api/query-stream  (Next.js proxy → FastAPI, streaming passthrough)
    │
    ▼
async def query_stream()   [backend/main.py]
    │   Returns StreamingResponse (text/event-stream)
    │
    ▼
AgentWorkflow.run(user_msg)  ─────────────────────────────────────┐
    │                                                              │
    ▼                                                              │
WorkflowHandler.stream_events()  ← async generator                │
    │                                                              │
    ├─ AgentInput event ──► SSE: data: {"type":"step","msg":"…"}   │
    │                                                              │
    ├─ ToolCall event ────► SSE: data: {"type":"tool_call","tool":…│
    │       │                                                      │
    │       ▼                                                      │
    │  FunctionTool.call()   [tools.py]                            │
    │       │                                                      │
    │  ┌────┴─────────────────────┐                               │
    │  │ READ tool?               │ WRITE tool?                   │
    │  │ → executes SQL           │ → creates Proposal row        │
    │  │ → returns dict result    │ → returns {proposal_id, diff} │
    │  └──────────────────────────┘                               │
    │                                                              │
    ├─ ToolCallResult event ► SSE: data: {"type":"tool_result",…}  │
    │                                                              │
    ▼                                                              │
AgentWorkflow decides: more steps? ──► repeat loop ───────────────┘
    │ done
    ▼
Final AgentOutput  ──► SSE: data: {"type":"answer","text":…,"trace":[…],"proposal_id":…}
    │                      data: [DONE]
    ▼
Browser EventSource
    │
    ├─ Step events: update "thinking…" indicator
    ├─ Answer event: render final answer text
    └─ proposal_id present? → render ProposalCard component
            │
            ▼
        [Approve]  [Reject]
            │
            ▼
POST /api/proposals/{id}/confirm   (requires MONAI_API_KEY)
            │
            ▼
async def confirm_proposal()   [backend/main.py]
    │  1. Load Proposal by id
    │  2. Check status == "pending"
    │  3. Check expires_at > now()  
    │  4. hmac.compare_digest(token, proposal.token)
    │  5. BEGIN transaction
    │     a. Execute all ops in payload atomically
    │     b. Write N AuditLog rows (before/after)
    │     c. Update proposal.status = "confirmed", confirmed_at = now()
    │  6. COMMIT
    │  7. reset_engine() — invalidate LLM cache
    │
    ▼
ProposalOut (confirmed)  ──► UI marks card as applied
```

### Recommended Project Structure Changes

```
backend/
├── query.py          # REPLACE ask()/route() with agent() + streaming async generator
├── tools.py          # ADD write tools (produce proposals); existing read tools unchanged
├── main.py           # ADD async /query-stream endpoint (SSE); ADD /proposals/{id}/confirm
│                     # ADD GET /proposals?status=pending
├── schemas.py        # ADD ProposalOut, ConfirmRequest, AgentStepEvent, AgentAnswerEvent
├── models.py         # No changes (Proposal + AuditLog already there from Phase 1)
└── tests/
    ├── test_agent.py     # NEW: multi-step chaining, tool trace, honest refusal
    ├── test_proposals.py # NEW: proposal lifecycle (create, confirm, reject, expire, replay)
    └── test_write_tools.py # NEW: write tool proposal generation, orphan-delete blocking

ui/app/
├── page.tsx              # ADD ProposalCard component, SSE EventSource consumer, step indicator
└── api/[...proxy]/route.ts  # PATCH: stream SSE passthrough for /query-stream
```

### Pattern 1: FunctionAgent with FunctionTool wrapping existing tools

**What:** Wrap each `tools.py` function as a `FunctionTool`; assemble into `FunctionAgent` +
`AgentWorkflow`. The agent chains tools automatically based on the question.

**When to use:** This is THE pattern for Phase 2. All 9 read tools + write tools become
`FunctionTool` instances.

```python
# Source: verified against llama-index-core 0.14.22 source + constructor inspection
from llama_index.core.agent import AgentWorkflow, FunctionAgent
from llama_index.core.tools import FunctionTool
from llama_index.llms.ollama import Ollama
from backend.tools import spending_total, income_total, net_total  # etc.
from backend.config import configure_llm
from llama_index.core import Settings

def _build_agent() -> AgentWorkflow:
    configure_llm()
    llm = Settings.llm

    read_tools = [
        FunctionTool.from_defaults(fn=spending_total),
        FunctionTool.from_defaults(fn=income_total),
        FunctionTool.from_defaults(fn=net_total),
        # ... all 9 read tools
    ]
    write_tools = [
        FunctionTool.from_defaults(fn=propose_add_transaction),
        FunctionTool.from_defaults(fn=propose_edit_transaction),
        # ... all write proposal tools
    ]

    agent = FunctionAgent(
        tools=read_tools + write_tools,
        llm=llm,
        system_prompt=_SYSTEM_PROMPT,  # see Pattern 3
        verbose=False,
    )
    return AgentWorkflow(agents=[agent], timeout=120.0)
```

**Key insight:** `FunctionTool.from_defaults(fn=fn)` uses the function's docstring for the
tool description and its type annotations for the schema. The existing `tools.py` functions
have good docstrings — they will produce correct tool specs automatically.

### Pattern 2: SSE streaming with WorkflowHandler.stream_events()

**What:** Run the agent asynchronously and stream coarse events to the browser via SSE.

**When to use:** Any request to `POST /query-stream`.

```python
# Source: verified against llama_index.core.workflow.handler.WorkflowHandler source
# and llama_index.core.agent.workflow.workflow_events source
import json
import asyncio
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from llama_index.core.agent.workflow.workflow_events import (
    ToolCallResult, AgentInput, AgentStream
)
from llama_index.core.workflow.events import StopEvent

async def _stream_agent(question: str):
    """Async generator yielding SSE-formatted lines."""
    handler = _agent_workflow.run(user_msg=question, max_iterations=10)
    tool_trace = []

    async for event in handler.stream_events():
        if isinstance(event, AgentInput):
            yield f"data: {json.dumps({'type': 'step', 'msg': 'thinking…'})}\n\n"

        elif isinstance(event, ToolCallResult):
            step = {
                "tool": event.tool_name,
                "args": event.tool_kwargs,
                "result": event.tool_output.content,
            }
            tool_trace.append(step)
            yield f"data: {json.dumps({'type': 'tool_result', 'step': step})}\n\n"

        elif isinstance(event, StopEvent):
            # Final answer is in the StopEvent result (AgentOutput)
            final: AgentOutput = event.result
            answer_text = str(final)  # AgentOutput.__str__ returns response.content
            # Extract proposal_id if a write tool was called
            proposal_id = _extract_proposal_id(tool_trace)
            payload = {
                "type": "answer",
                "text": answer_text,
                "trace": tool_trace,
                "proposal_id": proposal_id,
            }
            yield f"data: {json.dumps(payload)}\n\n"

    yield "data: [DONE]\n\n"


@app.post("/query-stream")  # no require_api_key — reads are public (D-06)
async def query_stream(req: QueryRequest):
    return StreamingResponse(
        _stream_agent(req.question),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

**Critical:** `AgentWorkflow.run()` returns a `WorkflowHandler` synchronously; the async
work starts when you iterate `stream_events()`. The `StreamingResponse` must wrap the async
generator directly. Do NOT `await` the handler before returning the response.

### Pattern 3: System prompt for tool-only, no-SQL, honest-refusal behavior

**What:** The system prompt is the primary guardrail for CHAT-02 (no raw SQL) and CHAT-08
(honest refusal).

```python
# Source: [ASSUMED] — derived from existing query.py _PROMPT pattern + CONTEXT.md constraints
import datetime

_SYSTEM_PROMPT = f"""
You are a personal finance assistant with access to parameterized query tools.

TODAY is {{today}}.

RULES:
1. You MUST only answer using the available tools. Never emit SQL.
2. If a question cannot be answered by any available tool, say honestly:
   "I can't compute that reliably with my current tools — I can [list what you can do]."
3. For write requests (add/edit/delete), use the propose_* tools.
   These create a proposal for the user to approve — they do NOT change any data.
4. For deletes of accounts or categories with dependent data, refuse and explain:
   "I can't delete [entity] because it has [N] dependent records. Please reassign them first."
5. For batch operations ("recategorize all X"), create a SINGLE batch proposal.
6. Never fabricate a number. If a tool returns zero, say zero.
""".strip()
```

### Pattern 4: Write tool as proposal-producer (never mutates directly)

**What:** Write tools in `tools.py` create `Proposal` rows and return the proposal metadata.
The agent includes `proposal_id` in its final answer; the UI renders the confirmation card.

```python
# Source: [ASSUMED] — derived from models.py Proposal schema + CONTEXT.md decisions
import secrets, uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from backend.models import Proposal
from backend.db import get_session_sync  # sync version for tool use

def propose_edit_transaction(
    transaction_id: int,
    category: str | None = None,
    merchant: str | None = None,
    amount: float | None = None,
    notes: str | None = None,
) -> dict:
    """
    Propose editing a transaction. Returns a proposal for user confirmation.
    Does NOT change any data — user must approve the proposal.
    Provide only the fields to change.
    """
    # 1. Look up current row (read-only)
    with get_session_sync() as db:
        tx = db.get(Transaction, transaction_id)
        if tx is None:
            return {"tool": "propose_edit_transaction", "error": f"Transaction {transaction_id} not found"}
        before = _tx_to_dict(tx)

    # 2. Compute after state
    after = {**before}
    if category is not None: after["category"] = category
    if merchant is not None: after["merchant"] = merchant
    if amount is not None: after["amount"] = str(amount)
    if notes is not None: after["notes"] = notes

    # 3. Build batch payload (D-03: even single-row ops use batch format)
    payload = {
        "operation": "edit_transaction",
        "rows": [{"id": transaction_id, "before": before, "after": after}],
    }

    # 4. Create proposal row
    token = secrets.token_urlsafe(32)
    with get_session_sync() as db:
        proposal = Proposal(
            token=token,
            operation="edit_transaction",
            payload=payload,
            status="pending",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        )
        db.add(proposal)
        db.commit()
        db.refresh(proposal)
        proposal_id = str(proposal.id)

    return {
        "tool": "propose_edit_transaction",
        "proposal_id": proposal_id,
        "summary": f"Edit transaction #{transaction_id}: {_diff_summary(before, after)}",
        "before": before,
        "after": after,
    }
```

**Key:** The agent receives the proposal dict as the tool result, includes `proposal_id` in
its synthesized answer, and the SSE response carries `proposal_id` for the UI to render the
card.

### Pattern 5: Confirm endpoint — atomic write + audit + token invalidation

```python
# Source: [ASSUMED] — derived from models.py schema + CONTEXT.md D-09/D-11
from fastapi import HTTPException
from sqlalchemy.orm import Session
import hmac

@app.post("/proposals/{proposal_id}/confirm",
          response_model=ProposalOut,
          dependencies=[Depends(require_api_key)])
async def confirm_proposal(
    proposal_id: uuid.UUID,
    req: ConfirmRequest,  # {"token": "..."}
    db: Session = Depends(get_session),
):
    proposal = db.get(Proposal, proposal_id)
    if proposal is None:
        raise HTTPException(404, "Proposal not found")
    if proposal.status != "pending":
        raise HTTPException(409, f"Proposal already {proposal.status}")
    if datetime.now(timezone.utc) > proposal.expires_at:
        raise HTTPException(410, "Proposal expired — ask again to redo this")
    if not hmac.compare_digest(req.token, proposal.token):
        raise HTTPException(401, "Invalid confirmation token")

    # Execute all ops atomically
    try:
        _execute_proposal_payload(db, proposal)  # writes all rows + N audit_log rows
        proposal.status = "confirmed"
        proposal.confirmed_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Write failed: {e}")

    from backend.query import reset_engine
    reset_engine()
    return proposal
```

### Pattern 6: Next.js proxy — SSE streaming passthrough

**What:** The current proxy buffers via `upstream.arrayBuffer()`. For SSE, the response body
must be passed through as a `ReadableStream`.

```typescript
// Source: [ASSUMED] — Next.js App Router Web Streams API
// Only the /query-stream path needs streaming; other paths keep the buffer approach

async function forwardRequest(req: NextRequest, segments: string[]): Promise<NextResponse> {
  const path = segments.join("/");
  const targetUrl = `${BACKEND}/${path}${req.nextUrl.search}`;
  const headers = new Headers(req.headers);
  headers.set("MONAI_API_KEY", API_KEY);
  headers.delete("host");

  const isStream = path === "query-stream";

  let body: ArrayBuffer | null = null;
  const method = req.method.toUpperCase();
  if (method !== "GET" && method !== "HEAD") {
    body = await req.arrayBuffer();
  }

  const upstream = await fetch(targetUrl, {
    method, headers, body: body ?? undefined, redirect: "manual",
  });

  if (isStream && upstream.body) {
    // Pass the ReadableStream directly — do NOT call .arrayBuffer()
    return new NextResponse(upstream.body, {
      status: upstream.status,
      headers: upstream.headers,
    });
  }

  // Non-streaming: original buffer path
  const responseBody = await upstream.arrayBuffer();
  return new NextResponse(responseBody, {
    status: upstream.status,
    headers: new Headers(upstream.headers),
  });
}
```

### Anti-Patterns to Avoid

- **`await handler` before streaming:** Don't `result = await workflow.run(...)` — this
  blocks until the agent finishes, losing all progress events. Always use `stream_events()`.
- **Calling `upstream.arrayBuffer()` for SSE:** Buffers the entire response; the browser
  sees no events until the agent finishes. Use `upstream.body` passthrough for SSE routes.
- **Write tool mutates directly:** ALL write operations must go through the Proposal row.
  Never call `db.commit()` inside a write tool — only inside the confirm endpoint.
- **Returning raw SQL from agent:** The system prompt + tool-only registry prevents this, but
  do NOT add a `run_sql` tool or any free-form query tool.
- **Singleton `_llm` without provider reset:** `reset_engine()` in the new `query.py` must
  also reset the agent workflow singleton, not just the LLM singleton.
- **Synchronous write tools in async agent:** `FunctionTool` can wrap sync functions; SQLAlchemy
  sync sessions work in a thread executor. But for DB writes in proposal creation, use a
  synchronous helper — do NOT use `asyncio.run()` inside a running event loop.
- **Non-timezone-aware datetime for expiry:** Always use `datetime.now(timezone.utc)`, not
  `datetime.utcnow()` (deprecated in 3.12+). Compare against `proposal.expires_at` which is
  stored with timezone.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Multi-step tool chaining | Custom loop with `route()` + result accumulator | `FunctionAgent` + `AgentWorkflow` | Handles scratchpad, max_iterations, early stopping, parallel tool calls automatically |
| Streaming event protocol | Custom websocket server | `WorkflowHandler.stream_events()` + `StreamingResponse` | LlamaIndex already emits `ToolCallResult`, `AgentInput`, `AgentStream` events; SSE wire format is 5 lines |
| Honest refusal detection | Post-hoc text parsing for "I don't know" | System prompt + `{"tool": null, "reason": "…"}` pattern | Agent's early stopping with `force` mode returns a message rather than looping; null-tool path already in `ask()` |
| Token uniqueness | Custom token table + counter | `secrets.token_urlsafe(32)` + `unique=True` DB constraint | DB constraint enforces uniqueness at insert; `hmac.compare_digest` prevents timing attacks |
| Proposal expiry enforcement | Client-side timer | Server-side `expires_at` check on confirm + client display only | Client timer is UX-only; security enforcement is always server-side |
| Batch atomic writes | N separate DB commits | Single `db.commit()` wrapping all N ops in confirm handler | DB transaction is the correct primitive; partial application would corrupt data |

---

## Runtime State Inventory

> This is not a rename/refactor/migration phase. Skip — no runtime state changes.

---

## Common Pitfalls

### Pitfall 1: FunctionAgent silently falls back to text when LLM lacks tool support

**What goes wrong:** If `is_function_calling_model=True` is set (the Ollama default) but the
actual model doesn't support tools, `FunctionAgent.take_step()` raises `ValueError: LLM must
be a FunctionCallingLLM` immediately. The confusion comes from configuring `is_function_calling_model`
via env var without testing the actual model.

**Why it happens:** `Ollama(is_function_calling_model=True)` is the constructor default.
Setting `OLLAMA_MODEL` to a model that doesn't support tools will fail at runtime, not at
import time.

**How to avoid:** Verified — `gemma4:31b-cloud` on the running Ollama instance reports
`"capabilities": ["completion", "thinking", "tools", "vision"]`. Always verify a new model's
capabilities before deploying. Add a health check that tests tool-calling on startup.

**Warning signs:** `ValueError: LLM must be a FunctionCallingLLM` in server logs.

### Pitfall 2: SSE blocked by Next.js proxy buffering

**What goes wrong:** The browser receives ALL SSE events at once after the agent finishes,
instead of progressively. The spinner never updates.

**Why it happens:** The current proxy calls `await upstream.arrayBuffer()`, which buffers the
entire response body. The browser's `EventSource` only receives the data after the stream
completes.

**How to avoid:** For the `/query-stream` path, pass `upstream.body` (a `ReadableStream`)
directly to `NextResponse`. Keep the `arrayBuffer()` path for non-streaming endpoints.

**Warning signs:** Agent appears to "hang" then all events arrive simultaneously; browser
DevTools Network tab shows the SSE response with no intermediate chunks.

### Pitfall 3: Proposal token replay after confirm

**What goes wrong:** A second `POST /proposals/{id}/confirm` with the same token succeeds,
applying the write twice (double edit, double audit row).

**Why it happens:** If the confirm handler only checks `token` validity but not `status`,
a confirmed proposal can be replayed.

**How to avoid:** Always check `proposal.status == "pending"` BEFORE token validation. The
DB constraint (`unique=True` on token) does NOT prevent replay — it only prevents duplicate
tokens at creation. Return 409 for non-pending proposals.

**Warning signs:** `audit_log` has duplicate rows with the same `proposal.id` reference.

### Pitfall 4: Datetime timezone mismatch on expiry check

**What goes wrong:** `proposal.expires_at` is timezone-aware (stored with UTC tz);
`datetime.utcnow()` is timezone-naive. Comparing them raises `TypeError: can't compare
offset-naive and offset-aware datetimes`.

**Why it happens:** Python's `datetime.utcnow()` returns naive datetime. SQLAlchemy with
`DateTime(timezone=True)` returns timezone-aware datetime from PostgreSQL.

**How to avoid:** Always use `datetime.now(timezone.utc)` for the comparison. The models.py
already uses `DateTime(timezone=True)` — match it.

**Warning signs:** `TypeError` in confirm endpoint; or worse, silent expiry bypass if
timezone is stripped somewhere.

### Pitfall 5: Write tool uses `db.commit()` directly (bypasses proposal flow)

**What goes wrong:** A write tool that calls `db.commit()` inside the agent loop applies the
change before the user confirms, violating CHAT-04/CHAT-05.

**Why it happens:** Copy-paste from read tool pattern; forgetting the two-phase write
requirement.

**How to avoid:** All write tools ONLY create `Proposal` rows. The word "propose_" in the
function name enforces this convention. Code review gate: grep for `db.commit()` in any
function starting with `propose_` — there should be none except the proposal row creation
itself.

**Warning signs:** Data changes appear immediately without user seeing a confirm card.

### Pitfall 6: Agent loops beyond useful depth

**What goes wrong:** Agent makes 15+ tool calls on a simple question, hitting the 20-iteration
limit and returning "Max iterations reached" instead of an answer.

**Why it happens:** Financial questions can require many lookups if the agent explores
exhaustively. The default `DEFAULT_MAX_ITERATIONS = 20` is generous.

**How to avoid:** Set `max_iterations=10` in `workflow.run()` for financial Q&A. Add a system
prompt instruction: "Be concise — use the minimum number of tool calls to answer." For batch
write proposals (e.g. recategorize 200 rows), the agent should call `list_categories()` once
to confirm the category exists, then call `propose_batch_recategorize()` once — 2 steps, not
200.

**Warning signs:** Slow responses; `"Max iterations of N reached"` in logs.

### Pitfall 7: proposal_id extraction from tool trace is fragile

**What goes wrong:** The SSE response's `proposal_id` field is None even when a write was
proposed, because the extraction logic missed the proposal dict in the tool result.

**Why it happens:** `ToolCallResult.tool_output.content` is a string (JSON representation of
the dict). Parsing it requires `json.loads()`, which can fail if the tool returned an error.

**How to avoid:** Write tools always return a dict with a top-level `"proposal_id"` key.
The SSE event handler does `json.loads(tool_output.content)` and looks for `"proposal_id"`.
Wrap in try/except — if parsing fails, `proposal_id` stays None.

---

## Code Examples

### Complete async SSE generator for FastAPI

```python
# Source: verified pattern from WorkflowHandler.stream_events() source inspection
# in llama-index-core 0.14.22
import json
from llama_index.core.agent.workflow.workflow_events import (
    ToolCallResult, AgentInput
)
from llama_index.core.workflow import StopEvent

async def _stream_agent_response(question: str):
    handler = _get_agent_workflow().run(
        user_msg=question,
        max_iterations=10,
    )
    tool_trace = []

    async for event in handler.stream_events():
        if isinstance(event, AgentInput):
            yield f"data: {json.dumps({'type': 'step', 'msg': 'thinking…'})}\n\n"

        elif isinstance(event, ToolCallResult):
            content = event.tool_output.content
            try:
                result_dict = json.loads(content)
            except Exception:
                result_dict = {"raw": content}
            step = {
                "tool": event.tool_name,
                "args": event.tool_kwargs,
                "result": result_dict,
            }
            tool_trace.append(step)
            yield f"data: {json.dumps({'type': 'tool_result', 'step': step})}\n\n"

        elif isinstance(event, StopEvent):
            final = event.result
            answer = str(final)  # AgentOutput.__str__ returns response.content
            proposal_id = next(
                (s["result"].get("proposal_id")
                 for s in tool_trace
                 if isinstance(s["result"], dict) and "proposal_id" in s["result"]),
                None
            )
            yield f"data: {json.dumps({'type': 'answer', 'text': answer, 'trace': tool_trace, 'proposal_id': proposal_id})}\n\n"

    yield "data: [DONE]\n\n"
```

### FunctionTool wrapping existing read tool

```python
# Source: verified against FunctionTool.from_defaults signature in llama-index-core 0.14.22
from llama_index.core.tools import FunctionTool
from backend.tools import spending_total

# FunctionTool.from_defaults uses the function docstring as description
# and type annotations as schema — existing tools.py functions are ready as-is
spending_tool = FunctionTool.from_defaults(fn=spending_total)
# Result: tool name = "spending_total", schema derived from (period, start_date, end_date) sig
```

### Proposal payload JSONB shape (batch format, D-03)

```python
# Source: [ASSUMED] — derived from CONTEXT.md D-03 decisions + models.py Proposal schema

# Single-row edit (still uses batch wrapper for consistency with D-03)
payload = {
    "operation": "edit_transaction",
    "rows": [
        {
            "id": 1234,
            "before": {"category": "Shopping", "amount": "-50000", "merchant": "Tokopedia"},
            "after":  {"category": "Electronics", "amount": "-50000", "merchant": "Tokopedia"},
        }
    ]
}

# Multi-row batch (e.g. recategorize all Gojek → Transport)
payload = {
    "operation": "edit_transaction",
    "rows": [
        {"id": 101, "before": {"category": "Other"}, "after": {"category": "Transport"}},
        {"id": 102, "before": {"category": "Other"}, "after": {"category": "Transport"}},
        # ... N rows
    ]
}

# Category rename (remaps transactions, not an orphaning delete)
payload = {
    "operation": "rename_category",
    "rows": [
        {
            "old_name": "Food & Drink",
            "new_name": "Food & Drinks",
            "affected_count": 347,
        }
    ]
}
```

### Browser EventSource consumer (React)

```typescript
// Source: [ASSUMED] — Web EventSource API + React hooks pattern
function useAgentStream(question: string | null) {
  const [steps, setSteps] = useState<string[]>([]);
  const [answer, setAnswer] = useState<string | null>(null);
  const [trace, setTrace] = useState<any[]>([]);
  const [proposalId, setProposalId] = useState<string | null>(null);

  useEffect(() => {
    if (!question) return;
    // SSE is POST-based here — use fetch + ReadableStream, not EventSource
    // (EventSource only supports GET)
    let cancelled = false;
    (async () => {
      const resp = await fetch("/api/query-stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });
      const reader = resp.body!.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      while (!cancelled) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n\n");
        buf = lines.pop()!;
        for (const line of lines) {
          const data = line.replace(/^data: /, "").trim();
          if (data === "[DONE]") return;
          const msg = JSON.parse(data);
          if (msg.type === "step") setSteps(s => [...s, msg.msg]);
          if (msg.type === "tool_result") setTrace(t => [...t, msg.step]);
          if (msg.type === "answer") {
            setAnswer(msg.text);
            setTrace(msg.trace);
            if (msg.proposal_id) setProposalId(msg.proposal_id);
          }
        }
      }
    })();
    return () => { cancelled = true; };
  }, [question]);

  return { steps, answer, trace, proposalId };
}
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `route()` single-shot JSON → tool | `FunctionAgent` multi-step tool chaining | llama-index-core 0.10+ | Agent can call 2-10 tools per question, synthesize answer |
| `ReActAgent` (text-based tool calling) | `FunctionAgent` (native function calling) | When LLM providers added tool-calling APIs | More reliable, structured args, no text parsing |
| LlamaIndex `QueryEngine` + index | `FunctionAgent` + `FunctionTool` registry | llama-index-core 0.10 (workflow system) | No index needed for structured SQL tools |
| `AgentRunner` (older API) | `AgentWorkflow` + `WorkflowHandler` | llama-index-core ~0.12 | Event streaming via `stream_events()`, composable multi-agent |

**Deprecated/outdated:**
- `llama_index.core.agent.AgentRunner`: older API, replaced by `AgentWorkflow` in 0.10+.
  Still present in the codebase? No — `query.py` uses `llm.complete()` directly, not
  `AgentRunner`. No migration needed.
- `llm.predict()` single-shot: the current `query.py` approach. Being replaced by agent loop.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | System prompt wording for CHAT-08 honest refusal | Pattern 3 | Agent may not refuse correctly; test with "run a SQL query" probe |
| A2 | `proposals.payload` JSONB shape (batch array format) | Pattern 4 + Code Examples | Confirm executor would need to be updated; schema change is backwards-compatible |
| A3 | Write tool signatures (function names, param names) | Pattern 4 | Affects tool descriptions the agent sees; can be tuned without schema changes |
| A4 | Next.js proxy SSE passthrough using `upstream.body` ReadableStream | Pattern 6 | May need `export const dynamic = "force-dynamic"` directive; testable locally |
| A5 | `get_session_sync()` helper exists for sync write tool DB access | Pattern 4 | May need to add a sync session factory; current `get_session()` is FastAPI dependency, not standalone |
| A6 | `_get_agent_workflow()` singleton reset also clears FunctionAgent | Pitfall 6 | If agent caches LLM state, `reset_engine()` may need to rebuild the full workflow |

---

## Open Questions

1. **DB session access in write tools (sync context)**
   - What we know: `backend/db.py` has `get_session()` as a FastAPI dependency (yields
     `Session`); `tools.py` uses `engine.connect()` for read queries (sync, not a session).
   - What's unclear: Write tools need to INSERT a `Proposal` row. Should they use
     `engine.begin()` (connection-level, already in use) or a `sessionmaker` Session (ORM-level,
     needed for `db.add(proposal)`)?
   - Recommendation: Add a `get_session_sync()` context manager in `db.py` using
     `sessionmaker(engine)()` for use inside write tools.

2. **Target-row disambiguation for vague edit/delete requests**
   - What we know: User says "fix my Starbucks transaction" — there may be 12 Starbucks rows.
   - What's unclear: Should the agent (a) call `largest_transactions` / `list_categories` to
     find candidates and ask the user to pick, (b) pick the most recent one, or (c) propose
     editing all matching rows as a batch?
   - Recommendation: Agent should call a `find_transactions(merchant, category, period, limit)`
     read tool first to surface candidates, then ask the user to confirm which one if multiple
     match. Add `find_transactions` as a new read tool. Planner should include this.

3. **GET /proposals endpoint for pending proposals on page load**
   - What we know: CONTEXT.md mentions "a GET /proposals?status=pending for the card".
   - What's unclear: Should this be authenticated (read-only public) or require API key?
   - Recommendation: Public read (no API key) — exposes proposal metadata (diff) but no
     secret token. Token is never returned in GET responses. Proposal ID is safe to expose
     (UUID is non-guessable and has no security function itself).

4. **Reject endpoint**
   - What we know: D-11 says a second confirm is rejected (409). D-10 says expired proposals
     show "Expired" in UI.
   - What's unclear: Is there an explicit `POST /proposals/{id}/reject` endpoint, or does the
     UI simply not call confirm (the proposal expires naturally)?
   - Recommendation: Add `POST /proposals/{id}/reject` (requires API key) that sets
     `status = "rejected"`. Cleaner than relying on TTL; allows immediate cleanup. Returns
     `ProposalOut`.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| PostgreSQL | Proposal + AuditLog writes | ✓ | 16 (Docker) + port 5434 accepting | — |
| Ollama | Default LLM provider | ✓ | 0.21.0 at localhost:11434 | Claude or OpenAI via LLM_PROVIDER |
| `gemma4:31b-cloud` | FunctionAgent tool-calling | ✓ | Installed, `tools` capability confirmed | Set `is_function_calling_model=False` → ReActAgent |
| Docker | Full stack | ✓ | 29.3.1 | Run services directly |
| `pytest-asyncio` | Async endpoint tests | ✓ | 1.4.0 (already installed) | — |
| `httpx.AsyncClient` | Async test client | ✓ | 0.28.1 (already installed) | — |

**Missing dependencies with no fallback:** none

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.1.0 + pytest-asyncio 1.4.0 |
| Config file | none — needs `pytest.ini` or `pyproject.toml [tool.pytest.ini_options]` with `asyncio_mode = "auto"` |
| Quick run command | `uv run --with-requirements backend/requirements.txt pytest backend/tests/ -x -q` |
| Full suite command | `uv run --with-requirements backend/requirements.txt pytest backend/tests/ -v` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|--------------|
| CHAT-01 | Agent chains 2+ tools in one turn | unit (mock LLM) | `pytest backend/tests/test_agent.py::test_multi_step_chain -x` | ❌ Wave 0 |
| CHAT-02 | Agent refuses to emit raw SQL | unit (mock LLM) | `pytest backend/tests/test_agent.py::test_no_sql_emission -x` | ❌ Wave 0 |
| CHAT-04 | Write tool creates proposal, no DB mutation | unit | `pytest backend/tests/test_write_tools.py::test_propose_creates_row -x` | ❌ Wave 0 |
| CHAT-05 | Second confirm with same token → 409 | integration | `pytest backend/tests/test_proposals.py::test_token_single_use -x` | ❌ Wave 0 |
| CHAT-05 | Confirm after expiry → 410 | integration | `pytest backend/tests/test_proposals.py::test_expired_proposal -x` | ❌ Wave 0 |
| CHAT-06 | Confirm writes N audit_log rows | integration | `pytest backend/tests/test_proposals.py::test_audit_on_confirm -x` | ❌ Wave 0 |
| CHAT-07 | All write tools produce proposals (add/edit/delete × 4 entities) | unit | `pytest backend/tests/test_write_tools.py -x` | ❌ Wave 0 |
| CHAT-08 | Agent returns honest refusal for unknown questions | unit (mock LLM) | `pytest backend/tests/test_agent.py::test_honest_refusal -x` | ❌ Wave 0 |
| D-06 | Orphan-delete blocked + explained | unit | `pytest backend/tests/test_write_tools.py::test_orphan_delete_blocked -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `uv run --with-requirements backend/requirements.txt pytest backend/tests/ -x -q`
- **Per wave merge:** `uv run --with-requirements backend/requirements.txt pytest backend/tests/ -v`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `backend/tests/test_agent.py` — covers CHAT-01, CHAT-02, CHAT-08 (mock LLM)
- [ ] `backend/tests/test_write_tools.py` — covers CHAT-04, CHAT-07, D-06
- [ ] `backend/tests/test_proposals.py` — covers CHAT-05, CHAT-06 (requires DB)
- [ ] `pytest.ini` or `pyproject.toml` `[tool.pytest.ini_options]` with `asyncio_mode = "auto"` — needed for async tests
- [ ] `backend/tests/conftest.py` update — add `async_client` fixture using `httpx.AsyncClient` + `ASGITransport`

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes — confirm endpoint is a write | `require_api_key` (HMAC compare) — already in project |
| V3 Session Management | no | Single-user; no session tokens beyond API key |
| V4 Access Control | yes — proposals: public read metadata, gated write | GET proposals = no key; confirm/reject = require_api_key |
| V5 Input Validation | yes — write tool parameters, confirm token | Pydantic v2 schemas on all endpoints; token is HMAC-compared |
| V6 Cryptography | yes — proposal token | `secrets.token_urlsafe(32)` (CSPRNG); `hmac.compare_digest` (constant-time); never log tokens |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Proposal replay (second confirm with valid token) | Repudiation | Check `status == "pending"` before token validation; return 409 on non-pending |
| Stale-tab attack (confirm old proposal from cached page) | Tampering | 15-minute TTL enforced server-side; 410 on expired |
| Token brute-force | Elevation of Privilege | `secrets.token_urlsafe(32)` = 256-bit entropy; 43-char token; unique DB index; HMAC compare is constant-time |
| Token logging in agent trace | Information Disclosure | Token column is NEVER returned in GET /proposals, tool traces, or SSE events. Only in the confirm response. |
| Agent emits free-form SQL | Tampering | Tool-only registry; system prompt guard; no `run_sql` tool in registry |
| Orphan cascade delete | Tampering | Write tool checks dependent row count before creating proposal; blocks at tool level |

---

## Sources

### Primary (HIGH confidence)

- `llama_index.core.agent` module — `FunctionAgent`, `ReActAgent`, `AgentWorkflow`,
  `WorkflowHandler` source code inspected directly via `inspect.getsource()` in
  llama-index-core 0.14.22 [VERIFIED: uv run]
- `llama_index.core.agent.workflow.workflow_events` — `ToolCallResult`, `ToolCall`,
  `AgentInput`, `AgentOutput`, `AgentStream` fields confirmed via `model_fields` introspection
  [VERIFIED: uv run]
- Ollama `/api/show` response — `"capabilities": ["completion", "thinking", "tools", "vision"]`
  for `gemma4:31b-cloud` [VERIFIED: curl localhost:11434]
- `backend/models.py` — `Proposal`, `AuditLog` ORM model fields confirmed [VERIFIED: codebase]
- `backend/alembic/versions/002_new_tables.py` — Phase 1 migration confirmed proposals +
  audit_log tables created [VERIFIED: codebase]
- `backend/auth.py` — `require_api_key` dependency confirmed [VERIFIED: codebase]

### Secondary (MEDIUM confidence)

- [LlamaIndex streaming docs](https://developers.llamaindex.ai/python/framework/understanding/agent/streaming/) — AgentWorkflow streaming patterns
- [LlamaIndex FunctionAgent intro](https://developers.llamaindex.ai/python/examples/agent/agent_workflow_basic/) — basic usage
- [Next.js App Router streaming guide](https://nextjs.org/docs/app/guides/streaming) — ReadableStream passthrough pattern

### Tertiary (LOW confidence — assumptions)

- Payload JSONB shape (A2): batch array format derived from CONTEXT.md D-03 + models.py; not
  from official spec. Planner should finalize.
- Next.js proxy SSE passthrough (A4): derived from Next.js Web Streams docs + source review.
  Must be tested locally.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all packages verified running in environment
- Agent framework choice (FunctionAgent): HIGH — Ollama capability confirmed via API
- SSE transport: HIGH — `WorkflowHandler.stream_events()` source verified; `StreamingResponse`
  confirmed available
- Proposal flow patterns: MEDIUM — model schema verified, execution pattern is [ASSUMED]
- Next.js SSE proxy passthrough: MEDIUM — pattern derived from docs, needs local test

**Research date:** 2026-06-21
**Valid until:** 2026-07-21 (llama-index-core 0.14.x stable; Ollama model capability confirmed)
