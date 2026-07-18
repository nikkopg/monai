# Requirements: monai v1.2 — Connected Ledger (Liquids ↔ Investments)

**Defined:** 2026-07-18
**Core Value:** You can understand and manage your entire financial life — spending and investments — by talking to a trustworthy AI that never fabricates a number and never changes your data without your say-so.

**Reference:** BudgetBakers Wallet web app (dashboard, Records tab, Add-record modal, Settings > Categories) — captured live 2026-07-18. Deliberately trimmed: templates, payer, payment type/status.

## v1.2 Requirements

Requirements for this milestone. Each maps to roadmap phases.

### Dashboard (NW)

- [ ] **NW-01**: User sees a main dashboard where net worth = liquid accounts + investment platforms, each counted exactly once
- [ ] **NW-02**: User sees the liquid vs investment split with per-side breakdowns on the dashboard

### Accounts (ACCT)

- [ ] **ACCT-01**: User can add, edit, and remove liquid accounts in a dedicated account manager
- [ ] **ACCT-02**: User can set an account's balance; the delta is stored as a visible "Adjustment" record (balances stay derived, never a stored field)
- [ ] **ACCT-03**: Accounts are typed liquid/investment (DB-enforced after live audit + backfill); investment-typed accounts are excluded from cashflow totals — the double-count fix

### Records (REC)

- [ ] **REC-01**: User can browse all records in a date-grouped ledger with a daily net per group
- [ ] **REC-02**: User can filter records by search, account, category, record type, amount range, and transfer visibility
- [ ] **REC-03**: User can select multiple records and bulk delete or bulk recategorize
- [ ] **REC-04**: User can add a record via a modal with Expense / Income / Transfer segmented form (amount + currency, account, category picker, date-time, note; "add another")
- [ ] **REC-05**: Transfer pairs display as one logical unit; editing or deleting affects both legs atomically (single-leg edits blocked)

### Categories (CAT)

- [ ] **CAT-01**: Categories are first-class entities (name, color, icon, parent) with up to 3 hierarchy levels
- [ ] **CAT-02**: User can manage categories in Settings — add, edit, delete with a block-or-reassign guard (no orphaned records)
- [ ] **CAT-03**: The 74 existing category strings migrate onto the hierarchy via a human-reviewed mapping with row/sum parity checks; destructive column drop is a separate later migration
- [ ] **CAT-04**: Record forms, filters, and dashboard charts use the hierarchical category picker

### Platforms (PLAT)

- [ ] **PLAT-01**: User can open a platform detail view with a PnL tab and a buy/sell history tab
- [ ] **PLAT-02**: Platform manager reaches CRUD parity with the account manager (extends existing `PlatformManager.tsx`)

### Connection layer (XFER)

- [ ] **XFER-01**: User can transfer between liquid accounts; stored as paired records via `transfer_pair_id`
- [ ] **XFER-02**: User can transfer liquid → investment platform (transaction linked to a portfolio deposit event via `source_account_id`)
- [ ] **XFER-03**: Buy/sell requires choosing a liquid source/destination account; one confirmation writes both entries in one DB transaction
- [ ] **XFER-04**: Cross-currency entry uses dual amounts (sent + received, each with currency); USD assets valued in IDR via existing FX cache
- [ ] **XFER-05**: Historical imported transfer rows are retro-paired by migration (matched by date+amount; unmatched flagged, left as-is)

### Chat (CHAT — continues v1.0 numbering)

- [ ] **CHAT-09**: User can perform the new operations (records, transfers, funded buy/sell, category changes) via chat with the existing confirm-before-write flow; new write tools registered on the agent and kept off the MCP read-only surface

## Future Requirements

Deferred. Tracked but not in current roadmap.

### Records

- **REC-F1**: Labels on records — free-form multi-tags separate from categories (declined for v1.2; keeps record modal simple)

### Categories

- **CAT-F1**: Nature-of-Spending (Need/Want) classification per category — would unlock "wants vs needs" chat queries
- **CAT-F2**: Hide toggle — hide a category from pickers/reports without deleting

### Carried from v1.x backlog

- **QRY-01**: Recurring-charge / subscription detection
- **QRY-02**: Compare two arbitrary periods side by side
- **QRY-03**: Token-by-token streaming of agent responses
- **INVX-02**: Automated reksadana NAV feed

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Record templates (Wallet feature) | Single-user YAGNI; "add and create another" covers repeat entry |
| Payer / payment type / payment status fields | Single-user YAGNI; note field suffices |
| Forced live-FX on cross-currency entry | Violates never-fabricate principle; manual dual-amount is authoritative (Firefly III "foreign amount" pattern) |
| Investment cash as an `accounts` row | Would reintroduce double-counting; investment cash lives in platforms/holdings |
| Free-form SQL from agent | Standing exclusion — confident-wrong-number risk |
| Write tools over MCP to external clients | Standing exclusion — writes stay in the web app |
| Multi-currency for *spending* records | IDR-only holds (0/5608 skipped); currency fields on records exist for transfer legs only |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| NW-01 | Phase 15 | Pending |
| NW-02 | Phase 15 | Pending |
| ACCT-01 | Phase 16 | Pending |
| ACCT-02 | Phase 13 | Pending |
| ACCT-03 | Phase 12 | Pending |
| REC-01 | Phase 17 | Pending |
| REC-02 | Phase 17 | Pending |
| REC-03 | Phase 17 | Pending |
| REC-04 | Phase 16 | Pending |
| REC-05 | Phase 17 | Pending |
| CAT-01 | Phase 11 | Pending |
| CAT-02 | Phase 11 | Pending |
| CAT-03 | Phase 11 | Pending |
| CAT-04 | Phase 11 | Pending |
| PLAT-01 | Phase 17 | Pending |
| PLAT-02 | Phase 16 | Pending |
| XFER-01 | Phase 13 | Pending |
| XFER-02 | Phase 13 | Pending |
| XFER-03 | Phase 13 | Pending |
| XFER-04 | Phase 13 | Pending |
| XFER-05 | Phase 13 | Pending |
| CHAT-09 | Phase 14 | Pending |

**Coverage:**
- v1.2 requirements: 22 total
- Mapped to phases: 22
- Unmapped: 0 ✓ (roadmap: Phases 11-17)

---
*Requirements defined: 2026-07-18*
*Last updated: 2026-07-18 after v1.2 roadmap creation (Phases 11-17, 20/20 mapped)*
