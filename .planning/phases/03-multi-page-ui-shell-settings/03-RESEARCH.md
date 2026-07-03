# Phase 3: Multi-Page UI Shell + Settings - Research

**Researched:** 2026-07-03
**Domain:** Next.js App Router multi-page restructuring + FastAPI settings persistence + runtime LLM reconfiguration
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Navigation & Route Structure**
- Top horizontal nav bar (app name + 4 links) using `next/link` with `usePathname`
  active-state highlight — client-side transitions satisfy "no full page reload".
- Root `/` redirects to `/chat` (chat is the app's core value).
- The existing chat UI (ask box, SSE streaming, ProposalCard, tool trace) moves from
  `ui/app/page.tsx` to `/chat` intact — no behavior changes.
- The existing manual-entry form and recent-transactions list move to `/cashflow` as
  its interim content; `/investments` renders a real skeleton page stating holdings
  arrive in Phase 5. No blank screens anywhere.

**Settings Persistence & Backend**
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

**Settings Page UX**
- Sectioned cards: "LLM Provider & Model", "API Keys", "Preferences" — each with its
  own Save button and inline success/error message.
- Provider dropdown (ollama / claude / openai) + model text input pre-filled with
  the provider's current/default model. No dynamic model-list fetching (deferred).
- API key inputs are password-type with masked placeholder from the server and a
  "leave blank to keep current key" hint.
- Save buttons disable while pending; result shown as inline status text. No
  test-connection button this phase (deferred).

**Code Structure & Styling**
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

### Deferred Ideas (OUT OF SCOPE)
- Dynamic model-list fetching per provider (e.g. querying Ollama's /api/tags).
- "Test connection" button on the Settings page.
- Any styling re-platform (Tailwind/shadcn) — stays inline-styles this cycle.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-------------------|
| UI-01 | App has distinct Chat, Cashflow, Investment, and Settings pages | Architecture Patterns § Route Split; Code Examples § Root redirect, page skeletons |
| UI-02 | Shared navigation lets the user move between all pages | Architecture Patterns § `<Nav/>` component (usePathname); Common Pitfalls § "use client" boundaries |
| UI-03 | Settings page lets the user configure the LLM provider/model and API keys in-UI | Architecture Patterns § Settings backend (app_settings, GET/PUT, runtime reconfigure); Code Examples § configure_llm DB override, key masking |
| UI-04 | Settings page lets the user configure base currency and the price data source | Architecture Patterns § app_settings schema; same GET/PUT endpoint as UI-03 |
</phase_requirements>

## Summary

This phase is a pure extension of the existing, already-shipped stack — **no new npm
or pip packages are required**. Next.js 14.2.15 App Router already provides everything
needed for the route split (`next/link`, `usePathname`, server-component `redirect()`),
and the backend already has the exact scaffolding this phase needs: Alembic migration
chain, `require_api_key` dependency, Pydantic v2 schema-per-role convention, and the
`reset_engine()` singleton-invalidation pattern used after every write. The work is
almost entirely **moving and composing existing code**, not introducing anything novel.

The two areas requiring genuine design decisions are (1) how `backend/config.py:
configure_llm()` reads DB-backed overrides without breaking its existing env-var
fallback and the tests that rely on it, and (2) the API-key masking round-trip, which
has no built-in FastAPI/Pydantic primitive — it must be hand-built as a pair of
schemas (`SettingsOut` masks, `SettingsUpdate` accepts optional plaintext, blank-means-
keep). Both are well-understood, low-risk patterns with no external library dependency.

**Primary recommendation:** Split `ui/app/page.tsx` mechanically into `/chat` and
`/cashflow` route folders (copy-paste, no rewrites), add a `<Nav/>` client component
in `app/layout.tsx` using `usePathname`, and extend `backend/config.py` so
`configure_llm()` accepts an optional settings dict — sourced from a new
`get_effective_settings()` helper in a new `backend/settings.py` module — with env
vars remaining the fallback when no DB row exists. This keeps `configure_llm()`
backward-compatible with the pattern `_get_llm()` in `query.py` already uses.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Route navigation (/chat, /cashflow, /investments, /settings) | Frontend Server (SSR) — Next.js App Router | Browser (client-side transitions via `next/link`) | Next.js owns route resolution; the actual page transition after the first load is client-side (no full reload), satisfying UI-02. |
| Active-link highlighting | Browser | — | `usePathname()` is a client-only hook; must run in a `"use client"` component re-rendered on navigation. |
| Root `/` → `/chat` redirect | Frontend Server (SSR) | — | `redirect()` in a server component `page.tsx` runs before any client JS ships; simplest, no extra network hop. |
| Settings persistence (`app_settings` table) | Database / Storage | — | Must survive browser sessions and container restarts (criterion 4); a DB table, not env vars or client storage, is the only tier that satisfies this. |
| Settings read/write API (`GET`/`PUT /settings`) | API / Backend | — | Business rule "DB overrides env defaults" and the masking logic must live server-side — the browser must never see full API keys. |
| Runtime LLM reconfiguration | API / Backend | — | `configure_llm()` + `reset_engine()` already live in `backend/config.py` / `backend/query.py`; extending them in place preserves the single source of truth for LLM setup. |
| API key masking (display) | API / Backend (compute mask) | Browser (render masked placeholder) | The mask must be computed server-side from the stored value — the browser only ever receives the already-masked string, never the raw key. |
| Settings form state / validation (client) | Browser | — | Standard controlled-input React state; no server round-trip until Save is clicked (per CONTEXT.md: "No client-side settings cache beyond component state"). |

## Standard Stack

### Core

No new packages this phase. Everything is drawn from already-installed dependencies:

| Library | Version (installed) | Purpose | Why Standard |
|---------|---------|---------|--------------|
| next | 14.2.15 `[VERIFIED: ui/package-lock.json]` | App Router routing, layouts, `redirect()`, `usePathname` | Already the project's frontend framework; App Router route-groups are the standard way to add pages without a rewrite. |
| react / react-dom | 18.3.1 `[VERIFIED: ui/package-lock.json]` | Component model | Existing dependency, unchanged. |
| fastapi | >=0.110.0 `[VERIFIED: backend/requirements.txt]` | `GET`/`PUT /settings` endpoints | Existing dependency, unchanged. |
| sqlalchemy | >=2.0.0 `[VERIFIED: backend/requirements.txt]` | `AppSetting` ORM model | Existing dependency, unchanged. |
| alembic | >=1.13.0 `[VERIFIED: backend/requirements.txt]` | `app_settings` table migration | Existing migration chain (`3a1f8c2d9e04` → `7b4e9f1a6c52`); this phase adds revision 3. |
| pydantic | v2 (via fastapi) `[VERIFIED: backend/schemas.py]` | `SettingsOut` / `SettingsUpdate` schemas | Existing schema-per-role convention (`*Out`, `*Update`) already used for `TransactionOut`/`TransactionCreate`. |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| llama-index-llms-anthropic / -openai / -ollama | >=0.1.0 `[VERIFIED: backend/requirements.txt]` | Provider-specific LLM clients | Already imported lazily inside `configure_llm()` per provider branch — unchanged this phase. |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `redirect()` in server-component `page.tsx` | `next.config.js` `redirects()` | CONTEXT.md leaves this to discretion; `redirect()` keeps routing logic colocated with the App Router and is simpler for a single static root-to-child redirect. `redirects()` config requires a restart to change and is meant for larger redirect tables — unnecessary here. |
| `app_settings` generic key/value JSONB table | Dedicated typed columns (e.g. `settings.llm_provider`, `settings.base_currency`) | CONTEXT.md locks the key-value JSONB shape. A single generic table avoids a schema migration every time a new setting is added — appropriate for a single-user app with a handful of settings, at the cost of losing DB-level type constraints (mitigated by Pydantic validation at the API boundary). |
| Hand-rolled masking function | `pydantic.SecretStr` | `SecretStr` only masks in Python `repr()`/logs, not in JSON serialization the way this phase needs (`••••last4` derived from the stored value, shown even on GET) — it does not solve the round-trip UX requirement. A plain `str` column + a `mask_key()` helper function is simpler and sufficient `[CITED: WebSearch — FastAPI/Pydantic secret-masking patterns]`. |

**Installation:** None — no new packages required this phase.

**Version verification:** `next@14.2.15`, `react@18.3.1` confirmed via `ui/package-lock.json` (already pinned, no upgrade in scope). `fastapi>=0.110.0`, `sqlalchemy>=2.0.0`, `alembic>=1.13.0` confirmed via `backend/requirements.txt` (already pinned, no upgrade in scope). No registry lookups were needed since no new packages are introduced.

## Package Legitimacy Audit

**Not applicable — this phase introduces zero new packages.** All libraries used (Next.js App Router primitives, FastAPI, SQLAlchemy, Alembic, Pydantic v2, LlamaIndex provider clients) are already installed and pinned in `ui/package-lock.json` / `backend/requirements.txt` from prior phases. No `npm install` or `pip install` step is required for this phase's tasks.

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
Browser
  │
  │ GET /            GET /chat, /cashflow, /investments, /settings
  ▼
Next.js App Router (ui/app/)
  ├─ layout.tsx  ──renders──▶ <Nav/> (client component, usePathname)
  │                              │
  │                              ▼ next/link client-side transition (no reload)
  ├─ page.tsx (root)  ──▶ redirect("/chat")            [server component]
  ├─ chat/page.tsx     ──▶ ask box, SSE stream, ProposalCard, tool trace
  ├─ cashflow/page.tsx ──▶ manual-entry form, recent-tx table
  ├─ investments/page.tsx ─▶ static skeleton card (Phase 5 placeholder)
  └─ settings/page.tsx ──▶ 3 cards: Provider, API Keys, Preferences
         │
         │ fetch("/api/settings")  [GET on load, PUT on Save]
         ▼
app/api/[...proxy]/route.ts (existing catch-all)
         │ injects MONAI_API_KEY header server-side
         ▼
FastAPI backend (backend/main.py)
  ├─ GET  /settings   (public)          ──▶ backend/settings.py:get_effective_settings()
  │                                            │  reads app_settings table,
  │                                            │  falls back to env-var defaults,
  │                                            │  masks key fields before return
  └─ PUT  /settings   (require_api_key) ──▶ backend/settings.py:upsert_settings()
                                                │  upserts app_settings rows
                                                │  IF provider/model/key changed:
                                                ▼
                                        backend/config.py:configure_llm(overrides=...)
                                                │
                                                ▼
                                        backend/query.py:reset_engine()
                                                │  clears _llm + _agent_workflow singletons
                                                ▼
                                        next POST /query-stream rebuilds agent
                                        with new provider on first use
```

### Recommended Project Structure

```
ui/app/
├── layout.tsx              # server component; renders <Nav/> + {children}
├── styles.ts                # NEW — extracted card/input/btn/label constants
├── components/
│   └── Nav.tsx               # NEW — "use client"; usePathname-based active nav
├── page.tsx                  # NEW — root; redirect("/chat")
├── chat/
│   └── page.tsx               # MOVED — ask box + SSE + ProposalCard + trace (intact)
├── cashflow/
│   └── page.tsx               # MOVED — manual-entry form + recent-tx table
├── investments/
│   └── page.tsx               # NEW — skeleton card, Phase 5 placeholder copy
├── settings/
│   └── page.tsx               # NEW — 3 sectioned cards, GET on load / PUT per section
└── api/[...proxy]/route.ts   # UNCHANGED — already proxies any /api/* path incl. /api/settings

backend/
├── main.py                   # ADD: GET /settings, PUT /settings routes
├── settings.py                # NEW — get_effective_settings(), upsert_settings(), mask_key()
├── config.py                  # EXTEND: configure_llm(overrides: dict | None = None)
├── query.py                   # UNCHANGED — _get_llm()/reset_engine() already correct
├── models.py                  # ADD: AppSetting ORM model
└── schemas.py                 # ADD: SettingsOut, SettingsUpdate

alembic/versions/
└── 003_app_settings.py        # NEW — creates app_settings(key TEXT PK, value JSONB, updated_at)
```

### Pattern 1: Mechanical page split (no rewrite)

**What:** Move JSX sections of `ui/app/page.tsx` verbatim into new route folders;
do not refactor logic while moving.
**When to use:** Any time an existing single-file page grows into multiple routes and
CONTEXT.md/UI-SPEC state "moved intact — no behavior changes" (as here for `/chat`
and `/cashflow`).
**Example:**
```tsx
// ui/app/chat/page.tsx — everything above "Add transaction" section from the
// old page.tsx, unchanged: ProposalCard component, ask()/SSE logic, JSX for
// the "Ask about your finances" <section style={card}>.
"use client";
import { useEffect, useRef, useState } from "react";
import { card, input, btn, label } from "../styles";
// ...ProposalCard definition unchanged...
export default function ChatPage() {
  // ...ask(), SSE reader loop, proposal state — copied verbatim...
}
```
```tsx
// ui/app/cashflow/page.tsx — "Log a transaction" + "Recent transactions" sections
"use client";
import { useEffect, useState } from "react";
import { card, input, btn, label } from "../styles";
export default function CashflowPage() {
  // ...form state, addTx(), loadTxs(), txs table — copied verbatim...
}
```

### Pattern 2: `<Nav/>` client component with `usePathname`

**What:** Extract active-link nav into its own `"use client"` component so
`layout.tsx` itself stays a server component `[CITED: nextjs.org/docs/app/api-reference/functions/use-pathname]`.
**When to use:** Any shared nav that needs to highlight the current route.
**Example:**
```tsx
// ui/app/components/Nav.tsx
"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/chat", label: "Chat" },
  { href: "/cashflow", label: "Cashflow" },
  { href: "/investments", label: "Investments" },
  { href: "/settings", label: "Settings" },
];

export default function Nav() {
  const pathname = usePathname();
  return (
    <nav style={{ /* sticky, background #1a1d23, borderBottom #2a2e37 — see UI-SPEC */ }}>
      <span style={{ fontWeight: 600, fontSize: 20, color: "#e6e8eb" }}>monai</span>
      {LINKS.map((l) => {
        const active = pathname === l.href || pathname.startsWith(l.href + "/");
        return (
          <Link
            key={l.href}
            href={l.href}
            style={{
              color: active ? "#3b82f6" : "#9aa0a6",
              fontWeight: active ? 600 : 400,
              borderBottom: active ? "2px solid #3b82f6" : "2px solid transparent",
            }}
          >
            {l.label}
          </Link>
        );
      })}
    </nav>
  );
}
```
```tsx
// ui/app/layout.tsx — stays a server component; renders Nav once
import Nav from "./components/Nav";
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body style={{ margin: 0, background: "#0f1115", color: "#e6e8eb", fontFamily: "..." }}>
        <Nav />
        {children}
      </body>
    </html>
  );
}
```

### Pattern 3: Root redirect via server component

**What:** `redirect()` from `next/navigation`, called directly (not inside try/catch)
in a server component `page.tsx` `[CITED: nextjs.org/docs/app/api-reference/functions/redirect]`.
**When to use:** Static, single-target redirects colocated with routing logic.
**Example:**
```tsx
// ui/app/page.tsx
import { redirect } from "next/navigation";
export default function RootPage() {
  redirect("/chat"); // throws NEXT_REDIRECT; must NOT be wrapped in try/catch
}
```

### Pattern 4: Settings — masked round-trip schema pair

**What:** Two Pydantic schemas per settings resource: an `Out` schema that only ever
serializes masked/derived fields, and an `Update` schema whose secret fields are
`Optional[str] = None`, where `None`/empty means "keep existing" `[CITED: WebSearch — FastAPI/Pydantic secret field patterns; SecretStr does not solve API round-trip masking]`.
**When to use:** Any settings/credentials form where the UI must show "a key is set"
without ever re-exposing the real value.
**Example:**
```python
# backend/schemas.py
class SettingsOut(BaseModel):
    llm_provider: str
    llm_model: str
    anthropic_api_key_masked: str | None   # e.g. "••••ab12" or None if unset
    openai_api_key_masked: str | None
    base_currency: str
    price_data_source: str

class SettingsUpdate(BaseModel):
    llm_provider: str | None = None
    llm_model: str | None = None
    anthropic_api_key: str | None = None    # blank/absent = keep current
    openai_api_key: str | None = None
    base_currency: str | None = None
    price_data_source: str | None = None
```
```python
# backend/settings.py
def mask_key(raw: str | None) -> str | None:
    if not raw:
        return None
    return f"••••{raw[-4:]}" if len(raw) >= 4 else "••••"

def upsert_settings(db, patch: dict) -> None:
    """Only write keys present AND non-empty in patch — blank string means
    'keep existing', so callers must filter before calling this."""
    for key, value in patch.items():
        if value is None or value == "":
            continue  # keep-existing semantics — do not overwrite with blank
        row = db.get(AppSetting, key) or AppSetting(key=key)
        row.value = value
        row.updated_at = datetime.now(timezone.utc)
        db.merge(row)
    db.commit()
```

### Pattern 5: `configure_llm()` extended with DB overrides (backward-compatible)

**What:** Add an optional `overrides: dict | None` parameter that takes precedence
over env vars, without changing the function's existing no-arg call sites
(`_get_llm()` in `query.py`, and any test that calls `configure_llm()` directly).
**When to use:** Whenever runtime-configurable settings must override 12-factor env
defaults without breaking the existing env-only code path.
**Example:**
```python
# backend/config.py
def configure_llm(overrides: dict | None = None) -> None:
    from llama_index.core import Settings
    overrides = overrides or {}
    provider = overrides.get("llm_provider") or os.getenv("LLM_PROVIDER", "ollama").lower()
    if provider == "ollama":
        model = overrides.get("llm_model") or os.getenv("OLLAMA_MODEL", "gemma4:31b-cloud")
        # ...unchanged base_url / embed_model handling...
    elif provider == "claude":
        model = overrides.get("llm_model") or os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
        api_key = overrides.get("anthropic_api_key") or os.getenv("ANTHROPIC_API_KEY")
        Settings.llm = Anthropic(model=model, api_key=api_key)
    # ...openai branch mirrors claude...
```
```python
# backend/query.py — _get_llm() passes DB-backed overrides
def _get_llm():
    global _llm
    if _llm is None:
        from backend.settings import get_effective_settings
        configure_llm(overrides=get_effective_settings(raw_keys=True))
        from llama_index.core import Settings
        _llm = Settings.llm
    return _llm
```

### Anti-Patterns to Avoid

- **Rewriting the chat/cashflow UI while moving it:** CONTEXT.md is explicit — "moves
  from `ui/app/page.tsx` to `/chat` intact — no behavior changes." Any refactor here
  risks silently breaking the SSE parsing loop or the `ProposalCard` expiry logic that
  Phase 2 verification already exercised.
- **Making `layout.tsx` a `"use client"` component:** would force the entire app shell
  to re-render on every navigation and lose the benefit of `usePathname` being scoped
  to a small child component `[CITED: nextjs.org/docs/app/api-reference/functions/use-pathname]`.
- **Returning the full API key on `GET /settings` "just this once for convenience":**
  violates the explicit locked decision ("Full keys never round-trip to the browser
  after save") and is a real security regression, not a style choice.
- **Silently overwriting a stored key with an empty string on PUT:** must be filtered
  server-side (see Pattern 4) — the UI's "leave blank to keep current key" hint is a
  promise the backend must enforce, not just a placeholder string.
- **Reading `os.environ` directly inside route handlers for settings values:** breaks
  the "DB overrides env defaults" contract and creates two divergent sources of truth;
  all reads must go through `get_effective_settings()`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|--------------|-----|
| Schema migration for `app_settings` | Manual `CREATE TABLE` script run by hand | Alembic revision (existing chain, revision 3 after `7b4e9f1a6c52`) | FND-01 requirement: all schema changes via Alembic, preserving existing data; the project already has a working Alembic setup — no reason to deviate. |
| API-key auth on `PUT /settings` | New auth mechanism / header scheme | Existing `require_api_key` dependency (`backend/auth.py`) | Already fail-closed (503 if unset), constant-time compare, tested in `test_auth.py`. Reuse, don't duplicate. |
| Client-side route matching for nav highlighting | Manual `window.location` parsing | `usePathname()` from `next/navigation` | Built-in, reactive to client-side transitions, officially documented pattern `[CITED: nextjs.org]`. |
| Secret encryption at rest | Custom AES/Fernet wrapper around `app_settings.value` | Plaintext JSONB column (same trust model as the existing `MONAI_API_KEY` env var, which is also plaintext) `[ASSUMED]` | Single-user, self-hosted deployment (per CLAUDE.md) — the app already stores its own auth key as plaintext env var; adding app-level encryption for LLM provider keys without a broader secrets-management story (KMS, vault) would be inconsistent complexity for the same threat model. Flagged in Assumptions Log — confirm with user if compliance requirements exist beyond self-hosted single-user use. |

**Key insight:** Every mechanism this phase needs (migrations, auth, singleton
invalidation, schema-per-role) already exists in the codebase from Phases 1–2. The
risk in this phase is not "which library to pick" but "don't duplicate or diverge
from the pattern that's already there."

## Common Pitfalls

### Pitfall 1: `configure_llm()` signature change breaks existing call sites/tests
**What goes wrong:** Adding a required parameter to `configure_llm()` breaks any
existing caller that invokes it with zero args (`_get_llm()` in `query.py`).
**Why it happens:** `configure_llm()` is called from `query.py:_get_llm()` with no
arguments today; a naive edit that makes the new parameter required (not defaulted)
is a breaking change caught only at runtime on first `/query` or `/query-stream` call.
**How to avoid:** Add the new parameter as `overrides: dict | None = None` with a
safe default that preserves today's env-only behavior when omitted.
**Warning signs:** `TypeError: configure_llm() missing 1 required positional argument`
on any endpoint that triggers `_get_llm()`.

### Pitfall 2: Provider switch doesn't take effect without `reset_engine()`
**What goes wrong:** User changes provider in Settings, saves successfully, but the
next chat question still uses the old provider.
**Why it happens:** `_llm` and `_agent_workflow` are lazy module-level singletons in
`query.py` — they are only rebuilt when `None`. Just updating `app_settings` in the
DB does nothing until the singletons are cleared.
**How to avoid:** The `PUT /settings` handler must call `backend.query.reset_engine()`
(same pattern already used after `/transactions`, `/import`, and proposal confirm)
whenever `llm_provider`, `llm_model`, or any API key field is part of the accepted
patch — this is explicitly required by CONTEXT.md and success criterion 3.
**Warning signs:** Manual test: change provider, save, ask a question — if the answer
still comes from the old provider (e.g. still hits Ollama after switching to Claude),
`reset_engine()` was not called or was called before the DB write committed.

### Pitfall 3: PUT partial update clobbers unrelated settings
**What goes wrong:** Saving just the "Preferences" card (base currency + price source)
accidentally blanks out the LLM provider or API keys because a single `PUT /settings`
endpoint received a full-object body with unset fields defaulting to `None`/empty.
**Why it happens:** CONTEXT.md specifies three independently-saveable cards, each
with its own Save button — but a single generic `PUT /settings` endpoint is easy to
implement as "replace everything" instead of "merge only provided fields."
**How to avoid:** `SettingsUpdate` fields must all be `Optional` with `None` default;
the upsert logic (Pattern 4) must skip any field that is `None` or an empty string —
never treat "not sent" the same as "clear this value" for anything except the
explicit "leave blank to keep current key" case (which is itself a skip, not a clear).
**Warning signs:** Saving Preferences causes the next chat question to silently fall
back to the default Ollama provider even though Claude was configured moments ago.

### Pitfall 4: SSE streaming continues to work unchanged — don't "fix" what isn't broken
**What goes wrong:** A well-intentioned refactor of `ui/app/api/[...proxy]/route.ts`
during the page split (e.g. "let's also proxy /settings specially") accidentally
touches the `isStream` gate that makes `/query-stream` work, reintroducing the
buffering bug Phase 2 fixed.
**Why it happens:** The proxy route is a single catch-all file; any edit to it is a
blast-radius risk for the one endpoint (`query-stream`) that requires the
non-buffered `ReadableStream` passthrough path.
**How to avoid:** `/api/settings` needs zero changes to `route.ts` — it already
matches the catch-all `[...proxy]` pattern and takes the standard (non-`isStream`)
buffered path, which is correct for a small JSON payload. Do not touch `route.ts`
in this phase at all; if it compiles and existing chat SSE still streams after the
page split, the proxy layer needs no changes.
**Warning signs:** Chat responses stop appearing incrementally (whole answer arrives
at once after a long pause) — sign that `route.ts`'s `isStream` branch was disturbed.

### Pitfall 5: `"use client"` boundary placed too high, breaking SSR of static pages
**What goes wrong:** Marking `layout.tsx` or the `/investments` skeleton page as
`"use client"` unnecessarily forces client-side rendering for content that has no
interactivity, increasing bundle size and losing the SSR benefit for the
`/investments` static skeleton.
**Why it happens:** Copy-pasting `"use client"` from `/chat`/`/cashflow` (which
genuinely need it for `useState`/`useEffect`) onto every new file "to be safe."
**How to avoid:** Only `Nav.tsx`, `chat/page.tsx`, `cashflow/page.tsx`, and
`settings/page.tsx` need `"use client"` (they use hooks/state). `layout.tsx`,
root `page.tsx` (redirect), and `investments/page.tsx` (static skeleton, no state)
should remain server components.
**Warning signs:** `investments/page.tsx` ships a JS bundle chunk despite having no
interactive elements; Next.js build output shows it as a client-rendered route when
it should be static/server-rendered.

### Pitfall 6: Existing `test_auth.py`/`test_agent.py` assumptions about env-only config
**What goes wrong:** `backend/auth.py` reads `_CONFIGURED_KEY` from `os.environ` at
**module import time** (not per-request) — the exact same pattern this phase should
avoid repeating for LLM settings (env-at-import-time is why `conftest.py` needs a
`monkeypatch.setattr` workaround instead of just setting the env var). If
`get_effective_settings()` is similarly cached at import time, tests that expect
DB-driven overrides to take effect immediately will flake.
**Why it happens:** The established `MONAI_API_KEY` pattern (read once, patch the
module attribute in tests) is a reasonable model for a value that truly never
changes at runtime — but LLM settings are explicitly meant to change at runtime
(criterion 3), so the same "read once at import" pattern must NOT be copied for
`get_effective_settings()`. It should query the DB (or an explicitly-reset cache)
on each `_get_llm()` call, matching the existing `reset_engine()` invalidation model.
**How to avoid:** Do not cache `get_effective_settings()` results across requests
except via the same `_llm`/`_agent_workflow` singleton lifecycle already gated by
`reset_engine()`. No new caching layer needed — the existing lazy-singleton pattern
already re-evaluates settings correctly as long as `reset_engine()` is called on save.
**Warning signs:** New `test_settings.py` tests pass individually but fail when run
after a prior test that changed settings, or the running dev server keeps using the
first-loaded provider even after a successful `PUT /settings` + UI refresh.

## Code Examples

Verified/derived patterns:

### Alembic migration for `app_settings`
```python
# alembic/versions/003_app_settings.py — Source: existing 002_new_tables.py pattern
"""add app_settings key-value table

Revision ID: <generate>
Revises: 7b4e9f1a6c52
Create Date: 2026-07-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "<generate>"
down_revision = "7b4e9f1a6c52"

def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.Text, primary_key=True),
        sa.Column("value", JSONB, nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

def downgrade() -> None:
    op.drop_table("app_settings")
```

### FastAPI settings endpoints (backend/main.py additions)
```python
# Source: pattern mirrors existing /transactions (GET public / POST auth-protected)
from backend.settings import get_effective_settings, upsert_settings
from backend.schemas import SettingsOut, SettingsUpdate

@app.get("/settings", response_model=SettingsOut)
def read_settings(db: Session = Depends(get_session)):
    return get_effective_settings(db)

@app.put("/settings", response_model=SettingsOut, dependencies=[Depends(require_api_key)])
def write_settings(patch: SettingsUpdate, db: Session = Depends(get_session)):
    changed_llm = upsert_settings(db, patch.model_dump(exclude_none=True))
    if changed_llm:
        from backend.config import configure_llm
        from backend.query import reset_engine
        configure_llm(overrides=get_effective_settings(db, raw_keys=True))
        reset_engine()
    return get_effective_settings(db)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|-------------------|---------------|--------|
| Single `ui/app/page.tsx` (851 lines) serving all UI | Four route folders (`/chat`, `/cashflow`, `/investments`, `/settings`) under App Router | This phase | Enables independent evolution of each page (Phase 4 cashflow dashboard, Phase 5 investments) without one file growing unbounded. |
| LLM provider/keys configured only via env vars (`.env`, docker-compose) | Env vars remain defaults; DB (`app_settings`) can override at runtime without restart | This phase | Satisfies criterion 3 — no container restart needed to switch providers; env vars become "initial/fallback config" rather than the only config surface. |

**Deprecated/outdated:** None — this phase adds capability, it does not replace or
deprecate an existing pattern (env-var config remains valid as the fallback layer).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|----------------|
| A1 | API keys stored in `app_settings.value` (JSONB) as plaintext, with no application-level encryption at rest, is an acceptable trust model | Don't Hand-Roll; Security Domain | If the user's threat model requires encryption at rest (e.g. shared host, backup exposure), this needs a KMS/Fernet-key design not currently scoped — would add a new dependency and a key-management story mid-phase. Low likelihood given CLAUDE.md's explicit single-user/self-hosted/local-first framing and the existing plaintext `MONAI_API_KEY` env var precedent, but not verified with the user directly for Phase 3. |
| A2 | `usePathname().startsWith(l.href + "/")` is sufficient for active-state matching on nested routes (none exist yet, but future-proofing) | Architecture Patterns § Pattern 2 | If a future sub-route (e.g. `/cashflow/edit/1`) is added without matching this convention, the nav highlight could show wrong state — low impact, cosmetic only. |
| A3 | A single `PUT /settings` endpoint (not three separate endpoints per card) is acceptable even though the UI has three independently-saveable Save buttons | Architecture Patterns § Pattern 4; Common Pitfalls § 3 | CONTEXT.md doesn't explicitly mandate one vs. three endpoints — assumed one endpoint with partial-patch semantics is simpler and matches the "PUT /settings (auth-protected) upserts values" wording literally. If the planner/user wants three distinct endpoints for cleaner audit-log-style separation, this is a straightforward within-scope change. |

**If this table is empty:** N/A — see entries above; none block planning, all are reasonable defaults consistent with locked decisions and project conventions.

## Open Questions

1. **Should `PUT /settings` write an `AuditLog` row like other write endpoints do?**
   - What we know: Every other write path (`/transactions`, proposal confirm) writes
     an `AuditLog` row (CHAT-06 requirement). `/settings` is a new write path but is
     not part of the CHAT-* requirement family (UI-03/UI-04 don't mention audit).
   - What's unclear: Whether settings changes (especially API key updates) should be
     audited for security-review purposes, distinct from the financial-data audit log.
   - Recommendation: Out of scope for UI-03/UI-04 literally, but flag for the planner
     as a cheap addition (`AuditLog(entity="settings", ...)`, storing masked values
     only) — a natural low-cost security improvement, not a blocker.

2. **Does the price data source setting (`coingecko`/`yfinance`/`manual`) need
   Phase-3-time validation, or is it inert until Phase 5 wires it up?**
   - What we know: CONTEXT.md states "Phase 5 consumes the price source setting" —
     Phase 3 only needs to store and display it.
   - What's unclear: Whether the dropdown values need to exactly match string
     literals Phase 5's price adapters will expect, to avoid a silent rename later.
   - Recommendation: Use the exact three strings from CONTEXT.md/UI-SPEC
     (`coingecko`, `yfinance`, `manual`) as the stored values — treat this as a
     locked enum now so Phase 5 doesn't need a data migration for existing settings.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|--------------|-----------|---------|----------|
| Node.js | Next.js dev/build | ✓ | not probed this session (Docker: 20-alpine, host: 22.x per CLAUDE.md) | — |
| npm | package management | ✓ (per `ui/package-lock.json` presence) | — | — |
| Python 3.12+ | Backend | ✓ (project already running Phase 1/2 code) | — | — |
| PostgreSQL | `app_settings` storage | ✓ (existing `monai-db` container, port 5434) | 16-alpine `[VERIFIED: docker-compose.yml]` | — |
| Alembic | Migration | ✓ | >=1.13.0 `[VERIFIED: backend/requirements.txt]` | — |
| Ollama (local LLM) | Default provider testing | Not probed this session — external daemon expected at `http://localhost:11434` per CLAUDE.md | — | Settings page must remain usable/testable even if Ollama is down; switching to `claude`/`openai` provider in Settings does not require Ollama to be running. |

**Missing dependencies with no fallback:** None identified — no new external tool/service dependency introduced this phase.

**Missing dependencies with fallback:** Ollama availability is not required for this phase's UI/API work (only for actually exercising the default provider's chat responses, which is unchanged Phase 2 behavior).

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework (backend) | pytest >=8.0.0, `pytest-asyncio` (auto mode) — `[VERIFIED: pyproject.toml, backend/requirements.txt]` |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`, `testpaths = ["backend/tests"]`) |
| Framework (frontend) | None installed — `ui/package.json` has no test runner (`[VERIFIED: ui/package.json]`) |
| Quick run command | `pytest backend/tests/test_settings.py -x` (once created) |
| Full suite command | `pytest backend/tests -x` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|---------------------|--------------|
| UI-01 | Four distinct routes render without error | manual/browser (no frontend test runner) | N/A — visual/browser check per route | N/A |
| UI-02 | Nav present on every page; client-side transition (no reload); active link highlights | manual/browser | N/A | N/A |
| UI-03 | `GET /settings` returns masked keys; `PUT /settings` updates provider and next chat request uses it | unit + integration | `pytest backend/tests/test_settings.py -x` | ❌ Wave 0 |
| UI-03 | `PUT /settings` requires `MONAI_API_KEY` (401 without it, matching existing auth pattern) | unit | `pytest backend/tests/test_settings.py::test_put_settings_requires_key -x` | ❌ Wave 0 |
| UI-03 | Empty/absent key field on PUT keeps existing key (does not clobber) | unit | `pytest backend/tests/test_settings.py::test_blank_key_keeps_existing -x` | ❌ Wave 0 |
| UI-04 | `PUT /settings` persists base currency + price source; survives a fresh `GET` (simulating a new browser session) | integration | `pytest backend/tests/test_settings.py::test_preferences_persist -x` | ❌ Wave 0 |

Frontend page-render and nav-interaction checks (UI-01, UI-02) have no automated
frontend test framework in this project — they are **manual-only by necessity**, not
by choice. This is a pre-existing project gap (no `jest`/`vitest`/`playwright` in
`ui/package.json`), not something to introduce net-new in this phase unless the
planner decides a minimal Playwright smoke test is worth the added dependency
surface — flagged as a discretionary planner decision, not a requirement of this
research.

### Sampling Rate
- **Per task commit:** `pytest backend/tests/test_settings.py -x` (once it exists)
- **Per wave merge:** `pytest backend/tests -x` (full backend suite — cheap, existing suite is fast per `conftest.py`'s session-scoped `TestClient`)
- **Phase gate:** Full suite green before `/gsd-verify-work`; UI-01/UI-02 require manual browser verification per the note above.

### Wave 0 Gaps
- [ ] `backend/tests/test_settings.py` — covers UI-03, UI-04 (GET/PUT round-trip, masking, keep-existing-key, LLM reconfigure triggers `reset_engine()`, persistence across simulated sessions)
- [ ] No new fixtures needed — `conftest.py`'s existing `client`/`api_key` fixtures cover the new endpoints (write endpoint pattern is identical to existing `/transactions`).
- [ ] Framework install: none — pytest already installed and configured.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|----------------|---------|---------------------|
| V2 Authentication | Partial | `PUT /settings` reuses existing `require_api_key` (static API key, `hmac.compare_digest`, fail-closed 503 on misconfiguration) — no new auth mechanism introduced. |
| V3 Session Management | No | Single-user, stateless API-key model; no sessions in this app. |
| V4 Access Control | Yes | `GET /settings` is intentionally public (read-only, matches existing `GET /accounts`/`GET /transactions` pattern) but returns **masked** key fields only — access control for the sensitive part (raw keys) is enforced by never serializing them, not by gating the GET endpoint. |
| V5 Input Validation | Yes | `SettingsUpdate` Pydantic schema validates provider/price-source enum values, currency string, etc., at the API boundary — same pattern as `TransactionCreate`. |
| V6 Cryptography | Partial `[ASSUMED]` | No new cryptography introduced — API keys stored as plaintext JSONB, consistent with the existing plaintext `MONAI_API_KEY` env var. See Assumption A1 — flagged for user confirmation if this trust model is insufficient. |
| V13 API Security | Yes | `PUT /settings` is a state-changing endpoint and correctly requires the API key per the project's established write-endpoint convention (D-06 in STATE.md decisions). |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|------------------------|
| API key leakage via `GET /settings` response | Information Disclosure | Never serialize raw key values in `SettingsOut` — only masked derived strings (Pattern 4). Verified by a dedicated test (`test_settings.py`) asserting the raw key never appears in the GET response body. |
| Settings tampering by unauthenticated client | Tampering | `PUT /settings` gated by `require_api_key`, same as all other write endpoints — no new pattern needed. |
| Blank-string key overwrite silently deleting a configured provider key | Tampering / availability | Upsert logic must treat empty string same as absent (skip), enforced server-side, not just via UI placeholder text (Pitfall 3). |
| Settings change not taking effect (stale singleton) creating a false sense of "provider switched" while still calling the old (possibly now-invalid) provider | Repudiation / trust | `reset_engine()` called synchronously within the same `PUT /settings` request that changed LLM-relevant fields, before returning 200 to the client (Pitfall 2). |

## Sources

### Primary (HIGH confidence)
- `ui/app/page.tsx`, `ui/app/layout.tsx`, `ui/app/api/[...proxy]/route.ts` — direct codebase read, existing shipped code this phase extends.
- `backend/config.py`, `backend/query.py`, `backend/main.py`, `backend/auth.py`, `backend/models.py`, `backend/schemas.py`, `backend/db.py` — direct codebase read.
- `alembic/versions/001_baseline.py`, `002_new_tables.py`, `alembic/env.py`, `alembic.ini` — direct codebase read, existing migration chain and conventions this phase's migration must follow.
- `backend/tests/conftest.py`, `test_auth.py` — direct codebase read, existing test-fixture and auth-testing conventions.
- `docker-compose.yml`, `ui/package.json`, `ui/package-lock.json`, `backend/requirements.txt`, `pyproject.toml` — direct codebase read, verifying installed versions and test config.
- `.planning/phases/03-multi-page-ui-shell-settings/03-CONTEXT.md`, `03-UI-SPEC.md` — locked user decisions and design contract for this phase.

### Secondary (MEDIUM confidence)
- [Next.js redirect() docs](https://nextjs.org/docs/app/api-reference/functions/redirect) — WebSearch-confirmed, official docs.
- [Next.js usePathname docs](https://nextjs.org/docs/app/api-reference/functions/use-pathname) — WebSearch-confirmed, official docs.
- FastAPI/Pydantic secret-masking pattern discussion — WebSearch aggregate of `pydantic/pydantic` GitHub issues and `fastapi/fastapi` discussions confirming `SecretStr` does not solve API round-trip masking; hand-built mask function is the practical approach.

### Tertiary (LOW confidence)
- None used as a basis for a recommendation in this document.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages; all versions verified directly from `package-lock.json`/`requirements.txt` in the repo.
- Architecture: HIGH — patterns are direct extensions of code already reviewed line-by-line in this session (config.py, query.py, main.py, the proxy route, the Alembic chain).
- Pitfalls: HIGH — all six pitfalls are derived from concrete, observed characteristics of this codebase (singleton caching, import-time env reads, catch-all proxy route, existing test patterns), not generic/external speculation.

**Research date:** 2026-07-03
**Valid until:** 2026-08-02 (30 days — stable, no fast-moving external dependency; re-verify if Next.js or FastAPI major version changes before then)
