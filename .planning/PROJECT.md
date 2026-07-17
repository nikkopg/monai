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

## Current Milestone: v1.1 UI Redesign — "Paper" Aesthetic

**Goal:** Re-skin all four pages + the nav shell to the Claude Design "paper" mockup — a warm editorial look — without changing any behavior, data, or endpoints.

**Target features (all visual; functionality preserved):**
- Design-token foundation (colors, Instrument Serif + Hanken Grotesk type, radii, spacing) driving `ui/app/styles.ts` as the single source of truth
- Nav shell restyle (left sidebar, serif wordmark, synced footer card)
- Cashflow page — dark net-worth hero, 6-month trend, stat cards, category donut, accounts list, recent transactions
- Chat page — user/assistant bubbles, collapsible tool-trace, proposal card, sticky composer
- Investments page — total-value hero, allocation donut, holdings table
- Settings page — provider segmented control, API-key + preferences cards, live-refresh toggle

**Key context:** Pixel-faithful to `.planning/design/monai-redesign.dc.html` (recreate the look, not the prototype's internals). Data stays real and IDR — the mockup's USD/fake numbers are illustrative. No backend, schema, or API changes; zero regressions to v1.0 behavior. Rollout is foundation-first: tokens → Nav → pages.

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
- ✓ Alembic-managed schema (non-destructive on live data) + 5 forward-looking tables (audit_log, proposals, holdings, portfolio_events, price_cache) + Decimal money type + API-key auth on write endpoints with server-side Next.js proxy — v1.0 (FND-01/02/03)
- ✓ Agentic chat: multi-step reasoning loop that plans and chains multiple safe parameterized tools, never emits SQL, refuses honestly — v1.0 (CHAT-01/02/08)
- ✓ Confirm-before-write agent edits (add/edit/delete transactions, accounts, categories, holdings) via single-use, operation-scoped proposal tokens + audit log — v1.0 (CHAT-04/05/06/07)
- ✓ Spending↔portfolio correlation queries via chat — v1.0 (CHAT-03)
- ✓ Single MCP server (FastMCP co-mounted in FastAPI) powering web chat + external clients; read-only tools to external clients, auth-required — v1.0 (MCP-01/02/03/04)
- ✓ Cashflow dashboard (totals, category donut, income-vs-expense, month trend, per-account balances) + full transaction/account CRUD + category rename/merge + CSV upload — v1.0 (CASH-01..08)
- ✓ Investment subsystem: holdings CRUD, live prices (CoinGecko/yfinance/manual fallback), staleness badges, portfolio value + per-holding P&L, portfolio events — v1.0 (INV-01..07)
- ✓ Multi-platform / multi-currency (USD→IDR) holdings, cash + physical-gold asset types, allocation pie + historical value/P&L charts — v1.0 (INVX-01, Phase 7)
- ✓ Four-page app (Chat / Cashflow / Investment / Settings) with shared nav; Settings configures LLM provider/model + API keys + base currency + price source in-UI — v1.0 (UI-01..04)

### Active

<!-- v1.1 scope: visual redesign only. See .planning/REQUIREMENTS.md for REQ-IDs. -->

- v1.1 UI Redesign ("paper" aesthetic) — design-token foundation + restyle of Nav and all four pages, pixel-faithful to the Claude Design mockup, functionality unchanged (UIR-* requirements).

Deferred v2 candidates (still out of this cycle): QRY-01 recurring-charge detection, QRY-02 compare two arbitrary periods, QRY-03 token-by-token streaming, INVX-02 automated reksadana NAV feed.

### Out of Scope

<!-- Explicit boundaries with reasoning to prevent re-adding. -->

- Multi-user / accounts & permissions — single-user self-hosted app by design
- Bank sync / aggregation — PCI scope, out of project goals
- Budget/envelope tracking — not core to the spending+investment AI value
- Multi-currency normalization for *spending* — single-currency IDR holds (0/5608 rows skipped). NOTE: *investment* multi-currency (USD→IDR conversion, native-currency cost basis) shipped in v1.0 Phase 7; spending stays IDR-only
- Weather correlation, AI market-news filtering — recorded as non-goals in prior design
- Public v2 / open-source release (CI, Docker Hub, public README) — defer until this cycle is in daily use
- Agent free-form SQL generation — deliberately excluded; reintroduces confident-wrong-number risk that caused the original tool-router pivot
- Write tools over MCP to external clients — writes stay in the web app this cycle

## Current State

**Shipped v1.0** (2026-07-17) — Phases 1-7, 30 plans, 35/35 requirements, milestone audit passed. monai is now a four-page agentic personal-finance app (chat / cashflow / investments / settings) with confirm-before-write agent edits, a live-priced multi-platform/multi-currency investment subsystem (cash + gold, allocation + historical charts), and a read-only MCP server for external clients. Stack: FastAPI + PostgreSQL (Alembic-managed) + Next.js, LlamaIndex FunctionAgent, FastMCP.

**Known non-blocking debt carried into v1.1:** `/mcp/` trailing-slash auth test suggested; `_execute_proposal_payload` delete_holding branch drift vs `writes.apply_delete_holding`; a few human-verify visual-only items (streaming ProposalCard render, staleness badge pixels, non-deterministic live-LLM tool selection) — backend contracts all verified programmatically.

**Next milestone goals (v1.1 — to be defined via `/gsd:new-milestone`):** candidates are the deferred v2 items — recurring-charge/subscription detection (QRY-01), arbitrary two-period comparison (QRY-02), token-by-token streaming (QRY-03), automated reksadana NAV feed (INVX-02) — plus paying down the debt above.

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
| Agent reasons + chains *safe parameterized tools* only (no free SQL) | Preserves the correctness-by-construction win from the original tool-router pivot | ✓ Good — v1.0 |
| Agent writes use confirm-before-applying (human-in-the-loop) + audit log | Money app: never mutate user data without explicit approval | ✓ Good — v1.0 (UUID+TTL single-use tokens) |
| One MCP server powers web chat + external clients | Single tool surface, reusable from Claude Desktop/IDE | ✓ Good — v1.0 (FastMCP co-mounted, live UAT 5/5) |
| External MCP clients get read tools only; writes web-app-only | Keep destructive actions behind the app's confirmation UI; smaller attack surface | ✓ Good — v1.0 |
| Spending↔portfolio correlation queries included (via chat) | The documented differentiator; agentic loop makes it natural | ✓ Good — v1.0 |
| Investments cover IDX / crypto / mutual funds with manual price fallback | Matches the user's actual portfolio; IDX/reksadana lack reliable free price APIs | ✓ Good — v1.0 |
| Settings page for in-UI configuration | Easier setup without editing env vars | ✓ Good — v1.0 |
| Holdings identity = `(ticker, platform_id)`, native-currency cost basis, cash + gold asset types | Real dogfooding showed users hold the same asset across platforms and in multiple currencies | ✓ Good — v1.0 Phase 7 (added mid-milestone) |

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
*Last updated: 2026-07-18 — started milestone v1.1 (UI Redesign — "Paper" Aesthetic)*
