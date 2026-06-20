# Concerns & Technical Debt

**Analysis Date:** 2026-06-20

Status reference: `TODOS.md` is the authoritative live backlog; this document
captures *risk-oriented* observations from a code read. Severity is this
analysis's judgment for a self-hosted, single-user v1.

## Security

### HIGH — Backend exposed on the LAN, no auth
- `docker-compose.yml` runs `backend` with `network_mode: host` and the API
  binds `0.0.0.0:8001`, so it is reachable at `<machine>:8001` on the whole LAN,
  not just localhost. There is **no authentication** on any endpoint
  (`backend/main.py`) — anyone on the network can read all transactions and
  `POST /import`/`/transactions`.
- CORS is locked to localhost (`backend/main.py`), but CORS does not stop direct
  HTTP clients — it only constrains browsers.
- Tracked in `TODOS.md` ("Access binding"): decide between binding `127.0.0.1`,
  adding a `MONAI_API_KEY` check, or accepting+documenting LAN exposure.

### LOW — Default DB credentials in compose
- `monai:monai` Postgres credentials are hardcoded in `docker-compose.yml`.
  Acceptable for local single-user, but should not ship to any shared host.
- No `.env` / secret management; cloud LLM keys (`ANTHROPIC_API_KEY`,
  `OPENAI_API_KEY`) would be injected at runtime — fine, but undocumented.

### LOW — `gemma4:31b-cloud` default is a *cloud* model
- The default `OLLAMA_MODEL`/`OLLAMA_EMBED_MODEL` is `gemma4:31b-cloud`
  (`backend/config.py`, `docker-compose.yml`), which routes through ollama.com —
  contradicting the README's "all data stays on your machine / local by default"
  privacy promise. A truly local default (e.g. a 7B/8B local model) would match
  the stated privacy posture. (Observation 94 noted a downstream ollama.com
  failure.)

## Data Integrity / Correctness

### MEDIUM — No database migrations
- Schema is created via `Base.metadata.create_all()` on startup
  (`backend/db.py:init_db`). There is **no Alembic or migration tooling**. Any
  future column change (the planned `holdings`, `portfolio_events`,
  `transfer_pair_id`, `base_currency`/`fx_rate` in root `ARCHITECTURE.md`/`TODOS.md`)
  will require manual SQL on existing volumes — `create_all` won't alter
  existing tables.

### MEDIUM — Money stored correctly in DB, but floated in transit
- ORM uses `Numeric(18, 2)` for `amount` (`backend/models.py`) — correct. But
  tools cast to `float()` for aggregation/return (`backend/tools.py`) and the
  Pydantic `TransactionOut.amount` is `float` (`backend/schemas.py`), and the UI
  uses JS numbers. Rounding tolerance is even baked into a test
  (`abs(net - (inc - spend)) < 1.0`). Fine for display/queries at current scale;
  worth noting before any feature that sums to the cent over millions of rows.

### LOW — Single-currency assumption is load-bearing
- The importer **silently skips** any row whose currency differs from the first
  row's (`backend/importer.py:parse_csv`, logged at WARNING only) and the schema
  drops `base_currency`/`fx_rate` (validated as a non-issue: 0/5608 skipped). If
  a foreign-currency account is ever added, those transactions vanish from
  imports with only a log line — no surfaced error. `TODOS.md` parks this
  knowingly.

## Reliability

### MEDIUM — LLM is a hard runtime dependency with no fallback
- `/query` requires a reachable LLM (Ollama daemon at `:11434`, or a cloud key).
  Cold-start latency is 10–30s; with the cloud default it needs network. There's
  no caching of routed results and no graceful degradation beyond the honest
  refusal string. The query feature is fully down if the model is unreachable.

### LOW — `reset_engine()` is vestigial / misleading
- `backend/query.py:reset_engine()` only nulls the `_llm` singleton; its own
  docstring says "the router holds no per-import state." It's called after every
  `/transactions` and `/import` (`backend/main.py`), forcing an LLM
  re-instantiation (and re-`configure_llm()`) that buys nothing. Minor waste +
  confusing name.

### LOW — `@app.on_event("startup")` is deprecated
- `backend/main.py` uses the deprecated FastAPI `on_event` startup hook rather
  than the lifespan context manager. Works today; will warn/break on a future
  FastAPI major.

## Maintainability

### MEDIUM — Two parallel codebases / duplicated parser logic
- `poc/` (Approach A, SQLite/Streamlit) and `backend/` (Approach C) coexist with
  **two divergent Wallet CSV parsers** (`poc/parser.py` path-based vs.
  `backend/importer.py` text-based) that share logic but can drift. `TODOS.md`
  flags `poc/` for deletion; until then it's dead weight and a source of
  confusion (the root `ARCHITECTURE.md` module-layout section is also stale,
  describing planned `importer/`, `query/`, `docker/` dirs that don't exist).

### LOW — Stale top-level docs
- `README.md` still says "🚧 not usable yet" / "Getting started: not ready,"
  but the stack runs via `docker compose up -d --build`. Root `ARCHITECTURE.md`
  module layout predates the actual `backend/` structure. `TODOS.md` already
  lists the README update.

### LOW — Committed data/artifacts in the repo
- `poc/monai.db` (SQLite DB) and `report_*.csv` (real Wallet exports — personal
  financial data) are committed. The CSVs contain real transaction history;
  consider whether they belong in version control.

## Testing Gaps

See `TESTING.md`. Briefly: no tests for `backend/main.py` endpoints, no test for
`backend/importer.py:parse_csv`, no end-to-end `ask()` test, no frontend tests,
no coverage tooling, and **no CI pipeline**. The tested core (tool SQL invariants
+ router JSON parsing) is the right priority, but the HTTP/import surface is
unguarded against regressions. `TODOS.md` calls out the backend API + importer
tests as "Now" work.

## Operations

- **No backup rotation** — `TODOS.md` (eng-review D6) wants cron-based
  `pg_dump` retention for the `monai_pgdata` volume; not implemented.
- **No observability** — INFO-level stdlib logging only; no error tracking,
  metrics, or health beyond `GET /health`.
- **Platform-locked compose** — `network_mode: host` is Linux-only; Mac/Windows
  require switching to bridge networking + `host.docker.internal` (documented in
  root `ARCHITECTURE.md`, but the compose file itself only works on Linux as-is).

## Summary (priority order)

| # | Severity | Concern | Location |
|---|----------|---------|----------|
| 1 | HIGH | LAN-exposed API with no authentication | `docker-compose.yml`, `backend/main.py` |
| 2 | MEDIUM | No DB migration tooling (blocks planned schema additions) | `backend/db.py` |
| 3 | MEDIUM | LLM is a hard dependency, no fallback/caching | `backend/query.py` |
| 4 | MEDIUM | Two parallel codebases + duplicated parsers; `poc/` not deleted | `poc/`, `backend/importer.py` |
| 5 | MEDIUM | Money floated in transit/tests despite `Numeric` storage | `backend/tools.py`, `backend/schemas.py` |
| 6 | LOW | Cloud-default model contradicts "local/private" promise | `backend/config.py` |
| 7 | LOW | Untested HTTP/import surface, no CI | `backend/tests/` |
| 8 | LOW | Stale README/ARCHITECTURE, committed personal CSV data | `README.md`, `report_*.csv` |

---

*Concerns analysis: 2026-06-20*
