---
phase: 03-multi-page-ui-shell-settings
plan: 02
subsystem: api
tags: [fastapi, sqlalchemy, alembic, pydantic, llama-index, settings, audit-log]

# Dependency graph
requires:
  - phase: 01-schema-foundation-auth
    provides: Alembic migration tooling, require_api_key auth dependency, AuditLog model/idiom
  - phase: 02-agentic-loop-confirm-before-write
    provides: reset_engine() cache-invalidation singleton in backend/query.py
provides:
  - "app_settings DB-backed key-value table (migration 003) overriding env-var LLM/preference defaults"
  - "GET /settings (public, masked) and PUT /settings (auth-gated, partial upsert) endpoints"
  - "configure_llm(overrides=...) runtime reconfiguration path, backward-compatible with the zero-arg call"
  - "masked-only AuditLog trail for every settings write"
affects: [03-03-settings-ui, phase-4-cashflow-ui, phase-5-investments]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Settings service module (backend/settings.py) as the single source of truth for effective config, mirroring the importer's get-or-create upsert idiom"
    - "SettingsOut/SettingsUpdate schema-per-role pair, matching TransactionCreate/TransactionOut convention"
    - "Masked-secret-at-rest-in-audit pattern: raw key values run through mask_key() before ever touching AuditLog.after"

key-files:
  created:
    - alembic/versions/003_app_settings.py
    - backend/settings.py
    - backend/tests/test_settings.py
  modified:
    - backend/models.py
    - backend/schemas.py
    - backend/config.py
    - backend/main.py

key-decisions:
  - "configure_llm's claude branch used Settings.embed_model = MockEmbedding(embed_dim=1) instead of the pre-existing 'local' string, which eagerly resolved to HuggingFaceEmbedding (a package not installed in this repo) — fixes a latent bug this plan's tests were the first to exercise"
  - "SettingsUpdate field validators treat both None and empty-string as 'keep existing' (skip validation) for llm_provider/price_data_source, consistent with upsert_settings' blank-means-keep-existing semantics for API keys"

patterns-established:
  - "Pattern: DB-backed settings override env-var config via get_effective_settings(db, raw_keys=bool) — raw_keys=True is strictly internal (configure_llm only), never exposed via API"

requirements-completed: [UI-03, UI-04]

coverage:
  - id: D1
    description: "GET /settings returns effective settings with masked API keys, never raw key fields, base_currency defaulting to IDR"
    requirement: "UI-03"
    verification:
      - kind: unit
        ref: "backend/tests/test_settings.py#test_get_settings_returns_defaults"
        status: pass
      - kind: unit
        ref: "backend/tests/test_settings.py#test_key_is_masked_never_raw"
        status: pass
    human_judgment: false
  - id: D2
    description: "PUT /settings requires MONAI_API_KEY auth (401 without it) and updates provider/model, reflected on a subsequent GET"
    requirement: "UI-03"
    verification:
      - kind: unit
        ref: "backend/tests/test_settings.py#test_put_settings_requires_key"
        status: pass
      - kind: unit
        ref: "backend/tests/test_settings.py#test_put_updates_provider_and_get_reflects"
        status: pass
    human_judgment: false
  - id: D3
    description: "Blank/absent key field on PUT keeps the previously stored key (no clobber)"
    requirement: "UI-03"
    verification:
      - kind: unit
        ref: "backend/tests/test_settings.py#test_blank_key_keeps_existing"
        status: pass
    human_judgment: false
  - id: D4
    description: "base_currency and price_data_source persist across a fresh GET; price_data_source validated against the locked enum"
    requirement: "UI-04"
    verification:
      - kind: unit
        ref: "backend/tests/test_settings.py#test_preferences_persist"
        status: pass
    human_judgment: false
  - id: D5
    description: "PUT that changes an LLM field (provider/model/keys) calls reset_engine() exactly once; a preferences-only PUT does not call it"
    requirement: "UI-03"
    verification:
      - kind: unit
        ref: "backend/tests/test_settings.py#test_llm_change_resets_engine"
        status: pass
    human_judgment: false
  - id: D6
    description: "Every accepted PUT /settings writes exactly one masked-only AuditLog row (entity=settings) — raw key values never persisted to the audit trail"
    verification:
      - kind: unit
        ref: "backend/tests/test_settings.py#test_key_is_masked_never_raw (indirectly, via GET-body assertion) + manual psql inspection of audit_log rows"
        status: pass
    human_judgment: false
  - id: D7
    description: "Provider switch takes effect on the next real chat request against a live LLM daemon (no container restart needed) — not automatable in this sandbox (no Ollama/LLM daemon available)"
    verification: []
    human_judgment: true
    rationale: "Requires a live Ollama/Claude/OpenAI daemon to observe an actual chat response using the newly configured provider; this sandbox has no LLM daemon. reset_engine() invocation itself is proven by D5; the end-to-end 'next request uses new provider' behavior needs a human/live-environment check per 03-VALIDATION.md."

# Metrics
duration: 45min
completed: 2026-07-04
status: complete
---

# Phase 3 Plan 2: Settings Persistence Backend Summary

**DB-backed app_settings table with masked-key GET/PUT /settings endpoints that reconfigure the live LLM singleton and audit every write, satisfying UI-03/UI-04's backend half.**

## Performance

- **Duration:** 45 min
- **Started:** 2026-07-04T02:03:00Z
- **Completed:** 2026-07-04T02:48:28Z
- **Tasks:** 3 (RED test suite, migration+model+service+config, GREEN routes)
- **Files modified:** 7 (2 created migration/service, 1 created test file, 4 modified existing)

## Accomplishments

- `app_settings(key, value, updated_at)` table via Alembic migration 003 (down_revision `7b4e9f1a6c52`), applied cleanly to a live Postgres volume
- `backend/settings.py`: `get_effective_settings(db, raw_keys=False)` (DB overrides env defaults), `upsert_settings(db, patch)` (keep-existing-on-blank semantics, returns whether an LLM-relevant field changed), `mask_key(raw)` (bullet-last4 masking)
- `GET /settings` (public) and `PUT /settings` (auth-gated via existing `require_api_key`) in `backend/main.py`, following the same public-read/auth-write/reset_engine idiom already used for `POST /transactions`
- `configure_llm(overrides: dict | None = None)` backward-compatible extension — the zero-arg call in `query.py`'s `_get_llm()` is unchanged; overrides take precedence over env vars per field
- Every accepted `PUT /settings` writes exactly one `AuditLog(entity="settings", operation="update")` row whose `after` payload has any key fields pre-masked — verified by direct psql inspection that no raw key string is ever persisted
- `backend/tests/test_settings.py`: 7 tests covering the full contract (defaults, auth gate, provider round-trip, masking, blank-key-keep-existing, preference persistence, reset_engine call-count gating)
- Full backend suite green: 58 passed, 12 skipped (pre-existing, unrelated to this plan), 0 failed

## Task Commits

Each task was committed atomically:

1. **Task 1: Failing settings test suite (RED)** - `cd11798` (test)
2. **Task 2: Migration, model, schemas, settings service, configure_llm overrides** - `b02da55` (feat)
3. **Task 3: GET/PUT /settings routes with runtime reconfigure + audit (GREEN)** - `30c06a5` (feat)

**Plan metadata:** committed as part of this SUMMARY (see final commit below)

_Note: Task 1 alone follows the RED convention (test-only commit); Tasks 2-3 combined migration/model/schema plumbing with the route implementation per the plan's task boundaries, not a strict per-symbol TDD split._

## Files Created/Modified

- `alembic/versions/003_app_settings.py` - Creates `app_settings` table (key/value/updated_at), down_revision `7b4e9f1a6c52`
- `backend/settings.py` - `mask_key`, `get_effective_settings`, `upsert_settings`, setting-key constants
- `backend/tests/test_settings.py` - 7-test contract suite for GET/PUT /settings
- `backend/models.py` - Added `AppSetting` ORM model (mirrors `AuditLog`'s JSONB/`server_default` idiom)
- `backend/schemas.py` - Added `SettingsOut`/`SettingsUpdate` with locked-enum field validators for `llm_provider`/`price_data_source`
- `backend/config.py` - `configure_llm(overrides=None)`; fixed a latent claude-branch bug (see Deviations)
- `backend/main.py` - Added `GET /settings`, `PUT /settings` routes with masked audit logging + conditional `configure_llm`/`reset_engine` reconfiguration

## Decisions Made

- **MockEmbedding over a new package install for the claude branch's embed_model:** the pre-existing `Settings.embed_model = "local"` line eagerly resolves to `HuggingFaceEmbedding`, which requires the `llama-index-embeddings-huggingface` package (not installed, not in `backend/requirements.txt`). Since no embedding-based retrieval is used anywhere in this app's tool-router agent, switching to `llama_index.core.embeddings.MockEmbedding(embed_dim=1)` (already part of the installed `llama-index-core` dependency) is behaviorally inert for this codebase and avoids adding a new external dependency to fix a pre-existing latent bug.
- **Blank string treated as "keep existing" for all `SettingsUpdate` fields, not just API keys:** the field validators for `llm_provider`/`price_data_source` only reject non-empty values outside the locked enum, letting an empty string pass through validation so `upsert_settings`' blank-means-skip semantics apply uniformly across every field, not only the two key fields the plan's tests explicitly exercise.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed configure_llm() claude branch ImportError on first real exercise**
- **Found during:** Task 3 (running `test_put_updates_provider_and_get_reflects`, which is the first test in the repo's history to actually call `configure_llm()` with `provider="claude"`)
- **Issue:** `Settings.embed_model = "local"` triggers eager resolution via `resolve_embed_model()`, which for the string `"local"` requires `llama-index-embeddings-huggingface` — a package not installed and not listed in `backend/requirements.txt`. This is a pre-existing bug in `backend/config.py` that no prior test exercised (no test previously called `configure_llm()` with a non-default provider).
- **Fix:** Replaced `Settings.embed_model = "local"` with `Settings.embed_model = MockEmbedding(embed_dim=1)` from `llama_index.core.embeddings` (already installed, zero new dependencies). No embeddings are actually used by this app's `FunctionAgent`-based tool router, so this is behaviorally inert.
- **Files modified:** `backend/config.py`
- **Verification:** `test_put_updates_provider_and_get_reflects` passes; full backend suite green (58 passed, 12 skipped, 0 failed)
- **Committed in:** `30c06a5` (Task 3 commit)

---

**Total deviations:** 1 auto-fixed (1 bug fix, Rule 1)
**Impact on plan:** Necessary to make the plan's own specified test (`test_put_updates_provider_and_get_reflects`, which PUTs `llm_provider=claude`) pass without introducing a new dependency or altering the plan's test assertions. No scope creep — fix is scoped to the exact code path this plan's tests exercise for the first time.

## Issues Encountered

- **Sandbox had no live Postgres despite the environment notes claiming one was running.** `docker` was unavailable in this worktree (`/var/run/docker.sock` not present) and nothing was listening on port 5434. Postgres 16 was already installed as a system package (`postgresql-16`), so the cluster was started (`pg_ctlcluster 16 main start`), reconfigured to listen on port 5434 (`/etc/postgresql/16/main/postgresql.conf`, `port = 5434`) to match `DATABASE_URL`'s default, and the `monai` role + database were created to match the project's expected connection string. `alembic upgrade head` then applied migrations 001-002 cleanly before this plan's migration 003 was added. This is a sandbox/environment setup gap, not a code issue — resolved locally to enable running the plan's live-DB verification steps as specified.

## User Setup Required

None - no external service configuration required. (Note: the sandbox Postgres port reconfiguration above was a one-time local environment fix, not a change to the project's documented setup — `docker-compose.yml`'s Postgres service already targets port 5434 by design.)

## Next Phase Readiness

- Backend settings persistence + reconfiguration engine is complete and tested; plan 03-03 (browser Settings UI) can now build directly against `GET/PUT /settings` without further backend changes.
- `configure_llm(overrides=...)` is available for any future phase needing programmatic LLM reconfiguration.
- No blockers. The one item requiring human/live-environment verification (D7 — provider switch observed end-to-end against a real chat request) is explicitly out of scope for this sandbox per the plan's own `<verification>` section and is not a gate on plan completion.

---
*Phase: 03-multi-page-ui-shell-settings*
*Completed: 2026-07-04*
