---
phase: 11
slug: category-hierarchy-schema-audit-migration
status: planned
nyquist_compliant: true
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
| 11-01-01 | 01 | 1 | CAT-03 | T-11-02 | load_mapping rejects empty/unknown rows | unit (RED) | `pytest backend/tests/test_category_migration.py -q` | ❌ created by task | ⬜ pending |
| 11-01-02 | 01 | 1 | CAT-01, CAT-03 | T-11-01, T-11-03 | bound-param backfill; abort-on-unknown; parity assert | unit (GREEN) + full suite | `pytest backend/tests/test_category_migration.py backend/tests -q` | ❌ created in 11-01-01 | ⬜ pending |
| 11-02-01 | 02 | 2 | CAT-03 | T-11-06 | 74/74 exact-key CSV coverage vs live DB | scripted CLI | python coverage one-liner (see plan) | n/a (CSV artifact) | ⬜ pending |
| 11-02-02 | 02 | 2 | CAT-03 | — | human mapping review (D-06) | manual checkpoint | none — blocking human gate | n/a | ⬜ pending |
| 11-02-03 | 02 | 2 | CAT-03 | T-11-05 | parity + idempotency + zero-NULL psql assertions | migration/integration | psql boolean check (see plan) | n/a (live DB) | ⬜ pending |
| 11-03-01 | 03 | 3 | CAT-01, CAT-02 | T-11-10 | depth cap, child-aware delete guard, system locks | unit (RED) | `pytest backend/tests/test_category_hierarchy.py -q` | ❌ created by task | ⬜ pending |
| 11-03-02 | 03 | 3 | CAT-01, CAT-02 | T-11-08..12 | require_api_key + reset_engine on all mutations | unit (GREEN) + full suite | `pytest backend/tests/test_category_hierarchy.py backend/tests/test_category_management.py -q` | ❌/✅ (new + modify) | ⬜ pending |
| 11-04-01 | 04 | 3 | CAT-04 | T-11-16 | Transfer/system exclusion in rollup | unit (RED) | `pytest backend/tests/test_tools.py -k category -q` | ✅ extend | ⬜ pending |
| 11-04-02 | 04 | 3 | CAT-04 | T-11-13, T-11-14 | propose_* off READ_TOOL_NAMES; params bound | unit (GREEN) + registry assert | pytest + python registry check (see plan) | ✅ extend | ⬜ pending |
| 11-05-01 | 05 | 4 | CAT-03 | T-11-17, T-11-18 | Uncategorized fallback, never NULL/raise | unit (tdd) | `pytest backend/tests/test_category_hierarchy.py -k resolve -q` | ✅ extend | ⬜ pending |
| 11-05-02 | 05 | 4 | CAT-03 | T-11-19 | import unknowns land visibly in Uncategorized | integration probe | full suite + import probe script (see plan) | ✅ | ⬜ pending |
| 11-06-01 | 06 | 4 | CAT-02 | — | N/A (tokens) | typecheck | `cd ui && npx tsc --noEmit` | ✅ | ⬜ pending |
| 11-06-02 | 06 | 4 | CAT-02 | T-11-20, T-11-21 | text-node rendering; confirm dialogs | typecheck + source assertions | `cd ui && npx tsc --noEmit` | ❌ created by task | ⬜ pending |
| 11-06-03 | 06 | 4 | CAT-02, CAT-04 | — | N/A (wiring) | typecheck + grep gate | tsc + move-complete check (see plan) | ✅ | ⬜ pending |
| 11-07-01 | 07 | 5 | CAT-04 | T-11-23 | no Transfer entry in summary response | unit (tdd) | `pytest backend/tests/test_cashflow_summary.py -q` | ✅ extend | ⬜ pending |
| 11-07-02 | 07 | 5 | CAT-04 | T-11-24 | text-node rendering in chart | typecheck | `cd ui && npx tsc --noEmit` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Wave 0 is satisfied by the TDD plans' RED tasks (tests written before implementation):

- [ ] `backend/tests/test_category_migration.py` — mapping load, abort-on-unknown, parity (CAT-03) — plan 11-01 Task 1 (RED)
- [ ] `backend/tests/test_category_hierarchy.py` — tree CRUD, depth cap, delete guards incl. child case (CAT-01/CAT-02) — plan 11-03 Task 1 (RED)
- [ ] Migration parity assertions live inside revision 009 itself (abort-on-unknown, row/sum parity) — CAT-03, plan 11-01 Task 2

*Existing pytest infrastructure covers the rest (test_tools.py and test_cashflow_summary.py are extended in place).*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 74-string mapping review | CAT-03 | Human-judgment task by design (execution checkpoint) | Review drafted mapping CSV; edit; approve before migration runs |
| Settings tree UI look/feel | CAT-02 | Visual | Open Settings > Categories; expand/collapse, add/edit/delete |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies (sole exception: 11-02-02, the D-06 human checkpoint — manual by design)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (RED tasks in plans 11-01 and 11-03)
- [x] No watch-mode flags
- [x] Feedback latency < 90s (quick suite ~60s)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** planned 2026-07-19 by gsd-planner
