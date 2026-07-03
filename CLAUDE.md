<!-- GSD:project-start source:PROJECT.md -->
## Project

**monai**

monai is a self-hosted, single-user personal-finance app with a conversational AI
layer over your own spending and investment data. It imports Wallet (BudgetBakers)
CSV exports into PostgreSQL and lets you ask questions — and now *act* — in natural
language. This cycle turns it into a real multi-page app (cashflow, investments,
chat, settings) with an **agentic** chat that can both read and safely edit your
data, exposed as an MCP server for use from external clients too.

**Core Value:** You can understand and manage your entire financial life — spending and investments —
by talking to a trustworthy AI that never fabricates a number and never changes your
data without your say-so.

### Constraints

- **Tech stack**: FastAPI + PostgreSQL + Next.js (App Router) — established Approach C stack; build on it, don't re-platform
- **AI**: LlamaIndex abstraction with multi-provider config (Ollama local default / Claude / OpenAI) — agentic loop should build on this
- **Architecture**: Correctness-by-construction — the LLM selects/chains parameterized tools; it never emits SQL
- **Safety**: All agent writes require explicit user confirmation before applying; validated; audit-logged
- **Deployment**: Self-hosted via Docker Compose; single-user; local-first / privacy-respecting
- **Schema**: New `holdings` and `portfolio_events` tables + any column additions need a migration story (no Alembic today)
- **Currency**: Single-currency (IDR) assumption holds for spending; investments may span instruments/currencies
<!-- GSD:project-end -->

<!-- GSD:stack-start source:codebase/STACK.md -->
## Technology Stack

## Languages
- Python 3.12 (Docker runtime) / 3.14 (host dev) — backend API and AI query layer (`backend/`, `poc/`)
- TypeScript 5.6.3 — Next.js frontend (`ui/`)
- SQL (PostgreSQL dialect) — hand-written query tools and views (`backend/db.py`, `backend/tools.py`)
## Runtime
- Python: 3.12-slim (Docker), 3.14 (host)
- Node.js: 20-alpine (Docker), 22.x (host dev)
- Python: `pip` / `uv` (dev runner via `uv run --with-requirements`)
- Node: `npm`
- Lockfile: `ui/package-lock.json` present
## Frameworks
- FastAPI >=0.110.0 — REST API server (`backend/main.py`)
- Uvicorn (standard extras) >=0.27.0 — ASGI server, port 8001
- Next.js 14.2.15 — React SSR/SPA (`ui/`)
- React 18.3.1 — UI rendering (`ui/app/page.tsx`, `ui/app/layout.tsx`)
- LlamaIndex Core >=0.10.0 — LLM abstraction layer (`backend/query.py`, `poc/query.py`)
- LlamaIndex Ollama LLM >=0.1.0 — local model integration
- LlamaIndex Ollama Embeddings >=0.1.0 — local embeddings
- LlamaIndex Anthropic LLM >=0.1.0 — Claude API integration
- LlamaIndex OpenAI LLM >=0.1.0 — OpenAI API integration
- LlamaIndex OpenAI Embeddings >=0.1.0 — OpenAI embeddings
- SQLAlchemy >=2.0.0 — ORM and query builder (`backend/db.py`, `backend/models.py`)
- psycopg[binary] >=3.1.0 — PostgreSQL driver (psycopg3)
- Streamlit >=1.30.0 — PoC interactive UI (`poc/app.py`)
- pytest >=8.0.0 — test runner
- Node.js multi-stage Docker build for frontend (`ui/Dockerfile`)
- Docker Compose — full stack orchestration (`docker-compose.yml`)
## Key Dependencies
- `fastapi` >=0.110.0 — all API endpoints depend on it
- `llama-index-core` >=0.10.0 — LLM routing and Settings singleton used across backend and PoC
- `sqlalchemy` >=2.0.0 — all DB access uses SQLAlchemy ORM + engine
- `psycopg[binary]` >=3.1.0 — psycopg3 required for `postgresql+psycopg://` connection strings
- `python-multipart` >=0.0.9 — required for FastAPI file upload (`POST /import`)
- `uvicorn[standard]` >=0.27.0 — production ASGI server in Docker
- PostgreSQL 16-alpine — database image in `docker-compose.yml`
- Ollama — external local LLM daemon, expected at `http://localhost:11434`
## Configuration
- `DATABASE_URL` — PostgreSQL connection string (default: `postgresql+psycopg://monai:monai@localhost:5434/monai`)
- `LLM_PROVIDER` — `ollama` (default) | `claude` | `openai`
- `OLLAMA_MODEL` — default `gemma4:31b-cloud`
- `OLLAMA_EMBED_MODEL` — default `gemma4:31b-cloud`
- `OLLAMA_BASE_URL` — default `http://localhost:11434`
- `CLAUDE_MODEL` — default `claude-haiku-4-5-20251001`
- `OPENAI_MODEL` — default `gpt-4o-mini`
- `MONAI_API` — Next.js backend proxy target (default: `http://127.0.0.1:8001`)
- `ANTHROPIC_API_KEY` — required when `LLM_PROVIDER=claude`
- `OPENAI_API_KEY` — required when `LLM_PROVIDER=openai`
- `ui/tsconfig.json` — TypeScript config
- `ui/next.config.js` — Next.js config with `/api/*` reverse proxy rewrites
- `backend/Dockerfile` — Python 3.12-slim, installs `backend/requirements.txt`
- `ui/Dockerfile` — multi-stage Node 20-alpine build
## Platform Requirements
- Python 3.12+ (3.14 used on host)
- Node.js 20+
- Ollama daemon running locally on port 11434 (default LLM provider)
- PostgreSQL accessible on port 5434 (or via Docker Compose)
- `uv` for backend dev runner (optional but documented)
- Docker + Docker Compose (Linux; compose uses `network_mode: host` — Mac/Windows requires adjustment)
- PostgreSQL 16 (managed via `monai_pgdata` named volume)
- Ollama on host for default local inference
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

## Language & Style
- Python 3.12+ syntax. Modern type hints used liberally:
- `snake_case` for functions, variables, modules; `PascalCase` for classes.
- Leading underscore marks module-private helpers: `_extract_json`,
- Every module opens with a triple-quoted docstring explaining *what it does and
- Strict TS (`ui/tsconfig.json`), `camelCase` functions/state, `PascalCase`
- React function components, hooks (`useState`, `useEffect`), `async` handlers.
- Inline `React.CSSProperties` style objects (`card`, `input`, `btn`, `label`)
## Type Hints & Schemas
- Backend uses **full type annotations** on signatures and SQLAlchemy
- Pydantic v2 for API boundaries (`backend/schemas.py`): `BaseModel` with
- Schema naming by role: `*Create` (input), `*Out` (output/ORM read),
## Error Handling
- **Domain layer raises `ValueError`** with a descriptive message
- **API layer translates** exceptions to HTTP: `ValueError → HTTPException(422)`,
- **AI/query layer never raises to the user** — `ask()` wraps routing and tool
- `_extract_json` raises `ValueError` for malformed model output (tested).
## Patterns
- **Registry pattern:** `TOOLS = {name: callable}` dict in `backend/tools.py`;
- **Structured-dict returns:** every tool returns a `dict` with a `"tool"`
- **Lazy imports inside route handlers** (`backend/main.py`) — e.g.
- **Parameterized SQL only:** all queries use SQLAlchemy `text()` with bound
- **`_get_or_create_account` helper** shared between `/transactions` and the
- **Centralized relative dates:** `resolve_period()` + the `PERIODS` tuple are
## Logging
- Standard library `logging`. Module-level loggers via
- App configures root level once: `logging.basicConfig(level=logging.INFO)` in
- Skips/anomalies logged at `WARNING` (currency mismatch, unparseable amount);
## Configuration
- 12-factor: all config via environment variables with sensible defaults read in
- Provider switch (`LLM_PROVIDER`) drives lazy, provider-specific imports inside
## Comments & Documentation
- Heavy use of *intent* comments explaining sign conventions, exclusivity of date
- Docstrings describe return-tuple shapes precisely
## Conventions NOT present (gaps)
- No linter/formatter config committed (no `ruff`, `black`, `flake8`,
- No pre-commit hooks.
- No type-checker config (`mypy`/`pyright`) despite thorough annotations.
- No docstring style enforcement (Google/NumPy) — freeform but consistent.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

## Overview
- `poc/` — **Approach A** (throwaway): Python + SQLite + Streamlit + LlamaIndex
- `backend/` + `ui/` — **Approach C** (production vertical slice): FastAPI +
## Architectural Pattern
```
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
## Data Flow
## Key Abstractions
- **`TOOLS` registry** (`backend/tools.py`) — `dict[str, callable]` mapping tool
- **Named periods** (`PERIODS` + `resolve_period`) — all relative-date logic is
- **LlamaIndex `Settings` singleton** — `backend/config.py:configure_llm()` sets
- **`date_helpers` view** (`backend/db.py`) — Postgres view of relative-date
## Entry Points
- **Backend API:** `backend/main.py:app` (FastAPI). Dev:
- **Frontend:** `ui/app/page.tsx` (Next.js App Router, `"use client"`). Dev:
- **PoC (throwaway):** `poc/app.py` (Streamlit), `poc/load.py` (CLI loader).
- **Containers:** `docker compose up -d --build` → db (:5434), backend (:8001),
## State & Caching
- The LLM client is a module-level singleton (`_llm` in `backend/query.py`).
- DB sessions are per-request via the `get_session()` FastAPI dependency
## Anti-patterns / Notable Deviations
- **Lazy imports inside handlers** — `from backend.query import ask/reset_engine`
- **Two divergent CSV parsers** — `backend/importer.py` (production, in-memory
- **Broad `except Exception`** in `/query` and `ask()` — intentional, to convert
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->
## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, `.github/skills/`, or `.codex/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->



<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
