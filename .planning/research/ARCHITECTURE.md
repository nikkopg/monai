# Architecture Research

**Domain:** Agentic personal-finance app — FastAPI + Postgres + Next.js with agent loop, MCP server, investment subsystem, and multi-page UI
**Researched:** 2026-06-21
**Confidence:** HIGH (existing codebase confirmed; patterns verified against LlamaIndex, FastMCP, and Alembic docs)

## Standard Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         Browser (Next.js)                        │
│  /chat   /cashflow   /investments   /settings                    │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Chat page — proposal banner → confirm/reject button      │  │
│  └───────────────────────────────────────────────────────────┘  │
└──────────────────────────┬──────────────────────────────────────┘
                           │ fetch /api/* (Next.js rewrite proxy)
┌──────────────────────────▼──────────────────────────────────────┐
│                    FastAPI  (backend/main.py)                     │
│                                                                  │
│  POST /chat          POST /proposals/{id}/confirm                │
│  GET  /proposals     DELETE /proposals/{id}                      │
│  GET/POST /transactions  GET/POST /holdings                      │
│  POST /import        GET /prices   POST /settings                │
│                                                                  │
│  ┌──────────────┐  ┌────────────────┐  ┌──────────────────────┐ │
│  │  agent.py    │  │  proposals.py  │  │  price_service.py    │ │
│  │  (loop)      │  │  (store+TTL)   │  │  (fetch + cache)     │ │
│  └──────┬───────┘  └────────────────┘  └──────────────────────┘ │
│         │                                                        │
│  ┌──────▼──────────────────────────────────────────────────┐    │
│  │              tools.py  (shared tool registry)            │    │
│  │  read tools (9 existing)   +   write tools (new)         │    │
│  └──────┬──────────────────────────────────────────────────┘    │
│         │                                                        │
│  ┌──────▼──────────────────────────────────────────────────┐    │
│  │  mcp_server.py  (FastMCP, mounted at /mcp)               │    │
│  │  read tools exposed externally; write tools web-only     │    │
│  └─────────────────────────────────────────────────────────┘    │
└──────────────────────────┬──────────────────────────────────────┘
                           │ SQLAlchemy (Alembic-managed schema)
┌──────────────────────────▼──────────────────────────────────────┐
│                      PostgreSQL 16                                │
│  transactions   accounts   audit_log   proposals                 │
│  holdings       portfolio_events       price_cache               │
└─────────────────────────────────────────────────────────────────┘
                           │
                    ┌──────▼──────┐
                    │  External   │
                    │  MCP clients│
                    │ (Claude     │
                    │  Desktop /  │
                    │  IDE)       │
                    └────────────┘
```

### Component Responsibilities

| Component | Responsibility | Boundary |
|-----------|----------------|----------|
| `backend/agent.py` | Multi-step tool-calling loop; orchestrates tool selection, chaining, and stopping | Owns the agentic conversation loop; does NOT write data directly — emits proposals for writes |
| `backend/tools.py` | Single source of truth for all tool implementations — read tools (existing 9) + write tools (new) | Pure functions returning dicts; no HTTP, no agent state; reused by agent loop AND MCP server |
| `backend/proposals.py` | Stores pending write proposals (Postgres table + TTL); issues and validates confirmation tokens | All write actions flow through here before any DB mutation |
| `backend/mcp_server.py` | FastMCP instance mounted into FastAPI ASGI at `/mcp`; exposes read tools to external clients | No write tools exposed externally; same tool functions imported from `tools.py` |
| `backend/price_service.py` | Fetches and caches market prices; TTL-based refresh; per-source adapters (sectors.app, CoinGecko, manual fallback) | Never called by the agent directly — agent calls a tool that delegates here |
| `backend/importer.py` | Unchanged — CSV parse + bulk insert | Existing; no changes needed for this milestone |
| `backend/query.py` | REPLACED by `agent.py` | Existing single-shot router is the replacement target; keep file stub or rename |
| `ui/app/` | Multi-page Next.js App Router layout | Chat, Cashflow, Investments, Settings pages; shared nav in root layout |

## Recommended Project Structure

```
backend/
├── main.py              # FastAPI app + route registration; mounts MCP server
├── config.py            # Unchanged; add PRICE_API_KEY, PRICE_PROVIDER env vars
├── db.py                # Unchanged engine/session; remove create_all (Alembic takes over)
├── models.py            # Add: Holdings, PortfolioEvent, AuditLog, Proposal, PriceCache
├── schemas.py           # Add: ChatRequest/Response, ProposalOut, HoldingCreate/Out, etc.
├── tools.py             # EXTEND: add write tools (add_transaction, edit_transaction,
│                        #   delete_transaction, add_holding, edit_holding, delete_holding,
│                        #   add_account, edit_account, add_category_alias)
├── agent.py             # NEW: FunctionAgent or ReActAgent wrapper + streaming helper
├── proposals.py         # NEW: create_proposal(), get_proposal(), confirm_proposal(),
│                        #   expire_proposals(); Proposal Postgres table + uuid token
├── price_service.py     # NEW: get_price(ticker), refresh_prices(); adapter registry
├── mcp_server.py        # NEW: FastMCP(name="monai"); register read tools; mount in main.py
├── importer.py          # Unchanged
├── migrations/          # NEW: Alembic env + version scripts
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       ├── 001_add_audit_log.py
│       ├── 002_add_proposals.py
│       ├── 003_add_holdings_portfolio_events.py
│       └── 004_add_price_cache.py
└── tests/
    ├── test_tools.py        # Extend with write tool tests
    ├── test_router.py       # Unchanged (JSON extraction)
    ├── test_agent.py        # NEW: agent loop integration tests
    └── test_proposals.py    # NEW: proposal lifecycle tests

ui/app/
├── layout.tsx           # Root layout: add <Nav /> shared navigation
├── page.tsx             # Redirect to /chat or keep as landing
├── chat/
│   └── page.tsx         # Chat page: message list + proposal confirmation banner
├── cashflow/
│   └── page.tsx         # Cashflow dashboard + CRUD transaction table
├── investments/
│   └── page.tsx         # Holdings table + portfolio value + P&L
├── settings/
│   └── page.tsx         # LLM provider, API keys, base currency, price source
└── components/
    ├── Nav.tsx           # Shared navigation
    ├── ProposalBanner.tsx # Confirm/reject a pending write proposal
    └── ...
```

### Structure Rationale

- **`agent.py` separate from `query.py`:** The existing `query.py:ask()` is a single-shot tool call. The new agent is a multi-step loop — a qualitatively different component. Keep `query.py` as a stub or alias during transition to avoid breaking any tests; switch the `/chat` endpoint to `agent.py` once stable.
- **`tools.py` as shared registry:** Both `agent.py` and `mcp_server.py` import from the same `tools.py`. This is the correctness-by-construction guarantee — no separate copy of tool logic in the MCP server.
- **`proposals.py` as its own module:** The confirm-before-write path involves its own Postgres table, TTL logic, and token issuance. Colocating it in `main.py` would grow unmanageable.
- **`migrations/` in `backend/`:** Alembic env in the backend package, pointing at the same `DATABASE_URL`. The `create_all` in `db.py` is removed after the first Alembic baseline migration is created.

## Architectural Patterns

### Pattern 1: Shared Tool Registry (tools.py as the single source of truth)

**What:** `tools.py` is a `dict[str, callable]` mapping tool names to pure functions. Both the web agent and the MCP server import from it. Neither owns its own copy.

**When to use:** Any time you add a new capability — add one function to `tools.py`, register it in `TOOLS`, and it is automatically available to both the agent and (if you choose) the MCP server.

**Trade-offs:** Tight coupling between tool names/signatures and all consumers — deliberate here because correctness-by-construction requires exactly this constraint.

**Example:**
```python
# backend/tools.py
TOOLS: dict[str, callable] = {
    # existing read tools
    "spending_total": spending_total,
    "income_total": income_total,
    # ... 7 more
    # NEW write tools — same registry, same module
    "add_transaction": add_transaction,      # returns proposal dict, not DB write
    "edit_transaction": edit_transaction,
    "delete_transaction": delete_transaction,
    "add_holding": add_holding,
}

# backend/agent.py
from backend.tools import TOOLS
llama_tools = [FunctionTool.from_defaults(fn=fn, name=name) for name, fn in TOOLS.items()]

# backend/mcp_server.py
from backend.tools import TOOLS
READ_TOOL_NAMES = {k for k in TOOLS if not k.startswith(("add_", "edit_", "delete_"))}
for name in READ_TOOL_NAMES:
    mcp.tool(name=name)(TOOLS[name])
```

### Pattern 2: Agentic Loop (FunctionAgent wrapping tools.py)

**What:** Replace `query.py:ask()` with `agent.py` using LlamaIndex `FunctionAgent` (for LLMs with native function-calling like Claude/OpenAI) or `ReActAgent` (for Ollama models without native tool calling). The loop: LLM selects a tool and args → tool executes → result fed back to LLM → repeat until LLM emits a final answer with no tool call.

**When to use:** Multi-hop questions ("what was my net spending in the 3 months before I bought BBCA?"), compound queries (get portfolio events, then query spending in that window), write actions (agent identifies the change needed, emits a proposal).

**Trade-offs:** Higher latency per turn (multiple LLM round-trips); correctness-by-construction is preserved because the fixed TOOLS dict is unchanged; hallucinated tool names return a safe "tool not found" error, not SQL.

**Key constraint:** Write tools in the agent context do NOT write to the DB. They return a structured `ProposalDict` that `proposals.py` stores. The actual DB write only happens when `POST /proposals/{id}/confirm` is called.

**Example:**
```python
# backend/agent.py
from llama_index.core.agent import FunctionCallingAgent
from llama_index.core.tools import FunctionTool
from backend.tools import TOOLS
from backend.proposals import create_proposal

def _make_write_tool_wrapper(name, fn):
    """Write tools return a proposal, not a direct DB mutation."""
    async def wrapped(**kwargs):
        proposed = fn(**kwargs)   # returns dict describing the change
        token = create_proposal(action=name, payload=proposed)
        return {"status": "pending_confirmation", "proposal_token": token, "preview": proposed}
    wrapped.__name__ = name
    return FunctionTool.from_defaults(fn=wrapped, name=name)

WRITE_TOOL_NAMES = {"add_transaction", "edit_transaction", "delete_transaction",
                    "add_holding", "edit_holding", "delete_holding"}

def build_agent():
    tools = []
    for name, fn in TOOLS.items():
        if name in WRITE_TOOL_NAMES:
            tools.append(_make_write_tool_wrapper(name, fn))
        else:
            tools.append(FunctionTool.from_defaults(fn=fn, name=name))
    return FunctionCallingAgent.from_tools(tools, llm=get_llm(), verbose=False)
```

### Pattern 3: Confirm-Before-Write (proposal → token → confirm → audit)

**What:** Every agent-initiated write is intercepted before it hits the DB. The agent emits a proposal; the UI shows it with a confirm/reject button; the user's approval triggers the actual write + audit log entry. A TTL (e.g. 10 minutes) auto-expires unresponded proposals.

**When to use:** All agent-driven mutations. Direct UI CRUD (cashflow page transaction form) may bypass proposals — that is fine; proposals exist for AI-initiated writes where the user needs to verify the AI understood correctly.

**Trade-offs:** Adds one round-trip UI interaction for every AI write; worth it for a money app where fabricated mutations are worse than slow mutations.

**Data flow:**

```
Agent loop
  → write tool called
  → proposals.create_proposal(action, payload) → stores in `proposals` table
  → returns ProposalOut {id, token, preview, expires_at}
  → agent returns final answer: "I'll add a Rp 50.000 restaurant transaction on 2026-06-20.
     Please confirm."
  → UI renders ProposalBanner with preview and confirm/reject buttons

User clicks Confirm
  → POST /proposals/{id}/confirm  {token: "..."}
  → proposals.confirm_proposal(id, token) validates token + not expired
  → executes the actual DB write (tools.py write function, now with session)
  → inserts audit_log row {action, payload, confirmed_at, user="local"}
  → returns 200 OK

User clicks Reject (or proposal expires)
  → DELETE /proposals/{id}  OR  background TTL sweep
  → proposal row deleted; no DB mutation; no audit entry
```

**Schema:**
```sql
CREATE TABLE proposals (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  token       TEXT NOT NULL UNIQUE,          -- single-use confirmation token
  action      TEXT NOT NULL,                 -- "add_transaction", "edit_holding", etc.
  payload     JSONB NOT NULL,                -- the full proposed change
  preview     TEXT,                          -- human-readable description
  status      TEXT NOT NULL DEFAULT 'pending',  -- pending | confirmed | rejected | expired
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  expires_at  TIMESTAMPTZ NOT NULL,          -- created_at + 10 minutes
  confirmed_at TIMESTAMPTZ
);

CREATE TABLE audit_log (
  id          BIGSERIAL PRIMARY KEY,
  action      TEXT NOT NULL,
  payload     JSONB NOT NULL,
  source      TEXT NOT NULL DEFAULT 'agent', -- 'agent' | 'ui'
  proposal_id UUID REFERENCES proposals(id),
  committed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### Pattern 4: MCP Server Co-mounted in FastAPI (FastMCP)

**What:** FastMCP's `http_app()` returns an ASGI sub-application that mounts at `/mcp` in the same FastAPI process. One port, one deployment, shared CORS/middleware. External clients (Claude Desktop, IDEs) connect to `http://your-server:8001/mcp`.

**When to use:** Always for this project — running a separate MCP process doubles ops complexity for zero benefit in a single-user self-hosted app.

**Read/write gating:** Register only read tools with the FastMCP instance. Write tools are exposed only via the internal `agent.py` loop (which goes through the proposal flow). External MCP clients physically cannot call write tools because those tool names are not registered on the MCP server.

**Example:**
```python
# backend/mcp_server.py
from fastmcp import FastMCP
from backend.tools import TOOLS

READ_TOOL_NAMES = {"spending_total", "income_total", "net_total",
                   "spending_by_category", "spending_in_category",
                   "transaction_count", "largest_transactions",
                   "average_daily_spending", "list_categories",
                   # + new read tools for holdings/portfolio
                   "portfolio_value", "holdings_list", "correlation_spending_event"}

mcp = FastMCP(name="monai")
for name in READ_TOOL_NAMES:
    mcp.tool(name=name)(TOOLS[name])

# backend/main.py
from backend.mcp_server import mcp
app.mount("/mcp", mcp.http_app())
```

### Pattern 5: Investment Subsystem (holdings + price cache + correlation)

**What:** Two new tables (`holdings`, `portfolio_events`) + a price service with adapter registry. Price fetches are cached in a `price_cache` table with a per-ticker TTL (configurable, default 1 hour). Correlation tools join spending windows around portfolio event dates.

**Price source strategy (IDX + crypto + mutual funds):**
- **Crypto:** CoinGecko free API — well-covered, no key required at low volume
- **IDX stocks:** sectors.app API (commercial, Indonesia-specific) OR yfinance as a scraping fallback (fragile but free) — manual fallback is the guaranteed path
- **Indonesian mutual funds (reksadana):** No reliable free API; manual price entry is the primary path; consider OJK/Bareksa scraping if needed later
- **Manual fallback:** Any ticker with no live source accepts a `last_known_price` updated manually

**Schema:**
```sql
CREATE TABLE holdings (
  id            BIGSERIAL PRIMARY KEY,
  ticker        TEXT NOT NULL,
  name          TEXT,                        -- display name (e.g. "Bank Central Asia")
  quantity      NUMERIC(18,6) NOT NULL,
  avg_cost      NUMERIC(18,2) NOT NULL,
  purchase_date DATE NOT NULL,
  currency      TEXT NOT NULL DEFAULT 'IDR',
  asset_type    TEXT NOT NULL DEFAULT 'stock',  -- 'stock' | 'crypto' | 'mutual_fund' | 'other'
  price_source  TEXT,                         -- 'coingecko' | 'sectors' | 'yfinance' | 'manual'
  last_known_price NUMERIC(18,2),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE portfolio_events (
  id          BIGSERIAL PRIMARY KEY,
  date        DATE NOT NULL,
  ticker      TEXT NOT NULL,
  event_type  TEXT NOT NULL,                 -- 'buy' | 'sell' | 'dividend' | 'split'
  quantity    NUMERIC(18,6),
  price       NUMERIC(18,2),
  notes       TEXT
);

CREATE TABLE price_cache (
  ticker      TEXT PRIMARY KEY,
  price       NUMERIC(18,2) NOT NULL,
  currency    TEXT NOT NULL DEFAULT 'IDR',
  source      TEXT NOT NULL,
  fetched_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  ttl_seconds INT NOT NULL DEFAULT 3600
);
```

## Data Flow

### Agentic Chat Flow (read-only query)

```
User types question in /chat
  → POST /chat {message: "how much did I spend on food since I bought BBCA?"}
  → agent.py builds FunctionCallingAgent with all TOOLS
  → Agent loop iteration 1:
      LLM → {tool: "portfolio_events", args: {ticker: "BBCA"}}
      → tools.portfolio_events(ticker="BBCA") → [{date: "2024-03-15", event_type: "buy"}]
  → Agent loop iteration 2:
      LLM → {tool: "spending_in_category", args: {category: "food", period: "since:2024-03-15"}}
      → tools.spending_in_category(...) → {total: 4500000, currency: "IDR"}
  → Agent loop stops (no more tool calls)
  → LLM synthesizes final answer
  → POST /chat returns {answer: "...", sources: [...tool results...]}
```

### Confirm-Before-Write Flow

```
User: "Add a Rp 50.000 restaurant expense today"
  → POST /chat {message: "..."}
  → agent.py loop:
      LLM → {tool: "add_transaction", args: {amount: -50000, category: "Restaurant", date: "2026-06-21"}}
      → write tool wrapper → proposals.create_proposal(...)
      → returns ProposalOut {id: "uuid-xxx", token: "tok-yyy", preview: "Add -Rp50.000 Restaurant 2026-06-21"}
  → Agent returns: "I'll add that. Please confirm." + proposal embedded in response
  → UI renders ProposalBanner (preview + Confirm + Reject)

User clicks Confirm:
  → POST /proposals/uuid-xxx/confirm {token: "tok-yyy"}
  → proposals.confirm_proposal() validates: token matches, not expired, status=pending
  → Executes write: tools._execute_add_transaction(payload, session)
  → Inserts audit_log row
  → Updates proposal.status = 'confirmed'
  → Returns 200 {committed: true}
  → UI dismisses banner, refreshes transaction list

User clicks Reject (or 10 min pass):
  → DELETE /proposals/uuid-xxx  OR  background TTL sweep marks status='expired'
  → No DB mutation; no audit entry
```

### Price Fetch Flow

```
GET /prices (called on Investments page load, or by portfolio_value tool)
  → price_service.get_prices(tickers=[...])
  → For each ticker:
      Check price_cache (fetched_at + ttl_seconds > NOW()?) → cache hit: return cached price
      Cache miss:
        ticker.price_source == 'coingecko' → fetch CoinGecko API
        ticker.price_source == 'sectors'   → fetch sectors.app API
        ticker.price_source == 'manual'    → return last_known_price (no fetch)
      On fetch success: upsert price_cache row
      On fetch failure: return last_known_price with {stale: true} flag
  → Returns {ticker: {price, currency, stale, fetched_at}}
```

## Key Data Flows Summary

1. **Read query:** user → `/chat` → agent loop → tool(s) → SQL → formatted answer. No state written.
2. **AI write:** user → `/chat` → agent loop → write tool → proposal stored → UI shows banner → user confirms → `/proposals/{id}/confirm` → DB write + audit. Two HTTP round-trips, one DB write gate.
3. **Direct UI write (cashflow CRUD):** user → cashflow page form → `POST /transactions` → direct DB write + audit_log row. No proposal needed (user is already making an intentional direct action).
4. **Price refresh:** Investments page load → `GET /prices` → price_service → cache check → external API if stale → `price_cache` upsert.
5. **MCP external query:** Claude Desktop → `GET /mcp` → FastMCP → read tool → SQL → result. No write tools available.

## Build Order (Phase Dependencies)

The dependency graph determines what must exist before each component can be built:

```
Phase 1: Schema foundation (FIRST — everything depends on this)
  - Add Alembic; create baseline migration from current schema
  - Add: audit_log, proposals, holdings, portfolio_events, price_cache tables
  - Remove create_all from db.py; Alembic manages schema from here
  - No code changes to existing endpoints; zero regression risk

Phase 2: Agentic loop (SECOND — needs schema foundation, replaces query.py)
  - Write agent.py (FunctionAgent wrapper around existing TOOLS dict)
  - Write tool wrappers that return ProposalDict instead of writing
  - Write proposals.py (create/confirm/expire logic)
  - Update POST /chat endpoint in main.py
  - Add POST /proposals/{id}/confirm, DELETE /proposals/{id}
  - Existing read tools: zero changes

Phase 3: Multi-page UI (THIRD — can be built in parallel with Phase 2 backend)
  - Add Nav.tsx, ProposalBanner.tsx
  - Add /chat, /cashflow, /investments, /settings pages
  - Chat page: wire to new /chat endpoint + proposal confirmation flow
  - Cashflow page: wire existing CRUD endpoints + add edit/delete

Phase 4: Investment subsystem (FOURTH — needs schema from Phase 1)
  - Extend tools.py: portfolio_value, holdings_list, get_holding_detail
  - Write price_service.py with CoinGecko + manual adapters
  - POST /holdings CRUD endpoints
  - Wire Investments page (from Phase 3) to real data

Phase 5: MCP server (FIFTH — needs agent + tool layer stable from Phase 2)
  - Write mcp_server.py (FastMCP, read tools only)
  - Mount at /mcp in main.py
  - Test from Claude Desktop
  - Add correlation tools (spending_by_event_window) to TOOLS and expose via MCP
```

**Why this order:**
- Alembic must come first — `holdings`, `proposals`, `audit_log` are needed by multiple later phases. Without migrations, schema changes in a Docker Compose environment require manual `psql` intervention.
- Agent loop before MCP — the MCP server wraps the same tools as the agent, but it's simpler to validate tool correctness via the web UI (proposals visible, audit log inspectable) before exposing to external clients.
- UI multi-page can overlap with Phase 2 — the static page scaffolding (nav, routing, empty pages) doesn't depend on the agent being done. The chat page can start with a mock endpoint.
- Investment subsystem after multi-page UI — the Investments page exists before the data is live, and it can show a "no holdings yet" state while price_service.py is being built.

## Anti-Patterns

### Anti-Pattern 1: Write tools that directly mutate the DB

**What people do:** Implement `add_transaction(session, ...)` as a tool that inserts a row, then give it to the agent.

**Why it's wrong:** The agent can hallucinate arguments (wrong amount, wrong date, wrong category). Money mutations without user confirmation are the failure mode the entire architecture is designed to prevent.

**Do this instead:** Write tools return `ProposalDict`. The `proposals.confirm_proposal()` path is the only code path that touches the DB for mutations. Direct UI CRUD (forms) bypasses proposals because those are explicit user-initiated actions.

### Anti-Pattern 2: Separate MCP server process

**What people do:** Run `python mcp_server.py` as a second service in docker-compose.yml.

**Why it's wrong:** Adds a second port, second health check, second process to manage, and breaks the shared in-process tool call (you'd have to HTTP-call the FastAPI backend from the MCP server, introducing a network hop).

**Do this instead:** Mount FastMCP inside FastAPI with `app.mount("/mcp", mcp.http_app())`. One process, one port. External MCP clients connect to `http://host:8001/mcp`.

### Anti-Pattern 3: Duplicating tool logic in mcp_server.py

**What people do:** Copy-paste tool implementations into the MCP server file.

**Why it's wrong:** Two copies of the same SQL drift over time. The correctness-by-construction guarantee depends on one version of each tool being tested.

**Do this instead:** `mcp_server.py` imports functions from `tools.py` and registers them. Zero logic in `mcp_server.py` itself.

### Anti-Pattern 4: Keeping create_all with new tables

**What people do:** Add Holdings/Proposal ORM models and keep `Base.metadata.create_all()` in `db.py:init_db()`.

**Why it's wrong:** On an existing Postgres volume, `create_all` is idempotent for existing tables but creates new ones without constraints/indexes that Alembic would add. If the volume is recreated, `create_all` and Alembic migrations conflict. In a team or multi-env scenario, schema history is lost.

**Do this instead:** After Phase 1, remove `create_all`. Run `alembic upgrade head` on container startup (or in an init container). All schema changes go through versioned migration files.

### Anti-Pattern 5: Agent free-form SQL fallback

**What people do:** Add a `run_sql(query: str) -> list` escape hatch tool for questions the parameterized tools can't answer.

**Why it's wrong:** This is precisely what the tool-router pivot was designed to eliminate. The original `NLSQLTableQueryEngine` produced confident wrong numbers. A free-form SQL tool reintroduces that exact risk.

**Do this instead:** If a user question cannot be answered by existing tools, the agent says "I can't compute that yet." Add a new parameterized tool if the question pattern recurs.

## Integration Points

### External Services

| Service | Integration Pattern | Confidence | Notes |
|---------|---------------------|------------|-------|
| CoinGecko API | REST GET `/simple/price` | HIGH | Free tier, no key, 10–30 calls/min limit; sufficient for <50 tickers |
| sectors.app | REST GET (paid) | MEDIUM | Indonesia-specific IDX + financials; free tier limited |
| yfinance | Python library scraping Yahoo Finance | LOW | Fragile, breaks on Yahoo changes; use as last resort before manual |
| Claude / OpenAI / Ollama | LlamaIndex `Settings.llm` | HIGH | Existing pattern; unchanged |

### Internal Boundaries

| Boundary | Communication | Direction |
|----------|---------------|-----------|
| `agent.py` ↔ `tools.py` | Direct Python import; `FunctionTool.from_defaults(fn=...)` | agent imports tools |
| `mcp_server.py` ↔ `tools.py` | Direct Python import | mcp imports tools |
| `agent.py` ↔ `proposals.py` | Direct Python call: `create_proposal(action, payload)` | agent calls proposals |
| `main.py` ↔ `mcp_server.py` | ASGI mount: `app.mount("/mcp", mcp.http_app())` | main mounts mcp |
| `tools.py` ↔ `price_service.py` | Direct Python call from portfolio tools | tools call price_service |
| `main.py` ↔ `db.py` | FastAPI `Depends(get_session)` | unchanged pattern |

## Scaling Considerations

This is a single-user self-hosted app. Scaling is not a concern. What matters instead:

| Concern | Mitigation |
|---------|------------|
| Agent latency (multi-step LLM calls) | Stream partial responses via SSE; show thinking steps in UI |
| LLM as hard dependency | Maintain honest-refusal fallback; `except Exception` → "I couldn't answer that" |
| Price API rate limits | `price_cache` table absorbs repeated requests; TTL-gated fetches |
| Proposal table growth | Background sweep or startup cleanup of expired proposals older than 24h |
| Alembic on fresh volume | `alembic upgrade head` in docker entrypoint; idempotent |

## Sources

- LlamaIndex Agents docs: https://docs.llamaindex.ai/en/stable/module_guides/deploying/agents/
- LlamaIndex FunctionTool docs: https://developers.llamaindex.ai/python/framework/module_guides/deploying/agents/tools/
- FastMCP FastAPI integration: https://gofastmcp.com/integrations/fastapi
- FastMCP mount pattern (2026): https://ekky.dev/blog/2026-05-10-fastapi-fastmcp-mount-stream-authenticate
- fastapi_mcp (alternative, auto-routes): https://github.com/tadata-org/fastapi_mcp
- Human-in-the-loop patterns (Cloudflare): https://developers.cloudflare.com/agents/concepts/agentic-patterns/human-in-the-loop/
- AWS Bedrock HITL confirmation: https://aws.amazon.com/blogs/machine-learning/implement-human-in-the-loop-confirmation-with-amazon-bedrock-agents/
- Alembic with existing FastAPI + SQLAlchemy: https://pawamoy.github.io/posts/add-alembic-migrations-to-existing-fastapi-ormar-project/
- Alembic autogenerate: https://alembic.sqlalchemy.org/en/latest/autogenerate.html
- sectors.app (IDX data API): https://sectors.app/
- OHLC.dev (IDX API alternative): https://ohlc.dev/indonesia-stock-exchange-idx-api
- Idempotent agent retry patterns: https://www.buildmvpfast.com/blog/idempotent-ai-agent-retry-safe-patterns-production-workflow-2026

---
*Architecture research for: monai agentic AI layer + MCP + investment subsystem*
*Researched: 2026-06-21*
