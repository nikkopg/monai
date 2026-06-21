# Project Research Summary

**Project:** monai
**Domain:** Self-hosted single-user agentic personal-finance app (cashflow + investments + MCP server)
**Researched:** 2026-06-21
**Confidence:** HIGH (core stack, architecture, agent patterns, Alembic, charting) / MEDIUM (IDX prices) / LOW (reksadana prices)

## Executive Summary

monai is a brownfield FastAPI + PostgreSQL + Next.js personal-finance app being extended into a full agentic application with write capability, investment tracking, multi-page UI, and an MCP server. The established tool-router philosophy — LLM selects parameterized tools, never emits SQL — is load-bearing and must be carried through the agentic upgrade. All four research streams converge on the same build order: Alembic schema migrations first, then the agentic loop with confirm-before-write, then the multi-page UI, then the investment subsystem, and finally the MCP server as a thin wrapper over the already-proven tool registry.

The single biggest structural risk is **schema migration**: the existing `Base.metadata.create_all()` is a silent no-op on any column or table added to an existing Postgres volume. Alembic must be introduced before any new table (holdings, proposals, audit_log, price_cache) is defined. The second load-bearing safety requirement is **confirm-before-write**: every agent-initiated write must go through a backend-persisted `proposals` table with a single-use token scoped to the exact proposed operation — not a session-level or reusable approval. Shipping write tools without this gate is not an option.

Price data is the highest-uncertainty area. CoinGecko (crypto) is solid and free. IDX stocks via yfinance are fragile but viable for MVP; Sectors.app is the production-quality IDX option pending free-tier confirmation. Indonesian reksadana has **no reliable free API** — manual last-known-price entry with a `fetched_at` + `price_source` staleness model is mandatory from day one, not a later refinement. All three price sources must store `fetched_at` and display freshness to the user; displaying a bare price number without provenance destroys trust in a money app.

## Key Findings

### Recommended Stack

The existing stack (FastAPI, PostgreSQL 16, SQLAlchemy 2 / psycopg3, Next.js 14.2 / React 18, LlamaIndex Core) is retained without re-platforming. All additions are additive packages.

The agentic layer requires upgrading `llama-index-core` to `>=0.14.0` and using `AgentWorkflow` + `FunctionAgent` — the current LlamaIndex-endorsed pattern. `AgentRunner` and `FunctionCallingAgentWorker` are **explicitly deprecated and removed** in the 0.14 line. Do not install `llama-index-agent-openai` — it pins old versions and causes dependency conflicts. Human-in-the-loop is implemented via `InputRequiredEvent` / `HumanResponseEvent` from `llama_index.core.workflow`, which suspends the workflow until the user responds.

The MCP server uses **FastMCP 3.4.2** (the official Pythonic MCP wrapper), mounted as an ASGI sub-app inside the existing FastAPI process at `/mcp` — one process, one port, no separate container. The Streamable HTTP transport (not SSE, not stdio) is the current MCP spec-recommended production transport. FastMCP 3.x requires its `lifespan` to be combined with FastAPI's lifespan or a `RuntimeError` at startup will result.

**Core technologies:**
- `llama-index-core>=0.14.0`: `AgentWorkflow` + `FunctionAgent` + `InputRequiredEvent` / `HumanResponseEvent` — all agent and HITL primitives; no separate agent package needed
- `fastmcp>=3.4.2`: MCP server; ASGI-mounted inside FastAPI; Streamable HTTP transport; one process/port
- `alembic>=1.18.4`: schema migration — required before any new table is created; replaces `create_all`
- `yfinance>=0.2.50`: IDX stock prices (`.JK` tickers); fragile but free; wrap every call in try/except
- `httpx>=0.27.0`: CoinGecko REST calls (async-compatible); also for Sectors.app if adopted
- `recharts^3.8.1`: React 18-compatible SVG charts (line, bar, donut); shadcn/ui-compatible; no canvas
- No new package needed for reksadana — manual price entry is the correct choice

### Expected Features

All four research areas agree on the feature scope and prioritization. The app has four surfaces: Cashflow Dashboard, Investment Tracker, Agentic Chat, and Settings.

**Must have (table stakes):**
- Alembic migration baseline — prerequisite for everything else
- API key auth (`MONAI_API_KEY`) on all write endpoints — prerequisite for write tools
- Overview cards (income, expenses, net, account balances) — every finance app leads with this
- Spending-by-category donut chart + income vs expense monthly bar chart — canonical finance visualizations
- Transaction edit + delete (PUT/DELETE endpoints + inline UI) — users correct import errors constantly
- Account CRUD — prerequisite for correct categorization
- Category rename + merge — Wallet CSV categories are verbose; rename is prerequisite for merge
- CSV upload from UI — without this, new installs require manual scripts
- Holdings CRUD (ticker, quantity, avg cost, purchase date, currency, asset_type) — minimum viable investment tracker
- Holdings table: current price, P&L, P&L%, portfolio total — derived from holdings x prices
- `portfolio_events` log (buy/sell/dividend) — prerequisite for correlation queries
- Manual / last-known-price fallback with `fetched_at` + `price_source` — mandatory for IDX and reksadana
- Agentic multi-step loop (`AgentWorkflow` + `FunctionAgent`)
- Confirm-before-write with backend-persisted `proposals` table + single-use token — non-negotiable safety gate
- Audit log of applied writes — required for user trust
- Read tools across both spending and investment domains
- NL writes: add/edit/delete transaction, add/edit/delete holding (through proposal flow)
- Settings page: LLM provider/model, API keys, price data source, Ollama base URL

**Should have (differentiators):**
- Spending + investment correlation queries ("since I bought BBCA, how has eating-out changed?") — the documented differentiator; no other self-hosted tool does this
- Streaming / incremental chat response display — multi-step agent chains look like hangs without it
- Holdings CSV import — faster than manual entry for existing portfolios
- MCP server for external clients (Claude Desktop / IDE) — read tools only; unique in self-hosted finance
- CoinGecko live price adapter (crypto) — well-served by free API

**Defer (v2+):**
- Write tools over MCP to external clients — external clients get read-only tools this cycle
- Richer trend tools: recurring-charge detection, period comparison, spend forecasting
- Sectors.app / Bibit price adapters — depends on API key availability and free tier confirmation
- Multi-currency normalization — 0/5608 rows are foreign-currency; not needed yet

**Anti-features (explicitly excluded):**
- Agent free-form SQL — reintroduces the confident-wrong-number failure mode
- Bank sync / Open Banking — PCI scope
- Multi-user — single-user self-hosted by design
- Budget/envelope tracking — YNAB does this better
- Real-time sub-minute price updates — no free API supports this for IDX; adds WebSocket complexity

### Architecture Approach

The architecture follows a five-component backend pattern where `tools.py` is the single source of truth shared by both the web agent and the MCP server — no logic duplication. The agent (`agent.py`) runs the `FunctionAgent` loop; write tools return `ProposalDict` rather than writing to the DB; `proposals.py` stores pending writes in Postgres with a UUID token and TTL; the confirm endpoint validates the token, executes the write inside a single transaction, and logs to `audit_log`. The MCP server (`mcp_server.py`) imports only read tools from `tools.py` and is mounted at `/mcp` inside FastAPI.

New tables: `proposals` (id, token, action, payload, preview, status, created_at, expires_at), `audit_log` (id, action, payload, source, proposal_id, committed_at), `holdings` (ticker, name, quantity, avg_cost, purchase_date, currency, asset_type, price_source, last_known_price, updated_at), `portfolio_events` (date, ticker, event_type, quantity, price, notes), `price_cache` (ticker, price, currency, source, fetched_at, ttl_seconds).

**Major components:**
1. `backend/tools.py` — single source of truth; pure functions; shared by agent loop and MCP server; no HTTP, no agent state
2. `backend/agent.py` — `FunctionAgent` + `AgentWorkflow` wrapper; write tools return `ProposalDict`, not DB writes
3. `backend/proposals.py` — `proposals` Postgres table + TTL + single-use token issuance and validation
4. `backend/price_service.py` — pluggable adapters per asset class (CoinGecko / yfinance / manual); `price_cache` table with per-source TTL
5. `backend/mcp_server.py` — FastMCP instance; read tools only; ASGI-mounted at `/mcp`
6. `backend/migrations/` — Alembic env + versioned migration files; `create_all` removed from `db.py`
7. `ui/app/` — four Next.js App Router pages (chat, cashflow, investments, settings) + shared Nav + ProposalBanner component

### Critical Pitfalls

All ten pitfalls in PITFALLS.md are project-specific and grounded in the existing codebase. The five most consequential:

1. **No Alembic — `create_all` silently no-ops on existing tables** — Add Alembic and generate the baseline migration before touching any schema. The `create_all` in `db.py` must be removed. Run `pg_dump` before every migration. This is the first task of the milestone, not a setup chore.

2. **API auth absent from write endpoints** — Add `MONAI_API_KEY` header check on all mutation endpoints (`POST`, `PUT`, `DELETE`, `PATCH`) before any write endpoint ships. Read endpoints can stay open. The current LAN-exposed unauthenticated API is acceptable for reads; it is a data-destruction risk for writes.

3. **Confirm token must be operation-scoped, not session-scoped** — The backend `proposals` table stores the exact `{action, payload}` hash; the confirm token is single-use and bound to that specific proposed operation. If the agent re-plans and arguments change, a new token is issued and the old one is invalidated. A session-level "user confirmed something" approval is not sufficient.

4. **Write tools must not directly mutate the DB** — Write tools in the agent context return a `ProposalDict`. The `proposals.confirm_proposal()` endpoint is the only code path that touches the DB for agent-initiated mutations. All writes in a confirmed bundle execute inside a single Postgres transaction — partial write + no rollback leaves data corrupt.

5. **Price staleness displayed as current** — Every price in `price_cache` and `holdings` must carry `fetched_at` and `price_source`. The UI must display "Price as of [date]" with a staleness badge when `now() - fetched_at` exceeds the per-instrument TTL (crypto 5 min, IDX stock 1 business day, reksadana 2 business days). A bare portfolio total with no timestamp destroys user trust.

Additional pitfalls to track: confirmation fatigue (show structured diff, not prose; delete requires explicit acknowledgment), prompt injection through note fields (sanitize tool output at the result boundary), MCP write tool accidental exposure (two explicit tool manifests: `READ_TOOLS` and `WRITE_TOOLS`; CI test that external client manifest contains zero write tools), float-in-transit on investment amounts (use `Decimal` in Pydantic; aggregate in Postgres, not Python), non-deterministic agent responses (temperature=0 for tool routing; `max_iterations=8`, `max_function_calls=12`; 10-question x 5-run determinism regression suite).

## Implications for Roadmap

The dependency graph across all four research files is unambiguous. The phase order below is not a suggestion — it is dictated by hard blockers.

### Phase 1: Schema Foundation + Auth

**Rationale:** Everything downstream (agent writes, investment tracking, price caching, audit trail) depends on tables that do not exist yet. `create_all` silently no-ops on them. Alembic must exist before any new model is defined. API auth must exist before any write endpoint ships. These two prerequisites cannot be deferred.

**Delivers:**
- Alembic initialized; baseline migration from existing schema; `create_all` removed from `db.py`
- Versioned migrations for: `audit_log`, `proposals`, `holdings`, `portfolio_events`, `price_cache`
- `MONAI_API_KEY` header check on all mutation endpoints (existing `POST /transactions` and all future write routes)
- `pg_dump` backup procedure documented

**Addresses:** FEATURES.md — all write features (blocked on proposals table); holdings, portfolio_events (blocked on schema)

**Avoids:** PITFALLS P7 (Alembic/create_all), P10 (LAN write access without auth)

**Research flag:** Standard patterns — skip research phase. Alembic + SQLAlchemy 2 is well-documented.

---

### Phase 2: Agentic Loop + Confirm-Before-Write

**Rationale:** The agent loop is the centerpiece of the milestone. It can be built and validated on read tools first (low risk), then write tools added once the proposal flow is proven. The existing `query.py` single-shot router is replaced. This phase must complete before the MCP server (Phase 5) because the MCP server wraps the same tool registry and correctness must be validated via the web UI before external exposure.

**Delivers:**
- `backend/agent.py`: `FunctionAgent` + `AgentWorkflow` wrapping existing 9 read tools; replaces `query.py` on the `/chat` endpoint
- `backend/proposals.py`: `create_proposal()`, `get_proposal()`, `confirm_proposal()`, `expire_proposals()` with Postgres-backed `proposals` table + UUID token + TTL
- `POST /proposals/{id}/confirm` and `DELETE /proposals/{id}` endpoints
- Write tool wrappers for add/edit/delete transaction (return `ProposalDict`, not DB mutations)
- `audit_log` writes on every confirmed proposal
- Determinism regression suite: 10 existing validated questions x 5 runs; same tool selection every run
- `temperature=0` enforced; `max_iterations=8`, `max_function_calls=12` set

**Uses:** `llama-index-core>=0.14.0`, `FunctionAgent`, `AgentWorkflow`, `InputRequiredEvent` / `HumanResponseEvent`

**Implements:** Pattern 2 (agentic loop), Pattern 3 (confirm-before-write flow)

**Avoids:** PITFALLS P1 (agent reasoning around safe tools), P2 (confirmation fatigue), P3 (partial writes), P4 (prompt injection), P9 (non-deterministic responses)

**Research flag:** Needs research phase. LlamaIndex 0.14 `AgentWorkflow` / `FunctionAgent` API is new; HITL via `InputRequiredEvent` has implementation nuances. SSE vs WebSocket streaming for HITL is an open question (see Gaps).

---

### Phase 3: Multi-Page UI

**Rationale:** Static page scaffolding (nav, routing, four page shells) does not depend on the agent being complete. The cashflow page wires existing CRUD endpoints. The chat page integrates the Phase 2 agent. ProposalBanner is the confirm-before-write UI. Investments page can show "no holdings yet" until Phase 4 delivers data.

**Delivers:**
- Shared `Nav.tsx` and root layout for `/chat`, `/cashflow`, `/investments`, `/settings` routes
- `ProposalBanner.tsx`: structured diff display (field | old value | new value); confirm/reject with 2-second delay enforced for destructive operations; token bound to exact operation
- Cashflow page: overview cards (income, expenses, net), spending-by-category donut, income vs expense monthly bar (Recharts), recent transactions table, inline edit/delete, CSV upload widget
- Chat page: message list with streaming display + ProposalBanner integration
- Settings page: LLM provider/model, API keys (masked), price data source selector, Ollama base URL
- Full transaction CRUD UI (edit/delete endpoints — PUT/DELETE `/transactions/{id}`)
- Account CRUD UI and endpoints
- Category rename + merge UI and endpoints

**Uses:** `recharts^3.8.1`

**Avoids:** PITFALLS P2 (confirmation fatigue — ProposalBanner shows structured diff, not prose)

**Research flag:** Standard patterns — skip research phase. Recharts + Next.js App Router is well-documented. ProposalBanner design is load-bearing UX; invest time here.

---

### Phase 4: Investment Subsystem

**Rationale:** Depends on schema from Phase 1 (holdings, portfolio_events, price_cache tables) and the multi-page UI from Phase 3 (Investments page shell). The price service abstraction must support pluggable adapters from the start — IDX, crypto, and reksadana require different fetch strategies and TTL policies.

**Delivers:**
- `backend/price_service.py`: `get_price(ticker)`, `refresh_prices()`; adapter registry with CoinGecko (crypto), yfinance (IDX fallback), and manual; `price_cache` upsert with per-instrument TTL
- Holdings CRUD endpoints (`GET/POST/PUT/DELETE /holdings`)
- New read tools in `tools.py`: `portfolio_value`, `holdings_list`, `get_holding_detail`, `portfolio_events_by_ticker`
- Write tools in `tools.py` (through proposal flow): `add_holding`, `edit_holding`, `delete_holding`
- Investments page wired to real data: holdings table with ticker, quantity, avg cost, current price, value, P&L, P&L%; portfolio total with timestamp
- Staleness badge: visual indicator on holdings where `now() - fetched_at > ttl`
- `portfolio_events` CRUD (buy/sell events; foundation for correlation queries)
- Holdings CSV import endpoint and UI
- Spending + investment correlation tool: `spending_by_event_window(ticker, event_type, category)` — joins portfolio event date with spending period
- All `amount`/`price`/`quantity`/`avg_cost` Pydantic fields changed from `float` to `Decimal`

**Avoids:** PITFALLS P6 (stale price displayed as current — `fetched_at` + TTL + staleness badge), P8 (float-in-transit — Decimal throughout)

**Research flag:** Needs research phase for IDX price source. Sectors.app free tier coverage and rate limits need direct verification. Ollama function-calling support question affects `FunctionAgent` vs `ReActAgent` choice. reksadana bibit-reksadana unofficial API should be tested against the user's specific funds before being wired in.

---

### Phase 5: MCP Server

**Rationale:** The MCP server is the final additive layer — it wraps the already-proven, already-tested tool registry from `tools.py`. It must come last because: (a) tool correctness is validated via the web UI first; (b) external client exposure of an unstable tool surface is a higher-risk surface to debug; (c) the read/write scope split must be enforced before any external client connects.

**Delivers:**
- `backend/mcp_server.py`: `FastMCP(name="monai")`; read tools registered from `READ_TOOLS` manifest; mounted at `/mcp` in `main.py`; Streamable HTTP transport; FastMCP lifespan combined with FastAPI lifespan
- `READ_TOOLS` and `WRITE_TOOLS` as explicit separate manifests; external handler imports only `READ_TOOLS`
- CI test: connect as external client, enumerate tools, assert zero write tools present
- `mcp.http_app(transport="streamable-http", path="/")` bound to `127.0.0.1` in production
- Correlation tools (`spending_by_event_window`) exposed via MCP for external clients
- Claude Desktop connection verified

**Uses:** `fastmcp>=3.4.2`, Streamable HTTP transport

**Implements:** Pattern 4 (MCP co-mounted in FastAPI)

**Avoids:** PITFALLS P5 (MCP write tools accidentally exposed — two explicit manifests + CI assertion)

**Research flag:** Standard patterns for FastMCP mounting. FastMCP 3.x lifespan wiring is documented but finicky — treat as medium-risk implementation.

---

### Phase Ordering Rationale

- **Alembic is a hard blocker.** Without it, adding any new table to an existing Docker volume is silent no-op or requires `docker compose down -v` (data destruction). Every subsequent phase adds tables.
- **Auth is a hard blocker for write endpoints.** The write capability fundamentally changes the risk surface; auth cannot be deferred even one phase.
- **Proposals table blocks write tools.** The confirm-before-write flow requires Postgres persistence — an in-memory dict loses proposals on restart.
- **Agent loop before MCP.** The MCP server wraps the agent's tool registry; correctness must be validated with the full proposal + audit flow before any external client connects.
- **UI (Phase 3) can overlap Phase 2.** Static page scaffolding (Nav, routing, page shells, Recharts charts) has no agent dependency. ProposalBanner needs the proposals endpoint from Phase 2 but can be built against a mock.
- **Investment subsystem (Phase 4) after UI shell.** The Investments page can ship as "no holdings yet" while the backend price service is being built.

### Research Flags

Phases needing deeper research during planning:
- **Phase 2:** LlamaIndex 0.14 `AgentWorkflow` / `FunctionAgent` API specifics; `InputRequiredEvent` / `HumanResponseEvent` HITL wiring; SSE vs WebSocket decision for streaming
- **Phase 4:** Sectors.app free tier coverage and quota for IDX (direct verification required); Ollama function-calling support (determines `FunctionAgent` vs `ReActAgent` for Ollama users); reksadana bibit-reksadana API availability test

Phases with standard patterns (skip research phase):
- **Phase 1:** Alembic + SQLAlchemy 2 is well-documented; standard FastAPI setup
- **Phase 3:** Recharts + Next.js App Router is well-documented; ProposalBanner is custom but straightforward
- **Phase 5:** FastMCP 3.x mounting pattern is documented; lifespan wiring is the only finicky part

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All packages confirmed on PyPI/npm with version numbers; LlamaIndex 0.14 API verified against official docs; FastMCP 3.4.2 released June 2026 |
| Features | HIGH | Validated against Firefly III, Ghostfolio, Wealthfolio; grounded in competitor analysis and PROJECT.md requirements |
| Architecture | HIGH | Existing codebase confirmed; patterns verified against LlamaIndex, FastMCP, and Alembic official docs; component boundaries are clear |
| Pitfalls | HIGH | Project-specific; grounded in direct codebase read (CONCERNS.md, existing code debt); MCP security grounded in OWASP docs |
| IDX Prices | MEDIUM | yfinance reliability issues documented; Sectors.app coverage not directly verified for free tier |
| Reksadana Prices | LOW | No reliable free API confirmed; manual fallback is the only safe choice; bibit-reksadana is unofficial and may break |

**Overall confidence:** HIGH for the core build; MEDIUM for the price data layer

### Gaps to Address

- **Ollama function-calling support:** `FunctionAgent` uses native tool-calling APIs. If the user's local Ollama model (gemma4 or similar) does not support function calling, Phase 2 must use `ReActAgent` instead. Verify against the specific model before Phase 2 planning. This is an open question from all four research streams.
- **IDX price source choice:** Sectors.app free tier quota and coverage for the user's specific IDX holdings must be verified directly at `sectors.app/api` before Phase 4. If free tier is insufficient, yfinance fallback is the only free option (fragile). This decision affects `price_service.py` adapter priority.
- **SSE vs WebSocket for HITL streaming:** The Phase 2 agent loop emits events (thinking steps, tool calls, `InputRequiredEvent` proposals) that need to stream to the Next.js frontend. LlamaIndex's HITL pattern works with SSE or WebSocket; FastAPI supports both. The choice affects the Phase 3 UI event listener. Recommendation: start with SSE (simpler, unidirectional, HTTP-native) and upgrade to WebSocket only if bidirectional mid-stream responses are needed. Decide before Phase 2 backend is built.
- **Sectors.app free tier:** Requires direct account creation + API test against `.JK` tickers to confirm coverage and quota before committing to it in Phase 4.

## Sources

### Primary (HIGH confidence)
- [LlamaIndex Agents docs](https://developers.llamaindex.ai/python/framework/module_guides/deploying/agents/) — `FunctionAgent`, `AgentWorkflow`, deprecation of `AgentRunner`/`FunctionCallingAgentWorker`
- [LlamaIndex HITL docs](https://developers.llamaindex.ai/python/framework/understanding/agent/human_in_the_loop/) — `InputRequiredEvent`, `HumanResponseEvent` pattern
- [llama-index-core PyPI](https://pypi.org/project/llama-index-core/) — version 0.14.22 confirmed (May 2026)
- [FastMCP docs: FastAPI integration](https://gofastmcp.com/integrations/fastapi) — mounting, lifespan, transport options
- [fastmcp PyPI](https://pypi.org/project/fastmcp/) — version 3.4.2 released June 6 2026
- [alembic PyPI](https://pypi.org/project/alembic/) — version 1.18.4 released Feb 10 2026
- [recharts npm](https://www.npmjs.com/package/recharts) — version 3.8.1 confirmed
- [CoinGecko API pricing](https://www.coingecko.com/en/api/pricing) — Demo plan: 10K calls/month, ~30-100 calls/min, free
- [OWASP MCP Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/MCP_Security_Cheat_Sheet.html) — tool poisoning, scope enforcement
- Project codebase: `.planning/codebase/CONCERNS.md`, `.planning/codebase/ARCHITECTURE.md` — existing debt and patterns
- [Smashing Magazine — Designing for Agentic AI: Practical UX Patterns](https://www.smashingmagazine.com/2026/02/designing-agentic-ai-practical-ux-patterns/) — confirm-before-write as canonical UX pattern

### Secondary (MEDIUM confidence)
- [Sectors.app](https://sectors.app/) — IDX API coverage confirmed for stocks; free tier quota unverified
- [yfinance reliability article](https://medium.com/@trading.dude/why-yfinance-keeps-getting-blocked-and-what-to-use-instead-92d84bb2cc01) — Feb 2025 Yahoo redesign breakage documented
- [Ghostfolio open-source wealth management](https://github.com/ghostfolio/ghostfolio) — competitor feature baseline
- [Wealthfolio open-source portfolio tracker](https://wealthfolio.app/) — competitor feature baseline
- [Alembic autogenerate](https://alembic.sqlalchemy.org/en/latest/autogenerate.html) — migration workflow

### Tertiary (LOW confidence)
- [Bibit Reksadana unofficial API](https://github.com/risan/bibit-reksadana) — reksadana NAV data; unofficial, no SLA, may break; use only as optional `price_source='live_reksadana'` code path with hard fallback
- WebSearch results on reksadana API landscape — confirms no reliable free source exists as of June 2026

---
*Research completed: 2026-06-21*
*Ready for roadmap: yes*
