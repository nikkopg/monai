---
phase: 14
slug: rest-endpoints-agent-mcp-tool-registration
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on severity (the blocking gate)
threats_open: 0
asvs_level: 1
created: 2026-07-31
---

# Phase 14 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.
> Retroactive audit against the `<threat_model>` blocks in 14-01/14-02/14-03-PLAN.md.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| test harness → live Postgres | Tests seed and clean up real rows | `zz14test-`-prefixed seed rows |
| external MCP client → tools/list surface | Untrusted external clients must never see/call a write tool | tool names + schemas |
| chat LLM → proposal payload → confirm dispatch | LLM-built payloads reach `apply_*` and can be malformed | proposal JSON payload |
| REST client → new write endpoints | Untrusted request bodies cross into the mutation layer | transfer/funded-buy/sell/adjust-balance bodies |
| request body → apply_* after-dict | Malformed/negative/nonexistent-reference input must be rejected cleanly | account/platform references, amounts |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-14-01 | Elevation of Privilege | new propose_* on MCP read-only surface | high | mitigate | Registered ONLY in trailing `TOOLS.update()` (tools.py:1333), after `READ_TOOL_NAMES` snapshot (tools.py:628) | closed |
| T-14-02 | Tampering / Info Disclosure | malformed proposal payload → KeyError → 500 leak | high | mitigate | `try/except (KeyError, TypeError) as e: raise ValueError(...)` guard (main.py:1215-1231); confirm endpoint maps ValueError→422 (main.py:1283-1288) | closed |
| T-14-05 | Spoofing / Elevation of Privilege | new REST write endpoint missing auth gate | high | mitigate | All 5 routes carry `dependencies=[Depends(require_api_key)]` (main.py:256,445,478,808,835) | closed |
| T-14-03 | Tampering (data integrity) | double-commit inside apply_* breaks atomicity | medium | mitigate | Dispatch branches call apply_* only; `db.commit()` grep in writes.py = 0; single commit at main.py:1282 | closed |
| T-14-06 | Tampering (data integrity) | unbounded/negative amounts bypass sign normalization | medium | mitigate | `Field(..., gt=0)` on transfer amount + funded cash_amount/quantity/price (schemas.py:196,219-221); `BalanceAdjustmentCreate.target_balance` deliberately unconstrained | closed |
| T-14-07 | Information Disclosure | nonexistent account/platform → 500 stack-trace leak | medium | mitigate | `apply_add_portfolio_event` now guards `db.get(Platform, after["platform_id"]) is None → ValueError` (writes.py:435), mapped to 422 by every caller; `test_funded_buy_rejects_nonexistent_platform` pins 422-not-500. Fixed in quick task 260731-998 (commit fc0bf73) | closed |
| T-14-08 | Tampering (data integrity) | double-commit / hand-rolled SQL diverging from shared mutation layer | medium | mitigate | Each of the 5 REST handlers calls its apply_* exactly once + `db.commit()` exactly once; zero raw `text(`/`db.add(Transaction`/`db.add(PortfolioEvent` in handler bodies | closed |
| T-14-T1 | Tampering | test seed rows on live DB | low | mitigate | `finally`-block `_cleanup_*` + `zz14test-` prefixes throughout test_write_endpoints.py + test_proposals.py | closed |
| T-14-04 | Tampering (data integrity) | transfer/funded leg missing is_transfer=True → double-count | low | accept | Verified: none of the 5 new propose_* functions or REST leg-builders set `is_transfer` in their payloads (0 matches in tools.py:1123-1330); apply_add_transfer/apply_add_investment_transfer force it internally (writes.py:188) | closed |
| T-14-SC | Tampering | supply chain / new packages | low | accept | Verified: no diff to requirements.txt/pyproject.toml across the Phase-14 commit range | closed |

*Status: open · closed · open — below {block_on} threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above workflow.security_block_on (high) count toward threats_open*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Findings — T-14-07 (RESOLVED 2026-07-31)

> **Resolved** in quick task 260731-998 (commit `fc0bf73`). Root cause fixed at the
> shared chokepoint: `apply_add_portfolio_event` (backend/writes.py:435) now runs
> `if db.get(Platform, after["platform_id"]) is None: raise ValueError(...)` before
> the insert, so a nonexistent `platform_id` raises `ValueError` — already mapped to
> `HTTPException(422)` by every caller — instead of reaching the FK and raising
> `IntegrityError` → 500. One guard closes all 5 call paths (the 3 new REST routes,
> the agent-path confirm branches, and the inherited Phase-13 `create_portfolio_event`
> route). `test_funded_buy_rejects_nonexistent_platform` (test_write_endpoints.py:382)
> asserts 422; full suite green (273 passed, only the pre-existing unrelated
> `test_settings.py::test_put_settings_requires_key` failure remains). The original
> finding is retained below for the audit record.

---

The plan's stated mitigation — "apply_* raise ValueError on missing refs; handler maps
ValueError→HTTPException(422)" — does **not** hold for the `platform_id` reference on
the 3 new endpoints that route through `apply_add_portfolio_event`
(`create_funded_buy`, `create_funded_sell`, `create_investment_transfer`, plus the
matching agent-path confirm branches):

- `apply_add_portfolio_event` (backend/writes.py:410-474) never checks whether
  `platform_id` refers to an existing row before inserting; it relies on the
  `PortfolioEvent.platform_id` FK constraint (backend/models.py:264-266,
  `nullable=False`) to reject a bad reference at `db.flush()` time. That raises
  `sqlalchemy.exc.IntegrityError`, not `ValueError`.
- None of the 3 affected REST handlers (backend/main.py:445-499, 835-862) catch
  `IntegrityError` — only `except ValueError as e: raise HTTPException(422, ...)`.
  An `IntegrityError` therefore propagates unhandled.
- Empirically verified (in-process `TestClient`, `raise_server_exceptions=False`,
  no repo files modified): `POST /portfolio-events/funded-buy` with
  `platform_id=999999999` returns **`500 Internal Server Error`** (generic body,
  no JSON `detail`, no literal stack trace in the response — Starlette's default
  unhandled-exception handler — but it is a 500, not the promised 422).
- No test in `test_write_endpoints.py` or `test_proposals.py` exercises a
  nonexistent-`platform_id` case for any of the 5 new operations — the gap is
  untested as well as unmitigated.
- The `account`/`source_account_name`/`from_account` half of this threat does
  **not** reproduce: `_get_or_create_account` (backend/importer.py:110-116)
  silently creates a new account row for an unrecognized name rather than
  erroring — matching pre-existing project-wide convention. No crash, no leak,
  but also no rejection (out of scope for this threat's "500 leak" framing).
- This exact gap pre-dates Phase 14: the Phase-13 `create_portfolio_event` route
  (backend/main.py:426-442) has the identical `except ValueError`-only pattern.
  Phase 14 inherited it into 3 new routes without adding the missing
  `IntegrityError` catch, so the plan's own mitigation claim for T-14-07 is not
  actually true for the platform-reference vector.

**Disposition:** stays `mitigate` (not re-classified `accept`) — this is an
unintentional gap, not a reviewed and accepted risk. Severity `medium` is below
the phase's `block_on: high` threshold, so it does not block ship, but it is
tracked here for a follow-up fix: add `except IntegrityError as e: raise
HTTPException(422, detail=...)` (mirroring confirm_proposal's existing pattern
at main.py:1289-1291) to `create_funded_buy`, `create_funded_sell`, and
`create_investment_transfer`, or add an explicit `db.get(Platform, platform_id)`
existence check inside `apply_add_portfolio_event` before the insert.

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| T-14-04 | T-14-04 | apply_* primitives force `is_transfer=True` internally (closed in Phase 13, T-13-07); propose_*/REST callers verified to never re-derive or override it | Phase 13/14 plan authors | 2026-07-31 |
| T-14-SC | T-14-SC | No new runtime packages added this phase — verified via empty diff on requirements.txt/pyproject.toml across the Phase-14 commit range | Phase 14 plan authors | 2026-07-31 |

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-07-31 | 10 | 9 | 1 (non-blocking) | gsd-security-auditor |
| 2026-07-31 | 10 | 10 | 0 | /gsd-secure-phase (T-14-07 fixed via quick 260731-998, commit fc0bf73) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed (all 10 threats closed; T-14-07 remediated 2026-07-31)
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-07-31 — all 10 threats closed (T-14-07 fixed via quick task 260731-998, commit fc0bf73).
