# Phase 12: Typed Accounts + Transfer/Funding Schema Foundations - Pattern Map

**Mapped:** 2026-07-25
**Files analyzed:** 5 (1 create migration, 2 modify, 2 create tests)
**Analogs found:** 5 / 5 (all exact in-repo precedent)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `alembic/versions/010_typed_accounts.py` (CREATE) | migration | batch / transform | `alembic/versions/009_category_hierarchy.py` | exact (backfill+constrain+DDL guard) |
| `backend/models.py` (MODIFY) | model | — | same file, `Category`/`Transaction`/`PortfolioEvent` mappings | exact (in-file idiom) |
| `backend/tools.py` (MODIFY) | tool (domain) | CRUD / read-aggregate | same file, `_ROLLUP_FROM` FROM-clause idiom | exact (in-file idiom) |
| `backend/tests/test_typed_accounts.py` (CREATE) | test | — | `backend/tests/test_category_migration.py` (pure) + introspection | role-match |
| `backend/tests/test_cashflow_view.py` (CREATE) | test | — | `backend/tests/test_tools.py` (live-DB SQL) | role-match |
| `backend/importer.py` `_get_or_create_account` (VERIFY, no change) | importer | — | — | relies on `server_default 'liquid'` |

---

## Pattern Assignments

### `alembic/versions/010_typed_accounts.py` (migration, batch/transform)

**Analog:** `alembic/versions/009_category_hierarchy.py`

**Revision-chain header** (009 L44–54) — copy this shape, set `down_revision` to 009's `revision`:
```python
import sqlalchemy as sa
from alembic import op

revision: str = "<new hash>"
down_revision: Union[str, None] = "e5f6a7b8c9d0"   # 009's revision id (009 L51)
branch_labels = None
depends_on = None

# D-02 hard-coded audit map (analog: 009's GROUP_META module const, L63–77)
ACCOUNT_TYPE = {1: "liquid", 2: "liquid", 3: "investment", 559: "liquid"}
```

**Idempotent DDL guard + add_column + index** (009 L243–258) — reuse verbatim shape for `transfer_pair_id` / `source_account_id`:
```python
tx_columns = {c["name"] for c in inspector.get_columns("transactions")}
if "category_id" not in tx_columns:
    op.add_column("transactions", sa.Column("category_id", sa.Integer(), nullable=True))
tx_fks = {fk["name"] for fk in inspector.get_foreign_keys("transactions")}
if "fk_transactions_category" not in tx_fks:
    op.create_foreign_key("fk_transactions_category", "transactions", "categories", ["category_id"], ["id"])
tx_indexes = {ix["name"] for ix in inspector.get_indexes("transactions")}
if "ix_transactions_category_id" not in tx_indexes:
    op.create_index("ix_transactions_category_id", "transactions", ["category_id"])
```
Apply this exact guard idiom to: `transactions.transfer_pair_id` (Integer, nullable, index `ix_transactions_transfer_pair_id`, **no FK** per RESEARCH Open Q2) and `portfolio_events.source_account_id` (Integer, nullable, **FK→accounts.id** `fk_portfolio_events_source_account`, index `ix_portfolio_events_source_account_id`).

**Abort-loudly assert** (009 L260–267, upgrade() opens at L138 with `inspector = sa.inspect(op.get_bind())`) — swap the unmapped-string check for the account-set check from RESEARCH L282–294:
```python
unmapped = find_unmapped(distinct_strings, mapping)
if unmapped:
    raise RuntimeError(f"Category migration abort — unmapped category strings: {unmapped}")
# → phase 12: assert set(live account ids) == set(ACCOUNT_TYPE) and 0 NULL types remain
```

**Downgrade** (009 L329–347) — strict reverse, each drop guarded on `get_indexes`/`get_columns`:
```python
def downgrade() -> None:
    tx_indexes = {ix["name"] for ix in inspector.get_indexes("transactions")}
    if "ix_transactions_category_id" in tx_indexes:
        op.drop_index("ix_transactions_category_id", table_name="transactions")
    # ...drop_constraint, drop_column, drop_table
```
Phase 12 downgrade order (RESEARCH L154–162): `DROP VIEW IF EXISTS cashflow_transactions` → drop the two indexes+columns → `alter_column type` back to nullable/default None → `drop_constraint("ck_accounts_type", ..., type_="check")`.

**View creation** (no 009 analog — use `op.execute` raw SQL, RESEARCH L149–151 + Pattern 2):
```sql
CREATE VIEW cashflow_transactions AS
SELECT t.* FROM transactions t
WHERE NOT EXISTS (SELECT 1 FROM accounts a WHERE a.id = t.account_id AND a.type = 'investment');
```
Guard: `if "cashflow_transactions" not in inspector.get_view_names()`. **Hard requirement (D-07/D-06):** `NOT EXISTS` keeps NULL-`account_id` rows IN; predicate keys `= 'investment'` (never `!= 'liquid'`). Create the view AFTER adding this phase's columns so `t.*` is a superset (RESEARCH Pitfall 5).

**CHECK + tighten** (no direct 009 line; per RESEARCH L138–141):
```python
op.create_check_constraint("ck_accounts_type", "accounts", "type IN ('liquid','investment')")
op.alter_column("accounts", "type", existing_type=sa.String(64), nullable=False, server_default="liquid")
```
Order matters (RESEARCH Pitfall 2): backfill → assert-zero-NULL → CHECK → SET NOT NULL. All values bound via `sa.text(...)` params — only identifiers are code constants.

---

### `backend/models.py` (model)

**Analog:** in-file `Category`/`Transaction`/`PortfolioEvent` mapped_column idioms.

**`Account.type`** — current (L51): `type: Mapped[str | None] = mapped_column(String(64), nullable=True)`. Change to reflect DB state (RESEARCH Pitfall 4):
```python
type: Mapped[str] = mapped_column(String(64), nullable=False, server_default="liquid")
```
Precedent for `server_default` on a mapped_column: `PortfolioEvent.currency` L262–264 (`server_default="IDR", nullable=True`).

**`Transaction.transfer_pair_id`** — mirror the nullable-indexed-Integer idiom of `category_id` (L148–150), but plain Integer, no FK (RESEARCH Open Q2):
```python
# analog: category_id L148-150
category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True, index=True)
# → new: transfer_pair_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
```

**`PortfolioEvent.source_account_id`** — mirror `platform_id` FK idiom (L255–257) but nullable:
```python
# analog: platform_id L255-257
platform_id: Mapped[int] = mapped_column(ForeignKey("platforms.id"), nullable=False, index=True)
# → new: source_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True, index=True)
```

---

### `backend/tools.py` (tool, read-aggregate)

**Analog:** in-file `spending_total` (L117) etc. — mechanical `FROM transactions` → `FROM cashflow_transactions` swap only; parameterized `text()` SQL otherwise unchanged. The view exposes `t.*` so `amount`, `is_transfer`, `date`, `category`, `merchant`, `account_id`, `category_id` all remain.

**Switch these TOTALS/listings (required):**

| Tool | Line | FROM-clause to change |
|------|------|-----------------------|
| `spending_total` | L127 | `"SELECT COALESCE(SUM(-amount), 0) FROM transactions "` → `FROM cashflow_transactions` |
| `income_total` | L144 | `"SELECT COALESCE(SUM(amount), 0) FROM transactions "` → view |
| `net_total` | L161 | `"SELECT COALESCE(SUM(amount), 0) FROM transactions "` → view |
| `spending_by_category` | L237 (`_ROLLUP_FROM`) | `"FROM transactions t JOIN categories c ..."` → `FROM cashflow_transactions t JOIN categories c ...` |
| `transaction_count` | L383 | `"SELECT COUNT(*) FROM transactions WHERE ..."` → view |
| `largest_transactions` | L403 | `"... FROM transactions WHERE {sign} ..."` → view (RESEARCH rec: switch for consistency) |
| `average_daily_spending` | L426 (total_sql) | `FROM transactions` → view. **Note:** the `MIN(date)/MAX(date)` fallback at L434 stays `FROM transactions` (span, not a total). |
| `monthly_trend` | L454 | `"FROM transactions "` → view |
| `find_transactions` | L547 | `"SELECT id, date, amount, category, merchant, account_id FROM transactions WHERE"` → view (RESEARCH rec) |

**Leave unchanged:**
- `account_balances` (L472, SQL at L491+) — already `LEFT JOIN`s accounts; per-account list, not a total. Stays `FROM transactions`. Add a code comment: liquid/investment net-worth split is Phase 15 (CONTEXT discretion item D).

Example (RESEARCH L201–204):
```python
# spending_total L126-129 — before → after
"SELECT COALESCE(SUM(-amount), 0) FROM cashflow_transactions "   # was: FROM transactions
"WHERE amount < 0 AND is_transfer = false" + _date_clause(s, e, p)
```

---

### `backend/tests/test_typed_accounts.py` (test — pure + introspection)

**Analog:** `backend/tests/test_category_migration.py` (importlib-loads the migration module, tests pure helpers, no DB).

**importlib migration-load idiom** (test_category_migration.py L13–55) — reuse verbatim, retargeting `MIGRATION_PATH` to `010_typed_accounts.py`. Note the `_ensure_real_alembic_package()` shim (L25–55) that dodges the repo's own `alembic/` scaffold shadowing the pip package — **copy it as-is**, it is a required workaround.
```python
MIGRATION_PATH = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "010_typed_accounts.py"
```
Pure tests: assert `migration.ACCOUNT_TYPE == {1:"liquid",2:"liquid",3:"investment",559:"liquid"}` (D-02).

**DB introspection tests** (RESEARCH L353–361) — `sa.inspect(engine)` over `get_columns`/`get_indexes` for `transfer_pair_id` (nullable, indexed) and `source_account_id` (nullable, indexed). CHECK+default: INSERT `type='bogus'` rejected; INSERT omitting `type` yields `'liquid'`.

### `backend/tests/test_cashflow_view.py` (test — live-DB invariant)

**Analog:** `backend/tests/test_tools.py` (runs live-DB SQL via the shared engine; `conftest.py` assumes migrations already applied — no fresh-migrate fixture).

Invariants (RESEARCH Criterion 2 + L296–306): (a) no investment-account row in `cashflow_transactions`; (b) `COUNT(*) WHERE account_id IS NULL` identical in `transactions` and the view; (c) `raw_spending − view_spending == investment_expense` (the ~45.9M double-count delta, computed live not hard-coded).

---

## Shared Patterns

### Idempotent abort-loudly migration
**Source:** `alembic/versions/009_category_hierarchy.py` (upgrade L138+, guards L243–258, downgrade L329–347)
**Apply to:** `010_typed_accounts.py` — every structural step guarded by `sa.inspect()` existence check; every data step raises `RuntimeError` naming offending rows. `env.py` L72–73 wraps in one `begin_transaction()` → any raise = clean full rollback.

### Parameterized `text()` SQL, identifiers-only interpolation
**Source:** `backend/tools.py` (all tools) + 009 (bound params throughout)
**Apply to:** migration backfill, view SQL, tools swap. Values always bound (`sa.text(...)` params); the only string-built token is the table name `cashflow_transactions` (code constant).

### mapped_column nullable-indexed-FK idiom
**Source:** `backend/models.py` `Transaction.category_id` L148–150, `PortfolioEvent.platform_id` L255–257, `PortfolioEvent.currency` L262–264 (server_default)
**Apply to:** the two new pairing columns + `Account.type` server_default.

### Importer relies on server_default (no change)
**Source:** `backend/importer.py` `_get_or_create_account` L110 — constructs `Account(name, currency)` without `type` (RESEARCH L311–315). With `type NOT NULL DEFAULT 'liquid'`, SQLAlchemy omits the unset column, Postgres fills `'liquid'`. **VERIFY only, no edit** (D-05).

---

## No Analog Found

| File/Element | Role | Reason | Fallback |
|--------------|------|--------|----------|
| `CREATE VIEW cashflow_transactions` | DDL view | No existing view created via a migration in `alembic/versions/` (the `date_helpers` view predates Alembic, bootstrapped in `db.py`) | Use `op.execute(raw SQL)` per RESEARCH Pattern 2 / L149–151; guard on `inspector.get_view_names()` |
| CHECK constraint via `op.create_check_constraint` | DDL | 009 uses table/FK/index guards but no CHECK | RESEARCH L138 provides exact call; guard on `inspector.get_check_constraints('accounts')` |

## Metadata

**Analog search scope:** `alembic/versions/`, `backend/models.py`, `backend/tools.py`, `backend/tests/`, `backend/importer.py`
**Files scanned:** 6 (graphify-oriented, then targeted reads)
**Pattern extraction date:** 2026-07-25
