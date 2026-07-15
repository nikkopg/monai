# Phase 6: MCP Server - Research

**Researched:** 2026-07-15
**Domain:** MCP (Model Context Protocol) server co-mounted on FastAPI; FastMCP framework
**Confidence:** HIGH (mounting/lifespan verified against official FastMCP docs + local code); MEDIUM (custom-header auth wiring — pattern derived from docs, exact code is planner's to write)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Expose the **full 15-tool read registry** from `backend/tools.py` over MCP — including the ID-lookup helpers `find_platforms` and `find_accounts`. No curation.
- **D-02:** **Close the agent/MCP parity gap in this phase.** Three read tools exist in the `TOOLS` registry but are NOT currently wired into the web agent's `read_tools` list in `backend/query.py`: `spending_before_after_purchase`, `monthly_trend`, `account_balances`. Add all three to the agent's `read_tools` so the web-agent surface and the MCP surface are **identical at 15 read tools** (MCP-02 stays literally true). Small additive edit to `query.py`'s `read_tools` list.
- **D-03:** **Writes are never exposed over MCP.** The 11 `propose_*` write tools do not appear in the MCP registry at all — calling one fails because the tool does not exist there (not merely blocked).
- **D-04:** **Reuse the single `MONAI_API_KEY`** (same secret FastAPI write routes validate via `backend/auth.py:require_api_key`). No separate MCP key. External client presents the key over the MCP HTTP transport.
- **D-05:** **Author MCP-facing tool descriptions** rather than relying purely on auto-derived docstrings. Descriptions MUST explicitly enumerate the valid `period` values (from `resolve_period` / `PERIODS`) and any other constrained param formats. Reuse existing docstrings as the base where they already read well.

### Claude's Discretion
- **Exact FastMCP auth wiring** — which header / mechanism FastMCP supports most cleanly for co-mounted HTTP; how `require_api_key` is adapted to the MCP request path vs. FastAPI's `Depends`. → **Researched below (Pitfall 2 / Pattern 3).**
- **Registration mechanics** — wrapping the `TOOLS` dict callables, decorating, or a thin adapter; keep `tools.py` single implementation, no logic fork. → **Researched below (Pattern 2).**
- **Return shape over MCP** — tools return structured dicts today; confirm they serialize cleanly as MCP tool results. → **Researched below (Pattern 2, confirmed clean).**
- **FastMCP version / mounting API** — pin and mount per current docs. → **Pinned: `fastmcp>=3.4,<4` (Pattern 1).**

### Deferred Ideas (OUT OF SCOPE)
- **Investment/portfolio reads over MCP** (portfolio value, P&L) — REST-only today, not in the tool registry; surfacing means new read tools; own scope, later phase.
- **Separate revocable MCP-only API key** — deferred in favor of reusing the single `MONAI_API_KEY` (D-04). Revisit if multi-client / key-rotation needs emerge.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| MCP-01 | monai exposes finance tools via a single MCP server | Pattern 1: one `FastMCP` instance co-mounted on the existing FastAPI app at `/mcp`, same process/port 8001. No second server. |
| MCP-02 | Web chat agent and external MCP clients share the same underlying tool implementations (one source of truth) | Pattern 2: register the `backend/tools.py:TOOLS` callables directly as MCP tools (thin wrappers, no logic fork). D-02 wires the 3 unwired tools into `query.py` so both surfaces are identical at 15. |
| MCP-03 | External clients can use read/query tools only; write tools not exposed | D-03: only `TOOLS` (15 read) are registered; the 11 `propose_*` callables are never passed to the MCP server → absent from `tools/list`. |
| MCP-04 | External clients must authenticate before use | Pattern 3 + Pitfall 2: Starlette middleware scoped to `/mcp` reusing `backend/auth.py` `_CONFIGURED_KEY` + `hmac.compare_digest`; unauthenticated → 401. |
</phase_requirements>

## Summary

Phase 6 co-mounts a FastMCP server onto monai's existing FastAPI app at `/mcp`, exposing the 15 read-only callables in `backend/tools.py:TOOLS` to external MCP clients (e.g. Claude Desktop) with the same implementations the web agent uses. The work is small and additive: add one dependency (`fastmcp`), create one new module (`backend/mcp_server.py`) that registers the `TOOLS` callables as MCP tools with hand-authored external-facing descriptions, wire the MCP ASGI app into `backend/main.py` via `combine_lifespans` (because the app already has a scheduler lifespan), gate the `/mcp` path with a middleware reusing the existing `MONAI_API_KEY` check, and make one additive edit to `query.py`'s `read_tools` list (D-02) to close the parity gap.

The single most important discovered fact that simplifies this phase: **the `TOOLS` callables self-manage their DB sessions** (each opens `get_session_sync()` internally and returns a plain structured `dict`). There is NO session-injection problem — an MCP tool wrapper just calls the callable and returns its dict, which serializes cleanly as an MCP structured result. No `Depends`, no per-request session plumbing into the MCP path.

Two real gotchas to plan around: (1) monai's app **already has a `lifespan`** (the APScheduler snapshot job), so you cannot just pass `mcp_app.lifespan` to `FastAPI(...)` — you must use `combine_lifespans(existing, mcp_app.lifespan)` or the MCP session manager silently fails to initialize; (2) monai's auth is a **custom `MONAI_API_KEY` header** (not OAuth/Bearer), so FastMCP's built-in `StaticTokenVerifier`/OAuth providers are the wrong tool — a thin Starlette middleware scoped to `/mcp` reusing `backend/auth.py` is the correct, minimal, one-secret path (D-04).

**Primary recommendation:** Add `fastmcp>=3.4,<4`; create `backend/mcp_server.py` that builds a `FastMCP` instance and registers the 15 `TOOLS` callables via a thin `mcp.tool` wrapper carrying hand-authored `period`-enumerating descriptions; mount `mcp.http_app(path="/")` at `/mcp` in `main.py` using `combine_lifespans`; enforce `MONAI_API_KEY` with a Starlette middleware scoped to `/mcp`; add the 3 missing tools to `query.py:read_tools`.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| MCP transport (tools/list, tools/call over streamable-HTTP) | API / Backend | — | Co-mounted ASGI sub-app on the FastAPI process; no new server, no frontend involvement. |
| Tool implementations (the 15 reads) | API / Backend (`tools.py`) | — | Already the single source of truth; MCP is a second consumer of the same callables. |
| Auth gate on `/mcp` | API / Backend (middleware) | — | Reuses `backend/auth.py`; header check happens at ASGI layer before MCP session handling. |
| Tool descriptions (LLM-facing) | API / Backend (`mcp_server.py`) | — | Static strings authored in the registration wrapper; consumed by the external client's model. |
| DB session per tool call | Database / Storage (`get_session_sync`) | — | Each callable self-manages its session; MCP tier does not plumb sessions. |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `fastmcp` | `>=3.4,<4` (latest 3.4.4) | Python MCP server framework; provides `FastMCP`, `@mcp.tool`, `mcp.http_app()` ASGI app, `combine_lifespans` | The canonical, most-used Python MCP framework; authored by Jeremiah Lowin (Prefect); official docs at gofastmcp.com. The reference MCP Python SDK's `FastMCP` derives from this project. `[VERIFIED: PyPI]` (106 releases, requires-python `>=3.10`, monai runs 3.12) `[CITED: gofastmcp.com/integrations/fastapi]` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `starlette` | (transitive, already present via FastAPI) | `BaseHTTPMiddleware` / pure-ASGI middleware for the `/mcp` auth gate | Needed only if you implement the auth gate as a Starlette middleware (recommended). Already installed. `[VERIFIED: local — FastAPI depends on Starlette]` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Thin `mcp.tool` wrappers over `TOOLS` | `FastMCP.from_fastapi(app=app)` (auto-convert REST endpoints to MCP) | REJECTED — FastMCP's own docs say "Stop Converting Your REST APIs to MCP"; auto-conversion would surface write endpoints too (violates D-03/MCP-03) and mirror REST param shapes, not the curated `period` vocabulary D-05 requires. `[CITED: gofastmcp.com/integrations/fastapi]` |
| Custom-header middleware reusing `require_api_key` | FastMCP `StaticTokenVerifier` / OAuth provider | REJECTED — `StaticTokenVerifier` expects a Bearer `Authorization` header and its own docs say "never use in production"; OAuth providers add machinery monai doesn't need. monai's contract is a static `MONAI_API_KEY` header + `hmac.compare_digest` (D-04). A scoped middleware reuses that verbatim. `[CITED: gofastmcp.com/servers/auth/token-verification]` |
| Separate MCP process/port | Standalone `mcp.run(transport="http")` server | REJECTED by MCP-01 + CONTEXT (co-mount on port 8001, same process). |

**Installation:**
```bash
# add to backend/requirements.txt:
fastmcp>=3.4,<4
```

**Version verification:** `fastmcp` latest = **3.4.4**, uploaded 2026-07-09, `requires_python: >=3.10`, 106 releases, repo `github.com/PrefectHQ/fastmcp`, docs `gofastmcp.com`. Verified via PyPI JSON API on 2026-07-15. monai's Docker runtime is Python 3.12-slim — compatible. `[VERIFIED: PyPI]`

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| `fastmcp` | PyPI | project 1.5+ yrs; latest release 2026-07-09 | high (unreadable via JSON API — PyPI does not expose download counts in `/pypi/json`) | github.com/PrefectHQ/fastmcp | **SUS (seam)** → **Approved (human-reviewed)** | Add to requirements |

**Seam verdict rationale:** `gsd-tools query package-legitimacy check` returned `SUS` with reasons `["too-new", "unknown-downloads"]`. Both are **false positives**: "too-new" is computed from the *latest release upload date* (2026-07-09 — a routine version bump of an established project with **106 releases**), and "unknown-downloads" is because the PyPI JSON endpoint does not carry download stats (not because downloads are low). The package is the canonical Python MCP framework, authored by Jeremiah Lowin (Prefect founder), with official documentation at gofastmcp.com referenced throughout the MCP ecosystem. Manually dispositioned **Approved**.

> Planner note: because the automated seam flagged `SUS`, add ONE `checkpoint:human-verify` task before the `pip install fastmcp` / requirements edit, per protocol. The human confirms `fastmcp` on PyPI resolves to `github.com/PrefectHQ/fastmcp` before install. Low effort, satisfies the gate.

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** `fastmcp` (seam false-positive — planner inserts one checkpoint:human-verify before install)

## Architecture Patterns

### System Architecture Diagram

```
External MCP client (Claude Desktop)                Web browser (Next.js chat)
        │  streamable-HTTP + MONAI_API_KEY header            │  SSE /query
        ▼                                                    ▼
┌────────────────────────── FastAPI app (backend/main.py, port 8001) ──────────────────────────┐
│                                                                                               │
│   Starlette middleware (scoped to /mcp path)                                                  │
│     └─ reuse backend/auth.py: _CONFIGURED_KEY + hmac.compare_digest                           │
│          ├─ missing/invalid MONAI_API_KEY  → 401 (reject before MCP session)   [MCP-04]       │
│          └─ valid → pass through                                                              │
│                          │                                                                    │
│   app.mount("/mcp", mcp_app)          existing REST routes (/query, /transactions, ...)       │
│        │                                        │                                             │
│        ▼ mcp.http_app(path="/")                 ▼ backend/query.py  FunctionAgent             │
│   FastMCP instance (backend/mcp_server.py)      read_tools[15] + write_tools[11]              │
│     tools/list → 15 read tools ONLY  [MCP-03]        │                                         │
│     tools/call name,args                             │                                         │
│        │                                             │                                         │
│        └──────────────┬──────────────────────────────┘                                        │
│                       ▼                                                                        │
│              backend/tools.py : TOOLS  (15 read callables — SINGLE SOURCE OF TRUTH)  [MCP-02] │
│                       │  each opens get_session_sync() internally, returns structured dict    │
│                       ▼                                                                        │
│              PostgreSQL (parameterized SQL only — no free-form SQL over MCP)                   │
└───────────────────────────────────────────────────────────────────────────────────────────────┘
```

Lifespan: `FastAPI(lifespan=combine_lifespans(existing_scheduler_lifespan, mcp_app.lifespan))`.

### Recommended Project Structure
```
backend/
├── mcp_server.py    # NEW: build_mcp() → FastMCP instance; register 15 TOOLS as mcp.tool with authored descriptions
├── auth.py          # REUSE: _CONFIGURED_KEY + hmac check; expose a helper the /mcp middleware calls (see Pattern 3)
├── main.py          # EDIT: import build_mcp; mcp_app = mcp.http_app(path="/"); combine_lifespans; app.mount("/mcp", mcp_app); add /mcp auth middleware
├── tools.py         # UNCHANGED: TOOLS is the single source of truth (already 15)
├── query.py         # EDIT (D-02): add spending_before_after_purchase, monthly_trend, account_balances to read_tools
└── tests/
    └── test_mcp.py  # NEW: reuse client/api_key fixtures; assert tools/list=15 read-only, a read call, write absent, 401 unauth
```

### Pattern 1: Co-mount FastMCP on existing FastAPI with combined lifespans
**What:** Build the MCP ASGI app and mount it at `/mcp`; combine its lifespan with monai's existing scheduler lifespan.
**When to use:** Whenever the parent FastAPI app already has a `lifespan` (monai does — APScheduler).
**Example:**
```python
# Source: https://gofastmcp.com/integrations/fastapi  (Combining Lifespans, Basic Mounting)
# backend/main.py (shape)
from fastmcp.utilities.lifespan import combine_lifespans
from backend.mcp_server import build_mcp

mcp = build_mcp()                       # FastMCP instance with 15 tools registered
mcp_app = mcp.http_app(path="/")        # path="/" because we mount at "/mcp" → endpoint is /mcp

# EXISTING scheduler lifespan is `lifespan` (already defined). Combine, don't replace:
app = FastAPI(
    title="monai", version="0.1.0",
    lifespan=combine_lifespans(lifespan, mcp_app.lifespan),   # enters in order, exits reversed
)
# ... existing middleware / routes ...
app.mount("/mcp", mcp_app)              # MCP endpoint at http://host:8001/mcp
```
`[CITED: gofastmcp.com/integrations/fastapi]` `[VERIFIED: local — backend/main.py:120-139 confirms existing `lifespan`]`

### Pattern 2: Register TOOLS callables as MCP tools with authored descriptions (no logic fork)
**What:** Loop the `TOOLS` dict; register each callable as an MCP tool, attaching a hand-authored external-facing description (D-05). Return the callable's dict unchanged (serializes as MCP structured content).
**When to use:** This is the core of MCP-02 — one implementation, two consumers.
**Key facts that make this trivial:**
- Each `TOOLS` callable **self-manages its DB session** (`with get_session_sync() as db:` internally) and takes only plain params (`period: str`, `limit: int`, etc.). No session injection into the MCP path is needed. `[VERIFIED: local — backend/tools.py:485,528; find_accounts signature `(name=None, limit=10)`]`
- Each returns a plain `dict` (e.g. `{"tool": "find_accounts", "rows": [...]}`) — JSON-serializable, so it lands as an MCP tool result without adaptation (unlike the agent's formatted-answer path, which is a separate concern). `[VERIFIED: local — every TOOLS callable returns a dict]`
**Example:**
```python
# backend/mcp_server.py (shape)
from fastmcp import FastMCP
from backend.tools import TOOLS, PERIODS           # PERIODS = the valid period vocabulary
# Hand-authored, external-LLM-facing descriptions (D-05). period-taking tools enumerate PERIODS.
_PERIOD_HELP = "period is one of: " + ", ".join(PERIODS) + \
    ' — use "custom" with ISO start_date/end_date (end inclusive) for arbitrary ranges.'
MCP_DESCRIPTIONS: dict[str, str] = {
    "spending_total": "Total spending (money out) over a period. " + _PERIOD_HELP,
    # ... one authored line per tool; reuse docstring prose where it already reads well ...
}

def build_mcp() -> FastMCP:
    mcp = FastMCP("monai finance (read-only)")
    for name, fn in TOOLS.items():
        # Thin wrapper: attach authored description; keep fn's signature/params via FastMCP introspection.
        mcp.tool(name=name, description=MCP_DESCRIPTIONS.get(name, fn.__doc__ or name))(fn)
    return mcp
```
> Registration mechanic note (Discretion): FastMCP's `mcp.tool(...)` accepts `name` and `description` overrides and derives the input JSON-schema from the callable's type-annotated signature — so passing the raw `TOOLS` callable works and no logic is forked. Confirm during implementation that `mcp.tool(name=..., description=...)(fn)` is the exact 3.x call form (the docs show the decorator `@mcp.tool` and the callable form; both accept `name`/`description` kwargs). `[CITED: gofastmcp.com/integrations/fastapi]` `[ASSUMED — exact kwargs of mcp.tool in 3.4.x to be confirmed at implementation]`

### Pattern 3: Auth gate on the mounted /mcp path (reuse MONAI_API_KEY, D-04)
**What:** A middleware scoped to request paths under `/mcp` that reuses `backend/auth.py`'s configured-key + constant-time check. Reject with 401 before the MCP session manager sees the request.
**When to use:** MCP-04. This is the discretion item — chosen over FastMCP's OAuth/StaticTokenVerifier because monai's contract is a static custom header.
**Example:**
```python
# backend/main.py (shape) — Starlette pure middleware scoped to /mcp
import hmac
from starlette.responses import JSONResponse
from backend import auth   # reuse _CONFIGURED_KEY

@app.middleware("http")
async def mcp_api_key_guard(request, call_next):
    if request.url.path.startswith("/mcp"):
        if not auth._CONFIGURED_KEY:
            return JSONResponse({"detail": "Server misconfigured: MONAI_API_KEY unset"}, status_code=503)
        key = request.headers.get("MONAI_API_KEY")
        if key is None or not hmac.compare_digest(key, auth._CONFIGURED_KEY):
            return JSONResponse({"detail": "Invalid or missing API key"}, status_code=401)
    return await call_next(request)
```
> Cleaner refactor (recommended, still minimal): extract the key-check body of `require_api_key` into a small `auth.check_key(key: str | None) -> None` (raises) or `auth.key_ok(key) -> bool`, and call it from BOTH the FastAPI dependency and this middleware — so the constant-time comparison lives in exactly one place. This keeps D-04's "one secret, one check" literally true and avoids duplicating the hmac logic. `[VERIFIED: local — backend/auth.py:40-51 is the logic to extract]`
> Header choice: monai's existing clients send the custom header `MONAI_API_KEY` (not `Authorization: Bearer`). Reuse that exact header name for the MCP transport so there is one auth convention across the whole app (D-04). An MCP client that supports custom headers (Claude Desktop's HTTP transport `headers` config) sends `MONAI_API_KEY: <key>`. `[VERIFIED: local — backend/auth.py:22 header name]`

### Anti-Patterns to Avoid
- **Passing `mcp_app.lifespan` alone to `FastAPI(...)`** when an app lifespan already exists → drops the scheduler startup. Use `combine_lifespans`.
- **`FastMCP.from_fastapi(app)` auto-conversion** → surfaces write endpoints (breaks D-03/MCP-03) and REST param shapes instead of the curated `period` vocabulary.
- **Re-implementing tool logic for MCP** → forks the single source of truth; MCP-02 requires reusing `TOOLS` callables verbatim.
- **Adding a second server/port** → violates MCP-01 (single server) and CONTEXT (co-mount on 8001).
- **Reaching for OAuth/StaticTokenVerifier** for a single static key → over-engineered; `StaticTokenVerifier` is explicitly dev-only per FastMCP docs.
- **App-wide CORS interacting with an OAuth-mounted MCP** → not applicable here (no OAuth), but note monai already has `CORSMiddleware`; since we use a plain header (no `.well-known`/OAuth routes), the documented CORS-vs-OAuth conflict does not apply. `[CITED: gofastmcp.com/integrations/fastapi — CORS Middleware]`

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| MCP protocol (tools/list, tools/call, streamable-HTTP, session mgmt, JSON-RPC framing) | A hand-rolled JSON-RPC/SSE handler | `fastmcp` `mcp.http_app()` | Protocol correctness, transport negotiation, and MCP session lifecycle are exactly what the framework provides. |
| Tool input JSON-schema | Manually written per-tool schemas | FastMCP deriving schema from the callable's type hints | The `TOOLS` callables are already fully type-annotated; FastMCP generates the schema. |
| Combining two ASGI lifespans | Nested `async with` boilerplate | `fastmcp.utilities.lifespan.combine_lifespans` | Provided, ordered-enter/reverse-exit, one line. |
| API-key constant-time check | New comparison code in the middleware | Reuse `backend/auth.py` (`_CONFIGURED_KEY` + `hmac.compare_digest`) | D-04 one-secret/one-check; avoids a timing-unsafe duplicate. |

**Key insight:** This phase is almost entirely wiring, not building. The two assets that already exist — the self-session-managing `TOOLS` callables and the `MONAI_API_KEY` check — mean the only genuinely new code is ~1 module (`mcp_server.py`) plus ~15 lines of mounting/middleware in `main.py`.

## Runtime State Inventory

> Greenfield-additive phase (no rename/refactor of stored strings). Included for completeness because it touches auth/config.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — MCP is read-only; no new tables, no stored keys. Verified: no schema change in scope (portfolio reads deferred). | none |
| Live service config | External MCP clients (Claude Desktop) must be configured with the `/mcp` URL + `MONAI_API_KEY` header — this config lives in the client, not in monai's repo. | Document the client-side connection config in phase verification steps (not a monai code change). |
| OS-registered state | None — same uvicorn process, no new scheduler/task. Verified: mount is in-process. | none |
| Secrets/env vars | `MONAI_API_KEY` — **reused, unchanged** (D-04). No new secret. Verified: `backend/auth.py:27` reads it once at import. | none (ensure it is set — already required for write routes) |
| Build artifacts / installed packages | New dependency `fastmcp` → Docker image must be rebuilt after `requirements.txt` edit (MEMORY: "deploy requires rebuild"). | `docker compose up -d --build` before live/UAT verification. |

## Common Pitfalls

### Pitfall 1: Existing lifespan silently dropped → scheduler stops running
**What goes wrong:** Following the "basic" docs snippet `app = FastAPI(lifespan=mcp_app.lifespan)` replaces monai's existing scheduler lifespan; the daily portfolio-value snapshot job (Phase 5/7) silently stops.
**Why it happens:** monai already defines `lifespan` (backend/main.py:120) for APScheduler; the common tutorial assumes a fresh app with no lifespan.
**How to avoid:** Use `combine_lifespans(lifespan, mcp_app.lifespan)` (Pattern 1). The docs explicitly cover this case.
**Warning signs:** MCP works but the daily snapshot no longer appears; or MCP session-manager errors if the MCP lifespan is dropped instead.
`[CITED: gofastmcp.com/integrations/fastapi — Combining Lifespans]`

### Pitfall 2: Wrong auth mechanism (Bearer/OAuth) instead of the existing custom header
**What goes wrong:** Wiring FastMCP's `StaticTokenVerifier` or an OAuth provider — expects `Authorization: Bearer`, adds a second auth convention, and `StaticTokenVerifier` is documented as dev-only. Breaks D-04's single-secret goal.
**Why it happens:** FastMCP's auth docs foreground OAuth/token verifiers; the "just reuse my one header" path is a plain ASGI middleware, not a FastMCP feature.
**How to avoid:** Gate `/mcp` with a Starlette middleware reusing `backend/auth.py` (Pattern 3). Extract the check into `auth.key_ok()`/`auth.check_key()` so it lives in one place.
**Warning signs:** Clients need to send `Authorization: Bearer` while write routes need `MONAI_API_KEY` — two conventions = D-04 violated.

### Pitfall 3: Mount path vs. http_app(path=...) double-prefix
**What goes wrong:** `mcp.http_app(path="/mcp")` **and** `app.mount("/mcp", mcp_app)` → endpoint becomes `/mcp/mcp`, and the ROADMAP success criterion says the connect target is literally `http://host:8001/mcp`.
**Why it happens:** Both the http_app `path` and the mount prefix contribute to the final URL.
**How to avoid:** Use `mcp.http_app(path="/")` + `app.mount("/mcp", mcp_app)` → endpoint is exactly `/mcp`, matching the ROADMAP. (The docs' "Lifespan Management" snippet uses precisely this combination.)
**Warning signs:** Client 404s at `/mcp`; tool list only reachable at `/mcp/mcp`.
`[CITED: gofastmcp.com/integrations/fastapi — Lifespan Management snippet]`

### Pitfall 4: Middleware ordering vs. the mounted sub-app
**What goes wrong:** If the auth check is placed inside the MCP app instead of the outer FastAPI middleware, the MCP session manager may process (and error on) the request before auth runs.
**Why it happens:** Mounted ASGI sub-apps handle their own request lifecycle; the outer app's middleware runs first only if the guard is registered on the outer app.
**How to avoid:** Register the `/mcp` guard as outer-app middleware (`@app.middleware("http")` or `app.add_middleware`), so it runs before the request reaches the mounted `mcp_app`. The FastAPI docs note mounted MCP routes "go through the same outer app," so outer middleware (CORS, auth) applies. `[CITED: gofastmcp.com/integrations/fastapi]`

## Code Examples

### Enumerating the valid period vocabulary in a description (D-05)
```python
# Source: local backend/tools.py:30-34 (PERIODS) + resolve_period contract
from backend.tools import PERIODS
# PERIODS = ("this_week","last_week","this_month","last_month","this_year",
#            "last_year","last_30_days","last_90_days","all_time","custom")
period_help = (
    "period must be one of: " + ", ".join(p for p in PERIODS if p != "custom")
    + '. Or pass period="custom" with ISO start_date and end_date (end inclusive).'
)
```
`[VERIFIED: local — backend/tools.py:30-34]`

### Reusing the existing test fixtures for MCP tests
```python
# Source: local backend/tests/conftest.py — client (TestClient) + api_key (monkeypatch) already exist
def test_mcp_lists_only_read_tools(client, api_key):
    # POST the MCP tools/list JSON-RPC to /mcp with the MONAI_API_KEY header; assert 15 read tools, no propose_*.
    ...
def test_mcp_requires_key(client):
    # Same call WITHOUT the header → 401 (MCP-04)
    ...
```
`[VERIFIED: local — backend/tests/conftest.py:30-58 (client, api_key fixtures); test_auth.py 401 pattern]`

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Convert REST/OpenAPI → MCP (`from_fastapi`) as the primary path | Curated, purpose-built `@mcp.tool` servers | FastMCP guidance ("Stop Converting Your REST APIs to MCP") | Confirms Pattern 2 (curated tools) over auto-conversion — aligns with D-01/D-05. |
| SSE transport | streamable-HTTP (default for `http_app`) | MCP spec evolution | Use `mcp.http_app(path="/")` default transport; SSE is legacy. |
| Pass single `mcp_app.lifespan` | `combine_lifespans` when app has its own lifespan | FastMCP utilities | Required here (scheduler). |

**Deprecated/outdated:**
- SSE-only MCP transport: superseded by streamable-HTTP.
- `StaticTokenVerifier` for real auth: documented dev-only; not for monai's production single-user deployment.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Exact call form `mcp.tool(name=..., description=...)(fn)` in FastMCP 3.4.x accepts a pre-defined callable with name/description overrides | Pattern 2 | LOW — if the 3.x API differs slightly (e.g. `mcp.add_tool(...)` or `Tool.from_function`), the fix is a one-line change; the approach (register `TOOLS` callables with authored descriptions) holds. Confirm against installed `fastmcp` at implementation. |
| A2 | Claude Desktop / target MCP client can send a **custom** header (`MONAI_API_KEY`) on its HTTP transport | Pattern 3 / D-04 | MEDIUM — if the client only supports `Authorization: Bearer`, the middleware can additionally accept `Authorization: Bearer <key>` as a fallback (still reuses the same `_CONFIGURED_KEY`). Verify the client's header config during UAT. Does not change the server design. |
| A3 | `fastmcp` weekly download volume is high (seam could not read it) | Package Legitimacy Audit | LOW — legitimacy established via authorship + official docs + 106 releases; download count is corroborating, not load-bearing. |

**If this table is empty:** N/A — three assumptions logged; A2 is the one worth confirming in UAT.

## Open Questions

1. **Exact FastMCP 3.4.x tool-registration API surface**
   - What we know: `@mcp.tool` decorator and `mcp.http_app(path=...)` + `combine_lifespans` are confirmed from official docs; registration accepts name/description overrides.
   - What's unclear: the precise method name/kwargs for registering a *pre-existing* callable (vs. decorating a fresh def) in 3.4.x.
   - Recommendation: at implementation, `python -c "import fastmcp, inspect; help(fastmcp.FastMCP.tool)"` in the built image to confirm; trivial to adjust.

2. **Client-side header support**
   - What we know: the server accepts `MONAI_API_KEY`.
   - What's unclear: whether the specific external client used for UAT sends custom headers vs. only Bearer.
   - Recommendation: have the middleware accept both `MONAI_API_KEY: <key>` and `Authorization: Bearer <key>` (same secret) to be client-agnostic; verify in UAT.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | backend runtime | ✓ | 3.12 (Docker) / 3.14 (host) | — |
| `fastmcp` | MCP server | ✗ (not yet installed) | target 3.4.4 (`>=3.4,<4`) | none — must add to requirements + rebuild image |
| FastAPI / Starlette / uvicorn | co-mount host + middleware | ✓ | FastAPI >=0.110, uvicorn[standard] >=0.27 | — |
| PostgreSQL | tool data | ✓ | 16-alpine | — |
| `pytest` / `httpx` TestClient | MCP tests | ✓ | pytest >=8, httpx >=0.27 | — |

**Missing dependencies with no fallback:** `fastmcp` — must be added to `backend/requirements.txt`; Docker image rebuilt (`docker compose up -d --build`) before live/UAT (MEMORY: deploy requires rebuild).
**Missing dependencies with fallback:** none.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest >=8.0.0 (+ pytest-asyncio; httpx TestClient) |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`, `testpaths = ["backend/tests"]`) |
| Quick run command | `python -m pytest backend/tests/test_mcp.py -x -q` |
| Full suite command | `python -m pytest backend/tests -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| MCP-01 | `/mcp` is served by the single co-mounted app (200 on MCP handshake with key) | integration | `pytest backend/tests/test_mcp.py::test_mcp_endpoint_mounted -x` | ❌ Wave 0 |
| MCP-02 | tools/list returns exactly the 15 `TOOLS` names; a read call returns the same dict a direct `TOOLS[name](...)` call returns (parity) | integration | `pytest backend/tests/test_mcp.py::test_mcp_read_parity -x` | ❌ Wave 0 |
| MCP-02 | `query.py:read_tools` now contains all 15 (D-02 parity) | unit | `pytest backend/tests/test_mcp.py::test_agent_read_tools_count -x` | ❌ Wave 0 |
| MCP-03 | tools/list contains zero `propose_*`; calling a write name errors "unknown tool" | integration | `pytest backend/tests/test_mcp.py::test_mcp_no_write_tools -x` | ❌ Wave 0 |
| MCP-04 | request to `/mcp` without `MONAI_API_KEY` → 401; with valid key → not 401 | integration | `pytest backend/tests/test_mcp.py::test_mcp_requires_key -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest backend/tests/test_mcp.py -x -q`
- **Per wave merge:** `python -m pytest backend/tests -q`
- **Phase gate:** Full suite green before `/gsd-verify-work`; then live UAT: connect an external MCP client to `http://host:8001/mcp` with the key, enumerate (15 read, 0 write), call "spending total last month", confirm parity with web chat.

### Wave 0 Gaps
- [ ] `backend/tests/test_mcp.py` — covers MCP-01..MCP-04 (reuses existing `client` + `api_key` fixtures from conftest.py; no new fixtures needed)
- [ ] Framework install: `fastmcp>=3.4,<4` in `backend/requirements.txt` + image rebuild (blocks any MCP test importing the mounted app)

*(No conftest changes needed — `client`, `async_client`, and `api_key` fixtures already exist and cover the MCP HTTP + auth test needs.)*

## Security Domain

> `security_enforcement` not disabled in config → included.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | Static `MONAI_API_KEY` header, constant-time `hmac.compare_digest`, fail-closed 503 if unset (reused from `backend/auth.py`). |
| V3 Session Management | no | MCP streamable-HTTP is stateless per-call under a single API key; no user sessions. |
| V4 Access Control | yes | Read-only surface by construction (only `TOOLS` registered; `propose_*` never present → MCP-03). No privilege escalation path to writes. |
| V5 Input Validation | yes | Tool params validated via FastMCP-derived JSON-schema from type hints; SQL is parameterized in `tools.py` (no free-form SQL over MCP — correctness-by-construction preserved). |
| V6 Cryptography | yes (minimal) | Only the constant-time key comparison; no new crypto. Do not hand-roll. |

### Known Threat Patterns for FastAPI + FastMCP co-mount

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Unauthenticated MCP access exposes finance data | Information Disclosure | `/mcp` auth middleware rejects missing/invalid key with 401 before MCP session handling (MCP-04). |
| Write tools reachable via MCP | Elevation of Privilege / Tampering | `propose_*` never registered → absent from `tools/list`; calling one is "unknown tool" (D-03/MCP-03). |
| Free-form SQL injection via a "flexible" MCP tool | Tampering | No such tool exists; all tools are the parameterized `TOOLS` callables. Do NOT add a raw-query tool. |
| Timing attack on key comparison | Information Disclosure | `hmac.compare_digest` (already used) — reuse, don't replace with `==`. |
| Key leakage via logs/trace | Information Disclosure | Do not log the `MONAI_API_KEY` header value in the `/mcp` middleware (mirror existing auth's silence). |

## Sources

### Primary (HIGH confidence)
- `gofastmcp.com/integrations/fastapi` — Mounting an MCP Server, Basic Mounting, Lifespan Management, Combining Lifespans (`combine_lifespans`), CORS Middleware, `@mcp.tool` shape. Fetched 2026-07-15.
- Local codebase (`backend/tools.py`, `backend/auth.py`, `backend/query.py`, `backend/main.py`, `backend/tests/conftest.py`, `pyproject.toml`) — self-session-managing callables, dict returns, `MONAI_API_KEY` header + hmac check, existing lifespan, existing test fixtures. Read 2026-07-15.
- PyPI JSON API (`pypi.org/pypi/fastmcp/json`) — version 3.4.4, requires-python >=3.10, 106 releases, repo PrefectHQ/fastmcp. Queried 2026-07-15.

### Secondary (MEDIUM confidence)
- `gofastmcp.com/servers/auth/token-verification` — `StaticTokenVerifier` (Bearer, dev-only) — confirms why the custom-header middleware is the right choice here.

### Tertiary (LOW confidence)
- WebSearch result summaries (medium/blog posts on FastMCP+FastAPI mounting/auth) — used only to locate the official docs, not cited as authority.

## Metadata

**Confidence breakdown:**
- Standard stack (fastmcp, mounting): HIGH — verified against official docs + PyPI + local code.
- Architecture (co-mount, combine_lifespans, tool reuse): HIGH — exact patterns quoted from official docs; local facts (self-session-managing dict-returning callables) verified in source.
- Auth wiring (custom-header middleware): MEDIUM — approach is sound and reuses verified local code, but the concrete middleware code is the planner's to write; client-side header support (A2) needs UAT confirmation.
- Pitfalls: HIGH — each maps to a documented behavior or a verified local fact.

**Research date:** 2026-07-15
**Valid until:** 2026-08-14 (30 days; FastMCP is active — re-confirm the tool-registration API against the installed 3.x at implementation, per A1/Open Q1).
