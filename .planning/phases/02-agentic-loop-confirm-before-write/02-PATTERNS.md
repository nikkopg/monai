# Phase 2: Agentic Loop + Confirm-Before-Write — Pattern Map

**Mapped:** 2026-06-21
**Files analyzed:** 11 new/modified files
**Analogs found:** 10 / 11

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `backend/query.py` (replace `ask`/`route`) | service | event-driven (streaming) | `backend/query.py` (current) | self — evolve in place |
| `backend/tools.py` (add write tools) | service | CRUD + request-response | `backend/tools.py` existing read tools | self — extend registry |
| `backend/main.py` (add endpoints) | controller | request-response | `backend/main.py` existing endpoints | self — extend |
| `backend/schemas.py` (add Proposal* schemas) | model/DTO | — | `backend/schemas.py` existing schemas | self — extend |
| `backend/db.py` (add `get_session_sync`) | utility | — | `backend/db.py` `get_session()` | self — extend |
| `alembic/versions/003_*.py` (if needed) | migration | — | `alembic/versions/002_new_tables.py` | exact |
| `backend/tests/conftest.py` (extend) | test | — | `backend/tests/conftest.py` (current) | self — extend |
| `backend/tests/test_agent.py` (new) | test | event-driven | `backend/tests/test_auth.py` | role-match |
| `backend/tests/test_write_tools.py` (new) | test | CRUD | `backend/tests/test_tools.py` | role-match |
| `backend/tests/test_proposals.py` (new) | test | CRUD + request-response | `backend/tests/test_auth.py` | role-match |
| `ui/app/api/[...proxy]/route.ts` (patch SSE) | middleware | streaming | self (current) | self — patch |

---

## Pattern Assignments

### `backend/query.py` — replace single-shot router with FunctionAgent loop

**Analog:** `backend/query.py` (current file — evolve in place)

**Module docstring pattern** (lines 1–11):
```python
"""
AI query layer — tool router (correct by construction).

The LLM does ONE job: read the question and emit JSON naming a tool + arguments.
It never writes SQL. The tool SQL is hand-written and tested in tools.py, and
relative dates are resolved in Python, so the model cannot get the year, the
expense/income sign, or column names wrong.

If the model can't map the question to a tool, we say so rather than fabricate
an answer — for a money app, refusing beats a confident wrong number.
"""
```
New module docstring must update this intent description to reflect multi-step agent.

**LLM singleton pattern** (lines 20, 80–86):
```python
_llm = None

def _get_llm():
    global _llm
    if _llm is None:
        configure_llm()
        from llama_index.core import Settings
        _llm = Settings.llm
    return _llm
```
New `query.py` uses the same lazy-singleton pattern but extends it to also cache the `AgentWorkflow` instance. Add `_agent_workflow = None` alongside `_llm = None`.

**`reset_engine()` pattern** (lines 152–155):
```python
def reset_engine() -> None:
    """Kept for API compatibility; the router holds no per-import state."""
    global _llm
    _llm = None
```
Extend to reset BOTH `_llm` and `_agent_workflow`:
```python
def reset_engine() -> None:
    global _llm, _agent_workflow
    _llm = None
    _agent_workflow = None
```

**Honest-refusal wording pattern** (lines 128–135 — the null-tool path):
```python
if not tool_name:
    reason = routing.get("reason", "no matching tool")
    return (
        f"I can't answer that one reliably yet ({reason}). "
        "I can total spending or income, break spending down by category, "
        "count transactions, find your largest transactions, or compute average "
        "daily spending — over any period."
    )
```
The new agent's honest-refusal response must follow the same wording style and enumerate what the agent CAN do.

**Broad-except pattern** (lines 121–125):
```python
def ask(question: str) -> str:
    try:
        routing = route(question)
    except Exception as e:
        return f"I couldn't interpret that question reliably ({e}). Try rephrasing."
```
Preserve this: the new `agent()` entry point wraps the entire agent loop in `try/except Exception` and returns a friendly string on failure — never raises to the API layer.

**Lazy import pattern** (lines 115, 108):
```python
from backend.query import ask
# ...
from backend.query import reset_engine
```
The `main.py` handlers import from `backend.query` lazily inside the handler function. New `query.py` public surface should export `agent_stream()` (async generator) and `reset_engine()`.

---

### `backend/tools.py` — extend TOOLS registry with write/propose tools

**Analog:** `backend/tools.py` existing read tools (entire file)

**Tool function signature pattern** (lines 99–109, `spending_total` as canonical example):
```python
def spending_total(period="all_time", start_date=None, end_date=None) -> dict:
    """Total money spent (expenses only, transfers excluded) in a period."""
    s, e = resolve_period(period, start_date, end_date)
    p: dict = {}
    sql = (
        "SELECT COALESCE(SUM(-amount), 0) FROM transactions "
        "WHERE amount < 0 AND is_transfer = false" + _date_clause(s, e, p)
    )
    with engine.connect() as c:
        total = float(c.execute(text(sql), p).scalar() or 0)
    return {"tool": "spending_total", "total": total, "period": _period_label(period, s, e)}
```
Write tools follow the same pattern: typed parameters, docstring, returns `dict` with `"tool"` key. The critical difference: write tools return `{"tool": "propose_*", "proposal_id": ..., "summary": ..., "before": ..., "after": ...}` instead of query results.

**Structured-dict return shape** — every read tool returns `{"tool": "<name>", ...payload}`. Write tools return:
```python
{
    "tool": "propose_edit_transaction",
    "proposal_id": "<uuid-str>",
    "summary": "Edit transaction #1234: category Other → Transport",
    "before": {...},
    "after": {...},
}
```

**TOOLS registry pattern** (lines 236–246):
```python
TOOLS = {
    "spending_total": spending_total,
    "income_total": income_total,
    # ... 7 more
}
```
Write tools are added to the same `TOOLS` dict with their `propose_*` names. The `FunctionTool.from_defaults(fn=fn)` in `query.py` iterates `TOOLS.values()` or a curated list — the registry remains the single source of truth.

**DB access pattern for read tools** (lines 107–108, 121–122, etc.):
```python
with engine.connect() as c:
    total = float(c.execute(text(sql), p).scalar() or 0)
```
Read tools use `engine.connect()` (connection-level, sync). Write tools need ORM-level session for `db.add(proposal)` + `db.commit()`. Use `SessionLocal()` from `backend.db` directly (not the FastAPI dependency):
```python
from backend.db import SessionLocal

def _get_session_sync():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```
Or use as a context manager:
```python
db = SessionLocal()
try:
    proposal = Proposal(...)
    db.add(proposal)
    db.commit()
    db.refresh(proposal)
finally:
    db.close()
```

**Error return pattern** — tools return error dict on domain failure (not raise):
```python
return {"tool": "propose_edit_transaction", "error": f"Transaction {id} not found"}
```
Mirrors the router's null-tool fallback (line 129). The agent receives the error dict as the tool result and synthesizes a user-facing message.

**Import block for write tools** (extends current lines 14–19):
```python
import secrets
import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.db import SessionLocal, engine
from backend.models import AuditLog, Holding, Proposal, Transaction, Account
```

---

### `backend/main.py` — add `/query-stream`, `/proposals/{id}/confirm`, `/proposals/{id}/reject`, `GET /proposals`

**Analog:** `backend/main.py` existing endpoints

**Import block pattern** (lines 18–35):
```python
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import desc
from sqlalchemy.orm import Session

from backend.auth import require_api_key
from backend.db import get_session
from backend.models import Account, Transaction
from backend.schemas import (
    AccountOut,
    ImportResponse,
    QueryRequest,
    QueryResponse,
    TransactionCreate,
    TransactionOut,
)
```
New endpoints add `StreamingResponse`, `uuid`, `Proposal`, and new schemas to these imports.

**Auth-gated write endpoint pattern** (lines 74–94, `POST /transactions`):
```python
@app.post("/transactions", response_model=TransactionOut, status_code=201, dependencies=[Depends(require_api_key)])
def create_transaction(payload: TransactionCreate, db: Session = Depends(get_session)):
    # ...
    db.add(tx)
    db.commit()
    db.refresh(tx)
    from backend.query import reset_engine
    reset_engine()
    return tx
```
The `POST /proposals/{id}/confirm` endpoint follows this exact pattern:
- `dependencies=[Depends(require_api_key)]`
- `db: Session = Depends(get_session)`
- Ends with `reset_engine()` after committing the write
- Returns the ORM object directly (Pydantic `from_attributes=True` handles serialization)

**Non-auth public endpoint pattern** (lines 113–120, `POST /query`):
```python
@app.post("/query", response_model=QueryResponse)
def query(req: QueryRequest):
    from backend.query import ask
    try:
        answer = ask(req.question)
    except Exception as e:
        raise HTTPException(500, f"Query failed: {e}")
    return QueryResponse(question=req.question, answer=answer)
```
The `POST /query-stream` is also public (no auth, reads only). The lazy import pattern `from backend.query import agent_stream` is used inside the handler.

**Lazy import pattern** (lines 92–93, 108–109, 115):
```python
from backend.query import reset_engine
reset_engine()
```
All `backend.query` imports happen inside handlers, never at module top level. This is load-bearing for Uvicorn reload behaviour.

**Error mapping pattern** (lines 103–107):
```python
try:
    parsed, inserted, skipped, currency = import_csv_text(db, text_content)
except ValueError as e:
    raise HTTPException(422, str(e))
```
The confirm endpoint maps domain errors: `ValueError → 422`, `404 not found → 404`, expired → `410`, wrong token → `401`, already confirmed/rejected → `409`.

**`StreamingResponse` pattern** — new, no existing analog in `main.py`. Copy from RESEARCH.md Pattern 2:
```python
from fastapi.responses import StreamingResponse

@app.post("/query-stream")
async def query_stream(req: QueryRequest):
    from backend.query import agent_stream
    return StreamingResponse(
        agent_stream(req.question),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

---

### `backend/schemas.py` — add Proposal*, Confirm*, AgentStep* schemas

**Analog:** `backend/schemas.py` (entire file)

**BaseModel pattern** (lines 23–31, `TransactionCreate`):
```python
class TransactionCreate(BaseModel):
    date: datetime
    amount: MoneyDecimal = Field(..., description="Signed: negative = expense, positive = income")
    currency: str = "IDR"
    category: str | None = None
    merchant: str | None = None
    notes: str | None = None
    account: str = Field(..., description="Account name; created if it doesn't exist")
    is_transfer: bool = False
```

**ORM-read schema pattern** (lines 34–47, `TransactionOut`):
```python
class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    date: datetime
    amount: MoneyDecimal
    # ...
```
`ProposalOut` must include `model_config = ConfigDict(from_attributes=True)` to deserialize from `Proposal` ORM model. UUID fields serialize as strings via Pydantic's default UUID handling.

**`MoneyDecimal` shared type** (lines 17–20):
```python
MoneyDecimal = Annotated[
    Decimal,
    PlainSerializer(lambda x: float(x), return_type=float, when_used="json"),
]
```
Use `MoneyDecimal` in any proposal `before`/`after` dict that contains amounts. The JSONB payload itself is `dict` typed — Pydantic passes it through as-is.

**New schemas to add** (follow the BaseModel conventions above):
```python
import uuid as _uuid

class ProposalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: _uuid.UUID
    operation: str
    payload: dict
    status: str
    expires_at: datetime
    created_at: datetime
    confirmed_at: datetime | None
    # NOTE: `token` is deliberately EXCLUDED — never returned in GET responses

class ConfirmRequest(BaseModel):
    token: str

class AgentStepEvent(BaseModel):
    type: str   # "step" | "tool_result" | "answer"
    msg: str | None = None
    step: dict | None = None
    text: str | None = None
    trace: list[dict] | None = None
    proposal_id: str | None = None
```

---

### `backend/db.py` — add `get_session_sync()` context manager

**Analog:** `backend/db.py` `get_session()` (lines 18–24)

**Existing pattern** (lines 14–24):
```python
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

def get_session():
    """FastAPI dependency — yields a session, always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```
`SessionLocal` is already defined. The new `get_session_sync()` is a plain context manager (not a generator-based FastAPI dependency) for use in synchronous write tools:

```python
from contextlib import contextmanager

@contextmanager
def get_session_sync():
    """Sync context manager — use in non-async tools (not as FastAPI dependency)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```
Write tools import `get_session_sync` from `backend.db` and use it as `with get_session_sync() as db:`.

---

### `alembic/versions/003_*.py` — only if a schema gap is found

**Analog:** `alembic/versions/002_new_tables.py` (entire file — exact pattern to copy)

**Migration file structure** (lines 1–21):
```python
"""<description>

Revision ID: <new_hash>
Revises: 7b4e9f1a6c52
Create Date: 2026-06-21

"""
from typing import Sequence, Union
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from alembic import op

revision: str = "<new_hash>"
down_revision: Union[str, None] = "7b4e9f1a6c52"  # points to 002
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
```

**`upgrade()` / `downgrade()` pattern** (lines 41–152):
```python
def upgrade() -> None:
    op.create_table(
        "table_name",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_table_name_col", "table_name", ["col"], unique=False)

def downgrade() -> None:
    op.drop_index("ix_table_name_col", "table_name")
    op.drop_table("table_name")
```
NOTE: Phase 1 already created `proposals` and `audit_log`. Research confirms no new migration is required for the core confirm loop. A 003 migration is only needed if a field is found missing (e.g., `proposal_id` FK on `audit_log` if the planner decides to add it).

---

### `backend/tests/conftest.py` — extend with async fixtures

**Analog:** `backend/tests/conftest.py` (current file)

**Existing sync fixture pattern** (lines 27–30):
```python
@pytest.fixture(scope="session")
def client() -> TestClient:
    """Return a TestClient wrapping the monai FastAPI app."""
    return TestClient(app)
```

**`api_key` patch fixture pattern** (lines 40–53):
```python
@pytest.fixture()
def api_key(monkeypatch: pytest.MonkeyPatch) -> str:
    import backend.auth as auth_mod
    monkeypatch.setattr(auth_mod, "_CONFIGURED_KEY", _TEST_API_KEY)
    return _TEST_API_KEY
```

**New async client fixture to add** (extends the file, follows `httpx.AsyncClient` + `ASGITransport`):
```python
import pytest_asyncio
import httpx
from fastapi.testclient import TestClient

@pytest_asyncio.fixture()
async def async_client():
    """httpx AsyncClient for testing async endpoints (query-stream, proposals)."""
    from backend.main import app
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
```
Also add `pytest.ini` or `pyproject.toml` entry (not a Python file, but a planner task):
```ini
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

---

### `backend/tests/test_agent.py` — new: multi-step chain, SQL refusal, honest refusal

**Analog:** `backend/tests/test_auth.py` (closest existing test file — endpoint + behavior tests)

**Test file docstring + import pattern** (test_auth.py lines 1–19):
```python
"""
Auth tests — require_api_key dependency.

Tests:
  (a) ...
"""

import pytest
```

**Test function naming and structure** (test_auth.py lines 29–32):
```python
def test_post_transactions_missing_key_returns_401(client, api_key):
    """No MONAI_API_KEY header → auth dependency raises 401."""
    resp = client.post("/transactions", json={"some": "data"})
    assert resp.status_code == 401
```
New tests follow `test_<behavior>_<expected_outcome>` naming. Agent tests mock the LLM to avoid real Ollama calls:
```python
from unittest.mock import patch, MagicMock

def test_multi_step_chain_returns_trace(client, api_key, monkeypatch):
    """Agent chains 2+ tools and returns trace in response metadata."""
    # mock agent_stream to yield canned SSE events
    ...
```

---

### `backend/tests/test_write_tools.py` — new: proposal creation, orphan-delete blocking

**Analog:** `backend/tests/test_tools.py` (read tool tests)

**Read test_tools.py first:**

The file is at `/home/nikko/nikko/projects/monai/backend/tests/test_tools.py`. Pattern needed — read it.

*(The planner should read `backend/tests/test_tools.py` before implementing `test_write_tools.py` to match its exact import and fixture style.)*

**General pattern from test_auth.py:**
```python
def test_propose_edit_creates_proposal_row(client, api_key):
    """Write tool creates Proposal row; does NOT mutate the Transaction."""
    # Call the write tool directly (not via HTTP), check DB state
    from backend.tools import propose_edit_transaction
    result = propose_edit_transaction(transaction_id=1, category="Transport")
    assert "proposal_id" in result
    assert result["tool"] == "propose_edit_transaction"
    # Verify the transaction was NOT mutated
    ...
```

---

### `backend/tests/test_proposals.py` — new: lifecycle (confirm, reject, expire, replay)

**Analog:** `backend/tests/test_auth.py` (auth + write endpoint pattern)

**Pattern for integration tests with DB writes:**
```python
def test_confirm_proposal_applies_write(client, api_key):
    """POST /proposals/{id}/confirm with valid token → 200, DB updated."""
    resp = client.post(
        f"/proposals/{proposal_id}/confirm",
        json={"token": token},
        headers={"MONAI_API_KEY": api_key},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "confirmed"

def test_confirm_proposal_second_call_returns_409(client, api_key):
    """Second confirm with same token → 409 (single-use enforcement)."""
    # first confirm...
    resp2 = client.post(f"/proposals/{proposal_id}/confirm", ...)
    assert resp2.status_code == 409
```

---

### `ui/app/api/[...proxy]/route.ts` — patch SSE passthrough

**Analog:** self (current file)

**Current buffering pattern to replace** (lines 55–63):
```typescript
// Stream response body back to the client
const responseBody = await upstream.arrayBuffer();
const responseHeaders = new Headers(upstream.headers);

return new NextResponse(responseBody, {
  status: upstream.status,
  statusText: upstream.statusText,
  headers: responseHeaders,
});
```

**New SSE-passthrough pattern** (replaces lines 55–63 in `forwardRequest`):
```typescript
const isStream = path === "query-stream";

if (isStream && upstream.body) {
  // Pass ReadableStream directly — do NOT call .arrayBuffer()
  return new NextResponse(upstream.body, {
    status: upstream.status,
    headers: upstream.headers,
  });
}

// Non-streaming: original buffer path
const responseBody = await upstream.arrayBuffer();
return new NextResponse(responseBody, {
  status: upstream.status,
  statusText: upstream.statusText,
  headers: new Headers(upstream.headers),
});
```
The `isStream` check must be computed BEFORE `upstream.arrayBuffer()` is called, since calling it on a stream consumes it. Add `const isStream = path === "query-stream";` immediately after `const path = segments.join("/");` (line 29).

---

### `ui/app/page.tsx` — add ProposalCard, SSE consumer, step indicator

**Analog:** `ui/app/page.tsx` (current file — extend in place)

**State and async fetch pattern** (lines 45–88):
```typescript
const [question, setQuestion] = useState("");
const [answer, setAnswer] = useState("");
const [asking, setAsking] = useState(false);

async function ask() {
  if (!question.trim()) return;
  setAsking(true);
  setAnswer("");
  try {
    const r = await fetch("/api/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    const d = await r.json();
    setAnswer(r.ok ? d.answer : `Error: ${d.detail || r.statusText}`);
  } catch (e: any) {
    setAnswer(`Error: ${e.message}`);
  } finally {
    setAsking(false);
  }
}
```
New `ask()` replaces the `fetch("/api/query")` call with a streaming `fetch("/api/query-stream")` + `ReadableStream` reader. Add `steps`, `trace`, `proposalId` to state alongside `answer`.

**Inline CSS object pattern** (lines 14–41):
```typescript
const card: React.CSSProperties = {
  background: "#1a1d23",
  border: "1px solid #2a2e37",
  borderRadius: 12,
  padding: 20,
  marginBottom: 20,
};
const btn: React.CSSProperties = {
  background: "#3b82f6",
  color: "white",
  border: "none",
  borderRadius: 8,
  padding: "10px 18px",
  fontSize: 14,
  cursor: "pointer",
  fontWeight: 600,
};
```
New `ProposalCard` component and step-indicator elements must follow the same inline `React.CSSProperties` object style — no external CSS classes, no CSS modules. Dark-mode palette: `#1a1d23` background, `#2a2e37` border, `#9aa0a6` muted text, `#3b82f6` primary button, `#f87171` destructive (reject), `#4ade80` success.

**`Tx` type pattern** (lines 4–11):
```typescript
type Tx = {
  id: number;
  date: string;
  amount: number;
  category: string | null;
  merchant: string | null;
  is_transfer: boolean;
};
```
Add `Proposal` type alongside:
```typescript
type Proposal = {
  id: string;           // UUID
  operation: string;
  payload: { operation: string; rows: any[] };
  status: "pending" | "confirmed" | "rejected";
  expires_at: string;
  created_at: string;
};
```

---

## Shared Patterns

### Authentication guard
**Source:** `backend/auth.py` (entire file, lines 1–49)
**Apply to:** `POST /proposals/{id}/confirm`, `POST /proposals/{id}/reject`
```python
from backend.auth import require_api_key
# On write endpoints:
@app.post("/proposals/{proposal_id}/confirm",
          response_model=ProposalOut,
          dependencies=[Depends(require_api_key)])
async def confirm_proposal(proposal_id: uuid.UUID, req: ConfirmRequest, db: Session = Depends(get_session)):
    ...
```
The `hmac.compare_digest` pattern from `auth.py` (line 47) is reused in the confirm endpoint for the proposal token validation:
```python
if not hmac.compare_digest(req.token, proposal.token):
    raise HTTPException(status_code=401, detail="Invalid confirmation token")
```

### Error mapping (ValueError → 422, generic → 500)
**Source:** `backend/main.py` lines 103–107
**Apply to:** confirm endpoint, reject endpoint, all new write endpoints
```python
try:
    ...
except ValueError as e:
    raise HTTPException(422, str(e))
except Exception as e:
    raise HTTPException(500, f"Operation failed: {e}")
```

### Lazy import inside handlers
**Source:** `backend/main.py` lines 92–93, 108–109, 115
**Apply to:** all new `main.py` handlers
```python
from backend.query import reset_engine
reset_engine()
```
and:
```python
from backend.query import agent_stream
```
Never import at module top level.

### Per-request DB session via dependency
**Source:** `backend/main.py` lines 60, 64, 75, 98
**Apply to:** all new endpoints that touch DB
```python
db: Session = Depends(get_session)
```

### Parameterized SQL — never raw string interpolation
**Source:** `backend/tools.py` (entire file)
**Apply to:** any new SQL in tools.py
```python
from sqlalchemy import text
sql = "SELECT id FROM transactions WHERE merchant ILIKE :merchant"
params = {"merchant": f"%{merchant}%"}
with engine.connect() as c:
    rows = c.execute(text(sql), params).fetchall()
```
Parameterized SQL is the single most important constraint. No f-strings inside SQL strings. No `% formatting` in SQL.

### Structured dict tool return
**Source:** `backend/tools.py` lines 109, 122, 135, etc.
**Apply to:** all write tools (propose_* functions)
```python
return {"tool": "propose_edit_transaction", "proposal_id": str(proposal.id), ...}
```
The `"tool"` key is always first and matches the function name.

### `MoneyDecimal` for amounts
**Source:** `backend/schemas.py` lines 17–20
**Apply to:** all new Pydantic schemas that contain `amount`, `price`, `quantity`, or `avg_cost`
```python
from backend.schemas import MoneyDecimal
```

### `DateTime(timezone=True)` for all datetimes
**Source:** `backend/models.py` lines 90–91, 115–117
**Apply to:** any new `DateTime` columns in migrations or models
```python
sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)
```
Always use `datetime.now(timezone.utc)` — not `datetime.utcnow()` — for Python-side datetime values to avoid timezone mismatch.

### Test fixture reuse
**Source:** `backend/tests/conftest.py` lines 27–53
**Apply to:** all new test files
```python
def test_something(client, api_key):
    # client — sync TestClient, session-scoped
    # api_key — patches _CONFIGURED_KEY, function-scoped
```

---

## No Analog Found

| File | Role | Data Flow | Reason |
|---|---|---|---|
| `backend/query.py` SSE async generator (`agent_stream`) | service | event-driven (streaming) | No existing streaming endpoint in codebase; use RESEARCH.md Pattern 2 as reference |

---

## Metadata

**Analog search scope:** `backend/`, `ui/app/`, `alembic/versions/`
**Files scanned:** 15
**Pattern extraction date:** 2026-06-21
