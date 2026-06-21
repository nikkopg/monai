# Stack Research

**Domain:** Self-hosted personal-finance app — agentic AI chat, MCP server, live investment prices, DB migrations, charting
**Researched:** 2026-06-21
**Confidence:** HIGH (agentic chat, MCP, Alembic, charting) / MEDIUM (IDX prices) / LOW (reksadana prices)

> This is a SUBSEQUENT milestone research file. All five areas below are ADDITIONS to the existing stack
> (FastAPI + PostgreSQL 16 + SQLAlchemy 2 / psycopg3 + Next.js 14.2 / React 18 + LlamaIndex Core >=0.10.0).
> Do not re-recommend existing choices.

---

## 1. Agentic Chat — LlamaIndex Multi-Step Tool-Calling

### Recommended approach: `AgentWorkflow` + `FunctionAgent`

Use `AgentWorkflow` (the single-agent form) wrapping a `FunctionAgent`. This is the current LlamaIndex-endorsed
pattern as of llama-index-core 0.14.x (latest: 0.14.22, May 2026). `AgentRunner` / `FunctionCallingAgentWorker`
(from `llama-index-agent-openai`) are **explicitly deprecated** — they were removed in the 0.14 line.

**Why FunctionAgent over ReActAgent:** The project already uses Claude, OpenAI, and Ollama (with models like
gemma4 that support native function calling). FunctionAgent uses the LLM provider's native tool-calling API,
which is faster and more reliable than the text-based ReAct prompting pattern. Use ReActAgent only for models
confirmed to lack function-calling support.

**Human-in-the-loop (confirm-before-write):** LlamaIndex `Workflow` has first-class support via
`InputRequiredEvent` and `HumanResponseEvent` (both in `llama_index.core.workflow`). The pattern:
a write-tool step emits `InputRequiredEvent` with a description of the proposed change; the workflow suspends via
`ctx.wait_for_event(HumanResponseEvent, ...)`; the FastAPI handler surfaces the prompt to the UI; the user
approves/rejects; the frontend sends the response back; the workflow resumes or aborts. This is the documented
pattern in official LlamaIndex HITL docs and works cleanly with SSE or WebSocket event streaming from FastAPI.

### Core Libraries

| Library | Version | Purpose | Why |
|---------|---------|---------|-----|
| `llama-index-core` | `>=0.14.0` | `AgentWorkflow`, `FunctionAgent`, `InputRequiredEvent`, `HumanResponseEvent`, `FunctionTool` | All agent + HITL primitives live here; no separate agent package needed |
| `llama-index-llms-anthropic` | current | Claude provider for agentic loop | Already in use; function-calling support confirmed |
| `llama-index-llms-openai` | current | OpenAI provider | Already in use; do NOT use `llama-index-agent-openai` (deprecated, pins old llms-openai) |
| `llama-index-llms-ollama` | current | Ollama local provider | Already in use; verify your local model supports function calling |

**No new packages needed** for the agent itself beyond upgrading `llama-index-core` to `>=0.14.0`.

### Key imports (current API)

```python
from llama_index.core.agent.workflow import FunctionAgent, AgentWorkflow
from llama_index.core.workflow import InputRequiredEvent, HumanResponseEvent
from llama_index.core.tools import FunctionTool
```

### Existing tool migration

The 9 functions in `backend/tools.py` become `FunctionTool` instances:

```python
tool = FunctionTool.from_defaults(fn=spending_total, name="spending_total", description="...")
```

Wrap them in a `FunctionAgent`, then wrap that in an `AgentWorkflow`. Write tools (add/edit/delete) follow
the same pattern but their implementations emit `InputRequiredEvent` before executing the SQL mutation.

### What NOT to use

| Avoid | Why |
|-------|-----|
| `llama-index-agent-openai` | Deprecated; pins old `llms-openai` versions causing dependency conflicts |
| `AgentRunner` / `FunctionCallingAgentWorker` | Explicitly deprecated in 0.14, removed |
| `ReActAgent` (text-based) | Inferior to FunctionAgent when function-calling is available; slower, less reliable |
| LangGraph / AutoGen | Re-platforming; LlamaIndex already installed and working |

---

## 2. MCP Server — Python, co-existing with FastAPI

### Recommended: FastMCP 3.x, mounted inside FastAPI, Streamable HTTP transport

**FastMCP** (latest: 3.4.2, June 6 2026; `pip install fastmcp`) is the official Pythonic wrapper over the
`mcp` SDK (latest: 1.28.0; v2 alpha targeting stable 2026-07-27, stay on v1.x). FastMCP is the recommended
path in all current MCP Python documentation — it eliminates boilerplate while remaining fully spec-compliant.

**Transport: Streamable HTTP** — the MCP spec updated 2025-03-26 to replace SSE with Streamable HTTP as the
recommended production transport. It uses standard HTTP POST + persistent response streams (bidirectional).
Use `transport="streamable-http"` in `mcp.http_app(transport="streamable-http", path="/")`.

**Co-existence with FastAPI:** Mount the MCP ASGI sub-app directly into the existing FastAPI app — one
process, one port (8001), no separate container or port.

```python
# backend/main.py addition
from fastmcp import FastMCP
from contextlib import asynccontextmanager

mcp = FastMCP("monai")

# Register tools
@mcp.tool()
def spending_total(period: str) -> dict: ...

mcp_app = mcp.http_app(transport="streamable-http", path="/")

@asynccontextmanager
async def lifespan(app):
    async with mcp_app.lifespan(app):
        yield

app = FastAPI(lifespan=lifespan)
app.mount("/mcp", mcp_app)
```

**IMPORTANT — lifespan wiring:** FastMCP 3.x requires you to pass `mcp_app.lifespan` as the FastAPI lifespan
(or combine with your existing lifespan using `fastmcp.utilities.combine_lifespans`). Failing to do this causes
`RuntimeError: Task group is not initialized`. This was an open issue in September 2025 and is now documented
as the correct pattern in FastMCP 3.x.

**Read-only vs read-write scoping:** FastMCP does not have built-in per-transport tool ACLs. Implement this
by registering two FastMCP instances: `mcp_internal` (all tools including write) and `mcp_external`
(read-only tools only), mounted at different paths (`/mcp/internal` and `/mcp`). The internal agent calls
`/mcp/internal`; Claude Desktop / IDE clients get `/mcp`.

### Core Libraries

| Library | Version | Purpose | Why |
|---------|---------|---------|-----|
| `fastmcp` | `>=3.4.2` | MCP server framework | Official Pythonic MCP wrapper; handles protocol, tool registration, transport |
| `mcp` | `>=1.28.0` (transitive) | MCP protocol SDK | FastMCP depends on it; stay on v1.x until v2 stable (2026-07-27) |

### What NOT to use

| Avoid | Why |
|-------|-----|
| Bare `mcp` SDK (no FastMCP) | 3-5x more boilerplate; FastMCP is the recommended abstraction layer |
| stdio transport for web | stdio is for local process-to-process (Claude Desktop direct); Streamable HTTP is correct for a network server |
| SSE transport | Superseded by Streamable HTTP in MCP spec 2025-03-26; still works but deprecated direction |
| Separate container for MCP | Unnecessary complexity; ASGI mount is single-process, single-port |

---

## 3. Investment Live Prices — Per Asset Class

### 3a. IDX (Indonesia Stock Exchange) Stocks — MEDIUM confidence

**The honest situation:** IDX lacks a reliable, free, officially-sanctioned price API. The options are:

| Option | Free Tier | Reliability | Verdict |
|--------|-----------|-------------|---------|
| `yfinance` (Yahoo Finance scraper) | Yes, unlimited | FRAGILE — Yahoo redesigned in Feb 2025; scraping breaks without notice; IDX tickers use `.JK` suffix (e.g. `BBCA.JK`) | Use for MVP only; expect breakage |
| Sectors.app | Limited free tier; paid from unspecified price | End-of-day IDX data, 99% coverage, designed for Indonesia | Best option if free tier sufficient; check `sectors.app/api` |
| OHLC.dev | Paid | Real-time IDX via Redis cache | Production quality; not free |
| Invezgo | Paid | Real-time IDX REST API | Production quality; not free |
| IDX official data services | Paid subscription | Official source | Enterprise pricing, not viable for self-hosted personal use |
| Twelve Data | Free tier: 8 req/min, 800/day | Covers IDX but not comprehensive | Viable for small portfolios |

**Recommended for MVP:** Use `yfinance` (`.JK` tickers) with explicit fallback to last-known price.
`pip install yfinance` — accepts `BBCA.JK`, `TLKM.JK` etc. Wrap every call in try/except and store
`last_fetched_at` + `last_known_price` on the `holdings` row. Surface staleness to the user in the UI
(`"Price as of [date]"` badge).

**Recommended for production quality:** Evaluate Sectors.app free tier. If it covers your holdings and
the free quota is adequate for a personal single-user app (price refreshes once/day would cost ~N holdings
calls/day), Sectors is the best-maintained IDX source.

| Library | Version | Purpose |
|---------|---------|---------|
| `yfinance` | `>=0.2.50` | IDX + US/global stock prices (.JK tickers); free, fragile |
| `httpx` | `>=0.27.0` (already likely transitive) | Sectors.app / OHLC.dev / Twelve Data REST calls |

### 3b. Crypto — HIGH confidence

**Use CoinGecko Demo (free) API.**

- Free tier (Demo plan): 10,000 calls/month, ~30 calls/min (conservative; docs say "up to 100 calls/min")
- Registration required for API key; free
- Covers all major coins by CoinGecko ID (e.g. `bitcoin`, `ethereum`, `binancecoin`)
- Endpoint: `GET /simple/price?ids={coin_ids}&vs_currencies=idr`
- Single-user personal app at once-per-page-load or once-per-day refresh will never hit 10K/month

| Library | Version | Purpose |
|---------|---------|---------|
| `httpx` | `>=0.27.0` | CoinGecko REST calls (async-compatible with FastAPI) |

No Python CoinGecko SDK is needed — the REST API is simple enough to call directly.

### 3c. Indonesian Mutual Funds (Reksadana) — LOW confidence; manual fallback required

**The honest situation:** There is no reliable, free, documented public API for Indonesian reksadana NAB
(Net Asset Value) data. The landscape as of June 2026:

| Option | Status | Notes |
|--------|--------|-------|
| Infovesta | Website only, no public API | Leading Indonesian fund data aggregator; no documented API; scraping fragile and ToS-prohibited |
| Bareksa | No public API | Similar to Infovesta |
| `bibit-reksadana` (GitHub: risan/bibit-reksadana) | Unofficial Bibit app scraper | Works by reverse-engineering Bibit's mobile API; no SLA, breaks with app updates; ToS grey area |
| OJK (Regulator) | No machine-readable price feed | OJK publishes fund data but not in a consumable API format |
| Sectors.app | Stocks/indices only; no reksadana coverage confirmed | Worth checking, but not documented for funds |

**Recommendation: manual last-known-price entry for reksadana holdings.** This is the correct
decision for a personal app where data integrity matters more than automation. The `holdings` schema
should include:

```sql
last_price        NUMERIC(20,4),
last_price_date   DATE,
price_source      TEXT   -- 'live_crypto' | 'live_idx' | 'manual'
```

The UI investment page shows price with source badge. The Settings page allows manual NAB entry per fund.
If the bibit-reksadana unofficial API works when tested against the user's specific funds, it can be wired
in behind the `price_source='live_reksadana'` code path — but it must fail gracefully and never block
the page render.

---

## 4. DB Migrations — Alembic

### Recommended: Alembic 1.18.x, autogenerate mode

| Library | Version | Why |
|---------|---------|-----|
| `alembic` | `>=1.18.4` | Standard SQLAlchemy migration tool; authored by same team; autogenerate diffs models→DB |

**Setup pattern for this codebase:**

```bash
pip install alembic>=1.18.4
alembic init alembic          # creates alembic/ dir + alembic.ini
```

`alembic/env.py` must import `Base` from `backend.models` and set `target_metadata = Base.metadata` for
autogenerate. Connect via the `DATABASE_URL` env var (same as FastAPI uses).

**Migration workflow:**
```bash
alembic revision --autogenerate -m "add holdings portfolio_events audit"
alembic upgrade head
```

**Startup behaviour:** Do NOT call `Base.metadata.create_all()` and `alembic upgrade head` simultaneously.
Replace the `init_db()` startup call with Alembic-managed migrations only. In development, running
`alembic upgrade head` manually or in the `db` service entrypoint is cleaner than auto-applying on every
startup. The existing `Base.metadata.create_all()` in `backend/db.py` must be removed or guarded once
Alembic is in place — otherwise schema drift is silent.

**What NOT to use:**

| Avoid | Why |
|-------|-----|
| Keep `Base.metadata.create_all()` alongside Alembic | Silent conflicts; Alembic won't detect columns created by `create_all` that differ from models |
| `aerich` (Tortoise ORM migrations) | Wrong ORM; this project uses SQLAlchemy |
| Manual `ALTER TABLE` scripts | No tracking, no rollback, no autogenerate |

---

## 5. Next.js Charting

### Recommended: Recharts 3.8.x

| Library | Version | Purpose | Why |
|---------|---------|---------|-----|
| `recharts` | `^3.8.1` | Line, bar, pie, area charts in React | Composable SVG components; zero canvas; full React 18 support; shadcn/ui-compatible; largest ecosystem |

```bash
npm install recharts
```

Recharts works with Next.js App Router and React 18 without configuration. The v3 API is stable
(v3.0 shipped with breaking changes from v2; v3.8.1 is the current stable as of March 2026).
No `"use client"` boundary issues — Recharts components are client components, which aligns with
the existing `"use client"` page architecture in `ui/app/page.tsx`.

**What NOT to use:**

| Avoid | Why |
|---------|-----|
| Chart.js / `react-chartjs-2` | Canvas-based; harder to style with Tailwind; worse TypeScript types |
| Victory | Smaller ecosystem; fewer chart types; less maintained in 2026 |
| D3 directly | Too low-level for this use case; high implementation cost for standard finance charts |
| Tremor (v3+) | Re-platformed to shadcn/ui paradigm; adds complexity if you're not already on that stack |

---

## Full Installation Summary

### Python (backend/requirements.txt additions)

```bash
# Agentic chat (upgrade existing llama-index-core)
llama-index-core>=0.14.0

# MCP server
fastmcp>=3.4.2

# Investment prices
yfinance>=0.2.50
httpx>=0.27.0        # for CoinGecko + optional Sectors.app calls

# DB migrations
alembic>=1.18.4
```

### Node (ui/)

```bash
npm install recharts
```

---

## Version Compatibility Notes

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| `llama-index-core>=0.14.0` | Existing `llama-index-llms-anthropic`, `llama-index-llms-openai`, `llama-index-llms-ollama` | Do NOT install `llama-index-agent-openai` — pins old `llms-openai` and conflicts |
| `fastmcp>=3.4.2` | FastAPI >=0.110.0 (existing) | Lifespan must be combined; see Section 2 for pattern |
| `recharts^3.8.1` | React 18 (existing) | Works; React 19 would need `react-is` override, but project is on React 18 |
| `alembic>=1.18.4` | SQLAlchemy >=2.0.0 (existing) | Full compatibility; autogenerate works with SQLAlchemy 2 declarative models |
| `yfinance>=0.2.50` | Python 3.12 (existing Docker runtime) | No conflicts; async not supported natively — call in FastAPI background task or executor |

---

## Confidence Assessment

| Area | Confidence | Basis |
|------|------------|-------|
| Agentic chat (LlamaIndex AgentWorkflow / FunctionAgent) | HIGH | Official LlamaIndex docs + PyPI version history confirmed; HITL pattern documented |
| MCP server (FastMCP 3.x, Streamable HTTP, FastAPI mount) | HIGH | FastMCP 3.4.2 confirmed on PyPI; mounting pattern in official FastMCP docs + May 2026 blog posts |
| Crypto prices (CoinGecko Demo) | HIGH | Official CoinGecko pricing page; rate limits confirmed |
| IDX stock prices (yfinance .JK + Sectors.app evaluation) | MEDIUM | yfinance reliability issues documented (Feb 2025 Yahoo redesign); Sectors.app coverage confirmed for IDX but free tier details require verification at sectors.app |
| Reksadana prices | LOW | No reliable free API exists; manual fallback is the honest recommendation; bibit-reksadana is unofficial and fragile |
| Alembic | HIGH | Version 1.18.4 confirmed on PyPI; standard FastAPI+SQLAlchemy 2 pattern well-documented |
| Recharts | HIGH | Version 3.8.1 confirmed on npm; React 18 compatibility confirmed |

---

## Sources

- [LlamaIndex Agents docs](https://developers.llamaindex.ai/python/framework/module_guides/deploying/agents/) — FunctionAgent, AgentWorkflow, deprecation of AgentRunner/FunctionCallingAgentWorker
- [LlamaIndex HITL docs](https://developers.llamaindex.ai/python/framework/understanding/agent/human_in_the_loop/) — InputRequiredEvent, HumanResponseEvent pattern
- [llama-index-core PyPI](https://pypi.org/project/llama-index-core/) — version history: 0.14.22 as latest (May 2026)
- [FastMCP docs: FastAPI integration](https://gofastmcp.com/integrations/fastapi) — mounting, lifespan, transport options
- [fastmcp PyPI](https://pypi.org/project/fastmcp/) — version 3.4.2, released June 6 2026
- [mcp PyPI](https://pypi.org/project/mcp/) — version 1.28.0 current; v2 alpha targeting 2026-07-27
- [CoinGecko API pricing](https://www.coingecko.com/en/api/pricing) — Demo plan: 10K calls/month, ~30-100 calls/min, free
- [alembic PyPI](https://pypi.org/project/alembic/) — version 1.18.4, released Feb 10 2026
- [recharts npm](https://www.npmjs.com/package/recharts) — version 3.8.1 confirmed
- [yfinance reliability article](https://medium.com/@trading.dude/why-yfinance-keeps-getting-blocked-and-what-to-use-instead-92d84bb2cc01) — Feb 2025 Yahoo redesign breakage documented
- [Sectors.app](https://sectors.app/) — IDX API coverage; free tier unconfirmed (verify directly)
- WebSearch (LOW confidence) — reksadana API landscape; confirms no reliable free source exists

---
*Stack research for: monai — agentic chat, MCP server, investment prices, Alembic, charting*
*Researched: 2026-06-21*
