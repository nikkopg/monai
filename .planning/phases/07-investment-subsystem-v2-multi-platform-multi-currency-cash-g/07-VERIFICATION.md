---
phase: 07-investment-subsystem-v2-multi-platform-multi-currency-cash-g
verified: 2026-07-12T16:17:02Z
status: passed
human_verified: 2026-07-13T00:00:00Z
human_verified_note: "All 3 human-UAT items passed — VZ-01 pie fixed (Number-coercion), VZ-02 line chart (Jul-11 corrupt data corrected), CH-01 live chat add confirmed working by user. See 07-HUMAN-UAT.md."
score: 22/22 must-haves verified
behavior_unverified: 0
overrides_applied: 0
human_verification:
  - test: "Allocation pie chart (VZ-01) — visually confirm the pie renders current IDR market value per slice and the asset-type↔platform toggle switches the grouping correctly on /investments"
    expected: "Pie shows proportional slices summing to total portfolio value; toggling between asset-type and platform re-renders with the other grouping; empty-portfolio state shows the 'Add a holding' message"
    why_human: "Visual rendering, proportions, and interactive toggle behavior cannot be verified via static code/grep — code presence, data wiring, and explicit-height wrapper are confirmed programmatically, but actual pixel-level correctness needs a human eye"
  - test: "Value-history line chart (VZ-02) — visually confirm the portfolio-value curve and P&L curve render correctly with the 1M/3M/6M/All range selector, 'like Bitget'"
    expected: "Line chart shows a smooth time series; switching Value/P&L view swaps the rendered line; range pills re-fetch and trim the series; sparse-history (<2 points) shows the 'Not enough history yet' message"
    why_human: "Visual rendering and range-selector interaction cannot be verified statically — code wiring, height-280 wrapper, and endpoint contract are confirmed programmatically, but actual chart behavior in a browser needs a human eye"
  - test: "Chat multi-platform add/delete — ask the chat agent to add a holding on a named platform (e.g. 'add 1 BTC on Bibit') and confirm it resolves the platform name, proposes with platform_id set, and the confirm succeeds without a 500"
    expected: "Agent calls find_platforms to resolve 'Bibit' -> platform_id, proposes add_holding with that platform_id in the after dict, user confirms, holding is created with platform_id populated (no NOT NULL IntegrityError) — the CH-01 regression stays closed end-to-end through the live LLM tool-calling path"
    why_human: "The regression-closure test (test_confirm_add_holding_persists_platform_id) proves the confirm-time delegation is correct with a hand-built proposal payload, but does not exercise the live LLM's tool-selection behavior (does the model actually call find_platforms when the platform is named ambiguously, does it ask the user when ambiguous per CH-01's design) — that requires a live conversational session"
---

# Phase 7: Investment Subsystem v2 (multi-platform, multi-currency, cash, gold, viz) Verification Report

**Phase Goal:** The portfolio reflects how the user actually holds assets — the same asset
across multiple platforms, cost basis in the currency it was bought in, cash and physical
gold as first-class positions — and surfaces allocation at a glance.
**Verified:** 2026-07-12T16:17:02Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `fx.get_rate` returns a Decimal sourced from frankfurter.dev, never a float | ✓ VERIFIED | `backend/fx.py:43-67` `fetch_frankfurter_rate` parses `Decimal(str(rate))`; `get_rate` returns the same type throughout |
| 2 | A second `get_rate` call for the same (date,base,quote) returns the cached row without a second HTTP call (FX-05) | ✓ VERIFIED | `backend/fx.py:107-131` cache-first read + `db.flush()` after insert (CR-02 fix, confirmed `autoflush=False` in `backend/db.py:17`); `test_get_rate_second_call_same_pair_does_not_refetch` passes with a fake DB that genuinely models autoflush (WR-01 fix confirmed) |
| 3 | An invalid currency code is rejected before any HTTP request (SSRF guard) | ✓ VERIFIED | `backend/fx.py:104-105` regex check before adapter call; `mock.assert_not_called` pattern in test_fx.py |
| 4 | The FX adapter never raises — HTTP/parse failure returns None | ✓ VERIFIED | `backend/fx.py:55-67` try/except wraps entire body, catches HTTPError/KeyError/ValueError/TypeError |
| 5 | cash and gold have explicit TTL entries in prices.py | ✓ VERIFIED | `backend/prices.py:47-59` `TTL_BY_ASSET_TYPE["gold"]` and `["cash"]` both present with explanatory comments |
| 6 | A USD-denominated buy converts to IDR at trade-date rate; current value uses today's rate; unrealized P&L includes FX gain/loss (FX-03) | ✓ VERIFIED | `backend/portfolio.py:93-131` `recompute_holding_from_events` converts at `ev.date` via `fx.get_rate`; `portfolio_summary` uses `today` for current value |
| 7 | A cash holding values as quantity × fx_rate(currency,'IDR',today) with NO price_cache read (CG-01) | ✓ VERIFIED | `backend/portfolio.py:214-226` explicit `if h.asset_type == "cash":` branch before `_latest_price` call, entirely skips price_cache |
| 8 | A cash holding produces a portfolio_value_history row via snapshot_all_holdings, not skipped (CG-01, feeds VZ-02) | ✓ VERIFIED | `backend/portfolio.py:354-375` cash branch precedes the `price_row is None -> skip` gate, writes the row and `continue`s before reaching the skip path |
| 9 | A cash holding's per-row summary has non-null current_value and is_stale=false, price_source='fx' (INV-05) | ✓ VERIFIED | `backend/portfolio.py:219-226` sets `current_value`, `is_stale = rate is None`, `price_source = "fx"` explicitly, bypassing `_price_is_stale(None, 'cash')` |
| 10 | A gold holding gets full average-cost ledger P&L identical to crypto/stock (CG-02) | ✓ VERIFIED | No gold-specific branch exists anywhere in `recompute_holding_from_events`/`portfolio_summary` — confirmed by absence; gold rides the unmodified path |
| 11 | A currency-mismatched buy/sell event raises ValueError → 422 | ✓ VERIFIED | `backend/writes.py:241-251` `apply_add_portfolio_event` compares `event_currency` vs `existing_holding.currency`, raises `ValueError`; `backend/main.py` maps ValueError→422 at both the direct endpoint and (post-fix) the proposal-confirm path |
| 12 | portfolio_summary groups holdings by asset_type in addition to platform (VZ-01 contract) | ✓ VERIFIED | `backend/portfolio.py:297-304` `asset_type_groups` built and returned; `backend/schemas.py:208` `PortfolioSummary.asset_type_groups` field present |
| 13 | A failed FX lookup propagates None — never a fabricated rate=1.0 | ✓ VERIFIED | `backend/portfolio.py:96-104` (recompute), `:479-481` (`_realized_for_position`, CR-01 fix), `:220`/`:359-362` (cash paths) — all propagate `None` on `rate is None`, no fallback constant |
| 14 | The allocation pie renders current IDR market value per group, toggling asset-type/platform | ✓ VERIFIED (code); visual rendering → human | `ui/app/investments/AllocationPieChart.tsx` pure renderer of `{label,value}[]`; `page.tsx:175-181` derives `allocationData` from `summary.asset_type_groups` or `activeGroups` per `allocationGroupBy` state |
| 15 | The pie reads /investments/summary groupings — no new backend endpoint | ✓ VERIFIED | `page.tsx` has no new fetch call for the pie; reuses the existing summary fetch result |
| 16 | The chart wrapper has explicit resolvable height (Recharts pitfall) | ✓ VERIFIED | `AllocationPieChart.tsx:41` `<div style={{width:"100%",height:280}}>` |
| 17 | GET /investments/history returns a daily time series (market value + P&L) from portfolio_value_history | ✓ VERIFIED | `backend/portfolio.py:404-439` `value_history_series`; `backend/main.py:455-468` route wired, returns `{points}` |
| 18 | The endpoint accepts a time-range parameter and filters accordingly | ✓ VERIFIED | `backend/portfolio.py:401,418-428` `_HISTORY_RANGES` dict (1M/3M/6M/All), invalid token raises ValueError→422 |
| 19 | The endpoint is an open read (no require_api_key) | ✓ VERIFIED | `backend/main.py:455` no `Depends(require_api_key)` on the route decorator; grep of all `require_api_key` routes confirms `/investments/history` absent |
| 20 | The line chart renders a value curve and P&L curve with a range selector (VZ-02) | ✓ VERIFIED (code); visual rendering → human | `ui/app/investments/ValueHistoryChart.tsx` renders both `total_market_value`/`total_pnl` Lines (mutually exclusive by `view` toggle) + 1M/3M/6M/All pills |
| 21 | find_platforms/find_accounts return rows with ids for name→id resolution | ✓ VERIFIED | `backend/tools.py:456-490` both functions return id-bearing rows; registered in `TOOLS` dict (`:506-507`) |
| 22 | propose_add_holding accepts platform_id; _execute_proposal_payload delegates to writes.py (CH-01 two-site fix) | ✓ VERIFIED | `backend/tools.py:845-877` `platform_id` param included in `after`; `backend/main.py:783-787` delegates to `apply_add_holding`/`apply_edit_holding`, no inline `Holding(...)` construction remains |

**Score:** 22/22 truths verified (0 present-but-behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/fx.py` | FX_ADAPTERS registry + get_rate() + fetch_frankfurter_rate() | ✓ VERIFIED | All present, matches spec exactly, `db.flush()` CR-02 fix confirmed |
| `backend/models.py::FxRateCache` | Immutable cache model | ✓ VERIFIED | `UniqueConstraint uq_fx_rate_cache_date_pair`, `Numeric(18,6)` rate |
| `backend/models.py::PortfolioEvent.currency` | Per-event currency column | ✓ VERIFIED | `String(8)`, `server_default='IDR'`, nullable |
| `alembic/versions/008_fx_rate_cache.py` | Reversible migration | ✓ VERIFIED | `upgrade()`/`downgrade()` present, exact inverse order; `alembic current` confirms head is `d3e4f5a6b7c8` on the live dev DB |
| `backend/tests/test_fx.py` | Mocked-httpx adapter + immutability tests | ✓ VERIFIED | 11 tests, independently re-run, all pass |
| `backend/portfolio.py` | FX-aware valuation, cash/gold special-cases, asset_type grouping | ✓ VERIFIED | All must-have logic present and correctly ordered (cash branch before price_cache reads) |
| `backend/writes.py` | Event-currency validation | ✓ VERIFIED | `apply_add_portfolio_event` validates and raises `ValueError` |
| `backend/schemas.py` | asset_type_groups field, PortfolioEventCreate.currency, corrected price docstring | ✓ VERIFIED | All three present |
| `ui/app/investments/AllocationPieChart.tsx` | Recharts pie clone | ✓ VERIFIED | Pure renderer, height-280 wrapper, empty state |
| `ui/app/investments/page.tsx` | Wires pie + toggle | ✓ VERIFIED | `AllocationPieChart` imported/rendered; existing holdings table untouched |
| `backend/portfolio.py::value_history_series` | Pure read-only calculator | ✓ VERIFIED | No `fx.get_rate` call, aggregates all rows unconditionally (cash included) |
| `backend/main.py::investments_history` | Open-read GET route | ✓ VERIFIED | No `require_api_key`; `ValueError`→422 |
| `backend/schemas.py::ValueHistoryResponse/PointOut` | Response models | ✓ VERIFIED | Present, `*Out`/`*Response` naming convention followed |
| `ui/app/investments/ValueHistoryChart.tsx` | Recharts LineChart clone | ✓ VERIFIED | Value/P&L toggle, range pills, height-280 wrapper, sparse-history empty state |
| `backend/tools.py` | find_platforms, find_accounts, propose_add_holding(platform_id) | ✓ VERIFIED | All three present, registered, tested |
| `backend/main.py::_execute_proposal_payload` | Delegates add_holding/edit_holding | ✓ VERIFIED | Inline `Holding(...)` construction fully removed; calls `apply_add_holding`/`apply_edit_holding` |
| `backend/tests/test_proposals.py` | CH-01 regression-closure integration test | ✓ VERIFIED | `test_confirm_add_holding_persists_platform_id` present and passing against a real DB session |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `fx.get_rate` | `fx_rate_cache` table | cache-first read, INSERT-only on miss | ✓ WIRED | Confirmed read-then-write ordering; `db.flush()` makes same-request re-reads visible (CR-02) |
| `recompute_holding_from_events` | `fx.get_rate` | conversion at trade-date, both total_cost mutation sites | ✓ WIRED | Lines 93-122; D-02 invariant preserved (avg_cost unchanged by sell — verified by inspecting the sell branch: only `total_cost`/`qty` mutate) |
| `portfolio_summary` | cash special-case | branch before `_latest_price` read | ✓ WIRED | Both aggregate total and per-row dict correctly special-cased |
| `snapshot_all_holdings` | cash special-case | branch before `price_row is None` skip gate | ✓ WIRED | Cash writes a row and `continue`s before reaching the generic skip path |
| `AllocationPieChart` | `/investments/summary` payload | `asset_type_groups` / `activeGroups` via page.tsx state | ✓ WIRED | No new fetch introduced; toggle switches source array |
| `ValueHistoryChart` | `GET /investments/history` | `loadHistory` useCallback, independent fetch | ✓ WIRED | `page.tsx:125-138` |
| `propose_add_holding` → `_execute_proposal_payload` | `apply_add_holding` | delegation, not inline construction | ✓ WIRED | `platform_id` flows proposal → confirm → DB write; proven by a real-DB integration test that passed independently |
| `find_platforms`/`find_accounts` | `TOOLS` registry | dict registration | ✓ WIRED | Both present as dict entries, confirmed via grep |

### Behavioral Spot-Checks / Test Execution (independently re-run, not trusted from SUMMARY)

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| FX + portfolio + write-tools + chat-tools + proposals test files | `pytest backend/tests/{test_fx,test_portfolio,test_write_tools,test_tools,test_proposals}.py -q` | 98 passed | ✓ PASS |
| Full backend suite (regression gate) | `pytest backend/tests/ -q` | 185 passed, 1 failed (`test_settings.py::test_put_settings_requires_key`) | ✓ PASS (matches claimed 185/1, confirmed unrelated to this phase — file not in any phase-07 `files_modified`, env-dependent `MONAI_API_KEY`) |
| UI typecheck | `cd ui && npx tsc --noEmit` | clean, no output | ✓ PASS |
| Migration head on live dev DB | `alembic current` | `d3e4f5a6b7c8 (head)` | ✓ PASS — migration 008 is actually applied, not just AST-valid |
| `autoflush=False` claim underpinning CR-02 | `grep autoflush backend/db.py` | `autoflush=False` confirmed | ✓ PASS |
| CH-01 regression test exercises a real DB session | Read `test_confirm_add_holding_persists_platform_id` | Uses `client`/`api_key`/`db_session` fixtures (integration, not unit-mocked) | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| INV-01 | 07-02 | Add/edit/remove holdings incl. currency | ✓ SATISFIED | Currency-aware write path, event validation |
| INV-02 | 07-01 (foundation) | Fetch current crypto prices | ✓ SATISFIED | Pre-existing Phase 5 capability, untouched and still passing |
| INV-03 | 07-01 (foundation) | Fetch IDX stock prices | ✓ SATISFIED | Pre-existing, untouched |
| INV-04 | 07-02 (CG-03 path) | Manual price override | ✓ SATISFIED | `/prices/override` unchanged, reused by gold |
| INV-05 | 07-02 | Staleness indicator, incl. cash's non-false-stale badge | ✓ SATISFIED | `is_stale`/`price_source` correctly set for cash |
| INV-06 | 07-02/03/04 | Portfolio value + per-holding P&L view | ✓ SATISFIED | Summary + pie + history chart all present |
| INV-07 | 07-02/05 | Buy/sell events recorded, enabling correlation | ✓ SATISFIED | Event ledger + currency validation intact |
| CHAT-03 | 07-05 | Spending↔portfolio correlation via chat | ✓ SATISFIED | CH-01 fix keeps the chat write path functional; correlation tool itself untouched (pre-existing) |
| INVX-01 | 07-04 | Historical portfolio value over time | ✓ SATISFIED | `GET /investments/history` + `value_history_series` + chart |

**Note on REQUIREMENTS.md inconsistency (non-blocking):** The traceability table at the bottom of `.planning/REQUIREMENTS.md` (lines ~121-129) lists INV-01 through INV-06 as `Phase 5: Investment Subsystem | In Progress` — a stale leftover from before this work was split into Phase 7. The top-of-file v1 checklist correctly shows all 9 requirement IDs for this phase checked `[x]` and the phase-specific table (line 129) correctly shows `INVX-01 | Phase 7 | Complete`. This is a documentation-only staleness issue in REQUIREMENTS.md's bottom table, not a code gap — all 9 IDs are traced to verified source above. Recommend updating that table's Phase 5 rows to point at Phase 7 (or splitting them) during the next `/gsd-docs-update` pass, but it does not block this phase.

### Anti-Patterns Found

None. No `TBD`/`FIXME`/`XXX`/`TODO`/`HACK`/`PLACEHOLDER` markers found in any of the 12 files reviewed in 07-REVIEW.md plus the files re-inspected in this verification. No stub returns, no hardcoded empty arrays feeding rendered UI, no console.log-only handlers.

### Deferred Items (informational, not gaps)

| Item | Status | Evidence |
|------|--------|----------|
| WR-03 — `PortfolioEvent.price`/`Holding.avg_cost` remain `Numeric(18,2)`, truncating sub-cent native-currency prices | Deferred (per task instructions, schema-migration design decision) | Confirmed still `Numeric(18, 2)` in `backend/models.py:164,194`. Does not fail any must-have truth in this phase's plans — no must-have specifies sub-cent precision. Affects an edge case (e.g. `$0.0035` stablecoin/penny-stock prices) not currently in the user's portfolio per the phase's dogfooding origin. Flagged for awareness, correctly out of this phase's scope per the review's own disposition. |
| `test_settings.py::test_put_settings_requires_key` | Pre-existing, unrelated | Confirmed via independent full-suite run; file not in any 07-0X-PLAN.md `files_modified` list; fails only when `MONAI_API_KEY` env var is unset in the test shell |

## Human Verification Required

3 items need human/visual testing (see frontmatter `human_verification` for full detail):

1. **Allocation pie chart (VZ-01)** — visual rendering + asset-type/platform toggle on `/investments`
2. **Value-history line chart (VZ-02)** — visual rendering + Value/P&L toggle + range selector on `/investments`
3. **Chat multi-platform add/delete** — live conversational session exercising the LLM's actual tool-selection behavior (does it call `find_platforms` and ask when ambiguous, per CH-01's design) — the regression-closure test proves the confirm-time write path is fixed, but not the live agent's tool-calling decisions

All code-level truths (22/22), artifacts, and key links are verified. Nothing failed. The phase is gated on human visual/UX confirmation only, not on any known code gap.

## Gaps Summary

No gaps. All must-haves across all 5 plans verified against actual source (not SUMMARY claims), all review findings independently confirmed fixed and covered by real regression tests, full backend test suite independently re-run and matches the claimed 185/1 (pre-existing unrelated failure), UI typecheck independently re-run and clean, and the live dev DB confirmed at migration head. The only open items are three human-only visual/UX checks that cannot be verified by static analysis.

---

_Verified: 2026-07-12T16:17:02Z_
_Verifier: Claude (gsd-verifier)_
