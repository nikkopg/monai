# Phase 5 — Plan Check Verdict

**Checked:** 2026-07-10
**Plans:** 05-01 … 05-06 (6 plans)
**Verdict:** PASS (with 3 non-blocking warnings)

Goal-backward verification of the six Phase-5 plans against ROADMAP goal + 6 success
criteria, REQUIREMENTS (INV-01…07, CHAT-03), CONTEXT decisions D-01…D-17, RESEARCH
constraints, and VALIDATION Wave-0 scaffolds. Every phase success criterion and every
requirement traces to a concrete implementing task. No locked decision is contradicted.
No out-of-scope item is planned. No blockers.

---

## Check Results

| # | Check | Result |
|---|-------|--------|
| 1 | Goal coverage (6 success criteria) | PASS |
| 2 | Requirement coverage (INV-01…07, CHAT-03) | PASS |
| 3 | Decision fidelity (D-01…D-17) | PASS |
| 4 | Wave/dependency soundness | PASS |
| 5 | Anti-shallow compliance (read_first, acceptance, no code fences) | PASS |
| 6 | Security gate (threat model, SSRF, unauth writes) | PASS |
| 7 | Scope discipline (nothing out-of-scope planned) | PASS |

---

## Check 1 — Goal coverage (6 ROADMAP success criteria)

| SC | What must be TRUE | Owning task(s) |
|----|-------------------|----------------|
| 1 | Add/edit/delete holding (ticker, qty, avg cost, date, currency, asset type) | 05-03 T2 (holdings/events CRUD) + T3 (HoldingModal/HoldingOverrideModal) |
| 2 | Per-holding current price, value, P&L, P&L%, staleness badge + stale indicator | 05-03 T2/T3 (P&L summary) + 05-04 T2/T3 (staleness in summary + StalenessBadge) |
| 3 | Crypto→CoinGecko, IDX→yfinance w/ fallback, funds/unresolvable→manual | 05-04 T1 (PRICE_ADAPTERS routed by asset_type) |
| 4 | Manual price override reflected immediately in P&L | 05-04 T2 (POST /prices/override) + T3 (PriceOverrideDialog) |
| 5 | Total portfolio value + "as of" timestamp | 05-03 T2 (GET /investments/summary as_of) + T3 (banner) |
| 6 | Portfolio buy/sell events recorded → agent answers correlation question | 05-03 T2 (portfolio_events on write) + 05-05 T1 (spending_before_after_purchase) |

All six criteria owned. No orphan criterion.

## Check 2 — Requirement coverage

Every requirement appears in a plan `requirements:` frontmatter AND has a real
implementing task (not merely declared):

- INV-01 → 05-03 T2/T3 (event ledger + holdings CRUD + modals). (05-02 also declares
  INV-01 for platform grouping, the INV-01 "grouped by platform" facet.)
- INV-02 → 05-04 T1 `fetch_crypto_price`.
- INV-03 → 05-04 T1 `fetch_idx_price` w/ fallback contract.
- INV-04 → 05-04 T2 `apply_set_price` + `/prices/override`.
- INV-05 → 05-04 T1 `is_stale` + T2 (is_stale in summary) + T3 StalenessBadge.
- INV-06 → 05-03 T2 (portfolio_summary realized/unrealized/total/as_of).
- INV-07 → 05-03 T2 (portfolio_events row per write).
- CHAT-03 → 05-05 T1 (`spending_before_after_purchase`, registered in TOOLS).

Note: 05-01 frontmatter lists all seven INV-* IDs (it is the shared schema/test
substrate feeding every INV requirement) — acceptable, since each ID also has a real
implementing task in a downstream plan. Not a double-count risk.

## Check 3 — Decision fidelity (spot-check load-bearing)

- D-01/D-02 avg-cost NOT FIFO: 05-03 feature block + RESEARCH Pattern 2 — sell leaves
  avg_cost unchanged (total_cost reduced by avg_cost×qty); explicit tests for the
  invariant. FIFO absent everywhere. ✓
- D-03 override audit-logged: 05-03 T2 `apply_edit_holding`/`apply_delete_holding`
  entity="holding" audited; threat T-05-03-REP. ✓
- D-11 manual override replaced by next live fetch: 05-04 key_links + T2. ✓
- D-13/D-14 single daily APScheduler snapshot in lifespan: 05-06 T1/T2
  (AsyncIOScheduler, CronTrigger daily, misfire_grace_time=3600, coalesce,
  max_instances=1, get_session_sync reuse, no @app.on_event). ✓
- D-15 correlation is a READ tool: 05-05 (tools.py only, parameterized SQL,
  structured-dict, honest error on no-buy-event). ✓
- D-16 direct REST + writes.py + audit + Decimal (no propose/confirm on UI path): all
  write plans use Depends(require_api_key) + apply_* + AuditLog. ✓
- D-17 migration chains down_revision="9c1a4f7d2b8e": 05-01 T4 + key_link. ✓

No task contradicts any D-01…D-17.

## Check 4 — Wave/dependency soundness

- Migration (05-01, wave 1, depends []) precedes every table-writing slice. ✓
- Wave numbering = max(dep wave)+1 throughout; all depends_on point to earlier waves
  (05-02→01; 05-03→01,02; 05-04→03; 05-05→03; 05-06→03,04). No forward/cyclic refs. ✓
- Wave 4 parallel pair disjoint: 05-04 touches prices/portfolio/main/schemas/writes +
  3 UI files + 2 tests; 05-05 touches ONLY tools.py + test_tools.py. Zero file overlap.
  ✓ (See WARNING-1 on a serialization subtlety, non-blocking.)

## Check 5 — Anti-shallow compliance

- Every `<task>` (auto/tdd) carries `<read_first>` including the file being modified +
  its PATTERNS.md analog + RESEARCH section refs. ✓
- Every task has an automated `<verify>` and a measurable `<done>`/acceptance. ✓
- Zero triple-backtick fences inside any PLAN.md (grep: 0/0/0/0/0/0) — no code blocks
  smuggled into `<action>`. ✓
- Wave-0 scaffolds (test_portfolio.py, test_prices.py, test_scheduler.py) created as
  real red targets in 05-01 T5; downstream plans fill them (RED→GREEN visible). ✓

## Check 6 — Security gate

- Every plan has a `<threat_model>` with trust boundaries + STRIDE register. ✓
- SSRF via ticker (high): mitigated by fixed server-side `TICKER_TO_COINGECKO_ID` map
  (unknown→None) + IDX ticker validated against stored holdings — 05-04 T-05-04-SSRF +
  key_link. ✓
- Unauthenticated writes (high): every write route
  `dependencies=[Depends(require_api_key)]`; GET reads open — 05-02/03/04 access-control
  threats. ✓
- Input validation: event_type Literal["buy","sell","dividend"], positive-Decimal
  price/quantity at schema layer before recompute — 05-03 T-05-03-EVT. ✓
- Scheduler DoS: max_instances=1 + misfire_grace_time — 05-06 T-05-06-DOS. ✓
- Package legitimacy: 05-01 T1 blocking-human gate before first yfinance/apscheduler
  install. ✓

## Check 7 — Scope discipline

Out-of-scope items confirmed ABSENT from all plans:
- v2 historical line chart (INVX-01): only the data collector (05-06) ships; no chart
  UI planned. ✓
- reksadana NAV feed (INVX-02): manual price is the fallback; no NAV adapter. ✓
- FX / multi-currency: everything IDR, no conversion code. ✓
- FIFO lots: average-cost only. ✓
- MCP write exposure: nothing MCP in Phase 5 (Phase 6). ✓

---

## Warnings (non-blocking)

**WARNING-1 (dependency_correctness / info): Wave-4 parallelism is nominal, not real.**
05-04 and 05-05 are both wave 4 and file-disjoint, but 05-06 depends on BOTH 05-03 and
05-04 while 05-05 also depends on 05-03. Executing 04 and 05 truly in parallel is safe
(disjoint files), but note 05-05 shares no files with 05-04 yet both import from the
05-03 surface (tools.py `spending_in_category` custom-period contract vs
portfolio.py/prices.py). No collision — informational only. Fix: none required.

**WARNING-2 (research_resolution / warning): RESEARCH `## Open Questions` not marked
(RESOLVED).** RESEARCH.md line 740 `## Open Questions` lacks the `(RESOLVED)` suffix and
its two items carry no inline RESOLVED marker (Dimension 11). Impact is low: Q1
(yfinance `fast_info` key casing) is explicitly absorbed as a Wave-0 smoke test in
05-04 Task 0 with a documented RESEARCH-default fallback; Q2 (CoinGecko Demo key) has a
"ship-without" recommendation and touches no task. Both are handled in-plan, so this
does not block execution. Fix (optional): append `(RESOLVED)` and inline resolutions to
keep the artifact self-consistent.

**WARNING-3 (numeric/precision / warning): avg_cost stored at Numeric(18,2) may lose
sub-rupiah precision on fractional-crypto average cost.** RESEARCH flags that
`Holding.avg_cost`/`PriceCache.price` are Numeric(18,2) while quantity is Numeric(28,8).
For crypto with small per-unit IDR fractions this is acceptable per the IDR
"no minor unit" assumption, but the 05-03 recompute divides total_cost/qty into a
2-dp column — a rounding cliff exists. Plans reuse existing columns as-is (D-17), so
this is inherited, not introduced. Fix (optional / future): note the rounding boundary
in a test assertion tolerance so it is a conscious contract, not a surprise.

---

## Recommendation

PASS — proceed to `/gsd-execute-phase 5`. No blockers. The three warnings are quality
notes; none prevent the phase goal from being achieved. WARNING-2 (mark Open Questions
RESOLVED) is the only one worth a one-line artifact touch-up and can be done inline
during execution or ignored, since both questions are already handled in 05-04 Task 0.
