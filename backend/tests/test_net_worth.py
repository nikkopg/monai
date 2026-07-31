"""
Net worth aggregation tests — NW-01/NW-02, SC#3 (Phase 15 Plan 01).

Pins the behavior of the new `net_worth()` read tool + GET /net-worth
endpoint: liquid (type='liquid' accounts) + investment (portfolio_summary
total_value) composed into one number, each account/holding counted exactly
once (D-01/D-03/D-04), a loud coverage-assertion ValueError on a
classification gap (D-05/D-06), and dual registration on both read-only
surfaces (TOOLS/READ_TOOL_NAMES + query.py's agent tool list — the exact
chat-tool-dual-registration gap that bit Phase 7).

Reuses the db_available/db_session fixture + _make_account/_make_transaction
seed-helper style from test_cashflow_summary.py; _make_account here adds a
`type` param so it can seed both liquid and investment accounts.
"""

import datetime

import pytest

from sqlalchemy import text


# ---------------------------------------------------------------------------
# DB fixture — skip if Postgres not available (mirrors test_cashflow_summary.py)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Seed-row helpers (mirrors test_cashflow_summary.py, + a type param)
# ---------------------------------------------------------------------------

def _make_transaction(db, *, date=None, amount=-50000, account_id=None, is_transfer=False) -> int:
    """Insert a minimal transaction row; return its id."""
    from backend.models import Transaction
    tx = Transaction(
        date=date or datetime.datetime(2024, 1, 15, 12, 0, 0),
        amount=amount,
        currency="IDR",
        category="Food",
        merchant="Test Merchant",
        account_id=account_id,
        is_transfer=is_transfer,
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)
    return tx.id


def _make_account(db, name: str = "Test Account NW", type: str = "liquid") -> int:
    """Insert (or reuse) an account row of a given type; return its id.

    Unlike test_cashflow_summary.py's hardcoded-liquid helper, this variant
    accepts `type` so the net_worth tests can seed both liquid and
    investment-typed accounts (D-03/D-04 partition).
    """
    from backend.models import Account
    existing = db.query(Account).filter(Account.name == name).first()
    if existing:
        db.delete(existing)
        db.commit()
    acc = Account(name=name, type=type, currency="IDR")
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc.id


# ---------------------------------------------------------------------------
# NW-01/D-04: liquid vs investment partition — each account counted once
# ---------------------------------------------------------------------------

def test_sum_counts_each_row_once(db_session):
    """Seed one liquid account and one investment-typed account, each with its
    own known transaction-derived balance. liquid_total must include only the
    liquid account's delta; the investment account must not appear in
    liquid_accounts (D-04 — counted exactly once, by construction)."""
    from backend.tools import net_worth

    before = net_worth(db_session)
    before_liquid_total = before["liquid_total"]

    liquid_id = _make_account(db_session, "zzNW-Liquid", type="liquid")
    invest_id = _make_account(db_session, "zzNW-Invest", type="investment")
    seeded_tx_ids = []
    try:
        seeded_tx_ids.append(_make_transaction(db_session, amount=250000, account_id=liquid_id))
        seeded_tx_ids.append(_make_transaction(db_session, amount=999999, account_id=invest_id))

        result = net_worth(db_session)

        assert result["liquid_total"] == pytest.approx(before_liquid_total + 250000.0), (
            "liquid_total must add the new liquid account's balance and exclude "
            "the investment-typed account's balance entirely"
        )
        liquid_ids = [r["id"] for r in result["liquid_accounts"]]
        assert liquid_id in liquid_ids
        assert invest_id not in liquid_ids, (
            "an investment-typed account must never appear in liquid_accounts — "
            "its value lives on the investment side only (D-04)"
        )
    finally:
        from backend.models import Transaction, Account
        for tx_id in seeded_tx_ids:
            tx = db_session.get(Transaction, tx_id)
            if tx:
                db_session.delete(tx)
        db_session.commit()
        for acc_id in (liquid_id, invest_id):
            acc = db_session.get(Account, acc_id)
            if acc:
                db_session.delete(acc)
        db_session.commit()


# ---------------------------------------------------------------------------
# NW-02/D-08: split reconciles to the combined total
# ---------------------------------------------------------------------------

def test_split_reconciles_to_total(db_session):
    """total == liquid_total + investment_total, and investment_total is
    reconciled against portfolio_summary's own total_value (the single source
    of truth) — never a hardcoded, price-dependent number."""
    from backend.tools import net_worth
    from backend.portfolio import portfolio_summary

    result = net_worth(db_session)
    assert result["total"] == pytest.approx(result["liquid_total"] + result["investment_total"])

    pf = portfolio_summary(db_session)
    assert result["investment_total"] == pytest.approx(float(pf["total_value"]))


# ---------------------------------------------------------------------------
# D-05/D-06, SC#3: coverage assertion raises loudly on a classification gap
# ---------------------------------------------------------------------------

def test_unclassified_type_raises(db_session, monkeypatch):
    """Force a coverage gap by stubbing account_balances() to return a row
    whose type is neither 'liquid' nor 'investment' (the DB CHECK constraint
    blocks a real out-of-set row — Open Question 2, do NOT try to insert one).
    net_worth() must raise ValueError rather than silently drop/double-count.
    """
    import backend.tools as tools_module

    def _stub_account_balances(*args, **kwargs):
        return {
            "tool": "account_balances",
            "rows": [
                {"id": 1, "name": "A", "type": "liquid", "current_balance": 100.0, "period_net": 0.0},
                {"id": 2, "name": "B", "type": "bogus", "current_balance": 50.0, "period_net": 0.0},
            ],
        }

    monkeypatch.setattr(tools_module, "account_balances", _stub_account_balances)

    with pytest.raises(ValueError):
        tools_module.net_worth(db_session)


# ---------------------------------------------------------------------------
# D-02: net_worth is registered read-only — TOOLS/READ_TOOL_NAMES surface
# ---------------------------------------------------------------------------

def test_net_worth_is_read_only():
    """net_worth must be in READ_TOOL_NAMES and absent from every write-tool
    mapping (the names TOOLS.update() adds on top of the frozen read
    snapshot) — the read-only safety contract (T-15-01)."""
    from backend.tools import READ_TOOL_NAMES, TOOLS

    assert "net_worth" in READ_TOOL_NAMES

    write_tool_names = set(TOOLS) - set(READ_TOOL_NAMES)
    assert "net_worth" not in write_tool_names
    assert all(name.startswith("propose_") for name in write_tool_names), (
        "sanity check: everything outside READ_TOOL_NAMES should be a propose_* "
        "write tool — otherwise this test isn't actually checking what it claims"
    )


# ---------------------------------------------------------------------------
# D-02, chat-tool-dual-registration memory: net_worth registered for the agent
# ---------------------------------------------------------------------------

def test_net_worth_registered_for_agent():
    """Registering net_worth in TOOLS/READ_TOOL_NAMES alone does NOT surface it
    to the agent — query.py's _get_agent_workflow builds its own explicit
    FunctionTool list (`read_tools`, a local variable, not a module-level
    export — `from backend.query import read_tools` is not importable). This
    is a source-grep regression guard (same style as
    test_cashflow_summary_resolve_period_called_once): it goes RED if the
    net_worth import or its FunctionTool.from_defaults(fn=net_worth) line is
    ever removed from _get_agent_workflow's body.
    """
    import inspect
    from backend.query import _get_agent_workflow

    src = inspect.getsource(_get_agent_workflow)
    assert "net_worth" in src, "_get_agent_workflow must import net_worth from backend.tools"
    # Registered via the zero-arg net_worth_tool wrapper with an explicit
    # name="net_worth" so the LLM tool schema stays argument-free (WR-01) while
    # still surfacing under the canonical "net_worth" tool name.
    assert 'FunctionTool.from_defaults(fn=net_worth_tool, name="net_worth")' in src, (
        "net_worth must be registered as a FunctionTool in the agent's read_tools "
        "list (chat-tool-dual-registration memory) — the MCP/TOOLS registry does "
        "not automatically surface it to the agent"
    )


# ---------------------------------------------------------------------------
# NW-02: GET /net-worth endpoint
# ---------------------------------------------------------------------------

def test_get_net_worth_endpoint(client, db_session):
    """GET /net-worth returns 200 with the full composed payload; total ==
    liquid_total + investment_total."""
    resp = client.get("/net-worth")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert set((
        "total", "liquid_total", "investment_total",
        "liquid_accounts", "investment_groups",
        "accounts_covered", "accounts_total",
    )) <= set(body.keys())
    assert body["total"] == pytest.approx(body["liquid_total"] + body["investment_total"])
