"""Tests for migration 016 (portfolio_events.transaction_id cash-leg link) on a scratch DB.

Runs against `monai_test_mig016`, created and dropped on the same server as
conftest's guarded DATABASE_URL. Never touches the live `monai`. All seed
values are synthetic.
"""
import os
import re
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = REPO_ROOT / "alembic" / "versions" / "016_portfolio_event_cash_leg.py"
PRE_016 = "f5c8a2d7e319"
REV_016 = "b6e2d9f4a170"
SCRATCH_DB = "monai_test_mig016"

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


def _has_column(engine) -> bool:
    with engine.connect() as c:
        return bool(
            c.execute(
                text(
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_name='portfolio_events' AND column_name='transaction_id'"
                )
            ).scalar()
        )


def _has_index(engine) -> bool:
    with engine.connect() as c:
        return bool(
            c.execute(
                text("SELECT count(*) FROM pg_indexes WHERE indexname='ix_portfolio_events_transaction_id'")
            ).scalar()
        )


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


def test_016_imports_nothing_from_backend():
    src = MIGRATION_PATH.read_text()
    assert not re.search(r"^\s*(from|import)\s+backend\b", src, re.MULTILINE)
    assert '"f5c8a2d7e319"' in src and '"b6e2d9f4a170"' in src


def _tx(c, acct, day, amount, category="Investment", transfer=True) -> int:
    return c.execute(
        text(
            "INSERT INTO transactions (date, amount, currency, category, account_id, is_transfer) "
            "VALUES (:d, :a, 'IDR', :cat, :acct, :tr) RETURNING id"
        ),
        {"d": f"{day} 09:30:00", "a": amount, "cat": category, "acct": acct, "tr": transfer},
    ).scalar()


def _ev(c, plat, ticker, etype, day, acct) -> int:
    return c.execute(
        text(
            "INSERT INTO portfolio_events (date, ticker, event_type, quantity, price, platform_id, "
            "currency, source_account_id) VALUES (:d, :t, :e, 1, 100, :p, 'IDR', :a) RETURNING id"
        ),
        {"d": day, "t": ticker, "e": etype, "p": plat, "a": acct},
    ).scalar()


def test_016_backfill_links_only_one_to_one_matches(scratch_url):
    cfg, command = _cfg(scratch_url)
    command.upgrade(cfg, PRE_016)
    engine = create_engine(scratch_url)
    try:
        with engine.connect() as c:
            assert c.execute(text("SELECT current_database()")).scalar() == SCRATCH_DB

        with engine.begin() as c:
            acct = c.execute(
                text("INSERT INTO accounts (name, type, currency) VALUES ('zzo3y-acct', 'liquid', 'IDR') RETURNING id")
            ).scalar()
            plat = c.execute(
                text("INSERT INTO platforms (name, kind) VALUES ('zzo3y-plat', 'exchange') RETURNING id")
            ).scalar()
            # 1:1 buy -> linked
            tx_ok = _tx(c, acct, "2024-01-10", -100)
            ev_ok = _ev(c, plat, "ZZO3YA", "buy", "2024-01-10", acct)
            # sell with two matching positive txs -> NULL
            _tx(c, acct, "2024-02-10", 100)
            _tx(c, acct, "2024-02-10", 200)
            ev_amb_tx = _ev(c, plat, "ZZO3YA", "sell", "2024-02-10", acct)
            # two buys, one matching tx -> both NULL
            _tx(c, acct, "2024-03-10", -100)
            ev_two_a = _ev(c, plat, "ZZO3YA", "buy", "2024-03-10", acct)
            ev_two_b = _ev(c, plat, "ZZO3YB", "buy", "2024-03-10", acct)
            # no source account -> NULL
            _tx(c, acct, "2024-04-10", -100)
            ev_nosrc = _ev(c, plat, "ZZO3YA", "buy", "2024-04-10", None)
            # wrong sign -> NULL
            _tx(c, acct, "2024-05-10", 100)
            ev_sign = _ev(c, plat, "ZZO3YA", "buy", "2024-05-10", acct)

        before = _counts(engine)
        command.upgrade(cfg, REV_016)
        with engine.connect() as c:
            assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() == REV_016
        assert _counts(engine) == before

        def link(ev_id):
            with engine.connect() as c:
                return c.execute(
                    text("SELECT transaction_id FROM portfolio_events WHERE id=:i"), {"i": ev_id}
                ).scalar()

        assert link(ev_ok) == tx_ok
        for ev_id in (ev_amb_tx, ev_two_a, ev_two_b, ev_nosrc, ev_sign):
            assert link(ev_id) is None
        assert _has_column(engine) and _has_index(engine)

        # re-run at head is a no-op
        command.stamp(cfg, PRE_016)
        command.upgrade(cfg, REV_016)
        assert _counts(engine) == before
        assert link(ev_ok) == tx_ok

        command.downgrade(cfg, PRE_016)
        assert not _has_column(engine) and not _has_index(engine)
        assert _counts(engine) == before
    finally:
        engine.dispose()
