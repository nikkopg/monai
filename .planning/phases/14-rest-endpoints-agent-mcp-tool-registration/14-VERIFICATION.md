---
phase: 14-rest-endpoints-agent-mcp-tool-registration
verified: 2026-08-03T09:50:00Z
status: passed
score: 4/4 must-haves verified
behavior_unverified: 0
overrides_applied: 0
---

# Phase 14: REST Endpoints + Agent/MCP Tool Registration Verification Report

**Phase Goal:** Every new write from Phase 13 is reachable from the REST API and from agentic chat, with write tools correctly excluded from the external MCP read-only surface.
**Verified:** 2026-08-03T09:50:00Z
**Status:** passed
**Re-verification:** No — this is the first VERIFICATION.md produced for this phase (backfilled retroactively; none was generated during execution).

**Backfill note:** No prior VERIFICATION.md, no PLAN-frontmatter `must_haves` blocking gate was skipped — must-haves were sourced from ROADMAP.md Success Criteria (the contract) plus each PLAN's own frontmatter `must_haves.truths`, which line up 1:1 with the roadmap criteria. Evidence below was independently re-derived against the current codebase (not copied from SUMMARY.md), including a live pytest run against the project's Postgres dev DB (port 5434, confirmed reachable).

## Goal Achievement

### Observable Truths

| # | Truth (ROADMAP Success Criterion) | Status | Evidence |
|---|---|---|---|
| 1 | User can trigger a transfer, funded buy/sell, balance adjustment, or category change via chat, going through the existing confirm-before-write proposal flow. | ✓ VERIFIED | Mechanics: `backend/tests/test_proposals.py::test_confirm_transfer_writes_both_legs`, `test_confirm_investment_transfer_links_event`, `test_confirm_funded_buy_writes_both_sides`, `test_confirm_funded_sell_writes_both_sides`, `test_confirm_balance_adjustment` — all 5 run live against Postgres and PASS (re-run this session, see Behavioral Verification). Each asserts real DB row values (signed amounts, `is_transfer`, linked `PortfolioEvent.source_account_id`, recomputed `Holding.quantity`), not just HTTP status. Category change (`propose_rename_category`/`propose_merge_category`) predates this phase (Phase 11-04) and remains dual-registered and covered by its own tests, unaffected by this phase's changes. Natural-language tool-selection quality (Test 7 in 14-UAT.md) was explicitly skipped by the user's own prior instruction — "requires a live LLM provider and human observation... not machine-verifiable" — and is treated here as an already-closed, user-waived item, not an open gap requiring a new human-verification cycle. |
| 2 | Each new write tool is registered in BOTH `backend/tools.py`'s TOOLS dict AND `backend/query.py`'s FunctionTool/write_tools list. | ✓ VERIFIED | `backend/tools.py:1408-1424` `TOOLS.update({...})` contains all 5: `propose_add_transfer`, `propose_add_investment_transfer`, `propose_add_funded_buy`, `propose_add_funded_sell`, `propose_add_balance_adjustment`. `backend/query.py:112-114,195-229` dual-registers all 5 as `FunctionTool.from_defaults(...)` entries in `write_tools`. Behavioral proof: `test_new_write_tools_registered_and_excluded` (`backend/tests/test_mcp.py:147`) asserts membership in `TOOLS` for all 5 names and PASSES live. |
| 3 | New write tools do NOT appear on the MCP read-only surface exposed to external clients. | ✓ VERIFIED | `backend/tools.py:679-703`: `TOOLS` dict (16 read entries) built first; `READ_TOOL_NAMES: frozenset[str] = frozenset(TOOLS)` snapshotted at line 703 — BEFORE the `TOOLS.update()` write-tool merge at line 1408. `backend/mcp_server.py:95` (`build_mcp`) iterates only `READ_TOOL_NAMES`, never `TOOLS` directly. Behavioral proof: `test_new_write_tools_registered_and_excluded` performs a live MCP `tools/list` JSON-RPC call and asserts none of the 5 new names appear (`leaked = new_tool_names & listed_names; assert not leaked`) — PASSES. `test_mcp_no_write_tools` and `test_mcp_read_parity` (asserting exactly 16 read names) also PASS, confirming no regression to the exclusion mechanism. |
| 4 | REST endpoints for the new operations exist and route through Phase 13's `apply_*` functions in `backend/writes.py`, not ad-hoc SQL. | ✓ VERIFIED | 5 routes confirmed in `backend/main.py`: `POST /transactions/transfer` (L1049, `apply_add_transfer`), `POST /transactions/investment-transfer` (L1076, `apply_add_investment_transfer`), `POST /portfolio-events/funded-buy` (L493, `apply_add_funded_buy`), `POST /portfolio-events/funded-sell` (L526, `apply_add_funded_sell`), `POST /accounts/{account_id}/adjust-balance` (L264, `apply_add_balance_adjustment`). All 5 are `dependencies=[Depends(require_api_key)]`, `status_code=201`, wrap the `apply_*` call in `try/except ValueError as e: raise HTTPException(422, ...)`, then `db.commit()` → `db.refresh()` → `reset_engine()`. No raw SQL/ORM inserts in any of the 5 handler bodies (visually confirmed; SUMMARY's `grep -c "text("` claim independently spot-checked). Behavioral proof: `test_post_transfer`, `test_post_investment_transfer`, `test_post_funded_buy`, `test_post_funded_sell`, `test_post_adjust_balance` in `backend/tests/test_write_endpoints.py` all PASS live. |

**Score:** 4/4 truths verified (0 present-but-behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `backend/tools.py` — 5 `propose_*` functions | `propose_add_transfer`, `propose_add_investment_transfer`, `propose_add_funded_buy`, `propose_add_funded_sell`, `propose_add_balance_adjustment` (L1198-1424) | ✓ VERIFIED | All 5 present, substantive (each builds a real payload dict and calls `_make_proposal`), registered in the trailing `TOOLS.update()` block, imported and used in `query.py` and (via `TOOLS`) reachable from `main.py`'s confirm dispatch. |
| `backend/query.py` — dual registration | 5 imports + 5 `FunctionTool.from_defaults` entries in `write_tools` | ✓ VERIFIED | L108-114 (imports), L195-229 (`FunctionTool` entries, 3 with explicit LLM-facing `description=` overrides documenting unsigned-magnitude/int-platform-id conventions). `write_tools` is concatenated into the live agent's tool list (`agent = FunctionAgent(tools=read_tools + write_tools, ...)`, L237). |
| `backend/main.py` — confirm dispatch branch | Grouped `elif operation in (...)` branch dispatching all 5 new ops through `apply_*`, guarded against malformed payloads | ✓ VERIFIED | L1449-1472. `try/except (KeyError, TypeError) as e: raise ValueError(...)` maps a malformed payload to the confirm endpoint's existing `ValueError`→422 handling — never an unhandled 500. |
| `backend/main.py` — 5 REST routes | `POST /transactions/transfer`, `/transactions/investment-transfer`, `/portfolio-events/funded-buy`, `/portfolio-events/funded-sell`, `/accounts/{id}/adjust-balance` | ✓ VERIFIED | All 5 present, `require_api_key`-gated, route through `apply_*`, single commit, `reset_engine()` after write. |
| `backend/schemas.py` — 5 `*Create` request models | `TransferCreate`, `InvestmentTransferCreate`, `FundedBuyCreate`, `FundedSellCreate`, `BalanceAdjustmentCreate` | ✓ VERIFIED | L226-289. All money fields use `MoneyDecimal` with `Field(..., gt=0)` on positive-magnitude fields; `BalanceAdjustmentCreate.target_balance` intentionally omits `gt=0` (documented — a target balance may legitimately be ≤0). |
| `backend/tools.py` — `READ_TOOL_NAMES` snapshot | Frozen before write-tool merge, exactly the 16 read tool names | ✓ VERIFIED | L703. `mcp_server.py` docstring at L88-90 has a stale count comment ("16 read + 11 write" — actually 16 write after this phase, harmless comment drift, not a functional bug — see Anti-Patterns). |

### Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| `backend/tools.py` propose_* (5 new) | `backend/writes.py` apply_* | called on confirm, not inside propose_* itself (proposal-then-confirm pattern) | ✓ WIRED | propose_* functions build payload dicts and call `_make_proposal`; the actual `apply_*` call happens in `main.py`'s confirm dispatch (correct — matches existing `propose_add_transaction` pattern). |
| `backend/main.py` confirm dispatch | `backend/writes.py` apply_* (5 new) | direct call inside `_execute_proposal_payload`, guarded try/except | ✓ WIRED | L1457-1470, imports at L60-69. |
| `backend/query.py` write_tools | `backend/tools.py` propose_* (5 new) | `FunctionTool.from_defaults(fn=propose_*)` | ✓ WIRED | L195-229; live agent tool count confirmed by `test_agent_read_tools_count` (16 read tools; write tools present but excluded from that count by `startswith("propose_")` filter). |
| `backend/mcp_server.py` build_mcp | `backend/tools.py` READ_TOOL_NAMES | `for name in READ_TOOL_NAMES: mcp.tool(...)` | ✓ WIRED | L95; never iterates `TOOLS` directly — write tools structurally cannot leak. |
| `backend/main.py` 5 new REST routes | `backend/writes.py` apply_* (5 new) | direct call in route handler body | ✓ WIRED | Confirmed per-route above; funded-buy/sell additionally coerce `Decimal`→`float` before the call (documented fix for a real JSON-serialization bug found during 14-03, verified by passing tests). |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|---|---|---|---|---|
| CHAT-09 | 14-01, 14-02, 14-03 | User can perform the new operations (records, transfers, funded buy/sell, category changes) via chat with the existing confirm-before-write flow; new write tools registered on the agent and kept off the MCP read-only surface. | ✓ SATISFIED | All 4 truths above VERIFIED with live-passing behavioral tests. REQUIREMENTS.md already marks CHAT-09 `[x]` / "Complete" — independently corroborated, not just trusted. No orphaned requirements found for Phase 14 (only CHAT-09 mapped, and it's claimed by all 3 plans consistently). |

### Behavioral Verification

Live Postgres reachable at `postgresql+psycopg://monai:monai@localhost:5434/monai` (container up, `pg_isready` succeeded) — ran the actual phase-14 test files once, not filtered from a full-suite run:

```
uv run --with-requirements backend/requirements.txt python -m pytest \
  backend/tests/test_proposals.py backend/tests/test_mcp.py backend/tests/test_write_endpoints.py -q
```

| Check | Result | Detail |
|---|---|---|
| `test_proposals.py` (16 tests) | ✓ PASS | Includes all 5 propose→confirm integration tests for the new operations (transfer, investment-transfer, funded-buy, funded-sell, balance-adjustment), each with value-level DB assertions (signed amounts, `is_transfer`, linked `source_account_id`, recomputed `Holding.quantity`) — not merely status-code checks. Also covers the malformed-payload 422 guard. |
| `test_mcp.py` (6 tests) | ✓ PASS | Includes `test_new_write_tools_registered_and_excluded` — the exact named test pinning SC#2/SC#3 (TOOLS membership + READ_TOOL_NAMES exclusion + live MCP `tools/list` exclusion). `test_mcp_read_parity` confirms exactly 16 read names exposed; `test_agent_read_tools_count` confirms agent read-tool parity unregressed. |
| `test_write_endpoints.py` (17 tests, 9 phase-14-scoped) | ✓ PASS | 5 happy-path (`test_post_transfer`, `test_post_investment_transfer`, `test_post_funded_buy`, `test_post_funded_sell`, `test_post_adjust_balance`) + 4 validation/auth (`test_transfer_rejects_negative_amount`, `test_funded_buy_rejects_zero_cash_amount`, `test_funded_buy_rejects_nonexistent_platform`, `test_transfer_missing_api_key_401`) all green. Other 8 tests in the file belong to earlier phases (bulk actions, paging, category filter) — unaffected, also passing. |
| **Total** | **39/39 PASS**, 0 failed | Confirms 14-UAT.md's documented "273 passed" full-suite claim on the scoped subset relevant to this phase's must-haves, independently re-run this session rather than trusted from the prior report. |

This satisfies the phase context's guidance: distinguished "verified by running" (this session, live) from "verified by inspection + prior documented run" (14-UAT.md's full-suite 273-pass claim, not independently re-run in full here — only the phase-scoped subset was, which is sufficient to prove all 4 must-have truths).

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|---|---|---|---|---|
| `backend/mcp_server.py` | 88-90 | Docstring says "27 entries (16 read + 11 write)" — stale; actual is 16 read + 16 write = 32 after this phase's 5 additions | ℹ️ Info | Comment drift only. The functional exclusion mechanism (`READ_TOOL_NAMES` snapshot before `TOOLS.update()`) is unaffected and independently verified live via `test_mcp_no_write_tools`/`test_new_write_tools_registered_and_excluded`. Cosmetic — does not block the phase goal. |

No TBD/FIXME/XXX/TODO/HACK/placeholder markers found in `backend/tools.py`, `backend/query.py`, `backend/main.py`, `backend/schemas.py`, or `backend/mcp_server.py` (the 5 files touched by this phase).

### Independent Corroboration Cross-Check

Re-derived the cross-phase audit's claims against current code — all hold, with only minor line-number drift (expected after later phases 15-17 touched the same files):

- 5/5 `apply_*` have a REST route: `main.py` L264 (adjust-balance, was ~264 — exact match), L493 (funded-buy, exact), L526 (funded-sell, exact), L1049 (transfer, exact), L1076 (investment-transfer, exact). No drift.
- 5/5 have a `propose_*` in `tools.py` L1198-1424 — exact match, no drift.
- Dual registration in `query.py` write_tools L112-237 — actual range L108-230 (imports at 108-114, list at 167-229, agent construction closes at 237) — within stated range, no material drift.
- Confirm-dispatch branch `main.py` ~L1458-1470 — actual L1449-1472 (the `elif operation in (...)` opens at 1449, guard closes at 1472) — within 1 line of the cited inner dispatch (1457-1470), no material drift.
- `READ_TOOL_NAMES = frozenset(TOOLS)` at `tools.py` L703 — exact match.
- `mcp_server.py` iterates only `READ_TOOL_NAMES` — confirmed at L95, exact match.

## Human Verification Required

None required as a new gap. One item was already investigated and explicitly closed by prior user instruction (not left open):

- **Live NL tool-selection quality** ("ask the assistant in plain language, e.g. 'move 500k from BCA to Jago', confirm it produces the correct proposal") — documented in `14-UAT.md` Test 7 as `skipped` with reason "requires a live LLM provider and human observation... not machine-verifiable," explicitly per user instruction at the time. This is a live-LLM UX/quality concern, not a code-path concern — the propose→confirm→apply mechanics it would exercise are already proven end-to-end by 5 passing integration tests re-verified live this session. Reopening this as a fresh `human_needed` item would contradict the user's own prior, documented decision to close it; it is noted here for transparency but does not block `passed` status.

## Deviations from PLAN/SUMMARY Claims

None found. Every artifact, wiring link, and behavioral claim cross-referenced against SUMMARY.md text held up under independent re-derivation (line numbers, test names, test outcomes). One pre-existing minor doc-comment staleness noted above (Anti-Patterns) — does not misrepresent behavior, only a stale entry count in a docstring.

## Gaps Summary

No gaps. All 4 ROADMAP Success Criteria are VERIFIED with live-passing behavioral evidence (not just structural/grep checks): dual registration, MCP exclusion, REST routing through Phase-13 `apply_*` primitives, and confirm-before-write chat mechanics are all proven by tests that assert real database row values, re-run against the live Postgres dev DB this session. CHAT-09 is SATISFIED. No orphaned requirements. No blockers, no unresolved debt markers, no disabled/circular tests, no stub code found in the 5 files this phase touched.

---

_Verified: 2026-08-03T09:50:00Z_
_Verifier: Claude (gsd-verifier) — retroactive backfill verification_
