# Phase 1: Schema Foundation + Auth - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-21
**Phase:** 1-Schema Foundation + Auth
**Areas discussed:** Alembic baseline strategy, Auth enforcement & public routes, New table schemas & precision, Decimal conversion boundary

---

## Alembic Baseline Strategy

### How should Alembic be introduced onto the existing populated DB?

| Option | Description | Selected |
|--------|-------------|----------|
| Two migrations + stamp | Autogen baseline matching current models → `alembic stamp` live DB → migration 2 adds 5 tables | ✓ |
| Single additive migration | One migration CREATEs the 5 new tables; Alembic never knows the base schema | |
| Handwritten baseline | Hand-author the initial revision instead of autogenerating | |

**User's choice:** Two migrations + stamp

### Where should the date_helpers view live once create_all() is gone?

| Option | Description | Selected |
|--------|-------------|----------|
| Into a migration | Move CREATE OR REPLACE VIEW into an Alembic migration | ✓ |
| Keep in startup hook | Leave view in an idempotent startup function | |

**User's choice:** Into a migration

### What safety net before the first `alembic upgrade head` on real data?

| Option | Description | Selected |
|--------|-------------|----------|
| Documented pg_dump step | Add a backup step to runbook/README before first upgrade | ✓ |
| Tested downgrade() | Require working/tested downgrade() on every migration | |
| Both | Backup AND reversible downgrades | |

**User's choice:** Documented pg_dump step

---

## Auth Enforcement & Public Routes

### How should the API key be enforced?

| Option | Description | Selected |
|--------|-------------|----------|
| Per-route dependency | FastAPI dependency attached to write routes | ✓ |
| Global middleware | Middleware checks every request, allow-lists read paths | |

**User's choice:** Per-route dependency

### Which endpoints stay reachable WITHOUT a key?

| Option | Description | Selected |
|--------|-------------|----------|
| All reads + /query public | GET reads + POST /query open; only writes keyed | ✓ |
| Only /health public | Lock down everything except health check | |
| Reads public, /query keyed | GET reads open, /query requires key | |

**User's choice:** All reads + /query public

### How does the Next.js frontend send the key to the backend?

| Option | Description | Selected |
|--------|-------------|----------|
| Server-side proxy injects it | Next route handler/middleware adds header from env; key never in browser | ✓ |
| Defer to Phase 3 Settings | Backend-only this phase; UI wiring lands with Settings page | |
| Client holds the key | Browser stores and sends the key | |

**User's choice:** Server-side proxy injects it

---

## New Table Schemas & Precision

### What Numeric precision for holdings/prices?

| Option | Description | Selected |
|--------|-------------|----------|
| qty(28,8), money(20,4) | 8-decimal quantities; 4-decimal money for sub-rupiah token prices | |
| qty(28,8), money(18,2) | 8-decimal quantities; money at 2 decimals like transactions | ✓ |
| qty(36,18), money(20,8) | Ethereum-grade 18-decimal quantities, 8-decimal money | |

**User's choice:** qty(28,8), money(18,2)

### How should audit_log before/after and proposal payloads be stored?

| Option | Description | Selected |
|--------|-------------|----------|
| JSONB columns | Flexible JSONB for varying entity shapes | ✓ |
| Typed columns | Explicit columns per audited field | |

**User's choice:** JSONB columns

### The proposal's confirm token — same as the row's UUID id, or a separate secret?

| Option | Description | Selected |
|--------|-------------|----------|
| Separate random secret | Distinct high-entropy token column gates confirmation | ✓ |
| UUID id is the token | Row UUID doubles as confirm token | |

**User's choice:** Separate random secret

### Where does a manually-set/overridden holding price live?

| Option | Description | Selected |
|--------|-------------|----------|
| price_cache w/ source='manual' | All prices flow through price_cache with a source field | ✓ |
| Column on holdings | last_known_price/manual_price column on holdings | |

**User's choice:** price_cache w/ source='manual'

---

## Decimal Conversion Boundary

### How far does the Decimal retrofit reach this phase?

| Option | Description | Selected |
|--------|-------------|----------|
| All money fields now | Switch existing transaction schemas to Decimal too, plus new schemas | ✓ |
| New paths only | Only holdings/price/proposal schemas use Decimal | |

**User's choice:** All money fields now

### How should Decimal values serialize in JSON responses?

| Option | Description | Selected |
|--------|-------------|----------|
| JSON number | Emit amounts as JSON numbers | ✓ |
| JSON string | Emit amounts as strings to guarantee zero float rounding | |

**User's choice:** JSON number

### Want a shared money type to enforce consistency, or keep it ad-hoc?

| Option | Description | Selected |
|--------|-------------|----------|
| Shared Decimal alias | One annotated money type reused across all schemas | ✓ |
| Plain Decimal per field | Annotate each field as Decimal individually | |

**User's choice:** Shared Decimal alias

---

## Claude's Discretion

- Exact column lists for the 5 tables (beyond precision/JSONB/token decisions) — derived from success criteria; skeletons suggested in CONTEXT.md.
- Alembic env layout (`alembic/` location, `env.py` wiring).
- Constant-time comparison primitive for the key check.

## Deferred Ideas

None — discussion stayed within phase scope. No scope creep surfaced; no pending todos matched this phase.
