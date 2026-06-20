# Technology Stack

**Analysis Date:** 2026-06-20

## Languages

**Primary:**
- Python 3.12 (Docker runtime) / 3.14 (host dev) — backend API and AI query layer (`backend/`, `poc/`)
- TypeScript 5.6.3 — Next.js frontend (`ui/`)

**Secondary:**
- SQL (PostgreSQL dialect) — hand-written query tools and views (`backend/db.py`, `backend/tools.py`)

## Runtime

**Environment:**
- Python: 3.12-slim (Docker), 3.14 (host)
- Node.js: 20-alpine (Docker), 22.x (host dev)

**Package Manager:**
- Python: `pip` / `uv` (dev runner via `uv run --with-requirements`)
- Node: `npm`
- Lockfile: `ui/package-lock.json` present

## Frameworks

**Backend:**
- FastAPI >=0.110.0 — REST API server (`backend/main.py`)
- Uvicorn (standard extras) >=0.27.0 — ASGI server, port 8001

**Frontend:**
- Next.js 14.2.15 — React SSR/SPA (`ui/`)
- React 18.3.1 — UI rendering (`ui/app/page.tsx`, `ui/app/layout.tsx`)

**AI/LLM:**
- LlamaIndex Core >=0.10.0 — LLM abstraction layer (`backend/query.py`, `poc/query.py`)
- LlamaIndex Ollama LLM >=0.1.0 — local model integration
- LlamaIndex Ollama Embeddings >=0.1.0 — local embeddings
- LlamaIndex Anthropic LLM >=0.1.0 — Claude API integration
- LlamaIndex OpenAI LLM >=0.1.0 — OpenAI API integration
- LlamaIndex OpenAI Embeddings >=0.1.0 — OpenAI embeddings

**Database ORM:**
- SQLAlchemy >=2.0.0 — ORM and query builder (`backend/db.py`, `backend/models.py`)
- psycopg[binary] >=3.1.0 — PostgreSQL driver (psycopg3)

**PoC only:**
- Streamlit >=1.30.0 — PoC interactive UI (`poc/app.py`)
- pytest >=8.0.0 — test runner

**Build/Dev:**
- Node.js multi-stage Docker build for frontend (`ui/Dockerfile`)
- Docker Compose — full stack orchestration (`docker-compose.yml`)

## Key Dependencies

**Critical:**
- `fastapi` >=0.110.0 — all API endpoints depend on it
- `llama-index-core` >=0.10.0 — LLM routing and Settings singleton used across backend and PoC
- `sqlalchemy` >=2.0.0 — all DB access uses SQLAlchemy ORM + engine
- `psycopg[binary]` >=3.1.0 — psycopg3 required for `postgresql+psycopg://` connection strings
- `python-multipart` >=0.0.9 — required for FastAPI file upload (`POST /import`)

**Infrastructure:**
- `uvicorn[standard]` >=0.27.0 — production ASGI server in Docker
- PostgreSQL 16-alpine — database image in `docker-compose.yml`
- Ollama — external local LLM daemon, expected at `http://localhost:11434`

## Configuration

**Environment:**
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

**Build:**
- `ui/tsconfig.json` — TypeScript config
- `ui/next.config.js` — Next.js config with `/api/*` reverse proxy rewrites
- `backend/Dockerfile` — Python 3.12-slim, installs `backend/requirements.txt`
- `ui/Dockerfile` — multi-stage Node 20-alpine build

## Platform Requirements

**Development:**
- Python 3.12+ (3.14 used on host)
- Node.js 20+
- Ollama daemon running locally on port 11434 (default LLM provider)
- PostgreSQL accessible on port 5434 (or via Docker Compose)
- `uv` for backend dev runner (optional but documented)

**Production:**
- Docker + Docker Compose (Linux; compose uses `network_mode: host` — Mac/Windows requires adjustment)
- PostgreSQL 16 (managed via `monai_pgdata` named volume)
- Ollama on host for default local inference

---

*Stack analysis: 2026-06-20*
