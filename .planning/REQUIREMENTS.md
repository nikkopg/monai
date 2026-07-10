# Requirements: monai

**Defined:** 2026-06-21
**Core Value:** You can understand and manage your entire financial life — spending and investments — by talking to a trustworthy AI that never fabricates a number and never changes your data without your say-so.

## v1 Requirements

Requirements for this cycle. Each maps to a roadmap phase.

### Foundation & Safety

- [x] **FND-01**: Database schema changes are applied via Alembic migrations, preserving existing data (no destructive `create_all` on populated tables)
- [x] **FND-02**: All API endpoints require a configurable API key (`MONAI_API_KEY`); requests without a valid key are rejected
- [x] **FND-03**: New write paths and money math use `Decimal` end-to-end (no float in transit for amounts they touch)

### Agentic Chat

- [x] **CHAT-01**: User's question is answered by a multi-step reasoning agent that can plan and chain multiple tools within a single turn
- [x] **CHAT-02**: The agent only invokes the fixed parameterized tools — it never emits raw SQL (correctness-by-construction preserved)
- [ ] **CHAT-03**: User can ask spending↔portfolio correlation questions (e.g. "since I bought NVDA, how has my eating-out spending changed?")
- [x] **CHAT-04**: When the agent intends to change data, it shows the exact proposed change and writes nothing until the user approves it in the UI
- [x] **CHAT-05**: An approval is bound to that exact proposed operation — single-use and operation-scoped (not a reusable session-level "yes")
- [x] **CHAT-06**: Every applied write is recorded in an audit log (what changed, old→new, when)
- [x] **CHAT-07**: Through the chat (via the confirm flow) the user can add, edit, and delete transactions, accounts, categories, and holdings
- [x] **CHAT-08**: When the agent cannot map a request to a tool, it says so honestly rather than fabricating an answer

### MCP Server

- [ ] **MCP-01**: monai exposes its finance tools via a single MCP server
- [ ] **MCP-02**: The web chat agent and external MCP clients share the same underlying tool implementations (one source of truth)
- [ ] **MCP-03**: External MCP clients can use read/query tools only; write tools are not exposed to external clients
- [ ] **MCP-04**: External MCP clients must authenticate before using the server

### Cashflow Tracker

- [x] **CASH-01**: Dashboard shows a spending/income overview (totals, spending-by-category, income vs expense) with charts
- [x] **CASH-02**: Dashboard shows a month-over-month spending trend
- [x] **CASH-03**: Dashboard shows per-account balances
- [x] **CASH-04**: User can create, edit, and delete transactions in the UI
- [x] **CASH-05**: User can create, edit, and delete accounts in the UI
- [x] **CASH-06**: User can rename a category, remapping the affected transactions
- [x] **CASH-07**: User can merge one category into another
- [x] **CASH-08**: User can upload a Wallet CSV from the UI and see the import result (parsed/inserted/skipped)

### Investments

- [x] **INV-01**: User can add, edit, and remove holdings (ticker, quantity, avg cost, purchase date, currency)
- [ ] **INV-02**: System fetches current market prices for crypto holdings
- [ ] **INV-03**: System fetches current market prices for IDX stock holdings (best-effort, with fallback)
- [ ] **INV-04**: User can manually set/override a holding's price (required fallback for mutual funds and no-API instruments)
- [ ] **INV-05**: Each displayed price shows its as-of time and a staleness indicator
- [ ] **INV-06**: Investment page shows current portfolio value and per-holding profit/loss
- [ ] **INV-07**: Portfolio events (buys/sells) are recorded, enabling correlation queries

### Pages & Settings

- [ ] **UI-01**: App has distinct Chat, Cashflow, Investment, and Settings pages
- [ ] **UI-02**: Shared navigation lets the user move between all pages
- [ ] **UI-03**: Settings page lets the user configure the LLM provider/model and API keys in-UI
- [ ] **UI-04**: Settings page lets the user configure base currency and the price data source

## v2 Requirements

Acknowledged but deferred — not in this cycle's roadmap.

### Advanced Query Tools

- **QRY-01**: Recurring-charge / subscription detection
- **QRY-02**: Compare two arbitrary periods side by side
- **QRY-03**: Token-by-token streaming of agent responses (SSE/WebSocket)

### Investments+

- **INVX-01**: Historical portfolio value over time (not just current snapshot)
- **INVX-02**: Automated reksadana NAV feed (if a reliable source emerges)

## Out of Scope

Explicitly excluded — recorded to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Multi-user / auth roles | Single-user self-hosted app by design |
| Bank sync / aggregation | PCI scope, out of project goals |
| Budget / envelope tracking | Not core to the spending+investment AI value |
| Multi-currency normalization (`base_currency`/`fx_rate`) | Parked; 0/5608 rows skipped, single-currency IDR holds |
| Agent free-form SQL generation | Reintroduces the confident-wrong-number risk that caused the tool-router pivot |
| Write tools over MCP to external clients | Writes stay behind the web app's confirmation UI this cycle |
| Public v2 / open-source release (CI, Docker Hub) | Defer until this cycle is in daily use |
| Weather correlation, AI market-news filtering | Recorded non-goals from prior design |

## Traceability

Which phases cover which requirements. Populated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| FND-01 | Phase 1: Schema Foundation + Auth | Complete |
| FND-02 | Phase 1: Schema Foundation + Auth | Complete |
| FND-03 | Phase 1: Schema Foundation + Auth | Complete |
| CHAT-01 | Phase 2: Agentic Loop + Confirm-Before-Write | Complete |
| CHAT-02 | Phase 2: Agentic Loop + Confirm-Before-Write | Complete |
| CHAT-04 | Phase 2: Agentic Loop + Confirm-Before-Write | Complete |
| CHAT-05 | Phase 2: Agentic Loop + Confirm-Before-Write | Complete |
| CHAT-06 | Phase 2: Agentic Loop + Confirm-Before-Write | Complete |
| CHAT-07 | Phase 2: Agentic Loop + Confirm-Before-Write | Complete |
| CHAT-08 | Phase 2: Agentic Loop + Confirm-Before-Write | Complete |
| UI-01 | Phase 3: Multi-Page UI Shell + Settings | Pending |
| UI-02 | Phase 3: Multi-Page UI Shell + Settings | Pending |
| UI-03 | Phase 3: Multi-Page UI Shell + Settings | Pending |
| UI-04 | Phase 3: Multi-Page UI Shell + Settings | Pending |
| CASH-01 | Phase 4: Cashflow Dashboard + CRUD | Complete |
| CASH-02 | Phase 4: Cashflow Dashboard + CRUD | Complete |
| CASH-03 | Phase 4: Cashflow Dashboard + CRUD | Complete |
| CASH-04 | Phase 4: Cashflow Dashboard + CRUD | Complete |
| CASH-05 | Phase 4: Cashflow Dashboard + CRUD | Complete |
| CASH-06 | Phase 4: Cashflow Dashboard + CRUD | Complete |
| CASH-07 | Phase 4: Cashflow Dashboard + CRUD | Complete |
| CASH-08 | Phase 4: Cashflow Dashboard + CRUD | Complete |
| INV-01 | Phase 5: Investment Subsystem | In Progress |
| INV-02 | Phase 5: Investment Subsystem | In Progress |
| INV-03 | Phase 5: Investment Subsystem | In Progress |
| INV-04 | Phase 5: Investment Subsystem | In Progress |
| INV-05 | Phase 5: Investment Subsystem | In Progress |
| INV-06 | Phase 5: Investment Subsystem | In Progress |
| INV-07 | Phase 5: Investment Subsystem | In Progress |
| CHAT-03 | Phase 5: Investment Subsystem | Pending |
| MCP-01 | Phase 6: MCP Server | Pending |
| MCP-02 | Phase 6: MCP Server | Pending |
| MCP-03 | Phase 6: MCP Server | Pending |
| MCP-04 | Phase 6: MCP Server | Pending |

**Coverage:**

- v1 requirements: 30 total
- Mapped to phases: 30
- Unmapped: 0

---
*Requirements defined: 2026-06-21*
*Last updated: 2026-06-21 — traceability populated after roadmap creation*
