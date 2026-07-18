# monai — Engineering Retrospective

Living record across milestones. Newest first.

## Milestone: v1.1 — UI Redesign ("Paper" Aesthetic)

**Shipped:** 2026-07-18
**Phases:** 3 (8-10) | **Plans:** 3 | **Commits:** 7 + 3 close | **Timeline:** 1 day

### What Was Built
Re-skinned the entire four-page app + shell to the Claude Design "paper" mockup
via a token layer in `styles.ts`, `next/font` (Instrument Serif + Hanken Grotesk),
and a sidebar-in-panel shell — zero backend changes, all behavior/data preserved
(real IDR), responsive to 375px. 10/10 UIR requirements, 27/27 e2e.

### What Worked
- **Foundation-first sequencing.** Re-skinning `styles.ts`'s shared constants in
  Phase 8 meant every downstream component that imported `card`/`input`/`btn`
  shifted to paper automatically — the token seam already existed.
- **Verifying in the real browser** (preview snapshots/inspect) caught real-data
  correctness (net worth 192M IDR, not the mockup's fake $50k) that a code read
  would have missed.
- **A blunt but semantic hex→token sweep** re-themed 11 leaf components in one
  pass; `grep` confirmed zero old hex remained.

### What Was Inefficient
- **e2e coupling to old copy/indicators** caused several avoidable red runs
  (blue-underline active state, "Total Income" captions, "Add transaction"
  label). Updating tests to track intentional redesign changes is correct, but a
  too-broad `replace_all` also hit the modal-submit selector and had to be
  reverted — scope replacements more tightly.
- **Environment friction**: a stale foreign dev server on :3001 shadowed the
  Playwright `reuseExistingServer`, and the committed chromium path didn't exist
  on the host. Cost a debugging detour; both documented for next time.

### Patterns Established
- Paper design tokens (`tokens` in `styles.ts`) as the single source of truth.
- Inline `repeat(auto-fit, minmax(min(100%, Npx), 1fr))` grids for CSS-free
  responsive stacking; `globals.css` + `!important` only for the shell collapse.
- Honesty over pixel-fidelity where the mockup implies fake data (sidebar footer;
  omitted live-refresh toggle with no backend field).

### Key Lessons
- When a redesign changes copy or an indicator, the e2e assertion must evolve
  with it — but keep the *behavioral* intent and scope the edit narrowly.
- The GSD full plan-phase agent pipeline is overkill for a fully-specified visual
  restyle; self-orchestrating the phases (tracked commits + verification) was the
  right call and far cheaper.

### Cost Observations
- Model mix: Opus (orchestration/implementation) + Sonnet (roadmapper subagent).
- Sessions: 1 (autonomous, AFK).
- Notable: avoided ~20-30 cold-start subagent spawns by self-orchestrating.

## Cross-Milestone Trends

| Milestone | Phases | Plans | Timeline | Notable |
|-----------|--------|-------|----------|---------|
| v1.0 | 7 | 30 | ~51 days | MVP: agentic chat + investments + MCP |
| v1.1 | 3 | 3 | 1 day | Presentation-only paper redesign |
