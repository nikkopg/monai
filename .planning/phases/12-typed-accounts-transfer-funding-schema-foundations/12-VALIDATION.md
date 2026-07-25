---
phase: 12
slug: typed-accounts-transfer-funding-schema-foundations
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-25
---

# Phase 12 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest >=8.0.0 (present; no install needed) |
| **Config file** | none dedicated; tests in `backend/tests/`, run against the LIVE dev DB (conftest.py assumes migrations applied — no fresh-migrate fixture) |
| **Quick run command** | `python -m pytest backend/tests/test_typed_accounts.py backend/tests/test_cashflow_view.py -x` |
| **Full suite command** | `python -m pytest backend/tests/` |
| **Estimated runtime** | ~10–20 seconds |

---

## Sampling Rate

- **After every task commit:** Run the quick run command (scoped to the plan's node ids).
- **After every plan wave:** Run `python -m pytest backend/tests/` (catches any cashflow tool whose SQL was not switched).
- **Before `/gsd:verify-work`:** Full suite green + `docker compose up -d --build` then a manual `spending_total`/`net_total` API check showing the ~45.9M gone.
- **Max feedback latency:** ~20 seconds.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 12-01-01 | 01 | 1 | ACCT-03 | T-12-01 | Classification + CHECK/default + pairing introspection encoded as named RED tests | unit+DB | `python -m pytest backend/tests/test_typed_accounts.py --co -q` | ❌ W0 (this task creates it) | ⬜ pending |
| 12-01-02 | 01 | 1 | ACCT-03 | T-12-02 | View invariants (exclude/keep-NULL/delta) + tools-level exclusion encoded as named RED tests | DB | `python -m pytest backend/tests/test_cashflow_view.py --co -q` | ❌ W0 (this task creates it) | ⬜ pending |
| 12-02-01 | 02 | 2 | ACCT-03 | T-12-01, T-12-03 | Backfill matches D-02, zero NULL, abort-loudly on drift, idempotent guarded DDL, NOT EXISTS view keeps NULL-account rows | unit+DB | `alembic upgrade head && python -m pytest backend/tests/test_typed_accounts.py backend/tests/test_cashflow_view.py::test_view_excludes_investment backend/tests/test_cashflow_view.py::test_view_keeps_null_account backend/tests/test_cashflow_view.py::test_double_count_delta -x` | ✅ (12-01) | ⬜ pending |
| 12-02-02 | 02 | 2 | ACCT-03 | T-12-01 | ORM mirrors DB (type NOT NULL + server_default; both pairing columns mapped) | unit | `python -c "import backend.models as m; assert m.Account.type.nullable is False"` | ✅ (12-01) | ⬜ pending |
| 12-03-01 | 03 | 3 | ACCT-03 | T-12-02, T-12-04 | Nine cashflow totals read the view; LEAVE-sites unchanged; tools.spending_total excludes investment | DB | `python -m pytest backend/tests/test_cashflow_view.py::test_tools_spending_excludes_investment backend/tests/ -x` | ✅ (12-01) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `backend/tests/test_typed_accounts.py` — Criterion 1 (D-02 classification, zero NULL), CHECK+default enforcement, Criterion 3 pairing-column introspection, ACCT-03 (created by 12-01-01).
- [ ] `backend/tests/test_cashflow_view.py` — Criterion 2 view invariants (exclude investment / keep NULL-account_id / raw−view==investment delta) + tools-level spending_total exclusion, ACCT-03 (created by 12-01-02).
- Shared fixtures: reuse existing `backend/tests/conftest.py` engine/session (no new fixture, no framework install).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live API cashflow reflects the fix | ACCT-03 (Crit. 2) | Committed code ≠ running container; the API must serve the rebuilt image to prove end-to-end (memory: "Deploy requires rebuild") | `docker compose up -d --build`; call the cashflow summary endpoint; confirm spending_total/net_total no longer include the ~45.9M "Investments" phantom. Automated tests already prove it at the DB/tools layer. |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (both test files created in Wave 1 / Plan 01)
- [x] No watch-mode flags
- [x] Feedback latency < 20s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-07-25
