---
phase: 06-mcp-server
plan: 02
subsystem: api
tags: [fastmcp, mcp, auth, agentic-tools, wiring]

requires: [06-01]
provides:
  - "backend/mcp_server.py:build_mcp() — FastMCP server exposing the 15 read-only backend.tools.TOOLS callables at /mcp"
  - "backend/auth.py:key_ok() — shared constant-time API-key check, reused by require_api_key and the /mcp middleware"
  - "backend/tools.py:READ_TOOL_NAMES — frozenset snapshot of the 15 read-tool names, taken before TOOLS.update() merges in the 11 propose_* write tools"
  - "backend/query.py read_tools list at 15 entries (D-02 parity — web agent surface == MCP surface)"
affects: []

tech-stack:
  added: []
  patterns:
    - "MCP endpoint co-mounted at /mcp via mcp.http_app(path='/') + app.mount('/mcp', mcp_app); combine_lifespans(lifespan, mcp_app.lifespan) preserves the existing APScheduler snapshot lifespan"
    - "Outer-app @app.middleware('http') guard scoped to request.url.path.startswith('/mcp'), registered before app.mount so it runs ahead of the mounted sub-app's own request handling"
    - "READ_TOOL_NAMES frozenset captured immediately after the TOOLS dict literal, before TOOLS.update() adds write tools — the correct way to get 'read-only names' from a registry that is later mutated to include writes"

key-files:
  created: [backend/mcp_server.py]
  modified: [backend/auth.py, backend/query.py, backend/main.py, backend/tools.py, backend/tests/test_mcp.py]

key-decisions:
  - "TOOLS is NOT a stable 15-entry read-only dict by the time consuming modules import it — backend/tools.py mutates it to 26 entries (TOOLS.update() with the 11 propose_* callables) at the bottom of the same module. Iterating TOOLS.items() directly in mcp_server.py would have silently registered all 26 tools including writes, breaking MCP-03/D-03. Fixed by adding backend.tools.READ_TOOL_NAMES, a frozenset snapshot taken right after the read-tool dict literal and before .update() runs — this is now the single source of truth for 'which TOOLS entries are read-only', consumed by both mcp_server.py and (indirectly, via TOOLS[name] lookups) query.py's list stays independently authored."
  - "MCP auth middleware accepts both the existing MONAI_API_KEY header AND Authorization: Bearer <key> (same underlying secret via key_ok()) — RESEARCH A2's client-agnostic fallback, since some external MCP clients only support Bearer."
  - "Tests speak the actual streamable-HTTP JSON-RPC wire protocol (initialize -> notifications/initialized -> tools/list | tools/call) against a context-managed TestClient, rather than calling FastMCP's internal Python API — this exercises the exact codepath (including the outer auth middleware) a real external MCP client hits. Discovered mid-implementation that TestClient must be used as `with client:` for the combined lifespan to actually start the FastMCP session manager; a bare (non-context-managed) TestClient never runs FastAPI lifespan events and the session manager raises 'Task group is not initialized'."
  - "test_mcp_requires_key uses the api_key fixture (configures a real key) then omits the header — mirrors test_auth.py's missing-key pattern. Without a configured key, the guard correctly returns 503 (fail-closed, matches require_api_key's existing contract) rather than 401; the 401 path specifically requires a configured-but-mismatched/missing key."

requirements-completed: [MCP-01, MCP-02, MCP-03, MCP-04]

duration: ~55min
completed: 2026-07-16
status: complete
---

# Phase 06 Plan 02: MCP Server Wave 1 — End-to-End Slice Summary

**Co-mounted a read-only, API-key-gated FastMCP server at `/mcp` on monai's existing FastAPI process, registering the 15 `backend/tools.py` read callables (verbatim, single source of truth) with hand-authored period-enumerating descriptions, while closing the web-agent/MCP parity gap and preserving the existing APScheduler lifespan.**

## Performance

- **Duration:** ~55 min (includes fastmcp local install + API-surface confirmation + manual JSON-RPC protocol exploration to derive the test harness)
- **Tasks:** 2 (both `type="auto" tdd="true"`)
- **Files modified:** 5 (1 created: `backend/mcp_server.py`; 4 modified: `backend/auth.py`, `backend/query.py`, `backend/main.py`, `backend/tools.py`; 1 test file filled in: `backend/tests/test_mcp.py`)

## Accomplishments

- `backend/mcp_server.py` (new): `build_mcp()` builds a `FastMCP("monai finance (read-only)")` instance and registers exactly the 15 read-only tools from `backend.tools.READ_TOOL_NAMES`, each with a hand-authored, period-enumerating description (`MCP_DESCRIPTIONS`, sourced from `backend.tools.PERIODS` — never hard-coded). Zero `propose_*` names present.
- `backend/tools.py`: added `READ_TOOL_NAMES: frozenset[str]`, captured immediately after the 15-entry `TOOLS` dict literal and before the later `TOOLS.update()` call that merges in the 11 write tools. This is the fix for a real discrepancy between the plan text (which assumed `TOOLS` stays 15 entries) and the actual runtime state of the module (`TOOLS` ends up with 26 entries after import) — see Deviations.
- `backend/auth.py`: extracted `key_ok(key) -> bool`, the single constant-time `hmac.compare_digest` check, now called by both `require_api_key` (existing write-route dependency) and the new `/mcp` middleware (D-04 one-secret/one-check).
- `backend/query.py`: added `spending_before_after_purchase`, `monthly_trend`, `account_balances` to the web agent's `read_tools` list (both the import block and the `FunctionTool.from_defaults(...)` list) — closes D-02, web-agent surface now == MCP surface at 15 read tools.
- `backend/main.py`: `mcp = build_mcp()`; `mcp_app = mcp.http_app(path="/")`; `FastAPI(lifespan=combine_lifespans(lifespan, mcp_app.lifespan))` (existing scheduler lifespan preserved, confirmed via test logs showing both "Scheduler started" and "StreamableHTTP session manager started"); `app.mount("/mcp", mcp_app)` → endpoint is exactly `/mcp`. An outer-app `@app.middleware("http")` guard (`mcp_api_key_guard`), registered before the mount, rejects any `/mcp*` request with a missing/invalid key (401) or an unconfigured server (503) before the MCP session manager ever sees it; accepts `MONAI_API_KEY` header or `Authorization: Bearer <key>` (same secret).
- `backend/tests/test_mcp.py`: all 5 skip markers removed; each test now drives the real streamable-HTTP JSON-RPC protocol against a context-managed `TestClient` (`with client:` — required so the combined lifespan actually starts). Confirmed live: `tools/list` returns exactly the 15 `READ_TOOL_NAMES`; a `tools/call` on `spending_total` returns a `structuredContent` dict byte-identical to the direct `TOOLS["spending_total"](...)` call; calling `propose_add_transaction` over MCP returns `isError: true` / `"Unknown tool: 'propose_add_transaction'"`; an unauthenticated request is rejected 401.

## Task Commits

Each task was committed atomically:

1. **Task 1: Build mcp_server.py, extract auth.key_ok(), and close D-02 parity in query.py** — `5a199fa` (feat)
2. **Task 2: Co-mount /mcp with combined lifespan + auth middleware, and fill the MCP tests green** — `8f3eb7b` (feat)

**Plan metadata:** (this commit, docs: complete plan)

## Files Created/Modified

- `backend/mcp_server.py` (created) — `build_mcp()`, `MCP_DESCRIPTIONS`, `_PERIOD_HELP`
- `backend/tools.py` — added `READ_TOOL_NAMES` frozenset (pre-mutation snapshot of the 15 read tool names)
- `backend/auth.py` — added `key_ok(key) -> bool`; `require_api_key` now delegates to it
- `backend/query.py` — `read_tools` list grew from 12 to 15 (added `spending_before_after_purchase`, `monthly_trend`, `account_balances`)
- `backend/main.py` — co-mounted `/mcp`, combined lifespan, outer-app auth middleware
- `backend/tests/test_mcp.py` — 5 tests un-skipped and implemented against the real MCP wire protocol

## Decisions Made

- **TOOLS registry mutation discovered mid-implementation (Rule 1 auto-fix):** the plan's PATTERNS.md/RESEARCH.md both describe `backend.tools.TOOLS` as "the 15 read tools" — true only of the dict *literal* at tools.py L493-510. In the actual module, `TOOLS.update({...11 propose_* tools...})` runs unconditionally right after the write-tool function defs, so by the time any importer (`mcp_server.py`, `query.py`) sees `TOOLS`, it already has 26 entries. Registering `TOOLS.items()` directly in `build_mcp()` would have silently exposed all 11 write tools over MCP — a direct MCP-03/D-03 violation the plan's own acceptance criteria (`test_mcp_no_write_tools`) would have caught, but only after the fact. Fixed at the source: `backend.tools.READ_TOOL_NAMES = frozenset(TOOLS)` captured immediately after the literal, before `.update()` — single source of truth for "which entries are read-only," consumed by `mcp_server.py`. This is a Rule 1 fix (code doesn't work as intended per the plan's stated behavior) applied at the root (the registry itself), not patched around in the consumer.
- Confirmed the exact FastMCP 3.4.4 API surface at implementation time per RESEARCH's Open-Q1: `mcp.tool(name=..., description=...)(fn)` (the two-step call form) works as documented; `combine_lifespans` imports cleanly from `fastmcp.utilities.lifespan`; `mcp.http_app(path="/")` returns a `StarletteWithLifespan` whose `.lifespan` combines correctly.
- Middleware accepts both `MONAI_API_KEY` and `Authorization: Bearer <key>` headers (RESEARCH A2) — same underlying secret, no new secret introduced, for client-agnostic MCP tooling.
- Live-verified (manual Python REPL exploration before writing the test file) that: (a) `TestClient` must be used as a context manager for FastAPI's combined lifespan to actually start the FastMCP session manager — a bare `TestClient(app)` (as used non-context-managed elsewhere in the suite) never fires lifespan events and the MCP session manager raises `RuntimeError: Task group is not initialized`; (b) the `/mcp` trailing-slash redirect (307) is normal FastMCP/Starlette routing behavior, handled transparently by `follow_redirects=True`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `TOOLS` registry is 26 entries, not 15, by the time consumers import it**
- **Found during:** Task 1, while writing `build_mcp()`
- **Issue:** The plan's `<action>` text for Task 1(a) says "iterate `backend.tools.TOOLS.items()`... Register ONLY `TOOLS` — never the propose_* dict (D-03)." This assumes `TOOLS` itself is the 15-entry read registry. In the actual file, `TOOLS.update({...propose_* tools...})` executes at module load (tools.py L954-967), so `TOOLS` is 26 entries by the time any importing module sees it. Iterating `TOOLS.items()` verbatim would have registered all 26 (15 read + 11 write) as MCP tools — silently violating MCP-03/D-03 at the exact seam the plan's threat model (T-06-02-02) calls out as high-severity.
- **Fix:** Added `backend.tools.READ_TOOL_NAMES: frozenset[str] = frozenset(TOOLS)`, captured in `tools.py` immediately after the read-tool dict literal and before the `.update()` call. `mcp_server.py:build_mcp()` iterates `READ_TOOL_NAMES` and looks up each callable via `TOOLS[name]`, guaranteeing read-only registration regardless of `TOOLS`'s later mutated state.
- **Files modified:** `backend/tools.py` (added `READ_TOOL_NAMES`), `backend/mcp_server.py` (iterates `READ_TOOL_NAMES` instead of `TOOLS.items()`)
- **Commit:** `5a199fa`
- **Verified:** `build_mcp()` registers exactly 15 tools with zero `propose_` prefixes (confirmed via `asyncio.run(mcp.list_tools())` and `test_mcp_no_write_tools`).

None of the other deviation rules (2/3/4) were triggered — the rest of the plan's action text (auth extraction, query.py parity edit, main.py co-mounting, middleware shape) matched the actual codebase exactly as described in PATTERNS.md/RESEARCH.md.

## Issues Encountered

- Full-suite run (`python -m pytest backend/tests -q`) shows **190 passed, 1 failed** — the 1 failure is `backend/tests/test_settings.py::test_put_settings_requires_key`, already documented as pre-existing/out-of-scope in `.planning/phases/06-mcp-server/deferred-items.md` (from Wave 0). Two of the other three previously-deferred failures (`test_prices.py::test_fetch_idx_price_fallback`, `test_prices.py::test_fetch_idx_price_success`, `test_scheduler.py::test_build_scheduler_registers_daily_job`) now pass in this environment — likely resolved by transitive dependencies pulled in alongside the `fastmcp` install, or unrelated environment drift since Wave 0. This is a net improvement (3 fewer failures than the documented baseline), not a regression introduced by this plan's changes; `deferred-items.md` left unmodified since the remaining failure is still present and still out of scope.
- `fastmcp` was not yet installed in the local `.venv` at execution start (Wave 0 only pinned it in `requirements.txt`); installed via `uv pip install 'fastmcp>=3.4,<4'` inside the existing `.venv`, resolving to `fastmcp==3.4.4` — matches the pin exactly, no legitimacy re-check needed (already approved in Wave 0's checkpoint).

## User Setup Required

- **Docker image rebuild required before live/UAT** (MEMORY: "deploy requires rebuild") — `docker compose up -d --build` to pick up the `fastmcp` dependency and the new `/mcp` mount before any external MCP client (e.g. Claude Desktop) can connect to `http://host:8001/mcp`.
- **Live UAT** (per plan's `<verification>` section, deferred to phase verification): connect an external MCP client to `http://host:8001/mcp` with the `MONAI_API_KEY` header (or `Authorization: Bearer <key>`), enumerate tools (expect 15 read / 0 write), call `spending_total` for `last_month`, confirm the result matches the web chat agent's answer for the same question, and confirm an unauthenticated connection is rejected. Not run in this plan — requires a running Docker deployment and an actual external MCP client.

## Next Phase Readiness

Phase 06 (MCP Server) is code-complete: both plans (06-01 Wave 0 foundation, 06-02 Wave 1 end-to-end slice) are done. All four phase requirements (MCP-01..MCP-04) have passing automated test coverage. Remaining before the phase can be marked fully verified: the live UAT step above (Docker rebuild + external MCP client connection test) — this is phase-level verification, not blocked on any further plan work.

---
*Phase: 06-mcp-server*
*Completed: 2026-07-16*

## Self-Check: PASSED

All created/modified files verified present (backend/mcp_server.py, backend/auth.py, backend/query.py, backend/main.py, backend/tools.py, backend/tests/test_mcp.py, .planning/phases/06-mcp-server/06-02-SUMMARY.md). Both task commits (5a199fa, 8f3eb7b) verified present in git log.
