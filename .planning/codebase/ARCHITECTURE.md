# Architecture

**Analysis Date:** 2026-06-20

## Overview

monai is a self-hosted personal-finance app with a conversational AI layer over
spending data. The repo currently holds **two parallel implementations**:

- `poc/` — **Approach A** (throwaway): Python + SQLite + Streamlit + LlamaIndex
  `NLSQLTableQueryEngine`. Built to validate feasibility against a real Wallet
  export. Gate cleared (10/10 test questions, 5608 rows). Slated for deletion.
- `backend/` + `ui/` — **Approach C** (production vertical slice): FastAPI +
  PostgreSQL + Next.js, with a hand-written **tool router** replacing NL-to-SQL.

The root `ARCHITECTURE.md` (not this file) is the project's **decision log**;
this document describes the *current code structure* for planning/execution.

## Architectural Pattern

**Layered service, single responsibility per module.** The production backend
(`backend/`) is a thin FastAPI app over a SQLAlchemy data layer, with the AI
query layer isolated behind a tool-router abstraction.

```
Browser (Next.js UI)
   │  fetch("/api/*")
   ▼
Next.js rewrite proxy  (ui/next.config.js)   — one browser origin
   │  http → MONAI_API (:8001)
   ▼
FastAPI app  (backend/main.py)               — routing, validation, HTTP errors
   ├── importer.py   CSV parse + bulk insert
   ├── query.py      LLM tool router  ──►  tools.py  (parameterized SQL)
   └── db.py / models.py / schemas.py         persistence + (de)serialization
   │
   ▼
PostgreSQL 16  (transactions, accounts, date_helpers view)
```

## Layers

| Layer | Files | Responsibility |
|-------|-------|----------------|
| HTTP / API | `backend/main.py` | Endpoints, dependency injection, error mapping (`ValueError`→422, generic→500), CORS |
| Schemas (DTO) | `backend/schemas.py` | Pydantic request/response models (`*Create`, `*Out`, `*Request`, `*Response`) |
| AI query | `backend/query.py` | LLM routes question → `{tool, args}` JSON; executes + formats |
| Tools (domain) | `backend/tools.py` | 9 hand-written, parameterized SQL aggregations; period resolution; answer formatting |
| Persistence | `backend/db.py`, `backend/models.py` | SQLAlchemy engine/session, ORM models, schema + `date_helpers` view bootstrap |
| Import | `backend/importer.py` | Wallet CSV parse, currency validation, bulk insert |
| Config | `backend/config.py` | `DATABASE_URL`; multi-provider LLM setup via `Settings` |
| Frontend | `ui/app/page.tsx`, `ui/app/layout.tsx` | Single-page React client: ask box, entry form, recent list |

## The Tool Router (key architectural decision)

The defining design choice (root `ARCHITECTURE.md`, "Query Layer Pivot"):
**the LLM never writes SQL.** Naive `NLSQLTableQueryEngine` produced confident
wrong numbers on the real dataset (wrong year, counted income as spending,
confused `type` vs `category`). Instead:

1. `backend/query.py:route()` — LLM reads the question and emits JSON naming
   exactly one tool + typed args (`{"tool": "spending_total", "args": {...}}`),
   or `{"tool": null, "reason": ...}` if it can't map the question.
2. `backend/query.py:_extract_json()` — robustly pulls the first balanced `{...}`
   from the model reply (strips markdown fences, prose).
3. `backend/tools.py` — the named tool runs **hand-written, tested SQL**.
   Relative dates ("last month") resolve in Python via `resolve_period()` and a
   fixed `PERIODS` tuple — the model can never get the year/boundaries wrong.
4. `backend/tools.py:format_answer()` — renders the structured dict as natural
   language with the correct currency.

**Failure philosophy:** for a money app, refusing beats a confident wrong number.
Every error path returns an honest "I couldn't…" string rather than a fabricated
figure.

## Data Flow

**Query** (`POST /query`): question → `ask()` → `route()` (LLM) → `_extract_json`
→ `TOOLS[name](**args)` → SQL against Postgres → `format_answer()` → `QueryResponse`.

**Import** (`POST /import`): multipart upload → `utf-8-sig` decode →
`import_csv_text()` → `parse_csv()` (validate columns, single-currency filter) →
`insert_rows()` (bulk, `_get_or_create_account`) → `reset_engine()`.

**Manual entry** (`POST /transactions`): Pydantic `TransactionCreate` →
`_get_or_create_account` → `Transaction` row → `reset_engine()`.

## Key Abstractions

- **`TOOLS` registry** (`backend/tools.py`) — `dict[str, callable]` mapping tool
  name to function. Adding a capability = add a function + register it + add its
  spec line in `query.py:_TOOL_SPEC`.
- **Named periods** (`PERIODS` + `resolve_period`) — all relative-date logic is
  centralized and returns `[start_inclusive, end_exclusive)` bounds.
- **LlamaIndex `Settings` singleton** — `backend/config.py:configure_llm()` sets
  `Settings.llm` / `Settings.embed_model` once per provider; `query.py` caches
  `Settings.llm` in module-level `_llm`.
- **`date_helpers` view** (`backend/db.py`) — Postgres view of relative-date
  boundaries, created on startup (legacy from the NL-to-SQL approach; the router
  resolves dates in Python now).

## Entry Points

- **Backend API:** `backend/main.py:app` (FastAPI). Dev:
  `uvicorn backend.main:app --reload --port 8001`. Schema auto-created on
  `@app.on_event("startup")` → `init_db()`.
- **Frontend:** `ui/app/page.tsx` (Next.js App Router, `"use client"`). Dev:
  `cd ui && npm run dev` (port 3001).
- **PoC (throwaway):** `poc/app.py` (Streamlit), `poc/load.py` (CLI loader).
- **Containers:** `docker compose up -d --build` → db (:5434), backend (:8001),
  frontend (:3001).

## State & Caching

- The LLM client is a module-level singleton (`_llm` in `backend/query.py`).
  Mutations (`/transactions`, `/import`) call `reset_engine()` which clears it —
  vestigial from the cached-engine era; the router itself holds no per-import
  state (see its docstring).
- DB sessions are per-request via the `get_session()` FastAPI dependency
  (`backend/db.py`), always closed in a `finally`.

## Anti-patterns / Notable Deviations

- **Lazy imports inside handlers** — `from backend.query import ask/reset_engine`
  is done *inside* route functions in `backend/main.py` to avoid import-time
  circular dependencies and defer LLM module loading.
- **Two divergent CSV parsers** — `backend/importer.py` (production, in-memory
  text) and `poc/parser.py` (path-based, SQLite). The backend one is
  self-contained by design (does not import from `poc/`).
- **Broad `except Exception`** in `/query` and `ask()` — intentional, to convert
  any failure into an honest refusal rather than a 500 with a wrong number.

---

*Architecture analysis: 2026-06-20*
