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

### Tell the agent about this_week and last_week named periods

**What:** Add `this_week` and `last_week` to the system prompt's named-period list in `backend/query.py` (currently: all_time, this_month, last_month, this_year, last_year, last_30_days, last_90_days).

**Why:** `backend/tools.py`'s `PERIODS` tuple and `resolve_period` already support `this_week`/`last_week` as ISO Monday-Sunday calendar weeks, but the prompt never tells the model those names exist. Asked "how much did I spend last week," the agent falls back to a rolling 7-day custom range instead of the calendar week — an internally-honest answer to the wrong question, not a fabricated figure.

**Context:** Found while running the agent eval: the "last week" case (case 4) failed identically across 3 live runs, and a code read showed the gap is in the prompt, not the model. The fix is one line: add `this_week`/`last_week` to the named-period line in `backend/query.py`, then re-run `--case 4`.

**Effort:** S
**Priority:** P2

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

**Context:** No script or CI job exists for this yet; a cron job or a scheduled container command both work.

**Effort:** S
**Priority:** P1
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

**Context:** `backend/evals/agent_eval.py`. Run with `env -u DATABASE_URL .venv/bin/python -m backend.evals.agent_eval`. On the last recorded run, 11 of 12 cases passed (results depend on the configured model); case 4 ("last week") failed because of a real prompt gap, tracked above as "Tell the agent about this_week and last_week named periods" — not a defect in the eval itself.

**Effort:** M
**Priority:** P1
**Completed:** v1.4 (2026-10-03)
