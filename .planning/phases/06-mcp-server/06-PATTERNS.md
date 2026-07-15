# Phase 6: MCP Server - Pattern Map

**Mapped:** 2026-07-15
**Files analyzed:** 6 (2 new, 4 modified)
**Analogs found:** 6 / 6

This phase is almost entirely wiring. Every new/modified file has a strong in-repo
analog — no file needs to fall back to RESEARCH.md-only patterns.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `backend/mcp_server.py` (NEW) | service/adapter | request-response | `backend/query.py` L114-127 (registers `TOOLS` callables into an LLM tool list) | role-match |
| `backend/test_mcp.py` (NEW) | test | request-response | `backend/tests/test_write_tools.py` + `conftest.py` fixtures | role-match |
| `backend/main.py` (MODIFY) | route/config | request-response | itself — `lifespan` + `app = FastAPI(...)` + CORS middleware, L120-150 | exact (self) |
| `backend/query.py` (MODIFY) | service | request-response | itself — `read_tools` list, L114-127 | exact (self) |
| `backend/auth.py` (MODIFY) | middleware | request-response | itself — `require_api_key`, L30-51 | exact (self) |
| `backend/requirements.txt` (MODIFY) | config | — | itself (append one pinned line) | exact (self) |

## Pattern Assignments

### `backend/mcp_server.py` (NEW — service/adapter, request-response)

**Analog:** `backend/query.py` L114-127 — the existing "register every `TOOLS`
callable into a tool list" loop. MCP registration is the same shape (iterate the
registry, wrap each callable) but targets `FastMCP` instead of `FunctionTool`.

**Registry to consume** (`backend/tools.py` L493-510) — the single source of truth, already exactly 15 read tools:
```python
# Registry: name -> callable (read tools)
TOOLS = {
    "spending_total": spending_total,
    "income_total": income_total,
    "net_total": net_total,
    "spending_by_category": spending_by_category,
    "spending_in_category": spending_in_category,
    "spending_before_after_purchase": spending_before_after_purchase,
    "transaction_count": transaction_count,
    "largest_transactions": largest_transactions,
    "average_daily_spending": average_daily_spending,
    "list_categories": list_categories,
    "find_transactions": find_transactions,
    "find_platforms": find_platforms,
    "find_accounts": find_accounts,
    "monthly_trend": monthly_trend,
    "account_balances": account_balances,
}
```

**Callable shape to register** (`backend/tools.py` L476-490) — plain type-annotated
params, self-managed session, returns a JSON-serializable dict. No session injection
needed; the return dict lands directly as an MCP tool result:
```python
def find_accounts(name: str | None = None, limit: int = 10) -> dict:
    """Search/filter accounts and return their ids, names, types, and currencies..."""
    from backend.models import Account
    p: dict = {"lim": max(1, min(int(limit), 50))}
    with get_session_sync() as db:
        q = db.query(Account)
        if name is not None:
            q = q.filter(Account.name.ilike(f"%{name}%"))
        rows = [_account_to_dict(a) for a in q.order_by(Account.name).limit(p["lim"]).all()]
    return {"tool": "find_accounts", "rows": rows}
```

**PERIODS vocabulary to enumerate in descriptions** (`backend/tools.py` L30-34, D-05):
```python
PERIODS = (
    "this_week", "last_week",
    "this_month", "last_month", "this_year", "last_year",
    "last_30_days", "last_90_days", "all_time", "custom",
)
```
Descriptions MUST list these (excluding/annotating `"custom"` → ISO `start_date`/`end_date`, end inclusive). Reuse each callable's docstring as the base where it already reads well.

**Registration loop (target shape, per RESEARCH Pattern 2):**
```python
from fastmcp import FastMCP
from backend.tools import TOOLS, PERIODS

def build_mcp() -> FastMCP:
    mcp = FastMCP("monai finance (read-only)")
    for name, fn in TOOLS.items():
        mcp.tool(name=name, description=MCP_DESCRIPTIONS.get(name, fn.__doc__ or name))(fn)
    return mcp
```
> Confirm exact `mcp.tool(name=..., description=...)(fn)` kwargs against installed fastmcp 3.4.x (RESEARCH A1/Open-Q1). Only `TOOLS` is registered → the 11 `propose_*` write tools are absent from `tools/list` (D-03/MCP-03).

---

### `backend/query.py` (MODIFY — service, D-02 parity edit)

**Analog:** itself. Additive edit to the existing `read_tools` list.

**Current `read_tools`** (L114-127) — 12 tools; missing 3 that already exist in `TOOLS`:
```python
read_tools = [
    FunctionTool.from_defaults(fn=spending_total),
    FunctionTool.from_defaults(fn=income_total),
    FunctionTool.from_defaults(fn=net_total),
    FunctionTool.from_defaults(fn=spending_by_category),
    FunctionTool.from_defaults(fn=spending_in_category),
    FunctionTool.from_defaults(fn=transaction_count),
    FunctionTool.from_defaults(fn=largest_transactions),
    FunctionTool.from_defaults(fn=average_daily_spending),
    FunctionTool.from_defaults(fn=list_categories),
    FunctionTool.from_defaults(fn=find_transactions),
    FunctionTool.from_defaults(fn=find_platforms),
    FunctionTool.from_defaults(fn=find_accounts),
]
```
**Edit:** add `spending_before_after_purchase`, `monthly_trend`, `account_balances`
(also add them to the local `from backend.tools import (...)` block at L100-104) →
15 tools, matching `TOOLS` and the MCP surface. Mirror the exact `FunctionTool.from_defaults(fn=...)` line format.

---

### `backend/main.py` (MODIFY — route/config, co-mount)

**Analog:** itself. Existing `lifespan` + `app = FastAPI(...)` + CORS middleware.

**Existing lifespan and app** (L120-150) — this is why RESEARCH mandates `combine_lifespans` (do NOT replace `lifespan`):
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the in-process daily portfolio-value snapshot scheduler (D-13/D-14)."""
    from backend.scheduler import build_scheduler
    scheduler = build_scheduler()
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)

app = FastAPI(title="monai", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[...],
    allow_methods=["*"],
    allow_headers=["*"],
)
```
**Edits (RESEARCH Pattern 1 + 3):**
1. `mcp = build_mcp(); mcp_app = mcp.http_app(path="/")`
2. `lifespan=combine_lifespans(lifespan, mcp_app.lifespan)` in the `FastAPI(...)` call (Pitfall 1: never pass `mcp_app.lifespan` alone).
3. `app.mount("/mcp", mcp_app)` → endpoint is exactly `/mcp` (Pitfall 3: `http_app(path="/")` + mount `/mcp`, not `/mcp/mcp`).
4. Register the `/mcp` auth guard as **outer-app** middleware (Pitfall 4) — see Shared Patterns → Authentication.

---

### `backend/auth.py` (MODIFY — middleware, extract shared check)

**Analog:** itself. Extract the constant-time check so the `/mcp` middleware and the FastAPI dependency share one implementation (D-04 one-secret/one-check).

**Existing check to extract** (L40-51):
```python
if not _CONFIGURED_KEY:
    raise HTTPException(status_code=503, detail="Server misconfigured: MONAI_API_KEY ...")
if api_key is None or not hmac.compare_digest(api_key, _CONFIGURED_KEY):
    raise HTTPException(status_code=401, detail="Invalid or missing API key")
```
**Edit (recommended, minimal):** add `def key_ok(key: str | None) -> bool: return bool(_CONFIGURED_KEY) and key is not None and hmac.compare_digest(key, _CONFIGURED_KEY)` and call it from both `require_api_key` and the new `/mcp` middleware. Header name stays `MONAI_API_KEY` (L22). Do not log the key value.

---

### `backend/test_mcp.py` (NEW — test, request-response)

**Analog:** `backend/tests/conftest.py` fixtures (reuse verbatim — no new fixtures) + `test_auth.py`'s 401 pattern.

**Fixtures already available** (`conftest.py` L30-70):
```python
@pytest.fixture(scope="session")
def client() -> TestClient:
    return TestClient(app)

_TEST_API_KEY = "test-monai-api-key-fixture"

@pytest.fixture()
def api_key(monkeypatch: pytest.MonkeyPatch) -> str:
    import backend.auth as auth_mod
    monkeypatch.setattr(auth_mod, "_CONFIGURED_KEY", _TEST_API_KEY)
    return _TEST_API_KEY
```
`async_client` (L41-47, httpx ASGITransport) is available for streamable-HTTP MCP calls if `TestClient` proves awkward.

**Tests to write** (RESEARCH Test Map, MCP-01..04):
- `test_mcp_endpoint_mounted` — MCP handshake at `/mcp` with key → not 404 (MCP-01).
- `test_mcp_read_parity` — `tools/list` == 15 `TOOLS` names; a `tools/call` result == direct `TOOLS[name](...)` dict (MCP-02).
- `test_agent_read_tools_count` — `query.py` read_tools == 15 (MCP-02/D-02).
- `test_mcp_no_write_tools` — no `propose_*` in `tools/list`; calling one → unknown tool (MCP-03).
- `test_mcp_requires_key` — `/mcp` without `MONAI_API_KEY` header → 401 (MCP-04).

---

### `backend/requirements.txt` (MODIFY — config)

Append one pinned line: `fastmcp>=3.4,<4`. Image rebuild required after (MEMORY: deploy requires rebuild). Insert one `checkpoint:human-verify` before install (seam flagged `SUS` — false positive, see RESEARCH Package Legitimacy Audit).

## Shared Patterns

### Authentication (the load-bearing cross-cutting pattern)
**Source:** `backend/auth.py` L22, L40-51 (`_CONFIGURED_KEY`, `hmac.compare_digest`, header `MONAI_API_KEY`).
**Apply to:** `backend/main.py` `/mcp` middleware AND `backend/auth.py` dependency — via one extracted `key_ok()`/`check_key()` helper (D-04).
**Middleware shape (RESEARCH Pattern 3)** — outer-app, scoped to `/mcp`, runs before the mounted sub-app (Pitfall 4):
```python
@app.middleware("http")
async def mcp_api_key_guard(request, call_next):
    if request.url.path.startswith("/mcp"):
        if not auth._CONFIGURED_KEY:
            return JSONResponse({"detail": "MONAI_API_KEY unset"}, status_code=503)
        if not auth.key_ok(request.headers.get("MONAI_API_KEY")):
            return JSONResponse({"detail": "Invalid or missing API key"}, status_code=401)
    return await call_next(request)
```
> A2 (RESEARCH): optionally also accept `Authorization: Bearer <key>` (same secret) for client-agnostic UAT.

### Tool registry reuse (single source of truth)
**Source:** `backend/tools.py:TOOLS` L493-510 (15 read callables).
**Apply to:** `backend/mcp_server.py` (register all 15) and `backend/query.py` (wire all 15 into `read_tools`). Never fork tool logic; both surfaces consume the same callables — this is MCP-02.

### Structured-dict returns
**Source:** every `TOOLS` callable returns `{"tool": name, ...}` (e.g. `backend/tools.py` L490).
**Apply to:** `mcp_server.py` — return the callable's dict unchanged; it serializes as an MCP structured result. No adapter, no formatting (the agent's formatted-answer path is a separate concern).

## No Analog Found

None. Every file has an in-repo analog.

The only genuinely external element is the **FastMCP mounting/`mcp.tool` API surface**
(`combine_lifespans`, `mcp.http_app(path=...)`, `mcp.tool(...)`), which has no in-repo
precedent — follow RESEARCH.md Patterns 1-2 and confirm the exact 3.4.x kwargs against
the installed package at implementation (RESEARCH A1/Open-Q1).

## Metadata

**Analog search scope:** `backend/` (tools.py, query.py, main.py, auth.py, tests/conftest.py)
**Files scanned:** 5 source + 1 conftest
**Pattern extraction date:** 2026-07-15
