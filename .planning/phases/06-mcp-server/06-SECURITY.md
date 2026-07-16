---
phase: "06 — MCP Server"
asvs_level: 1 (default, not configured)
block_on: high
threats_total: 8
threats_closed: 8
threats_open: 0
audited_at: 2026-07-16
audited_by: gsd-security-auditor
---

# Security Audit — Phase 06 (MCP Server)

Retroactive verification of the STRIDE register authored at plan time in
`06-01-PLAN.md` and `06-02-PLAN.md`. Every threat below was verified against
implementation code — documentation/intent alone was not accepted as evidence.

## Threat Verification

| Threat ID | Category | Severity | Disposition | Status | Evidence |
|-----------|----------|----------|--------------|--------|----------|
| T-06-01-SC | Tampering | high | mitigate | CLOSED | `backend/requirements.txt:17` pins `fastmcp>=3.4,<4`. Human legitimacy checkpoint recorded in `06-01-SUMMARY.md:23,65` (PrefectHQ/fastmcp, 106 PyPI releases; `package-legitimacy` SUS flag dispositioned as documented false positive before the requirements edit landed). |
| T-06-01-02 | Information Disclosure | low | accept | CLOSED | `backend/tests/conftest.py:54` defines `_TEST_API_KEY = "test-monai-api-key-fixture"`, a throwaway literal distinct from `MONAI_API_KEY`; used via `monkeypatch.setattr(auth_mod, "_CONFIGURED_KEY", _TEST_API_KEY)` (conftest.py:69-70). No real secret present in test fixtures. |
| T-06-02-01 | Information Disclosure | high | mitigate | CLOSED | `backend/main.py:167-191` `mcp_api_key_guard` — outer-app `@app.middleware("http")`, path-gated (`line 178`), returns 503 if `not auth._CONFIGURED_KEY` (line 179-183), 401 if `not auth.key_ok(key)` (line 189-190). Registered via `app.add_middleware`/`@app.middleware` BEFORE `app.mount("/mcp", mcp_app)` at line 194, so it runs ahead of the MCP session manager. Asserted by `test_mcp_requires_key` (`test_mcp.py:145-166`, expects 401) and `test_empty_configured_key_returns_503` (`test_auth.py:130`, expects 503). |
| T-06-02-02 | Elevation of Privilege / Tampering | high | mitigate | CLOSED | `backend/tools.py:517` snapshots `READ_TOOL_NAMES: frozenset[str] = frozenset(TOOLS)` BEFORE `TOOLS.update({...11 propose_* callables...})` at `tools.py:962-974` — the snapshot happens at line 517, the mutation at line 962, so the frozenset is provably pre-mutation. `backend/mcp_server.py:81-83` `build_mcp()` iterates `for name in READ_TOOL_NAMES:` and registers `fn = TOOLS[name]` — never iterates `TOOLS` directly. Verified 15 read tools only; zero `propose_*` names reachable. Asserted by `test_mcp_no_write_tools` (`test_mcp.py:131-142`: no `propose_*` in `tools/list`, and calling `propose_add_transaction` returns `isError: True` / "Unknown tool") and `test_mcp_read_parity` (`test_mcp.py:99-114`: `listed_names == set(READ_TOOL_NAMES)`, `len == 15`). |
| T-06-02-03 | Tampering | high | mitigate | CLOSED | `backend/main.py:178` guard condition is `request.url.path.startswith("/mcp")` — covers `/mcp`, `/mcp/`, and any sub-path under the mount. Middleware is registered as outer-app middleware (decorator at `main.py:167`, executes for every request before routing/mounting resolves `app.mount("/mcp", mcp_app)` at line 194) — Starlette's middleware stack runs before mounted sub-app dispatch by construction. Note: no dedicated test exercises `/mcp/` (trailing slash) or a fabricated sub-path directly — `test_mcp_endpoint_mounted` only checks the exact `/mcp` path is not 404. Code-level mitigation is present and correctly placed (satisfies `mitigate` disposition); test coverage for the trailing-slash/sub-path variant specifically is a gap, noted below as non-blocking (code, not test, is the disposition's bar). |
| T-06-02-04 | Information Disclosure | medium | mitigate | CLOSED | `backend/auth.py:30-39` `key_ok()` is the single comparison: `hmac.compare_digest(key, _CONFIGURED_KEY)` (line 39) — constant-time. `backend/main.py:189` middleware calls `auth.key_ok(key)`, not a hand-rolled `==`. `backend/auth.py:42-63` `require_api_key` (write-route dependency) also routes through the same `key_ok()` (line 62). One check, two call sites, no duplicate/weaker comparison found via grep across `main.py`/`auth.py`/`mcp_server.py`. |
| T-06-02-05 | Information Disclosure | medium | mitigate | CLOSED | Grepped `backend/main.py` and `backend/mcp_server.py` for `logging`/`logger`/`print(`/`.log(` in or near the middleware and MCP registration code — no logging statements reference `key`, `MONAI_API_KEY`, or `Authorization` header values anywhere in the guard (`main.py:167-191`) or `mcp_server.py`. The only occurrences of the string `MONAI_API_KEY` in `main.py` are a docstring comment (line 175) and the header-name lookup (line 184), never passed to a log call. |
| T-06-02-06 | Tampering | high | mitigate | CLOSED | `backend/mcp_server.py` imports only `from fastmcp import FastMCP` and `from backend.tools import PERIODS, READ_TOOL_NAMES, TOOLS` (lines 14, 16) — grepped the full file for `text(` and found zero matches; no raw SQL construction of any kind. `build_mcp()` (lines 68-84) only calls `mcp.tool(name=..., description=...)(fn)` against pre-existing parameterized `TOOLS` callables from `tools.py`; no free-form query tool is registered. |

## Unregistered Flags

None. Checked `## Threat Flags` sections in both `06-01-SUMMARY.md` and
`06-02-SUMMARY.md` — neither file contains a `## Threat Flags` heading (full
section-header grep of both files performed), so there is no new attack
surface reported by the executor beyond the plan-time register.

## Non-Blocking Notes (not counted in `threats_open`)

- **T-06-02-03 test coverage gap:** the `startswith("/mcp")` mitigation is
  present and correctly placed in code (verified above), but no test in
  `test_mcp.py` sends a request to `/mcp/` (trailing slash) or a fabricated
  sub-path (e.g. `/mcp/../other`) to directly exercise the boundary. Severity
  of the underlying threat is `high` and the code mitigation is confirmed
  present, so this does NOT open the threat — it is a test-suite improvement
  suggestion, not a security gap. Recommend adding
  `test_mcp_trailing_slash_requires_key` in a future pass.

## Verification Method

ASVS level not configured in `<config>` — defaulted to L1 (grep-level:
mitigation pattern present in the cited file). Applied per threat:
- `mitigate` dispositions: grepped/read the exact cited file(s) for the
  declared pattern and confirmed line-level presence, not just "a check
  exists somewhere."
- `accept` disposition (T-06-01-02): confirmed the accepted-risk rationale
  (throwaway test key) is true in code, not just asserted in the plan.
- No `transfer` dispositions in this register.

All 8 threats CLOSED. `threats_open: 0` — nothing blocks ship at `block_on: high`.
