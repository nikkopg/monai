---
phase: 06-mcp-server
verified: 2026-07-16T00:00:00Z
status: passed
score: 4/4 success criteria verified (9/9 must-have truths)
behavior_unverified: 0
overrides_applied: 0
human_verification:
  - test: "Live external-client UAT: after `docker compose up -d --build`, connect a real external MCP client (e.g. Claude Desktop) to http://host:8001/mcp with the MONAI_API_KEY header (or Authorization: Bearer <key>), enumerate tools, call spending_total last_month, and confirm the answer matches the web chat agent's answer to the same question; then confirm an unauthenticated connection is rejected."
    expected: "Client enumerates exactly 15 read tools / 0 write tools; spending_total parity holds vs web chat; unauthenticated connection rejected (401)."
    why_human: "Requires a running Docker deployment and a real third-party MCP client over the network — the transport, real-provider LLM parity, and client header/Bearer handling cannot be exercised by the in-process TestClient. Automated/code verification (below) is complete; this is the deployment-level smoke test only."
---

# Phase 6: MCP Server Verification Report

**Phase Goal:** External MCP clients can query the app's finance data using the same tools the web agent uses — via a read-only FastMCP server co-mounted on the existing FastAPI app at http://host:8001/mcp, API-key gated.

**Verified:** 2026-07-16
**Status:** passed (automated/code verification) — live external-client UAT remains as a manual deployment smoke test
**Re-verification:** No — initial verification

## Goal Achievement — 4 Success Criteria

| # | Success Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | External MCP client connects to /mcp and enumerates tools; list contains ONLY read tools, zero writes (MCP-01, MCP-03) | ✓ VERIFIED | Endpoint co-mounted at exactly `/mcp` (main.py L146 `http_app(path="/")` + L194 `mount("/mcp")`). `test_mcp_endpoint_mounted` asserts handshake not-404/200. `test_mcp_read_parity` asserts `tools/list` == `set(READ_TOOL_NAMES)` and len==15. Runtime probe: `build_mcp()` registers 15 names, zero `propose_`. 5/5 MCP tests pass. |
| 2 | Client calls a read tool and gets the SAME result the web chat agent returns for the same query (MCP-02 parity) | ✓ VERIFIED | `test_mcp_read_parity` (test_mcp.py L109-114) calls `spending_total(period=last_month)` over the live JSON-RPC wire and asserts `mcp_dict == TOOLS["spending_total"](period="last_month")`. Both surfaces register the identical `backend.tools.TOOLS` callables (single source of truth); query.py `read_tools` == 15 == `READ_TOOL_NAMES` (`test_agent_read_tools_count` L117-128). |
| 3 | Calling a write tool from the external client FAILS — tool ABSENT from registry (MCP-03, assert absence) | ✓ VERIFIED | `test_mcp_no_write_tools` (L131-142) asserts no `propose_*` name in `tools/list` AND that calling `propose_add_transaction` returns `isError: True` with `"Unknown tool"`. Runtime probe: `propose_ in READ_TOOL_NAMES: []`, MCP registry has zero propose_. Absence is by-construction (see security check below), not a runtime block. |
| 4 | Client must provide a valid API key; unauthenticated connections rejected (MCP-04) | ✓ VERIFIED | Outer-app middleware `mcp_api_key_guard` (main.py L167-191) guards `path.startswith("/mcp")`, delegates to `auth.key_ok()`. `test_mcp_requires_key` (L145-166) asserts a `/mcp` request with no key → 401. |

**Score:** 4/4 success criteria verified; 9/9 must-have truths verified.

## CRITICAL Security Check — READ_TOOL_NAMES pre-mutation snapshot (MCP-03/D-03)

The executor claimed `backend.tools.TOOLS` mutates to 26 entries at load, and that a `READ_TOOL_NAMES` frozenset snapshot taken BEFORE the mutation prevents a would-be MCP-03 violation. **All three sub-claims independently verified:**

| Claim | Status | Evidence |
| --- | --- | --- |
| TOOLS mutates to 26 (15 read + 11 propose_) via `TOOLS.update()` at module load | ✓ VERIFIED | tools.py L494-510 defines 15-entry read dict; L962 `TOOLS.update({...})` merges writes. Runtime probe: `TOOLS total: 26`, `propose_ in TOOLS: 11`. |
| READ_TOOL_NAMES is a genuine PRE-mutation snapshot (not re-derived from mutated TOOLS) | ✓ VERIFIED | tools.py L517 `READ_TOOL_NAMES: frozenset[str] = frozenset(TOOLS)` sits immediately after the read-dict literal (L510) and BEFORE the L962 update. Runtime probe: `READ_TOOL_NAMES: 15`, `propose_ in READ_TOOL_NAMES: []`. |
| build_mcp() registers ONLY read tools via READ_TOOL_NAMES; no propose_ can appear | ✓ VERIFIED | mcp_server.py L81-83 iterates `for name in READ_TOOL_NAMES: fn = TOOLS[name]; mcp.tool(...)(fn)`. It never iterates `TOOLS.items()`. Registration is keyed off the frozenset, so write tools are structurally excluded. |
| test_mcp_no_write_tools asserts ABSENCE in tools/list AND call-failure | ✓ VERIFIED | test_mcp.py L138 `assert not any(n.startswith("propose_") ...)`; L140-142 asserts calling `propose_add_transaction` → `isError: True` + `"Unknown tool"`. Both absence and failure covered. |

This is correctness-by-construction: even if a future refactor mutates TOOLS differently, `READ_TOOL_NAMES` is frozen at 15 read names, so the MCP surface cannot leak a write tool without an explicit change to the frozenset itself.

## Additional Verified Claims

| Claim | Status | Evidence |
| --- | --- | --- |
| query.py read_tools == 15 including 3 D-02 additions (web surface == MCP surface) | ✓ VERIFIED | query.py L116-132: exactly 15 `FunctionTool.from_defaults`, including `spending_before_after_purchase` (L122), `monthly_trend` (L130), `account_balances` (L131). `test_agent_read_tools_count` asserts `len==15` and `set == READ_TOOL_NAMES`. |
| auth.key_ok() is the single constant-time hmac check reused by both callers | ✓ VERIFIED | auth.py L30-39 `key_ok()` uses `hmac.compare_digest`. `require_api_key` (L62) delegates to it; main.py middleware (L189) calls `auth.key_ok(key)`. One check, no hand-rolled `==`. |
| /mcp guard covers whole subtree (no trailing-slash / sub-path bypass) | ✓ VERIFIED | main.py L178 `request.url.path.startswith("/mcp")` matches `/mcp`, `/mcp/`, and all sub-paths. 503-when-unset (L179) then 401-on-bad-key (L189) mirrors require_api_key ordering. Bearer fallback L187. |
| combine_lifespans used so APScheduler snapshot lifespan still runs | ✓ VERIFIED | main.py L42 imports `combine_lifespans`; L152 `lifespan=combine_lifespans(lifespan, mcp_app.lifespan)` — scheduler lifespan is first arg, preserved. Full suite passing (scheduler tests green) confirms no startup regression. |
| test_mcp.py 5/5 pass | ✓ VERIFIED | `uv run --with-requirements backend/requirements.txt python -m pytest backend/tests/test_mcp.py -q` → `5 passed`. |
| Full suite: 190 passed, 1 pre-existing failure (test_settings), unrelated to phase 6 | ✓ VERIFIED | Full run → `1 failed, 190 passed`. Failure is `test_settings.py::test_put_settings_requires_key` (expects 401, gets 503 when `_CONFIGURED_KEY` unset in that run). Documented pre-existing in `deferred-items.md` (from Wave 0, before any phase-6 code); file not in phase-6 files_modified. Not a regression. |
| No raw-SQL / free-form tool added to mcp_server.py | ✓ VERIFIED | mcp_server.py registers only TOOLS callables; no `text(` or query construction present — correctness-by-construction preserved. |
| fastmcp pinned `>=3.4,<4` | ✓ VERIFIED | requirements.txt L17 `fastmcp>=3.4,<4`; installed resolves to fastmcp 3.4.4. |

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| MCP test suite green | `pytest backend/tests/test_mcp.py -q` | 5 passed | ✓ PASS |
| TOOLS mutation / snapshot integrity | Python probe on backend.tools | TOOLS=26, READ_TOOL_NAMES=15, propose_ in snapshot=[] | ✓ PASS |
| Full backend suite | `pytest backend/tests -q` | 190 passed, 1 pre-existing failure | ✓ PASS |
| test_settings failure is pre-existing 503/401 isolation, not phase-6 | isolated re-run + deferred-items.md | 503 (unconfigured key), documented Wave 0 | ✓ PASS |

## Requirements Coverage

| Requirement | Source Plan | Status | Evidence |
| --- | --- | --- | --- |
| MCP-01 (co-mounted /mcp, enumerate tools) | 06-01, 06-02 | ✓ SATISFIED | Criterion 1 |
| MCP-02 (read parity with web agent) | 06-02 | ✓ SATISFIED | Criterion 2 |
| MCP-03 (zero write tools, absence) | 06-02 | ✓ SATISFIED | Criterion 3 + security check |
| MCP-04 (API-key gated, unauth rejected) | 06-02 | ✓ SATISFIED | Criterion 4 |

## Anti-Patterns Found

None. No debt markers (TBD/FIXME/XXX) in the phase-6 modified files. No stub returns, no hardcoded empty data on the MCP surface. The `Unknown tool` error path is the intended MCP-03 behavior, not a stub.

## Human Verification Required

1. **Live external-client UAT** (deployment smoke test) — after `docker compose up -d --build`, connect a real external MCP client to `http://host:8001/mcp` with the API key (header or Bearer), enumerate (expect 15 read / 0 write), call `spending_total last_month` and confirm parity with the web chat answer, and confirm an unauthenticated connection is rejected. Requires a running Docker deployment and a third-party MCP client; cannot be exercised by the in-process TestClient. **Automated/code verification is complete — this is the deployment-level confirmation only.**

## Gaps Summary

No gaps. All 4 success criteria and all 9 must-have truths are demonstrably true in the shipped code, and the critical MCP-03 security mechanism (READ_TOOL_NAMES pre-mutation snapshot) is verified at both the source-code and runtime levels. The only remaining item is the live external-client UAT, which is a deployment smoke test, not a code gap — noted for human verification.

---

*Verified: 2026-07-16*
*Verifier: Claude (gsd-verifier)*

## VERIFICATION PASSED
