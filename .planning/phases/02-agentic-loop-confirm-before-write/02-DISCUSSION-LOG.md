# Phase 2: Agentic Loop + Confirm-Before-Write - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-21
**Phase:** 2-Agentic Loop + Confirm-Before-Write
**Areas discussed:** Confirm UX surface, Write-op scope, Agent transparency, Proposal lifetime

---

## Confirm UX surface

### Q1 — Where does approve/reject happen this phase?

| Option | Description | Selected |
|--------|-------------|----------|
| Inline chat card | Proposal renders as a card inside the existing chat box with Approve/Reject; user never leaves the conversation | ✓ |
| Minimal button bolt-on | Backend fully built; thin pending-proposals strip on the existing page | |
| API-only this phase | Backend + tests only; all confirm UI deferred to Phase 3 | |

**User's choice:** Inline chat card

### Q2 — What does the proposal card show (esp. for edits)?

| Option | Description | Selected |
|--------|-------------|----------|
| Before→after diff | Edits show changed fields old→new; creates show full new row; deletes show removed row | ✓ |
| Full proposed state | Card shows the complete resulting record without highlighting changes | |

**User's choice:** Before→after diff

### Q3 — Can a single proposal cover multiple rows?

| Option | Description | Selected |
|--------|-------------|----------|
| One proposal, one approval | Payload describes a bulk op; one Approve applies all rows atomically, N audit rows; one token gates the batch | ✓ |
| Single-row only this phase | Proposals strictly one op on one row; agent splits bulk requests | |

**User's choice:** One proposal, one approval (atomic batch)

---

## Write-op scope

### Q1 — Which write operations can the agent propose in Phase 2? (multi-select)

| Option | Description | Selected |
|--------|-------------|----------|
| Transactions (add/edit/delete) | Core spending data; full proposal→confirm→audit loop | ✓ |
| Accounts (add/edit/delete) | Create/rename/delete accounts | ✓ |
| Categories (rename/merge) | Rename (remap tx) + merge; UI scheduled for Phase 4 | ✓ |
| Holdings (add/edit/delete) | Investment positions; table exists, subsystem is Phase 5 | ✓ |

**User's choice:** All four — full CHAT-07 surface

### Q2 — Do holding writes also record portfolio_events?

| Option | Description | Selected |
|--------|-------------|----------|
| Holdings row only (defer events) | Phase 2 writes holdings row + audit_log; portfolio_events stays Phase 5 | ✓ |
| Also record portfolio_events now | Pull part of INV-07 forward into Phase 2 | |

**User's choice:** Holdings row only — defer events to Phase 5

### Q3 — How to handle destructive writes with dependent data?

| Option | Description | Selected |
|--------|-------------|----------|
| Block + explain | Agent refuses to propose an orphaning delete and explains; no proposal created | ✓ |
| Propose with full impact | Agent proposes the delete; card shows blast radius; approval cascades | |
| Claude's discretion | Planner picks sensible per-entity rules | |

**User's choice:** Block + explain

---

## Agent transparency

### Q1 — How much of the multi-step work does the user see?

| Option | Description | Selected |
|--------|-------------|----------|
| Answer + collapsible trace | Answer prominent; tool-call chain in a collapsible "how I got this"; metadata always in API | ✓ |
| Answer only (metadata in API) | Chat shows final answer; trace only in API payload | |
| Always-visible steps | Every tool call rendered inline as it works | |

**User's choice:** Answer + collapsible trace

### Q2 — What does the chat do while the agent works?

| Option | Description | Selected |
|--------|-------------|----------|
| Blocking + spinner | One request/response; thinking spinner then full answer | |
| Progressive step updates | Stream coarse progress (calling X… → synthesizing…); needs streaming transport now | ✓ |

**User's choice:** Progressive step updates
**Notes:** This resolves the STATE.md open question toward "streaming transport must be wired in Phase 2." Transport (SSE vs WebSocket) remains a research item (SSE recommended). Coarse step events only — token-by-token streaming (QRY-03) stays v2.

---

## Proposal lifetime

### Q1 — Token TTL?

| Option | Description | Selected |
|--------|-------------|----------|
| ~15 minutes | Tight window; stale tab can't apply old change | ✓ |
| ~1 hour | Balanced; survives interruptions within a session | |
| ~24 hours | Generous; survives overnight; looser safety | |

**User's choice:** ~15 minutes

### Q2 — What happens in the UI on expiry?

| Option | Description | Selected |
|--------|-------------|----------|
| Card expires visibly | Card greys out, "Expired — ask again to redo," buttons disabled; enforced server-side | ✓ |
| Silent server-side only | Server rejects expired confirm; generic error only if clicked | |

**User's choice:** Card expires visibly

---

## Claude's Discretion

- Agent framework: `FunctionAgent` vs `ReActAgent` (depends on Ollama function-calling support) — research item.
- Streaming transport: SSE vs WebSocket (SSE recommended) — research item.
- Agent guardrails: max reasoning steps / loop protection / iteration cap.
- Target-row disambiguation for vague edit/delete targets.
- Refusal tone/wording for CHAT-08 (follow existing `query.py:ask()` style).
- Exact `proposals.payload` / `audit_log` JSONB shapes and new write-tool signatures.
- Confirm/reject/pending-proposals API surface beyond `POST /proposals/{id}/confirm`.

## Deferred Ideas

- Token-by-token answer streaming (QRY-03) — v2.
- Spending↔portfolio correlation queries (CHAT-03) + portfolio_events recording (INV-07) — Phase 5.
- Category management UI (CASH-06/07) — Phase 4 (agent write tool ships in Phase 2).
- Write tools over MCP — out of scope all cycle.
- Period comparison (QRY-02), recurring-charge detection (QRY-01) — v2.
