---
phase: 1
slug: schema-foundation-auth
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-21
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
| TBD | — | — | FND-01/02/03 | — | — | — | — | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

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

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
