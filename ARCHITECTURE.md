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
