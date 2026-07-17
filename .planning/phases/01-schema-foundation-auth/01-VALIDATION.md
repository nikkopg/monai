---
phase: 1
slug: schema-foundation-auth
status: validated
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-21
validated: 2026-07-17
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest >=8.0.0 (already a dependency) + httpx for API client tests |
| **Config file** | none yet — Wave 0 adds `backend/tests/conftest.py` |
| **Quick run command** | `cd backend && python -m pytest -q` |
| **Full suite command** | `cd backend && python -m pytest` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `cd backend && python -m pytest -q`
- **After every plan wave:** Run `cd backend && python -m pytest`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

> Populated by the planner / nyquist auditor once PLAN.md tasks exist.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| — | 01-01 | — | FND-01 (schema presence) | — | New tables bootstrap on a fresh DB; whole suite depends on them | infra/smoke | `pytest backend/tests -q` (191 collected — none run without the schema) | ✅ conftest.py | ✅ green |
| — | 01-03 | — | FND-02 | — | Missing/wrong key on write paths → 401; empty configured key → 503 | integration | `pytest backend/tests/test_auth.py -q` | ✅ test_auth.py | ✅ green (8) |
| — | 01-02 | — | FND-03 | — | Decimal round-trips as JSON number; non-numeric rejected | unit | `pytest backend/tests/test_decimal.py -q` | ✅ test_decimal.py | ✅ green (5) |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*
*FND-01 data-preservation on a populated volume is verified manually (see Manual-Only) — the automatable half (schema presence on a fresh DB) is proven by the conftest bootstrap.*

---

## Wave 0 Requirements

- [ ] `backend/tests/conftest.py` — shared fixtures (DB session, test client, API key)
- [ ] `backend/tests/` — test package init
- [ ] pytest already installed; add `httpx` for FastAPI TestClient/async client

*Filled in detail by the planner during PLAN.md creation.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `alembic upgrade head` is non-destructive on the live `monai_pgdata` volume | FND-01 | Requires a real existing volume with 5,609 transactions; cannot be fully simulated in unit tests | Run against a copy of the prod volume; confirm row counts unchanged + new tables present |

*Automated coverage handles the rest (auth 401s, Decimal round-trip, schema presence on a fresh DB).*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** validated 2026-07-17

---

## Validation Audit 2026-07-17

Retroactive audit (`/gsd-validate-phase 1`). State A. Full suite: **191 passed, 0 failed, 0 skipped** (DB up).

| Metric | Count |
|--------|-------|
| Requirements audited | 3 (FND-01/02/03) |
| Gaps found | 0 |
| Resolved (test generated) | 0 |
| Escalated to manual-only | 0 |

FND-02→`test_auth.py`, FND-03→`test_decimal.py` — both green. FND-01 schema presence proven implicitly by the conftest bootstrap; data-preservation on the live volume remains the one documented manual-only check.
