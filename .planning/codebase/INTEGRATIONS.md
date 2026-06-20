# External Integrations

**Analysis Date:** 2026-06-20

## APIs & External Services

**LLM Providers (switchable via `LLM_PROVIDER` env var):**
- Ollama (default) — local inference daemon, no data leaves the host
  - SDK/Client: `llama-index-llms-ollama`, `llama-index-embeddings-ollama`
  - Auth: None (unauthenticated local HTTP)
  - Base URL: `OLLAMA_BASE_URL` (default `http://localhost:11434`)
  - Default model: `gemma4:31b-cloud` (both LLM and embeddings)
  - Config: `backend/config.py`, `poc/config.py`

- Anthropic Claude — cloud LLM API
  - SDK/Client: `llama-index-llms-anthropic`
  - Auth: `ANTHROPIC_API_KEY` env var
  - Default model: `claude-haiku-4-5-20251001`
  - Embeddings: falls back to `"local"` (no Anthropic embedding API used)
  - Config: `backend/config.py`, `poc/config.py`

- OpenAI — cloud LLM + embeddings API
  - SDK/Client: `llama-index-llms-openai`, `llama-index-embeddings-openai`
  - Auth: `OPENAI_API_KEY` env var
  - Default model: `gpt-4o-mini`
  - Default embed model: OpenAI default via `OpenAIEmbedding()`
  - Config: `backend/config.py`, `poc/config.py`

## Data Storage

**Databases:**
- PostgreSQL 16 (primary data store)
  - Connection: `DATABASE_URL` env var
  - Default: `postgresql+psycopg://monai:monai@localhost:5434/monai`
  - Client: SQLAlchemy 2.x ORM with psycopg3 driver (`backend/db.py`)
  - Tables: `accounts`, `transactions` (`backend/models.py`)
  - Custom view: `date_helpers` — materialized relative-date calculations, created on startup (`backend/db.py`)
  - Docker volume: `monai_pgdata` (persistent named volume in `docker-compose.yml`)

**File Storage:**
- Local filesystem only — CSV imports are read from uploaded multipart files directly in memory (`backend/main.py` `POST /import`)

**Caching:**
- None — LLM instance is module-level singleton (`_llm` in `backend/query.py`), reset on each CSV import via `reset_engine()`

## Authentication & Identity

**Auth Provider:**
- None — no authentication system present in v1
- CORS is restricted to localhost origins (`http://localhost:3000`, `http://localhost:3001`) in `backend/main.py`
- Application is designed for local personal use only

## Monitoring & Observability

**Error Tracking:**
- None — no Sentry or equivalent

**Logs:**
- Python `logging` module at INFO level (`logging.basicConfig(level=logging.INFO)` in `backend/main.py`)
- No structured logging or log aggregation

## CI/CD & Deployment

**Hosting:**
- Docker Compose on Linux host (`docker-compose.yml`)
- Three services: `db` (PostgreSQL), `backend` (FastAPI on port 8001), `frontend` (Next.js on port 3001)
- Backend and frontend use `network_mode: host` to reach host Ollama daemon
- Backend port: 8001; Frontend port: 3001

**CI Pipeline:**
- Not detected — no GitHub Actions, CircleCI, or equivalent configuration

## Environment Configuration

**Required env vars (by provider):**

| Var | Required when | Default |
|-----|--------------|---------|
| `DATABASE_URL` | Always | `postgresql+psycopg://monai:monai@localhost:5434/monai` |
| `LLM_PROVIDER` | Always | `ollama` |
| `OLLAMA_BASE_URL` | `LLM_PROVIDER=ollama` | `http://localhost:11434` |
| `OLLAMA_MODEL` | `LLM_PROVIDER=ollama` | `gemma4:31b-cloud` |
| `OLLAMA_EMBED_MODEL` | `LLM_PROVIDER=ollama` | `gemma4:31b-cloud` |
| `ANTHROPIC_API_KEY` | `LLM_PROVIDER=claude` | None |
| `CLAUDE_MODEL` | `LLM_PROVIDER=claude` | `claude-haiku-4-5-20251001` |
| `OPENAI_API_KEY` | `LLM_PROVIDER=openai` | None |
| `OPENAI_MODEL` | `LLM_PROVIDER=openai` | `gpt-4o-mini` |
| `MONAI_API` | Frontend (Docker) | `http://127.0.0.1:8001` |

**Secrets location:**
- No `.env` file detected — environment vars are set directly in `docker-compose.yml` (non-secret defaults) or injected at runtime

## Webhooks & Callbacks

**Incoming:**
- None — no webhook endpoints defined

**Outgoing:**
- None — no outgoing webhook calls

## Data Import

**CSV Import (Wallet app export format):**
- Endpoint: `POST /import` in `backend/main.py`
- Accepts multipart file upload (UTF-8 or UTF-8-BOM encoded)
- Parsed by `backend/importer.py`
- Frontend proxies `/api/*` to backend via Next.js rewrites (`ui/next.config.js`)

---

*Integration audit: 2026-06-20*
