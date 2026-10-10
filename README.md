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

✅ **v1.4 shipped** (2026-10-04). See [Releases](https://github.com/nikkopg/monai/releases) for per-version notes.

- **Chat**: an agent that plans and chains tools over several steps. Every write is proposed as an Approve/Reject card (one card per proposal), applied only after you confirm, and audit-logged.
- **Cashflow**: one net-worth figure, liquids plus investments, each counted once. The dashboard has totals, a category donut, income vs expense, a month trend and per-account balances. A net-worth trend card goes back years: months without trustworthy data show as explained gaps, never interpolated.
- **Records**: a date-grouped ledger with daily nets, filters, transfer pairs and bulk actions. One modal records an expense, income or transfer.
- **Accounts and categories**: typed liquid/investment accounts with balance adjustments. Categories form a 3-level hierarchy, managed in Settings. Wallet (BudgetBakers) CSV import.
- **Investments**:
  - holdings across platforms, with live prices (crypto via CoinGecko, IDX via yfinance, manual fallback), P&L and staleness badges
  - USD→IDR conversion, cash and physical gold
  - allocation and historical charts
  - funded buy/sell from a liquid account
- **Settings**: LLM provider/model, API keys, base currency and price source, all set in the UI.
- **Inbox**: every proposal waiting for your approval, from chat or from Claude over MCP, in one page with its rows, duplicate flags, per-row skip and the confirm code; approve or reject with a button that says what it will do.
- **MCP server**: read-only finance tools for external MCP clients such as Claude Desktop (same registry as the web agent), plus curated write tools that only create proposals you approve with a code.

Not built yet: recurring-charge detection, arbitrary two-period comparison, token-by-token streaming, an automated reksadana NAV feed.

## Architecture

- **Backend** — Python 3.12 · FastAPI · SQLAlchemy 2.0 · psycopg3, on port `8001`
- **Database** — PostgreSQL 16, Alembic-managed schema, on port `5434`
- **AI** — LlamaIndex `FunctionAgent` over one tool registry (`backend/tools.py` `TOOLS`), streamed through `POST /query-stream`; multi-provider via `LLM_PROVIDER` (Ollama local default / Claude / OpenAI). Each tool's docstring is its prompt, and the LLM-visible tool surface is locked by a checked-in snapshot (`backend/tests/agent_tool_surface.json`)
- **Frontend** — Next.js 14 (App Router) + React 18; a server-side route handler proxies `/api/*` to the backend and injects the API key so it never reaches the browser bundle
- **MCP** — FastMCP co-mounted in the FastAPI app at `/mcp` (auth-gated)
- **Correctness by construction** — the LLM selects and chains parameterized tools; it never emits SQL. All agent writes require explicit user confirmation and are audit-logged.

## Getting started

Requires Docker + Docker Compose. Host networking is used so the backend can reach a local Ollama daemon — this is **Linux-only**; on Mac/Windows switch the compose services to bridge networking + `host.docker.internal`.

**1. Set an API key** (required — guards all write endpoints):

```sh
echo "MONAI_API_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')" >> .env
```

Optionally add a separate approver key. It approves or rejects any pending proposal whatever channel created it (`POST /proposals/{id}/approve` and `POST /proposals/{id}/reject`, sent in the `MONAI_APPROVER_KEY` header):

```sh
echo "MONAI_APPROVER_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')" >> .env
```

Docker compose also passes the key to the frontend container, whose proxy attaches it only to the Inbox list, approve, reject and row-skip requests (never to the browser), and only for same-origin requests to `127.0.0.1` or `localhost` (open the app at one of those, or through an SSH tunnel that keeps them); rebuild with `docker compose up -d --build` after changing it. The Inbox marks its own requests (`X-Monai-Surface: inbox`) and the proxy attaches the key to those only, so the chat card's Reject keeps API-key scope and is unaffected by the approver key. If the frontend's approver key is set but wrong, Inbox actions fail with the "Approvals aren't set up" message; fix the key, or leave it unset.

It must differ from `MONAI_API_KEY` (the backend answers 503 if they match or if it is unset). Never put it in any MCP client config: MCP clients hold `MONAI_API_KEY`, and the split is what keeps them from approving MCP-created proposals. `MONAI_API_KEY` still authorizes the REST write routes and chat token confirms, so treat it as a write key too.

**2. (Default provider) Have Ollama running** on the host at `http://localhost:11434` with the model in `docker-compose.yml` (`gemma4:31b-cloud`). To use Claude or OpenAI instead, set `LLM_PROVIDER=claude` (+ `ANTHROPIC_API_KEY`) or `LLM_PROVIDER=openai` (+ `OPENAI_API_KEY`) — these are also switchable in the Settings page.

**3. Start the stack:**

```sh
docker compose up -d --build
```

- Frontend: http://127.0.0.1:3001
- Backend API: http://127.0.0.1:8001
- MCP endpoint: http://127.0.0.1:8001/mcp (send `MONAI_API_KEY` as a header or `Authorization: Bearer <key>`)

**MCP writes.** Four tools let an MCP client capture data: `propose_transactions` (one row or a batch of up to 500), `propose_transfer`, `confirm_proposal` and `reject_proposal`. Every write lands as a pending proposal. Claude can apply it only with the 6-character code shown in monai; open Inbox in monai to read it (each Claude proposal shows its code with a Copy button). 5 wrong codes lock that proposal for MCP and 20 wrong codes per hour stop MCP confirms; you can still approve it in the Inbox. Skip rows in the Inbox before approving. Likely duplicates are flagged, never blocked. Never put the approver key in any MCP client config.

Alembic runs `alembic upgrade head` automatically at backend startup (idempotent). A fresh install needs nothing further. **If you have an existing `monai_pgdata` volume from before Alembic**, follow the one-time runbook below first.

### Network and timezone

The db, API and UI all listen on `127.0.0.1` only — nothing is reachable from the LAN. For remote use, SSH-tunnel instead: `ssh -L 3001:127.0.0.1:3001 user@your-server` (add `-L 8001:127.0.0.1:8001` for MCP), then open http://127.0.0.1:3001 locally. Point `mcp-remote` / Claude Desktop configs at http://127.0.0.1:8001/mcp. The backend runs on Asia/Jakarta via `TZ`/`PGTZ` in `docker-compose.yml`; the daily 01:00 WIB portfolio snapshot used to stamp the previous (UTC) date and now stamps the Jakarta date, so expect a one-time one-day discontinuity in the value history at cutover.

## Development

**Tests.** Run `pytest` from the repo root. It defaults to a separate `monai_test` database on the same Postgres, creating and migrating it on the first run, and it refuses to run against the live `monai` database. Tests use synthetic data only. `backend/tests_live_audit/` holds read-only checks against live data, run by hand only.

**UI tests.** `cd ui && CI=1 npm run e2e` runs the Playwright suite on port 3099 against mocked APIs. The Inbox live spec `e2e/inbox-live.spec.ts` is opt-in and writes real rows, so it needs a scratch backend on `monai_test` with synthetic, different API and approver keys. It refuses ports 8001 and 3001. Start the scratch backend, then run the spec with the same values in `E2E_*` and in `MONAI_API`, `MONAI_API_KEY`, `MONAI_APPROVER_KEY`:

```sh
DATABASE_URL=postgresql+psycopg://monai:monai@127.0.0.1:5434/monai_test MONAI_API_KEY=e2e-api-key-synthetic-0001 MONAI_APPROVER_KEY=e2e-approver-key-synthetic-0002 TZ=Asia/Jakarta PGTZ=Asia/Jakarta .venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8011
cd ui && CI=1 E2E_LIVE=1 E2E_BACKEND=http://127.0.0.1:8011 E2E_API_KEY=e2e-api-key-synthetic-0001 E2E_APPROVER_KEY=e2e-approver-key-synthetic-0002 MONAI_API=http://127.0.0.1:8011 MONAI_API_KEY=e2e-api-key-synthetic-0001 MONAI_APPROVER_KEY=e2e-approver-key-synthetic-0002 npx playwright test e2e/inbox-live.spec.ts
```

**CI.** GitHub Actions (`.github/workflows/backend-tests.yml`) runs the backend suite on Python 3.12 against a fresh Postgres, on every push and pull request.

**Agent eval (opt-in).** Asks 12 golden questions with your configured LLM against `monai_test`. It checks each answer's tool choice, date arguments and numbers, then prints a pass/fail table. It is never part of CI.

```sh
env -u DATABASE_URL python -m backend.evals.agent_eval            # all cases
env -u DATABASE_URL python -m backend.evals.agent_eval --case 4   # one case
env -u DATABASE_URL python -m backend.evals.agent_eval --self-check   # parser only: no DB, no LLM
```

**Pre-push guard.** The repo is public and monai runs on real finances. `.githooks/pre-push` blocks pushes that contain planning docs, data or dump files, secret-like tokens, or IDR-sized figures. Enable it once per clone:

```sh
git config core.hooksPath .githooks
```

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
