# Milestones

Historical record of shipped versions. Full detail archived under `.planning/milestones/`.

## v1.1 — UI Redesign ("Paper" Aesthetic)

**Shipped:** 2026-07-18 · **Phases:** 8-10 · **Plans:** 3 · **Timeline:** 2026-07-18 (1 day)
**Requirements:** 10/10 UIR satisfied · **Verification:** 3/3 phases passed, 27/27 e2e

Re-skinned the whole app to the Claude Design "paper" mockup — a warm editorial
look — with zero backend changes and all behavior/data preserved (real IDR):

- **Design foundation** — paper token layer in `styles.ts` (single source of truth), Instrument Serif + Hanken Grotesk via `next/font`, and the shell converted from a dark top-nav to a centered rounded panel with a left sidebar.
- **Cashflow + Chat** — net-worth hero, income/expense line trend, stat cards, category donut, accounts, transactions; chat user/assistant bubbles, collapsible tool-trace, green proposal card, sticky composer.
- **Investments + Settings** — total-value hero, allocation donut, platform-grouped holdings tables; settings paper cards + provider segmented control.
- **Consistency + responsive** — 11 secondary components re-themed to paper tokens; auto-fit grids + a sidebar icon-rail collapse give a no-overflow layout down to 375px.

**Known deferred items at close:** 11 pre-existing v1.0-era open artifacts (see STATE.md Deferred Items). Milestone-scoped deviations: Settings live-refresh toggle omitted (no backend field, presentation-only); sidebar footer kept honest (no fabricated sync numbers).

Archives: [v1.1-ROADMAP.md](milestones/v1.1-ROADMAP.md) · [v1.1-REQUIREMENTS.md](milestones/v1.1-REQUIREMENTS.md)

## v1.0 — Agentic Chat + Investments + Multi-page UI + MCP

**Shipped:** 2026-07-17 · **Phases:** 1-7 · **Plans:** 30 · **Timeline:** 2026-05-27 → 2026-07-17 (~51 days)
**Requirements:** 35/35 satisfied · **Audit:** passed (2026-07-17)

Turned a single-page NL-to-SQL prototype into a four-page agentic personal-finance app:

- **Agentic chat** — multi-step tool-chaining agent that never emits SQL and never mutates data without a single-use, operation-scoped, audit-logged confirmation.
- **Cashflow** — dashboard (totals, category donut, trend, per-account balances) + full transaction/account/category CRUD + CSV upload.
- **Investments** — holdings CRUD with live prices (CoinGecko/yfinance/manual), P&L, staleness badges; multi-platform, multi-currency (USD→IDR), cash + physical gold positions; allocation pie + historical value/P&L charts.
- **MCP server** — FastMCP co-mounted in FastAPI, read-only auth-gated tools shared with the web agent; live external UAT 5/5.
- **Foundation** — Alembic-managed schema, API-key auth on writes, Decimal money math end-to-end.

Archives: [v1.0-ROADMAP.md](milestones/v1.0-ROADMAP.md) · [v1.0-REQUIREMENTS.md](milestones/v1.0-REQUIREMENTS.md)
