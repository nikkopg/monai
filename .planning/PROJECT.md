# monai

## What This Is

monai is a self-hosted, single-user personal-finance app with a conversational AI
layer over your own spending and investment data. It imports Wallet (BudgetBakers)
CSV exports into PostgreSQL and lets you ask questions — and now *act* — in natural
language. This cycle turns it into a real multi-page app (cashflow, investments,
chat, settings) with an **agentic** chat that can both read and safely edit your
data, exposed as an MCP server for use from external clients too.

## Core Value

You can understand and manage your entire financial life — spending and investments —
by talking to a trustworthy AI that never fabricates a number and never changes your
data without your say-so.

## Requirements

### Validated

<!-- Shipped and confirmed valuable (inferred from existing codebase). -->

- ✓ Import Wallet (BudgetBakers) CSV into PostgreSQL — existing (validated on 5608 rows / 5 yrs)
- ✓ AI query layer via tool router — LLM picks one parameterized tool, never writes SQL — existing
- ✓ 9 read tools: spending/income/net totals, by-category, in-category, counts, largest, avg daily, list categories — existing
- ✓ Manual transaction entry (`POST /transactions`) — existing
- ✓ Single-page Next.js UI (ask box, entry form, recent list) — existing
- ✓ Multi-provider LLM config (Ollama / Claude / OpenAI) — existing
- ✓ Full Docker Compose stack (Postgres + FastAPI + Next.js) — existing
- ✓ Honest-refusal failure philosophy (refuse > confident wrong number) — existing
- ✓ Alembic-managed schema (non-destructive on live data) + 5 forward-looking tables (audit_log, proposals, holdings, portfolio_events, price_cache) + Decimal money type + API-key auth on write endpoints with server-side Next.js proxy — validated in Phase 1 (FND-01/02/03)

### Active

<!-- This cycle's scope. Hypotheses until shipped and validated. -->

**Agentic chat + MCP**
- [ ] Chat is agentic: a multi-step reasoning loop that plans, chains multiple tools, and reflects over results
- [ ] Agent uses only safe parameterized tools — no free-form SQL (correctness-by-construction preserved)
- [ ] Agent can answer spending↔portfolio correlation questions (e.g. "since I bought X, how has my eating-out changed?")
- [ ] Agent can perform write actions: add/edit/delete transactions, accounts, categories, holdings
- [ ] Every write is **confirm-before-applying**: agent proposes the exact change, nothing is written until the user approves in the UI
- [ ] Writes are validated and recorded in an audit log
- [ ] All tools exposed via a single MCP server
- [ ] MCP server powers both the web chat and external MCP clients (Claude Desktop / IDE)
- [ ] External MCP clients get read/query tools only; write tools are web-app-only

**Cashflow tracker**
- [ ] Dashboard: spending/income overview with charts and summaries
- [ ] Full CRUD on transactions (create, edit, delete) in the UI
- [ ] Account management (view, create, edit, delete) in the UI
- [ ] Category management (view, rename, merge) in the UI
- [ ] CSV import available from the UI (file upload)

**Investments**
- [ ] Holdings management: insert / edit / remove holdings (ticker, quantity, avg cost, purchase date, currency)
- [ ] Fetch current live market prices for held instruments
- [ ] Show current portfolio value and per-holding P&L
- [ ] Cover IDX stocks, crypto, and mutual funds / other instruments
- [ ] Manual / last-known-price fallback for instruments without a live price source

**Pages & navigation**
- [ ] Distinct pages: Chat, Cashflow, Investment, Settings
- [ ] Shared navigation across pages
- [ ] Settings page exposes configurable parameters in-UI (LLM provider/model, API keys, base currency, price data source)

### Out of Scope

<!-- Explicit boundaries with reasoning to prevent re-adding. -->

- Multi-user / accounts & permissions — single-user self-hosted app by design
- Bank sync / aggregation — PCI scope, out of project goals
- Budget/envelope tracking — not core to the spending+investment AI value
- Multi-currency normalization (`base_currency`/`fx_rate`) — parked; 0/5608 rows skipped, single-currency IDR holds. Revisit only if a foreign-currency account is added
- Weather correlation, AI market-news filtering — recorded as non-goals in prior design
- Public v2 / open-source release (CI, Docker Hub, public README) — defer until this cycle is in daily use
- Agent free-form SQL generation — deliberately excluded; reintroduces confident-wrong-number risk that caused the original tool-router pivot
- Write tools over MCP to external clients — writes stay in the web app this cycle

## Context

- **Brownfield.** Two implementations exist: `poc/` (Approach A — SQLite + Streamlit + LlamaIndex NL-to-SQL, throwaway, slated for deletion) and `backend/` + `ui/` (Approach C — the production vertical slice this cycle builds on).
- **The tool-router pivot is load-bearing.** Naive `NLSQLTableQueryEngine` produced confident wrong numbers on the real dataset (wrong year, income counted as spending, `type` vs `category` confusion). The agentic chat must preserve "LLM never writes SQL" — it reasons over and chains a fixed set of hand-written, tested tools.
- **Data scale validated:** 5608 rows / 5 years / single currency (IDR), 0 rows skipped.
- **Codebase map exists** at `.planning/codebase/` (ARCHITECTURE, STACK, STRUCTURE, CONCERNS, CONVENTIONS, INTEGRATIONS, TESTING). Root `ARCHITECTURE.md` is the project decision log; `TODOS.md` is the live backlog.
- **Known issues to address / be aware of:** no DB migration tooling (schema changes need a migration story now that holdings/portfolio tables are added); money is floated in transit despite `Numeric` storage; LAN-exposed API with no auth (`network_mode: host`); LLM is a hard runtime dependency with no fallback; stale README.
- **Open research item:** live price data source for IDX stocks and Indonesian mutual funds (reksadana) is uncertain — free APIs cover these poorly. Crypto is well-served (e.g. CoinGecko). Manual/last-known-price entry is the fallback.

## Constraints

- **Tech stack**: FastAPI + PostgreSQL + Next.js (App Router) — established Approach C stack; build on it, don't re-platform
- **AI**: LlamaIndex abstraction with multi-provider config (Ollama local default / Claude / OpenAI) — agentic loop should build on this
- **Architecture**: Correctness-by-construction — the LLM selects/chains parameterized tools; it never emits SQL
- **Safety**: All agent writes require explicit user confirmation before applying; validated; audit-logged
- **Deployment**: Self-hosted via Docker Compose; single-user; local-first / privacy-respecting
- **Schema**: New `holdings` and `portfolio_events` tables + any column additions need a migration story (no Alembic today)
- **Currency**: Single-currency (IDR) assumption holds for spending; investments may span instruments/currencies

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Agent reasons + chains *safe parameterized tools* only (no free SQL) | Preserves the correctness-by-construction win from the original tool-router pivot | — Pending |
| Agent writes use confirm-before-applying (human-in-the-loop) + audit log | Money app: never mutate user data without explicit approval | — Pending |
| One MCP server powers web chat + external clients | Single tool surface, reusable from Claude Desktop/IDE | — Pending |
| External MCP clients get read tools only; writes web-app-only | Keep destructive actions behind the app's confirmation UI; smaller attack surface | — Pending |
| Spending↔portfolio correlation queries included (via chat) | The documented differentiator; agentic loop makes it natural | — Pending |
| Investments cover IDX / crypto / mutual funds with manual price fallback | Matches the user's actual portfolio; IDX/reksadana lack reliable free price APIs | — Pending |
| Settings page for in-UI configuration | Easier setup without editing env vars | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-06-21 — Phase 1 (Schema Foundation + Auth) complete*
