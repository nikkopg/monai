# Roadmap: monai

**Project:** Self-hosted agentic personal-finance app (cashflow + investments + MCP server)

## Milestones

- ✅ **v1.0 — Agentic Chat + Investments + Multi-page UI + MCP** — Phases 1-7, 30 plans (shipped 2026-07-17). See [milestones/v1.0-ROADMAP.md](milestones/v1.0-ROADMAP.md).
- 🚧 **v1.1 — UI Redesign — "Paper" Aesthetic** — Phases 8-10 (in progress).

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

### 🚧 v1.1 — UI Redesign — "Paper" Aesthetic (In Progress)

**Milestone Goal:** Re-skin all four pages + the nav shell to the Claude Design "paper" mockup (`.planning/design/monai-redesign.dc.html`) — a warm editorial look — without changing any behavior, data, or endpoints.

- [x] **Phase 8: Design Foundation + App Shell** - Token layer, fonts, and the restyled sidebar/nav shell that every page depends on — completed 2026-07-18
- [ ] **Phase 9: Cashflow + Chat Restyle** - The two primary-workflow pages restyled to the mockup, bound to real data
- [ ] **Phase 10: Investments + Settings + Consistency Sweep** - Remaining pages, secondary surfaces (modals/managers/charts), responsive adaptation, and full regression pass

## Phase Details

### Phase 8: Design Foundation + App Shell
**Goal**: A single source-of-truth design-token layer exists and the app shell (sidebar nav + page chrome) matches the mockup, so every subsequent page restyle has tokens and a shell to build on.
**Depends on**: Phase 7 (v1.0 shipped baseline)
**Requirements**: UIR-01, UIR-02, UIR-03
**Success Criteria** (what must be TRUE):
  1. `ui/app/styles.ts` exports the full token set (palette incl. `#ece8e1`/`#f7f5f1`/`#f2efe8`/`#23201b`/`#2f6f4f`/`#b5503f`, type families, radii, spacing) and is the only place these values are hard-coded — no page has an inline hex/px literal duplicating a token.
  2. Instrument Serif renders on headings/wordmark/hero figures and Hanken Grotesk renders on body/controls across all four pages (fonts visibly loaded, not falling back to system serif/sans).
  3. The left sidebar shows the serif "monai" wordmark, uppercase "Menu" label, icon+label nav items with a dark active pill on the current page and inactive styling on the others, and a "synced" status footer card — matching the mockup on all four routes.
  4. The page background is cream with a centered rounded panel matching the mockup's shell geometry (radii, hairline borders, shadow) on every page.
  5. All existing Playwright e2e specs still pass (shell restyle causes no navigation/routing regressions).
**Plans**: TBD
**UI hint**: yes

### Phase 9: Cashflow + Chat Restyle
**Goal**: The Cashflow and Chat pages — the two highest-traffic workflows — visually match the mockup while remaining bound to real IDR data and the live chat/proposal flow.
**Depends on**: Phase 8
**Requirements**: UIR-04, UIR-05
**Success Criteria** (what must be TRUE):
  1. Cashflow renders a dark `#23201b` net-worth hero card with a serif tabular-figure total and a green/terracotta delta pill, sourced from the real net total (not mockup's fake numbers).
  2. Cashflow shows a period segmented control, 6-month income/expense trend, three stat cards (income/expenses/net), a spending-by-category donut + legend, an accounts list, and a recent-transactions list, all bound to live endpoints — matching the mockup's layout and styling.
  3. Chat shows right-aligned user bubbles, an assistant answer block with the monai wordmark, and a collapsible "how I got this" tool-trace, all driven by real chat responses.
  4. Chat's confirm-before-write proposal card (approve/reject) and sticky composer render per the mockup and still complete a real propose→confirm round-trip.
  5. All existing Playwright e2e specs covering cashflow and chat flows still pass.
**Plans**: TBD
**UI hint**: yes

### Phase 10: Investments + Settings + Consistency Sweep
**Goal**: The remaining two pages match the mockup, every secondary UI surface not shown in the mockup adopts the new tokens, the layout adapts to real browser viewports, and the full v1.0 behavior surface is regression-free.
**Depends on**: Phase 8 (tokens/shell); benefits from Phase 9 patterns (donut/hero/table styling reuse)
**Requirements**: UIR-06, UIR-07, UIR-08, UIR-09, UIR-10
**Success Criteria** (what must be TRUE):
  1. Investments renders a dark total-value hero with an all-time delta, an allocation donut + legend, and a holdings table (asset badge / units / price / value / return) — matching the mockup, bound to real holdings.
  2. Settings renders a provider segmented control, model input, API-key cards, preferences (base currency, price source), and a live-refresh toggle with save actions — matching the mockup, bound to real settings endpoints.
  3. Secondary surfaces absent from the mockup (CRUD modals, CSV upload dialog, account/platform/category managers, holding-override dialog, staleness badges, all charts) visually use the new tokens (no leftover old-theme colors/fonts) while their exact behavior is unchanged.
  4. At a narrow viewport the layout reflows usably (no clipping/horizontal overflow of the fixed 1240×820 mockup geometry) and internal panels scroll where content exceeds the frame.
  5. Every v1.0 flow (transaction/account/category CRUD, CSV import, holdings CRUD + price overrides, provider/key/preferences save, agent confirm-before-write) works identically post-restyle, and the full existing Playwright e2e suite passes with zero regressions.
**Plans**: TBD
**UI hint**: yes

## Backlog

Deferred to v2 (see next milestone's requirements):

- QRY-01: Recurring-charge / subscription detection
- QRY-02: Compare two arbitrary periods side by side
- QRY-03: Token-by-token streaming of agent responses
- INVX-02: Automated reksadana NAV feed

## Progress

**Execution Order:**
Phases execute in numeric order: 8 → 9 → 10

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|-----------------|--------|-----------|
| 1. Schema Foundation + Auth | v1.0 | 3/3 | Complete | 2026-06-21 |
| 2. Agentic Loop + Confirm-Before-Write | v1.0 | 3/3 | Complete | 2026-07-16 |
| 3. Multi-Page UI Shell + Settings | v1.0 | 3/3 | Complete | 2026-07-04 |
| 4. Cashflow Dashboard + CRUD | v1.0 | 7/7 | Complete | 2026-07-06 |
| 5. Investment Subsystem | v1.0 | 6/6 | Complete | 2026-07-11 |
| 6. MCP Server | v1.0 | 2/2 | Complete | 2026-07-15 |
| 7. Investment Subsystem v2 | v1.0 | 5/5 | Complete | 2026-07-13 |
| 8. Design Foundation + App Shell | v1.1 | 0/TBD | Not started | - |
| 9. Cashflow + Chat Restyle | v1.1 | 0/TBD | Not started | - |
| 10. Investments + Settings + Consistency Sweep | v1.1 | 0/TBD | Not started | - |

---
*Roadmap created: 2026-06-21 · v1.0 archived 2026-07-17 · v1.1 phases added 2026-07-18*
