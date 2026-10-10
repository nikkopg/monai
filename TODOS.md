# TODOS

The open-work list. `ARCHITECTURE.md` holds *decisions*; this holds *open work*.

## Agent / Chat

### Chat approve-flow Playwright spec

**What:** E2E spec: seed a proposal via the backend, mock the `/api/query-stream` SSE response, click Approve, and assert the resulting row shows up in Records; cover both the one-card and two-card cases.

**Why:** The core "ask, approve, see the change" flow has no automated browser coverage today — backend tests mock the LLM, so nothing exercises the real approve click end to end.

**Context:** The multi-proposal SSE shape (one card per proposal) and the isolated test database have both shipped. Known e2e trap: port 3001 can be a stale docker frontend left running from a previous session — use a temporary Playwright config pointed at a free port, not the project default.

**Effort:** M
**Priority:** P2
**Depends on:** isolated test database, one card per proposal (both shipped v1.4)
**Scheduled:** folded into the Capture Inbox plan (`docs/designs/capture-inbox.md`, eng review D11) and extended to cover Inbox approve. A statement batch and an MCP capture must each land in Records.

### Discord notification forwarding

**What:** Forward bank and e-wallet push notifications from an Android phone (Tasker/MacroDroid or an open-source forwarder) to the Capture Inbox Discord bot, so each payment becomes an uncleared capture seconds after it happens.

**Why:** It's the zero-typing version of capture. The weekly statement shrinks to a reconciliation diff.

**Context:** Cut from the Capture Inbox plan as stretch slice 5 (eng review D1). Notification text formats change without warning, so every parsed row must stay uncleared until a statement clears it. Start from `backend/discord_bot.py` once the bot exists.

**Effort:** L
**Priority:** P3
**Depends on:** Capture Inbox slice 2 (Discord bot)

### Recurring-charge / subscription detection (QRY-01)

**What:** A tool that flags transactions repeating at roughly the same amount and interval (e.g. monthly) as likely subscriptions.

**Why:** Completes the original "widen the query toolset" goal — the month-by-month trend half already shipped; this and period comparison are the open half.

**Context:** A new tool alongside `monthly_trend` and `spending_before_after_purchase` in `backend/tools.py`. No existing code attempts pattern detection across transactions.

**Effort:** M
**Priority:** P3

### Compare two arbitrary periods side by side (QRY-02)

**What:** A tool that takes two periods (or two custom ranges) and returns both totals plus the delta, instead of requiring two separate questions.

**Why:** The other open half of the original "widen the query toolset" item.

**Context:** `backend/tools.py` already resolves one period per call; this adds a second period argument and a diff in the response shape.

**Effort:** S
**Priority:** P3

## Investments

### Holdings derived only from portfolio_events

**What:** Rewrite add/edit/delete holding so each one appends an opening/adjustment/closing event, and the `holdings` table becomes a pure projection recomputed from `portfolio_events` — never edited directly.

**Why:** The current dual-write design (a ledger of events plus a directly editable holdings row) has already caused two bugs: a recompute that wiped a legacy holding's quantity because it had no backing events, and a deleted holding that could reappear on the next recompute.

**Context:** Start from `backend/writes.py`'s `apply_add_holding`, `apply_edit_holding`, `apply_delete_holding` and `backend/portfolio.py`'s `recompute_holding_from_events`. The investments UI's `HoldingModal` is the main caller whose save path would need updating. The current holding-delete-while-events-exist refusal is a stopgap, not the fix.

**Effort:** L
**Priority:** P2
**Depends on:** isolated test database (shipped v1.4)

### Holdings CSV import

**What:** Bulk-import broker positions as opening portfolio events (ticker, quantity, avg cost, purchase date, currency) once holdings are event-derived.

**Why:** Re-scoped down from a standalone holdings importer: manual entry in HoldingModal already covers the core need, so this is now a convenience for loading many positions at once, not a blocking gap.

**Context:** Demoted in priority because it depends on the event-derived rewrite above — building a bulk importer against the current dual-write holdings model would just add a third write path to migrate later.

**Effort:** M
**Priority:** P4
**Depends on:** Holdings derived only from portfolio_events

## Backend

### CSV importer tests

**What:** Tests for `importer.parse_csv`, `importer.import_csv_text`, and the `POST /import` happy path plus a bad-column 422.

**Why:** `POST /import` is covered only by the auth tests (which check the auth gate, not the import logic), and the parser has no direct test at all.

**Context:** Mirror the equivalent parser cases already written in `poc/tests` before `poc/` is removed, so that coverage isn't lost in the deletion.

**Effort:** S
**Priority:** P2
**Depends on:** None

### Split backend/main.py into per-domain APIRouters

**What:** Move main.py's routes into per-domain routers — cashflow, investments, categories, chat/proposals, settings, import.

**Why:** `backend/main.py` is 1604 lines and is the single most crowded file in the backend; one file for every route makes any change riskier than it needs to be.

**Context:** A mechanical, behavior-neutral move, not a redesign. Do it once the full test suite can prove nothing moved — the isolated test database makes that safe now. Keep the proposal executor next to the proposal routes rather than splitting them apart.

**Effort:** M
**Priority:** P3
**Depends on:** isolated test database (shipped v1.4)

### Multi-currency spending

**What:** Add `base_currency` + `fx_rate` to transactions so a foreign-currency spending account could be supported.

**Why:** Spending stays single-currency IDR by design — this was validated as a non-issue across the full import history. Investments already convert USD to IDR through the FX rate cache, which shipped early and is unrelated to this item.

**Context:** Revisit only if a foreign-currency spending account is actually added. No code change needed until then.

**Effort:** L
**Priority:** P4
**Depends on:** None

## Infrastructure / Ops

### Backup rotation

**What:** A scheduled `pg_dump` of the database, keeping 7 daily and 4 weekly dumps, with restic documented as the offsite upgrade.

**Why:** Nothing in the repo dumps the database today — the Postgres data volume is the only copy of the financial history.

**Context:** No script or CI job exists for this yet; a cron job or a scheduled container command both work. This now gates the Capture Inbox Wallet cutover (slice 4, eng review D3). Once Wallet is retired, no other copy of new transactions exists, so cutover waits until this ships and one restore has been verified.

**Effort:** S
**Priority:** P1
**Depends on:** None
**Blocks:** Capture Inbox slice 4 (Wallet cutover)

### Proxy hardening: session before key injection

**What:** Require a per-browser UI session (e.g. a signed httpOnly cookie set by a local login or a one-time pairing link) before the Next.js proxy injects `MONAI_API_KEY` or `MONAI_APPROVER_KEY`.

**Why:** The proxy adds keys to every request with no caller check, so any local process that can reach `127.0.0.1:3001` gets full write and approve. That includes a shell-capable AI agent, which can bypass the Capture Inbox MCP confirm-code gate.

**Context:** Start at `ui/app/api/[...proxy]/route.ts` (`headers.set("MONAI_API_KEY", API_KEY)`). Binding to 127.0.0.1 stays the outer control. Recorded by the Capture Inbox eng review (D13).

**Effort:** M
**Priority:** P2
**Depends on:** `MONAI_APPROVER_KEY` (Capture Inbox slice 1)

### DESIGN.md for the paper system

**What:** Run /design-consultation to write a DESIGN.md that captures the paper tokens in `ui/app/styles.ts` plus standing rules: the component map, status shown in words with no colored stripes, and the batch/check vocabulary.

**Why:** The design system lives only as code and in a local-only mockup, so every design review re-derives it, and decisions like the Capture Inbox's 10A/11A/12A live inside a single plan.

**Context:** Recorded by the Capture Inbox design review (13A). Start from `ui/app/styles.ts` and `docs/designs/capture-inbox.md` "Design decisions". A consultation can also revisit whether the cream/serif/terracotta look still fits.

**Effort:** S
**Priority:** P3
**Depends on:** None

### Hardware note in README

**What:** A README note on the RAM a local Ollama model needs, and that the cloud model needs outbound network access.

**Why:** Someone setting this up locally for the first time has no guidance on whether their machine can run the default model.

**Context:** README currently has no RAM/hardware section at all.

**Effort:** S
**Priority:** P3
**Depends on:** None

### Remove poc/

**What:** Delete the `poc/` directory (the Streamlit + SQLite throwaway prototype).

**Why:** Fully superseded by `backend/` + `ui/`; keeping it around risks someone mistaking it for a second supported path.

**Context:** Mirror its parser test cases into the backend importer tests first (see above) so nothing is lost on deletion.

**Effort:** S
**Priority:** P3
**Depends on:** CSV importer tests

### v2 / open-source release

**What:** A published container image and a pass over the public-facing README for a wider audience than the owner.

**Why:** CI already proves every push and PR, but there's no published image and the README is still written for a single self-hoster, not a general release.

**Context:** Defer until the app is in daily use — no urgency yet.

**Effort:** XL
**Priority:** P4
**Depends on:** None

## Out of scope (recorded so they don't get re-litigated)

Bank sync (PCI), budget tracking, multi-user, weather correlation, AI market-news
filtering. See `ARCHITECTURE.md`.

## Completed

### Approach A PoC

**What:** Wallet CSV import + LlamaIndex query layer, built as a throwaway Streamlit prototype.

**Why:** Proved the core idea (ask natural-language questions over imported spending data) before committing to a production stack.

**Context:** Lives in `poc/` (`app.py`, `load.py`, `query.py`). Scheduled for removal — see the open "Remove poc/" item.

**Effort:** M
**Priority:** P0
**Completed:** v0 prototype (2026-06-16)

### Approach C vertical slice

**What:** FastAPI + PostgreSQL + Next.js, replacing the Streamlit prototype.

**Why:** The production stack this app has run on ever since.

**Context:** `backend/`, `ui/`.

**Effort:** L
**Priority:** P0
**Completed:** v0 prototype (2026-06-20)

### Tool-router query layer

**What:** The LLM selects and chains parameterized tools instead of emitting SQL.

**Why:** Correctness-by-construction — the model can never generate an arbitrary query against real financial data.

**Context:** `backend/tools.py`'s `TOOLS` registry.

**Effort:** M
**Priority:** P0
**Completed:** v0 prototype (2026-06-20)

### Containerized backend + frontend

**What:** `docker compose` brings up the database, API and UI together.

**Why:** One-command local deploy.

**Context:** `docker-compose.yml`.

**Effort:** S
**Priority:** P0
**Completed:** v0 prototype (2026-06-20)

### Full-history import validated

**What:** The whole Wallet export history imports with zero skipped rows, in single-currency IDR.

**Why:** Confirms the importer handles the real shape of the owner's actual export, not just a small test file.

**Context:** Validated during the Approach A / early Approach C period.

**Effort:** S
**Priority:** P0
**Completed:** v0 prototype

### README matches a runnable app

**What:** README rewritten from "not usable yet" to an accurate quickstart.

**Why:** The app had been runnable for a while before the README caught up.

**Context:** `docker compose up -d --build`, then the documented ports for the UI and API.

**Effort:** S
**Priority:** P1
**Completed:** v1.0 (2026-07-18)

### CSV import in the UI

**What:** A file-upload control that posts to `/import` and refreshes.

**Why:** Without it, loading history required a manual script — not self-service for a fresh install.

**Context:** `ui/app/cashflow/CsvUpload.tsx`.

**Effort:** M
**Priority:** P1
**Completed:** v1.0 (2026-07-05)

### portfolio_events table

**What:** An append-only ledger of buy/sell/price events per holding.

**Why:** The foundation every later investments feature (the correlation tool, holding recompute) builds on.

**Context:** `PortfolioEvent` in `backend/models.py`.

**Effort:** M
**Priority:** P2
**Completed:** v1.0 (2026-06-21)

### Spending-vs-purchase correlation tool

**What:** "Since I bought X, how has my spending in category Y changed?"

**Why:** The unified spending + investment question this app is built to answer.

**Context:** `spending_before_after_purchase` in `backend/tools.py`.

**Effort:** M
**Priority:** P2
**Completed:** v1.0 (2026-07-11)

### Month-by-month spending trend tool

**What:** Spending totals broken out by calendar month over a window.

**Why:** The first of the two "widen the query toolset" items to ship; the other half (recurring-charge detection and period comparison) is still open above.

**Context:** `monthly_trend` in `backend/tools.py`.

**Effort:** S
**Priority:** P2
**Completed:** v1.0 (2026-07-05)

### Transfer pairing

**What:** A column linking the two legs of an internal transfer, with a parser heuristic that sets it automatically.

**Why:** Lets a transfer be treated as one event instead of two unrelated transactions.

**Context:** `Transaction.transfer_pair_id` in `backend/models.py`.

**Effort:** M
**Priority:** P2
**Completed:** v1.2 (2026-07-25)

### Localhost-only binding for DB, API and UI

**What:** The database, API and UI all bind to 127.0.0.1 instead of being reachable on the LAN.

**Why:** Closes an earlier LAN-exposure gap from the initial host-networking setup.

**Context:** `docker-compose.yml`, `backend/entrypoint.sh`, `ui/package.json`.

**Effort:** S
**Priority:** P1
**Completed:** v1.4 (2026-09-27)

### Isolated test database

**What:** The test suite runs against its own test database by default, with a guard refusing to run against the live one.

**Why:** An earlier out-of-pytest script hit the live database by accident; the suite needed its own safety rail.

**Context:** `backend/tests/conftest.py`'s refusal guard, mirrored by the agent eval below.

**Effort:** M
**Priority:** P1
**Completed:** v1.4 (2026-09-26)

### Backend CI on every push and PR

**What:** GitHub Actions runs the backend test suite against a fresh Postgres service on every push and PR.

**Why:** Catches a regression before it lands, not after.

**Context:** `.github/workflows/backend-tests.yml`.

**Effort:** S
**Priority:** P1
**Completed:** v1.4 (2026-09-26)

### Deploy timezone hardening

**What:** The container runs on Asia/Jakarta, and the backend logs a warning at startup if the process or database timezone doesn't match.

**Why:** A timezone mismatch between the app and the database would silently shift every date-bounded query.

**Context:** `docker-compose.yml`'s `TZ` setting and the startup check in `backend/main.py`'s lifespan.

**Effort:** S
**Priority:** P1
**Completed:** v1.4 (2026-09-27)

### Holding delete refused while events exist

**What:** Deleting a holding that still has ledger events raises instead of silently dropping history.

**Why:** Stopgap against the dual-write bug class the "Holdings derived only from portfolio_events" item above exists to fix properly.

**Context:** `backend/writes.py`'s `apply_delete_holding`.

**Effort:** S
**Priority:** P1
**Completed:** v1.4 (2026-09-27)

### One proposal card per proposal

**What:** A chat turn with multiple proposed changes renders one card per proposal instead of one shared card.

**Why:** A multi-item write (e.g. "add these two transactions") needs each change to be approvable on its own.

**Context:** `ui/app/chat/page.tsx`.

**Effort:** S
**Priority:** P1
**Completed:** v1.4 (2026-09-28)

### Opt-in agent eval

**What:** A hand-run script that drives the real agent loop against 12 golden questions and checks tool choice, args and answer numbers.

**Why:** The only path in the repo that exercises a real LLM end to end — a gate for model or prompt changes, not something CI runs.

**Context:** `backend/evals/agent_eval.py`. Run with `env -u DATABASE_URL .venv/bin/python -m backend.evals.agent_eval`. The last full run passed 11 of 12; case 4 ("last week") failed on a prompt gap that is now fixed, and passes when re-run with `--case 4`.

**Effort:** M
**Priority:** P1
**Completed:** v1.4 (2026-10-03)

### Tell the agent about this_week and last_week named periods

**What:** The prompt and the `spending_total` tool description now list the week periods, and a test keeps the prompt in step with the `PERIODS` tuple.

**Why:** `backend/tools.py`'s `PERIODS` tuple and `resolve_period` already supported `this_week`/`last_week` as ISO Monday-Sunday calendar weeks, but the prompt never told the model those names exist. Asked "how much did I spend last week," the agent fell back to a rolling 7-day custom range instead of the calendar week — an internally-honest answer to the wrong question, not a fabricated figure.

**Context:** `backend/query.py`'s `_SYSTEM_PROMPT` and `backend/tools.py`'s `spending_total` docstring now name both week periods; `backend/tests/test_agent.py::test_system_prompt_lists_every_named_period` fails if any non-custom `PERIODS` name is missing from either text.

**Effort:** S
**Priority:** P2
**Completed:** v1.4 (2026-10-03)
