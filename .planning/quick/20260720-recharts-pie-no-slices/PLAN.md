---
quick_id: 260720-7lu
slug: recharts-pie-no-slices
date: 2026-07-20
---

# Fix: recharts Pie charts render zero slices

## Problem

Both Pie charts in the app (`CategoryDonut`, `AllocationPieChart`) render
`<g class="recharts-pie-sector">` groups containing an empty
`<g class="recharts-shape">` — zero `<path>` elements, so no slices are visible.
Line charts are unaffected.

## Root cause

Not a data problem and not a regression from Phase 11 — it is how recharts 3.9
animates Pie entrance.

1. `defaultPieAnimateItems` (`recharts/es6/polar/Pie.js`) interpolates each
   sector's sweep from zero. At `animationElapsedTime === 0` every sector has
   `startAngle === endAngle`.
2. `Sector` (`recharts/es6/shape/Sector.js:180`) returns `null` when
   `startAngle === endAngle`. That is the empty `<g class="recharts-shape">`.
   (The very first sector is `0,0` and is skipped entirely, which is why the app
   showed N-1 sector groups for N categories.)
3. The animation clock is `RequestAnimationFrameTimeoutController`
   (`JavascriptAnimate.js`), and Pie's default `animationBegin` is 400ms. If no
   animation frame is delivered while the animation is pending — backgrounded
   tab, non-composited/offscreen pane, headless automation — elapsed time stays
   at 0 and the pie is permanently invisible. It does **not** self-heal when
   frames resume, because the pending timeout was scheduled against the dead
   clock and is never rescheduled.

Line charts survive because their t=0 interpolation still produces a full path.

Reproduced deterministically in the live app by stubbing
`window.requestAnimationFrame = () => 0` before a fresh Pie mount: 6 sectors,
0 paths — exactly the reported symptom.

## Fix

Add `isAnimationActive={false}` to both `<Pie>` elements. Sector geometry is
final on first render, with no dependency on an animation frame arriving.

- `ui/app/cashflow/charts/CategoryDonut.tsx`
- `ui/app/investments/AllocationPieChart.tsx`

Rejected alternatives: pinning/upgrading recharts (the behaviour is by design in
3.x, not a version bug); numeric vs percentage radii (irrelevant — radii were
already numeric and correct).

## Verification

Production build (`next build` + `next start`), real browser:

| condition | before | after |
|---|---|---|
| `CategoryDonut`, fresh mount, rAF starved | 6 sectors / 0 paths | 7 sectors / **7 paths** |
| `AllocationPieChart`, fresh mount, rAF starved | 0 paths | 4 sectors / **4 paths** |
| normal load | intermittent | 7 sectors / 7 paths |

`cd ui && npx tsc --noEmit` clean. No backend changes.
