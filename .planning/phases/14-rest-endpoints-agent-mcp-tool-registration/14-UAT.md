---
status: partial
phase: 14-rest-endpoints-agent-mcp-tool-registration
source: [14-01-SUMMARY.md, 14-02-SUMMARY.md, 14-03-SUMMARY.md]
started: 2026-07-31T00:00:00Z
updated: 2026-07-31T00:00:00Z
mode: autonomous (AFK — human-needed UATs skipped per user instruction)
---

## Current Test

[testing complete — automated pass, human/deploy-dependent tests marked blocked]

## Tests

### 1. Cold Start Smoke Test
expected: Kill the stack, rebuild, boot from scratch; server boots without errors and a primary query returns live data.
result: blocked
blocked_by: release-build
reason: "Live-stack cold start requires `docker compose up -d --build` (running backend container is pre-Phase-14 code; deploy-requires-rebuild). App import/boot IS verified at code level — the 272-test suite instantiates the FastAPI app and all routes without error."

### 2. Direct REST write endpoints exist and route through Phase-13 apply_*
expected: POST /transactions/transfer, /transactions/investment-transfer, /portfolio-events/funded-buy, /portfolio-events/funded-sell, and /accounts/{id}/adjust-balance accept valid payloads (with API key) and persist via the Phase-13 apply_* primitives (no ad-hoc SQL).
result: pass
evidence: "test_write_endpoints.py 8/8 green (5 happy-path persisting through apply_* + 3 validation/auth). Handlers commit once → reset_engine(); verified in 14-03-SUMMARY."

### 3. REST write endpoints reject bad input with 422 (not 500) and require auth
expected: Missing/invalid fields return HTTP 422; requests without a valid API key are rejected.
result: pass
evidence: "test_write_endpoints.py validation/auth tests green (require_api_key gate + ValueError→HTTPException(422) mapping)."

### 4. Agent chat: 5 propose_* write tools registered with working propose→confirm→apply
expected: The 5 new write operations are exposed as propose_* tools that create a proposal, and confirming the proposal applies the write through apply_* (confirm-before-write flow).
result: pass
evidence: "test_proposals.py — 5 propose→confirm integration tests green (transfer, investment-transfer, funded-buy, funded-sell, balance-adjustment). Dual-registered in tools.py TOOLS.update() AND query.py write_tools (verified by grep loops in 14-02-SUMMARY)."

### 5. Agent chat: malformed proposal payload returns clean 422 (not 500/KeyError)
expected: A confirm request with a mis-shaped payload returns 422, not an unhandled 500.
result: pass
evidence: "test_confirm_malformed_funded_buy_returns_422 green; (KeyError, TypeError)→ValueError guard wraps the new dispatch branches (14-02)."

### 6. New write tools excluded from the external MCP read-only surface
expected: The 5 propose_* write tools do NOT appear on the MCP tools/list surface exposed to external clients.
result: pass
evidence: "test_mcp.py::test_new_write_tools_registered_and_excluded green; READ_TOOL_NAMES still holds exactly 15 read names (snapshot taken before TOOLS.update()); test_mcp_no_write_tools + test_agent_read_tools_count unregressed."

### 7. Live chat end-to-end in natural language (LLM selects the tool)
expected: In the running app, asking the assistant in plain language (e.g. "move 500k from BCA to Jago") produces a proposal, and confirming it lands the correct paired rows.
result: blocked
blocked_by: other
reason: "Human-needed UAT (per user instruction, skipped while AFK): requires a live LLM provider, a rebuilt backend (deploy-requires-rebuild), and human observation of NL tool-selection quality. The underlying propose→confirm→apply mechanics are covered by Test 4."

## Summary

total: 7
passed: 5
issues: 0
blocked: 2
pending: 0
skipped: 0

## Gaps

[none — 0 issues. 2 tests blocked on deploy/human, not code defects.]
