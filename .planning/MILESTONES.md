# Milestones

Historical record of shipped versions. Full detail archived under `.planning/milestones/`.

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
