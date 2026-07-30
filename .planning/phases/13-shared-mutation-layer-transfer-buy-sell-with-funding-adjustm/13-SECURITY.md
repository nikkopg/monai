---
phase: 13
slug: shared-mutation-layer-transfer-buy-sell-with-funding-adjustm
status: verified
threats_open: 0
asvs_level: 1
created: 2026-07-30
---

# Phase 13 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.
> Shared mutation layer — transfer / funded buy+sell / investment-transfer / balance adjustment, plus retro-pairing migration.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| test harness → live Postgres | Tests write/read the shared live DB (no mock, no rollback fixture); an uncleaned test pollutes the shared account/transaction space (Phase 12 leftover-account problem). | Seeded accounts, transactions, events, holdings, audit rows |
| migration → live financial data | `011_retro_pair_transfers.upgrade()` mutates historical `transactions` rows on shared Postgres; a wrong/non-idempotent pass corrupts pairing state later read paths (Phase 17 REC-05) trust. | `transactions.transfer_pair_id` backfill |
| caller (Phase 14 confirm/endpoint) → writes.py | Untrusted amounts / account & platform names / currencies / target balances cross into the mutation layer; the layer must not commit and must tag transfer rows correctly. | Money amounts, names, currencies, quantities, prices |
| writes.py → Postgres | Multi-row writes whose atomicity depends entirely on the caller's single commit boundary (D-01). | Transaction + PortfolioEvent + holding rows |
| writes.py → portfolio.py | Holding math is delegated; a hand-rolled update here would silently diverge from the canonical position ledger. | Holding quantity / cost-basis recompute |

---

## Threat Register

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-13-01 | Tampering (partial write) | apply_add_transfer / funded buy+sell / investment-transfer | mitigate | Compose primitives, never commit (D-01); all legs persist under caller's single commit or none. `grep -c 'db.commit'` (comments excl.) = 0 (writes.py:150-266). | closed |
| T-13-02 | Tampering (orphaned leg) | apply_edit / apply_delete_transaction | mitigate | `allow_paired` guard raises ValueError on single-leg edit/delete of a paired row (writes.py:117-121, 140-144, D-04). | closed |
| T-13-03 | Tampering (silent balance error) | balance-adjustment delta | mitigate | Fresh UNFILTERED `SUM(amount)` scoped to the new fn (writes.py:92-95), distinct from `tools.py:account_balances`'s is_transfer filter; transfer-seeded delta test fails RED under a filtered SUM. | closed |
| T-13-04 | Tampering / DoS (backfill) | migration 011 upgrade() | mitigate | Non-destructive (sets previously-NULL column only); `WHERE transfer_pair_id IS NULL` re-run no-op; Alembic single-transaction rollback (011:57-76). | closed |
| T-13-05 | Tampering (money fields) | delta / amount / price fields | mitigate | `Decimal(str(x))` before every `Decimal()`; 14 occurrences incl. new delta calc (writes.py:62,96,128). | closed |
| T-13-06 | Tampering (raw SQL) | candidate-match / SUM / UPDATE SQL | mitigate | Bound `:param` `text()` only; no f-string/`%` SQL in writes.py, migration, or tests. | closed |
| T-13-07 | Repudiation (double-count leak) | transfer / cash / adjustment legs | mitigate | Every non-spending leg forces `is_transfer=True` **inside the layer** (writes.py:105,163-164,187,217,251), independent of caller input — apply_add_investment_transfer hardened this audit (was caller-dependent) to mirror its 3 siblings; excluded from spending/income/net totals. | closed |
| T-13-08 | Tampering (test data leak) | new tests writing to shared live DB | mitigate | Unique seed prefixes (`zz13test-`, `zzRetroPairTest`) + `finally` cleanup in all 12 new tests; never reuses real account names. | closed |
| T-13-09 | Tampering (incorrect pairing) | migration ambiguous-match | mitigate | Mutual `touch_count==1` COUNT(*)-per-row guard before UPDATE (011:79-110); no blind `LIMIT 1`; multiple-candidate branch unit-tested. | closed |
| T-13-10 | Tampering (id drift) | account / platform resolution | mitigate | Purely relational match / resolved by name via `_get_or_create_account` at runtime; zero hard-coded account ids (Finding 1). | closed |
| T-13-11 | Tampering (double-count via synthetic account) | investment money as accounts row | mitigate | Investment side is ALWAYS a PortfolioEvent linked via `source_account_id`, never a new Account (D-05); test asserts account count unchanged. | closed |
| T-13-12 | Tampering (position corruption) | holding update | mitigate | `recompute_holding_from_events` is the sole updater (writes.py:459 via apply_add_portfolio_event, D-06); no hand-rolled holding math. | closed |
| T-13-13 | Tampering (FX fabrication) | cross-currency valuation | mitigate | No write path calls a live FX rate (D-10); currencies stored as given; zero `get_rate`/`fx.` refs in writes.py. | closed |
| T-13-14 | Tampering (stored-balance drift) | balance persistence | mitigate | No stored `balance` column on `Account` (models.py) — balance stays derived (D-07); only the adjustment Transaction row is persisted. | closed |
| T-13-SC | Tampering (supply chain) | npm/pip/cargo installs | accept | No packages installed this phase; pytest/sqlalchemy/alembic already pinned (see Accepted Risks Log). | closed |

*Status: open · closed*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-13-01 | T-13-SC | No new dependencies added this phase; migration and writes.py reuse the already-pinned `sqlalchemy`/`alembic`/`pytest` imports (001–010 precedent). Supply-chain surface unchanged. | nikkopg | 2026-07-30 |

*Accepted risks do not resurface in future audit runs.*

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-07-30 | 15 | 14 | 1 | gsd-security-auditor (initial verify — T-13-07 open) |
| 2026-07-30 | 15 | 15 | 0 | writes.py:187 hardened (force is_transfer=True) + re-verify; 54 tests pass |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-07-30
