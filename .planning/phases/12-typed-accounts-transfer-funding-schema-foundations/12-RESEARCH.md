# Phase 12: Typed Accounts + Transfer/Funding Schema Foundations - Research

**Researched:** 2026-07-25
**Domain:** Alembic data migration on live financial Postgres — nullable→backfill→constrain column tightening + a structural-exclusion DB view + additive nullable FK columns
**Confidence:** HIGH (grounded in-repo: migration `009_category_hierarchy.py` is a near-exact precedent; all claims verified against source files this session)

## Summary

This is an **additive schema + one data migration** phase with almost no research surface: the repo already contains the exact idiom this phase needs. Migration `009_category_hierarchy.py` is a live-data, idempotent, abort-loudly, parity-asserted backfill wrapped in Alembic's single-transaction online model (`env.py` L72–73). Phase 12 reuses that skeleton on a much smaller dataset (4 accounts vs. 74 category strings), plus two mechanical additions: a `CREATE VIEW cashflow_transactions` and two nullable indexed columns.

The three technical pillars are all low-risk given the precedent: (1) tighten `accounts.type` from `String(64) NULL` → backfilled from D-02's hard-coded 4-row map → `CHECK(type IN ('liquid','investment'))` + `NOT NULL` + `server_default 'liquid'`; (2) a `cashflow_transactions` view that removes investment-account rows via **`NOT EXISTS`** (the one non-obvious correctness point — it is the clause that keeps NULL-`account_id` rows IN the view, which `NOT IN` silently drops); (3) add `transactions.transfer_pair_id` and `portfolio_events.source_account_id` (nullable, indexed) for Phase 13 to write later. No new packages, no UI, no write mechanics, no tool registration.

The one behavioral gotcha to verify (research focus #4) resolves cleanly: `importer._get_or_create_account` constructs `Account(name, currency)` with no `type`, so once the column is `NOT NULL server_default 'liquid'`, the INSERT still succeeds — SQLAlchemy omits the unset column and Postgres fills the default. The model's `Account.type` should be updated to reflect the server_default so the ORM matches the DB.

**Primary recommendation:** Clone the `009` migration structure into `010_typed_accounts.py`. Order `upgrade()`: guarded backfill of the 4 rows from a hard-coded `ACCOUNT_TYPE` dict → abort-loudly assert (exactly the 4 audited ids present, zero NULL types remaining) → CHECK constraint → `NOT NULL` + `server_default 'liquid'` → add the two additive columns → `CREATE VIEW cashflow_transactions` using `NOT EXISTS`. Then switch every cashflow **total** in `tools.py` from `FROM transactions` to `FROM cashflow_transactions`. Prove the fix with a before/after delta equal to the "Investments" account's expense magnitude (~45.9M IDR).

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** `accounts.type` is a **binary** closed set: `liquid` | `investment`, enforced by a CHECK constraint. Gates exactly the cashflow rule (`type='investment'` → excluded). No richer subtype set (no cash/bank/e-wallet split) — a separate cosmetic concern for a later phase.
- **D-02:** The 4 live accounts classify as:
  - `liquid`: **BCA** (id 2), **Cash** (id 1), **Stockbit** (id 559)
  - `investment`: **Investments** (id 3)
- **D-03:** **Stockbit is liquid, deliberately** — broker *cash* account (RDN balance that funds buys), distinct from stock positions in `holdings`/`platforms`. It is a valid liquid `source_account_id` when Phase 13 funds a buy. Do NOT re-infer it as investment from its name.
- **D-04:** The "Investments" account (id 3) is the real double-count: its −45.9M of non-transfer transactions are investment contributions booked as expenses. Typing it `investment` + the exclusion view removes that phantom spending from every cashflow total.
- **D-05:** After backfill, `accounts.type` becomes **NOT NULL** + CHECK(`liquid`,`investment`) + `server_default 'liquid'`. New/imported accounts (incl. `_get_or_create_account`) auto-get `liquid`; rare investment accounts re-typed by hand.
- **D-06:** Exclusion predicate keys on `type = 'investment'` (exclude only explicit investment), NOT `type != 'liquid'`. Failure mode of a mis-typed/new account is "shows up in cashflow" (visible, catchable), never "silently vanishes" (invisible). Aligns with never-fabricate / honest-failure.
- **D-07:** The migration creates a **`cashflow_transactions` DB view** = transactions minus investment-account rows. Every cashflow total in `backend/tools.py` reads `FROM cashflow_transactions`. Exclusion lives in the schema — any query inherits it (chosen over an app-level helper, which stays convention).

### Claude's Discretion
- **Exact DDL / Alembic revision structure** for migration `010`: column-type change to NOT NULL, CHECK syntax, index choices for `transfer_pair_id`/`source_account_id`, FK naming. Follow the repo-root `alembic/versions/` idiom and Phase 11's non-destructive, idempotent, parity-checked precedent.
- **View internals:** (a) MUST keep NULL-`account_id` rows IN (use `LEFT JOIN`/`NOT EXISTS`/`account_id NOT IN (investment ids)`, never an inner join that drops them) — **hard requirement, not discretion**; (b) whether the view also bakes in `is_transfer = false` or leaves that in the per-query SQL — pick cleanest.
- **Column semantics for the pairing columns:** `transfer_pair_id` self-referential vs shared-group-id; `source_account_id` FK target/index — planner's call, consistent with locked roles.
- **Whether the investment account is also removed from / shown separately in `account_balances`** (a per-account list, not a total). Criterion #2 targets the spending/income/net *totals*; `account_balances` is out of the strict criterion but worth a consistency note.

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within scope. Richer account subtypes were considered and explicitly rejected (D-01). Reconciling the "Investments" account's historical −45.9M against holdings/portfolio is Phase 13/15 territory, not a new idea.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ACCT-03 | Accounts are typed liquid/investment (DB-enforced after live audit + backfill); investment-typed accounts are excluded from cashflow totals — the double-count fix. | Standard Stack (Alembic nullable→backfill→constrain idiom, verified against `009`), Architecture Patterns (the `cashflow_transactions` `NOT EXISTS` view + `tools.py` `FROM` switch), Common Pitfalls (NULL-`account_id` drop, `NOT IN` NULL trap, `SET NOT NULL` requires zero NULLs), Validation Architecture (the three success-criterion proofs). |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| `accounts.type` classification + constraint | Database / Storage | — | A CHECK constraint + NOT NULL is DB-enforced by construction; app code can't emit an invalid type. |
| Cashflow exclusion of investment rows | Database / Storage (view) | API / Backend (`tools.py` `FROM` switch) | The view owns the invariant; `tools.py` inherits it by reading the view instead of the base table. Structural, not conventional (D-07). |
| Backfill of the 4 live accounts | Database / Storage (migration) | — | One-time data migration from a hard-coded human-audited map (D-02); no runtime code path. |
| Pairing columns (`transfer_pair_id`, `source_account_id`) | Database / Storage | — | Additive nullable columns; no writer this phase (Phase 13 populates). |
| Importer default typing | API / Backend (`importer.py`) | Database / Storage (`server_default`) | New CSV accounts get `liquid` from the DB default; the importer stays unchanged. |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Alembic | installed (repo has `alembic/` at root, migrations 001–009) | The migration `010` DDL + data backfill | Already the sole schema-management tool; `db.py` docstring: "Schema is fully Alembic-managed… no `init_db()`." `[VERIFIED: backend/db.py L1–6]` |
| SQLAlchemy | >=2.0.0 | `sa.inspect()` idempotency guards, `op.*` DDL helpers, `text()` parameterized backfill | Established repo idiom; migration `009` uses exactly this. `[VERIFIED: alembic/versions/009_category_hierarchy.py]` |
| PostgreSQL | 16-alpine | CHECK constraint, `CREATE VIEW`, partial/plain indexes | Target DB; view + CHECK are native. `[CITED: CLAUDE.md Technology Stack]` |
| psycopg[binary] | >=3.1.0 | driver (returns `Decimal` for `Numeric`) | Existing driver; no money columns added this phase so precision is not touched. `[VERIFIED: backend/models.py L129–131 note]` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest | >=8.0.0 | Migration-helper unit tests + view/introspection assertions | Mirror `test_category_migration.py` (pure-function tests, no DB) for the id→type map; add DB-level view invariant tests. `[VERIFIED: backend/tests/test_category_migration.py]` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `cashflow_transactions` DB view (D-07) | An app-level shared `FROM`/helper in `tools.py` | Rejected by D-07: a helper stays convention (forgettable by future/ad-hoc queries); a view makes exclusion structural. |
| `NOT EXISTS` in the view | `account_id NOT IN (SELECT id FROM accounts WHERE type='investment')` | Both work *only if* NULL-`account_id` is handled. `NOT IN` returns NULL (→ row excluded) for NULL `account_id` unless you add `account_id IS NULL OR …`. `NOT EXISTS` handles NULL correctly with no extra clause — safer default. |
| Materialized view | Plain view | No — balances/totals must be live; a plain view re-evaluates every query with zero staleness. |

**Installation:** None. No new packages. Everything (Alembic, SQLAlchemy, pytest, psycopg3, Postgres 16) is already in `backend/requirements.txt` / the compose stack.

## Package Legitimacy Audit

**Not applicable — this phase installs zero external packages.** It is a schema migration + edits to existing `tools.py`/`models.py` using already-present dependencies. No registry verification required.

## Architecture Patterns

### System Architecture Diagram

```
                    migration 010_typed_accounts.py  (one Alembic transaction, env.py L72–73)
                    ────────────────────────────────────────────────────────────────────
  D-02 hard-coded          │ 1. backfill: UPDATE accounts SET type=:t WHERE id=:id AND type IS NULL
  ACCOUNT_TYPE map ────────┤ 2. ABORT-LOUDLY assert: exactly {1,2,3,559} present · 0 NULL types left
  {1:liquid, 2:liquid,     │ 3. CHECK (type IN ('liquid','investment'))     ← constraint
   3:investment,           │ 4. ALTER type SET NOT NULL, SET DEFAULT 'liquid'
   559:liquid}             │ 5. ADD transactions.transfer_pair_id (null, idx)
                           │    ADD portfolio_events.source_account_id (null, idx, FK→accounts.id)
                           │ 6. CREATE VIEW cashflow_transactions AS
                           │       SELECT t.* FROM transactions t
                           │       WHERE NOT EXISTS (SELECT 1 FROM accounts a
                           │                          WHERE a.id=t.account_id AND a.type='investment')
                           ▼
   accounts (typed) ──┐         cashflow_transactions (view)  ── excludes investment-acct rows,
   transactions ──────┼────────▶                                  KEEPS NULL-account_id rows
   portfolio_events ──┘                    │
                                           ▼
                    backend/tools.py cashflow TOTALS switch FROM transactions → FROM cashflow_transactions
                    spending_total · income_total · net_total · spending_by_category (_ROLLUP_FROM)
                    · average_daily_spending · monthly_trend · transaction_count
                                           │
                                           ▼
                    REST /cashflow/summary · agent read tools  (unchanged call sites; SQL string only)
```

### Component Responsibilities
| File | Change | Detail |
|------|--------|--------|
| `alembic/versions/010_typed_accounts.py` (new) | Whole migration | `revision` = new hash; `down_revision = "e5f6a7b8c9d0"` (009's revision id). `[VERIFIED: 009 L51–52]` |
| `backend/models.py` L46–52 (`Account.type`) | `Mapped[str]`, `nullable=False`, `server_default="liquid"` | Reflect the DB state so the ORM matches and refreshes the value. Also add `transfer_pair_id` (Transaction) and `source_account_id` (PortfolioEvent) mappings. |
| `backend/tools.py` | Swap `FROM transactions` → `FROM cashflow_transactions` in every cashflow **total** | Parameterized `text()` SQL otherwise unchanged; the view exposes `t.*` so `amount`, `is_transfer`, `date`, `category_id`, `account_id` all remain. |

### Recommended Migration Structure (mirrors `009`)
```
upgrade():
  inspector = sa.inspect(op.get_bind()); conn = op.get_bind()
  # 0. (guard) if 'type' column missing, add nullable — normally already present (models.py L51)
  # 1. backfill from hard-coded ACCOUNT_TYPE (D-02), idempotent + non-clobbering:
  #    for id, t in ACCOUNT_TYPE.items():
  #        conn.execute(text("UPDATE accounts SET type=:t WHERE id=:id AND type IS NULL"), {...})
  # 2. ABORT-LOUDLY assertions (the account analog of 009's unmapped-string abort):
  #    live_ids = {r[0] for r in conn.execute(text("SELECT id FROM accounts"))}
  #    if live_ids != set(ACCOUNT_TYPE):  raise RuntimeError(naming the unexpected/missing ids)
  #    null_types = conn.execute(text("SELECT COUNT(*) FROM accounts WHERE type IS NULL")).scalar()
  #    if null_types:  raise RuntimeError(...)
  # 3. CHECK constraint (guard: name not in inspector.get_check_constraints('accounts')):
  #    op.create_check_constraint("ck_accounts_type", "accounts", "type IN ('liquid','investment')")
  # 4. tighten:
  #    op.alter_column("accounts", "type", existing_type=sa.String(64),
  #                    nullable=False, server_default="liquid")
  # 5. additive columns (each guarded against inspector.get_columns/get_indexes/get_foreign_keys):
  #    op.add_column("transactions", sa.Column("transfer_pair_id", sa.Integer(), nullable=True))
  #    op.create_index("ix_transactions_transfer_pair_id", "transactions", ["transfer_pair_id"])
  #    op.add_column("portfolio_events",
  #        sa.Column("source_account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=True))
  #    op.create_index("ix_portfolio_events_source_account_id", "portfolio_events", ["source_account_id"])
  # 6. view (guard: 'cashflow_transactions' not in inspector.get_view_names()):
  #    op.execute("CREATE VIEW cashflow_transactions AS SELECT t.* FROM transactions t "
  #               "WHERE NOT EXISTS (SELECT 1 FROM accounts a "
  #               "WHERE a.id = t.account_id AND a.type = 'investment')")
  # 7. proof assertions (see Validation Architecture) — optional but matches 009's self-check ethos

downgrade():  # strict reverse; leaves backfilled type VALUES in place (009 philosophy)
  op.execute("DROP VIEW IF EXISTS cashflow_transactions")
  op.drop_index("ix_portfolio_events_source_account_id", "portfolio_events")  # guarded
  op.drop_column("portfolio_events", "source_account_id")
  op.drop_index("ix_transactions_transfer_pair_id", "transactions")
  op.drop_column("transactions", "transfer_pair_id")
  op.alter_column("accounts", "type", existing_type=sa.String(64),
                  nullable=True, server_default=None)
  op.drop_constraint("ck_accounts_type", "accounts", type_="check")
```

### Pattern 1: Idempotent, abort-loudly data migration (the `009` idiom)
**What:** Every structural step is guarded by an `sa.inspect()` existence check so `upgrade()` is safely re-runnable; every data step aborts with a `RuntimeError` naming the offending rows rather than proceeding partially. Alembic wraps `run_migrations()` in one `begin_transaction()` so any raise rolls back the whole migration cleanly.
**When to use:** This migration, exactly.
**Example:**
```python
# Source: alembic/versions/009_category_hierarchy.py L138–166, L260–271 (verified this session)
inspector = sa.inspect(op.get_bind())
tx_columns = {c["name"] for c in inspector.get_columns("transactions")}
if "category_id" not in tx_columns:
    op.add_column("transactions", sa.Column("category_id", sa.Integer(), nullable=True))
# ...
unmapped = find_unmapped(distinct_strings, mapping)
if unmapped:
    raise RuntimeError(f"Category migration abort — unmapped category strings: {unmapped}")
```
```python
# env.py L72–73 — single-transaction online model → a raised RuntimeError = clean full rollback
with context.begin_transaction():
    context.run_migrations()
```

### Pattern 2: The `NOT EXISTS` exclusion view (keeps NULL-`account_id` rows)
**What:** A plain (non-materialized) view listing all transactions except those whose account is investment-typed. `NOT EXISTS` returns true for a NULL `account_id` (the correlated subquery is empty), so NULL-account rows are **kept** — the hard requirement in D-07.
**When to use:** The one view this phase creates.
**Example:**
```sql
-- keys on type='investment' only (D-06 honest-failure); NULL account_id stays IN the view
CREATE VIEW cashflow_transactions AS
SELECT t.* FROM transactions t
WHERE NOT EXISTS (
  SELECT 1 FROM accounts a
  WHERE a.id = t.account_id AND a.type = 'investment'
);
```
Then in `tools.py`, the only change per tool is the table name:
```python
# spending_total (backend/tools.py L126–129) — before → after
"SELECT COALESCE(SUM(-amount), 0) FROM cashflow_transactions "     # was: FROM transactions
"WHERE amount < 0 AND is_transfer = false" + _date_clause(s, e, p)
```

### Anti-Patterns to Avoid
- **Inner-joining accounts in the view.** `FROM transactions t JOIN accounts a ON a.id=t.account_id WHERE a.type<>'investment'` drops every NULL-`account_id` row — silently deletes them from all cashflow totals. Use `NOT EXISTS`.
- **`account_id NOT IN (SELECT id FROM accounts WHERE type='investment')` without the NULL guard.** `NULL NOT IN (…)` evaluates to NULL → the NULL-account row is excluded. Only safe as `account_id IS NULL OR account_id NOT IN (…)`. `NOT EXISTS` avoids the footgun entirely.
- **`SET NOT NULL` before backfilling.** Postgres rejects `ALTER … SET NOT NULL` while any row is NULL — all 4 rows are NULL today (`models.py` L51 note). Backfill + assert-zero-NULL must precede the tighten.
- **`type != 'liquid'` as the exclusion predicate.** Violates D-06 — a new/mis-typed account would vanish from totals invisibly. Key on `= 'investment'`.
- **`SELECT *` reads against the view.** The view's `t.*` freezes the column list at creation time; a future migration adding a `transactions` column won't appear in the view until it's recreated. `tools.py` already selects explicit columns, so keep it that way (don't introduce `SELECT * FROM cashflow_transactions`).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Investment-row exclusion in every query | A shared Python `WHERE` fragment appended in each tool | The `cashflow_transactions` view | D-07: a view is structural (inherited by any query); a fragment is convention (forgettable). |
| NULL-`account_id` handling | Manual `IS NULL OR …` branches | `NOT EXISTS` | One clause, correct on NULL by construction. |
| Idempotency of DDL | Ad-hoc try/except around `op.*` | `sa.inspect()` existence guards (009 idiom) | Deterministic, readable, matches the repo. |
| Importer default type | Passing `type='liquid'` at every call site | `server_default='liquid'` on the column | DB fills it on any INSERT that omits `type`, incl. `_get_or_create_account`. |

**Key insight:** The exclusion invariant and the future-account safety both belong in the schema (view + CHECK + server_default), not in Python. That is the entire point of D-05/D-06/D-07 — make the correct behavior the default the DB enforces, so no code path (present or future) can forget it.

## Runtime State Inventory

> This is a schema/data migration on the live dev DB. Grep finds files, not runtime state — here is the explicit audit.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| **Stored data** | `accounts` table: 4 live rows (ids 1,2,3,559), all `type IS NULL` today. `[VERIFIED: models.py L51 note + CONTEXT D-02, live-verified in the discuss session]` | **Data migration** — backfill from the D-02 map (in migration 010). |
| **Live service config** | None. No external service stores an account type. | None — verified: type is a monai-internal DB column only. |
| **OS-registered state** | None. No scheduler/daemon references account type. | None. |
| **Secrets/env vars** | None. No env var names the account type or these columns. | None. |
| **Build artifacts / installed packages** | `models.py` ORM must be re-read by the running container after migration; committed code ≠ running container (memory: "Deploy requires rebuild"). | `docker compose up -d --build` before any live verification. |

**The canonical question — after every file is updated, what still holds the old state?** The live Postgres volume (`monai_pgdata`): the 4 account rows stay NULL until migration 010 runs against the live DB. The migration is the only thing that changes them; there is no other cache of account type.

## Common Pitfalls

### Pitfall 1: NULL-`account_id` rows silently dropped from cashflow
**What goes wrong:** An inner join or bare `NOT IN` in the view excludes transactions with no account, deleting them from every total.
**Why it happens:** SQL three-valued logic — `NULL NOT IN (…)` is NULL, not TRUE; an inner join has no row to match.
**How to avoid:** `NOT EXISTS` (correlated subquery empty for NULL `account_id` → row kept). Assert in a test that `COUNT(*) WHERE account_id IS NULL` is identical in `transactions` and `cashflow_transactions`.
**Warning signs:** `spending_total` from the view is *lower* than expected by more than the investment account's magnitude.

### Pitfall 2: `SET NOT NULL` fails because rows are still NULL
**What goes wrong:** `ALTER … SET NOT NULL` errors out because all 4 rows are NULL at migration start.
**Why it happens:** Ordering — the tighten ran before the backfill.
**How to avoid:** Backfill → assert zero NULL → *then* CHECK + NOT NULL + default. (Same order 009 uses for `category_id`, minus the deferred NOT NULL.)
**Warning signs:** `column "type" contains null values` from Postgres during `alembic upgrade`.

### Pitfall 3: An unaudited 5th account appears before migration runs
**What goes wrong:** A new account was created (e.g. by the importer) between the D-02 audit and the migration; the hard-coded 4-row map doesn't cover it, so it'd get whatever the tighten defaults to.
**Why it happens:** Live DB drift.
**How to avoid:** Abort-loudly: assert `set(live account ids) == {1,2,3,559}` before constraining; raise naming the extra/missing id so a human classifies it. This is the account analog of 009's unmapped-string abort and makes success-criterion #1 ("none auto-inferred") true at migration time, while `server_default 'liquid'` makes it permanent thereafter.
**Warning signs:** Migration raises `RuntimeError` naming an unexpected account id — that's the guard working, not a bug.

### Pitfall 4: ORM `Account.type` left as nullable in `models.py`
**What goes wrong:** DB says NOT NULL + default 'liquid'; the model still says `nullable=True` with no `server_default`. INSERTs still work (DB fills the default), but the in-memory object keeps `type=None` after flush (compounded by `expire_on_commit=False` in `db.py` L17), so any read-back before refresh sees stale `None`.
**Why it happens:** Model not updated to match the migration.
**How to avoid:** Update `Account.type` to `Mapped[str] = mapped_column(String(64), nullable=False, server_default="liquid")`. Harmless for the importer (it never reads `type` back) but correct for every other consumer.
**Warning signs:** New account objects report `type is None` immediately after commit in the same session.

### Pitfall 5: View column list frozen at creation
**What goes wrong:** A later migration adds a `transactions` column; `SELECT * FROM cashflow_transactions` doesn't show it.
**Why it happens:** Postgres expands `SELECT t.*` at view-definition time.
**How to avoid:** Create the view *after* adding this phase's columns (so `transfer_pair_id` is included as a harmless superset), and keep `tools.py` selecting explicit columns. Recreate the view in any future migration that adds a column the view must expose.

## Code Examples

### Backfill the 4 rows (idempotent, non-clobbering)
```python
# Pattern from 009 L289–296, adapted (verified this session)
ACCOUNT_TYPE = {1: "liquid", 2: "liquid", 3: "investment", 559: "liquid"}  # D-02
for acct_id, t in ACCOUNT_TYPE.items():
    conn.execute(
        sa.text("UPDATE accounts SET type = :t WHERE id = :id AND type IS NULL"),
        {"t": t, "id": acct_id},
    )
```

### Abort-loudly account audit assertion
```python
live_ids = {r[0] for r in conn.execute(sa.text("SELECT id FROM accounts"))}
if live_ids != set(ACCOUNT_TYPE):
    raise RuntimeError(
        f"Typed-accounts migration abort — live account ids {sorted(live_ids)} "
        f"do not match the audited set {sorted(ACCOUNT_TYPE)}; classify new/missing "
        "accounts in ACCOUNT_TYPE (D-02) before re-running."
    )
null_types = conn.execute(sa.text("SELECT COUNT(*) FROM accounts WHERE type IS NULL")).scalar()
if null_types:
    raise RuntimeError(f"{null_types} accounts still NULL after backfill")
```

### The double-count proof (criterion #2, concrete)
```python
# investment-account expense magnitude that must disappear from cashflow after the view
raw = conn.execute(sa.text("SELECT COALESCE(SUM(-amount),0) FROM transactions "
    "WHERE amount < 0 AND is_transfer = false")).scalar()
view = conn.execute(sa.text("SELECT COALESCE(SUM(-amount),0) FROM cashflow_transactions "
    "WHERE amount < 0 AND is_transfer = false")).scalar()
inv = conn.execute(sa.text("SELECT COALESCE(SUM(-amount),0) FROM transactions t "
    "JOIN accounts a ON a.id=t.account_id "
    "WHERE a.type='investment' AND t.amount < 0 AND t.is_transfer = false")).scalar()
assert raw - view == inv        # the ~45.9M "Investments" phantom spend, removed by construction
```

### Importer still works (research focus #4 — verified)
```python
# backend/importer.py L110–116 — constructs Account WITHOUT type
acc = Account(name=name, currency=currency)   # type omitted
db.add(acc); db.flush()
# With DB `type NOT NULL DEFAULT 'liquid'`, SQLAlchemy omits the unset column,
# Postgres fills 'liquid'. INSERT succeeds. No importer change needed (D-05).
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `accounts.type` decorative `String(64) NULL` | DB-enforced `CHECK(liquid,investment) NOT NULL DEFAULT 'liquid'` | This phase | Type becomes a real discriminator; new accounts default to the safe included case. |
| Cashflow reads `FROM transactions`, exclusion by convention | Reads `FROM cashflow_transactions`; exclusion structural | This phase | The double-count is impossible to reintroduce in any query. |

**Deprecated/outdated:** Nothing removed. Additive only.

## Validation Architecture

> `workflow.nyquist_validation: true` (config.json) — this section is required.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest >=8.0.0 |
| Config file | none dedicated found; tests live in `backend/tests/`, run against the **live dev DB** (see `conftest.py` — no fresh-migrate fixture; the suite assumes migrations already applied). `[VERIFIED: backend/tests/conftest.py]` |
| Quick run command | `python -m pytest backend/tests/test_typed_accounts.py -x` (or via `uv run` per project dev runner) |
| Full suite command | `python -m pytest backend/tests/` |

Two test shapes, matching the `009` precedent:
- **Pure-function tests (no DB)** — mirror `test_category_migration.py`: assert the `ACCOUNT_TYPE` map covers exactly {1,2,3,559} with the D-02 values, and (optionally) unit-test any helper that builds the view SQL.
- **DB invariant tests** — run against the live dev DB *after* migration 010, asserting the view/column/constraint facts below.

### Phase Requirements → Test Map
| Req / Criterion | Behavior | Test Type | Automated Command | File Exists? |
|-----------------|----------|-----------|-------------------|-------------|
| Criterion 1 (4-account audit) | Every account row `type IN ('liquid','investment')`, none NULL, and matches D-02 (1,2,559=liquid; 3=investment) | unit + DB | `pytest backend/tests/test_typed_accounts.py::test_account_classification -x` | ❌ Wave 0 |
| Criterion 2 (structural exclusion) | (a) no investment-account row in `cashflow_transactions`; (b) NULL-`account_id` rows present in view; (c) `raw_spending − view_spending == investment_expense` (the −45.9M) | DB | `pytest backend/tests/test_cashflow_view.py -x` | ❌ Wave 0 |
| Criterion 3 (pairing columns) | `transactions.transfer_pair_id` and `portfolio_events.source_account_id` exist, nullable, indexed | DB introspection | `pytest backend/tests/test_typed_accounts.py::test_pairing_columns -x` | ❌ Wave 0 |
| Constraint enforcement | INSERT with `type='bogus'` rejected; INSERT omitting `type` yields `'liquid'` | DB | `pytest backend/tests/test_typed_accounts.py::test_type_check_and_default -x` | ❌ Wave 0 |
| Migration idempotency | `upgrade()` re-runnable; guards no-op on second pass | DB | part of the migration test | ❌ Wave 0 |

Criterion 3 introspection example:
```python
insp = sa.inspect(engine)
tx = {c["name"]: c for c in insp.get_columns("transactions")}
assert tx["transfer_pair_id"]["nullable"] is True
assert any("transfer_pair_id" in ix["column_names"] for ix in insp.get_indexes("transactions"))
pe = {c["name"]: c for c in insp.get_columns("portfolio_events")}
assert pe["source_account_id"]["nullable"] is True
assert any("source_account_id" in ix["column_names"] for ix in insp.get_indexes("portfolio_events"))
```

### Sampling Rate
- **Per task commit:** `python -m pytest backend/tests/test_typed_accounts.py backend/tests/test_cashflow_view.py -x`
- **Per wave merge:** `python -m pytest backend/tests/` (full suite — catches any cashflow tool whose SQL wasn't switched to the view)
- **Phase gate:** Full suite green + a live `docker compose up -d --build` then a manual `spending_total`/`net_total` check showing the −45.9M gone, before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] `backend/tests/test_typed_accounts.py` — classification, CHECK+default, pairing-column introspection (covers Criteria 1 & 3, ACCT-03)
- [ ] `backend/tests/test_cashflow_view.py` — view invariants + double-count-delta proof (covers Criterion 2, ACCT-03)
- [ ] (optional) `backend/tests/test_typed_accounts_migration.py` — pure-function test of the `ACCOUNT_TYPE` map + abort-loudly helper, mirroring `test_category_migration.py`
- No framework install needed (pytest present).

## Security Domain

> `security_enforcement` absent in config → treated as enabled. Surface is tiny (a schema migration with no user input).

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V5 Input Validation | partial | The backfill map is hard-coded constants (D-02), not user input. All migration + `tools.py` SQL uses `text()` bound parameters — never string interpolation of external data. The one interpolated fragment is the table name `cashflow_transactions` (a code constant, not data). `[VERIFIED: 009 uses bound params throughout; tools.py L127 etc.]` |
| V6 Cryptography | no | No crypto in scope. |
| V2/V3/V4 (authn/session/access) | no | No auth surface touched; migration runs in the trusted entrypoint. |

### Known Threat Patterns for this stack
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection via backfill/view SQL | Tampering | All values bound via `sa.text(...)` parameters; the only string-built identifiers are code constants. No external input reaches SQL this phase. |
| Silent data loss (rows vanishing from totals) | Tampering / Repudiation | The `NOT EXISTS` view + the D-06 `='investment'` predicate ensure the failure mode is "over-includes visibly," never "drops silently"; parity/delta assertions catch drift. |

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| PostgreSQL | migration + view | ✓ (compose `db` :5434, `postgres:16-alpine`) | 16 | — |
| Alembic | migration 010 | ✓ (`alembic/versions/001–009` present) | installed | — |
| SQLAlchemy | `op`/`inspect`/`text` | ✓ | >=2.0.0 | — |
| pytest | validation tests | ✓ | >=8.0.0 | — |
| Docker Compose | live verification (rebuild) | ✓ | — | — |

**Missing dependencies with no fallback:** None.
**Missing dependencies with fallback:** None. All required tooling is already in the stack.

## Open Questions

1. **Should `account_balances`, `largest_transactions`, and `find_transactions` also read the view?** (D-07 discretion + CONTEXT discretion item D)
   - What we know: strict criterion #2 targets the spending/income/net **totals**. `account_balances` (L472) already `LEFT JOIN`s `accounts` and is a per-account list, not a total.
   - What's unclear: whether the investment account should show a balance there (arguably yes, shown separately) and whether investment rows should surface in "largest expense" / transaction search.
   - Recommendation: switch the pure **totals** (spending/income/net/by-category/avg-daily/monthly-trend/count) to the view — required. For `largest_transactions` and `find_transactions`, switch too for consistency (an investment contribution shouldn't rank as a top expense). Leave `account_balances` on `FROM transactions` this phase and add a code comment that the liquid/investment split for net worth is Phase 15. Planner confirms.

2. **`transfer_pair_id` shape: self-referential FK vs shared-group id?** (D-07 discretion)
   - What we know: it pairs two `transactions` rows written together in Phase 13.
   - What's unclear: a self-FK where each leg points to the other has a chicken-and-egg insert order (both ids must exist first); a shared-group id (same integer on both legs) avoids it.
   - Recommendation: this phase adds a plain **nullable, indexed `Integer`** with no FK, so it's purely additive and unblocking. Decide self-ref-vs-group semantics in Phase 13 when the writer exists. `source_account_id`, by contrast, is a clean FK to `accounts.id` (a real liquid source) — add the FK now.

## Sources

### Primary (HIGH confidence)
- `alembic/versions/009_category_hierarchy.py` — the idempotent/abort-loudly/parity backfill idiom, revision-chain values, downgrade philosophy (read in full this session).
- `alembic/env.py` L72–73 — single `begin_transaction()` online-migration model (clean rollback on raise).
- `backend/tools.py` L117–558 — every cashflow aggregate's exact SQL and `FROM` clause.
- `backend/models.py` L46–52, L124–154, L240–264 — `Account.type`, `Transaction`, `PortfolioEvent` current shapes.
- `backend/importer.py` L110–116 — `_get_or_create_account` omits `type` (server_default resolution).
- `backend/db.py` L1–17 — Alembic-only schema management; `expire_on_commit=False`.
- `backend/tests/conftest.py`, `backend/tests/test_category_migration.py` — test infrastructure runs against live dev DB; pure-function migration-test precedent.
- `.planning/phases/12-.../12-CONTEXT.md`, `.planning/ROADMAP.md`, `.planning/REQUIREMENTS.md` (XFER/ACCT-03) — locked decisions and requirement text.

### Secondary (MEDIUM confidence)
- None needed — no external lookups; the phase is fully specified by in-repo precedent.

### Tertiary (LOW confidence)
- None.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The live dev DB still has exactly accounts {1,2,3,559} at migration time. | Runtime State Inventory, Pitfall 3 | Low — the abort-loudly assertion turns a wrong assumption into a loud, safe halt (not silent misclassification). Verify with `SELECT id,name,type FROM accounts` before running. |
| A2 | The "Investments" (id 3) expense magnitude is ~45.9M IDR (D-04). | Code Examples (double-count proof) | Low — the proof asserts `raw − view == investment_expense` computed live, so the exact figure is derived, not hard-coded into the assertion. |

**Note:** Both are operational assumptions verifiable in one query against the live DB during Wave 1; neither is a design assumption requiring a user decision. All design claims are `[VERIFIED]`/`[CITED]` against source.

## Open Questions → Planner
See the two Open Questions above (account_balances/listings view-switch scope; `transfer_pair_id` FK shape). Both are D-07 discretion items with a recommended default; neither blocks planning.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages; every tool already in the repo and exercised by migrations 001–009.
- Architecture (backfill idiom + `NOT EXISTS` view + `FROM` switch): HIGH — 009 is a direct precedent; the view correctness reasoning is verified SQL semantics.
- Pitfalls: HIGH — each is grounded in a specific source line or a well-known Postgres three-valued-logic behavior.

**Research date:** 2026-07-25
**Valid until:** 2026-08-24 (stable — internal schema; no fast-moving external deps)
