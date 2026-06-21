# Phase 2: Agentic Loop + Confirm-Before-Write - Context

**Gathered:** 2026-06-21
**Status:** Ready for planning

<domain>
## Phase Boundary

Replace the single-shot tool router with a multi-step **agentic loop**, and add a
**confirm-before-write** proposal system on top of the `proposals`/`audit_log`
tables Phase 1 already created.

This phase delivers:
- A **multi-step agent** (LlamaIndex `AgentWorkflow`/`FunctionAgent` or `ReActAgent` —
  framework choice is a research item) that **plans and chains the existing 9 read
  tools** within one turn to answer questions that need ≥2 tool calls
  (CHAT-01). It replaces `query.py`'s current one-call `route()`/`ask()` path.
- **Correctness-by-construction preserved**: the agent only invokes named tools in
  `tools.py`; it never emits raw SQL. Asking it to "run SQL" → honest refusal
  (CHAT-02).
- **Write tools** added to the `tools.py` registry for **add/edit/delete on
  transactions, accounts, categories (rename/merge), and holdings** (CHAT-07).
- **Confirm-before-write loop**: a proposed write creates a `proposals` row
  (UUID id + separate secret token + TTL) and mutates nothing; the user approves
  in the chat UI; `POST /proposals/{id}/confirm` with the correct token executes
  the write, writes `audit_log` rows, and marks the proposal confirmed
  (CHAT-04, CHAT-05, CHAT-06).
- **Honest refusal** when no tool maps to the request — never fabricate a number
  (CHAT-08).

**In scope = HOW to build the above.** Out of scope (own phases): multi-page UI
shell + Settings (Phase 3); cashflow dashboard + full CRUD *UI* (Phase 4);
investment prices/P&L, `portfolio_events`, correlation queries (Phase 5); MCP
server exposure (Phase 6).

**Requirements covered:** CHAT-01, CHAT-02, CHAT-04, CHAT-05, CHAT-06, CHAT-07, CHAT-08.

</domain>

<decisions>
## Implementation Decisions

### Confirm-before-write UX
- **D-01:** Approve/reject happens via an **inline chat card** rendered inside the
  existing chat/ask box (`ui/app/page.tsx`), with **Approve / Reject** buttons —
  the user never leaves the conversation. (Note: the polished multi-page shell is
  Phase 3; this card is the Phase-2 confirm surface, built onto today's single page.)
- **D-02:** The proposal card shows a **before→after diff**. Edits render changed
  fields as `old → new` (unchanged fields marked); creates show the full new row;
  deletes show the row being removed. Matches CHAT-04's "exact proposed change" and
  the `audit_log` before/after shape.
- **D-03:** A single proposal **can cover multiple rows** (e.g. "recategorize all 12
  Gojek transactions to Transport"). One **Approve applies the whole batch
  atomically**, writing **N `audit_log` rows**. The single-use, operation-scoped
  token gates the entire batch (one token = one Approve = all N rows or none). The
  card shows a summary + affected count. The `proposals.payload` JSONB must therefore
  represent a batch operation, not just a single-row op.

### Write-operation scope
- **D-04:** All of CHAT-07 ships in Phase 2 — write tools for **transactions**
  (add/edit/delete), **accounts** (add/edit/delete), **categories** (rename/merge),
  and **holdings** (add/edit/delete). All live in `tools.py` (single source of truth,
  reused by the Phase 6 MCP server — but writes are NOT exposed over MCP).
- **D-05:** **Holdings = row CRUD only.** Adding/editing/deleting a holding writes the
  `holdings` row + `audit_log` and **does NOT write `portfolio_events`**. Event
  recording (INV-07), prices, P&L, and correlation queries stay in Phase 5. Keeps the
  Phase 2/5 seam clean.
- **D-06:** **Destructive writes with dependent data are blocked + explained.** If a
  delete would orphan/cascade data (e.g. "delete my BCA account" with 800
  transactions, or deleting a category in use), the agent **refuses to create the
  proposal** and explains why ("reassign or remove those first"). No proposal row is
  created. Consistent with the honest-refusal, money-safe philosophy.
  - Category **rename/merge** is inherently non-orphaning (it remaps), so it is
    allowed — only true orphaning deletes are blocked.

### Agent transparency & response mode
- **D-07:** Chat shows the **synthesized answer prominently** plus a **collapsible
  "how I got this" trace** listing the chained tool calls (tool name + args +
  result). The full tool-call trace is **always returned in the API response
  metadata** (satisfies success criterion #1 regardless of UI state).
- **D-08:** The chat shows **progressive step updates** while the agent works
  (coarse events like "calling spending_total… → synthesizing…"), not a single
  blocking response. **This means a streaming transport must be wired in Phase 2.**
  - **Scope guard:** coarse step/progress events are in scope; **token-by-token
    streaming of the answer text (QRY-03) stays a v2 deferral.** Don't build
    token streaming this phase.
  - The **transport choice (SSE vs WebSocket) is a research item** — STATE.md's
    standing recommendation is SSE.

### Proposal lifetime & safety
- **D-09:** Proposal token **TTL = ~15 minutes**. Approving after expiry is a no-op;
  the DB stays unchanged (success criterion #5). Tightest safety window — a stale tab
  cannot apply an old change.
- **D-10:** **Expiry is visible in the UI.** The inline card greys out and shows
  "Expired — ask again to redo this" with disabled buttons once the window passes.
  Expiry is **enforced server-side** on confirm (token validity + `expires_at` check);
  the UI reflects that state.
- **D-11 (carried from Phase 1 / pre-roadmap, restated as enforced HERE):** The confirm
  token is **single-use and operation-scoped** — not a reusable session-level "yes." A
  second confirm with the same token is rejected (success criterion #4). The token is
  the separate secret `proposals.token` column, never the UUID `id`.

### Claude's Discretion (planner/researcher decide)
- **Agent framework**: `FunctionAgent` vs `ReActAgent` — depends on whether the
  configured LLM (esp. Ollama `gemma4:31b-cloud`) supports native function-calling.
  Research flag in ROADMAP.md. Verify before planning.
- **Streaming transport**: SSE vs WebSocket for the progressive step updates (D-08).
  Recommendation: SSE.
- **Agent guardrails**: max reasoning steps / loop protection / iteration cap — pick
  sensible defaults (not discussed; technical).
- **Target-row disambiguation**: how the agent identifies WHICH transaction an
  edit/delete refers to when the user is vague (e.g. multiple "Starbucks" rows) — may
  need a read/lookup step before proposing, or asking the user to pick. Planner's call.
- **Refusal tone/wording** for CHAT-08 — follow the existing honest-refusal style in
  `query.py:ask()`.
- **Exact `proposals.payload` / `audit_log` JSONB shapes** for each operation type,
  and the new write-tool signatures in `tools.py` — derive from these decisions and
  the existing tool conventions.
- **Confirm/reject API surface** beyond `POST /proposals/{id}/confirm` (e.g. a reject
  endpoint, a `GET /proposals?status=pending` for the card) — derive from the UX above.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase definition & requirements
- `.planning/ROADMAP.md` §"Phase 2: Agentic Loop + Confirm-Before-Write" — goal + 6
  success criteria (the verification target) + the Phase 2 research flag.
- `.planning/REQUIREMENTS.md` — CHAT-01 (multi-step agent), CHAT-02 (no raw SQL),
  CHAT-04 (confirm-before-write), CHAT-05 (single-use operation-scoped approval),
  CHAT-06 (audit log), CHAT-07 (write surface), CHAT-08 (honest refusal). Also note
  QRY-03 (token streaming) is v2/out-of-scope.
- `.planning/PROJECT.md` §Constraints, §Key Decisions — correctness-by-construction
  (no free SQL), confirm-before-applying + audit log, `tools.py` single source of
  truth, never re-platform.
- `.planning/STATE.md` §"Accumulated Context" — pre-roadmap locked decisions
  (`proposals` backend-persisted; token single-use + operation-scoped; `tools.py`
  shared by agent AND MCP) and the Phase 2 open questions (Ollama function-calling →
  FunctionAgent vs ReActAgent; SSE vs WebSocket).

### Existing code to evolve
- `backend/query.py` — the current single-shot router (`route()`/`ask()`/`_get_llm()`/
  `_extract_json()`). The agentic loop replaces this; `reset_engine()` is the
  cache-invalidation hook called from `main.py` on writes.
- `backend/tools.py` — the `TOOLS` registry + `format_answer()` + `resolve_period()`/
  `PERIODS`. New write tools join this registry; the agent chains these read tools.
  Sign convention (expense<0, income>0, transfers excluded) is load-bearing.
- `backend/main.py` — endpoint surface; `POST /query` (public, read-only) is where the
  agent is invoked; new `POST /proposals/{id}/confirm` (write, needs `require_api_key`)
  and any pending-proposals read endpoint go here. Lazy-import pattern in handlers.
- `backend/models.py` — `Proposal` (UUID id, secret `token`, `operation`, `payload`
  JSONB, `status`, `expires_at`, `confirmed_at`) and `AuditLog` (entity, entity_id,
  operation, before/after JSONB) — already built in Phase 1, consumed here.
  `Account`/`Transaction`/`Holding` are the write targets.
- `backend/auth.py` — `require_api_key` dependency; the confirm endpoint is a write →
  must be gated.
- `backend/config.py` — `configure_llm()` multi-provider switch (ollama/claude/openai);
  the agent must work across all three (drives the FunctionAgent vs ReActAgent question).
- `ui/app/page.tsx` (247 lines) — current single-page chat/ask box; the inline proposal
  card + progressive step updates are wired here.
- `ui/next.config.js` + the Phase-1 server-side proxy route handler — the key-injecting
  proxy through which confirm calls must pass.

### Codebase maps (background)
- `.planning/codebase/ARCHITECTURE.md` §"The Tool Router" — the load-bearing pivot
  (NL→SQL produced confident wrong numbers); the agentic loop must NOT reintroduce
  free-form SQL.
- `.planning/codebase/INTEGRATIONS.md`, `STACK.md` — LlamaIndex integration surface and
  provider wiring.
- `.planning/phases/01-schema-foundation-auth/01-CONTEXT.md` §decisions D-10/D-11 — the
  JSONB-payload and separate-secret-token rationale that this phase enforces at runtime.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `TOOLS` registry + structured-dict tool returns (`tools.py`) — write tools follow the
  same `dict` return shape; the agent's read repertoire is already built and tested.
- `resolve_period()` / `PERIODS` — relative-date resolution the agent reuses for any
  date-scoped read step in a multi-tool chain.
- `format_answer()` — natural-language rendering of tool results; the agent's synthesis
  step can build on it (or the agent synthesizes from raw dicts).
- `Proposal` / `AuditLog` ORM models — the persistence layer for the confirm loop is
  already migrated in (Phase 1). No new migration needed for the core loop unless a
  field is missing.
- `require_api_key` dependency — drop onto the confirm/write endpoints.
- `reset_engine()` (`query.py`) — existing cache-invalidation hook fired after writes
  in `main.py`; the confirm endpoint should fire it after applying a write.

### Established Patterns
- Parameterized SQL only / correctness-by-construction — the single most important
  constraint; the agent reasons over tools, never emits SQL.
- Lazy imports inside route handlers (`main.py`); per-request session via `get_session()`.
- Module-level LLM singleton (`_llm` in `query.py`) + `configure_llm()` provider switch.
- Full type annotations + Pydantic v2 `*Create`/`*Out`/`*Request`/`*Response` schemas;
  shared `Decimal` money type (Phase 1) for any amount the write tools touch.
- Error philosophy: domain raises `ValueError` → API maps to 422; `ask()` never raises
  to the user (broad except → friendly message).

### Integration Points
- `POST /query` (`main.py:113`) — the agent entry point; today calls `ask()`. Multi-step
  agent + progressive streaming changes this handler's response contract (answer +
  tool-call metadata + optional `proposal_id`, possibly a streamed event channel).
- The Next.js server-side proxy (Phase 1) — confirm calls and any streaming endpoint
  must route through it (API key injection; SSE/WS must survive the proxy).
- `proposals.payload` JSONB — the seam between the agent's proposed write and the
  confirm-time executor; must encode batch ops (D-03) and all four entity types (D-04).

</code_context>

<specifics>
## Specific Ideas

- Proposal card visuals (from discussion): a bordered card titled `PROPOSED
  <OP> · <entity> #<id>` with before→after lines and `[Approve] [Reject]`; expired
  state greys out with "⏱ Expired — ask again to redo." Batch ops show a one-line
  summary + affected count + total.
- Collapsible trace UX: "▾ how I got this (N steps)" listing `tool(args) → result`
  per step.
- The agent should split or batch as appropriate: a "fix all my X" request becomes one
  batch proposal (D-03), but the user explicitly wanted atomic all-or-nothing approval.

</specifics>

<deferred>
## Deferred Ideas

- **Token-by-token answer streaming (QRY-03)** — v2. Phase 2 does coarse step/progress
  events only (D-08).
- **Spending↔portfolio correlation queries (CHAT-03)** and **`portfolio_events`
  recording (INV-07)** — Phase 5. Phase 2 holdings writes are row-only (D-05).
- **Category management UI (CASH-06/07)** — Phase 4 builds the dedicated UI; Phase 2
  ships the agent-driven rename/merge write tool only.
- **Write tools over MCP** — explicitly out of scope all cycle; writes stay behind the
  web confirm UI (PROJECT.md Out of Scope).
- **Period comparison (QRY-02), recurring-charge detection (QRY-01)** — v2.

</deferred>

---

*Phase: 2-Agentic Loop + Confirm-Before-Write*
*Context gathered: 2026-06-21*
