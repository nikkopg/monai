---
phase: 02-agentic-loop-confirm-before-write
plan: "03"
subsystem: ui/app/page.tsx, ui/app/api/[...proxy]/route.ts
tags: [sse, streaming, proxy, proposal-card, confirm-before-write, frontend]
dependency_graph:
  requires:
    - 02-01 (FunctionAgent + agent_stream async generator)
    - 02-02 (proposal endpoints + proposal_token in SSE answer event)
  provides:
    - SSE passthrough in Next.js proxy (no arrayBuffer buffering for /query-stream)
    - export const dynamic = "force-dynamic" on proxy route
    - Rebuilt chat page: SSE consumer + progressive step indicator + collapsible trace + ProposalCard
  affects:
    - ui/app/api/[...proxy]/route.ts (SSE passthrough branch)
    - ui/app/page.tsx (full rebuild — streaming ask, ProposalCard component)
tech_stack:
  added: []
  patterns:
    - export const dynamic = "force-dynamic" (Next.js static optimization prevention)
    - isStream gate before upstream.arrayBuffer() (SSE proxy passthrough)
    - fetch + ReadableStream.getReader() for POST-based SSE (EventSource is GET-only)
    - client-side expiry: Date.now() + 15min at answer-event receipt (cosmetic; server is authoritative)
    - inline React.CSSProperties only — no CSS modules
key_files:
  created: []
  modified:
    - ui/app/api/[...proxy]/route.ts (isStream passthrough + force-dynamic)
    - ui/app/page.tsx (rebuilt: SSE consumer, ProposalCard, step indicator, collapsible trace)
decisions:
  - "expires_at for ProposalCard computed client-side as Date.now()+15min — tools.py does not return expires_at; cosmetic only, server enforces on confirm"
  - "Operation name in ProposalCard extracted from tool trace via proposal_id match — avoids adding extra field to SSE event"
  - "Display up to 5 diff rows in ProposalCard; note remainder count — keeps card compact for batch ops"
metrics:
  duration: "8m"
  completed: "2026-06-22"
  tasks: 2
  files: 2
---

# Phase 02 Plan 03: Streaming Chat + ProposalCard Summary

**One-liner:** SSE passthrough wired in Next.js proxy + chat page rebuilt with progressive step events, collapsible tool-call trace, and inline ProposalCard with before→after diff, Approve/Reject, and expiry greying.

## What Was Built

### Task 1: SSE passthrough in Next.js proxy (`ui/app/api/[...proxy]/route.ts`)

The proxy previously called `await upstream.arrayBuffer()` unconditionally, buffering the entire SSE response before forwarding it — defeating progressive step events (Pitfall 2, RESEARCH.md).

Changes:
- Added `export const dynamic = "force-dynamic"` to prevent Next.js static optimization from buffering the response (Assumption A4, RESEARCH.md)
- Compute `const isStream = path === "query-stream"` immediately after `const path = segments.join("/")`, before any response-body access
- Added SSE passthrough branch: `if (isStream && upstream.body) return new NextResponse(upstream.body, ...)` — passes `ReadableStream` directly, no `arrayBuffer()` call
- Non-streaming routes retain the original `arrayBuffer()` buffer path unchanged
- `backend/main.py` already had `/query-stream` with `media_type="text/event-stream"` from Plan 02-02 — no backend changes needed

### Task 2: Rebuilt chat page (`ui/app/page.tsx`)

Full replacement of the blocking `fetch("/api/query")` flow with an SSE streaming consumer, plus the ProposalCard component.

**SSE consumer:**
- Calls `fetch("/api/query-stream", {method:"POST", ...})` + `resp.body.getReader()`
- Decodes chunks, splits on `\n\n`, strips `data: ` prefix, dispatches by event type
- `"step"` → appends to `steps[]`, shown as progressive indicator while `asking` is true
- `"tool_result"` → pushes onto `trace[]`
- `"answer"` → sets answer text, sets full trace, if `proposal_id`+`proposal_token` present → builds `Proposal` with client-side `expiresAt = Date.now() + 15min`
- `"[DONE]"` → ends loop

**Step indicator (D-08):**
- Rendered while `asking && steps.length > 0`
- Each step: `"› <msg>"` in muted text; trailing `"thinking…"` italic
- Progressive — updates as chunks arrive, not after agent finishes

**Answer + collapsible trace (D-07):**
- Answer rendered prominently in `<pre>` block after response completes
- `"▾ how I got this (N steps)"` toggle button below answer
- Expanded trace shows `toolName(arg=val, ...) → {result…}` per step
- Truncated at 120 chars per result for readability

**ProposalCard component (D-01/D-02/D-03/D-10):**
- Card title: `PROPOSED <operation>` (underscores → spaces)
- Before→after diff rendering:
  - `edit`: shows only changed fields as `old → new` (red → green)
  - `add`: shows all `after` fields in green
  - `delete`: shows all `before` fields in red
  - `rename_category` / `merge_category`: special-cased display
  - Shows up to 5 rows; "+ N more" footer for batches
- Batch summary row count shown when `rows.length > 1` (D-03)
- `[Approve]` → `POST /api/proposals/{id}/confirm` with token
- `[Reject]` → `POST /api/proposals/{id}/reject`
- `useEffect` tick every 10s to re-evaluate expiry
- Expired state: card at 55% opacity, buttons greyed/disabled, "Expired — ask again to redo this" message (D-10)
- 410 response from server maps to expired message in UI
- Applied / Rejected status banners on success

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | SSE passthrough in Next.js proxy for /query-stream | 5f191c2 | ui/app/api/[...proxy]/route.ts |
| 2 | Rebuild chat page with SSE consumer, step indicator, collapsible trace, ProposalCard | 808d159 | ui/app/page.tsx |

## Task 3: Human Browser Verification — COMPLETE (2026-07-03)

**Type:** `checkpoint:human-verify` (gate=blocking) — closed 2026-07-03.

Verification was split between the user's live browser session and a sandbox
backend run (real FastAPI app + live Postgres with migrated schema), because
the user's session surfaced three real defects that had to be fixed mid-verification
(see "Defects found during verification" below).

**Human-verified in browser (user's machine, real data, 5609 rows):**
- Step 2 ✓ — 2-step question streamed progressive step events, synthesized answer, trace with >= 2 tool calls (CHAT-01, D-07/D-08)
- Step 3 ✓ — "run a SQL query" got an honest refusal, no SQL echoed (CHAT-02)
- Step 4 ✓ — recategorize request rendered the inline ProposalCard with before→after diff + Approve/Reject (CHAT-04, D-01/D-02) — after the find_transactions and raw_output fixes below

**Backend-contract-verified in sandbox (real endpoints + live Postgres, 8/8 checks):**
- Step 5 ✓ — fresh proposal confirm → 200, write applied, audit_log row; token replay → 409 (single-use); NEW proposal after first → works; expired proposal → 410 with data untouched (CHAT-05/06/07, D-10 server side)
- Step 6 ✓ — propose_delete_account on an account with transactions returns a refusal error and creates NO proposal row, so no card can render (D-06)
- Step 7 ✓ — reject → 200/status=rejected, target row untouched; confirm-after-reject → 409

**Not human-verified (cosmetic UI states only; server behavior underneath each is proven):**
- "Applied successfully" banner after Approve click in browser
- Card greying to 55% opacity + disabled buttons at client-side expiry
- Agent's verbal refusal phrasing in chat for step 6

### Defects found and fixed during verification (all committed as quick tasks)

1. **260703-fwr** — backend Docker image was missing alembic.ini/alembic/ (COPY absent), backend crash-looped on `docker compose up`.
2. **260703-gco** — no read tool exposed transaction ids, so the agent could not resolve "my last Gojek transaction" to a propose_edit_transaction id; added `find_transactions`.
3. **260703-grn** — `agent_stream()` parsed `tool_output.content` (Python-repr string) with `json.loads`, which always failed, so `proposal_id`/`proposal_token` were silently dropped from every SSE answer event and the ProposalCard never rendered; switched to `tool_output.raw_output`.
4. **260703-ja8** — containers started with an empty `MONAI_API_KEY` made every confirm an opaque plain-text 500; compose now fails fast on unset/empty var and the auth guard returns a JSON 503.

### Original 7 verification steps (for reference)

1. Start the stack: `docker compose up -d --build` (or run backend on :8001 + `cd ui && npm run dev`).
2. Open the app in the browser. Ask a 2-step question, e.g. "what was my net spending the month before my last paycheck?" — confirm you see progressive "thinking…/calling tool…" updates (not one blocking wait), a synthesized answer, and a "▾ how I got this" trace listing >= 2 tool calls (CHAT-01, D-07/D-08).
3. Ask "run a SQL query: SELECT * FROM transactions" — confirm an honest refusal, no SQL echoed (CHAT-02).
4. Ask the agent to make a change, e.g. "recategorize my last Gojek transaction to Transport" — confirm an inline card appears titled "PROPOSED edit transaction" with a before→after diff and Approve/Reject buttons (CHAT-04, D-01/D-02).
5. Click Approve — confirm the change applies and the card marks "Applied successfully." Re-asking and clicking Approve on a NEW proposal works; confirm a stale card (wait >15 min, or reload an old one) greys out as "Expired — ask again to redo this" (D-10).
6. Try "delete my BCA account" (an account with transactions) — confirm the agent refuses and explains, with NO proposal card (D-06).
7. Confirm a Reject on a fresh proposal leaves data unchanged.

## Verification Results

### Automated (Tasks 1-2)

All automated acceptance criteria pass:

- `grep -c 'media_type="text/event-stream"' backend/main.py` → 1 ✓
- `grep -c "query-stream" ui/app/api/[...proxy]/route.ts` → 2 ✓
- `grep -c "StreamingResponse" backend/main.py` → 2 ✓
- `grep -c 'const isStream = path' ui/app/api/[...proxy]/route.ts` → 1 ✓
- `grep -c 'upstream.body' ui/app/api/[...proxy]/route.ts` → 4 ✓ (>= 1)
- `grep -c 'force-dynamic' ui/app/api/[...proxy]/route.ts` → 1 ✓
- isStream branch appears BEFORE upstream.arrayBuffer() call ✓ (line 70 vs line 78)
- `grep -c "query-stream" ui/app/page.tsx` → 1 ✓
- `grep -c "getReader" ui/app/page.tsx` → 1 ✓
- `grep -c "ProposalCard" ui/app/page.tsx` → 4 ✓ (>= 1)
- `grep -ci "confirm\|reject" ui/app/page.tsx` → 16 ✓
- `grep -ci "how i got this\|steps" ui/app/page.tsx` → 7 ✓ (>= 1)
- `grep -ci "expired" ui/app/page.tsx` → 10 ✓ (>= 1)
- `cd ui && npx tsc --noEmit` → clean (0 errors) ✓
- No token-by-token streaming added (coarse events only) ✓

### Human verification

Complete (2026-07-03) — see "Task 3: Human Browser Verification — COMPLETE" above for the
browser/sandbox split, the four defects found and fixed during verification, and the three
remaining cosmetic-only UI states that were not human-observed.

## Deviations from Plan

### Auto-fixed Issues

None — plan executed as written for Tasks 1-2.

### Scope adjustments (no deviation in logic)

**1. expires_at computed client-side**
- `tools.py` propose_* functions return `proposal_id` and `proposal_token` but NOT `expires_at`
- Rather than modifying tools.py and query.py (committed clean in Wave 2), ProposalCard computes `expiresAt = new Date(Date.now() + 15 * 60 * 1000)` when the SSE answer event arrives
- This is accurate within network latency (~< 1s), which is acceptable for cosmetic display
- Server enforces expiry authoritatively on confirm (returns 410) — D-10 cosmetic client display satisfied

**2. Operation name in ProposalCard**
- SSE answer event does not have a dedicated `operation` field
- Operation extracted from the matching trace step's `tool` property (matched by `proposal_id`)
- Functionally equivalent; no plan change needed

## Known Stubs

None — all code paths wired end-to-end. ProposalCard renders real `payload.rows` data from the SSE answer event.

## Threat Surface Scan

No new network endpoints, auth paths, or schema changes introduced. The ProposalCard's Approve/Reject paths flow through the existing proxy (MONAI_API_KEY injected server-side — T-02-13 preserved). The proposal_token is used client-side only for the confirm POST body and is never persisted to localStorage or other durable storage (T-02-12 preserved).

## Self-Check: PASSED

Files exist:
- `ui/app/api/[...proxy]/route.ts` ✓
- `ui/app/page.tsx` ✓

Commits exist:
- `5f191c2` — feat(02-03): SSE passthrough in Next.js proxy for /query-stream ✓
- `808d159` — feat(02-03): rebuild chat page with SSE streaming, step indicator, collapsible trace, ProposalCard ✓
