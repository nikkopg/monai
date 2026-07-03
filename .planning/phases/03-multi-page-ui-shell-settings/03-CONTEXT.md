# Phase 3: Multi-Page UI Shell + Settings - Context

**Gathered:** 2026-07-03
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous — recommended answers accepted per user pre-authorization)

<domain>
## Phase Boundary

Turn the single-page Next.js app into a four-page app with shared navigation, and
add a Settings page that configures the backend from the browser.

This phase delivers:
- Four distinct routes — `/chat`, `/cashflow`, `/investments`, `/settings` — each a
  real page (no blank screens, no 404s). Root `/` redirects to `/chat` (UI-01).
- A shared navigation component on every page with client-side transitions (no full
  page reload) and active-link highlighting (UI-02).
- A Settings page that lets the user pick LLM provider + model, enter API keys
  (masked in display), and save — subsequent chat requests use the new provider
  without a backend restart (UI-03).
- Settings for base currency and preferred price data source, persisted server-side
  so they survive browser sessions (UI-04).
- Backend support: a new `app_settings` table (Alembic migration), `GET /settings`
  and `PUT /settings` endpoints (write auth-protected via `MONAI_API_KEY`), and a
  runtime LLM reconfigure path.

Out of scope (own phases): cashflow dashboard charts + full CRUD UI (Phase 4);
holdings/prices/P&L (Phase 5); MCP server (Phase 6).

**Requirements covered:** UI-01, UI-02, UI-03, UI-04.

</domain>

<decisions>
## Implementation Decisions

### Navigation & Route Structure
- Top horizontal nav bar (app name + 4 links) using `next/link` with `usePathname`
  active-state highlight — client-side transitions satisfy "no full page reload".
- Root `/` redirects to `/chat` (chat is the app's core value).
- The existing chat UI (ask box, SSE streaming, ProposalCard, tool trace) moves from
  `ui/app/page.tsx` to `/chat` intact — no behavior changes.
- The existing manual-entry form and recent-transactions list move to `/cashflow` as
  its interim content; `/investments` renders a real skeleton page stating holdings
  arrive in Phase 5. No blank screens anywhere.

### Settings Persistence & Backend
- New `app_settings` key-value table (key TEXT PK, value JSONB, updated_at) created
  by an Alembic migration — settings must persist across browser sessions
  (criterion 4) and be readable by the backend at request time (criterion 3).
- `GET /settings` returns current effective settings (DB overrides env defaults);
  `PUT /settings` (auth-protected) upserts values. On save that changes provider,
  model, or keys, the backend re-runs LLM configuration from DB-backed values and
  resets the agent singleton (existing `reset_engine` pattern in `backend/query.py`).
- API keys are stored server-side in `app_settings`. `GET /settings` returns masked
  values only (e.g. `••••last4`); an empty/absent key field on PUT means "keep the
  existing key". Full keys never round-trip to the browser after save.
- Base currency (default `IDR`) and price data source (`coingecko` | `yfinance` |
  `manual`) are stored in the same table; Phase 5 consumes the price source setting.

### Settings Page UX
- Sectioned cards: "LLM Provider & Model", "API Keys", "Preferences" — each with its
  own Save button and inline success/error message.
- Provider dropdown (ollama / claude / openai) + model text input pre-filled with
  the provider's current/default model. No dynamic model-list fetching (deferred).
- API key inputs are password-type with masked placeholder from the server and a
  "leave blank to keep current key" hint.
- Save buttons disable while pending; result shown as inline status text. No
  test-connection button this phase (deferred).

### Code Structure & Styling
- Keep the existing inline `React.CSSProperties` style-object convention; extract
  the shared constants (`card`, `input`, `btn`, `label`) into a shared module (e.g.
  `ui/app/styles.ts`) so all four pages reuse them.
- Shared `<Nav/>` client component rendered once in `app/layout.tsx`.
- Settings API calls go through the existing catch-all `/api/[...proxy]` route
  handler (server-side `MONAI_API_KEY` injection already works there).
- Server settings are the source of truth; the Settings page fetches
  `GET /api/settings` on load. No client-side settings cache beyond component state.

### Claude's Discretion
- Exact visual styling of the nav (spacing, colors) within the existing aesthetic.
- Settings key naming scheme inside `app_settings`.
- Whether `/` uses `redirect()` in a server component or Next.js `redirects()` config.
- How provider-specific model defaults are surfaced in the UI.

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `ui/app/page.tsx` (851 lines) — complete chat UI with SSE streaming, ProposalCard,
  collapsible tool trace, manual entry form, recent-transactions list. Split, don't
  rewrite.
- `ui/app/api/[...proxy]/route.ts` — server-side catch-all proxy injecting
  `MONAI_API_KEY`; reuse for `/api/settings`.
- `backend/config.py:configure_llm()` — provider-switch logic reading env vars;
  extend to read DB-backed overrides.
- `backend/query.py:reset_engine()` — existing singleton-reset pattern for applying
  new LLM config at runtime.
- Alembic migration chain from Phase 1 (`alembic/versions/`) — add `app_settings`
  as a new revision.
- `require_api_key` dependency (`backend/main.py`) — attach to `PUT /settings`.

### Established Patterns
- Inline `React.CSSProperties` style objects; no CSS framework.
- Pydantic v2 schemas per role (`*Out`, `*Request`) in `backend/schemas.py`.
- Domain errors raise `ValueError` → API maps to `HTTPException(422)`.
- Parameterized SQL / SQLAlchemy ORM only.
- 12-factor env config with defaults in `backend/config.py`.

### Integration Points
- `ui/app/layout.tsx` — nav mounts here.
- `backend/main.py` — new `/settings` GET/PUT endpoints.
- `alembic/versions/` — new migration for `app_settings`.
- `backend/config.py` + `backend/query.py` — runtime LLM reconfiguration path.

</code_context>

<specifics>
## Specific Ideas

- Settings save must take effect on the next chat request without restarting the
  backend container (success criterion 3 phrasing: "subsequent chat requests use
  the new provider").
- Masked key display format: show only enough to identify the key (`••••` + last 4).

</specifics>

<deferred>
## Deferred Ideas

- Dynamic model-list fetching per provider (e.g. querying Ollama's /api/tags).
- "Test connection" button on the Settings page.
- Any styling re-platform (Tailwind/shadcn) — stays inline-styles this cycle.

</deferred>
