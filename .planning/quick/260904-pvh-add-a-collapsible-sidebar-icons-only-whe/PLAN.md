---
type: quick
slug: 260904-pvh-add-a-collapsible-sidebar-icons-only-whe
files_modified:
  - ui/app/components/Nav.tsx
autonomous: true
---

<objective>
Add a chevron-toggled collapsible left sidebar to `ui/app/components/Nav.tsx` — collapsed shows icons only (~68px), persisted to localStorage, accessible.
</objective>

<context>
Single-file UI change (~40 lines) in a `"use client"` Next.js App Router component.
Existing structure to preserve: `NAV_LINKS` array, the `Icon` component, and the
brand row / "Menu" label / `<nav>` of `<Link>`s / footer card in `Nav()`.
Conventions: inline `React.CSSProperties` style objects, `tokens` from `../styles`,
camelCase, strict TS. localStorage convention: wrap access in try/catch.

CODEBASE ORIENTATION: `graphify-out/graph.json` exists. Run
`graphify query`/`graphify explain` before any broad reads, and `graphify update .`
after editing.
</context>

<tasks>

<task type="auto">
  <name>Task 1: Collapsible icons-only sidebar with persistence + a11y</name>
  <files>ui/app/components/Nav.tsx</files>
  <action>
Add `collapsed` state via `useState` (init to a fixed default, e.g. `false`) plus a
`useEffect` that hydrates it from `localStorage.getItem("monai.sidebarCollapsed")`
on mount — init-then-hydrate ordering avoids an SSR/hydration mismatch. On every
toggle, persist the new value to `localStorage` under the same key. Wrap BOTH the
read and the write in try/catch per the project's localStorage convention.

Convert the module-level `sidebar` const into a value computed from `collapsed`
(move it inside the component or compute inline): width `236` when expanded, ~`68`
when collapsed; keep the existing `transition`-friendly feel (a `width .2s ease`
transition is a nice-to-have). When collapsed, center content horizontally
(e.g. `alignItems: "center"`) and reduce horizontal padding so icons sit centered.

Add a chevron toggle button at the top of the `<aside>` (before/at the brand row)
that flips `collapsed`. Give it `aria-label` "Collapse sidebar" when expanded and
"Expand sidebar" when collapsed. Use an inline SVG chevron consistent with the
existing `Icon` stroke style (`stroke="currentColor"`); no new dependency.

When collapsed, hide (do not render, or `display:none`) the "monai" wordmark text,
the "Menu" label, each nav item's `<span className="nav-label">` text, and the
"Local-first" footer text — keep each nav item's icon `<span>` visible and centered
within the item (remove the label gap / center the item when collapsed).

Accessibility: when collapsed, each icon-only nav `<Link>` MUST carry an accessible
name — set `aria-label` and `title` to its `label` from `NAV_LINKS`. The icon
`<span>` keeps `aria-hidden`.

No backend, no new dependencies, no changes outside this file. `layout.tsx` needs no
change (the `<aside>` is a flex sibling that just gets narrower).
  </action>
  <verify>
    <automated>cd ui && npx tsc --noEmit</automated>
  </verify>
  <done>
- Toggle button flips collapsed/expanded and shows the correct `aria-label`.
- Collapsed: `<aside>` width ~68px; wordmark, "Menu" label, nav-item labels, and
  "Local-first" footer text are hidden; SVG icons remain visible and centered.
- Collapsed state persists across a page reload via `localStorage`
  ("monai.sidebarCollapsed"); localStorage access is try/catch-wrapped and there is
  no hydration mismatch.
- Each collapsed nav `<Link>` has an `aria-label`/`title` matching its page label.
- `cd ui && npx tsc --noEmit` exits clean.
  </done>
</task>

</tasks>

<verification>
Run `cd ui && npx tsc --noEmit` — must be clean.
NOTE: The running Docker frontend is a STALE build and will NOT reflect this change.
A live visual check requires a frontend rebuild or a `next dev` server — do not claim
the Docker container shows it.
After editing, run `graphify update .`.
</verification>

<success_criteria>
`ui/app/components/Nav.tsx` renders a chevron-collapsible, icons-only sidebar that
shrinks to ~68px, hides all text labels while keeping centered icons, persists its
collapsed state across reloads, exposes accessible names for the toggle and each
collapsed nav link, and passes `tsc --noEmit`.
</success_criteria>
