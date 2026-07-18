---
phase: 11
slug: category-hierarchy-schema-audit-migration
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-18
---

# Phase 11 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest >=8.0.0 (backend) / `tsc --noEmit` (ui) |
| **Config file** | backend/tests/ (existing suite) |
| **Quick run command** | `uv run --with-requirements backend/requirements.txt pytest backend/tests -x -q` |
| **Full suite command** | `uv run --with-requirements backend/requirements.txt pytest backend/tests -q && (cd ui && npx tsc --noEmit)` |
| **Estimated runtime** | ~60 seconds |

---

## Sampling Rate

- **After every task commit:** Run the quick run command
- **After every plan wave:** Run the full suite command
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 90 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 11-01-01 | 01 | 1 | CAT-01 | — | N/A | unit | `pytest backend/tests -x -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*
*(Planner fills the full map per task.)*

---

## Wave 0 Requirements

- [ ] `backend/tests/test_categories.py` — stubs for CAT-01/CAT-02 (tree CRUD, delete guards)
- [ ] Migration parity assertions live inside the Alembic migration itself (abort-on-unknown, row/sum parity) — CAT-03

*Existing pytest infrastructure covers the rest.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 74-string mapping review | CAT-03 | Human-judgment task by design (execution checkpoint) | Review drafted mapping CSV; edit; approve before migration runs |
| Settings tree UI look/feel | CAT-02 | Visual | Open Settings > Categories; expand/collapse, add/edit/delete |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
