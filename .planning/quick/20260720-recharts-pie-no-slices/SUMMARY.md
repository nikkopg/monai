---
quick_id: 260720-7lu
slug: recharts-pie-no-slices
date: 2026-07-20
status: complete
---

# Summary

Added `isAnimationActive={false}` to both `<Pie>` elements
(`ui/app/cashflow/charts/CategoryDonut.tsx`,
`ui/app/investments/AllocationPieChart.tsx`).

recharts 3.9 collapses every Pie sector to `startAngle === endAngle` at
animation t=0, and `Sector` renders `null` for that — so a Pie is genuinely
zero `<path>`s until an animation frame lands. The clock is rAF-based and never
recovers if frames are missed while the animation is pending, which is why the
pie could stay blank indefinitely while Line charts looked fine.

Verified in a real browser against a production build, under a stubbed-out
`requestAnimationFrame` (the condition that reproduced the bug): both pies now
render their full path set. `npx tsc --noEmit` clean.

## Follow-up found while verifying (not fixed here)

`ui/app/cashflow/page.tsx` on this branch still destructures `by_category` as
`[category, total]` tuples, but the backend now returns hierarchy objects
(`{id, name, color, icon, total, children}`). A production build of this branch
crashes on `/cashflow` with "Cannot read properties of undefined". The container
currently running on :3001 does not crash, so the deployed build is ahead of
this branch. Worth reconciling before the next deploy.
