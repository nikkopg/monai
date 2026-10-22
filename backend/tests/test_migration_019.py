"""Tests for migration 019 (external MCP servers, selections, calls) on a scratch DB.

Migration tests run against `monai_test_mig019`, created and dropped on the same
server as conftest's guarded DATABASE_URL. Never touches the live `monai`. The
model-parity tests at the bottom use conftest's `monai_test`. All values are
synthetic.
"""
import os
import re
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DataError, IntegrityError

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = REPO_ROOT / "alembic" / "versions" / "019_external_mcp.py"
PRE_019 = "22645aa717c0"
REV_019 = "20116eb89bff"
SCRATCH_DB = "monai_test_mig019"
NEW_TABLES = ("mcp_servers", "thread_mcp_servers", "ext_calls")

COUNTS_SQL = text(
    "SELECT table_name, (xpath('/row/c/text()', query_to_xml("
    "format('select count(*) as c from %I.%I', table_schema, table_name), "
    "false, true, '')))[1]::text::bigint AS n "
    "FROM information_schema.tables "
    "WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY 1"
)

INDEXES = ("ix_ext_calls_pending", "ix_ext_calls_turn", "ix_ext_calls_thread")


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


def _has_table(engine, name: str) -> bool:
    with engine.connect() as c:
        return bool(
            c.execute(
                text("SELECT count(*) FROM information_schema.tables WHERE table_name=:n"),
                {"n": name},
            ).scalar()
        )


def _has_index(engine, name: str) -> bool:
    with engine.connect() as c:
        return bool(
            c.execute(text("SELECT count(*) FROM pg_indexes WHERE indexname=:n"), {"n": name}).scalar()
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


def _insert_server(c, **over):
    p = dict(slug="zz-mig", transport="http", url="https://zz.example.com/mcp", command=None)
    p.update(over)
    return c.execute(
        text(
            "INSERT INTO mcp_servers (slug, transport, url, command) "
            "VALUES (:slug, :transport, :url, :command) RETURNING id"
        ),
        p,
    ).scalar()


def _insert_call(c, thread_id, server_id=None, message_id=None, **over):
    p = dict(
        t=thread_id, turn=uuid.uuid4(), m=message_id, s=server_id,
        appr="approved", via="user", receipt=None, reason=None,
    )
    p.update(over)
    return c.execute(
        text(
            "INSERT INTO ext_calls (thread_id, turn_id, message_id, server_id, server_slug, "
            "tool, args, args_sha256, destination, leaves_machine, reason, approval, "
            "decided_via, expires_at, receipt) VALUES (:t, :turn, :m, :s, 'zz-mig', 'zz_tool', "
            "CAST('{\"q\": \"zz\"}' AS jsonb), repeat('0', 64), 'zz.example.com', true, "
            ":reason, :appr, :via, now() + interval '15 minutes', :receipt) RETURNING id"
        ),
        p,
    ).scalar()


def test_019_imports_nothing_from_backend():
    src = MIGRATION_PATH.read_text()
    assert not re.search(r"^\s*(from|import)\s+backend\b", src, re.MULTILINE)
    assert f'"{PRE_019}"' in src and f'"{REV_019}"' in src


def test_019_upgrade_rerun_downgrade_preserve_rows(scratch_url):
    cfg, command = _cfg(scratch_url)
    command.upgrade(cfg, PRE_019)
    engine = create_engine(scratch_url)
    try:
        with engine.connect() as c:
            assert c.execute(text("SELECT current_database()")).scalar() == SCRATCH_DB
        with engine.begin() as c:
            c.execute(text("INSERT INTO threads (id, title) VALUES (:i, 'zz migration')"), {"i": uuid.uuid4()})
        before = _counts(engine)
        command.upgrade(cfg, REV_019)
        with engine.connect() as c:
            assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() == REV_019
        assert all(_has_table(engine, t) for t in NEW_TABLES)
        assert all(_has_index(engine, i) for i in INDEXES)
        after = _counts(engine)
        assert all(after.pop(t) == 0 for t in NEW_TABLES)
        assert after == before

        # re-run is a no-op (entrypoint.sh runs upgrade on every boot)
        command.stamp(cfg, PRE_019)
        command.upgrade(cfg, REV_019)
        again = _counts(engine)
        assert all(again.pop(t) == 0 for t in NEW_TABLES)
        assert again == before

        command.downgrade(cfg, "-1")
        assert not any(_has_table(engine, t) for t in NEW_TABLES)
        assert not any(_has_index(engine, i) for i in INDEXES)
        assert _counts(engine) == before

        command.upgrade(cfg, "head")
        assert all(_has_table(engine, t) for t in NEW_TABLES)
    finally:
        engine.dispose()


def test_019_constraints(scratch_url):
    cfg, command = _cfg(scratch_url)
    command.upgrade(cfg, REV_019)
    engine = create_engine(scratch_url)
    try:
        with engine.begin() as c:
            thread_id = uuid.uuid4()
            c.execute(text("INSERT INTO threads (id, title) VALUES (:i, 'zz migration')"), {"i": thread_id})
            sid = _insert_server(c)
            row = c.execute(
                text(
                    "SELECT enabled, headers::text, args::text, env::text, approved_tools::text, "
                    "tool_policies::text, changed_count FROM mcp_servers WHERE id=:i"
                ),
                {"i": sid},
            ).one()
            assert row == (False, "{}", "[]", "{}", "[]", "{}", None)
            _insert_server(c, slug="zz-npx", transport="stdio", url=None, command="npx")

        def rejected(fn, *a, **kw) -> None:
            # VARCHAR(24) rejects an over-long slug as DataError before the CHECK runs
            with pytest.raises((IntegrityError, DataError)):
                with engine.begin() as c:
                    fn(c, *a, **kw)

        rejected(_insert_server, slug="zz-a", transport="stdio", url=None, command="bash")
        rejected(_insert_server, slug="zz-b", transport="stdio", url=None, command=None)
        rejected(_insert_server, slug="zz-c", transport="stdio", command="npx")  # stdio with a url
        rejected(_insert_server, slug="zz-d", transport="http", command="npx")  # http with a command
        rejected(_insert_server, slug="zz_bad")
        rejected(_insert_server, slug="z" * 25)
        rejected(_insert_server)  # duplicate slug zz-mig

        rejected(_insert_call, thread_id, sid, appr="pending", via="user")
        rejected(_insert_call, thread_id, sid, appr="approved", via=None)
        rejected(_insert_call, thread_id, sid, appr="maybe")
        rejected(_insert_call, thread_id, sid, via="admin")
        rejected(_insert_call, thread_id, sid, receipt="done")
        rejected(_insert_call, thread_id, sid, reason="other")

        with engine.begin() as c:
            _insert_call(c, thread_id, sid, appr="approved", via="policy", receipt="pending")
            _insert_call(c, thread_id, sid, appr="pending", via=None, reason="ledger_read")
    finally:
        engine.dispose()


def test_019_cascades(scratch_url):
    cfg, command = _cfg(scratch_url)
    command.upgrade(cfg, REV_019)
    engine = create_engine(scratch_url)
    try:
        thread_id, msg_id = uuid.uuid4(), uuid.uuid4()
        with engine.begin() as c:
            c.execute(text("INSERT INTO threads (id, title) VALUES (:i, 'zz migration')"), {"i": thread_id})
            c.execute(
                text("INSERT INTO messages (id, thread_id, seq, role) VALUES (:m, :t, 1, 'user')"),
                {"m": msg_id, "t": thread_id},
            )
            sid = _insert_server(c)
            c.execute(
                text("INSERT INTO thread_mcp_servers (thread_id, server_id) VALUES (:t, :s)"),
                {"t": thread_id, "s": sid},
            )
            call = _insert_call(c, thread_id, sid, message_id=msg_id)

        def scalar(sql, **p):
            with engine.connect() as c:
                return c.execute(text(sql), p).scalar()

        # deleting a message nulls ext_calls.message_id
        with engine.begin() as c:
            c.execute(text("DELETE FROM messages WHERE id=:m"), {"m": msg_id})
        assert scalar("SELECT message_id FROM ext_calls WHERE id=:i", i=call) is None

        # deleting the server drops its links, nulls server_id, keeps server_slug
        with engine.begin() as c:
            c.execute(text("DELETE FROM mcp_servers WHERE id=:s"), {"s": sid})
        assert scalar("SELECT count(*) FROM thread_mcp_servers") == 0
        with engine.connect() as c:
            assert c.execute(
                text("SELECT server_id, server_slug FROM ext_calls WHERE id=:i"), {"i": call}
            ).one() == (None, "zz-mig")

        # deleting the thread removes its ext_calls and links
        with engine.begin() as c:
            sid2 = _insert_server(c, slug="zz-two")
            c.execute(
                text("INSERT INTO thread_mcp_servers (thread_id, server_id) VALUES (:t, :s)"),
                {"t": thread_id, "s": sid2},
            )
            c.execute(text("DELETE FROM threads WHERE id=:t"), {"t": thread_id})
        assert scalar("SELECT count(*) FROM ext_calls") == 0
        assert scalar("SELECT count(*) FROM thread_mcp_servers") == 0
        assert scalar("SELECT count(*) FROM mcp_servers") == 1  # the server itself survives
    finally:
        engine.dispose()
