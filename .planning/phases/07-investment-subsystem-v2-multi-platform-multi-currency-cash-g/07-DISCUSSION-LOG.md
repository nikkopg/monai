# Phase 7: Investment Subsystem v2 - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-12
**Phase:** 07-investment-subsystem-v2-multi-platform-multi-currency-cash-gold-viz
**Areas discussed:** Currency & FX model, Cash & gold positions, Allocation pie chart, Chat multi-platform ripple, Historical line chart (added mid-discussion)

**Context at start:** Scope item 1 (multi-platform holdings) already shipped pre-discussion (quick task 260711-rb2 + migration 007). No SPEC.md run; currency model pinned here instead.

---

## Currency & FX model

### FX source
| Option | Description | Selected |
|--------|-------------|----------|
| Manual rate in settings | One editable USD→IDR rate in app_settings | |
| Live FX API | Auto-fetch daily via free API, adapter like prices | ✓ |
| Hardcoded constant | Fixed rate in code | |

### FX timing / P&L semantics
| Option | Description | Selected |
|--------|-------------|----------|
| Current spot for both | Convert cost + value at today's rate; FX cancels out | |
| Historical at purchase | Cost at trade-date rate; unrealized P&L includes FX gain/loss | ✓ |

### Currency scope
| Option | Description | Selected |
|--------|-------------|----------|
| USD + IDR only | Crypto/USDT in USD, else IDR | |
| Arbitrary per-holding currency | General currency column, any currency → IDR | ✓ |

### FX storage / reproducibility
| Option | Description | Selected |
|--------|-------------|----------|
| Snapshot rate on the event | portfolio_events gains currency + fx_rate; cost locks in | |
| Re-fetch by date each time | Store native cost + currency only; look up rate from FX cache | ✓ |

**User's choice:** Live FX API + historical-at-purchase + arbitrary currency + re-fetch-by-date.
**Notes:** Internally consistent — a live API serves by-date rates, which historical-at-purchase and arbitrary currencies both need. Claude added a guard (FX-05): the FX adapter must cache historical by-date rates immutably (keyed date+pair, like price_cache) so re-fetch is stable and past P&L doesn't drift despite the no-column choice.

---

## Cash & gold positions

### Model
| Option | Description | Selected |
|--------|-------------|----------|
| Cash=balance, gold=holding | Cash directly-set (D-03); gold a normal ledger holding w/ P&L | ✓ |
| Both directly-set balances | Simplest; gold loses cost-basis/P&L | |
| Both through events ledger | Uniform one-path; cash-as-buy/sell awkward | |

### Gold price
| Option | Description | Selected |
|--------|-------------|----------|
| Manual price per gram | Enter IDR/gram, via price_cache like reksadana | ✓ |
| Live gold spot adapter | Fetch spot (USD/oz) + FX-convert | |

**User's choice:** Cash = balance (asset_type=cash, D-03 override, value = amount × FX); gold = ledger holding (asset_type=gold, grams × manual per-gram price, full P&L).
**Notes:** Live gold spot adapter deferred — addable later via D-08 registry.

---

## Allocation pie chart

| Option | Description | Selected |
|--------|-------------|----------|
| By asset type | Slices = crypto/stocks/funds/cash/gold | |
| Toggle: asset type ↔ platform | Asset-type pie + toggle to re-slice by platform | ✓ |
| By platform only | Each platform's share | |

**User's choice:** Toggle asset-type ↔ platform.
**Notes:** Value basis = current IDR market value; placement → /gsd-ui-phase.

---

## Chat multi-platform ripple

| Option | Description | Selected |
|--------|-------------|----------|
| Agent resolves & asks | find_platforms read tool; agent asks which platform; proposal carries platform_id | ✓ |
| Default to a platform | Fall back to a designated default | |
| Refuse in chat (UI only) | propose_add_holding returns "use Investments page" | |

**User's choice:** Agent resolves & asks.
**Notes:** Also add the analogous find_accounts read tool — fixes the parallel account-id gap logged in STATE.md Pending Todos.

---

## Historical line chart (added mid-discussion)

User asked "why doesn't the P&L line chart exist yet?" — answered: it's INVX-01, deliberately deferred to v2 in Phase 5; only its data pipeline (portfolio_value_history + daily snapshot scheduler, D-13/D-14) shipped. Data has been accumulating since; can't backfill before that.

### Pull into Phase 7?
| Option | Description | Selected |
|--------|-------------|----------|
| Add it to Phase 7 | Fold INVX-01 in as scope item 6 (data + Recharts ready) | ✓ |
| Keep it deferred (v2) | Leave as INVX-01 | |

### What it plots
| Option | Description | Selected |
|--------|-------------|----------|
| Value, same toggle as pie | Total value over time w/ asset-type↔platform split | |
| Value + P&L views | Two views: value over time AND unrealized P&L over time | ✓ (free-text) |
| Leave details to UI pass | Commit to scope only | |

**User's choice:** Value + P&L views, "like Bitget has" (two curves + time-range selector).
**Notes:** ROADMAP updated to add scope item 6. Source = portfolio_value_history (market_value + cost_basis in IDR/day). Realized P&L still derives from events. History starts at collector go-live (no backfill, D-13).

---

## Claude's Discretion

- Specific free FX API (must support IDR + historical by-date) — research task.
- New asset_type enum strings (cash, gold).
- Migration/backfill: add holdings.currency default IDR; existing IDR holdings unchanged; cash-position storage shape.
- Chart placement, range presets, toggle rendering → /gsd-ui-phase.

## Deferred Ideas

- Live gold spot adapter (manual ships now).
- INVX-02 automated reksadana NAV feed (still v2).
- FIFO cost basis (still rejected, Phase 5 D-02).
