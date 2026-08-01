---
status: partial
phase: 16-ui-extend-existing-components
source: [16-VERIFICATION.md]
started: 2026-08-01T19:40:00Z
updated: 2026-08-01T19:40:00Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. Segmented-control visual parity
expected: Open the record modal; the Expense/Income/Transfer segmented control looks visually indistinguishable from the Settings LLM-provider selector (UIR-07) — same pill container, active state = white background + shadow, inactive = muted/transparent.
result: [pending]

### 2. Rebuild the frontend before UAT
expected: Run `docker compose up -d --build` for the frontend service first. The running `monai-frontend` container currently serves a stale pre-Phase-16 build (the verifier confirmed and worked around this). Without a rebuild you'd be testing old UI.
result: [pending]

### 3. Live Transfer click-through (real Postgres)
expected: After rebuild, add a real Transfer record between two liquid accounts. Both legs appear correctly, balances move atomically, no orphan leg — the Phase-13 atomic-pair guarantee holds end-to-end through the new modal.
result: [pending]

## Summary

total: 3
passed: 0
issues: 0
pending: 3
skipped: 0
blocked: 0

## Gaps
