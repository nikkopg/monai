"""Live-database invariant assertions (D-05 Rule B, 24-CONTEXT.md).

LIVE AUDIT — this file lives in backend/tests_live_audit/, outside
`testpaths` (pyproject.toml) and outside backend/tests/conftest.py's guard,
so a default `pytest` run never collects it and it never inherits the
guarded conftest's monai_test default or its refusal. It is re-run
deliberately against live `monai`:
`DATABASE_URL=postgresql+psycopg://monai:monai@localhost:5434/monai .venv/bin/pytest backend/tests_live_audit/test_live_invariants.py -x -q -p no:cacheprovider`

Both tests below were moved here, bodies unchanged, because their assertion
or comment is explicitly about the live data itself, not seedable input
(D-05 interpretation): `test_account_classification` (from
backend/tests/test_typed_accounts.py) asserts specific live account ids and
exactly one live "Investments" account; `test_no_orphan_transactions` (from
backend/tests/test_cleanup_migration.py) is, by its own comment, a
deliberate live-ledger tripwire that must not become a seeded test. Both
are read-only.
"""

import pytest
from sqlalchemy import text

from backend.db import engine


@pytest.fixture()
def db_session():
    from backend.db import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.rollback()
        db.close()


def test_account_classification():
    """Every live accounts row is classified: no NULLs, the original liquid
    ids stay liquid, and there is exactly one investment account ('Investments').

    The investment account's surrogate id is intentionally NOT asserted — it is
    not load-bearing and changes if the account is ever deleted+recreated (it
    moved 3 -> 994 after an accidental delete/restore). The D-02 classification
    invariant is what matters, not the id."""
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, name, type FROM accounts")).fetchall()
    types_by_id = {row[0]: row[2] for row in rows}

    assert all(t in {"liquid", "investment"} for t in types_by_id.values()), (
        f"non-liquid/investment types present: {types_by_id}"
    )
    null_count = sum(1 for t in types_by_id.values() if t is None)
    assert null_count == 0, f"{null_count} accounts still have type IS NULL"

    assert types_by_id.get(1) == "liquid"
    assert types_by_id.get(2) == "liquid"
    assert types_by_id.get(559) == "liquid"

    investments = [(row[0], row[1]) for row in rows if row[2] == "investment"]
    assert len(investments) == 1, f"expected exactly one investment account, got {investments}"
    assert investments[0][1] == "Investments", f"investment account misnamed: {investments}"


# ---------------------------------------------------------------------------
# D-10 orphan tripwire — the ONE deliberate live-database invariant
# assertion in this file. Do NOT "fix" it into a seeded test — it exists to
# fail loudly the moment the orphan class returns, because orphaned
# transactions (account_id IS NULL) are invisible to account_balances()'s
# `accounts LEFT JOIN transactions` and therefore to net_worth(), but ARE
# counted by the cashflow_transactions view (its `NOT EXISTS` predicate
# matches nothing for a NULL account_id), silently reintroducing the
# phantom-cashflow parity break that Phase 22's baseline depends on staying
# at zero. Actually fixing the write path that mints orphans
# (apply_delete_account) is deferred to Phase 22 (D-DEF-01); this assertion
# is the agreed interim coverage (D-10).
# ---------------------------------------------------------------------------

def test_no_orphan_transactions(db_session):
    n = db_session.execute(
        text("SELECT count(*) FROM transactions WHERE account_id IS NULL")
    ).scalar()
    assert n == 0, (
        f"{n} orphaned transaction(s) with account_id IS NULL: these are "
        "invisible to account_balances()'s accounts LEFT JOIN transactions "
        "(and therefore to net_worth()), but ARE counted by the "
        "cashflow_transactions view — their return silently breaks Phase "
        "22's parity baseline."
    )
