# monai — Backlog

The durable task list. `ARCHITECTURE.md` holds *decisions*; this holds *open work*.
Grouped by when, not strictly ordered within a group.

## Done

- [x] Approach A PoC — Wallet CSV import + LlamaIndex query (commit `007d5ed`)
- [x] Approach C vertical slice — FastAPI + Postgres + Next.js (commit `19fc062`)
- [x] Query layer pivot — tool router (correct by construction), 21 tests (commit `19fc062`)
- [x] Containerize backend + frontend into `docker compose` (commit `d4a34ba`)
- [x] Validate on full 5-year history (5608 rows, 0 skipped, single currency IDR)

## Now (small, high-value — finishes a usable v1)

- [ ] **Update README** — it still says "not usable yet" / "Getting started: not ready."
      It IS runnable now: `docker compose up -d --build` → http://localhost:3001.
      Document the ports (5434/8001/3001) and the host-Ollama requirement.
- [ ] **CSV import in the UI** — the `/import` endpoint exists but the page has no
      upload control, so loading history needs a manual script. Add a file-upload
      button that POSTs to `/import` and refreshes. Without this the app isn't
      self-service for a fresh install.
- [ ] **Backend API + importer tests** — only `tools.py` and the router JSON parser
      are tested. Add tests for `/transactions` (create+list), `/import` (happy path
      + bad-column 422), and `importer.parse_csv` (mirror the PoC parser tests).

## Security / ops (before trusting it with real data long-term)

- [ ] **Access binding** — containerizing put the backend on `network_mode: host`
      with `--host 0.0.0.0`, so the API is reachable on the LAN at `<machine>:8001`,
      not just localhost. The design doc wanted localhost-only for v1. Decide:
      bind 127.0.0.1, add the `MONAI_API_KEY` check, or accept LAN exposure and
      document it.
- [ ] **Backup rotation** (eng-review D6) — cron: keep 7 daily + 4 weekly dumps of
      the `monai_pgdata` volume (`pg_dump`). Document restic as the offsite upgrade.
- [ ] **Hardware note in README** — Ollama RAM (local models) + the cloud-model
      caveat (needs network to ollama.com).

## Next (v1.1 — the actual differentiator: investments)

- [ ] **Holdings CSV import** (eng-review D13) — schema locked:
      `ticker, quantity, avg_cost, purchase_date, currency`. Add `holdings` table,
      importer, and `/holdings` endpoints.
- [ ] **portfolio_events table** — `(id, date, ticker, event_type, price)`, needed
      for correlation queries.
- [ ] **Correlation query tools** — e.g. "since I bought NVDA, how has my eating-out
      spending changed?" New tools in `tools.py` joining spending + portfolio events.
      This is the unified spending+investment AI that no other self-hosted tool has.
- [ ] **Widen the query toolset** — current tools cover totals/categories/counts/
      largest/averages. Add: spending trend over time (month-by-month), compare two
      periods, recurring-charge / subscription detection.

## Later / parked

- [ ] **`transfer_pair_id`** (eng-review D11) — add with FK + uniqueness constraint
      + a parser heuristic to link paired transfers, once a real need appears.
      Currently `is_transfer` flag alone is enough (655 transfers flagged correctly).
- [ ] **Multi-currency** (eng-review D12) — `base_currency` + `fx_rate`. **Parked:**
      validated as a non-issue (0 rows skipped across 5608). Only revisit if a
      foreign-currency account is added.
- [ ] **Remove `poc/`** — Approach A is throwaway by design and fully superseded by
      `backend/`. Delete once you're confident you won't need it as reference.
- [ ] **v2 / open-source release** — CI, Docker Hub image, public README. Per the
      design doc, don't plan this until v1.1 is in daily use.

## Out of scope (recorded so they don't get re-litigated)

Bank sync (PCI), budget tracking, multi-user, weather correlation, AI market-news
filtering. See `ARCHITECTURE.md` and the design doc.
