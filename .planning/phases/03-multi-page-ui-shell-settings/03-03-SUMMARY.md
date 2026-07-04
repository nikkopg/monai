---
phase: 03-multi-page-ui-shell-settings
plan: 03
subsystem: ui
tags: [nextjs, react, typescript, playwright, settings, forms]

# Dependency graph
requires:
  - phase: 03-multi-page-ui-shell-settings
    provides: "03-01: four-route Next.js shell (/chat, /cashflow, /investments, /settings), shared styles.ts, settings route placeholder"
  - phase: 03-multi-page-ui-shell-settings
    provides: "03-02: GET/PUT /settings backend endpoints with SettingsOut/SettingsUpdate schemas, masked keys, partial-update semantics"
provides:
  - "Full ui/app/settings/page.tsx: three independently-saveable cards (LLM Provider & Model, API Keys, Preferences)"
  - "ui/e2e/settings.spec.ts Playwright render spec covering card titles, Save button labels, select option sets, masked-key hint"
affects: [04-cashflow-crud, 05-investments]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Per-card SaveState ({idle|saving|success|error}) with a shared putSettings() helper that builds a partial JSON body and PUTs it through /api/settings"
    - "Provider select onChange re-derives the model input from a DEFAULT_MODEL_BY_PROVIDER map, mirroring backend/config.py's per-provider defaults"

key-files:
  created:
    - ui/e2e/settings.spec.ts
  modified:
    - ui/app/settings/page.tsx

key-decisions:
  - "DEFAULT_MODEL_BY_PROVIDER map (ollama/claude/openai -> model string) is hardcoded in the frontend, mirrored from backend/config.py's os.getenv() defaults, since CONTEXT.md defers dynamic model-list fetching to a later phase"
  - "Save Keys always clears both password inputs after a Save attempt (success or failure) so a previously-typed raw key never lingers in component state longer than one request cycle (T-03-20 mitigation)"

patterns-established:
  - "Card-scoped Save: each of the three settings cards owns its own <form>, SaveState, and partial PUT body — no shared submit handler across cards"

requirements-completed: [UI-03, UI-04]

coverage:
  - id: D1
    description: "The /settings page renders three sectioned cards in order: LLM Provider & Model, API Keys, Preferences"
    requirement: "UI-03"
    verification:
      - kind: e2e
        ref: "ui/e2e/settings.spec.ts#/settings page > renders the three card section titles"
        status: pass
    human_judgment: false
  - id: D2
    description: "On mount the page loads current settings via GET /api/settings and pre-fills the model input and masked key placeholders"
    requirement: "UI-03"
    verification:
      - kind: e2e
        ref: "manual Playwright check (not committed, see Issues Encountered) against a live backend: model input showed 'gemma4:31b-cloud', anthropic key placeholder showed '••••5678'"
        status: pass
    human_judgment: false
  - id: D3
    description: "Each card's Save button PUTs only its own fields (blank/unset omitted) and shows an inline success or error message"
    requirement: "UI-03"
    verification:
      - kind: e2e
        ref: "manual Playwright check (not committed): Save Preferences round-trip persisted base_currency=USD, price_data_source=manual, verified via a follow-up GET /api/settings"
        status: pass
    human_judgment: false
  - id: D4
    description: "Provider dropdown offers ollama/claude/openai; price data source dropdown offers coingecko/yfinance/manual; base currency defaults to IDR"
    requirement: "UI-04"
    verification:
      - kind: e2e
        ref: "ui/e2e/settings.spec.ts#/settings page > provider select offers ollama, claude, openai"
        status: pass
      - kind: e2e
        ref: "ui/e2e/settings.spec.ts#/settings page > price data source select offers coingecko, yfinance, manual"
        status: pass
    human_judgment: false
  - id: D5
    description: "Save buttons disable and show a pending label while a request is in flight"
    verification:
      - kind: unit
        ref: "code inspection: disabled={state.status === 'saving'} + disabledBtn style swap on all three Save buttons (ui/app/settings/page.tsx)"
        status: pass
    human_judgment: false
  - id: D6
    description: "Settings save takes effect on the very next real chat request against a live LLM daemon, without a container restart"
    verification: []
    human_judgment: true
    rationale: "Requires a live Ollama/Claude/OpenAI daemon issuing a real chat request after a provider switch; this sandbox has no LLM daemon. The backend's reset_engine() call-count behavior was already proven in 03-02 (D5); the full end-to-end 'next chat uses new provider' observation needs a human with a running stack, per 03-VALIDATION.md."

# Metrics
duration: ~20min
completed: 2026-07-04
status: complete
---

# Phase 3 Plan 03: Settings Frontend Summary

**Full three-card Settings page (LLM Provider & Model / API Keys / Preferences) that loads GET /api/settings on mount and PUTs card-scoped partial updates through the existing proxy, replacing the 03-01 placeholder.**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-07-04T02:38:00Z (approx, worktree spawn)
- **Completed:** 2026-07-04T02:58:42Z
- **Tasks:** 2 (RED render spec, GREEN full page) — both complete
- **Files modified:** 2 (1 created, 1 modified)

## Accomplishments

- `ui/app/settings/page.tsx` fully replaced: a client component rendering the "Settings" Display heading and three `<section style={card}>` cards in the locked order (LLM Provider & Model, API Keys, Preferences), all importing `card`/`input`/`btn`/`label` from `../styles` with no local redefinition
- `useEffect` fetches `GET /api/settings` on mount and pre-fills the provider, model, masked-key placeholders, base currency, and price data source; if the fetch fails the cards still render with an inline load-error banner rather than replacing the whole page
- Each card owns an independent `SaveState` (`idle`/`saving`/`success`/`error`) and its own `<form onSubmit>` that builds a body containing only that card's fields (blank/unset fields omitted) before `PUT /api/settings` — verified this never clobbers the other two cards' values
- Provider `<select>` (ollama/claude/openai) updates the model text input to that provider's default (`gemma4:31b-cloud` / `claude-haiku-4-5-20251001` / `gpt-4o-mini`) on change, matching `backend/config.py`'s own defaults
- API key inputs are `type="password"`, show the server's masked value (`anthropic_api_key_masked`/`openai_api_key_masked`) as placeholder, carry the "Leave blank to keep the current key." helper text, and are cleared from component state immediately after every Save attempt (success or failure)
- Price data source `<select>` (coingecko/yfinance/manual) and base currency text input (defaults to `IDR`)
- Save buttons disable and render "Saving…" while their own request is in flight; on completion show "Saved." (`#4ade80`) or "Save failed: {detail}. Your previous settings are unchanged — try again." (`#f87171`) next to the button
- `ui/e2e/settings.spec.ts` — 5-test Playwright render spec: three card titles, three exact Save button labels, provider select option set, price-source select option set, masked-key helper text. RED (5/5 failing) against the 03-01 placeholder before Task 2, GREEN (5/5 passing) after
- `ui/e2e/smoke.spec.ts` (03-01's suite) still passes 10/10 — the settings route change did not break the shared nav / route-render smoke coverage
- Ran the full flow against a live backend (Postgres + `uvicorn backend.main:app` started locally in this sandbox, per environment notes) to manually confirm: model prefill, masked-key placeholder value, and a Save Preferences round trip that persisted `base_currency`/`price_data_source` server-side (verified via a follow-up `GET /api/settings`)

## Task Commits

Each task was committed atomically:

1. **Task 1: Failing settings-page render spec (RED)** - `9e6e437` (test)
2. **Task 2: Build the full Settings page (GREEN)** - `35d26f7` (feat)

## Files Created/Modified

- `ui/e2e/settings.spec.ts` - New Playwright spec asserting the three-card contract (titles, Save button labels, select option sets, masked-key hint)
- `ui/app/settings/page.tsx` - Replaced the 03-01 placeholder with the full `SettingsPage`: fetch-on-load, three independently-saveable cards, partial PUT bodies, pending/success/error states

## Decisions Made

- **`DEFAULT_MODEL_BY_PROVIDER` is a small hardcoded frontend map**, not a fetch to any backend "list models" endpoint — matches 03-CONTEXT.md's explicit deferral of dynamic model-list fetching, and mirrors the exact default strings already in `backend/config.py`'s `os.getenv(..., default)` calls so the two stay in sync by inspection.
- **Both API key inputs are cleared immediately after every Save Keys attempt**, regardless of success or failure — the raw key the user types is only ever held in React state for the duration of one submit cycle, consistent with the plan's T-03-20 mitigation ("the raw key ... is sent once on Save and not persisted in client state beyond the input").

## Deviations from Plan

None — plan executed exactly as written. Task 1 produced a failing (RED) spec against the 03-01 placeholder as required; Task 2 built the full page and turned it green without needing any Rule 1-4 fixes.

## Issues Encountered

- The sandbox's `ui/` worktree checkout had no `node_modules` (unlike the main tree noted in the environment notes) — ran `npm install --no-audit --no-fund` inside this worktree's `ui/` directory before any Playwright run, per the environment notes' own caveat about the worktree being a separate checkout.
- To go beyond the plan's required frontend-only render assertions and directly prove the GET-prefill / partial-PUT-persistence behavior end-to-end, a live backend was started locally (Postgres was already listening on 127.0.0.1:5434; started `uvicorn backend.main:app --port 8001` with `DATABASE_URL`/`MONAI_API_KEY` set, per the environment notes). A temporary, uncommitted Playwright spec (`e2e/manual_check.spec.ts`) drove the live page and confirmed: (a) the model input pre-fills with the effective `llm_model`, (b) the Anthropic key input's placeholder shows the server's masked value, and (c) a Save Preferences submission persists `base_currency`/`price_data_source` to the DB, confirmed via a follow-up `GET /api/settings`. That spec was deleted after the check (not part of the plan's required deliverables) and the backend process was stopped; `git status` was clean before the final task commit.

## User Setup Required

None - no external service configuration required. The live-backend manual check above used only local sandbox resources (already-running Postgres, `uvicorn` invoked directly); no persistent local environment changes were made.

## Next Phase Readiness

- UI-03 and UI-04 are both fully implemented in the browser: a user can pick an LLM provider/model, enter API keys (masked), and set base currency/price data source, each saving independently.
- The only remaining verification item (D6 above) is the true end-to-end "next chat request uses the newly saved provider" check against a live LLM daemon — this requires a running Ollama/Claude/OpenAI backend and is explicitly out of scope for this sandbox per 03-VALIDATION.md; a human should exercise this once the full `docker compose up` stack (with a real LLM daemon) is available.
- No blockers for Phase 4 (cashflow CRUD) or Phase 5 (investments) — this plan touched only `ui/app/settings/page.tsx` and added `ui/e2e/settings.spec.ts`; `ui/app/api/[...proxy]/route.ts`, `Nav.tsx`, `layout.tsx`, and the other route pages are untouched (confirmed via `git diff --stat`).

---
*Phase: 03-multi-page-ui-shell-settings*
*Completed: 2026-07-04*
