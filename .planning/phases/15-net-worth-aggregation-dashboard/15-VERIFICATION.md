---
phase: 15-net-worth-aggregation-dashboard
verified: 2026-07-31T09:55:00Z
human_verified: 2026-07-31T10:35:00Z
status: passed
score: 8/8 must-haves verified
human_verification_result: "PASSED — rebuilt stack; live GET /net-worth 200 and rendered /cashflow DOM confirm hero == liquid + investment (310,564,818 = 236,186,300 + 74,378,518), split + breakdown render, no investment account under Liquid accounts, no delta chip, coverage 3/3. See 15-HUMAN-UAT.md."
behavior_unverified: 0
overrides_applied: 0
human_verification:
  - test: "Rebuild the deployed stack (`docker compose up -d --build`), open http://localhost:3001/ (/cashflow), and visually confirm: (1) hero 'Net worth' number == Liquid stat card + Investment stat card; (2) no type='investment' account appears under 'Liquid accounts' — its value only appears under 'Investment platforms'; (3) no ▲/▼ delta chip on the hero; (4) split row + breakdown cards render for an account with a balance but zero transactions this period."
    expected: "All four checks hold visually on the running app; hero/split/breakdown match the GET /net-worth payload exactly."
    why_human: "This is the plan's own Task 3 checkpoint:human-verify (gate: blocking). It was auto-approved by the executing pipeline's --auto mode without an actual human eyeball (15-02-SUMMARY.md 'Deferred Human Verification' section says so explicitly), and no 15-UAT.md exists in the phase directory. The currently-running backend container on :8001 returns 404 for /net-worth — i.e. the live deployed stack is stale and has NOT been rebuilt with this phase's code (deploy-requires-rebuild memory), so a human checking the live app right now would see the OLD dashboard, not this phase's work. A rebuild is required before this check can be done, and rendering/visual layout cannot be verified by grep/static analysis."
---

# Phase 15: Net Worth Aggregation + Dashboard Verification Report

**Phase Goal:** The user has one trustworthy number for their entire financial life, with visibility into how it splits.
**Verified:** 2026-07-31
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Net worth = liquid accounts + investment platforms, each real account/holding counted exactly once (NW-01, ROADMAP SC#1) | VERIFIED | `net_worth()` (backend/tools.py:518-566) partitions `account_balances()` rows strictly by `type=='liquid'`, sums investment side from `portfolio_summary(db)['total_value']` (disjoint data source — never re-summed). Live smoke test against the real DB: `total: 310474634.28 == liquid_total(236186300.0) + investment_total(74288334.28)`; `liquid_accounts` type set == `{'liquid'}` only (no investment account leaked in). Unit test `test_sum_counts_each_row_once` proves an investment-typed account's balance is excluded from `liquid_total` and its id absent from `liquid_accounts`. |
| 2 | Liquid vs investment split with a per-side breakdown, not just the combined total (NW-02, ROADMAP SC#2) | VERIFIED | Backend payload carries `liquid_total`/`investment_total`/`liquid_accounts`/`investment_groups` (backend/schemas.py:91-100, confirmed live). Frontend (ui/app/cashflow/page.tsx:432-464) renders a "Liquid"/"Investment" split-row (two stat cards) plus a "Liquid accounts" per-account card (L562-628, sourced from `netWorthData.liquid_accounts`) and an "Investment platforms" per-platform card (L630-685+, sourced from `netWorthData.investment_groups`, no delta line). `npx tsc --noEmit` clean. |
| 3 | The net-worth query's account-type filter is asserted to cover 100% of accounts — no silently dropped or double-included row (ROADMAP SC#3) | VERIFIED | `net_worth()` raises `ValueError` when `len(liquid_rows)+len(investment_rows) != len(rows)` (backend/tools.py:544-548). `GET /net-worth` catches it → `HTTPException(422, ...)` (backend/main.py:742-745), never a raw 500. `test_unclassified_type_raises` forces the gap via `monkeypatch` on `account_balances` (never a live CHECK-violating insert) and asserts the raise — passes. |
| 4 | `net_worth` is a zero-arg, read-only agent/MCP tool: in `READ_TOOL_NAMES`, absent from every write surface | VERIFIED | `TOOLS['net_worth'] = net_worth_tool` (zero-arg wrapper, backend/tools.py:569-581, 692) registered before the `READ_TOOL_NAMES = frozenset(TOOLS)` freeze (line 700). Programmatic check: `'net_worth' in READ_TOOL_NAMES` and `TOOLS['net_worth'] is net_worth_tool` — both true; `inspect.signature(net_worth_tool)` has zero params. `test_net_worth_is_read_only` additionally asserts every name outside `READ_TOOL_NAMES` starts with `propose_`. |
| 5 | `net_worth` is dual-registered on the agent surface (query.py), not just TOOLS/MCP (chat-tool-dual-registration memory) | VERIFIED | backend/query.py:104 imports `net_worth_tool`; L163 `FunctionTool.from_defaults(fn=net_worth_tool, name="net_worth")` inside `_get_agent_workflow`. `test_net_worth_registered_for_agent` source-greps this exact line — passes. `build_mcp()` (backend/mcp_server.py:82-98) loops `READ_TOOL_NAMES` and registers `TOOLS[name]` (= `net_worth_tool`), so the MCP surface also gets the zero-arg wrapper, not the `db`-taking `net_worth` — confirms the WR-01 code-review fix (commit c6474e3) is actually applied, not just claimed. |
| 6 | The "Liquid accounts" per-account breakdown does not render a misleading period-scoped delta (WR-02 code-review fix) | VERIFIED | grep for `signed(` / `period_net` on the liquid-account row markup (ui/app/cashflow/page.tsx L578-627) shows only `money(a.current_balance)`; no `signed(a.period_net)` line remains — matches commit c6474e3's stated removal. |
| 7 | Full backend test suite stays green except the pre-existing, documented-unrelated `test_settings.py::test_put_settings_requires_key` failure | VERIFIED | Ran `cd backend && uv run --with-requirements requirements.txt python -m pytest tests/ -q`: **279 passed, 1 failed** — the single failure is exactly `test_put_settings_requires_key` (503 vs 401), matching STATE.md's pre-existing-since-Phase-12 note. `tests/test_net_worth.py` alone: **6/6 passed**. |
| 8 | User visually confirms the deployed `/cashflow` dashboard shows the hero/split/breakdown correctly (plan 15-02 Task 3, `checkpoint:human-verify gate="blocking"`) | ⚠️ Not yet performed — routed to human verification | Code-complete and typecheck-clean, but the plan's own blocking human-verify checkpoint was auto-approved without an actual visual check (15-02-SUMMARY.md says so explicitly); no `15-UAT.md` exists. The live running backend container (port 8001) currently 404s on `/net-worth` — the deployed stack predates this phase and needs a rebuild before a human can see the new dashboard. |

**Score:** 7/8 truths verified (1 routed to human verification; 0 failed)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/tools.py` | `net_worth()`, `net_worth_tool()`, additive `account_balances().type`, TOOLS/READ_TOOL_NAMES registration | ✓ VERIFIED | All present, substantive (not stubs), wired (imported by main.py/query.py/mcp_server.py) |
| `backend/schemas.py` | `NetWorth(BaseModel)` | ✓ VERIFIED | Present at L91-100, mirrors CashflowSummary's loose style, used by the endpoint's `response_model` |
| `backend/main.py` | `GET /net-worth` (open read, 422-safe) | ✓ VERIFIED | Present at L733-746; no `require_api_key` dependency; try/except ValueError→422 confirmed |
| `backend/query.py` | agent registration (`read_tools` list) | ✓ VERIFIED | `FunctionTool.from_defaults(fn=net_worth_tool, name="net_worth")` present and used by `_get_agent_workflow` |
| `backend/mcp_server.py` | `MCP_DESCRIPTIONS["net_worth"]` + auto-registration via `READ_TOOL_NAMES` loop | ✓ VERIFIED | Description present (L74-78); `build_mcp()` needs no additional code (confirmed by reading the loop) |
| `backend/tests/test_net_worth.py` | 6 test cases (partition, split-reconcile, coverage-raise, read-only, agent-registration, endpoint) | ✓ VERIFIED | All 6 present, substantive (real DB fixtures + monkeypatch, not trivial asserts), 6/6 pass |
| `ui/app/cashflow/page.tsx` | Server-sourced hero, split row, per-side breakdowns, gate, empty/error states | ✓ VERIFIED | All present; `npx tsc --noEmit` clean; no client-side net-worth `reduce` remains (grepped, zero matches) |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `net_worth()` | `account_balances()` | Python-side filter on `type=='liquid'` | ✓ WIRED | Confirmed by reading source + live smoke test (`liquid_accounts` type set == `{'liquid'}`) |
| `net_worth()` | `portfolio_summary(db)` | `.total_value` / `.groups` | ✓ WIRED | Confirmed; investment side never re-derived from holdings/portfolio_events directly |
| `GET /net-worth` | `net_worth(db)` | try/except ValueError → HTTPException(422) | ✓ WIRED | Read directly in main.py:742-745; unit test + coverage-assertion test both green |
| `query.py` agent `read_tools` | `net_worth_tool` | `FunctionTool.from_defaults(fn=net_worth_tool, name="net_worth")` | ✓ WIRED | Source-grepped and asserted by `test_net_worth_registered_for_agent` |
| `TOOLS`/`READ_TOOL_NAMES` | `net_worth_tool` | dict entry before freeze line | ✓ WIRED | Confirmed programmatically (`TOOLS['net_worth'] is net_worth_tool`) |
| `ui/app/cashflow/page.tsx` hero | `GET /net-worth` | `fetch("/api/net-worth")` in `loadNetWorth()`, bound to `netWorthData.total` | ✓ WIRED | Confirmed by reading L135-155 (fetch) and L359 (render binding) |
| Liquid/Investment breakdown cards | `netWorthData.liquid_accounts` / `investment_groups` | `.map()` render | ✓ WIRED | Confirmed at L578, L647 |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|---------------------|--------|
| `/cashflow` hero + split + breakdown | `netWorthData` | `GET /api/net-worth` → `backend.main.net_worth_endpoint` → `net_worth(db)` → real Postgres queries (`account_balances()` SQL + `portfolio_summary()` holdings/prices) | Yes — live smoke test against the real dataset returned `total: 310,474,634.28`, `accounts_covered/total: 9/9`, 8 liquid accounts, 5 investment platforms (non-empty, non-static) | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| `net_worth()` composes real DB data, one count each side | Started a local `uvicorn backend.main:app` against the live dev Postgres; `GET /net-worth` | 200; `total==liquid_total+investment_total` True; `liquid_accounts` type set == `{'liquid'}` only; `accounts_covered/accounts_total == 9/9` | ✓ PASS |
| Coverage-assertion raises and maps to 422 | `pytest backend/tests/test_net_worth.py::test_unclassified_type_raises` (monkeypatch-forced gap) | Passed | ✓ PASS |
| Read-only / dual-registration contract | `pytest backend/tests/test_net_worth.py::test_net_worth_is_read_only test_net_worth_registered_for_agent` + direct `python -c` import check | Passed / True | ✓ PASS |
| Full backend regression | `cd backend && uv run --with-requirements requirements.txt python -m pytest tests/ -q` | 279 passed, 1 failed (pre-existing `test_settings.py::test_put_settings_requires_key`, documented in STATE.md since Phase 12) | ✓ PASS (no phase-15 regression) |
| Frontend strict typecheck | `cd ui && npx tsc --noEmit` | Clean, no errors | ✓ PASS |
| Live dashboard visual render | N/A — requires running deployed stack + human eyeball | Not run (deployed container is stale — 404s on `/net-worth`) | ? SKIP → routed to human verification |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|--------------|--------|----------|
| NW-01 | 15-01, 15-02 | User sees a main dashboard where net worth = liquid + investment, each counted exactly once | ✓ SATISFIED | Backend composition + coverage assertion + frontend hero binding, all verified above. **Note:** `.planning/REQUIREMENTS.md` still shows this as `[ ]` unchecked / "Pending" in the Traceability table (lines 14, 95) — a stale tracking doc, not a code gap (other completed-phase requirements like ACCT-02/ACCT-03 are correctly marked `[x]`/"Complete", so this looks like a missed doc-update step for phase 15, worth fixing but not blocking). |
| NW-02 | 15-01, 15-02 | User sees the liquid vs investment split with per-side breakdowns | ✓ SATISFIED | Split row + two breakdown cards verified above. Same stale-tracking-doc note as NW-01 applies. |

No orphaned requirements — REQUIREMENTS.md maps only NW-01/NW-02 to Phase 15 and both are claimed in the plans' frontmatter.

### Anti-Patterns Found

None. Scanned `backend/tools.py`, `backend/main.py`, `backend/query.py`, `backend/schemas.py`, `backend/mcp_server.py`, `backend/tests/test_net_worth.py`, and `ui/app/cashflow/page.tsx` for `TBD`/`FIXME`/`XXX`/`TODO`/`HACK`/`PLACEHOLDER`/empty-implementation patterns — zero matches. The two WARNING-level findings from `15-REVIEW.md` (WR-01: `db` param leak onto tool schemas; WR-02: misleading `period_net` delta) were both confirmed fixed in commit `c6474e3` by direct source inspection (see Truths #5 and #6 above) — not just trusted from the commit message.

### Human Verification Required

### 1. Live `/cashflow` dashboard visual check (Plan 15-02 Task 3 checkpoint)

**Test:** Rebuild the stack (`docker compose up -d --build` — the running container is currently stale and 404s on `/net-worth`), open `http://localhost:3001/`, and:
1. Confirm the hero "Net worth" number equals the Liquid stat-card total + Investment stat-card total.
2. Confirm no `type='investment'` account (e.g. the legacy "Investments" account) appears in the Liquid subtotal or under "Liquid accounts" — its value should only appear under "Investment platforms."
3. Confirm there is no ▲/▼ delta chip on the hero.
4. Confirm the split row + breakdown cards still render for an account that has a balance but no transactions in the selected period.

**Expected:** All four checks pass visually, matching the already-verified `GET /net-worth` payload (`total: 310,474,634.28`, 8 liquid accounts, 5 investment platforms, no coverage gap).
**Why human:** This is the plan's own `checkpoint:human-verify gate="blocking"` (Task 3 of 15-02-PLAN.md). It was auto-approved by the executing pipeline's `--auto` mode without an actual visual check (15-02-SUMMARY.md's "Deferred Human Verification" section states this explicitly), and no `15-UAT.md` was produced. Visual rendering, layout, and "does this look right" cannot be verified by static analysis or grep — and the currently-deployed container predates this phase's code, so this check cannot even be attempted until a rebuild happens.

### Gaps Summary

No functional gaps. All backend and frontend code for NW-01/NW-02/SC#3 is implemented, tested (6/6 net-worth unit tests + 279/280 full suite, the 1 failure pre-existing and unrelated), and typecheck-clean. Both code-review warnings (WR-01, WR-02) from `15-REVIEW.md` were verified fixed at the source-code level, not just trusted from the commit message. The single open item is the plan's own blocking human-verify checkpoint, which was never actually performed against a rebuilt stack — this is a process gap (auto-approved checkpoint), not evidence of broken code. A secondary, non-blocking observation: `.planning/REQUIREMENTS.md`'s checkbox/traceability status for NW-01/NW-02 was not updated to reflect phase completion (cosmetic, unlike other completed requirements in the same file).

---

_Verified: 2026-07-31_
_Verifier: Claude (gsd-verifier)_
