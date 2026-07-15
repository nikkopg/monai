# Phase 6: MCP Server - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-15
**Phase:** 6-mcp-server
**Areas discussed:** Tool surface, Auth model, Tool descriptions, Investment-read boundary, Tool-set parity

---

## Tool surface

| Option | Description | Selected |
|--------|-------------|----------|
| All read tools as-is | Expose every read tool in the tools.py registry, including find_platforms / find_accounts | ✓ |
| Curated analytical subset | Drop agent-internal ID-lookup helpers | |
| Discuss which to include | Walk the registry tool-by-tool | |

**User's choice:** All read tools as-is
**Notes:** No curation — external clients get the full read surface.

---

## Auth model

| Option | Description | Selected |
|--------|-------------|----------|
| Reuse MONAI_API_KEY | Same single key the write routes use, passed as an HTTP header | ✓ |
| Separate MCP key | Distinct, independently-revocable MCP key | |
| You decide | Let research/planner pick FastMCP's cleanest mechanism | |

**User's choice:** Reuse MONAI_API_KEY
**Notes:** One secret to manage; exact FastMCP header wiring left to planner discretion.

---

## Tool descriptions

| Option | Description | Selected |
|--------|-------------|----------|
| Reuse docstrings as-is | FastMCP auto-derives from Python docstrings | |
| MCP-facing descriptions | Explicitly enumerate valid period values / param formats | ✓ |
| You decide | Let planner choose | |

**User's choice:** MCP-facing descriptions
**Notes:** External client LLMs see only name + description + schema; valid `period` values must be enumerated so models don't guess.

---

## Investment-read boundary

| Option | Description | Selected |
|--------|-------------|----------|
| Agent read tools only | Expose exactly what the agent has (spending/cashflow); defer investment reads | ✓ |
| Include investment reads | Author new portfolio value/P&L read tools | |
| Discuss | Talk through whether spending-only is acceptable for v1 | |

**User's choice:** Agent read tools only
**Notes:** Portfolio reads are REST-only today; surfacing over MCP = new tools, deferred to a later phase.

---

## Tool-set parity (follow-up)

Surfaced on adversarial re-read: the `TOOLS` registry has 15 read tools but `query.py` only wires 12 into the web agent — `spending_before_after_purchase`, `monthly_trend`, `account_balances` are unwired. So "all read tools" (15) and MCP-02's "same as the web agent" (12) disagreed.

| Option | Description | Selected |
|--------|-------------|----------|
| Full registry (15) | Expose all 15 over MCP; leave the 3 unwired for the agent | |
| Agent's 12 only | Strict MCP-02 parity at 12 | |
| Full 15 + wire agent too | Expose all 15 over MCP AND wire the 3 into the agent's read_tools so both surfaces match at 15 | ✓ |

**User's choice:** Full 15 + wire agent too
**Notes:** Keeps MCP-02 literally true (both surfaces identical) and closes the incidental agent gap in the same phase.

---

## Claude's Discretion

- Exact FastMCP auth wiring (header/mechanism for co-mounted HTTP transport; adapting require_api_key to the MCP request path).
- Tool registration mechanics (wrap/decorate/adapter) — keep tools.py the single implementation.
- MCP result serialization of the tools' structured-dict returns.
- FastMCP version pin and mounting API.

## Deferred Ideas

- Investment/portfolio reads over MCP — own scope, later phase.
- Separate revocable MCP-only API key — deferred in favor of reusing MONAI_API_KEY.
