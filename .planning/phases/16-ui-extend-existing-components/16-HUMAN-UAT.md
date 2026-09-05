---
status: complete
phase: 16-ui-extend-existing-components
source: [16-VERIFICATION.md]
started: 2026-08-01T19:40:00Z
updated: 2026-08-03T05:50:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Rebuild the frontend before UAT
expected: `docker compose up -d --build` for the frontend service; container serves the current Phase-16 build (not the stale pre-Phase-16 image).
result: passed — Claude did it 2026-08-01. Root cause of the stale/crash-looping container was an orphaned `npm run dev` process (pid 498365, an executor leftover) squatting port 3001, causing `EADDRINUSE`. Killed the orphan, rebuilt + recreated `monai-frontend`; now `Up`, `✓ Ready`, serving HTTP 200 on :3001, no crash-loop.

### 2. Segmented-control visual parity
expected: The Expense/Income/Transfer segmented control looks visually indistinguishable from the Settings LLM-provider selector (UIR-07) — same pill container, active = white bg + shadow, inactive = muted/transparent.
result: passed — Claude verified 2026-08-01 via computed CSS on the live build (screenshots unavailable in this env). All 14 properties are byte-identical between the two controls: container bg rgb(242,239,232) / border 1px rgb(226,220,207) / radius 12px / pad 4px; active pill #fff + boxShadow rgba(40,34,24,.12) 0 1px 2px + weight 600 + radius 9px + pad 8px 18px; inactive color rgb(139,132,116) + weight 500. Both default to first segment (Expense / ollama). Stronger-than-visual proof of verbatim reuse.

### 3. Live Transfer click-through (real Postgres)
expected: In the live app, add a real Transfer record between two liquid accounts. Both legs appear correctly, balances move atomically, no orphan leg — the Phase-13 atomic-pair guarantee holds end-to-end through the new modal.
result: passed — user confirmed 2026-08-03 via live click-through against real Postgres. A real Transfer between two liquid accounts posts both legs, balances move atomically, no orphan leg. The Phase-13 atomic-pair guarantee holds end-to-end through the new modal.

## Summary

total: 3
passed: 3
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps
