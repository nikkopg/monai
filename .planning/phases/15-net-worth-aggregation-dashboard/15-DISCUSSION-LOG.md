# Phase 15: Net Worth Aggregation + Dashboard - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-31
**Phase:** 15-net-worth-aggregation-dashboard
**Mode:** `--auto go with all recs` (all gray areas auto-selected; recommended option chosen per question)
**Areas discussed:** Aggregation seam, Liquid/investment partition, Coverage assertion, Dashboard presentation

---

## Aggregation seam

| Option | Description | Selected |
|--------|-------------|----------|
| New dedicated `net_worth` read (tool + `GET /net-worth`) composing existing reads | One home for the number + coverage assertion; exposable as agent/MCP read | ✓ |
| Bolt net worth onto `cashflow_summary` | Fewer surfaces, but overloads a spending-scoped read | |
| Compute in the frontend from separate calls | No single source of truth; assertion can't live server-side | |

**Choice:** New dedicated read (D-01), registered on read-only surfaces (D-02).
**Notes:** `account_balances` already flags the split as "Phase 15 discretion item D".

---

## Liquid/investment partition (double-count guard)

| Option | Description | Selected |
|--------|-------------|----------|
| Partition by `accounts.type`: liquid = SUM(type='liquid'), investment = portfolio_summary.total_value | Reuses migration-010 discriminator; counted-once by construction | ✓ |
| Sum all account balances + portfolio (subtract investment accounts) | Fragile; reintroduces double-count risk | |
| Tag holdings back to accounts | Contradicts "investment money is never a synthetic account row" (Phase 13 D-05) | |

**Choice:** Partition by `accounts.type` (D-03/D-04).
**Notes:** id 3 "Investments" (type=investment) excluded from liquid; Stockbit id 559 stays liquid (broker cash).

---

## Coverage assertion (SC #3)

| Option | Description | Selected |
|--------|-------------|----------|
| Assert liquid_count + investment_count == total accounts; loud-raise on unclassified; return covered count | Cheap given DB CHECK; testable; loud not silent | ✓ |
| Trust the DB CHECK, no runtime assertion | Meets schema invariant but not SC #3's "asserted to cover 100%" | |

**Choice:** Runtime coverage assertion + test (D-05/D-06).

---

## Dashboard presentation

| Option | Description | Selected |
|--------|-------------|----------|
| Net-worth headline + liquid/investment split + per-side breakdown on existing `/cashflow` page | Rescopes existing dashboard; reuses cards; matches PROJECT.md intent | ✓ |
| Brand-new dedicated dashboard page | More scope; overlaps Phase 16 | |

**Choice:** Headline + split + per-side breakdown on `/cashflow` (D-07/D-08).
**Notes:** root `/` already redirects to `/cashflow`.

---

## Claude's Discretion

- Payload field names / Pydantic schema shape for the `net_worth` read.
- Whether liquid per-account rows extend `account_balances` (carry `type`) or a dedicated query.
- Frontend layout details within existing dashboard styling.

## Deferred Ideas

- Records tab, account/platform managers, record modal, PnL/buy-sell views — Phase 16.
- Net-worth history / trend-over-time chart — future phase (not in NW-01/NW-02).
