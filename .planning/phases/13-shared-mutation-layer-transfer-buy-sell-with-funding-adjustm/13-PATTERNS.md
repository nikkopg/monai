# Phase 13: Shared Mutation Layer — Pattern Map

**Mapped:** 2026-07-30
**Files analyzed:** 3 (writes.py modification, one new migration, test extensions)
**Analogs found:** 3 / 3

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `backend/writes.py` (5 new `apply_*` fns) | service (mutation layer) | CRUD (composed, multi-row) | `apply_add_portfolio_event` (L247), `apply_add_transaction` (L54) — same file | exact |
| `backend/writes.py` (`apply_edit_transaction`/`apply_delete_transaction` guard) | service | request-response (guard/raise) | same functions, in place (L79, L98) | exact |
| `alembic/versions/011_retro_pair_transfers.py` | migration | batch (backfill) | `alembic/versions/009_category_hierarchy.py` (parity-checked backfill), `010_typed_accounts.py` (idempotent guarded steps) | exact |
| `backend/tests/test_write_tools.py` (extend) | test | request-response | same file, existing `test_apply_add_portfolio_event_audits_and_recomputes` (L587) | exact |
| `backend/tests/test_transfer_retro_pairing.py` (new) | test | batch | no direct analog for standalone migration-module import; `009`/`010` migration files themselves are the analog for logic under test | role-match |

## Pattern Assignments

### `backend/writes.py` — new `apply_*` functions

**Analog:** `apply_add_transaction` (L54-76) + `apply_add_portfolio_event` (L247-311), same file.

**Module contract (top-of-file docstring, L1-14) — binding on every new function:**
```python
"""
Shared write mutations for monai (D-02).
...
Every apply_* function:
  - performs exactly one entity mutation (add/edit/delete/rename/merge)
  - writes exactly one AuditLog row recording before/after state
  - never commits the session itself — the caller owns the transaction boundary
"""
```
Composed functions (transfer, funded buy/sell, adjustment) mutate MULTIPLE entities — each entity still gets its own `AuditLog` row (D-02), written by the primitive it calls (`apply_add_transaction`/`apply_add_portfolio_event` already do this). The composed function itself does not need an extra top-level audit row unless it sets a field the primitive didn't (e.g. `transfer_pair_id`, `source_account_id` — see below).

**Imports already present (L16-24), reuse as-is, no new imports needed:**
```python
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.importer import _get_or_create_account
from backend.models import Account, AuditLog, Category, Holding, Platform, PortfolioEvent, PriceCache, Transaction
from backend.portfolio import recompute_holding_from_events
```

**Money idiom (LOAD-BEARING, copy verbatim in every new money field):**
```python
# writes.py:62
amount=Decimal(str(after["amount"])),  # LOAD-BEARING: str() before Decimal() avoids float artifacts
```
Applies to: transfer leg amounts, funded-buy/sell cash amounts, the adjustment delta.

**Flush-before-audit idiom (populate `.id` before referencing it):**
```python
# writes.py:72-76
db.add(tx)
db.flush()  # LOAD-BEARING: populates tx.id before the AuditLog row below
db.add(AuditLog(entity="transaction", entity_id=tx.id, operation="add",
                before=None, after=after))
return tx
```
For the transfer pair: insert leg A via `apply_add_transaction` (flush gives `leg_a.id`), insert leg B via `apply_add_transaction` (flush gives `leg_b.id`), THEN set `leg_a.transfer_pair_id = leg_a.id; leg_b.transfer_pair_id = leg_a.id` (shared-group-id convention per RESEARCH.md, no extra flush needed since both rows are already flushed/attached — SQLAlchemy tracks the attribute change for the next flush/commit).

**Composition pattern — call one `apply_*` primitive, then adjust the returned ORM object directly** (mirrors how `apply_add_portfolio_event` itself composes `recompute_holding_from_events` at L297 and then mutates `holding.asset_type` at L310 post-hoc):
```python
# writes.py:296-310 — composition-then-mutate-in-place idiom to copy
recompute_holding_from_events(db, after["ticker"], after["platform_id"])
if after.get("asset_type") is not None:
    db.flush()  # NOTE: session is autoflush=False — flush before re-querying a just-added row
    holding = db.query(Holding).filter(
        Holding.ticker == after["ticker"], Holding.platform_id == after["platform_id"]
    ).one_or_none()
    if holding is not None:
        holding.asset_type = after["asset_type"]
```
Apply the same "flush, re-query if needed, mutate in place" shape when setting `PortfolioEvent.source_account_id` after calling `apply_add_portfolio_event` for the liquid→investment transfer and funded buy/sell functions — the returned `ev` object from `apply_add_portfolio_event` already has `.id` populated (flushed at L293), so `ev.source_account_id = tx.account_id` can be set directly on the returned object without a re-query.

**Account resolution — never hard-code an id (RESEARCH Finding 1, Pitfall 2):**
```python
# _get_or_create_account already used inside apply_add_transaction (L58)
acc = _get_or_create_account(db, account_name, currency)
```
For "the Investments account" / "the Stockbit account" needed by liquid→investment transfer or funded buy/sell, resolve by name/type at call time (caller passes an account name string into the composed function's `after` dict, same as `apply_add_transaction` already does) — never a literal id like migration `010`'s now-stale `ACCOUNT_TYPE = {1: "liquid", 2: "liquid", 3: "investment", 559: "liquid"}` map.

**`is_transfer` tagging (Pitfall 5) — every new leg must explicitly pass it:**
```python
# apply_add_transaction defaults is_transfer to False (writes.py:70) unless passed
is_transfer=after.get("is_transfer", False),
```
Every composed function's `after` dict for a transfer leg / funded-buy cash leg MUST include `"is_transfer": True` explicitly — the primitive will not infer it.

**Balance-adjustment delta — do NOT reuse `tools.py:account_balances` (Finding 2/Pitfall 1). Fresh inline query, no `is_transfer` filter:**
```python
# Source: RESEARCH.md Pattern 2, not an existing writes.py line — net-new SQL
current = db.execute(
    text("SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE account_id = :id"),
    {"id": account_id},
).scalar()
delta = Decimal(str(target_balance)) - Decimal(str(current))
```

---

### `backend/writes.py` — leg-protection guard on `apply_edit_transaction` / `apply_delete_transaction`

**Analog:** the functions themselves, in place (L79-95, L98-104).

**Current signature/body (L79-95) — guard inserts at the top, before the existing `db.get` null-check pattern:**
```python
def apply_edit_transaction(db: Session, tx_id: int, after: dict, before: dict | None) -> Transaction:
    """Partial-update an existing transaction. None fields in `after` are left unchanged."""
    tx = db.get(Transaction, tx_id)
    if tx is None:
        raise ValueError(f"Transaction {tx_id} not found during confirm")
    if after.get("category") is not None:
        ...
```
New signature adds `allow_paired: bool = False` (default preserves every existing caller's behavior unchanged — no call-site elsewhere in the codebase needs updating except the new pair-aware functions themselves):
```python
def apply_edit_transaction(
    db: Session, tx_id: int, after: dict, before: dict | None, allow_paired: bool = False
) -> Transaction:
    tx = db.get(Transaction, tx_id)
    if tx is None:
        raise ValueError(f"Transaction {tx_id} not found during confirm")
    if tx.transfer_pair_id is not None and not allow_paired:
        raise ValueError(
            f"Transaction {tx_id} is one leg of a paired transfer "
            f"(transfer_pair_id={tx.transfer_pair_id}); use the pair-aware "
            "transfer function to edit both legs together."
        )
    # ... existing body unchanged (writes.py:84-95)
```
Same shape for `apply_delete_transaction` (L98-104): check `tx.transfer_pair_id is not None and not allow_paired` before the existing `if tx is not None: db.delete(tx)` line.

---

### `alembic/versions/011_retro_pair_transfers.py`

**Analog:** `009_category_hierarchy.py` (parity-checked backfill idiom) + `010_typed_accounts.py` (idempotent guarded-`if` steps, abort-loudly precedent).

**Revision header — chain off `010`'s actual revision id (confirmed live: `010`'s `revision = "f1a2b3c4d5e6"`):**
```python
# Source: alembic/versions/010_typed_accounts.py:44-47, same shape
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "<new-uuid-or-slug>"
down_revision: Union[str, None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
```

**Candidate-match query (verified live this session, RESEARCH.md Code Examples):**
```sql
SELECT a.id AS leg_a_id, b.id AS leg_b_id
FROM transactions a
JOIN transactions b
  ON a.date::date = b.date::date
 AND a.amount = -b.amount
 AND a.account_id <> b.account_id
 AND a.id < b.id
WHERE a.is_transfer = true AND b.is_transfer = true;
```
Must be followed by a `COUNT(*)` guard per row before pairing (Pitfall 4) — do not `LIMIT 1` blindly. Exactly-one-match → `UPDATE ... SET transfer_pair_id = leg_a_id WHERE id IN (leg_a_id, leg_b_id)`; zero or multiple matches → leave NULL, print the flagged ids (no new column — `009`'s report-only precedent, see Open Question 1 in RESEARCH.md).

**Parity/abort idiom to copy — `009`'s `assert_parity` (L124-135) is the reporting-style analog** (raises loudly on unexpected mismatch, but D-11 explicitly makes "0 or multiple matches" an *expected non-fatal* outcome — so retro-pairing prints/logs, it does not raise, for the flagged rows; only a genuine SQL/count-guard bug should raise):
```python
# writes.py idiom to mirror, NOT a raise for expected-empty-match case:
def assert_parity(pre: dict, post: dict) -> None:
    mismatches = [...]
    if mismatches:
        raise RuntimeError("...")
```

**Idempotent guarded-step idiom to copy from `010` (inspector-driven `if not exists` checks, no destructive re-run):**
```python
# alembic/versions/010_typed_accounts.py:56-65 shape
def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    for account_id, acc_type in SOME_MAP.items():
        conn.execute(sa.text("UPDATE ... WHERE ... AND type IS NULL"), {...})
```
Retro-pairing's re-run safety: `UPDATE transactions SET transfer_pair_id = :group_id WHERE id IN (:a,:b) AND transfer_pair_id IS NULL` — the `IS NULL` guard makes re-running `upgrade()` a no-op on already-paired rows (idempotent per D-11).

**Anti-pattern explicitly flagged by RESEARCH — do NOT hard-code account ids** (unlike `010`'s now-stale `ACCOUNT_TYPE = {1: "liquid", 2: "liquid", 3: "investment", 559: "liquid"}` at L53, which the live DB has already drifted past — id 3 no longer exists, Investments is now 994). The retro-pairing migration never needs account ids explicitly (it joins on `a.account_id <> b.account_id`, not specific ids), so this is a non-issue for `011` as long as no one adds an `ACCOUNT_TYPE`-style map.

---

### `backend/tests/test_write_tools.py` (extend) / `backend/tests/test_transfer_retro_pairing.py` (new)

**Analog:** `test_apply_add_portfolio_event_audits_and_recomputes` (L587-630) + the module's fixture block (L1-96).

**Fixture idiom (already in file, reuse as-is — no new fixtures needed per RESEARCH.md Wave 0 Gaps):**
```python
# backend/tests/test_write_tools.py:26-45
@pytest.fixture(scope="module")
def db_available():
    from backend.db import engine
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception as e:
        pytest.skip(f"Postgres not available: {e}")
    return True

@pytest.fixture()
def db_session(db_available):
    """Return a live SQLAlchemy session; roll back after each test."""
    from backend.db import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

**Per-test shape to copy (L587-630) — seed, call `apply_*` directly (no endpoint), commit, assert on live DB state, clean up:**
```python
def test_apply_add_portfolio_event_audits_and_recomputes(db_session):
    from decimal import Decimal
    from backend.writes import apply_add_portfolio_event
    from backend.models import PortfolioEvent, Holding, AuditLog

    ticker = "EVTTEST01"
    _cleanup_ticker(db_session, ticker)
    plat_id = _make_platform(db_session, "TestAuditRecomputePlatform")

    before_audit = int(db_session.execute(
        text("SELECT COUNT(*) FROM audit_log WHERE entity = 'portfolio_event'")
    ).scalar() or 0)

    apply_add_portfolio_event(db_session, {...})
    db_session.commit()

    ev = db_session.query(PortfolioEvent).filter(PortfolioEvent.ticker == ticker).one()
    assert ev.event_type == "buy"
    ...
    after_audit = int(db_session.execute(
        text("SELECT COUNT(*) FROM audit_log WHERE entity = 'portfolio_event'")
    ).scalar() or 0)
    assert after_audit == before_audit + 1

    _cleanup_ticker(db_session, ticker)
```
Note: tests call `db_session.commit()` themselves after the `apply_*` call — that commit belongs to the TEST (playing the role of "the caller"), not the function under test, consistent with D-01's never-commit contract.

**Seed helpers already present, reuse directly** — `_make_transaction(db)` (L52-66), `_make_account(db, name=...)` (L69-80), `_make_holding(db)` (L83-92), `_count_proposals(db)` (L95-96). New transfer/adjustment tests need a `_make_account` pair and can build `after` dicts inline (no new seed helper required unless a specific fixture — e.g. two named liquid accounts — repeats across 3+ tests).

**For `test_transfer_retro_pairing.py` (new file):** RESEARCH.md recommends following `test_category_migration.py`'s pattern of `importlib`-importing the migration module standalone (bypassing the `alembic/` runner) to unit-test the pure matching/pairing logic before running it live. No existing `test_category_migration.py` content was read this pass — the planner/implementer should locate and read that file directly for the exact `importlib` shape before writing `011`'s test, since RESEARCH.md names it as the closest analog but this pattern-mapping pass did not re-read it (avoid duplicate reads — confirm its exact import shape at implementation time).

## Shared Patterns

### Never-commit contract
**Source:** `backend/writes.py` L10-14 (module docstring), verified zero `db.commit()` calls anywhere in the file today.
**Apply to:** All 5 new `apply_*` functions, no exceptions. Verification command: `grep -n "db.commit" backend/writes.py` must return zero matches after this phase.

### One-AuditLog-row-per-mutated-entity
**Source:** `apply_add_transaction` (L74-75), `apply_add_portfolio_event` (L294-295) — each primitive already writes its own row; composed functions get this "for free" as long as they call the primitives rather than hand-rolling inserts.
**Apply to:** transfer (2 rows — one per leg), liquid→investment transfer (1 transaction row + 1 portfolio_event row), funded buy/sell (1 transaction row + 1 portfolio_event row), adjustment (1 transaction row).

### `Decimal(str(x))` money idiom
**Source:** `writes.py:62`, `writes.py:90`, `writes.py:287-288` (inline "LOAD-BEARING" comments).
**Apply to:** every new money field — transfer amounts, funded-buy/sell cash amounts, the adjustment delta computation.

### Parameterized SQL only
**Source:** every existing query in `writes.py` uses `text()` with bound `:param` placeholders (e.g. `resolve_category_id` L40-43, the balance-adjustment SELECT above). No string-formatted SQL anywhere in the file.
**Apply to:** the balance-adjustment SUM query, the retro-pairing migration's candidate-match query and UPDATE statements.

## No Analog Found

None — all target files have a strong same-file or same-directory analog (writes.py extends itself; the migration extends 009/010; tests extend test_write_tools.py). The only soft gap is `test_transfer_retro_pairing.py`'s exact `importlib` shape, which RESEARCH.md points at `backend/tests/test_category_migration.py` — read that file directly at implementation time rather than assuming its shape here.

## Metadata

**Analog search scope:** `backend/writes.py`, `backend/models.py`, `backend/portfolio.py`, `alembic/versions/009_category_hierarchy.py`, `alembic/versions/010_typed_accounts.py`, `backend/tests/test_write_tools.py`
**Files scanned:** 6 (full or targeted reads) + graphify traversal (166 nodes) for orientation
**Pattern extraction date:** 2026-07-30
