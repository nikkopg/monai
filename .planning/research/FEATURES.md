# Feature Research

**Domain:** Personal finance ledger — transfers, balance adjustments, investment buy/sell, cross-currency entry, hierarchical categories, net worth aggregation
**Researched:** 2026-07-18
**Confidence:** MEDIUM (cross-checked across Firefly III, Actual Budget, GnuCash, YNAB, BudgetBakers Wallet official docs/wikis; no primary-source access to BudgetBakers' internal implementation, so exact mechanics are inferred from documented UX behavior, not source code)

**Supersedes for this milestone:** the previous FEATURES.md (2026-06-21) covered v1.0 scope (cashflow dashboard, investment tracker basics, agentic chat, settings) — all now shipped, not re-researched. This file is scoped ONLY to the v1.2 "Connected Ledger" target features: net-worth dashboard, account/platform managers, Records ledger, transfers, balance adjustments, buy/sell atomicity, cross-currency entry, and first-class categories.

## Feature Landscape

### Table Stakes (Users Expect These)

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Transfer as one record, not two independent entries | Every reference app (Firefly III, Actual Budget, BudgetBakers Wallet) presents a transfer as a single logical thing in the UI even though it's stored as two ledger rows. Users who see "Transfer $50 Checking → Savings" twice as separate expense/income rows perceive it as a bug. | MEDIUM | Store as a **linked pair**: two `records` rows sharing a `transfer_group_id` (or equivalent), opposite signs, same timestamp. UI collapses them into one row in the date-grouped ledger. |
| Editing/deleting one side of a transfer updates/deletes both | Firefly III and Actual Budget both guarantee this; Actual's own bug tracker shows what breaks when it *doesn't* hold (split-transfer bug leaves orphaned unlinked rows). | MEDIUM | Any edit path (amount, date, account) must write through both rows atomically in one DB transaction. Deleting one must delete (or explicitly orphan-warn) the other — never leave a dangling half-transfer. |
| Balance-adjustment records are a distinct, visible record type — not silently merged into "Expense" | YNAB and Firefly III both surface these as a named type ("Reconciliation", "Balance Adjustment") rather than disguising them as a normal expense/income. Users need to see *why* a balance jumped without a matching real-world transaction. | LOW | monai's account manager already plans this ("balance edits create adjustment records — balances stay derived"). Give it its own `record_type = 'adjustment'` (or similar), category-less, so it's filterable/excludable from spending totals. |
| Buy/sell events atomically move cash out of/into a real liquid account | GnuCash's core model: a stock purchase always has a matching cash-account leg (the guide explicitly steers users toward a real bank/brokerage account leg rather than a floating `Equity:Opening Balance` entry). monai's own spec already requires this: "buy/sell modal picks liquid source/destination account, one confirmation applies both entries atomically." | MEDIUM | Extends the existing `portfolio_events` + `holdings` model: a buy/sell event needs a linked record in a liquid account so the cash side is never invisible. Must be one DB transaction — a buy that debits liquid cash but fails to create the portfolio_event (or vice versa) is a correctness bug in a money app. |
| Cross-currency transfer requires an explicit destination-currency amount, not just an auto-converted number | Firefly III's foreign-amount field exists specifically because auto-FX at entry time is often wrong (bank spread, stale rate) — letting the user override is table stakes, not a nice-to-have. monai's own spec already calls this "dual-amount cross-currency." | LOW–MEDIUM | UI: two amount fields when source/destination account currencies differ (source amount IDR, destination amount USD or vice versa). Store both amounts + implied rate on the transfer pair. Do NOT force a live-FX-only entry path. |
| Category tree with parent → child (→ grandchild) and a "reassign before delete" or "block delete if in use" guard | Every reference app in this space enforces *some* protection against orphaned/miscategorized transactions on category delete. BudgetBakers Wallet (the explicit reference) hard-blocks deletion of an in-use (sub)category until the user reassigns affected records. Actual Budget instead prompts inline for a replacement category. | MEDIUM | Pick one behavior deliberately (see Behavior Specifics below) — don't leave it ambiguous. |
| Net worth = sum of exactly one record per real account/holding (no implicit double count) | Every net-worth aggregator (Monarch, Empower, MyAssets) works this way *structurally* — net worth isn't computed by a dedup algorithm, it's guaranteed by having one canonical account entity per real-world thing. monai's own PROJECT.md names the exact bug this fixes: the current investment-account double-count. | LOW (schema-driven) | This is exactly what `accounts.type` as liquid/investment discriminator solves — the fix is in *data modeling* (one row = one account, tagged once), not in dashboard-layer math. Confidence LOW on citing a named "double-counting bug" case study elsewhere (nobody publicly documents this failure mode) but MEDIUM-HIGH as an architectural inference, since it's the obvious corollary of every net-worth tool's one-account-one-entry design and matches monai's own diagnosed root cause. |

### Differentiators (Competitive Advantage)

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Agentic chat can propose transfer/buy-sell/adjustment records (not just simple transactions) | None of Firefly III, Actual, GnuCash, YNAB, or Wallet have a conversational agent that can draft a paired transfer or a buy/sell event for confirmation. This extends monai's existing confirm-before-write agent to the new atomic multi-leg record types. | MEDIUM–HIGH | Depends on transfer/buy-sell writes existing as tools in the `TOOLS` registry first. Per project memory (`chat-tool-dual-registration`), any new write tool must be registered in BOTH `tools.py` TOOLS and `query.py`'s FunctionTool list — the LLM only sees the latter. Multi-leg atomicity makes the "propose" JSON shape more complex than existing single-row proposals. |
| Single trustworthy dashboard showing liquids + investments never double-counted, with natural-language explanation on demand | Reference apps show net worth as a static number; monai can let the user *ask* "why did net worth change this week" and get a tool-routed, honest answer chaining existing spending/portfolio tools. | LOW (mostly recombining existing chat tools) | Builds on already-shipped CHAT-03 (spending↔portfolio correlation). |
| Records ledger with transfer pairs visually distinguished + bulk actions in one date-grouped list | BudgetBakers Wallet has date-grouped records with daily nets; monai's plan matches this but adds bulk actions (not clearly documented as a Wallet feature). | MEDIUM | UI/interaction work, not a data-model risk. |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|------------------|-------------|
| Live/automatic FX rate lookup forced on every cross-currency transfer entry | Feels more "accurate" than manual entry | Real transfers happen at whatever rate the bank/exchange actually applied — forcing a live API rate creates a number that doesn't match reality, violating monai's "never fabricate a number" principle. Firefly III deliberately lets the manual foreign-amount override the calculated one for this reason. | Default the destination-amount field to a fetched/cached rate for convenience, but always let the user overwrite it before saving (matches the existing FX-cache-for-valuation vs entry-time-FX split already decided in PROJECT.md). |
| Auto-detecting transfers from expense/income pairs (like BudgetBakers' bank-sync heuristic matching) | Reduces manual entry | monai has no bank sync (explicitly out of scope). This heuristic only exists in Wallet because it ingests live bank feeds. Building transfer-auto-detection for CSV-imported/manually-entered data risks false-positive merges (two unrelated same-amount transactions on the same day). | Transfers are always explicitly created via the Transfer segment of the record modal — never inferred. |
| Hard-delete a category that's in use, silently leaving orphaned/NULL category_id on old records | Feels like the simplest implementation | Orphaned records lose meaning in reports/charts, and the AI chat's category tools would silently degrade (a spend total "by category" would drop transactions with no warning) — collides with the never-fabricate principle. | Block-or-reassign pattern (see Behavior Specifics) — pick whichever, but never silent orphan. |
| Free-text/arbitrary-depth category nesting (4+ levels) | "More flexibility" | PROJECT.md and the reference product both cap at 3 levels; deeper trees make the management UI and the AI's category tools (already built, expects flat/shallow lookups) meaningfully harder for a single-user app that doesn't need it. | Hard-cap at 3 levels as scoped. |
| Multi-entry double-entry bookkeeping exposed to the user (raw debit/credit ledger, GnuCash-style) | "More correct/powerful" | GnuCash's full double-entry UI is a well-known adoption barrier for non-accountants — Firefly III explicitly notes it is "not double-entry accounting" in the traditional sense specifically to stay approachable. monai is single-user, casual bookkeeping, not GAAP compliance. | Keep the paired-record model as an internal implementation detail; the user-facing UI always shows one human-readable "Transfer" or "Buy" row, never raw debit/credit splits. |

## Feature Dependencies

```
accounts.type discriminator (liquid/investment)
    └──requires──> Main dashboard net-worth (single-counted)

Account manager (liquid accounts CRUD)
    └──requires──> Balance-adjustment records (adjustment needs an account to adjust)
    └──enables──> Records tab (date-grouped ledger needs accounts to group/filter by)

Record input modal (Expense/Income/Transfer)
    └──requires──> Transfer pair data model (linked records, transfer_group_id)
    └──enables──> Records tab bulk actions on transfer pairs

Categories as first-class entities (3-level hierarchy)
    └──requires──> migration from free-string category column
    └──enables──> Record input modal category picker
    └──enables──> Category management UI (Settings)
    └──must-precede──> category delete/reassign behavior (must exist before delete UI ships)

Platform manager (investment side)
    └──mirrors──> Account manager (same CRUD pattern, explicitly stated in PROJECT.md)

Liquid→investment transfer (paired, dual-amount cross-currency)
    └──requires──> Transfer pair data model
    └──requires──> Account manager + Platform manager (both endpoints must exist)
    └──requires──> Cross-currency dual-amount entry pattern

Buy/sell events with liquid source/destination
    └──requires──> Account manager (liquid leg)
    └──requires──> existing holdings/portfolio_events tables (investment leg, already shipped)
    └──requires──> atomic multi-table write (liquid record + portfolio_event in one transaction)

USD→IDR entry-time FX
    └──enhances──> Buy/sell events (native-currency cost basis, already decided in v1.0)
    └──enhances──> Liquid→investment transfers (dual-amount)

Agentic chat proposals for transfer/buy-sell/adjustment
    └──requires──> all of the above write paths existing as tools first (registry pattern)
```

### Dependency Notes

- **Net-worth dashboard requires `accounts.type`:** this is the single schema change that fixes the double-count; it should land before or alongside the dashboard phase, not after — building the dashboard against the old ambiguous model just recreates the bug.
- **Balance-adjustment requires Account manager:** an adjustment record is meaningless without an account to attach the delta to; account manager (add/edit/remove accounts) is a hard prerequisite, not just related work.
- **Categories-as-first-class must land before category management UI and before record-input category picker:** the migration off the free-string `category` column is the riskiest single piece of this milestone (touches every existing transaction row) and should be sequenced early, isolated from feature work that depends on it.
- **Buy/sell atomic write requires both Account manager and the existing holdings/portfolio_events tables:** this is a cross-subsystem write (liquid + investment) — the atomicity requirement (single DB transaction, single confirmation) means it should be planned as one unit of work, not split across a "liquids phase" and an "investments phase" that ship independently.
- **Transfer pair data model is shared infrastructure:** both liquid↔liquid transfers and liquid↔investment transfers use it. Build the linked-pair mechanism once, generically, rather than as two separate implementations.
- **Chat/MCP write-tool registration is a known trap** (project memory: `chat-tool-dual-registration`): every new write path (transfer, adjustment, buy/sell) needs registration in both `tools.py` TOOLS and `query.py`'s FunctionTool list, or the LLM silently can't see it despite the HTTP endpoint working. Also relevant: `TOOLS registry mutates to 26` memory — any read-only surface (e.g. MCP) must iterate a `READ_TOOL_NAMES` allowlist, not raw `TOOLS`, once new propose_* write tools are added for these features.

## Behavior Specifics (Quality Gate Answers)

### What happens to records when a category is deleted?

Two validated patterns exist across reference apps; recommend the **BudgetBakers-matching block-until-reassigned** pattern since Wallet is the explicit reference product and monai already leans toward "never fabricate/never silently mutate":

1. **Block-and-require-reassignment (Wallet's pattern, recommended):** Deletion is refused (422-style error, matching monai's existing `ValueError → HTTPException(422)` convention) while any record still references the category (or its children). UI surfaces "N records use this category" and offers a bulk-reassign action (pick a replacement category, matching Actual Budget's inline reassignment prompt) before allowing delete.
2. **Alternative — inline reassign-on-delete (Actual Budget's pattern):** Delete UI always asks "move N affected records to which category?" as part of the delete flow itself, never a two-step block.

Either is acceptable; **do not** silently null out `category_id` on delete (the anti-feature above) — that breaks category-based spend totals invisibly, which the AI chat tools would then report as if categories were simply absent, contradicting the never-fabricate principle.

**Sub-category delete:** if a leaf (3rd-level) category is deleted, records should offer reassignment to the immediate parent as the default suggested target, not force picking a brand-new leaf. **Mid-level category delete** (has children) should either cascade the block to include all descendant categories' records, or require the user to delete/reassign children first — do not allow deleting a category that still has live child categories.

### How do transfer pairs stay in sync on edit?

- Store as **two DB rows sharing a `transfer_group_id`** (Firefly III's paired-transaction pattern, adapted to monai's existing single-`records`-table style rather than introducing a separate journal abstraction).
- Any edit to amount, date, or either account must be applied as **one DB transaction that updates/validates both rows together** — never expose an edit UI that lets you change only one leg's amount without updating the other (this is exactly the Actual Budget bug found in research: splitting one side of a transfer desyncs the pair).
- **Deleting a transfer deletes both legs** in one transaction; there is no supported "delete only one side" action — offer "delete transfer" as a single action on the paired row in the UI, not two separate delete buttons.
- **Cross-currency transfers store both amounts** (source-currency amount on the source leg, destination-currency amount on the destination leg) plus the implied rate for reference — editing one amount should prompt (not silently auto-recompute) whether to also update the other, since the rate was a point-in-time manual entry, not a live formula.

### How does buy/sell stay atomic with the funding account?

- One user confirmation → one DB transaction writing both: (a) a `records` row on the chosen liquid account (debit for buy, credit for sell) and (b) the existing `portfolio_events` row + `holdings` quantity update.
- If either write fails, roll back both — a partial buy/sell (holding updated but cash not debited, or vice versa) is a correctness bug in a money app, matching GnuCash's requirement that share purchases always have a matching cash-account leg.
- Net proceeds on sell = gross sale value minus any fees, mirroring GnuCash's commission-handling convention — if monai tracks fees on portfolio_events already, reuse that field for the cash-leg net amount rather than introducing a second fee concept.

## MVP Definition

### Launch With (v1.2, per PROJECT.md scope)

- [ ] `accounts.type` liquid/investment discriminator — fixes double-count, everything else depends on it
- [ ] Account manager (liquid CRUD) + balance-adjustment records
- [ ] Records tab (date-grouped, filters, transfer pairs shown as one row, bulk actions)
- [ ] Record input modal (Expense / Income / Transfer segmented)
- [ ] Platform manager (investment CRUD, mirrors account manager)
- [ ] Platform detail (PnL + buy/sell history)
- [ ] Liquid→investment transfers (paired, dual-amount cross-currency)
- [ ] Buy/sell atomic write (liquid leg + portfolio_event, one confirmation)
- [ ] USD→IDR entry-time FX (dual-amount + existing FX cache for valuation)
- [ ] Categories as first-class 3-level hierarchy + management UI + migration
- [ ] Category delete-reassignment guard (block-or-reassign, not silent orphan)

### Add After Validation (v1.x)

- [ ] Chat/MCP write-tool support for transfer/buy-sell/adjustment (extends existing confirm-before-write pattern to the new atomic multi-leg writes)
- [ ] Bulk transfer-pair actions beyond basic delete (e.g. bulk re-date, bulk re-account)

### Future Consideration (v2+)

- [ ] Recurring-charge/subscription detection (already deferred as QRY-01 in PROJECT.md)
- [ ] Automated reksadana NAV feed (already deferred as INVX-02)
- [ ] Bank sync / auto-transfer-detection — explicitly out of scope per PROJECT.md (PCI/aggregation scope)

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| `accounts.type` discriminator + net-worth dashboard | HIGH | LOW | P1 |
| Account manager + balance adjustments | HIGH | MEDIUM | P1 |
| Categories first-class + migration | HIGH | MEDIUM–HIGH | P1 |
| Records tab + record input modal | HIGH | MEDIUM | P1 |
| Transfer pair data model | HIGH | MEDIUM | P1 |
| Platform manager + platform detail | MEDIUM–HIGH | MEDIUM | P1 |
| Liquid→investment transfer (dual-amount) | HIGH | MEDIUM–HIGH | P1 |
| Buy/sell atomic write | HIGH | MEDIUM–HIGH | P1 |
| USD→IDR entry-time FX | MEDIUM | LOW–MEDIUM | P1 |
| Category delete/reassign UI | MEDIUM | LOW–MEDIUM | P1 (blocks category management UI otherwise being unsafe) |
| Chat proposals for new write types | MEDIUM | MEDIUM–HIGH | P2 |
| Bulk actions beyond delete | LOW–MEDIUM | LOW | P2 |

**Priority key:**
- P1: In scope for this milestone (all listed in PROJECT.md Active requirements)
- P2: Natural follow-on, not required for v1.2 to be complete

## Competitor Feature Analysis

| Feature | Firefly III | Actual Budget | GnuCash | YNAB | BudgetBakers Wallet (reference) | monai's approach |
|---------|--------------|----------------|---------|------|----------------------------------|-------------------|
| Transfer storage | Two Transaction rows under one TransactionJournal | Two linked transactions, auto-sync on edit | Two splits in one multi-split transaction | Two linked transactions | Single record with transfer flag/icon | Two rows sharing `transfer_group_id`, same style as Firefly/Actual |
| Balance adjustment | Named "reconciliation" transaction type, auto-created from statement-balance diff | Not clearly separated in docs found | Manual adjusting entry against Equity | Named "Reconciliation Balance Adjustment," auto-created | Manual balance edit (not explicitly documented as a ledger record) | First-class adjustment record type, explicit per PROJECT.md |
| Buy/sell cash linkage | N/A (not an investment-focused tool) | N/A | Explicit cash/brokerage leg required, lot-based cost basis | N/A | Investments feature exists but linkage mechanics undocumented publicly | Atomic buy/sell: liquid leg + portfolio_event in one transaction |
| Cross-currency transfer | Manual dual-amount ("foreign amount") override | Not a core focus (single-currency-oriented) | Manual, via currency-specific accounts + price entries | Not a core focus | Not clearly documented | Dual-amount entry (source + destination currency), matches Firefly's override pattern |
| Category hierarchy depth | Flat with some grouping | Groups + categories (2-level) | Unlimited (full account-tree reuse) | Category groups (2-level) | 3-level (category/subcategory/sub-subcategory) — explicit reference | 3-level, matches Wallet exactly (explicit reference, trimmed elsewhere) |
| Category delete safety | Not directly researched | Inline reassign prompt | N/A (accounts, not deletable while in use) | Not directly researched | Hard block until manually reassigned via filter | Recommend block-until-reassigned (matches reference product) |

## Sources

- [Firefly III — Transactions (financial concepts)](https://docs.firefly-iii.org/explanation/financial-concepts/transactions/)
- [Firefly III — Transaction Management (DeepWiki)](https://deepwiki.com/firefly-iii/firefly-iii/3.3-transaction-management)
- [Firefly III — How to reconcile accounts](https://docs.firefly-iii.org/how-to/firefly-iii/finances/reconcile/)
- [Firefly III — Exchange rates](https://docs.firefly-iii.org/explanation/financial-concepts/exchange-rates/)
- [Firefly III — How to use currencies](https://docs.firefly-iii.org/how-to/firefly-iii/features/currencies/)
- [Firefly III is not double-entry accounting — observations](https://www.kennethballard.com/?p=9483)
- [Actual Budget — Transfers](https://actualbudget.org/docs/transactions/transfers/)
- [Actual Budget — Split Transactions](https://actualbudget.org/docs/transactions/split-transactions/)
- [Actual Budget — Categories](https://actualbudget.org/docs/budgeting/categories/)
- [Actual Budget GitHub issue #5694 — split-transfer bug](https://github.com/actualbudget/actual/issues/5694)
- [GnuCash — Stock Transaction Assistant](https://wiki.gnucash.org/wiki/Stock_Transaction_Assistant)
- [GnuCash — Selling Shares](https://www.gnucash.org/docs/v5/C/gnucash-guide/invest-sell1.html)
- [GnuCash — Buying Shares](https://www.gnucash.org/docs/v3/C/gnucash-guide/invest-buy-stock1.html)
- [GnuCash — Capital Gains / lot management](https://www.gnucash.org/docs/v4/C/gnucash-guide/invest-sell1.html)
- [YNAB — Balance Adjustments: A Guide](https://support.ynab.com/en_us/balance-adjustments-a-guide-rko4OwILs)
- [YNAB — A Guide to Reconciling Accounts](https://support.ynab.com/en_us/reconciling-accounts-a-guide-BJFE3fHys)
- [BudgetBakers Wallet — All about Categories and Subcategories](https://support.budgetbakers.com/hc/en-us/articles/7077082048146-All-about-Categories-and-Subcategories)
- [BudgetBakers Wallet — Bank Transfers](https://support.budgetbakers.com/hc/en-us/articles/7148334559762-Bank-Transfers)
- [BudgetBakers Wallet — Everything About Transactions](https://support.budgetbakers.com/hc/en-us/articles/7149271363090-Everything-About-Transactions-Add-edit-clone-split-duplicates)
- [Beyond Budget — Groups and categories](https://www.beyondbudgetapp.com/basics/groups-and-categories)
- [Wealthtender — Best Net Worth Tracker Apps](https://wealthtender.com/insights/money-management/wealth-tracker-apps-and-websites-know-your-net-worth/)
- [Monarch — Expense & Net Worth Tracking](https://www.monarch.com/features/tracking)

---
*Feature research for: monai v1.2 Connected Ledger (liquids ↔ investments)*
*Researched: 2026-07-18*
