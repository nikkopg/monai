# Phase 6: MCP Server - Context

**Gathered:** 2026-07-15
**Status:** Ready for planning

<domain>
## Phase Boundary

Expose monai's **read tools** to external MCP clients (e.g. Claude Desktop) via a
**FastMCP server co-mounted in the existing FastAPI app** at
`http://host:8001/mcp`. External clients enumerate and call the *same*
`backend/tools.py` read implementations the web chat agent uses — one source of
truth, no duplicated logic. The surface is **read-only** (zero write/`propose_*`
tools) and **API-key gated** (unauthenticated connections rejected).

**In scope (HOW to build the above):**
- Add FastMCP as a dependency and co-mount it on the FastAPI app at `/mcp`.
- Register the 15 `tools.py` read tools as MCP tools with external-LLM-facing
  descriptions.
- Wire the 3 currently-unwired read tools into the web agent's `read_tools` list
  so the web-agent surface and the MCP surface are identical at 15 tools.
- Enforce API-key auth on the MCP transport, reusing the existing
  `MONAI_API_KEY`.

**Out of scope (own phases / deferred):**
- Any write / `propose_*` tools over MCP (permanently out — MCP-03).
- New investment/portfolio *read* tools (portfolio value/P&L is REST-only today;
  surfacing it over MCP = new tools, deferred).
- Streaming / token-level responses (v2, QRY-03).

**Requirements covered:** MCP-01, MCP-02, MCP-03, MCP-04.

</domain>

<decisions>
## Implementation Decisions

### Tool surface
- **D-01:** Expose the **full 15-tool read registry** from `backend/tools.py`
  over MCP — including the ID-lookup helpers `find_platforms` and
  `find_accounts`. External clients get the richest read surface; no curation.
- **D-02:** **Close the agent/MCP parity gap in this phase.** Three read tools
  exist in the `TOOLS` registry but are NOT currently wired into the web agent's
  `read_tools` list in `backend/query.py`: `spending_before_after_purchase`,
  `monthly_trend`, `account_balances`. Add all three to the agent's `read_tools`
  so the web-agent surface and the MCP surface are **identical at 15 read
  tools** — MCP-02 ("same tools the web agent uses") stays literally true. This
  is a small additive edit to `query.py`'s `read_tools` list.
- **D-03:** **Writes are never exposed over MCP.** The 11 `propose_*` write tools
  do not appear in the MCP registry at all — attempting to call one fails
  because the tool does not exist there (not merely because it's blocked).

### Authentication
- **D-04:** **Reuse the single `MONAI_API_KEY`** (the same secret the FastAPI
  write routes already validate via `backend/auth.py:require_api_key`). No
  separate MCP key. The external client presents the key over the MCP HTTP
  transport (header mechanism per FastMCP's co-mounted-HTTP auth — see
  Discretion). One secret to manage, consistent with existing auth.

### Tool descriptions for external LLMs
- **D-05:** **Author MCP-facing tool descriptions** rather than relying purely on
  auto-derived Python docstrings. External client models see only the MCP tool
  name + description + param schema, not the source. Descriptions MUST
  explicitly enumerate the valid `period` values (the named-period set from
  `resolve_period` / the `PERIODS` tuple, e.g. `last_month`, `this_month`,
  `last_week`, …) and any other constrained param formats, so an external model
  calls tools correctly without trial-and-error. Reuse existing docstrings as
  the base where they already read well.

### Claude's Discretion (planner/researcher decide)
- **Exact FastMCP auth wiring** — which header / mechanism FastMCP supports most
  cleanly for a co-mounted HTTP (streamable-HTTP) transport, and how
  `require_api_key` is adapted to the MCP request path vs. FastAPI's `Depends`.
- **Registration mechanics** — whether MCP tools are declared by wrapping the
  `TOOLS` dict callables, decorating them, or a thin adapter; keep `tools.py` as
  the single implementation, no logic fork.
- **Return shape over MCP** — tools return structured dicts today; confirm those
  serialize cleanly as MCP tool results (vs. the agent's formatted-answer path).
- **FastMCP version / mounting API** — pin and mount per current FastMCP docs.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & requirements
- `.planning/ROADMAP.md` §"Phase 6: MCP Server" — goal + 4 success criteria (the
  verification target: connect to `/mcp`, enumerate read-only tools, call a read
  tool with agent-parity results, write tools absent, API-key required).
- `.planning/REQUIREMENTS.md` §"MCP Server" — MCP-01 (single MCP server),
  MCP-02 (shared tool implementations, one source of truth), MCP-03 (read/query
  tools only; no writes), MCP-04 (authenticate before use).
- `.planning/PROJECT.md` §"Key Decisions" — "One MCP server powers web chat +
  external clients"; "External MCP clients get read tools only; writes
  web-app-only".

### Existing code to evolve
- `backend/tools.py` §`TOOLS` (dict, ~L494) — the 15-tool read registry that is
  the single source of truth; `resolve_period` + `PERIODS` for the valid
  `period` values D-05 must document.
- `backend/query.py` §`read_tools` list (L114–127) — the 12 tools currently
  wired to the web agent; D-02 adds `spending_before_after_purchase`,
  `monthly_trend`, `account_balances` here.
- `backend/main.py` §`app = FastAPI(...)` (L139) — the app to co-mount FastMCP
  onto; `lifespan` wiring.
- `backend/auth.py` §`require_api_key` — the `MONAI_API_KEY` check to reuse
  (D-04).

### Codebase maps (background)
- `.planning/codebase/ARCHITECTURE.md` §"The Tool Router" — correctness-by-
  construction; the MCP surface must NOT reintroduce free-form SQL.
- `.planning/codebase/INTEGRATIONS.md`, `STACK.md` — FastAPI / LlamaIndex
  integration surface and dependency wiring.
- `.planning/phases/02-agentic-loop-confirm-before-write/02-CONTEXT.md` §D-04 —
  the "`tools.py` single source of truth, reused by the Phase 6 MCP server, but
  writes are NOT exposed over MCP" decision this phase now realizes.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `backend/tools.py:TOOLS` — 15 read tools already parameterized and returning
  structured dicts; register these directly, no reimplementation.
- `backend/auth.py:require_api_key` — existing `MONAI_API_KEY` validation, reused
  verbatim for MCP auth (D-04).
- `resolve_period` / `PERIODS` — the canonical named-period vocabulary to surface
  in MCP tool descriptions (D-05).

### Established Patterns
- **Registry pattern:** `TOOLS = {name: callable}` in `tools.py` is the single
  tool surface; both the web agent (`query.py`) and this MCP server consume it.
- **Auth via FastAPI `Depends(require_api_key)`** on write routes — MCP transport
  must apply an equivalent gate on its own request path.
- **Structured-dict returns** from every tool — MCP results reuse these.

### Integration Points
- FastMCP co-mounts onto the existing `FastAPI` app in `backend/main.py` at
  `/mcp` (same process, port 8001) — no separate server.
- `backend/query.py`'s `read_tools` list is edited (D-02) so agent and MCP
  surfaces match; this is the only web-agent-facing change.

</code_context>

<specifics>
## Specific Ideas

- Success-criterion example query to keep working end-to-end: an external client
  asks for "spending total for last month" and gets the **same** result the web
  chat agent returns for the same query (parity is the acceptance bar).
- The connect target is literally `http://host:8001/mcp` (as written in the
  ROADMAP success criteria) — keep that path.

</specifics>

<deferred>
## Deferred Ideas

- **Investment/portfolio reads over MCP** (portfolio value, P&L) — currently
  REST-only, not in the tool registry, so unreachable by agent or MCP. Surfacing
  it means authoring new read tools; its own scope, a later phase.
- **Separate revocable MCP-only API key** — considered for isolation; deferred in
  favor of reusing the single `MONAI_API_KEY` (D-04). Revisit if multi-client or
  key-rotation needs emerge.

</deferred>

---

*Phase: 6-MCP Server*
*Context gathered: 2026-07-15*
