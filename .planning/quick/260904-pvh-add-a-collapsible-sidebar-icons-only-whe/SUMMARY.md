---
quick_id: 260904-pvh
slug: add-a-collapsible-sidebar-icons-only-whe
status: complete
date: 2026-09-04
commit: c6000e5
---

# Quick Task: Collapsible icons-only sidebar

**Objective:** Let the user collapse the left sidebar to an icons-only rail.

## What changed

- `ui/app/components/Nav.tsx` (only file touched):
  - Chevron toggle button at the top of the sidebar collapses/expands it.
  - Collapsed: `<aside>` shrinks 236px → 68px; wordmark, "Menu" label, nav text
    labels, and the Local-first footer card are hidden — SVG icons stay, centered.
  - `sidebar` const became `sidebarStyle(collapsed)`; smooth width/padding transition.
  - Collapsed state persists to `localStorage["monai.sidebarCollapsed"]`, hydrated in
    a `useEffect` (init false → correct after mount) so SSR never mismatches;
    localStorage access wrapped in try/catch.
  - Accessibility: icon-only nav `<Link>`s get `aria-label`/`title` of their page
    name when collapsed; the toggle button has an `aria-label`.

## Verification

- `cd ui && npx tsc --noEmit` → exit 0 (clean).
- UI-only change, no backend, no new deps.
- NOTE: the running docker `monai-frontend` is a stale build — this change is NOT
  visible there until the frontend image is rebuilt (`docker compose up -d --build
  frontend`) or run via `next dev`.
