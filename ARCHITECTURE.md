# monai — Architecture

## Module Layout

```
monai/
  poc/                  # Approach A — throwaway PoC
    db.py               # SQLite schema, WAL mode, date_helpers view
    parser.py           # Wallet CSV parser (semicolon-delimited)
    config.py           # LLM provider config (LLM_PROVIDER env var)
    query.py            # LlamaIndex NLSQLTableQueryEngine + LRU cache
    load.py             # CLI: parse CSV → insert into DB
    app.py              # Streamlit chat UI
    requirements.txt
    tests/
      test_parser.py
      test_db.py

  backend/              # Approach C — FastAPI (not started)
  importer/             # Approach C — import pipeline
  query/                # Approach C — LlamaIndex AI layer
  ui/                   # Approach C — Next.js frontend
  docker/               # Approach C — Docker Compose + Dockerfiles
```

## Approach A → Approach C Handoff Criteria

**Stop Approach A and design Approach C when:**
1. At least **7 of the 10 pre-defined test questions** (below) return correct answers
2. The spending schema (columns, types, edge cases) is fully understood from the real export
3. This `ARCHITECTURE.md` is up to date with the discovered schema

**Approach A data is throwaway.** Start Approach C on fresh PostgreSQL using the schema
documented here as input. Do not migrate the SQLite file.

### Validation results (2026-06-20) — GATE CLEARED ✅

Full history loaded and all 10 test questions passed.

| Metric | Result | Implication for Approach C |
|--------|--------|----------------------------|
| Rows loaded | 5608 | AI query layer holds at real scale, not just the 52-row sample |
| Rows skipped | **0** | Single-currency (IDR) confirmed at full scale — multi-currency is a non-issue |
| Test questions | **10/10** | Exceeds 7/10 threshold; relative dates, aggregations, top-N all reliable |

**Decision impact:** `base_currency` + `fx_rate` columns drop from the v1 Approach C
schema. Add them only if a foreign-currency account is ever introduced. v1 stays
single-currency.

## Approach C — Query Layer Pivot (2026-06-20)

**Finding during the vertical-slice build:** naive `NLSQLTableQueryEngine` +
`gemma4:31b-cloud` writes *wrong SQL* on the real 5-year dataset — it hardcoded
the wrong year (2024 instead of 2026, ignoring injected date + `date_helpers`),
counted income (Salary) as spending (`ORDER BY SUM(amount)` without `amount < 0`),
and confused the `type` column with `category`. All three returned confident wrong
numbers — the worst failure mode for a money app. The PoC's 10/10 passed only
because the 52-row sample was a single recent month, so these traps never fired.

**Decision: tool router, correct by construction.** The LLM no longer writes SQL.
It picks one of a fixed set of parameterized tools (`backend/tools.py`) and fills
typed arguments; the SQL is hand-written and tested, and relative dates resolve in
Python via named periods (`this_month`, `last_year`, ...). If the model can't map a
question to a tool, the app says so rather than fabricate a number.

- `backend/tools.py` — spending_total, income_total, net_total, spending_by_category,
  spending_in_category, transaction_count, largest_transactions, average_daily_spending,
  list_categories. Each returns a structured dict; `format_answer` renders it with the
  correct currency.
- `backend/query.py` — LLM router: question → `{tool, args}` JSON → execute → format.
- This is the eng-review-anticipated "FunctionTool wrappers" direction, applied to
  basic aggregations (not just correlation queries) because plain NL2SQL proved
  unreliable here.

## Approach C — Stack (vertical slice, in progress)

```
docker-compose.yml      # 3 services: db, backend, frontend
backend/                # FastAPI
  Dockerfile            # python:3.12-slim image
  config.py             # DATABASE_URL + LLM provider (ollama gemma default) + OLLAMA_BASE_URL
  db.py                 # SQLAlchemy engine/session, schema bootstrap, date_helpers view
  models.py             # Account, Transaction (Numeric money, real timestamp)
  schemas.py            # Pydantic request/response
  importer.py           # Wallet CSV parse + bulk insert (self-contained, not poc/)
  tools.py              # parameterized SQL tools (correct by construction)
  query.py              # LLM tool router
  main.py               # FastAPI app: /health /accounts /transactions /import /query
  tests/                # 21 tests (tool SQL invariants + router JSON parsing)
ui/                     # Next.js 14
  Dockerfile            # multi-stage node:20-alpine build → next start
  app/page.tsx          # query box + transaction entry form + recent list
  next.config.js        # /api/* proxy → backend (one browser origin)
```

**Run the whole stack (containerized):**
```bash
docker compose up -d --build     # db + backend + frontend
# → frontend at http://localhost:3001, backend at :8001, Postgres at :5434
```
Schema is auto-created on backend startup. Load history once via the `/import`
endpoint (multipart CSV upload) or the UI. Data persists in the `monai_pgdata` volume.

**Networking:** `db` runs on the default bridge network with its port published on
`5434`. `backend` and `frontend` run on the **host network** (`network_mode: host`)
so the backend reaches the host's Ollama daemon (`127.0.0.1:11434`) and the db's
published port directly — without forcing Ollama to rebind to `0.0.0.0`. Linux-only;
on Mac/Windows switch backend to bridge networking with
`OLLAMA_BASE_URL=http://host.docker.internal:11434` and add `extra_hosts:
host.docker.internal:host-gateway`.

**Ports:** this machine already runs another project (`oldlegs`) on 5432/5433/3000/8000,
so monai uses Postgres `5434`, backend `8001`, frontend `3001`. Override via
`DATABASE_URL` / `MONAI_API` / `OLLAMA_BASE_URL` env vars in the compose file.

**Dev mode (no containers for app code):** run `docker compose up -d db`, then
`uvicorn backend.main:app --port 8001` in a venv and `cd ui && npm run dev` — same
ports, hot reload.

## Wallet by BudgetBakers CSV Schema

Source: `report_*.csv` exported from the Android app (Settings → Others → Export → CSV).

**Delimiter:** `;` (semicolon)
**Date format:** `YYYY-MM-DD HH:MM:SS`
**Amount:** signed float, negative = expense, positive = income

| Wallet column       | Type    | Notes                                    |
|---------------------|---------|------------------------------------------|
| account             | text    | Account name (e.g. "Cash")               |
| category            | text    | App category (e.g. "Restaurant, fast-food") |
| currency            | text    | ISO code (e.g. "IDR")                    |
| amount              | float   | Negative for expenses                    |
| ref_currency_amount | float   | Same as amount when single-currency      |
| type                | text    | "Expenses" or "Income"                   |
| payment_type        | text    | "TRANSFER", etc.                         |
| payment_type_local  | text    | Localized label                          |
| note                | text    | Transaction description (user-entered)   |
| date                | text    | "YYYY-MM-DD HH:MM:SS"                    |
| gps_latitude        | float   | Often empty                              |
| gps_longitude       | float   | Often empty                              |
| gps_accuracy_in_meters | int  | Often empty                              |
| warranty_in_month   | int     | 0 for most rows                          |
| transfer            | bool    | "true" if account transfer (not real expense) |
| payee               | text    | Often empty; merchant name if populated  |
| labels              | text    | Optional user labels                     |
| envelope_id         | int     | Wallet internal category ID              |
| custom_category     | bool    | "true" if user-defined category          |

## Normalized Transactions Schema (Approach A — SQLite)

```sql
accounts(
  id       INTEGER PRIMARY KEY,
  name     TEXT UNIQUE,
  type     TEXT,
  currency TEXT
)

transactions(
  id           INTEGER PRIMARY KEY,
  date         TEXT,       -- "YYYY-MM-DD HH:MM:SS"
  amount       REAL,       -- negative = expense
  currency     TEXT,
  category     TEXT,       -- editable; starts equal to raw_category
  raw_category TEXT,       -- original Wallet category, never overwritten
  merchant     TEXT,       -- payee if non-empty, else note
  notes        TEXT,       -- note field from Wallet
  account_id   INTEGER REFERENCES accounts(id),
  is_transfer  INTEGER     -- 1 if account transfer; exclude from aggregates
)
```

**Key rule:** All aggregate queries must filter `WHERE is_transfer = 0`.

**Deferred to Approach C:**
- `transfer_pair_id` — add with FK + uniqueness constraint once real export reveals pairing
- `base_currency` + `fx_rate` — for multi-currency normalization

## Approach C Schema Additions (planned)

```sql
-- transactions additions
ALTER TABLE transactions ADD COLUMN transfer_pair_id INTEGER;  -- FK to sibling transfer row
ALTER TABLE transactions ADD COLUMN base_currency TEXT;         -- normalized currency
ALTER TABLE transactions ADD COLUMN fx_rate REAL;              -- conversion rate at time of tx

-- holdings (v1.1 — Week 7+)
holdings(
  id            INTEGER PRIMARY KEY,
  ticker        TEXT NOT NULL,
  quantity      REAL NOT NULL,
  avg_cost      REAL NOT NULL,
  purchase_date TEXT NOT NULL,   -- "YYYY-MM-DD"
  currency      TEXT NOT NULL,
  imported_at   TEXT             -- timestamp of CSV import
)

-- Input: manual CSV with columns: ticker,quantity,avg_cost,purchase_date,currency

-- portfolio events (v1.1 — for correlation FunctionTools)
portfolio_events(
  id         INTEGER PRIMARY KEY,
  date       TEXT NOT NULL,
  ticker     TEXT NOT NULL,
  event_type TEXT NOT NULL,   -- "buy", "sell", "dividend", "split"
  price      REAL
)
```

## LLM Provider Configuration

```bash
# Local (default, no data leaves your machine)
LLM_PROVIDER=ollama OLLAMA_MODEL=mistral streamlit run poc/app.py

# Claude API
LLM_PROVIDER=claude ANTHROPIC_API_KEY=sk-... streamlit run poc/app.py

# OpenAI
LLM_PROVIDER=openai OPENAI_API_KEY=sk-... streamlit run poc/app.py
```

## Pre-defined Test Questions (10/10 required for A→C gate)

These questions must be answered correctly by the AI layer before Approach C begins.
Run them via the sidebar in `poc/app.py` or directly with `poc/query.py`.

1. How much did I spend in total this month?
2. How much did I spend on food and drinks this month?
3. What were my top 3 spending categories last month?
4. How much did I spend in total last month?
5. What is my total income vs total expenses this year?
6. Which day had my highest single expense?
7. How many transactions did I make this month?
8. What is my average daily spending this month?
9. How much did I spend on free time activities?
10. What are my 5 most expensive individual transactions?

**Pass threshold:** 7 of 10 correct → Approach A done, design Approach C.

## Hardware Requirements (Ollama)

| Model       | RAM required | Notes                          |
|-------------|-------------|--------------------------------|
| Mistral 7B  | ~4 GB       | Recommended for PoC            |
| Llama 3 8B  | ~5 GB       | Slightly better reasoning       |

First query after cold start: 10–30 seconds. Subsequent queries: 1–5 seconds.
