---
gsd_state_version: 1.0
milestone: v1.2
milestone_name: Connected Ledger — Liquids ↔ Investments
current_phase: 13
current_phase_name: shared-mutation-layer-transfer-buy-sell-with-funding-adjustm
status: executing
stopped_at: Completed 13-02-PLAN.md
last_updated: "2026-07-30T06:27:07.503Z"
last_activity: 2026-07-30
last_activity_desc: Phase 13 execution started
progress:
  total_phases: 7
  completed_phases: 2
  total_plans: 15
  completed_plans: 12
  percent: 29
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-07-18)

**Core value:** You can understand and manage your entire financial life — spending and investments — by talking to a trustworthy AI that never fabricates a number and never changes your data without your say-so.
**Current focus:** Phase 13 — shared-mutation-layer-transfer-buy-sell-with-funding-adjustm

## Current Position

Phase: 13 (shared-mutation-layer-transfer-buy-sell-with-funding-adjustm) — EXECUTING
Plan: 3 of 5
Status: Ready to execute
Last activity: 2026-07-30 -- Phase 13 execution started

Progress: [░░░░░░░░░░] 0%

## Performance Metrics

**Velocity:**

- Total plans completed (v1.0): 30
- Average duration: —
- Total execution time: —

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 1-7 (v1.0) | 30 | — | — |
| 8-10 (v1.1) | 3 | — | — |
| 11-17 (v1.2) | 0 | — | — |
| 11 | 7 | - | - |
| 12 | 3 | - | - |

**Recent Trend:**

- Last 5 plans: — (v1.1 closed 2026-07-18)
- Trend: —

*Updated after each plan completion*
| Phase 12 P01 | 20min | 2 tasks | 2 files |
| Phase 12 P02 | 35min | 2 tasks | 6 files |
| Phase 12 P03 | 20min | 1 tasks | 1 files |
| Phase 13 P01 | 45min | 2 tasks | 2 files |
| Phase 13 P02 | 25min | 2 tasks | 2 files |

## Accumulated Context

### Roadmap Evolution

- v1.2 roadmap created (2026-07-18): 7 phases (11-17), schema-first + dependency-ordered per research/SUMMARY.md. Categories (11) before typed accounts (12) — both audited against live data, categories first as the higher data-quality risk. Shared mutation layer (13) before REST/agent/MCP registration (14) — enforces atomicity by construction and treats dual/triple tool registration as one auditable checklist (prior incidents: `chat-tool-dual-registration`, `TOOLS registry mutates to 26`). Net worth dashboard (15) sequenced after typed-accounts reconciliation (12) and funding writes (13) so it's never built on unstable data. UI split into "extend existing" (16) vs "new surfaces" (17) — the former needs the stable API contract, the latter is purely additive.
- v1.1 roadmap created (2026-07-18): 3 phases (8, 9, 10), foundation-first — tokens/shell (8) block both page phases (9, 10). Cashflow+Chat grouped in Phase 9 (primary workflows); Investments+Settings+secondary-surface consistency+regression sweep grouped in Phase 10.

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [v1.2 pre-roadmap]: Liquid↔liquid transfers pair via `transactions.transfer_pair_id` (Transaction↔Transaction); liquid→investment transfers pair via `portfolio_events.source_account_id` (Transaction↔PortfolioEvent) — investment money must never become a synthetic `accounts` row, or the double-count bug returns by construction
- [v1.2 pre-roadmap]: `accounts.type` promoted from decorative to a DB-enforced discriminator only after manual audit of all 4 live (currently NULL) accounts — no auto-inference
- [v1.2 pre-roadmap]: 74 free-string categories migrate via a human-reviewed mapping, not an automatic one, with row/sum parity assertions baked into the migration
- [v1.1 pre-roadmap]: Visual-only re-skin — no backend/schema/API changes that milestone; `ui/app/styles.ts` remains the single token source (no CSS framework migration)
- [Phase ?]: Phase 12 Plan 01: both new test files query/introspect live Postgres directly (no mocking, no fresh-migrate fixture) — matches test_tools.py idiom
- [Phase ?]: Phase 12 Plan 01: test_type_check_and_default explicitly rolls back both probe inserts so the live accounts table is never mutated by the test suite
- [Phase ?]: Phase 12 Plan 01: test_double_count_delta derives the investment-expense magnitude live via SQL, never hard-codes the ~45.9M figure from RESEARCH.md
- [Phase ?]: Phase 12 Plan 02: migration 010 (f1a2b3c4d5e6, down_revision=e5f6a7b8c9d0) backfills ACCOUNT_TYPE={1:liquid,2:liquid,3:investment,559:liquid} per locked D-02 map, no auto-inference
- [Phase ?]: Phase 12 Plan 02: transfer_pair_id carries NO foreign key (plain indexed Integer) — pairing semantics deferred to Phase 13
- [Phase ?]: Phase 12 Plan 02: cashflow_transactions view created after pairing columns so SELECT t.* is the full superset; NOT EXISTS keyed on type='investment' keeps NULL-account_id rows
- [Phase 12]: Phase 12 Plan 03: switched 10 FROM-clause sites (spending_total, income_total, net_total, spending_by_category, spending_in_category, transaction_count, largest_transactions, average_daily_spending total, monthly_trend, find_transactions) from transactions to cashflow_transactions; account_balances, currency probe, date-span query, and delete-guard COUNTs left on the base table intentionally
- [Phase 12]: Plan 03: resolved a plan-drafting mislabel where the 10th switch site was described as 'spending_by_category's grand-total denominator' but actually belongs to spending_in_category (line number and SQL pattern were correct, function name was not) — switched spending_in_category since it is genuinely a cashflow total
- [Phase ?]: apply_add_transfer(db, leg_a_after, leg_b_after) takes two Transaction-shaped after dicts, one per leg (Phase 13 Plan 01)
- [Phase ?]: apply_add_balance_adjustment(db, account_id, target_balance) takes positional account_id + target_balance, not an after-dict (Phase 13 Plan 01)
- [Phase ?]: Balance-adjustment row tagged category='Adjustment' AND is_transfer=True — is_transfer is the only existing lever that excludes a row from cashflow totals (D-08, Phase 13 Plan 01)
- [Phase 13-02]: Retro-pair mutual count-guard: a candidate pair is only committed when BOTH sides individually have exactly one candidate match — prevents a half-pair when one side's sole candidate is itself ambiguous
- [Phase 13-02]: Migration 011's flagged marker is report-only (no new column) — a flagged row is is_transfer=true AND transfer_pair_id IS NULL, printed during upgrade()
- [Phase 13-02]: Migration 011 downgrade() is a documented no-op — no schema object owned by this revision; backfilled data left in place per 009/010 downgrade posture

### Pending Todos

None yet.

### Blockers/Concerns

- [Phase 11 planning]: 74-category mapping is a human-judgment task — must be done before migration DDL is written, not automated
- [Phase 12 planning]: Confirm exact Alembic nullable→backfill→constrain idiom before touching live `accounts.type` data (established pattern from migration 008, but needs a plan-time check)
- [Phase 13 planning]: FX precision handling on buy/sell-with-funding is subtle (BTC price_cache USD/IDR conflation class of bug); flagged for research pass
- test_settings.py::test_put_settings_requires_key fails 503 vs 401 — pre-existing, confirmed unrelated to Phase 12 Plan 02 via git-stash bisection, logged in deferred-items.md

### Quick Tasks Completed

See milestones/v1.0-* and v1.1-* archives and prior STATE.md history (git) for earlier quick-task logs.

| Date | Slug | Description |
|------|------|-------------|
| 2026-07-20 | recharts-pie-no-slices | Pie charts rendered zero `<path>`s — recharts 3.9 collapses sectors to a zero-width angle at animation t=0 and the rAF clock can leave them stuck there. Fixed with `isAnimationActive={false}` on both `<Pie>`s. |

## Deferred Items

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| v2 | QRY-01: recurring-charge detection | Acknowledged | v1.0 close |
| v2 | QRY-02: period comparison | Acknowledged | v1.0 close |
| v2 | QRY-03: streaming token-by-token | Acknowledged | v1.0 close |
| v2 | INVX-02: automated reksadana NAV | Acknowledged | v1.0 close |
| v2 | REC-F1: record labels/tags | Acknowledged | v1.2 requirements |
| v2 | CAT-F1: nature-of-spending (need/want) | Acknowledged | v1.2 requirements |
| v2 | CAT-F2: category hide toggle | Acknowledged | v1.2 requirements |
| debug | this-week-period-fails | diagnosed |
| quick_task | 260703-f5b-patch-flat-commands-manifest-resolution | missing |
| quick_task | 260703-fwr-fix-backend-dockerfile-copy-alembic-ini | missing |
| quick_task | 260703-gco-add-find-transactions-read-tool | missing |
| quick_task | 260703-grn-fix-agent-stream-to-use-tooloutput-raw | missing |
| quick_task | 260703-ja8-harden-monai-api-key-misconfiguration | missing |
| quick_task | 260711-k35-fix-log-event-modal-dropping-platform | missing |
| quick_task | 260711-l41-add-optional-per-holding-coingecko-id | missing |
| quick_task | 260711-rb2-multi-platform-holdings-same-asset | missing |
| uat_gap | phase 04 | diagnosed |
| uat_gap | phase 07 | resolved |

## Session Continuity

Last session: 2026-07-30T06:27:07.493Z
Stopped at: Completed 13-02-PLAN.md
Resume file: None

Next: `/gsd-plan-phase 11`
