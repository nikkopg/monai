---
phase: 05-investment-subsystem
plan: 02
subsystem: platform-crud
tags: [crud, audit-log, reassign-then-delete, fastapi, pydantic, nextjs, use-client, wave-2]
requires:
  - platforms table + Platform ORM model (05-01)
  - holdings.platform_id nullable FK (05-01)
provides:
  - apply_add_platform / apply_edit_platform / apply_delete_platform (audited write helpers)
  - PlatformCreate / PlatformUpdate / PlatformOut DTOs
  - GET/POST/PUT/DELETE /platforms REST routes (writes API-key guarded)
  - PlatformManager.tsx (inline edit + reassign-on-422 delete)
  - live "use client" /investments page hosting the platform manager
affects:
  - backend/writes.py
  - backend/schemas.py
  - backend/main.py
  - backend/tests/test_write_tools.py
  - ui/app/investments/page.tsx
tech-stack:
  added: []
  patterns:
    - Reassign-then-delete in one audited helper (holdings.platform_id UPDATE, not inline)
    - DTO-by-role (Create/Update/Out) mirroring Account
    - Write routes carry dependencies=[Depends(require_api_key)]; GET stays open
    - 422 detail={message, affected_count} shape consumed verbatim by the frontend
    - Phase-3 server skeleton grown to "use client" tracker (RESEARCH Pitfall 5)
key-files:
  created:
    - ui/app/investments/PlatformManager.tsx
  modified:
    - backend/writes.py
    - backend/schemas.py
    - backend/main.py
    - backend/tests/test_write_tools.py
    - ui/app/investments/page.tsx
decisions:
  - "apply_*_platform copies the account helpers verbatim with entity='platform'; reassigns holdings.platform_id"
  - "DELETE /platforms/{id} returns 422 detail.affected_count when holdings remain and no reassign target is given"
  - "reassign_to is an int query param used only in a parameterized UPDATE (T-05-02-INP)"
  - "GET /platforms is an open read; POST/PUT/DELETE require the MONAI_API_KEY header (T-05-02-AC)"
  - "Reassign-confirm dialog shows the richer UI-SPEC L145 copy (target + source names) below the select"
metrics:
  duration: ~40m
  completed: 2026-07-10
  tasks: 3
  files: 6
status: complete
---

# Phase 5 Plan 02: Platform CRUD Vertical Slice Summary

Platform-management vertical slice (D-12) landed end to end: three audited `apply_*_platform` write helpers, three platform DTOs, four REST routes (open GET + API-key-guarded POST/PUT/DELETE with reassign-then-delete), a `PlatformManager.tsx` mirroring the Phase-4 account manager, and the first real render of `/investments` as a `"use client"` page. A real user can now add/rename/delete platforms and reassign holdings on delete — the "buckets" every holding will attach to in Plan 03.

## What Was Built

- **backend/writes.py** — `apply_add_platform(db, after)` (inserts a `platforms` row, flushes, writes one `AuditLog(entity="platform", operation="add", before=None)`); `apply_edit_platform(db, platform_id, after, before)` (partial-update, one edit AuditLog); `apply_delete_platform(db, platform_id, before, reassign_to=None) -> int` — when `reassign_to` is set, runs a single parameterized `UPDATE holdings SET platform_id = :reassign_to WHERE platform_id = :pid`, records `{reassign_to, reassigned_count}` in the single delete AuditLog after-dict, then deletes the platform. Copies the account helpers verbatim; never self-commits (caller owns the transaction — D-16).
- **backend/schemas.py** — `PlatformCreate` (name: str, kind: str | None = None), `PlatformUpdate` (all-optional name/kind), `PlatformOut` (`ConfigDict(from_attributes=True)`; id, name, kind). DTO-by-role, mirroring the Account trio.
- **backend/main.py** — `GET /platforms` (open read, `list[PlatformOut]`, ordered by name); `POST /platforms` (201, `dependencies=[Depends(require_api_key)]`); `PUT /platforms/{platform_id}` (guarded, ValueError→422); `DELETE /platforms/{platform_id}` (guarded, `reassign_to: int | None` query param). DELETE counts dependent holdings; with holdings and no target → `HTTPException(422, detail={"message": f"{n} holdings use this platform — reassign or delete them first", "affected_count": n})`; with `reassign_to` → validates target then calls the audited helper. Each write commits + `reset_engine()`.
- **backend/tests/test_write_tools.py** — three new cases: `test_apply_add_platform_creates_row_and_audit` (row + exactly one platform AuditLog, operation="add", before=None), `test_apply_delete_platform_reassigns_holdings` (seed holding on A, delete A with reassign_to=B, assert holding now points at B and after-dict carries `reassigned_count`), `test_post_platforms_requires_api_key` (POST without key → 401, with `MONAI_API_KEY` header → 201 + row). Reuses the module `db_available`/`api_key` fixtures; each test self-cleans.
- **ui/app/investments/PlatformManager.tsx** — structural mirror of `AccountManager.tsx`: `editingId`/`editName` inline-edit state; add-row with a `name` input plus a smaller optional `kind` input (placeholder "e.g. brokerage, crypto app"); Edit/Delete text-links; delete via `ConfirmDialog` imported from `../cashflow/ConfirmDialog`; on 422 reads `detail.affected_count`, swaps to a destination-platform `<select>` and re-issues `DELETE /api/platforms/{id}?reassign_to=${targetId}`. `extractDetail(r)` copied verbatim. Kind shown as a muted suffix on each row; empty-state copy per UI-SPEC.
- **ui/app/investments/page.tsx** — converted from the Phase-3 server skeleton to `"use client"`: fetches `GET /api/platforms`, renders the "Investments" heading (28px/600) and hosts `<PlatformManager>` with a loading state and the UI-SPEC portfolio-fetch error copy. Grows in Plans 03/04; this slice renders the platform-manager section only.

## Verification Results

All backend verifies run under the repo's uv `.venv` against live PostgreSQL on `localhost:5434`; frontend verify via `npx tsc --noEmit` in `ui/`.

| Task | Verify | Result |
|------|--------|--------|
| 1 | `pytest backend/tests/test_write_tools.py -x -q` | PASS — 14 passed (11 pre-existing + 3 new platform) |
| 1 | POST /platforms 401-without-key / 201-with-key | PASS — `test_post_platforms_requires_api_key` green |
| 2 | `pytest ...::test_apply_add_platform_creates_row_and_audit` | PASS — 1 passed |
| 3 | `npx tsc --noEmit \| grep -qiE "investments/(PlatformManager\|page)"` | PASS — `OK` (0 total tsc error lines, none in new files) |
| verification | DELETE with holdings → 422 + affected_count; `?reassign_to=` → reassigns then deletes | PASS — live integration check: 422 `affected_count:1`; reassign → 200 `{reassigned:1}`, holding moved to target, source gone |

**End-to-end integration check (live DB):** created source+target platforms via `POST /platforms`, seeded a holding on the source, then: `DELETE` without reassign returned `422` with `detail.affected_count == 1`; `DELETE ?reassign_to=<target>` returned `200 {"status":"deleted","reassigned":1}`, the holding's `platform_id` moved to the target, and the source platform was deleted. All rows cleaned up afterward.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking issue] Pending Alembic migration 004 not applied to the live DB.**
- **Found during:** Task 1 (first pytest run failed with `psycopg.errors.UndefinedColumn: column "platform_id" of relation "holdings" does not exist`).
- **Issue:** Plan 01's migration `004_investment_platforms.py` (rev `b2e6d4a19f73`) was committed to code but the running database on `localhost:5434` was still at `9c1a4f7d2b8e` (003) — the `platforms` table and `holdings.platform_id` column did not exist, so every holdings-touching write and this whole slice would fail.
- **Fix:** Ran the already-committed migration: `alembic upgrade head` (003 → `b2e6d4a19f73`). This is a schema-sync of existing migration code, not an authored schema change (no Rule 4 architectural decision). After upgrade, the full suite went green.
- **Files modified:** none (DB state only — the migration file already existed from Plan 01).
- **Commit:** n/a (environment fix; no source change).

**2. [Enhancement within scope] Richer reassign-confirm copy.**
- The plan's `<action>` cites the base reassign line; UI-SPEC L145 additionally specifies "Reassign {n} holdings to \"{target}\" and delete \"{source}\"?" shown after a target is chosen. Implemented as a muted `<p>` below the destination `<select>` inside the same `ConfirmDialog`. Purely additive copy; no structural change.

No architectural (Rule 4) changes. No auth gates encountered during execution.

## Known Stubs

None. The `/investments` page intentionally renders only the platform-manager section this slice (portfolio-total banner and per-platform holding cards are Plans 03/04, per the plan's `<action>`); this is a planned incremental build, not a stub — the platform manager itself is fully wired to live routes.

## Threat Surface

No new security surface beyond the plan's `<threat_model>`. All three registered threats are mitigated: T-05-02-AC (write routes carry `require_api_key`, GET open — verified by the 401/201 test), T-05-02-INP (Pydantic DTOs validate name/kind; `reassign_to` is an int query param used only in a parameterized UPDATE), T-05-02-REP (every mutation writes exactly one AuditLog row — verified by the add-audit and delete-reassign tests).

## Deferred (Human UAT)

Task 3 `<human-check>` is **deferred to human UAT** (not blocking): load `/investments`, add a platform with a kind, rename it inline, delete a platform with no holdings (confirm dialog), and confirm the reassign-flow copy appears when deleting a platform that has holdings. Requires the frontend + backend running (`docker compose up -d --build` for a live deploy, or dev servers). All automated proxies for this flow (tsc-clean, 422/reassign integration path) pass.

## Commits

- `6ad9517` feat(05-02): platform CRUD backend — helpers, DTOs, audited routes
- `0dab028` feat(05-02): PlatformManager UI + live /investments client page

## Self-Check: PASSED

`ui/app/investments/PlatformManager.tsx` present on disk; both commits (`6ad9517`, `0dab028`) found in git log; the two backend/frontend verifies (pytest 14-green, tsc `OK`) re-confirmed.
