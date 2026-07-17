# monai

Personal wealth intelligence layer. Self-hosted, AI-queryable, yours.

## What it is

A self-hosted, single-user app that combines your **spending history** and **investment holdings** in one place, with a conversational AI layer that can both *read and safely act on* your data.

Not a budgeting app. Not another Mint clone. Every self-hosted finance tool does one thing — Actual Budget does spending, Ghostfolio does investments. None of them talk to each other, and none have a natural-language layer that can also make changes for you behind a confirmation gate. monai is the bridge.

**What you can ask it:**
- "How much did I spend on food in April 2024?"
- "You bought NVDA in March — since then, how has my eating-out spending changed?"
- "Add a 2M IDR groceries transaction for yesterday" → it proposes the exact change and waits for your approval before writing anything.

The AI never fabricates a number (it chains a fixed set of tested tools, never raw SQL) and never changes your data without an explicit, single-use confirmation.

## Status

✅ **v1.0 shipped** (2026-07-17) — a working four-page app.

- **Chat** — agentic, multi-step reasoning that plans and chains tools; confirm-before-write edits with an audit log.
- **Cashflow** — dashboard (totals, category donut, income-vs-expense, month trend, per-account balances) + full CRUD on transactions/accounts/categories + Wallet CSV upload.
- **Investments** — holdings CRUD with live prices (crypto via CoinGecko, IDX via yfinance, manual fallback), P&L and staleness badges, multi-platform / multi-currency (USD→IDR) positions, cash + physical gold, allocation pie + historical value/P&L charts.
- **Settings** — configure LLM provider/model, API keys, base currency, and price source in-UI.
- **MCP server** — read-only finance tools exposed to external MCP clients (e.g. Claude Desktop) over the same tool source the web agent uses.

Deferred to v2: recurring-charge/subscription detection, arbitrary two-period comparison, token-by-token streaming, automated reksadana NAV feed.

## Architecture

- **Backend** — Python 3.12 · FastAPI · SQLAlchemy 2.0 · psycopg3, on port `8001`
- **Database** — PostgreSQL 16, Alembic-managed schema, on port `5434`
- **AI** — LlamaIndex `FunctionAgent` over a fixed tool registry; multi-provider via `LLM_PROVIDER` (Ollama local default / Claude / OpenAI)
- **Frontend** — Next.js 14 (App Router) + React 18; a server-side route handler proxies `/api/*` to the backend and injects the API key so it never reaches the browser bundle
- **MCP** — FastMCP co-mounted in the FastAPI app at `/mcp` (read-only, auth-gated)
- **Correctness by construction** — the LLM selects and chains parameterized tools; it never emits SQL. All agent writes require explicit user confirmation and are audit-logged.

## Getting started

Requires Docker + Docker Compose. Host networking is used so the backend can reach a local Ollama daemon — this is **Linux-only**; on Mac/Windows switch the compose services to bridge networking + `host.docker.internal`.

**1. Set an API key** (required — guards all write endpoints):

```sh
echo "MONAI_API_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')" >> .env
```

**2. (Default provider) Have Ollama running** on the host at `http://localhost:11434` with the model in `docker-compose.yml` (`gemma4:31b-cloud`). To use Claude or OpenAI instead, set `LLM_PROVIDER=claude` (+ `ANTHROPIC_API_KEY`) or `LLM_PROVIDER=openai` (+ `OPENAI_API_KEY`) — these are also switchable in the Settings page.

**3. Start the stack:**

```sh
docker compose up -d --build
```

- Frontend: http://localhost:3000
- Backend API: http://localhost:8001
- MCP endpoint: http://localhost:8001/mcp (send `MONAI_API_KEY` as a header or `Authorization: Bearer <key>`)

Alembic runs `alembic upgrade head` automatically at backend startup (idempotent). A fresh install needs nothing further. **If you have an existing `monai_pgdata` volume from before Alembic**, follow the one-time runbook below first.

## Privacy

All data stays on your machine. AI inference runs locally via Ollama by default. Cloud APIs (Claude/OpenAI) only activate if you explicitly set `LLM_PROVIDER=claude` or `LLM_PROVIDER=openai`.

## Database migrations

monai uses [Alembic](https://alembic.sqlalchemy.org/) for schema management. The Docker entrypoint runs `alembic upgrade head` automatically on every container start (idempotent).

### One-time introduction runbook (existing `monai_pgdata` volume)

> **Only for volumes created before Alembic was introduced.** A fresh install skips this — Alembic applies all migrations on first start.

**Step 1 — Backup first:**

```sh
docker exec monai-db pg_dump -U monai monai > backup_pre_alembic.sql
```

Confirm the file is non-empty before proceeding.

**Step 2 — Stamp the baseline** (marks the existing schema as already applied WITHOUT running it):

```sh
alembic stamp 3a1f8c2d9e04
alembic current   # must show: 3a1f8c2d9e04
```

> **WARNING:** Step 2 MUST precede Step 3 on an existing volume. Skipping the stamp and running `alembic upgrade head` directly makes migration 001 fail with "relation accounts already exists".

**Step 3 — Apply the remaining migrations:**

```sh
alembic upgrade head
alembic current   # must show the current head revision
```

**Step 4 — Verify no data loss:**

```sh
docker exec monai-db psql -U monai -d monai -c "SELECT count(*) FROM transactions;"
docker exec monai-db psql -U monai -d monai -c "\dt"   # audit_log, proposals, holdings, portfolio_events, price_cache, platforms, ... present
docker exec monai-db psql -U monai -d monai -c "\dv"   # date_helpers present
```

### Day-to-day usage

After the one-time runbook, `docker compose up` handles everything — Alembic runs at container start and skips already-applied migrations.

## License

MIT
