---
task: 260703-f5b-patch-flat-commands-manifest-resolution
mode: quick
subsystem: infra
tags: [gsd-core, capability-state, install-profiles, vendored-patch, node]

# Dependency graph
requires: []
provides:
  - "_resolveManifest() third fallback branch for flat gsd-<stem>.md command layouts"
  - "parseCallsAgents exported from install-profiles.cjs"
  - "_loadFlatCommandsManifest helper + export in capability-state.cjs"
affects: [gsd-core-vendored-patches, graphify, capability-state]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Purely-additive fallback branches gated by `.size > 0` on the prior branch's result, preserving byte-for-behavior compatibility with existing layouts"

key-files:
  created: []
  modified:
    - .claude/gsd-core/bin/lib/capability-state.cjs
    - .claude/gsd-core/bin/lib/install-profiles.cjs

key-decisions:
  - "Applied the upstream-proposed fix for open-gsd/gsd-core#1858 verbatim as a LOCAL patch to vendored code — not yet merged upstream as of this session; must be reapplied after any future gsd-update"
  - "Third fallback in _resolveManifest only triggers when both prior layouts (source tree, installed skills dir) are empty (installed.size === 0), preserving additive-only behavior"

patterns-established:
  - "Vendored-patch commits under .claude/gsd-core/ must state in the commit message that they need reapplication after gsd-update, and reference the tracking upstream issue"

requirements-completed: []

coverage:
  - id: D1
    description: "_resolveManifest gains a flat-commands (gsd-<stem>.md) fallback that restores capability surfacing under Claude Code's flat command layout"
    verification:
      - kind: other
        ref: "node .claude/gsd-core/bin/gsd-tools.cjs graphify status (manual CLI invocation)"
        status: pass
      - kind: other
        ref: "node .claude/gsd-core/bin/gsd-tools.cjs capability state (manual CLI invocation, 8 affected capabilities spot-checked)"
        status: pass
    human_judgment: false

duration: 3min
completed: 2026-07-03
status: complete
---

# Quick Task 260703-f5b: Patch flat-commands manifest resolution Summary

**Added a third, purely-additive fallback branch to `_resolveManifest()` in vendored `.claude/gsd-core/` so capability surfacing (graphify + 7 others) works under Claude Code's flat `.claude/commands/gsd-*.md` layout.**

## Performance

- **Duration:** ~3 min
- **Completed:** 2026-07-03T11:02:00Z
- **Tasks:** 2 (1 code patch, 1 verification-only)
- **Files modified:** 2

## Accomplishments
- `_resolveManifest()` now has three resolution branches: (1) nested source tree `commands/gsd/*.md`, (2) installed-runtime skills dir `<configDir>/skills/gsd-*/SKILL.md`, (3) NEW — flat commands dir `gsd-<stem>.md` files, reached only when both prior branches are empty.
- New helper `_loadFlatCommandsManifest(commandsDir)` mirrors `loadSkillsManifest`'s parsing (not `_loadInstalledSkillsManifest`'s), since flat command files carry real bodies with recoverable `requires:` and agent refs.
- `parseCallsAgents` exported from `install-profiles.cjs` (was previously internal-only) and reused rather than reimplemented.
- `graphify status` no longer returns `{"disabled": true}` — it returns real graph status data.
- `capability state` now reports `surfaced:true`/`enabled:true` for graphify and the other 7 affected capabilities (validate-phase, secure-phase, ui-review, code-review, ai-integration, mempalace, profile-user); `graphify` additionally reports `active:true` (its config gate `graphify.enabled` was already `true`).

## Task Commits

Each task was committed atomically:

1. **Task 1: Add flat-commands (gsd-*.md) fallback branch to _resolveManifest** - `33f4cd7` (fix)
2. **Task 2: Verify surfaced/active flip across the 8 affected capabilities** - verification-only, no separate commit (ran both repro CLI commands; see Verification Output below)

_Note: This is a LOCAL patch to vendored code under `.claude/gsd-core/` — it must be reapplied after any future `gsd-update` until the upstream fix (open-gsd/gsd-core#1858) merges._

## Files Created/Modified
- `.claude/gsd-core/bin/lib/capability-state.cjs` - added `_loadFlatCommandsManifest()` helper, wired third fallback branch into `_resolveManifest()`, imported `parseCallsAgents`, exported the new helper for test parity
- `.claude/gsd-core/bin/lib/install-profiles.cjs` - exported the already-existing `parseCallsAgents` function (no body change)

## Decisions Made
- Implemented the upstream issue's own proposed fix (open-gsd/gsd-core#1858) as-is rather than inventing an alternative approach, since it was already verified during planning to be additive-safe.
- Guarded the new branch with `installed.size > 0` (not just `fs.existsSync`) so the flat-commands fallback is provably unreachable whenever either pre-existing layout yields any manifest entries — this is what makes the change purely additive.

## Deviations from Plan

None - plan executed exactly as written. Both tasks completed with no auto-fixes, no blocking issues, and no architectural questions.

## Issues Encountered

None.

## Verification Output (before/after for graphify)

### BEFORE (repro, prior to patch)

`graphify status`:
```json
{
  "disabled": true,
  "message": "graphify is not enabled. Enable with: gsd-tools config-set graphify.enabled true"
}
```

`capability state` — graphify entry:
```json
{
  "id": "graphify",
  "tier": "full",
  "skills": ["graphify"],
  "installed": true,
  "surfaced": false,
  "enabled": false,
  "active": false,
  "hooks": []
}
```

### AFTER (post-patch)

`graphify status`:
```json
{
  "exists": true,
  "last_build": "2026-07-03T10:59:49.909Z",
  "node_count": 3673,
  "edge_count": 3710,
  "hyperedge_count": 0,
  "stale": false,
  "age_hours": 0,
  "built_at_commit": "09a1480",
  "current_commit": "33f4cd7",
  "commits_behind": 3,
  "commit_stale": true,
  "last_build_auto_update": null
}
```

`capability state` — graphify entry:
```json
{
  "id": "graphify",
  "tier": "full",
  "skills": ["graphify"],
  "installed": true,
  "surfaced": true,
  "enabled": true,
  "active": true,
  "hooks": []
}
```

The other 7 affected capabilities (validate-phase, secure-phase, ui-review, code-review, ai-integration, mempalace, profile-user) were spot-checked via `capability state`: all now show `surfaced:true` and `enabled:true`. `active` varies per capability's own config gate (expected — e.g. `mempalace.active` remains `false` because `mempalace.enabled` config gate wasn't asserted in this task; that is EXPECTED per the plan's success criteria — only `surfaced`/`enabled` must flip for the seven non-graphify capabilities).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Capability surfacing is restored for this project's flat command layout; graphify and the other 7 capabilities are correctly surfaced/enabled.
- Reminder: this is a vendored-code patch. If/when `/gsd-update` is run before upstream open-gsd/gsd-core#1858 merges, this patch will be overwritten and must be reapplied (re-run this quick task or manually reapply the diff).

---
*Task: 260703-f5b-patch-flat-commands-manifest-resolution*
*Completed: 2026-07-03*

## Self-Check: PASSED

- FOUND: `.claude/gsd-core/bin/lib/capability-state.cjs`
- FOUND: `.claude/gsd-core/bin/lib/install-profiles.cjs`
- FOUND: `.planning/quick/260703-f5b-patch-flat-commands-manifest-resolution-/260703-f5b-SUMMARY.md`
- FOUND: commit `33f4cd7` in `git log --oneline --all`
