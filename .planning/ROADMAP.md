# Roadmap: monai

**Project:** Self-hosted agentic personal-finance app (cashflow + investments + MCP server)
**Milestone:** Agentic Chat + Investments + Multi-page UI + MCP
**Granularity:** Standard (6 phases)
**Coverage:** 30/30 v1 requirements mapped
**Created:** 2026-06-21

---

## Phases

- [x] **Phase 1: Schema Foundation + Auth** - Alembic migrations, new tables, API key auth — unblocks everything downstream (completed 2026-06-21)
- [x] **Phase 2: Agentic Loop + Confirm-Before-Write** - Multi-step agent replaces single-shot router; write proposals with human approval gate (completed 2026-07-03)
- [x] **Phase 3: Multi-Page UI Shell + Settings** - Four-page navigation, Settings page; users can navigate and configure the app (completed 2026-07-04)
- [x] **Phase 4: Cashflow Dashboard + CRUD** - Spending/income dashboard with charts; full transaction/account/category management in UI (completed 2026-07-05)
- [ ] **Phase 5: Investment Subsystem** - Holdings CRUD, live prices, P&L display, portfolio events, and spending-correlation queries
- [ ] **Phase 6: MCP Server** - FastMCP server co-mounted in FastAPI; read-only tools exposed to external clients

---

## Phase Details

### Phase 1: Schema Foundation + Auth

**Goal**: The database schema is safe to evolve and all write endpoints are authenticated
**Mode:** mvp
**Depends on**: Nothing (first phase)
**Requirements**: FND-01, FND-02, FND-03
**Success Criteria** (what must be TRUE):

  1. Running `alembic upgrade head` on an existing Postgres volume applies new tables (`audit_log`, `proposals`, `holdings`, `portfolio_events`, `price_cache`) without destroying existing `transactions`/`accounts` data
  2. All `POST`, `PUT`, `DELETE`, `PATCH` endpoints return `401 Unauthorized` when the `MONAI_API_KEY` header is missing or wrong; existing read endpoints remain accessible
  3. Any new transaction, holding, or price amount flowing through the API is stored and returned as `Decimal` (no float rounding visible in responses)
  4. `Base.metadata.create_all()` has been removed from `db.py`; schema is fully Alembic-managed

**Plans**: 3 plans

- [x] 01-01-PLAN.md — Alembic introduction (baseline + stamp), 5 new tables + date_helpers view, Decimal storage, remove create_all
- [x] 01-02-PLAN.md — MONAI_API_KEY auth on write routes + server-side Next.js proxy injecting the key
- [x] 01-03-PLAN.md — MoneyDecimal type: Decimal-as-JSON-number serialization for transaction amounts

### Phase 2: Agentic Loop + Confirm-Before-Write

**Goal**: Users can ask multi-step financial questions and safely approve AI-proposed data changes
**Mode:** mvp
**Depends on**: Phase 1
**Requirements**: CHAT-01, CHAT-02, CHAT-04, CHAT-05, CHAT-06, CHAT-07, CHAT-08
**Success Criteria** (what must be TRUE):

  1. A question requiring two or more tool calls (e.g. "what was my net spending in the month before I got my last paycheck?") returns a synthesized answer, with tool calls visible in the response metadata
  2. The agent never emits a raw SQL string — all data access goes through the named tool registry; asking it to "run a SQL query" results in an honest refusal
  3. When the agent proposes a write (add/edit/delete transaction, account, category, or holding), a proposal record appears in the `proposals` table with a UUID token and TTL — no DB mutation has occurred yet
  4. Confirming a proposal via `POST /proposals/{id}/confirm` with the correct token executes the write, writes an `audit_log` row, and marks the proposal confirmed; a second confirm with the same token is rejected
  5. Rejecting or letting a proposal expire leaves the database unchanged
  6. When a question cannot be answered with available tools, the agent responds with an honest "I can't compute that" rather than fabricating a number

**Plans**: 3 plans

- [x] 02-01-PLAN.md — Async test infra + FunctionAgent multi-step read loop (CHAT-01/02/08)
- [x] 02-02-PLAN.md — propose_* write tools + confirm/reject/list endpoints with atomic write, audit, token guards (CHAT-04/05/06/07, D-06)
- [x] 02-03-PLAN.md — SSE /query-stream + proxy passthrough + inline ProposalCard UI with progressive steps, trace, diff, expiry (CHAT-01/04 surfacing) [completed 2026-07-03 — human verification surfaced 4 defects, all fixed as quick tasks 260703-fwr/gco/grn/ja8]

### Phase 3: Multi-Page UI Shell + Settings

**Goal**: Users can navigate between all pages of the app and configure it from the browser
**Mode:** mvp
**Depends on**: Phase 1
**Requirements**: UI-01, UI-02, UI-03, UI-04
**Success Criteria** (what must be TRUE):

  1. The app has four distinct routes — `/chat`, `/cashflow`, `/investments`, `/settings` — each rendering a unique page with no blank screen or 404
  2. A shared navigation component appears on every page and lets the user switch between all four pages without a full page reload
  3. The Settings page lets the user select an LLM provider and model, enter API keys (masked in display), and save the configuration — subsequent chat requests use the new provider
  4. The Settings page lets the user set base currency and the preferred price data source; the selection persists across browser sessions

**Plans**: 3/3 plans complete
**Wave 1**

- [x] 03-01-PLAN.md — Nav shell + route split (/chat, /cashflow, /investments, /settings) + Playwright smoke (UI-01, UI-02) [wave 1]
- [x] 03-02-PLAN.md — Settings persistence backend: app_settings migration, GET/PUT /settings, runtime LLM reconfigure, masked keys, audit (UI-03, UI-04) [wave 1]

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 03-03-PLAN.md — Settings page UI: three-card form, GET-on-load, per-card partial PUT (UI-03, UI-04) [wave 2, depends 03-01+03-02]

**UI hint**: yes

### Phase 4: Cashflow Dashboard + CRUD

**Goal**: Users can understand their spending and income at a glance, and manage transactions, accounts, and categories directly in the UI
**Mode:** mvp
**Depends on**: Phase 2, Phase 3
**Requirements**: CASH-01, CASH-02, CASH-03, CASH-04, CASH-05, CASH-06, CASH-07, CASH-08
**Success Criteria** (what must be TRUE):

  1. The Cashflow page shows a spending/income overview with total income, total expenses, net, per-account balances, a spending-by-category donut chart, and a month-over-month income vs expense bar chart — all populated from real data
  2. The Cashflow page shows a month-over-month spending trend (bar or line chart) covering at least 6 months of history
  3. A user can create a new transaction, edit an existing one, and delete one directly in the UI — changes reflect immediately without a page reload
  4. A user can create, edit, and delete accounts from the UI
  5. A user can rename a category (all affected transactions remapped) and merge one category into another from the UI
  6. A user can upload a Wallet CSV file from the UI and see the count of rows parsed, inserted, and skipped

**Plans**: 7 plans (2 gap-closure)

**Wave 1** *(parallel — no file overlap)*

- [x] 04-01-PLAN.md — Shared write helpers (backend/writes.py) + refactor _execute_proposal_payload to dispatch, regression-guarded (D-02) [wave 1]
- [x] 04-02-PLAN.md — Dashboard read aggregations (monthly_trend, account_balances) + new schemas + test scaffold (CASH-01/02/03) [wave 1]

**Wave 2** *(depends 04-01 + 04-02)*

- [x] 04-03-PLAN.md — Backend REST: GET /cashflow/summary, tx/account CRUD, reassign-then-delete, category rename/merge (CASH-01..07, D-01/05/06/08) [wave 2]

**Wave 3** *(depends 04-03)*

- [x] 04-04-PLAN.md — Frontend dashboard: Recharts install, 3 charts, summary/per-account/period-selector on /cashflow (CASH-01/02/03, D-04/07) [wave 3]

**Wave 4** *(depends 04-03 + 04-04)*

- [x] 04-05-PLAN.md — Frontend CRUD: TransactionModal, ConfirmDialog, AccountManager, CategoryManager, CsvUpload + refetch wiring (CASH-04..08, D-03/09/10) [wave 4]

**Wave 5** *(gap closure from 04-UAT.md — parallel, no file overlap)*

- [ ] 04-06-PLAN.md — Gap 1 (major): add this_week/last_week to PERIODS + resolve_period, ValueError→422 on /cashflow/summary, backend tests (CASH-01/02/03) [wave 5]
- [ ] 04-07-PLAN.md — Gap 2 (minor): TransactionModal category becomes a select from GET /categories with deliberate "+ New category…" affordance, e2e updates (CASH-04/06) [wave 5]

**UI hint**: yes

### Phase 5: Investment Subsystem

**Goal**: Users can track their portfolio, see current value and P&L with fresh prices, and ask correlation questions about spending and investments
**Mode:** mvp
**Depends on**: Phase 3, Phase 4
**Requirements**: INV-01, INV-02, INV-03, INV-04, INV-05, INV-06, INV-07, CHAT-03
**Success Criteria** (what must be TRUE):

  1. A user can add a holding (ticker, quantity, avg cost, purchase date, currency, asset type), edit it, and delete it from the Investments page
  2. The Investments page shows each holding's current price, current value, P&L (IDR), and P&L% — with a staleness badge showing "Price as of [date/time]" and a visual indicator when data is older than the per-instrument TTL
  3. Crypto holdings fetch live prices from CoinGecko; IDX stock holdings attempt a live fetch (yfinance/.JK with fallback); mutual funds and unresolvable tickers show the manually-set last known price
  4. A user can manually set or override any holding's price from the UI — the override is immediately reflected in P&L calculations
  5. The Investments page shows a total portfolio value figure with a corresponding "as of" timestamp
  6. Portfolio buy/sell events are recorded when holdings change, enabling the agent to answer: "since I bought BBCA, how has my eating-out spending changed?" with a number

**Plans**: TBD
**UI hint**: yes

### Phase 6: MCP Server

**Goal**: External MCP clients can query the app's finance data using the same tools the web agent uses
**Mode:** mvp
**Depends on**: Phase 2, Phase 5
**Requirements**: MCP-01, MCP-02, MCP-03, MCP-04
**Success Criteria** (what must be TRUE):

  1. An external MCP client (e.g. Claude Desktop) can connect to `http://host:8001/mcp` and enumerate the available tools — the tool list contains only read tools; zero write tools appear
  2. The external client can successfully call a read tool (e.g. spending total for last month) and receive the same result that the web chat agent would return for the same query
  3. Attempting to call a write tool (add transaction, edit holding) from the external client fails — the tool does not exist in the MCP server's registry
  4. The external client must provide a valid API key to use the MCP server; unauthenticated connections are rejected

**Plans**: TBD

---

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Schema Foundation + Auth | 3/3 | Complete   | 2026-06-21 |
| 2. Agentic Loop + Confirm-Before-Write | 2/3 | In Progress|  |
| 3. Multi-Page UI Shell + Settings | 3/3 | Complete   | 2026-07-04 |
| 4. Cashflow Dashboard + CRUD | 5/5 | Complete   | 2026-07-05 |
| 5. Investment Subsystem | 0/? | Not started | - |
| 6. MCP Server | 0/? | Not started | - |

---

## Coverage

| Requirement | Phase |
|-------------|-------|
| FND-01 | Phase 1 |
| FND-02 | Phase 1 |
| FND-03 | Phase 1 |
| CHAT-01 | Phase 2 |
| CHAT-02 | Phase 2 |
| CHAT-04 | Phase 2 |
| CHAT-05 | Phase 2 |
| CHAT-06 | Phase 2 |
| CHAT-07 | Phase 2 |
| CHAT-08 | Phase 2 |
| UI-01 | Phase 3 |
| UI-02 | Phase 3 |
| UI-03 | Phase 3 |
| UI-04 | Phase 3 |
| CASH-01 | Phase 4 |
| CASH-02 | Phase 4 |
| CASH-03 | Phase 4 |
| CASH-04 | Phase 4 |
| CASH-05 | Phase 4 |
| CASH-06 | Phase 4 |
| CASH-07 | Phase 4 |
| CASH-08 | Phase 4 |
| INV-01 | Phase 5 |
| INV-02 | Phase 5 |
| INV-03 | Phase 5 |
| INV-04 | Phase 5 |
| INV-05 | Phase 5 |
| INV-06 | Phase 5 |
| INV-07 | Phase 5 |
| CHAT-03 | Phase 5 |
| MCP-01 | Phase 6 |
| MCP-02 | Phase 6 |
| MCP-03 | Phase 6 |
| MCP-04 | Phase 6 |

All 30 v1 requirements mapped. No orphans.

---

## Research Flags

| Phase | Research Needed | Reason |
|-------|-----------------|--------|
| Phase 2 | Yes | LlamaIndex 0.14 `AgentWorkflow`/`FunctionAgent` API is new; `InputRequiredEvent`/`HumanResponseEvent` HITL wiring has implementation nuances; SSE vs WebSocket for streaming |
| Phase 5 | Yes | Sectors.app free tier coverage for IDX tickers requires direct verification; Ollama function-calling support determines `FunctionAgent` vs `ReActAgent` |
| All others | No | Standard patterns with well-documented APIs |

---
*Roadmap created: 2026-06-21*
*Last updated: 2026-06-21 after Phase 2 planning*
