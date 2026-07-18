---
phase: 9
name: Cashflow + Chat Restyle
requirements: [UIR-04, UIR-05]
wave: 1
depends_on: [8]
autonomous: true
files_modified:
  - ui/app/cashflow/page.tsx
  - ui/app/cashflow/charts/CategoryDonut.tsx
  - ui/app/cashflow/charts/TrendChart.tsx
  - ui/app/chat/page.tsx
  - ui/e2e/smoke.spec.ts
  - ui/e2e/cashflow-dashboard.spec.ts
  - ui/e2e/cashflow-crud.spec.ts
---

# Phase 9 — Cashflow + Chat Restyle

**Goal:** The two highest-traffic pages match the mockup while staying bound to
real IDR data and the live chat/proposal flow. Uses the Phase 8 tokens/shell.

## Tasks

### T1 — Cashflow page (UIR-04)
Rewrite `ui/app/cashflow/page.tsx` to the mockup layout, preserving all data
wiring (`/api/cashflow/summary`, `/api/transactions?limit=10`) and CRUD
(TransactionModal, ConfirmDialog, AccountManager, CategoryManager, CsvUpload,
refreshAll):
- "Overview" eyebrow + serif "Cashflow" h1 + period segmented control (Week/
  Month/Last/Year → this_week/this_month/last_month/this_year).
- Dark net-worth hero (Σ account current_balance) + delta pill (Σ period_net).
- 6-month trend card (legend + TrendChart).
- Three stat cards: Income / Expenses / Net saved (from totals).
- Spending-by-category donut + legend; accounts list (badge initials, balance,
  delta). Recent transactions (tinted icon, merchant/category·date, signed
  amount) with "+ Add transaction" and subtle Edit/Delete actions.
- read_first: cashflow/page.tsx, styles.ts, charts/*
- acceptance: real net-worth/income/expense figures render (not mockup fakes);
  period pill click refetches; CRUD still works.

### T2 — Charts (UIR-04)
- `TrendChart.tsx`: BarChart → LineChart, income solid green / expenses dashed
  terracotta (mockup), paper axes/tooltip.
- `CategoryDonut.tsx`: compact paper ring (paper palette, paper tooltip).
- Drop the income-vs-expense bar from the page (mockup replaces it with hero +
  stat cards). `IncomeExpenseBar.tsx` left in tree (unused; removable later).

### T3 — Chat page (UIR-05)
Rewrite `ui/app/chat/page.tsx` to the mockup, preserving the SSE `ask()`
(/api/query-stream), tool-trace, and ProposalCard confirm/reject endpoints:
- "Assistant" eyebrow + serif "Ask about your money" h1.
- Right-aligned user bubble (askedQuestion), assistant block (serif "monai"
  wordmark + status), streamed steps, answer paragraph, collapsible
  "how I got this" trace.
- ProposalCard re-skinned: green-accented card, Approve (green) / Reject (ghost),
  "expires in N min" — same propose→confirm→reject wiring.
- Sticky composer (input + dark Ask button); composer clears on send.
- read_first: chat/page.tsx, styles.ts
- acceptance: bubble + answer render from a real /api/query-stream response;
  proposal approve/reject still hit their endpoints.

### T4 — e2e alignment (UIR-09 partial)
Update specs for the intentional copy/indicator changes: smoke /chat + /cashflow
headings, dashboard captions (Income/Expenses/Net saved, "Spending by category",
"Year" pill), crud "+ Add transaction" trigger (modal submit stays "Add
transaction"). Keep every behavioral assertion.

## must_haves
- Cashflow + Chat visually match the mockup, bound to real data/flow (UIR-04/05).
- No functional regressions; full e2e suite green.

## Verification
- `npx tsc --noEmit` clean.
- `npx playwright test` — 27/27 pass.
- Preview: cashflow renders real IDR net-worth/stat figures + donut/trend/accounts;
  chat renders bubble + answer + composer.
