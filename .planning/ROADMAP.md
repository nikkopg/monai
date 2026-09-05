# Roadmap: monai

**Project:** Self-hosted agentic personal-finance app (cashflow + investments + MCP server)

## Milestones

- ✅ **v1.0 — Agentic Chat + Investments + Multi-page UI + MCP** — Phases 1-7, 30 plans (shipped 2026-07-17). See [milestones/v1.0-ROADMAP.md](milestones/v1.0-ROADMAP.md).
- ✅ **v1.1 — UI Redesign ("Paper" Aesthetic)** — Phases 8-10, 3 plans (shipped 2026-07-18). See [milestones/v1.1-ROADMAP.md](milestones/v1.1-ROADMAP.md).
- ✅ **v1.2 — Connected Ledger — Liquids ↔ Investments** — Phases 11-18, 31 plans (shipped 2026-09-05). See [milestones/v1.2-ROADMAP.md](milestones/v1.2-ROADMAP.md).

## Phases

<details>
<summary>✅ v1.0 (Phases 1-7) — SHIPPED 2026-07-17</summary>

- [x] Phase 1: Schema Foundation + Auth (3/3 plans) — completed 2026-06-21
- [x] Phase 2: Agentic Loop + Confirm-Before-Write (3/3 plans) — completed 2026-07-16
- [x] Phase 3: Multi-Page UI Shell + Settings (3/3 plans) — completed 2026-07-04
- [x] Phase 4: Cashflow Dashboard + CRUD (7/7 plans) — completed 2026-07-06
- [x] Phase 5: Investment Subsystem (6/6 plans) — completed 2026-07-11
- [x] Phase 6: MCP Server (2/2 plans) — completed 2026-07-15
- [x] Phase 7: Investment Subsystem v2 — multi-platform, multi-currency, cash, gold, viz (5/5 plans) — completed 2026-07-13

Full phase detail: [milestones/v1.0-ROADMAP.md](milestones/v1.0-ROADMAP.md)

</details>

<details>
<summary>✅ v1.1 UI Redesign — "Paper" Aesthetic (Phases 8-10) — SHIPPED 2026-07-18</summary>

- [x] Phase 8: Design Foundation + App Shell (1/1 plan) — completed 2026-07-18
- [x] Phase 9: Cashflow + Chat Restyle (1/1 plan) — completed 2026-07-18
- [x] Phase 10: Investments + Settings + Consistency Sweep (1/1 plan) — completed 2026-07-18

Full phase detail: [milestones/v1.1-ROADMAP.md](milestones/v1.1-ROADMAP.md)

</details>

<details>
<summary>✅ v1.2 Connected Ledger — Liquids ↔ Investments (Phases 11-18) — SHIPPED 2026-09-05</summary>

- [x] Phase 11: Category Hierarchy — Schema, Audit, Migration (7/7 plans) — completed 2026-07-20
- [x] Phase 12: Typed Accounts + Transfer/Funding Schema Foundations (3/3 plans) — completed 2026-07-25
- [x] Phase 13: Shared Mutation Layer — Transfer, Buy/Sell-with-Funding, Adjustment Writes (5/5 plans) — completed 2026-07-30
- [x] Phase 14: REST Endpoints + Agent/MCP Tool Registration (3/3 plans) — completed 2026-07-31
- [x] Phase 15: Net Worth Aggregation + Dashboard (2/2 plans) — completed 2026-07-31
- [x] Phase 16: UI — Extend Existing Components (3/3 plans) — completed 2026-08-01
- [x] Phase 17: UI — New Surfaces (Records Tab, Categories Manager) (5/5 plans) — completed 2026-08-02
- [x] Phase 18: UI entry points for balance adjustment, liquid→investment transfer, and funded buy/sell (3/3 plans) — completed 2026-08-17 (close-out 2026-09-04)

Full phase detail: [milestones/v1.2-ROADMAP.md](milestones/v1.2-ROADMAP.md)

</details>

## Backlog

Deferred to next milestone (see `.planning/REQUIREMENTS.md` and `.planning/PROJECT.md` Next Milestone Goals):

- QRY-01: Recurring-charge / subscription detection
- QRY-02: Compare two arbitrary periods side by side
- QRY-03: Token-by-token streaming of agent responses
- INVX-02: Automated reksadana NAV feed
- REC-F1: Labels on records (free-form multi-tags separate from categories)
- CAT-F1: Nature-of-Spending (Need/Want) classification per category
- CAT-F2: Hide toggle for categories
- Net-worth-over-time reconstruction from the original Wallet export (see PROJECT.md Next Milestone Goals)

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|-----------------|--------|-----------|
| 1. Schema Foundation + Auth | v1.0 | 3/3 | Complete | 2026-06-21 |
| 2. Agentic Loop + Confirm-Before-Write | v1.0 | 3/3 | Complete | 2026-07-16 |
| 3. Multi-Page UI Shell + Settings | v1.0 | 3/3 | Complete | 2026-07-04 |
| 4. Cashflow Dashboard + CRUD | v1.0 | 7/7 | Complete | 2026-07-06 |
| 5. Investment Subsystem | v1.0 | 6/6 | Complete | 2026-07-11 |
| 6. MCP Server | v1.0 | 2/2 | Complete | 2026-07-15 |
| 7. Investment Subsystem v2 | v1.0 | 5/5 | Complete | 2026-07-13 |
| 8. Design Foundation + App Shell | v1.1 | 1/1 | Complete | 2026-07-18 |
| 9. Cashflow + Chat Restyle | v1.1 | 1/1 | Complete | 2026-07-18 |
| 10. Investments + Settings + Consistency Sweep | v1.1 | 1/1 | Complete | 2026-07-18 |
| 11. Category Hierarchy | v1.2 | 7/7 | Complete | 2026-07-20 |
| 12. Typed Accounts + Transfer Schema | v1.2 | 3/3 | Complete | 2026-07-25 |
| 13. Shared Mutation Layer | v1.2 | 5/5 | Complete | 2026-07-30 |
| 14. REST + Agent/MCP Tools | v1.2 | 3/3 | Complete | 2026-07-31 |
| 15. Net Worth Dashboard | v1.2 | 2/2 | Complete | 2026-07-31 |
| 16. UI — Extend Existing | v1.2 | 3/3 | Complete | 2026-08-01 |
| 17. UI — New Surfaces | v1.2 | 5/5 | Complete | 2026-08-02 |
| 18. UI Entry Points (balance adjust, transfer, funded buy/sell) | v1.2 | 3/3 | Complete | 2026-08-17 |

---
*Roadmap created: 2026-06-21 · v1.0 archived 2026-07-17 · v1.1 archived 2026-07-18 · v1.2 archived 2026-09-05*
