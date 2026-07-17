---
phase: 8
name: Design Foundation + App Shell
status: passed
verified: 2026-07-18
requirements: [UIR-01, UIR-02, UIR-03]
---

# Phase 8 Verification — Design Foundation + App Shell

Goal-backward check against the roadmap's 5 success criteria.

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | `styles.ts` exports the full token set as the only place values are hard-coded | ✅ PASS | `tokens` object exports palette (`#ece8e1`/`#f7f5f1`/`#f2efe8`/`#23201b`/`#2f6f4f`/`#b5503f` …), font vars, radii, spacing; shared style constants derive from tokens; `btn.background` is now a token, not `#3b82f6`. |
| 2 | Instrument Serif on headings/wordmark, Hanken Grotesk on body, across all pages | ✅ PASS | preview_inspect on the wordmark → `font-family: __Instrument_Serif_1f5468, …` (next/font hashed family loaded, not system fallback). Body default = `tokens.font.sans`. |
| 3 | Sidebar: serif wordmark, "Menu" label, icon+label items, dark active pill, footer card — on all four routes | ✅ PASS | Screenshot shows wordmark + green dot, MENU, 4 icon items, dark pill on Cashflow. Live eval after client-nav: active link `bg rgb(35,32,27)`, others transparent. |
| 4 | Cream page bg + centered rounded panel matching mockup shell | ✅ PASS | Body bg `#ece8e1`; panel `#f7f5f1`, radius 22, hairline border, soft shadow (layout.tsx); screenshot confirms rounded cream frame. |
| 5 | All existing Playwright e2e specs pass (no nav/routing regressions) | ✅ PASS | `27 passed (33.7s)` against current code (:3002). |

## Verification commands

- `npx tsc --noEmit` (ui/) → exit 0.
- `npx playwright test` → 27/27 pass. NOTE: run against the live keyed preview
  server on :3002; the committed config's :3001 was held by a stale
  pre-redesign dev server (foreign-owned PID, unkillable here) that
  `reuseExistingServer` kept reusing. Also, the config's hard-coded fallback
  chromium path (`/opt/pw-browsers/chromium-1194`) is absent on this host — set
  `PLAYWRIGHT_CHROMIUM_PATH=~/.cache/ms-playwright/chromium-1217/chrome-linux64/chrome`.

## Carried-forward notes for Phases 9-10

- Page interiors (cashflow/chat/investments/settings) still use v1.0-era inline
  styles on a now-cream panel — expected mid-migration; restyled in 9 & 10.
- The two chromium-path / stale-3001 gotchas above will recur when running e2e.
