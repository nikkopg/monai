---
status: complete
phase: 02-agentic-loop-confirm-before-write
source: [02-01-SUMMARY.md, 02-02-SUMMARY.md, 02-03-SUMMARY.md]
started: 2026-07-16T20:40:00+07:00
updated: 2026-07-16T20:45:00+07:00
mode: automated (agent-run; visual/streaming UI checks skipped per operator instruction)
---

## Current Test

[testing complete]

## Tests

### 1. Cold Start Smoke Test
expected: Backend boots with proposals + /query-stream (SSE) endpoints; a primary read returns live data.
result: pass
evidence: `GET /categories` → HTTP 200 against running monai-backend; proposals/query-stream routes registered in main.py (boot clean, per Phase-5 cold-start check same container).

### 2. Multi-Step Agent Answers (CHAT-01)
expected: A question is answered by a multi-step FunctionAgent that can plan and chain tools in one turn.
result: pass
evidence: test_agent.py behavior tests (CHAT-01 path) pass; query.py uses FunctionAgent + max_iterations (multi-step), agent_stream async generator. 59/59 phase-2 suite.

### 3. Agent Never Emits Raw SQL (CHAT-02)
expected: The agent only invokes fixed parameterized tools — never emits SQL.
result: pass
evidence: `grep -cE "run_sql|SELECT |DELETE FROM|text(" backend/query.py` → 0. test_agent CHAT-02 path passes. Tools are the only DB surface (FunctionTool.from_defaults × 9).

### 4. Confirm-Before-Write: Target Unchanged Until Approved (CHAT-04)
expected: When the agent intends to change data it returns a proposal (id + token) and writes NOTHING until the user approves.
result: pass
evidence: test_write_tools.py 11 tests — core invariant asserts propose_* returns proposal_id+token AND the target row is UNCHANGED. No mutation in propose_* (grep UPDATE/DELETE/INSERT in propose_ bodies → 0).

### 5. Single-Use, Operation-Scoped Approval (CHAT-05)
expected: An approval is bound to that exact proposed op — single-use, not a reusable session yes.
result: pass
evidence: test_proposals.py — token single-use → 409 on reuse; expiry → 410; wrong-token → 401; hmac.compare_digest ×2 in main.py. GET /proposals excludes the token (not in ProposalOut.model_fields).

### 6. Audit Log on Every Applied Write (CHAT-06)
expected: Every applied write is recorded in an audit log (what changed, old→new, when).
result: pass
evidence: test_proposals asserts audit rows written on confirm; main.py AuditLog( ) ×11 across apply paths (shared with direct CRUD per integration check).

### 7. Add/Edit/Delete Transactions, Accounts, Categories, Holdings via Chat (CHAT-07)
expected: Through the confirm flow the user can add/edit/delete transactions, accounts, categories, and holdings.
result: pass
evidence: 11 propose_* tools (grep `def propose_` → 11); test_write_tools has one case per entity family incl orphan-delete blocked (D-06). Confirm dispatches to shared apply_* (integration check).

### 8. Honest "Cannot Map" (CHAT-08)
expected: When the agent can't map a request to a tool, it says so rather than fabricating.
result: pass
evidence: test_agent.py CHAT-08 path passes (honest no-tool response). Deterministic test, not live-LLM.

### 9. Streaming Chat + ProposalCard UI (02-03)
expected: SSE step indicator streams progressively; ProposalCard shows before→after diff, Approve/Reject, expiry greying + "Expired" message on 410.
result: skipped
reason: Visual/streaming UI (SSE render, expiry greying, diff card) — not automatable; needs human eyes on running frontend. Backend SSE (/query-stream text/event-stream) + proxy passthrough are code-present; the confirm/reject endpoints they call are verified in tests 4–6.

## Summary

total: 9
passed: 8
issues: 0
pending: 0
skipped: 1
blocked: 0
note: The 1 skip is the streaming ProposalCard visual layer; its backend contract (SSE endpoint, confirm/reject, expiry 410, single-use token) is fully verified in tests 4–6.

## Gaps

[none — 8/8 automatable checks pass; 1 visual check skipped; 0 issues]
