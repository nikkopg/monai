# Directory Structure

**Analysis Date:** 2026-06-20

## Top-Level Layout

```
monai/
├── backend/              # Approach C — FastAPI production backend (ACTIVE)
├── ui/                   # Approach C — Next.js frontend (ACTIVE)
├── poc/                  # Approach A — throwaway PoC (SLATED FOR DELETION)
├── docker-compose.yml    # 3-service stack: db, backend, frontend
├── ARCHITECTURE.md       # Project DECISION log (not the codebase map)
├── README.md             # Project overview (stale — says "not usable yet")
├── TODOS.md              # Durable backlog (open work)
├── LICENSE               # MIT
├── report_*.csv          # Real Wallet exports (test/sample data)
└── .planning/            # GSD planning artifacts (this map lives here)
```

## `backend/` — FastAPI Backend (active)

```
backend/
├── main.py          # FastAPI app + all endpoints (/health /accounts
│                    #   /transactions /import /query), CORS, startup hook
├── config.py        # DATABASE_URL + configure_llm() multi-provider setup
├── db.py            # SQLAlchemy engine/session, init_db(), date_helpers view
├── models.py        # ORM models: Account, Transaction
├── schemas.py       # Pydantic DTOs: *Create / *Out / *Request / *Response
├── importer.py      # Wallet CSV parse + bulk insert (self-contained)
├── tools.py         # 9 parameterized SQL tools + resolve_period + format_answer
├── query.py         # LLM tool router: route() / ask() / _extract_json()
├── __init__.py      # marks backend a package (import path: backend.*)
├── Dockerfile       # python:3.12-slim image
├── requirements.txt # Python deps
├── .dockerignore
└── tests/
    ├── __init__.py
    ├── test_tools.py    # resolve_period (pure) + tool SQL (integration)
    └── test_router.py   # _extract_json JSON-extraction tests
```

**Import convention:** modules are imported as `backend.<module>` (absolute,
package-rooted). The app is run from the repo root, e.g.
`uvicorn backend.main:app`.

## `ui/` — Next.js Frontend (active)

```
ui/
├── app/
│   ├── layout.tsx     # Root layout (App Router)
│   └── page.tsx       # Single-page client: ask box + entry form + recent list
├── next.config.js     # /api/* → backend reverse-proxy rewrite
├── tsconfig.json      # TypeScript config
├── package.json       # next 14.2.15, react 18.3.1; scripts pinned to port 3001
├── package-lock.json
├── next-env.d.ts
├── Dockerfile         # multi-stage node:20-alpine build
└── .dockerignore
```

**App Router (Next 14):** pages live under `ui/app/`. The whole UI is currently
one client component (`page.tsx`); no component library or separate `components/`
directory yet. Styling is inline `React.CSSProperties` objects (dark theme).

## `poc/` — Approach A PoC (throwaway, slated for deletion)

```
poc/
├── app.py           # Streamlit chat UI
├── load.py          # CLI: parse CSV → insert into SQLite
├── parser.py        # Wallet CSV parser (path-based, SQLite-oriented)
├── db.py            # SQLite schema, WAL mode, date_helpers view
├── query.py         # LlamaIndex NLSQLTableQueryEngine + LRU cache
├── config.py        # LLM provider config
├── requirements.txt
├── monai.db         # SQLite database (committed PoC data)
└── tests/
    ├── __init__.py
    ├── test_parser.py
    └── test_db.py
```

> Per `TODOS.md`, `poc/` is "throwaway by design and fully superseded by
> `backend/`" — delete once confident it's no longer needed as reference.

## Key File Locations (where to add things)

| To add… | Put it in… |
|---------|-----------|
| A new API endpoint | `backend/main.py` (+ DTOs in `backend/schemas.py`) |
| A new query capability | `backend/tools.py` (function + `TOOLS` entry) **and** `backend/query.py` (`_TOOL_SPEC` line + example) |
| A new ORM table/column | `backend/models.py` (+ migration story — none yet, see CONCERNS) |
| A new LLM provider | `backend/config.py:configure_llm()` |
| A backend test | `backend/tests/test_*.py` |
| A UI feature | `ui/app/page.tsx` (or new App-Router page under `ui/app/`) |
| A new service/container | `docker-compose.yml` |

## Naming Conventions

- **Python files:** `snake_case.py`, one clear responsibility per module
  (`db.py`, `tools.py`, `importer.py`).
- **Private helpers:** leading underscore (`_extract_json`, `_get_or_create_account`,
  `_date_clause`, `_currency`, `_fmt`).
- **Pydantic schemas:** suffix by role — `TransactionCreate`, `TransactionOut`,
  `QueryRequest`, `QueryResponse`, `ImportResponse`, `AccountOut`.
- **Tests:** `test_<module>.py`, grouped into `Test<Thing>` classes.
- **TypeScript/React:** `page.tsx` / `layout.tsx` (Next conventions); `camelCase`
  functions and state, `PascalCase` types (`type Tx = {...}`).

## Data / Artifacts

- `report_2026-06-07_195027.csv`, `report_2026-06-20_132532.csv` — real Wallet
  exports used for validation/import (repo root).
- `poc/monai.db` — committed SQLite PoC database.
- `monai_pgdata` — Docker named volume for Postgres (not in repo).

## Generated / Ignored

- `.venv-backend/` — local Python virtualenv (Python 3.14 host).
- `.next/`, `node_modules/` — Next.js build + deps (frontend).
- `.pytest_cache/`, `__pycache__/` — test/bytecode caches.
- `.gstack/` — gstack browser tooling state.

---

*Structure analysis: 2026-06-20*
