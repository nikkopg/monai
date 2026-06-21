# Feature Research

**Domain:** Self-hosted personal cashflow + investment tracker with agentic AI chat (single-user)
**Researched:** 2026-06-21
**Confidence:** HIGH (verified against Firefly III, Ghostfolio, Wealthfolio, Smashing Magazine agentic UX patterns, CoinGecko/IDX API landscape)

---

## Scope Framing

This is a **subsequent milestone** research. The following already exist and are NOT re-researched:

- Wallet CSV import (backend)
- Read-only AI query (9 spending tools)
- Manual transaction entry (`POST /transactions`)
- Single-page Next.js UI

The new areas: **Cashflow Dashboard**, **Investment Tracker**, **Agentic Chat**, **Settings Page**.

---

## Feature Landscape

### Table Stakes — Cashflow Dashboard

Features any personal-finance UI must have. Missing them makes the app feel like a prototype.

| Feature | Why Expected | Complexity | Dependencies |
|---------|--------------|------------|--------------|
| Overview cards (total income, total expenses, net, account balances) | Every personal-finance tool from Firefly III to spreadsheets leads with this | LOW | Existing transactions + accounts endpoints |
| Spending-by-category donut/bar chart (current month) | Standard since Mint; donut chart is the canonical category breakdown | LOW | `spending_by_category` tool already exists |
| Income vs expense bar chart (month-over-month, last 6–12 months) | Users expect to see trend at a glance, not just current month | MEDIUM | Requires new trend aggregation tool in `tools.py` |
| Month-over-month spend trend line chart | The "am I spending more this month?" question is universal | MEDIUM | Same trend tool as above |
| Recent transactions list (sortable, filterable by category/account) | Every cashflow app surfaces a transaction log; essential for spot-checking | LOW | GET /transactions already exists; needs filter params |
| Edit transaction inline (amount, date, category, note, account) | Users correct import errors and miscategorized entries constantly | MEDIUM | No UPDATE endpoint exists today — must be built |
| Delete transaction | Users remove duplicates and test entries | LOW | No DELETE endpoint today — must be built |
| Create transaction manually (form in dashboard) | Already exists in the single-page UI; must carry over to the new page | LOW | POST /transactions exists |
| Account list with current balance per account | Users need to verify their account balances match reality | LOW | GET /accounts exists; balances need to be computed from transactions |
| Create / edit / delete account | Managing where money lives is prerequisite to correct categorization | MEDIUM | No account CRUD endpoints exist today |
| Category list with total spend | Category overview is the starting point for any spending analysis | LOW | `list_categories` tool + `spending_by_category` already exist |
| Rename category (all historical transactions remapped) | Wallet CSV categories are often verbose or inconsistent; renaming without remapping is useless | MEDIUM | No category endpoint exists; must update `category` column on all matching rows |
| Merge categories (move all transactions from A into B, delete A) | Power-users inevitably accumulate near-duplicate categories | MEDIUM | Depends on category rename logic; two-step: remap + delete |
| CSV upload from UI (Wallet CSV) | Without this, new installs require a manual script — not self-service | LOW | POST /import endpoint exists; UI file-upload widget missing |
| Date range picker for all dashboard views | Users want to analyze custom periods, not just presets | LOW | All tools already accept `period` arg; UI control needed |

### Table Stakes — Investment Tracker

| Feature | Why Expected | Complexity | Dependencies |
|---------|--------------|------------|--------------|
| Holdings list (ticker, quantity, avg cost, current price, current value, P&L, P&L%) | Any portfolio tracker surfaces this as the primary view (Ghostfolio, Wealthfolio both lead here) | MEDIUM | New `holdings` table; price fetch layer |
| Add / edit / delete holding (ticker, quantity, avg_cost, purchase_date, currency) | Manual CRUD is the minimum viable investment tracker without brokerage sync | LOW | New `/holdings` CRUD endpoints needed |
| Portfolio total value and total unrealized P&L | Users want the headline number immediately | LOW | Derived from holdings × current prices |
| Per-holding unrealized P&L in IDR and % | Essential sanity check; Ghostfolio and Portfolio Performance both surface this | LOW | Computed from (current_price − avg_cost) × quantity |
| Live price display (last updated timestamp) | Users need to know if the price is stale | LOW | Price fetch service; staleness indicator |
| Manual / last-known price fallback | IDX stocks and reksadana lack reliable free APIs — fallback is required, not optional | LOW | UI input for manual price override; stored in `holdings` or a price cache |
| CSV import for holdings (ticker,quantity,avg_cost,purchase_date,currency) | Schema is already locked in ARCHITECTURE.md; import is faster than manual entry for existing portfolios | MEDIUM | New importer module; `/holdings/import` endpoint |
| portfolio_events log (buy/sell/dividend/split with date + price) | Required for correlation queries ("since I bought X…") and for accurate P&L history | MEDIUM | New `portfolio_events` table; event CRUD |

### Table Stakes — Agentic Chat

| Feature | Why Expected | Complexity | Dependencies |
|---------|--------------|------------|--------------|
| Multi-step reasoning (agent chains multiple tools in one turn) | Single-tool-per-question is already shipped; "and also…" compound questions need chaining | HIGH | LlamaIndex agentic loop; tool registry expansion |
| Read tools over all domains (spending + investments) | Users ask cross-domain questions; agent must see both | MEDIUM | New investment query tools added to `tools.py` |
| Natural-language write: add transaction | Users describe a purchase; agent creates the entry | MEDIUM | Agent calls write tool → confirm-before-apply |
| Natural-language write: edit transaction | Users correct a past entry in conversation | MEDIUM | Same confirm-before-apply pipeline |
| Natural-language write: delete transaction | Users remove duplicate or erroneous entries | MEDIUM | Same confirm-before-apply pipeline |
| Natural-language write: add/edit/delete holding | Users update their portfolio without touching the form | MEDIUM | Investment write tools |
| Confirm-before-write UX (agent proposes, user approves or rejects) | This is the non-negotiable safety invariant for a money app; validated as a core requirement in PROJECT.md. Smashing Magazine (2026) identifies this as the canonical agentic-AI UX pattern for high-risk actions | HIGH | Pending action state in backend + approve/reject UI in chat |
| Audit log of applied writes | Users need to verify what was changed and when; required for trust | MEDIUM | `audit_log` table; log on each confirmed write |
| Honest refusal when agent cannot map question to tools | Inherited from existing tool-router philosophy; must be preserved in agentic mode | LOW | Already in `query.py`; must carry over to agent loop |
| Streaming / incremental chat response display | For agentic chains, users need progress feedback — a blank screen for 10s = apparent hang | MEDIUM | SSE or WebSocket streaming from FastAPI to Next.js |

### Table Stakes — Settings Page

| Feature | Why Expected | Complexity | Dependencies |
|---------|--------------|------------|--------------|
| LLM provider selector (Ollama / Claude / OpenAI) with model name input | Currently env-var only; settings page is the UX commitment in PROJECT.md | LOW | Existing `config.py`; needs a `/settings` GET+PUT endpoint |
| API key inputs (Anthropic, OpenAI) with masked display | Required for cloud LLM providers; must never log or echo keys in plaintext | LOW | Secure storage in env or a config table |
| Base currency display (IDR, read-only for now) | Users need to confirm what currency the app is operating in | LOW | Informational; no logic change needed |
| Price data source selector (CoinGecko / manual / future IDX API) | Required for the investment tracker's price fetch layer | LOW | Price service abstraction in backend |
| Ollama base URL override | Users running Ollama on a non-default port or remote host need this | LOW | Already in `config.py`; expose in UI |

---

### Differentiators

Features that separate monai from Firefly III, Ghostfolio, or any other self-hosted tool. These are the reason this app exists.

| Feature | Value Proposition | Complexity | Dependencies |
|---------|-------------------|------------|--------------|
| Spending ↔ investment correlation queries in natural language ("since I bought NVDA, how has my eating-out changed?") | No self-hosted tool combines cashflow + portfolio data in a single AI query. This is the documented differentiator in PROJECT.md. Cross-domain analysis requires agent chaining spending tools + portfolio event lookup + period alignment | HIGH | `portfolio_events` table; new correlation tools in `tools.py`; agentic multi-tool chaining |
| Confirm-before-write agentic writes with full audit trail | Most AI finance tools are read-only. The ability to write via NL with human-in-the-loop confirmation is rare in self-hosted software | HIGH | Pending-action state machine; approve/reject UI; audit log |
| LLM never writes SQL (correctness-by-construction) | Competitors using NL-to-SQL return confident wrong numbers on real multi-year datasets. The parameterized tool approach is load-bearing — it's why the numbers are correct | MEDIUM | Extend `tools.py` for new domains; no free SQL in agent |
| MCP server (web chat + external Claude Desktop / IDE clients) | Exposing finances as an MCP tool surface means Claude Desktop can query your spending from any conversation — no other self-hosted finance app does this | HIGH | FastAPI MCP server layer; read-only tool subset for external clients |
| IDX + crypto + reksadana coverage (Indonesian market) | Global tools (Ghostfolio, Wealthfolio) use Yahoo Finance + Alpha Vantage. IDX stocks and Indonesian mutual funds are poorly served. Targeted support for Sectors.app / OHLC.dev (IDX), CoinGecko (crypto), Bibit API (reksadana), and manual fallback serves the actual portfolio | MEDIUM | Price service abstraction with pluggable adapters per instrument type |
| Privacy-first, local-first, fully self-hosted | All data stays in a local Postgres volume. No telemetry, no cloud dependency. Ollama default means LLM calls stay on-device | LOW | Already the architecture; just needs to be maintained |
| Spending trend tools (month-by-month, period comparison, recurring charge detection) | Standard read tools cover totals; trend and recurrence detection help users find subscriptions and lifestyle drift | MEDIUM | New tools in `tools.py`; no schema changes |

---

### Anti-Features (Explicitly Out of Scope)

Features commonly requested in finance apps that are explicitly excluded from monai, with rationale to prevent re-litigating.

| Feature | Why Requested | Why Problematic / Out of Scope | Alternative Approach |
|---------|---------------|-------------------------------|----------------------|
| Bank sync / Open Banking aggregation | Automatic transaction import from banks | PCI scope, OAuth complexity with each bank, credential storage risk, country-specific API fragmentation (Indonesia has no Plaid equivalent). Explicitly out of scope in PROJECT.md | Wallet CSV import from the Android app; covers the same data without the attack surface |
| Multi-user / account permissions | Shared household finances | Single-user self-hosted by design; auth layer + per-user data isolation doubles complexity for zero benefit to the target user | Deploy separate instances per user |
| Budget / envelope tracking | Users want to set spending limits | Not core to the AI value proposition; creates a separate UX surface with its own complexity (YNAB, Actual Budget do this better) | Agent can answer "how close am I to last month's food spending?" without formal envelopes |
| Real-time (sub-minute) price updates | Live ticker display in investment view | IDX has no free real-time API; CoinGecko free tier is rate-limited; real-time WebSocket infrastructure adds significant complexity | End-of-day price fetch on demand or on a daily schedule; staleness timestamp shown |
| Agent free-form SQL generation | Covering query types not in the tool registry | Reintroduces the confident-wrong-number failure mode that caused the original tool-router pivot. Explicitly excluded in PROJECT.md | Expand the parameterized tool set; agent says "I can't answer that yet" if no tool matches |
| Write tools over MCP to external clients | Using Claude Desktop to edit transactions | Destructive writes without the app's confirmation UI = no safety gate. External MCP clients get read-only tools this cycle | Web app chat is the write interface; MCP = read + query |
| Multi-currency normalization (fx_rate) | Users with foreign accounts | Validated as a non-issue: 0 of 5608 rows are foreign-currency. `base_currency`/`fx_rate` parked in PROJECT.md | Investments can carry their own currency field; spending stays IDR |
| AI market-news filtering / sentiment | "What does the market think about BBCA?" | Out of scope in PROJECT.md; adds an external news dependency and hallucination risk | Manual research outside the app |
| Weather correlation | "Do I spend more when it rains?" | Recorded as a non-goal; novelty without actionability | — |
| Recurring budget automation (auto-pay, scheduled transfers) | Set-and-forget finance | Requires external integrations (bank APIs, scheduler); far outside the read/write-with-confirmation model | Manual transaction entry; agent can remind the user of recurring charges it detects |

---

## Feature Dependencies

```
[CSV upload UI]
    └──requires──> [POST /import endpoint] (already exists)

[Transaction edit/delete UI]
    └──requires──> [PUT /transactions/{id}, DELETE /transactions/{id}] (must build)

[Account CRUD UI]
    └──requires──> [POST/PUT/DELETE /accounts endpoints] (must build)

[Category rename UI]
    └──requires──> [PUT /categories/{name}/rename endpoint] (must build)

[Category merge UI]
    └──requires──> [Category rename logic] (merge = remap + delete)

[Dashboard trend charts]
    └──requires──> [New trend aggregation tool in tools.py]

[Holdings list with live prices]
    └──requires──> [holdings table + CRUD endpoints]
    └──requires──> [Price fetch service (CoinGecko / IDX adapter)]

[Holdings CSV import]
    └──requires──> [holdings table]

[portfolio_events log]
    └──requires──> [holdings table] (ticker FK reference)

[Spending ↔ investment correlation queries]
    └──requires──> [portfolio_events table]
    └──requires──> [Agentic multi-tool chaining]
    └──requires──> [New correlation tools in tools.py]

[Agentic multi-tool chaining]
    └──requires──> [LlamaIndex ReAct / function-calling agent loop]

[Agentic NL writes (transactions, holdings)]
    └──requires──> [Agentic multi-tool chaining]
    └──requires──> [Confirm-before-write state machine]

[Confirm-before-write UI]
    └──requires──> [Pending action state in backend (e.g. pending_actions table or in-memory)]
    └──requires──> [Approve / reject API endpoints]

[Audit log]
    └──requires──> [Confirm-before-write state machine] (log on confirmation)

[MCP server (external clients)]
    └──requires──> [Tool registry]
    └──enhances──> [Agentic agent loop]

[Settings page LLM config]
    └──requires──> [GET /settings + PUT /settings endpoints]
    └──enhances──> [All AI features]

[Price data source selector in settings]
    └──requires──> [Price service abstraction]
    └──enhances──> [Holdings live price display]
```

### Key Dependency Notes

- **Category rename is a prerequisite for merge.** Merge is implemented as: remap all transactions from source category to target category name (rename logic), then drop the source. Build rename first.
- **portfolio_events is a prerequisite for correlation queries.** The "since I bought X" query needs a dated event log to anchor the before/after spending periods. Holdings alone (current snapshot) are not enough.
- **Confirm-before-write must be built before any NL write tool.** The safety invariant is non-negotiable. Do not ship write tools without the approval gate.
- **Price fetch service must be abstracted.** IDX, crypto, and reksadana need different adapters. A single pluggable `PriceFetcher` interface prevents tight coupling to any single API.
- **MCP server is additive.** It wraps the existing tool registry. Build and stabilize the tool registry first; MCP layer is the final step.

---

## MVP Definition for This Milestone

### Launch With (this milestone, all four areas)

**Cashflow Dashboard:**
- [ ] Overview cards (income, expenses, net, account balances)
- [ ] Spending-by-category donut chart
- [ ] Income vs expense month-over-month bar chart
- [ ] Recent transactions list with filters
- [ ] Transaction edit + delete (PUT/DELETE endpoints + inline UI)
- [ ] Account create/edit/delete
- [ ] Category rename + merge
- [ ] CSV upload from UI

**Investment Tracker:**
- [ ] Holdings CRUD (form UI + API endpoints)
- [ ] Live price fetch with manual fallback
- [ ] Holdings table: ticker, quantity, avg cost, current price, value, P&L, P&L%
- [ ] Portfolio total value + total unrealized P&L
- [ ] portfolio_events log (buy/sell) for correlation query foundation
- [ ] Holdings CSV import

**Agentic Chat:**
- [ ] Multi-step agent loop (LlamaIndex ReAct or function-calling)
- [ ] Read tools across spending + investments
- [ ] Confirm-before-write gate (pending action state + approve/reject UI)
- [ ] NL writes: add/edit/delete transaction, add/edit/delete holding
- [ ] Audit log of applied writes
- [ ] Spending ↔ investment correlation query (at least one example: "since I bought X, how has category Y changed?")
- [ ] Streaming response display

**Settings:**
- [ ] LLM provider/model selector
- [ ] API key inputs (masked)
- [ ] Price data source selector
- [ ] Ollama base URL override

### Add After Validation (v1.x)

- [ ] MCP server for external clients (Claude Desktop) — additive; needs stable tool registry first
- [ ] Richer trend tools: recurring-charge detection, period comparison, spend forecasting
- [ ] Additional price adapters: Sectors.app (IDX), Bibit (reksadana) — depends on API key availability
- [ ] Dividend tracking (portfolio_events event_type="dividend")

### Future Consideration (v2+)

- [ ] Public/open-source release (CI, Docker Hub)
- [ ] Multi-currency normalization (if foreign-currency account is ever added)
- [ ] Write tools over MCP (if external-client write use case is validated)

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Transaction edit/delete | HIGH | LOW | P1 |
| Overview dashboard cards | HIGH | LOW | P1 |
| Spending-by-category chart | HIGH | LOW | P1 |
| CSV upload from UI | HIGH | LOW | P1 |
| Account CRUD | HIGH | MEDIUM | P1 |
| Category rename + merge | HIGH | MEDIUM | P1 |
| Holdings CRUD + manual price | HIGH | MEDIUM | P1 |
| Holdings list with P&L | HIGH | MEDIUM | P1 |
| Confirm-before-write agentic gate | HIGH | HIGH | P1 |
| Agentic multi-tool chaining | HIGH | HIGH | P1 |
| Income vs expense trend chart | MEDIUM | MEDIUM | P1 |
| Spending ↔ investment correlation | HIGH | HIGH | P1 (the differentiator) |
| portfolio_events log | MEDIUM | LOW | P1 (prereq for correlation) |
| Settings page | MEDIUM | LOW | P1 |
| NL write: transaction | HIGH | MEDIUM | P1 |
| NL write: holding | MEDIUM | MEDIUM | P1 |
| Audit log | MEDIUM | LOW | P1 |
| Holdings CSV import | MEDIUM | MEDIUM | P2 |
| Streaming chat response | MEDIUM | MEDIUM | P2 |
| MCP server (external clients) | MEDIUM | HIGH | P2 |
| Recurring charge detection tool | MEDIUM | MEDIUM | P2 |
| Sectors.app / Bibit price adapters | MEDIUM | MEDIUM | P2 |
| CoinGecko price adapter | MEDIUM | LOW | P2 |
| Period comparison trend tool | LOW | MEDIUM | P3 |

---

## Competitor Feature Analysis

| Feature | Firefly III | Ghostfolio | Wealthfolio | monai (this milestone) |
|---------|-------------|------------|-------------|----------------------|
| Transaction CRUD | Full (split, reconcile) | Not applicable | Not applicable | Full (add/edit/delete) |
| Category management | Full (hierarchical) | Not applicable | Tag-based | Rename + merge (flat) |
| Dashboard charts | Income/expense, category breakdown, account balance | Portfolio value, P&L, allocation | Holdings table, performance | Spending + investment combined |
| Investment holdings | Not applicable | Holdings CRUD, price fetch | Holdings CRUD | Holdings CRUD + events |
| Live price data | Not applicable | Yahoo Finance + CoinGecko | Yahoo Finance | CoinGecko + manual fallback; IDX via Sectors.app/OHLC.dev |
| AI / NL query | Not applicable | Not applicable | Not applicable | Agentic chat (read + write) |
| Cross-domain correlation | Not applicable | Not applicable | Not applicable | Spending ↔ portfolio (unique) |
| Confirm-before-write AI | Not applicable | Not applicable | Not applicable | Yes, canonical pattern |
| MCP server | Not applicable | Not applicable | Not applicable | Yes (external clients) |
| Bank sync | Yes (via Nordigen/GoCardless) | No | No | Explicitly out of scope |
| Multi-user | Yes | Yes | No | Explicitly out of scope |
| Budget envelopes | Yes | No | No | Explicitly out of scope |

---

## UX Considerations

### Confirm-Before-Write Pattern

The confirm-before-write flow for agentic writes must show:
1. The exact action the agent intends to take (e.g., "Update transaction #482: change category from 'Restaurant, fast-food' to 'Food'")
2. The current vs. proposed values side by side
3. Two clear buttons: **Apply** and **Cancel**
4. Nothing is written until Apply is clicked

The agent's pending action must be stored in backend state (not just frontend) so that a page refresh does not silently drop the unconfirmed change. A simple `pending_actions` table or in-memory dict keyed by session ID works for single-user.

Smashing Magazine (Feb 2026) articulates this as the canonical pattern: "Write confirmation messages like a transaction confirmation, not a permission scope — the user should be able to read the notification without any context and immediately know whether to approve."

### Correlation Query UX

"Since I bought NVDA, how has eating-out changed?" requires:
1. Agent looks up `portfolio_events` for the ticker purchase date
2. Agent computes spending in the category for the period before vs. after that date
3. Agent presents the comparison with actual numbers, not a narrative guess

The agent must use the parameterized tool approach for both legs — no free SQL. One tool for portfolio event lookup, one for period-bounded category spending, chained by the agent with the shared date anchor.

### Price Data for IDX / Crypto / Reksadana

- **Crypto:** CoinGecko free (Demo) tier supports IDR pricing and is rate-limited but adequate for end-of-day portfolio refresh. No API key required for basic endpoints.
- **IDX stocks:** OHLC.dev and Sectors.app both provide IDX data with API keys (paid tiers). The manual/last-known-price fallback is required because free tier coverage of IDX is uncertain.
- **Reksadana:** The Bibit API (unofficial, see github.com/risan/bibit-reksadana) provides NAV data but is unofficial and may break. Manual price entry is the safe default. The settings page should expose the price source per instrument type or per holding.

---

## Sources

- [Firefly III feature list](https://docs.firefly-iii.org/explanation/firefly-iii/about/introduction/)
- [Ghostfolio open-source wealth management](https://github.com/ghostfolio/ghostfolio)
- [Ghostfolio self-hosted guide 2026](https://www.pistack.xyz/posts/ghostfolio-self-hosted-portfolio-tracker-wealth-management-guide-2026/)
- [Wealthfolio open-source portfolio tracker](https://wealthfolio.app/)
- [Smashing Magazine — Designing for Agentic AI: Practical UX Patterns](https://www.smashingmagazine.com/2026/02/designing-agentic-ai-practical-ux-patterns/)
- [CoinGecko API (free Demo tier)](https://www.coingecko.com/en/api)
- [OHLC.dev IDX API](https://ohlc.dev/indonesia-stock-exchange-idx-api)
- [Sectors.app Indonesia stock data API](https://sectors.app/)
- [Bibit Reksadana unofficial API](https://github.com/risan/bibit-reksadana)
- [Agno — human-in-the-loop controls for AI agents](https://www.agno.com/blog/how-to-add-human-in-the-loop-controls-to-ai-agents-that-actually-run-in-production)
- [Syncfusion — 7 essential financial charts](https://www.syncfusion.com/blogs/post/financial-charts-visualization)
- [MoneyLover — category merge UX](https://moneylover.zendesk.com/hc/en-us/articles/33742206448793-Create-edit-delete-and-merge-categories)
- [Quicken — merge categories](https://info.quicken.com/mac/merge-categories)

---

*Feature research for: monai (cashflow + investment + agentic AI chat)*
*Researched: 2026-06-21*
