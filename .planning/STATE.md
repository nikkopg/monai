# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-21)

**Core value:** You can understand and manage your entire financial life — spending and investments — by talking to a trustworthy AI that never fabricates a number and never changes your data without your say-so.
**Current focus:** Phase 1 — Schema Foundation + Auth

## Current Position

Phase: 1 of 6 (Schema Foundation + Auth)
Plan: 0 of ? in current phase
Status: Ready to plan
Last activity: 2026-06-21 — Roadmap created; 30/30 requirements mapped to 6 phases

Progress: [░░░░░░░░░░] 0%

## Performance Metrics

**Velocity:**
- Total plans completed: 0
- Average duration: —
- Total execution time: —

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| - | - | - | - |

**Recent Trend:**
- Last 5 plans: —
- Trend: —

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- Pre-roadmap: Alembic + `MONAI_API_KEY` are hard blockers — must ship in Phase 1 before any write endpoint
- Pre-roadmap: `proposals` table must be backend-persisted (not in-memory); confirm token is single-use and operation-scoped
- Pre-roadmap: `tools.py` is the single source of truth shared by agent AND MCP server — no logic duplication
- Pre-roadmap: `portfolio_events` (INV-07) ships in Phase 5 before correlation queries (CHAT-03, also Phase 5)
- Pre-roadmap: Price layer uses pluggable adapters + `fetched_at`/staleness from day one; reksadana = manual fallback

### Pending Todos

None yet.

### Blockers/Concerns

- **Phase 2 open question:** Ollama function-calling support — if user's local model (e.g. gemma4) lacks native tool calling, must use `ReActAgent` instead of `FunctionAgent`. Verify before Phase 2 planning.
- **Phase 2 open question:** SSE vs WebSocket for streaming agent events to the Next.js frontend. Recommendation: start with SSE. Decide before Phase 2 backend is built.
- **Phase 5 open question:** Sectors.app free tier coverage for user's specific IDX tickers — requires direct verification before Phase 5 planning.

## Deferred Items

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| v2 | QRY-01: recurring-charge detection | Acknowledged | Init |
| v2 | QRY-02: period comparison | Acknowledged | Init |
| v2 | QRY-03: streaming token-by-token | Acknowledged | Init |
| v2 | INVX-01: historical portfolio value | Acknowledged | Init |
| v2 | INVX-02: automated reksadana NAV | Acknowledged | Init |

## Session Continuity

Last session: 2026-06-21
Stopped at: Roadmap + STATE.md created; REQUIREMENTS.md traceability updated. Next: `/gsd:plan-phase 1`
Resume file: None
