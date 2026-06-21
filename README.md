# monai

Personal wealth intelligence layer. Self-hosted, AI-queryable, yours.

## What it is

A self-hosted app that combines your **spending history** and **investment holdings** in one place, with a conversational AI layer over all of it.

Not a budgeting app. Not another Mint clone. The gap this fills: every self-hosted finance tool does one thing — Actual Budget does spending, Ghostfolio does investments. None of them talk to each other, and none have a natural language query layer. monai is the bridge.

**What you can ask it:**
- "How much did I spend on food in April 2024?"
- "You bought NVDA in March — since then you've spent 40% more on eating out. Correlation or celebration?"
- "Which subscriptions did I stop using 3 months before I cancelled them?"

## Status

🚧 Early development — not usable yet.

- [ ] v1 — spending import + AI query (Weeks 1–6)
- [ ] v1.1 — investment holdings + portfolio+spending correlation queries (Weeks 7–12)
- [ ] v2 — open source release (TBD)

## Architecture (planned)

**Proof of concept (current focus):**
- Python + SQLite
- LlamaIndex `NLSQLTableQueryEngine` for natural language queries
- Ollama (local) or Claude API via `LLM_PROVIDER` env var
- Streamlit chat UI

**Production (Approach C):**
- Python FastAPI + PostgreSQL
- LlamaIndex + custom `FunctionTool` wrappers for correlation queries
- Next.js frontend
- Docker Compose — single `docker compose up` to run

## Getting started

> Not ready yet. Check back once the PoC is working.

## Privacy

All data stays on your machine. AI inference runs locally via Ollama by default. Cloud API (Claude/OpenAI) only activates if you explicitly set `LLM_PROVIDER=claude` or `LLM_PROVIDER=openai`.

## Data safety

- SQLite WAL mode enabled
- Daily backup: `cp monai.db monai.db.$(date +%Y%m%d).bak`

## Migration

Built with migration from mobile money apps (Spendee, Wallet, Money Lover) as a Day 1 requirement. Import pipeline TBD — export format determines architecture.

## Database migrations

Monai uses [Alembic](https://alembic.sqlalchemy.org/) for schema management. The Docker
entrypoint runs `alembic upgrade head` automatically on every container start (idempotent).

### One-time introduction runbook (existing monai_pgdata volume)

> **Required for anyone who ran the app before Phase 1.** A fresh install skips straight to
> `docker compose up` — Alembic applies all migrations on first start.

**Step 0 — Generate an API key** (needed for write endpoints added in Phase 1):

```sh
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Add the result as `MONAI_API_KEY=<value>` to your `.env` (or export it before compose up).

**Step 1 — Backup first** (required before any migration — protects your 5,609 transactions):

```sh
docker exec monai-db pg_dump -U monai monai > backup_pre_alembic.sql
```

Confirm the file is non-empty before proceeding.

**Step 2 — Stamp the baseline** (marks the existing schema as already applied WITHOUT running it):

```sh
alembic stamp 3a1f8c2d9e04
alembic current   # must show: 3a1f8c2d9e04 (head is 002)
```

> **WARNING:** Step 2 MUST precede Step 3 on an existing volume. If you skip the stamp and
> run `alembic upgrade head` directly, migration 001 will fail with
> "relation accounts already exists" (Alembic Pitfall 1).

**Step 3 — Apply the new tables** (migration 002: audit_log, proposals, holdings,
portfolio_events, price_cache + date_helpers view):

```sh
alembic upgrade head
alembic current   # must show: <002_revision_id> (head)
```

**Step 4 — Verify no data loss:**

```sh
docker exec monai-db psql -U monai -d monai -c "SELECT count(*) FROM transactions;"
# expect: 5609
docker exec monai-db psql -U monai -d monai -c "SELECT count(*) FROM accounts;"
# expect: 3
docker exec monai-db psql -U monai -d monai -c "\dt"
# expect: audit_log, proposals, holdings, portfolio_events, price_cache in list
docker exec monai-db psql -U monai -d monai -c "\dv"
# expect: date_helpers in list
```

### Day-to-day usage

After the one-time runbook above, `docker compose up` handles everything. Alembic runs at
container start and is idempotent — already-applied migrations are skipped.

## License

MIT
