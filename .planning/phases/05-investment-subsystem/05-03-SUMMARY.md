---
phase: 05-investment-subsystem
plan: 03
subsystem: investments
tags: [portfolio, event-ledger, avg-cost, pnl, holdings, rest, ui]
status: complete
requires: ["05-01", "05-02"]
provides:
  - "recompute_holding_from_events / unrealized_pnl / portfolio_summary (portfolio.py)"
  - "apply_add_portfolio_event, apply_add/edit/delete_holding (writes.py)"
  - "PortfolioEventCreate/Out, Holding Create/Update/Out, PortfolioSummary (schemas.py)"
  - "POST /portfolio-events, POST/PUT/DELETE /holdings, GET /investments/summary"
  - "HoldingModal, HoldingOverrideModal, grouped-holdings render on /investments"
affects: [backend/writes.py, backend/schemas.py, backend/main.py, ui/app/investments]
tech-stack:
  added: []
  patterns:
    - "Position derives from the event ledger — apply_add_portfolio_event recomputes the holding (D-01)"
    - "event_type Literal-validated at the schema boundary (422 before recompute, T-05-03-EVT)"
    - "GET /investments/summary is an open composed read (holdings + price_cache + portfolio.py)"
    - "Dual-mode modal via editingHolding == null (mirrors TransactionModal)"
key-files:
  created:
    - ui/app/investments/HoldingModal.tsx
    - ui/app/investments/HoldingOverrideModal.tsx
  modified:
    - backend/portfolio.py
    - backend/writes.py
    - backend/schemas.py
    - backend/main.py
    - backend/tests/test_write_tools.py
    - ui/app/investments/page.tsx
decisions:
  - "notes field kept in HoldingModal per UI-SPEC but not persisted — PortfolioEvent has no notes column; the value is silently dropped rather than adding an unscoped migration"
  - "summary holding rows carry no platform_id (grouping lives on the group); HoldingRow.platform_id is optional and tolerates undefined in the override-edit path"
metrics:
  duration: ~35m
  completed: 2026-07-11
  tasks: 2
  files: 8
---

# Phase 5 Plan 3: Investment Keystone Slice Summary

Buy/sell/dividend event ledger with average-cost accounting, audited holding write helpers + the D-03 direct-override escape hatch, the composed `GET /investments/summary` read, and the `/investments` portfolio view (banner + P&L summary + platform-grouped holding cards) driven through `HoldingModal` and `HoldingOverrideModal`.

## What was built

**Task 1 (prior run, commit `5da9c8e` — not redone):** `backend/portfolio.py` — `recompute_holding_from_events`, `unrealized_pnl`, `portfolio_summary` (+ private `_latest_price`, `_realized_for_ticker`). Its two tests pass. Task 2/3 build directly on these signatures; notably `portfolio_summary(db)` already returns the exact composed payload the summary route needs (platform groups, per-holding nullable price/unrealized, totals, `as_of`), so the route is a thin wrapper.

**Task 2 — backend (commit `cc9a6ea`):**
- `backend/writes.py`: `apply_add_portfolio_event` (inserts `portfolio_events` row with `Decimal(str(...))` money, audits `entity="portfolio_event"`, then calls `recompute_holding_from_events(db, ticker)` before returning — D-01) and `apply_add_holding` / `apply_edit_holding` / `apply_delete_holding` (D-03 direct override, `entity="holding"`, audited, before-snapshot on edit/delete). Helpers never self-commit.
- `backend/schemas.py`: `PortfolioEventCreate` (`event_type: Literal["buy","sell","dividend"]`, `quantity`/`price` positive `MoneyDecimal`, `date`, `ticker`), `PortfolioEventOut`, `HoldingCreate`/`HoldingUpdate`/`HoldingOut`, `PortfolioSummary`.
- `backend/main.py`: `POST /portfolio-events`, `POST /holdings`, `PUT /holdings/{id}`, `DELETE /holdings/{id}` — all `dependencies=[Depends(require_api_key)]`, apply→commit→refresh→reset_engine, `ValueError→422`; open `GET /investments/summary` composing via `portfolio.portfolio_summary`.

**Task 3 — UI (commit `5c0059f`):**
- `HoldingModal.tsx`: event entry (Ticker / Asset type / Platform / Event type / Quantity / Price / Date / Notes); Dividend relabels Price→"Dividend amount (IDR)" and defaults Quantity to 1; POSTs `/api/portfolio-events`, refetches summary on success.
- `HoldingOverrideModal.tsx`: D-03 escape hatch, de-emphasized italic bypass caption, dual-mode create/edit → POST/PUT `/api/holdings`, Currency read-only "IDR".
- `page.tsx`: fetches `/api/investments/summary`; portfolio-total banner (Display figure + "as of" caption + placeholder disabled "Refresh prices" button for Plan 04), 2-column signed/colored Unrealized/Realized P&L summary, platform-grouped holding cards + "Unassigned" group, zero-qty holdings filtered (D-04), empty states, "Log event" primary CTA + de-emphasized "Add holding directly" text-link. Crypto-precision quantity formatter + `signDisplay:"always"` P&L formatter mirroring `cashflow/page.tsx`.

## Verification results

| Check | Result |
|-------|--------|
| `pytest backend/tests/test_write_tools.py -x -q` | **19 passed** |
| event_type "gift" → 422 (before recompute) | PASS (`test_portfolio_event_rejects_unknown_type`; no `GIFTTEST` holding created) |
| write without API key → 401 | PASS (`test_portfolio_event_requires_api_key` — api_key fixture configures the server key so the fail-closed 503 guard is satisfied, then the header is omitted to hit 401) |
| event write recomputes holding + one audit row | PASS (`test_apply_add_portfolio_event_audits_and_recomputes`) |
| edit/delete holding audited (D-03) | PASS (`test_apply_edit_and_delete_holding_audit`) |
| grouped summary payload with as_of + null→unassigned | PASS (`test_investments_summary_grouped_payload`; buy 10@100 then sell 4@250 → qty 6, avg 100, realized 600, current 300 → unrealized 1200) |
| GET /investments/summary over HTTP | 200, Decimals serialize as JSON numbers |
| `npx tsc --noEmit` (three UI files) | **OK** (zero TS errors project-wide) |

## Deviations from Plan

**1. [Rule 1 — Test setup] Auth test needs the api_key fixture to reach 401, not 503.**
- Found during: Task 2 verify. `test_portfolio_event_requires_api_key` initially took only `client`; with no `MONAI_API_KEY` configured, `require_api_key` returns the fail-closed 503 (misconfigured-server guard), not 401.
- Fix: added the `api_key` fixture (configures a server key) and omitted the request header — the exact pattern the existing `test_post_platforms_requires_api_key` uses.
- Commit: `cc9a6ea`.

## Known Stubs

- **"Refresh prices" button** (`page.tsx`) — rendered disabled with a title noting Plan 04 wires the live-fetch handler. Intentional per plan (`<action>`: "placeholder Refresh prices button — Plan 04 wires its handler").
- **`notes` field in HoldingModal** — visible per UI-SPEC but not sent/persisted (`PortfolioEvent` has no `notes` column). Left as inert UI rather than adding an unscoped migration.

## Deferred Issues

- `backend/tests/test_portfolio.py::test_manual_price_override` and `::test_staleness_ttl` fail as "not yet" placeholders — Plan 04 red-target scaffolds, out of scope for Plan 03. Logged in `deferred-items.md`. Task 1's own tests (`test_recompute_holding_from_events`, `test_avg_cost_realized_pnl`) pass.

## Outstanding

- **Human UAT (deferred, non-blocking):** browser flow — log a buy then a sell for one ticker, confirm the holding card shows recomputed qty/avg cost + realized P&L; use "Add holding directly" to seed a position; confirm platform grouping + Unassigned card + empty states render per UI-SPEC. Requires a rebuilt stack (`docker compose up -d --build`) before live verify.

## Self-Check: PASSED

- Created files exist: `ui/app/investments/HoldingModal.tsx`, `ui/app/investments/HoldingOverrideModal.tsx` — FOUND.
- Commits exist: `cc9a6ea`, `5c0059f` — FOUND.
