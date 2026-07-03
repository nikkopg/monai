# Phase 3: Multi-Page UI Shell + Settings - Pattern Map

**Mapped:** 2026-07-03
**Files analyzed:** 13
**Analogs found:** 12 / 13

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|-----------------|---------------|
| `ui/app/layout.tsx` | provider (server layout) | request-response | `ui/app/layout.tsx` (existing, modified) | exact |
| `ui/app/components/Nav.tsx` | component | event-driven (client nav) | `ui/app/page.tsx` (ProposalCard component + hooks usage) | role-match |
| `ui/app/styles.ts` | utility (shared constants) | transform | `ui/app/page.tsx` lines 49-81 (inline style consts) | exact (extraction) |
| `ui/app/page.tsx` (root, rewritten) | route | request-response | Next.js convention; no existing root-redirect analog in repo | no-analog (pattern-only) |
| `ui/app/chat/page.tsx` | component/route | streaming (SSE) | `ui/app/page.tsx` (existing, being split) | exact (source of move) |
| `ui/app/cashflow/page.tsx` | component/route | CRUD | `ui/app/page.tsx` (existing, being split — manual-entry form + recent tx list) | exact (source of move) |
| `ui/app/investments/page.tsx` | component (static) | request-response | `ui/app/page.tsx` card sections (structure only, no state) | role-match |
| `ui/app/settings/page.tsx` | component/route | CRUD (GET+PUT) | `ui/app/page.tsx` manual-entry form (`addTx`-style fetch + form state) | role-match |
| `backend/settings.py` | service | CRUD | `backend/importer.py` (`_get_or_create_account` upsert-style helper) + `backend/query.py` (singleton/config pattern) | role-match |
| `backend/models.py` (add `AppSetting`) | model | CRUD | `backend/models.py` `AuditLog`/`PriceCache` classes (simple key-value-ish tables with JSONB) | exact |
| `backend/schemas.py` (add `SettingsOut`, `SettingsUpdate`) | model (DTO) | transform | `backend/schemas.py` `TransactionCreate`/`TransactionOut` pair | exact |
| `backend/main.py` (add `GET/PUT /settings`) | controller/route | request-response | `backend/main.py` `GET/POST /transactions` (lines 69-104) | exact |
| `backend/config.py` (extend `configure_llm`) | config | transform | `backend/config.py` `configure_llm()` (existing, being extended in place) | exact |
| `alembic/versions/003_app_settings.py` | migration | batch | `alembic/versions/002_new_tables.py` | exact |
| `ui/tests/nav.spec.ts` (Playwright smoke test) | test | request-response | none — first frontend test file in repo | no-analog |

## Pattern Assignments

### `ui/app/layout.tsx` (server layout)

**Analog:** `ui/app/layout.tsx` (current, 22 lines) — modify in place, keep server component.

**Current full file** (to extend, not replace):
```tsx
export const metadata = {
  title: "monai",
  description: "Personal wealth intelligence",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          fontFamily:
            "system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif",
          background: "#0f1115",
          color: "#e6e8eb",
        }}
      >
        {children}
      </body>
    </html>
  );
}
```

**Change required:** import and render `<Nav/>` before `{children}`. Do NOT add `"use client"` here — RESEARCH.md Pitfall 5 explicitly warns against this; keep `layout.tsx` a server component and push the `usePathname` hook down into `Nav.tsx`.

---

### `ui/app/components/Nav.tsx` (new)

**Analog:** No direct nav analog exists yet in the repo (this is the first shared nav). Follow RESEARCH.md's Pattern 2 code example verbatim (it was derived from this codebase's style conventions) and reuse the hook-usage idiom from `ui/app/page.tsx`.

**Client-component + hook idiom** (source: `ui/app/page.tsx` lines 1-3):
```tsx
"use client";

import { useEffect, useRef, useState } from "react";
```
Apply the same `"use client"` placement convention to `Nav.tsx`, importing `usePathname` from `next/navigation` and `Link` from `next/link` instead.

**Style-object convention to follow** (source: `ui/app/page.tsx` lines 49-81 — see Shared Patterns below): define nav-specific colors inline as `React.CSSProperties`, matching the existing dark palette (`#0f1115` background, `#1a1d23` card, `#2a2e37` border, `#3b82f6` accent, `#e6e8eb` text, `#9aa0a6` muted).

---

### `ui/app/styles.ts` (new — extracted shared constants)

**Analog:** `ui/app/page.tsx` lines 49-81 (the `card`/`input`/`btn`/`label` const block being extracted).

**Exact block to move verbatim into `ui/app/styles.ts`, then export:**
```tsx
// ---------------------------------------------------------------------------
// Inline style objects — dark palette (CLAUDE.md: inline React.CSSProperties only)
// ---------------------------------------------------------------------------

export const card: React.CSSProperties = {
  background: "#1a1d23",
  border: "1px solid #2a2e37",
  borderRadius: 12,
  padding: 20,
  marginBottom: 20,
};
export const input: React.CSSProperties = {
  background: "#0f1115",
  border: "1px solid #2a2e37",
  borderRadius: 8,
  color: "#e6e8eb",
  padding: "10px 12px",
  fontSize: 14,
  width: "100%",
  boxSizing: "border-box",
};
export const btn: React.CSSProperties = {
  background: "#3b82f6",
  color: "white",
  border: "none",
  borderRadius: 8,
  padding: "10px 18px",
  fontSize: 14,
  cursor: "pointer",
  fontWeight: 600,
};
export const label: React.CSSProperties = {
  fontSize: 12,
  color: "#9aa0a6",
  marginBottom: 4,
  display: "block",
};
```
All four new/moved pages (`chat`, `cashflow`, `investments`, `settings`) import from here: `import { card, input, btn, label } from "../styles";` — no file should redefine these locally after extraction (CONTEXT.md decision).

---

### `ui/app/page.tsx` (root — rewritten to redirect)

**Pattern (from RESEARCH.md Pattern 3, no repo analog since this is a net-new redirect page):**
```tsx
import { redirect } from "next/navigation";
export default function RootPage() {
  redirect("/chat"); // throws NEXT_REDIRECT; must NOT be wrapped in try/catch
}
```
Stays a server component — no `"use client"`.

---

### `ui/app/chat/page.tsx` (moved, intact)

**Analog:** current `ui/app/page.tsx` (851 lines) — this IS the source file being split, not copied from elsewhere.

**What moves here (verbatim, no rewrite):** `"use client"` directive; `Tx`/`TraceStep`/`Proposal` types that are chat-only; `ProposalCard` component; the ask-box state, SSE `fetch("/api/query-stream")` reader loop, and JSX under "Ask about your finances". Import `card`, `input`, `btn`, `label` from `../styles` instead of defining locally.

**Types block to move if chat-only** (lines 9-43 — confirm which types `cashflow/page.tsx` also needs before splitting; `Tx` is used by both chat trace display and cashflow's recent-tx list, so it may need to move to a shared `types.ts` or be duplicated per CONTEXT.md's "no rewrite" mandate — planner should decide minimal-diff placement).

---

### `ui/app/cashflow/page.tsx` (moved, intact)

**Analog:** current `ui/app/page.tsx` — manual-entry form + recent-transactions list sections (need `Grep`/`Read` at plan time to find exact line ranges for "Log a transaction" and "Recent transactions" JSX, since this pattern-map pass did not need to load the full 851 lines).

**Convention:** `"use client"`, `useEffect`/`useState` for loading `Tx[]` via `fetch("/api/transactions")`, form submit handler posting to `/api/transactions` — same fetch-to-proxy pattern as chat's SSE call but using the buffered (non-stream) path.

---

### `ui/app/investments/page.tsx` (new, static skeleton)

**Analog:** `ui/app/page.tsx` card-section JSX structure (role-match only — reuse the `<section style={card}>` wrapper convention), but this page has **no state and no `"use client"`** (RESEARCH.md Pitfall 5). Server component, static copy: "Holdings and P&L land in Phase 5."

---

### `ui/app/settings/page.tsx` (new)

**Analog:** `ui/app/page.tsx` manual-entry form (fetch + form-state pattern) — closest existing CRUD-form idiom in the codebase.

**Fetch-on-load + POST pattern to follow** (conceptual analog from `page.tsx`'s transaction form): `useEffect` fetching `GET /api/settings` on mount into component state; three independent form sections each with their own `useState` for pending/success/error and their own `PUT /api/settings` call on Save (per-card partial-patch body, `SettingsUpdate.model_dump(exclude_none=True)`-compatible on the frontend — omit unset/blank fields from the JSON body sent).

**Auth note:** the browser-side fetch does NOT need to add auth headers — the `/api/[...proxy]/route.ts` catch-all already injects `MONAI_API_KEY` server-side (see Shared Patterns).

---

### `backend/settings.py` (new)

**Analog:** `backend/config.py:configure_llm()` (env-var-driven config function being extended) + `backend/main.py`'s proposal-apply block (upsert-style DB write with `db.get(...)  or Model(...)`).

**Upsert idiom to follow** (source: RESEARCH.md Pattern 4, consistent with `backend/importer.py:_get_or_create_account` get-or-create style):
```python
def upsert_settings(db, patch: dict) -> bool:
    """Only write keys present AND non-empty in patch — blank string means
    'keep existing', so callers must filter before calling this.
    Returns True if any LLM-relevant field changed (provider/model/keys)."""
    changed_llm = False
    for key, value in patch.items():
        if value is None or value == "":
            continue
        row = db.get(AppSetting, key) or AppSetting(key=key)
        row.value = value
        row.updated_at = datetime.now(timezone.utc)
        db.merge(row)
        if key in {"llm_provider", "llm_model", "anthropic_api_key", "openai_api_key"}:
            changed_llm = True
    db.commit()
    return changed_llm
```

**Masking helper** (net-new, no direct analog — hand-built per RESEARCH.md, `SecretStr` explicitly ruled out):
```python
def mask_key(raw: str | None) -> str | None:
    if not raw:
        return None
    return f"••••{raw[-4:]}" if len(raw) >= 4 else "••••"
```

---

### `backend/models.py` — add `AppSetting`

**Analog:** `AuditLog` class (lines 79-92 of `backend/models.py`) — same shape (simple table, JSONB column, `server_default="now()"` timestamp).

**Pattern to copy:**
```python
class AppSetting(Base):
    """Key-value settings store — DB overrides env-var defaults (Phase 3)."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()", nullable=False
    )
```
(Mirrors `AuditLog`'s `created_at` idiom — use `server_default="now()"` string form as already used throughout `models.py`, not `sa.func.now()`.)

---

### `backend/schemas.py` — add `SettingsOut`, `SettingsUpdate`

**Analog:** `TransactionCreate` / `TransactionOut` pair (lines 24-47 of `backend/schemas.py`) — the established `*Create`/`*Out` (here `*Update`/`*Out`) role-split convention.

**Pattern to copy (schema-per-role, all fields Optional on the Update side):**
```python
class SettingsOut(BaseModel):
    llm_provider: str
    llm_model: str
    anthropic_api_key_masked: str | None
    openai_api_key_masked: str | None
    base_currency: str
    price_data_source: str


class SettingsUpdate(BaseModel):
    llm_provider: str | None = None
    llm_model: str | None = None
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    base_currency: str | None = None
    price_data_source: str | None = None
```
No `ConfigDict(from_attributes=True)` needed since `get_effective_settings()` returns a plain dict, not an ORM row (unlike `AccountOut`/`TransactionOut` which read directly off ORM objects).

---

### `backend/main.py` — add `GET /settings`, `PUT /settings`

**Analog:** `GET/POST /transactions` (lines 69-104) — public GET, auth-protected write, `reset_engine()` called after a write that affects cached state.

**Core pattern to copy** (auth + error handling + reset_engine call, adapted from lines 84-104):
```python
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

**Auth import pattern** (already present, line 32): `from backend.auth import require_api_key` — reuse unchanged, do not build new auth.

**Reset-engine call site precedent** (lines 101-103, in `create_transaction`):
```python
    # New data — invalidate the cached query engine (currency/date context)
    from backend.query import reset_engine
    reset_engine()
```
Same lazy-import-inside-handler convention applies to the settings endpoint.

**Audit log pattern (per CONTEXT.md's resolved open question — write masked-only AuditLog row on every accepted PUT)**, source: `backend/main.py` lines 184-185, 201-202 (proposal-apply block):
```python
db.add(AuditLog(entity="transaction", entity_id=tx.id, operation="add",
                before=None, after=after))
```
Adapt for settings: `db.add(AuditLog(entity="settings", entity_id=None, operation="update", before=None, after=<masked patch dict>))` — never store raw key values in `after`.

---

### `backend/config.py` — extend `configure_llm()`

**Analog:** `backend/config.py:configure_llm()` itself (current, 53 lines) — extended in place, not replaced.

**Current signature/logic to extend (backward-compatibly, per RESEARCH.md Pitfall 1):**
```python
def configure_llm() -> None:
    """Set LlamaIndex Settings.llm + embed_model from LLM_PROVIDER."""
    from llama_index.core import Settings

    provider = os.getenv("LLM_PROVIDER", "ollama").lower()

    if provider == "ollama":
        from llama_index.llms.ollama import Ollama
        from llama_index.embeddings.ollama import OllamaEmbedding
        model = os.getenv("OLLAMA_MODEL", "gemma4:31b-cloud")
        ...
    elif provider == "claude":
        ...
    elif provider == "openai":
        ...
    else:
        raise ValueError(f"Unknown LLM_PROVIDER={provider!r}. Valid: ollama, claude, openai")
```
**Required change:** add `overrides: dict | None = None` parameter; each `os.getenv(...)` call becomes `overrides.get(key) or os.getenv(...)` (see RESEARCH.md Pattern 5 for the exact per-branch diff). Preserve the `ValueError` on unknown provider — matches project convention "domain layer raises ValueError."

---

### `alembic/versions/003_app_settings.py` (new)

**Analog:** `alembic/versions/002_new_tables.py` (full file read) — establishes revision-header format, `op.create_table`/`op.drop_table` symmetry in `upgrade()`/`downgrade()`.

**Header convention to copy** (lines 1-20 of `002_new_tables.py`):
```python
"""add app_settings key-value table

Revision ID: <generate>
Revises: 7b4e9f1a6c52
Create Date: 2026-07-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "<generate>"
down_revision: Union[str, None] = "7b4e9f1a6c52"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
```

**Table pattern to copy** (mirrors `price_cache`'s `fetched_at` / `audit_log`'s `created_at` — `server_default=sa.func.now()` style used in this file, distinct from the `"now()"` string form used in `models.py`; keep consistent with whichever the migration author of `002` used — `sa.func.now()`):
```python
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
Current head revision is `7b4e9f1a6c52` (from `002_new_tables.py`) — confirm no later revision exists before setting `down_revision`.

---

## Shared Patterns

### Auth (write endpoints)
**Source:** `backend/auth.py` (`require_api_key`, full file — `hmac.compare_digest`, fail-closed 503 if `MONAI_API_KEY` unset, 401 on mismatch), applied at `backend/main.py:84` (`dependencies=[Depends(require_api_key)]`).
**Apply to:** `PUT /settings` only. `GET /settings` stays public/unauthenticated, matching `GET /accounts` / `GET /transactions`.

### API proxy (frontend → backend)
**Source:** `ui/app/api/[...proxy]/route.ts` (full file, 130 lines) — catch-all handler injecting `MONAI_API_KEY` header server-side, buffered response path for all non-SSE routes.
**Apply to:** All `fetch("/api/settings")` calls from `ui/app/settings/page.tsx`. **No changes to `route.ts` are needed or wanted** — `/settings` is a small JSON payload that already matches the default (non-`isStream`) buffered branch (RESEARCH.md Pitfall 4 — do not touch this file).

### Error handling (backend)
**Source:** `backend/main.py` line 116-117 (`import_csv`): `except ValueError as e: raise HTTPException(422, str(e))`.
**Apply to:** Any `ValueError` raised inside `get_effective_settings()`/`upsert_settings()` (e.g. invalid `price_data_source` enum value) — same ValueError→422 mapping convention (`backend/schemas.py` Pydantic validation handles most of this automatically via `response_model`/body validation; hand-raised `ValueError` only for logic not expressible as a Pydantic constraint).

### Reset-engine invalidation
**Source:** `backend/query.py` lines 347-351 (`reset_engine()`) + call sites at `backend/main.py` lines 102-103 and 118-119.
**Apply to:** `PUT /settings` handler, gated on `changed_llm` flag returned from `upsert_settings()` — must be called synchronously before the response returns (RESEARCH.md Pitfall 2).

### Inline style-object convention
**Source:** `ui/app/page.tsx` lines 49-81 (moving to `ui/app/styles.ts`, see above).
**Apply to:** All four page files + `Nav.tsx` — no CSS framework, `React.CSSProperties` const objects only, dark palette exact hex values must match existing (`#0f1115`, `#1a1d23`, `#2a2e37`, `#3b82f6`, `#e6e8eb`, `#9aa0a6`).

### Schema-per-role (Pydantic)
**Source:** `backend/schemas.py` `TransactionCreate`/`TransactionOut` pair.
**Apply to:** `SettingsUpdate`/`SettingsOut` pair — see Pattern Assignments above.

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `ui/app/page.tsx` (root redirect, rewritten) | route | request-response | First redirect-only page in the repo; use RESEARCH.md's Next.js-documented `redirect()` pattern directly (no codebase precedent needed — official API). |
| `ui/tests/nav.spec.ts` (Playwright smoke test) | test | request-response | First frontend test file in the repo (`ui/package.json` has no test runner today); no analog to copy from — planner should scaffold `@playwright/test` config from scratch per CONTEXT.md's locked decision (one spec file, dev-dependency only). |
| `ui/app/components/Nav.tsx` (usePathname logic itself) | component | event-driven | No existing client component uses `usePathname`/`next/link` for nav; only the surrounding style/hook *conventions* have analogs (documented above) — the routing logic itself follows RESEARCH.md's Next.js-official pattern. |

## Metadata

**Analog search scope:** `ui/app/`, `backend/`, `alembic/versions/`
**Files scanned:** `ui/app/page.tsx`, `ui/app/layout.tsx`, `ui/app/api/[...proxy]/route.ts`, `backend/config.py`, `backend/query.py`, `backend/main.py`, `backend/models.py`, `backend/schemas.py`, `backend/auth.py`, `alembic/versions/001_baseline.py` (listed, not read — 002 sufficed as analog), `alembic/versions/002_new_tables.py`
**Pattern extraction date:** 2026-07-03
