---
phase: 8
name: Design Foundation + App Shell
status: complete
requirements: [UIR-01, UIR-02, UIR-03]
completed: 2026-07-18
---

# Phase 8 Summary — Design Foundation + App Shell

## What shipped

- **`ui/app/styles.ts`** — rewritten as the paper token layer. New `tokens`
  export (palette, `--font-serif`/`--font-sans`, radii, spacing, shadows) is the
  single source of truth. Shared constants (`card`, `input`, `btn`, `label`,
  `dangerBtn`, `chartColors`) re-skinned to the paper palette with **unchanged
  export names** so every downstream page/modal keeps compiling. Added `btnDark`
  (ink CTA) and `btnGhost` (neutral) for the mockup's button variants. (UIR-01)
- **`ui/app/layout.tsx`** — loads Instrument Serif + Hanken Grotesk via
  `next/font/google` (self-hosted → no runtime Google calls, privacy-aligned),
  exposes them as CSS vars, sets the cream `#ece8e1` body background, and wraps
  `<Nav/>` + `<main>` in the mockup's centered rounded `#f7f5f1` panel. The panel
  uses `min-height` (not the mockup's fixed 820px) so real content of any length
  fits. (UIR-02, UIR-03)
- **`ui/app/components/Nav.tsx`** — converted from a sticky top bar to the
  mockup's 236px left sidebar: serif "monai" wordmark + green dot, uppercase
  "Menu" label, icon+label nav items (inline SVG icons from the mockup), dark
  active pill via `usePathname`, and a status footer card. Nav order now matches
  the mockup (Cashflow first). (UIR-03)
- **`ui/app/page.tsx`** — root `/` now redirects to `/cashflow` (the mockup's
  default tab) instead of `/chat`. (UIR-03)

## Deviations / decisions

- **Footer card honesty:** the mockup's footer reads "Last import 2 hours ago ·
  4 accounts" (fabricated). Fabricating those numbers would violate monai's core
  "never fabricate a number" principle, so the footer instead reads
  "Local-first / Your data stays on this machine." — true for a self-hosted
  single-user app. If a real sync-status endpoint is wanted later, wire it here.
- **Fonts via `next/font`** rather than the mockup's `<link>` tag — self-hosting
  is idiomatic for App Router and avoids runtime third-party calls. Compiles and
  renders cleanly (verified: serif wordmark uses the hashed `__Instrument_Serif`
  family, not a system fallback).
- **e2e updated to match the intentional redesign:** `smoke.spec.ts` active-nav
  assertion changed from the old blue-accent/2px-border check to the new dark
  pill (`background-color: rgb(35,32,27)`), using retrying `toHaveCSS` to settle
  past the .2s fade. Also un-rotted a pre-existing stale assertion
  ("Investments are coming in Phase 5" → the real "Investments" heading).

## Verification

See `08-VERIFICATION.md`. tsc clean; 27/27 Playwright specs pass; sidebar shell +
fonts + active pill + cream panel confirmed via preview inspect/screenshot.
