"""Tests for migration 020 (currency model: IDR/USD constraints + transactions_idr).

Runs against a per-process scratch DB `monai_test_mig020_<token>`, created and dropped on the same
server as conftest's guarded DATABASE_URL. Never touches the live `monai`. All
values are synthetic.
"""
import os
import re
import secrets
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = REPO_ROOT / "alembic" / "versions" / "020_currency_model.py"
PRE_020 = "20116eb89bff"
REV_020 = "c4f2a8e61d93"
SCRATCH_DB = f"monai_test_mig020_{secrets.token_hex(4)}"  # per-process: concurrent runs must not FORCE-drop each other
NAMES = ("ck_accounts_currency", "ck_transactions_currency", "uq_accounts_id_currency", "fk_transactions_account_currency")

COUNTS_SQL = text(
    "SELECT table_name, (xpath('/row/c/text()', query_to_xml("
    "format('select count(*) as c from %I.%I', table_schema, table_name), "
    "false, true, '')))[1]::text::bigint AS n "
    "FROM information_schema.tables "
    "WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY 1"
)


def _counts(engine) -> dict[str, int]:
    with engine.connect() as c:
        return {name: n for name, n in c.execute(COUNTS_SQL)}


def _cfg(url: str):
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    cfg.attributes["sqlalchemy.url"] = url  # raw string, never str(URL)
    return cfg, command


@pytest.fixture()
def scratch_url(monkeypatch):
    monkeypatch.setattr("logging.config.fileConfig", lambda *a, **k: None)
    base = make_url(os.environ["DATABASE_URL"])
    assert base.database != "monai" and SCRATCH_DB != "monai"
    admin = create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{SCRATCH_DB}" WITH (FORCE)'))
            c.execute(text(f'CREATE DATABASE "{SCRATCH_DB}"'))
        yield base.set(database=SCRATCH_DB).render_as_string(hide_password=False)
    finally:
        with admin.connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{SCRATCH_DB}" WITH (FORCE)'))
        admin.dispose()


def _names(engine) -> dict[str, list[str]]:
    insp = inspect(engine)
    return {
        "ck_accounts_currency": [c["name"] for c in insp.get_check_constraints("accounts")],
        "ck_transactions_currency": [c["name"] for c in insp.get_check_constraints("transactions")],
        "uq_accounts_id_currency": [u["name"] for u in insp.get_unique_constraints("accounts")],
        "fk_transactions_account_currency": [f["name"] for f in insp.get_foreign_keys("transactions")],
    }


def _scalar(engine, sql: str, **p):
    with engine.connect() as c:
        return c.execute(text(sql), p).scalar()


def _col(engine, table: str, column: str):
    with engine.connect() as c:
        return c.execute(
            text(
                "SELECT is_nullable, column_default FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=:t AND column_name=:c"
            ),
            {"t": table, "c": column},
        ).one_or_none()


def _view_cols(engine, view: str) -> list[str]:
    with engine.connect() as c:
        return [
            r[0]
            for r in c.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name=:t ORDER BY ordinal_position"
                ),
                {"t": view},
            )
        ]


def _views(engine) -> set[str]:
    return set(inspect(engine).get_view_names())


def _seed_tx(c, account_id, currency, amount="-12.50"):
    return c.execute(
        text(
            "INSERT INTO transactions (date, amount, currency, account_id, is_transfer) "
            "VALUES ('1901-01-05 12:00', :a, :c, :acc, false) RETURNING id"
        ),
        {"a": amount, "c": currency, "acc": account_id},
    ).scalar()


def test_020_imports_nothing_from_backend():
    src = MIGRATION_PATH.read_text()
    assert not re.search(r"^\s*(from|import)\s+backend\b", src, re.MULTILINE)
    assert f'"{PRE_020}"' in src and f'"{REV_020}"' in src


def test_020_upgrade_is_idempotent_and_reversible(scratch_url):
    cfg, command = _cfg(scratch_url)
    command.upgrade(cfg, PRE_020)
    engine = create_engine(scratch_url)
    try:
        assert _scalar(engine, "SELECT current_database()") == SCRATCH_DB
        with engine.begin() as c:
            null_acc = c.execute(
                text("INSERT INTO accounts (name, type, currency) VALUES ('ZZ42 mig null', 'liquid', NULL) RETURNING id")
            ).scalar()
            idr_acc = c.execute(
                text("INSERT INTO accounts (name, type, currency) VALUES ('ZZ42 mig idr', 'liquid', 'IDR') RETURNING id")
            ).scalar()
            _seed_tx(c, null_acc, "  ", "-100.00")  # blank currency
            _seed_tx(c, idr_acc, "IDR", "-200.00")
            _seed_tx(c, None, "IDR", "-300.00")
            c.execute(
                text(
                    "INSERT INTO fx_rate_cache (rate_date, base_currency, quote_currency, rate, source) "
                    "VALUES ('1901-01-04', 'USD', 'IDR', 16000.000000, 'test')"
                )
            )
        before = _counts(engine)

        command.upgrade(cfg, REV_020)
        assert _scalar(engine, "SELECT version_num FROM alembic_version") == REV_020
        assert _scalar(engine, "SELECT count(*) FROM accounts WHERE currency IS NULL OR currency NOT IN ('IDR','USD')") == 0
        assert _scalar(engine, "SELECT count(*) FROM transactions WHERE currency NOT IN ('IDR','USD')") == 0
        nullable, default = _col(engine, "accounts", "currency")
        assert nullable == "NO" and "IDR" in default
        assert "IDR" in _col(engine, "transactions", "currency")[1]
        names = _names(engine)
        for n in NAMES:
            assert names[n].count(n) == 1, n
        fks = {f["name"]: f for f in inspect(engine).get_foreign_keys("transactions")}
        comp = fks["fk_transactions_account_currency"]
        assert comp["constrained_columns"] == ["account_id", "currency"]
        assert comp["referred_columns"] == ["id", "currency"]
        assert any(f["constrained_columns"] == ["account_id"] for f in fks.values())  # original FK kept
        nullable, _ = _col(engine, "fx_rate_cache", "rate_effective_date")
        assert nullable == "YES"
        assert _scalar(engine, "SELECT rate_effective_date FROM fx_rate_cache") is None
        assert {"transactions_idr", "cashflow_transactions"} <= _views(engine)
        assert _counts(engine) == before

        # re-run is a no-op (entrypoint.sh runs upgrade on every boot)
        command.stamp(cfg, PRE_020)
        command.upgrade(cfg, REV_020)
        assert _counts(engine) == before
        again = _names(engine)
        for n in NAMES:
            assert again[n].count(n) == 1, n

        command.downgrade(cfg, "-1")
        down = _names(engine)
        assert not any(n in down[n] for n in NAMES)
        assert "transactions_idr" not in _views(engine)
        assert _col(engine, "fx_rate_cache", "rate_effective_date") is None
        assert _col(engine, "accounts", "currency")[0] == "YES"
        assert "cashflow_transactions" in _views(engine)
        tx_cols = _view_cols(engine, "transactions")
        assert _view_cols(engine, "cashflow_transactions") == tx_cols
        assert _counts(engine) == before

        command.upgrade(cfg, REV_020)
        assert "transactions_idr" in _views(engine)
    finally:
        engine.dispose()


def _assert_rolled_back(engine):
    assert _scalar(engine, "SELECT version_num FROM alembic_version") == PRE_020
    assert "ck_accounts_currency" not in _names(engine)["ck_accounts_currency"]
    assert "transactions_idr" not in _views(engine)


def test_020_preflight_aborts_on_out_of_set_currency(scratch_url):
    cfg, command = _cfg(scratch_url)
    command.upgrade(cfg, PRE_020)
    engine = create_engine(scratch_url)
    try:
        with engine.begin() as c:
            acc = c.execute(
                text("INSERT INTO accounts (name, type, currency) VALUES ('ZZ42 mig eur', 'liquid', 'EUR') RETURNING id")
            ).scalar()
        with pytest.raises(RuntimeError) as exc:
            command.upgrade(cfg, REV_020)
        msg = str(exc.value)
        assert "1 accounts" in msg and str(acc) in msg
        assert "ZZ42" not in msg
        _assert_rolled_back(engine)
    finally:
        engine.dispose()


def test_020_preflight_aborts_on_tx_account_mismatch(scratch_url):
    cfg, command = _cfg(scratch_url)
    command.upgrade(cfg, PRE_020)
    engine = create_engine(scratch_url)
    try:
        with engine.begin() as c:
            acc = c.execute(
                text("INSERT INTO accounts (name, type, currency) VALUES ('ZZ42 mig idr', 'liquid', 'IDR') RETURNING id")
            ).scalar()
            tx = _seed_tx(c, acc, "USD", "-12.50")
        with pytest.raises(RuntimeError) as exc:
            command.upgrade(cfg, REV_020)
        msg = str(exc.value)
        assert str(tx) in msg
        assert "ZZ42" not in msg and "12.5" not in msg
        _assert_rolled_back(engine)
    finally:
        engine.dispose()


def test_020_fresh_empty_db_upgrades_twice(scratch_url):
    cfg, command = _cfg(scratch_url)
    command.upgrade(cfg, REV_020)
    command.stamp(cfg, PRE_020)
    command.upgrade(cfg, REV_020)
