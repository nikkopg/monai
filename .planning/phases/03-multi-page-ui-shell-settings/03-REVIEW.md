---
phase: 03-multi-page-ui-shell-settings
reviewed: 2026-07-04T03:07:31Z
depth: standard
files_reviewed: 17
files_reviewed_list:
  - ui/app/styles.ts
  - ui/app/components/Nav.tsx
  - ui/app/layout.tsx
  - ui/app/page.tsx
  - ui/app/chat/page.tsx
  - ui/app/cashflow/page.tsx
  - ui/app/investments/page.tsx
  - ui/app/settings/page.tsx
  - ui/e2e/smoke.spec.ts
  - ui/e2e/settings.spec.ts
  - ui/playwright.config.ts
  - backend/settings.py
  - backend/models.py
  - backend/schemas.py
  - backend/config.py
  - backend/main.py
  - backend/tests/test_settings.py
  - alembic/versions/003_app_settings.py
findings:
  critical: 0
  warning: 7
  info: 2
  total: 9
status: issues_found
---

# Phase 3: Code Review Report

**Reviewed:** 2026-07-04T03:07:31Z
**Depth:** standard
**Files Reviewed:** 17 (+ 1 verified-unchanged: `ui/app/api/[...proxy]/route.ts`)
**Status:** issues_found

## Summary

Reviewed the multi-page UI shell (Nav, styles, /chat, /cashflow, /investments, /settings)
and the backend settings subsystem (`backend/settings.py`, `AppSetting` model, schemas,
`configure_llm(overrides)`, GET/PUT `/settings`, migration, tests).

**Threat-model checklist — all confirmed satisfied, no Critical findings:**
- Raw API keys never serialize in `GET /settings` (`SettingsOut` has only `*_masked` fields; `get_effective_settings(raw_keys=False)` never includes raw values). Confirmed.
- `PUT /settings` is gated by `dependencies=[Depends(require_api_key)]`, matching the header name (`MONAI_API_KEY`) the proxy injects.
- Blank/absent key (and in fact any blank field) on PUT is filtered out in `upsert_settings` (`value is None or value == ""` → skip), so it cannot clobber a stored key. Verified against `test_blank_key_keeps_existing`.
- `reset_engine()` + `configure_llm()` re-run exactly when an LLM-relevant field changes (`_LLM_RELEVANT_KEYS`), verified against `test_llm_change_resets_engine`.
- `ui/app/api/[...proxy]/route.ts` is byte-for-byte unchanged versus `main` (`git diff main -- ui/app/api/\[...proxy\]/route.ts` produces no output) — confirmed via git log/diff, not just inspection.

No Critical/Blocker issues found. Several Warning-level correctness and robustness gaps remain, plus two Info-level maintainability notes, detailed below. Two of the Warnings are pre-existing bugs carried over verbatim from the original single-page `page.tsx` into the new `cashflow/page.tsx` — still worth fixing since they now ship as part of this phase's new file.

## Warnings

### WR-01: Settings page discards typed API keys on save failure

**File:** `ui/app/settings/page.tsx:125-134`
**Issue:** `saveKeys` unconditionally clears `anthropicKey`/`openaiKey` state after `await putSettings(...)` resolves, regardless of whether the save succeeded or failed:
```ts
await putSettings(body, setKeysState);
setAnthropicKey("");
setOpenaiKey("");
```
If the PUT fails (network error, 401, 500, validation error), the error banner is shown but the user's typed key is wiped from the input — they must retype the entire key. This is a real data-loss-of-input bug, not just cosmetic, since API keys are long and easy to mistype on retry.
**Fix:** Only clear the fields on success:
```ts
const ok = await putSettings(body, setKeysState);
if (ok) {
  setAnthropicKey("");
  setOpenaiKey("");
}
```
(requires `putSettings` to return a boolean, or inspect `keysState.status === "success"` after the await in a follow-up render — simplest is to have `putSettings` return `r.ok`.)

### WR-02: Settings audit-log write is not atomic with the settings write

**File:** `backend/main.py:129-139`, `backend/settings.py:137`
**Issue:** `upsert_settings(db, ...)` (line 129) internally calls `db.commit()` at the end of `backend/settings.py` (line 137), persisting the new settings values. Only *after* that has already committed does `write_settings` build `audit_after`, `db.add(AuditLog(...))`, and call a *second*, separate `db.commit()` (main.py:137-139). If the process crashes or the second commit fails between these two points, the settings change is durably applied but never audit-logged — violating the project's "validated; audit-logged" write pattern used consistently elsewhere (e.g. `_execute_proposal_payload` writes its AuditLog rows inside the same transaction/commit as the mutation).
**Fix:** Build the `AuditLog` row and add it to the session *before* calling `upsert_settings`, or refactor `upsert_settings` to accept the session and defer its own `db.commit()` to the caller so both writes land in one transaction:
```python
audit_after = ...
db.add(AuditLog(entity="settings", ...))
changed_llm = upsert_settings(db, patch.model_dump(exclude_none=True))  # single db.commit() covers both
```

### WR-03: Partial provider update can leave a stale/mismatched model in effect

**File:** `backend/settings.py:77-88` (`_load_raw`)
**Issue:** `_load_raw` computes the effective model as `rows.get(KEY_LLM_MODEL) or _model_env_default(provider)` — i.e. if a `llm_model` row is *already* stored (from a previous provider), it is reused verbatim even after `llm_provider` changes to a different provider. The only reason this doesn't currently manifest is that the shipped Settings UI always submits `llm_provider` and `llm_model` together (`saveProvider` in `ui/app/settings/page.tsx:116-123`, driven by `handleProviderChange` auto-filling the model). Any other client of `PUT /settings` (a future MCP client, curl, a script) that updates `llm_provider` alone will silently leave the old provider's model string in effect — e.g. switching to `openai` while `llm_model` still holds `claude-haiku-4-5-20251001`, breaking the next `configure_llm()` call.
**Fix:** In `upsert_settings`/`write_settings`, when `llm_provider` is present in the patch but `llm_model` is not, either reset `llm_model` to the new provider's default or reject the patch with a 422 requiring both fields together.

### WR-04: `mask_key("")` produces a misleading audit record for "keep existing" PUTs

**File:** `backend/main.py:132-136`
**Issue:** When a client sends a blank string for `anthropic_api_key`/`openai_api_key` (the documented "keep existing" signal), `upsert_settings` correctly skips writing it — but `write_settings`'s audit-log construction still runs `mask_key(audit_after[KEY_ANTHROPIC_API_KEY])` on that same blank value, and `mask_key("")` returns `None` (falsy input). The resulting `AuditLog.after` shows `"anthropic_api_key": null`, which reads as "the key was cleared" even though nothing changed.
**Fix:** Only include masked key fields in `audit_after` when the raw value was non-blank (i.e. mirror the same skip condition used in `upsert_settings`):
```python
if audit_after.get(KEY_ANTHROPIC_API_KEY):
    audit_after[KEY_ANTHROPIC_API_KEY] = mask_key(audit_after[KEY_ANTHROPIC_API_KEY])
else:
    audit_after.pop(KEY_ANTHROPIC_API_KEY, None)
```

### WR-05: `cashflow/page.tsx` swallows network/API errors on transaction submit (carried over)

**File:** `ui/app/cashflow/page.tsx:52-77` (`addTx`)
**Issue:** `addTx`'s `try { ... } finally { setSaving(false) }` has no `catch`. If `fetch` throws (offline, DNS failure) or the backend returns a non-2xx status (e.g. 422 validation, 401), the function either produces an unhandled promise rejection (thrown case) or silently no-ops (non-throwing non-ok response — `if (r.ok) {...}` guards the success path only, with no `else` branch), leaving the user staring at a form that appears to do nothing with zero feedback. This is unchanged from the original `ui/app/page.tsx` but is now shipped as new code in this phase.
**Fix:** Add an error state and surface it, mirroring the pattern already used in `settings/page.tsx`'s `SaveState`:
```ts
} catch (e) {
  setError(e instanceof Error ? e.message : "Network error");
} finally {
  setSaving(false);
}
```
plus an `else` branch on non-ok responses to surface `r.status`/`detail`.

### WR-06: `cashflow/page.tsx` datetime-local default mixes UTC and local time (carried over)

**File:** `ui/app/cashflow/page.tsx:28`
**Issue:** `date: new Date().toISOString().slice(0, 16)` produces a **UTC** wall-clock string, but it's bound to an `<input type="datetime-local">`, which both displays and re-parses that string as **local** time. For any user not in UTC+0, the form's initial date/time value visibly differs from "now" by the local UTC offset, and if submitted unedited, `new Date(form.date).toISOString()` (line 57) re-interprets the (UTC-valued-but-labeled-local) string as local time again, compounding the offset into the persisted transaction's `date`. Net effect: logged transactions get a systematically wrong timestamp equal to `now ± (2 × UTC offset)` unless the user manually corrects the date field every time. Same bug existed in the original `page.tsx`; it's being propagated into the new route unchanged.
**Fix:** Build the default from local time components instead of `toISOString()`:
```ts
function toLocalDatetimeInputValue(d: Date) {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
// ...
date: toLocalDatetimeInputValue(new Date()),
```

### WR-07: `AppSetting.value` typed `Mapped[dict]` but always holds scalar strings

**File:** `backend/models.py:165-166`, `backend/settings.py:130-131`
**Issue:** `AppSetting.value` is declared `Mapped[dict] = mapped_column(JSONB, nullable=False)`, but every write path (`upsert_settings`) assigns plain Python `str` values (provider names, model names, raw API keys, currency codes) to `row.value`. This works at runtime only because JSONB happily stores a bare JSON string scalar, and `_load_raw`'s `rows.get(key)` reads it back as `str` — but the ORM type annotation is simply wrong, and any future refactor (or a type-checker adopted later, since the project has none today per CLAUDE.md) will silently accept incorrect dict-shaped writes/reads without complaint, or a reviewer will reasonably assume `.value` is a dict and write `.value["foo"]` somewhere, raising at runtime.
**Fix:** Change the annotation to match actual usage: `value: Mapped[str] = mapped_column(Text, nullable=False)` (dropping JSONB in favor of `Text`, since no key currently needs nested JSON), or if JSONB is intentionally kept for future-proofing, change the annotation to `Mapped[str]` while leaving the column type JSONB, with a comment explaining the deliberate scalar-only usage.

## Info

### IN-01: Provider → default-model mapping duplicated in three places

**File:** `ui/app/settings/page.tsx:24-28`, `backend/config.py:36-65`, `backend/settings.py:62-69` (`_model_env_default`)
**Issue:** The `{ollama, claude, openai} → default model` mapping is hand-maintained independently in the frontend (`DEFAULT_MODEL_BY_PROVIDER`), `backend/config.py` (`configure_llm`'s per-branch `os.getenv(...)` defaults), and `backend/settings.py` (`_model_env_default`). A future change to e.g. `CLAUDE_MODEL`'s default will need to be applied in three places to stay consistent; missing one silently produces mismatched displayed-vs-effective defaults.
**Fix:** Consider having `_model_env_default` be the single source of truth and have `configure_llm` call it, and expose the mapping to the frontend via the `GET /settings` response (or a small `/api/config/defaults` endpoint) instead of hardcoding it a third time in TypeScript.

### IN-02: `base_currency` and `llm_model` accept unvalidated free-form strings

**File:** `backend/schemas.py:122-134` (`SettingsUpdate`)
**Issue:** Unlike `llm_provider` and `price_data_source`, which are validated against a fixed enum, `base_currency` and `llm_model` have no format validation at all — any string is accepted and persisted. `llm_model` being free-text is arguably intentional (arbitrary model names), but `base_currency` having no ISO-4217-style check means a typo (`"IRD"` instead of `"IDR"`) is silently stored and surfaced as the effective currency with no warning.
**Fix:** Add a lightweight `field_validator` for `base_currency` (e.g. 3-letter uppercase check) if incorrect currency codes are a realistic user error to guard against; otherwise document the omission as intentional.

---

_Reviewed: 2026-07-04T03:07:31Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
