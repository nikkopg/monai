---
slug: missing-investments-account
created: 2026-08-17
type: data_integrity
severity: high
found_during: Phase 18 regression gate
---

# Live DB has zero investment accounts

`backend/tests/test_typed_accounts.py::test_account_classification` fails:
`expected exactly one investment account, got []`.

## Evidence

Live `accounts` table (2026-08-17) — 8 rows, all `type='liquid'`:
`1 Cash`, `2 BCA`, `559 Stockbit`, `2307 ResolveAddDualAcct`, `2308 ResolveAddNoneAcct`,
`2309 ResolveEditAcct`, `2312 zzscopetest-account`, `2320 ZZ Test BCA`.

Audit trail for the account (`audit_log where entity='account'`):
- `3477` 2026-07-25 12:39 — `delete` of `{"id": 3, "name": "Investments", "type": "investment"}`
- `3478` 2026-07-25 13:00 — `restore` as id **994**, context: "revert accidental delete of
  account id 3 Investments (audit 3477); 122 txns had been bulk-reassigned to BCA (id 2)"
- **no delete row for 994 exists** — it vanished outside the audited write path.

`holdings` = 14 rows, `portfolio_events` = 3 rows, `transactions where account_id=994` = 0.

## Why it matters

`accounts.type` is a DB-enforced discriminator (Phase 12, D-02). With no `type='investment'`
row, the Phase 15 net-worth liquid/investment split is misclassifying real money, and the
Phase 12 reconciliation invariant is broken.

## Not caused by Phase 18

Phase 18 changed 8 files, all under `ui/` (no backend, no migration). No test deletes
accounts. The test reads live Postgres and fails identically at the phase base commit
`3306eba`.

## Open questions

1. How did 994 get deleted with no `audit_log` entry? Either an unaudited delete path exists
   (a real bug — account deletes ARE otherwise audited, cf. audit 6181) or it was removed by
   direct SQL / a migration.
2. Should 994 be restored, or re-created with a fresh id? The previously-reassigned 122
   transactions are still on BCA (id 2).
3. Secondary cleanup: ids 2307–2320 are leftover e2e/test accounts polluting production data.
