# Stack Research

**Domain:** v1.2 Connected Ledger — net-worth dashboard, Records tab, account/platform managers, liquid↔investment transfers, buy/sell atomic pairs, USD→IDR FX, 3-level category hierarchy
**Researched:** 2026-07-18
**Confidence:** HIGH

> SUBSEQUENT-milestone research. Question asked: "what stack additions are needed
> for the v1.2 features?" **Answer: none. Zero new dependencies.** Every v1.2
> feature is covered by the existing stack plus code patterns already in the repo.
> This file is therefore mostly a "what NOT to add" defense with pointers to the
> existing capability each feature reuses.

---

## Recommended Stack

### Core Technologies — unchanged

| Technology | Version (pinned/installed) | Purpose | v1.2 relevance |
|------------|---------------------------|---------|----------------|
| FastAPI | >=0.110.0 | API server | New endpoints (net worth, records, transfers, categories) follow existing route patterns in `backend/main.py` |
| SQLAlchemy + psycopg3 | >=2.0.0 / >=3.1.0 | ORM + driver | New `categories` table, transfer pairing, atomic buy/sell — all plain ORM + one transaction |
| Alembic | >=1.13.0 | Migrations | Migrations 009+ for categories table, `accounts.type` discriminator, transfer-pair columns. Migration 008 (`fx_rate_cache`) already shipped |
| Next.js (App Router) | 14.2.15 | Frontend | New pages/tabs are more of the same component pattern |
| React | 18.3.1 | UI | All new UI is standard controlled components |
| recharts | ^3.9.2 | Charts | PnL charts on platform detail = existing chart pattern (`TrendChart.tsx`, `AllocationPieChart.tsx`) |
| TypeScript | 5.6.3 | Types | — |
| httpx | >=0.27.0 | HTTP client | Already powers `backend/fx.py` frankfurter adapter |

**No version bumps required.** Next.js 15 is current stable (verified 2026-07-18) but upgrading is a re-platforming risk with zero v1.2 payoff — the "build on it, don't re-platform" constraint applies to major-version churn too.

### New Dependencies Required

**None.**

### Installation

```bash
# Nothing to install. requirements.txt and package.json are unchanged.
```

---

## Feature-by-Feature: Why the Existing Stack Covers It

### 1. Main dashboard (net worth = liquids + investments)

- **Backend:** one aggregation endpoint composing existing `cashflow_summary` + portfolio-valuation logic. `accounts.type` discriminator = one Alembic migration + a `WHERE` clause.
- **Frontend:** cards + recharts, same as the existing cashflow dashboard.
- **New library needed:** No.

### 2. Account manager + Records tab + record input modal

- **Account manager:** `AccountManager.tsx` already exists (CRUD + delete-flow state machine). Extend, don't rebuild. `PlatformManager.tsx` is the same pattern for investments.
- **Records tab (date-grouped ledger, daily nets, filters, bulk actions):**
  - *Date grouping:* a `reduce()` over the fetched page of records, grouped by `date.slice(0,10)`. Plain JS.
  - *Virtualization:* **not needed.** The validated dataset is 5,608 rows over 5 years. A paginated/limit-offset list (the existing recent-transactions pattern) renders a month (~100 rows) trivially. React 18 renders a few hundred DOM rows without jank. Do NOT add `react-window`/`@tanstack/react-virtual` — that's a fix for 10k+ *rendered* rows, which pagination prevents by construction.
  - *Filters:* controlled `<select>`/`<input>` bound to query params on the existing list endpoint. Native `<input type="date">` for date ranges (already the codebase idiom via `datetime-local`).
  - *Bulk actions:* a `Set<number>` of selected ids in component state + one `POST` with an id array. No table library.
- **Record input modal (Expense/Income/Transfer segmented form):** `TransactionModal.tsx` is the direct base — shared create/edit modal, category select with new-category sentinel, `toLocalDatetimeInputValue` helper. A segmented control is three styled `<button>`s toggling a `mode` state var, styled from `styles.ts` tokens (`btnDark`/`btnGhost` variants). BudgetBakers' own segmented control is exactly this.
- **New library needed:** No.

### 3. Platform detail (PnL, buy/sell history)

- Tabs = `useState<"pnl" | "history">` + conditional render (pattern already used across pages). PnL chart = recharts line/bar, same as existing historical value/P&L charts from v1.0 Phase 7. Buy/sell history = the Records-list pattern scoped to `portfolio_events`.
- **New library needed:** No.

### 4. Liquid→investment transfers (paired records, dual-amount cross-currency)

- **Pairing:** a `transfer_group_id` (UUID) or `paired_transaction_id` column via Alembic; both rows written in one SQLAlchemy session/transaction. DB-level atomicity, no app-level saga machinery.
- **Dual-amount entry:** two controlled number inputs (source amount + destination amount) in the modal. Backend stores both as `Numeric`, `Decimal(str(x))` in transit — the established money convention.
- **New library needed:** No.

### 5. Buy/sell debiting/crediting a liquid account atomically

- One endpoint, one `Session` transaction: insert `portfolio_events` row + insert paired `transactions` row, commit together. This composes two existing write paths inside the confirm-before-write proposal flow that already exists (`proposals` table, single-use tokens). SQLAlchemy transactions ARE the atomicity mechanism; nothing to add.
- **New library needed:** No.

### 6. USD→IDR auto-conversion

- **Fully built already.** `backend/fx.py` ships `get_rate()` — cache-first, immutable-insert against `fx_rate_cache` (migration 008), frankfurter adapter via httpx, SSRF-guarded, Decimal-only, never fabricates rate=1.0, USDT→USD alias. Tested in `backend/tests/test_fx.py`.
- v1.2 work is *call sites only*: record entry-time FX via the dual-amount fields; valuation-time FX via `get_rate()`.
- **New library needed:** No. Do NOT add `forex-python`, `currencyconverter`, or any exchange-rate SDK — the adapter registry pattern exists and works.

### 7. Categories as first-class 3-level hierarchy (color/icon/nature/hide)

- **Schema:** self-referential `parent_id` (adjacency list) on a new `categories` table. Depth ≤ 3 is a `CHECK` or app-level validation at write time — three levels never needs `ltree`, closure tables, or nested sets. Postgres `WITH RECURSIVE` (or a single 3-join query) handles rollups; at BudgetBakers scale (~100 categories) even loading the whole table and nesting in Python/JS is fine.
- **Backfill migration:** Alembic data migration mapping distinct `transactions.category` strings → category rows + FK. Same class of migration as v1.0's already-shipped ones.
- **Hierarchical category picker (frontend):** a nested `<select>` with indented option labels (`"— Food"`, `"—— Groceries"`), or a two-step select (parent → child). ~100 total categories fits in one dropdown. Do NOT add a tree-view component library (`rc-tree`, `react-arborist`) for a 3-level, ~100-node picker.
- **Color/icon:** color = hex string column + a swatch picker built from `styles.ts` `chartColors`/token palette (a row of colored `<button>`s). Icon = a small curated set of inline SVGs or emoji strings stored as text — do NOT add an icon font or `react-icons` (the app currently uses zero icon libraries; keep it that way, the paper aesthetic uses text/emoji glyphs).
- **New library needed:** No.

---

## What NOT to Add (YAGNI defense)

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `react-window` / `@tanstack/react-virtual` | Virtualization solves 10k+ rendered rows; pagination caps rendered rows at ~100–500. 5,608 total rows / 5 yrs | Limit-offset pagination on the existing list endpoint + month grouping |
| `@tanstack/react-table` (or any table lib) | Records tab is a styled list with checkboxes, not a spreadsheet. Sorting/filtering happen server-side via query params | Plain mapped rows + `Set<number>` selection state |
| Tailwind / CSS framework / component kit (MUI, shadcn, Radix) | Explicit project decision (v1.1: "no Tailwind migration"); `styles.ts` token layer is the single source of truth | `styles.ts` tokens + inline `React.CSSProperties` |
| Date-picker library | Native `<input type="date">`/`datetime-local` already the codebase idiom (`toLocalDatetimeInputValue`) | Native inputs |
| Form library (react-hook-form, Formik) + Zod | Every existing modal uses controlled `useState` fields + server-side Pydantic validation; forms have ≤8 fields | Existing controlled-component pattern; Pydantic remains the validation boundary |
| FX/currency library (`forex-python`, `babel` for formatting) | `backend/fx.py` + `fx_rate_cache` already implement cache-first ECB rates; IDR formatting already done via `Intl.NumberFormat`/existing helpers | `get_rate()` + existing formatters |
| `django-treebeard`-style tree libs, Postgres `ltree`, closure tables | 3 fixed levels, ~100 nodes. Adjacency list + `parent_id` FK is complete and obvious | `parent_id` self-FK + depth check |
| `sqlalchemy-utils` / `LtreeType` | Same as above | Plain columns |
| Icon library (`react-icons`, lucide) | Zero icon deps today; category icons are a small curated set | Emoji/text glyph column or a handful of inline SVGs |
| State-management lib (Zustand, Redux, React Query) | Pages already own their fetch/refetch lifecycle (`onSaved()` → parent refetch, "Pattern 5"); single-user app, no cache-invalidation complexity | Existing fetch-on-mount + refetch-callback pattern |
| Next.js 15 / React 19 upgrade | No v1.2 feature needs it; App Router API churn (async request APIs) is pure risk during a feature milestone | Stay on 14.2.15 / 18.3.1; revisit as its own chore milestone |
| Any new migration tool | Alembic shipped in v1.0 and has 8 migrations | Alembic 009+ |

## Alternatives Considered

| Recommended | Alternative | When the alternative would win |
|-------------|-------------|-------------------------------|
| Pagination for Records tab | Virtualized infinite scroll | If the product pivoted to rendering *all* records in one scroll AND row count grew 10x. Neither is planned |
| Adjacency-list categories | `ltree` / closure table | Unbounded-depth hierarchies or millions of nodes with subtree queries on hot paths. 3 levels / ~100 nodes never gets there |
| Two-step / indented `<select>` picker | Tree-view component | If categories became drag-to-reorder with hundreds of nodes. Management UI can still be a flat grouped list |
| `transfer_group_id` column | Event-sourcing / double-entry ledger rewrite | A true double-entry core would be a re-platform; paired records + DB transaction gives the same user-facing guarantee for single-user scale |

## Version Compatibility

No changes → no new compatibility surface. Existing pins (recharts ^3.9.2 with React 18.3.1, Next 14.2.15 with TS 5.6.3, fastmcp >=3.4,<4 with FastAPI >=0.110) all shipped and verified in v1.0/v1.1.

## Sources

- `backend/fx.py`, `backend/tests/test_fx.py` — FX capability verified complete in-repo (HIGH)
- `backend/models.py` L83-84 — `category`/`raw_category` free strings confirmed; migration target (HIGH)
- `ui/app/cashflow/TransactionModal.tsx`, `AccountManager.tsx`, `ui/app/investments/PlatformManager.tsx` — reusable modal/manager/select patterns confirmed via graphify + read (HIGH)
- `ui/app/styles.ts` — token layer confirmed as styling source of truth (HIGH)
- `.planning/PROJECT.md` — v1.2 scope, validated data scale (5,608 rows), "don't re-platform" constraint (HIGH)
- nextjs.org/blog — Next.js 15 stable; deliberate decision NOT to upgrade this milestone (HIGH, web-verified 2026-07-18)

---
*Stack research for: monai v1.2 Connected Ledger*
*Researched: 2026-07-18*
