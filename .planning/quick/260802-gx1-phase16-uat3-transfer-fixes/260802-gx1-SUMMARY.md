---
quick_id: 260802-gx1
slug: phase16-uat3-transfer-fixes
date: 2026-08-02
status: complete
commit: 3ffe59a
---

# Quick Task 260802-gx1 — Summary

Fixed two Phase 16 UAT #3 transfer defects, both from `is_transfer=true` being
conflated with "ignore for balance". Changes were implemented and tested before
this quick task was formalized (single code commit `3ffe59a`).

## What changed

- **`backend/tools.py` — `account_balances`:** `current_balance` now sums ALL
  of an account's transactions (transfers included). The `is_transfer = false`
  filter moved from the JOIN into the `period_net` FILTER only. Fixes flat
  liquid balances after a transfer, hidden balance-adjustments, and net-worth
  overstatement after liquid→investment funding transfers.
- **`backend/writes.py`:** added `apply_delete_transaction_or_pair` (+
  `_transaction_snapshot`) — deletes both legs of a transfer via the guarded
  primitive with `allow_paired=True`, one audit row per leg. The D-04 primitive
  and its guard test are unchanged.
- **`backend/main.py`:** `delete_transaction` (REST) and
  `_execute_proposal_payload` (agent) both route deletes through the new
  wrapper; endpoint now returns `deleted_ids`.
- **`backend/tests/test_write_tools.py`:** added
  `test_delete_transaction_or_pair_removes_both_legs`.

## Verification

- Targeted suites: `test_write_tools.py`, `test_transfer_retro_pairing.py`,
  `test_cashflow_summary.py` — 56 passed.
- Full backend suite — 279 passed, 2 failed. Both failures pre-existing and
  unrelated: `test_put_settings_requires_key` (known settings-503) and
  `test_account_classification` (freshly-started `monai-db` volume lacks the
  seeded investment account). Neither touches transfer/balance/delete code.
- **Deploy note:** requires `docker compose up -d --build backend` before the
  running app reflects the fix; UAT #3 should be re-run live afterward.

## Deferred

Deleting the cash leg of a liquid→investment funding transfer does not cascade
to its PortfolioEvent (`transfer_pair_id` is None there). Flagged as a separate
follow-up task.
