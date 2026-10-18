"""Tests for migration 018 (attachments) on a scratch DB.

Migration tests run against `monai_test_mig018`, created and dropped on the same
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
from sqlalchemy.exc import IntegrityError

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = REPO_ROOT / "alembic" / "versions" / "018_attachments.py"
PRE_018 = "edebc52384d8"
REV_018 = "22645aa717c0"
SCRATCH_DB = "monai_test_mig018"

COUNTS_SQL = text(
    "SELECT table_name, (xpath('/row/c/text()', query_to_xml("
    "format('select count(*) as c from %I.%I', table_schema, table_name), "
    "false, true, '')))[1]::text::bigint AS n "
    "FROM information_schema.tables "
    "WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY 1"
)

INDEXES = ("ix_attachments_thread_id", "ix_attachments_unpurged")


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


def _has_column(engine, table: str, column: str) -> bool:
    with engine.connect() as c:
        return bool(
            c.execute(
                text(
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_name=:t AND column_name=:c"
                ),
                {"t": table, "c": column},
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


def _insert_attachment(c, thread_id, **over):
    params = dict(t=thread_id, k="csv", s="ok", m=None, a=None)
    params.update(over)
    return c.execute(
        text(
            "INSERT INTO attachments (thread_id, message_id, filename, mime, kind, size_bytes, "
            "sha256, raw, parse_status, account_id) VALUES (:t, :m, 'zz018-a.csv', 'text/csv', "
            ":k, 2, repeat('0', 64), '\\x7a7a'::bytea, :s, :a) RETURNING id"
        ),
        params,
    ).scalar()


def test_018_imports_nothing_from_backend():
    src = MIGRATION_PATH.read_text()
    assert not re.search(r"^\s*(from|import)\s+backend\b", src, re.MULTILINE)
    assert f'"{PRE_018}"' in src and f'"{REV_018}"' in src


def test_018_upgrade_rerun_downgrade_preserve_rows(scratch_url):
    cfg, command = _cfg(scratch_url)
    command.upgrade(cfg, PRE_018)
    engine = create_engine(scratch_url)
    try:
        with engine.connect() as c:
            assert c.execute(text("SELECT current_database()")).scalar() == SCRATCH_DB
        with engine.begin() as c:
            c.execute(
                text(
                    "INSERT INTO proposals (id, token, operation, payload, status, expires_at) "
                    "VALUES (gen_random_uuid(), 'zz018-token-a', 'add_transaction', "
                    "CAST('{}' AS jsonb), 'pending', now() + interval '15 minutes')"
                )
            )
        before = _counts(engine)
        command.upgrade(cfg, REV_018)
        with engine.connect() as c:
            assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() == REV_018
        assert _has_table(engine, "attachments")
        assert all(_has_index(engine, i) for i in INDEXES)
        after = _counts(engine)
        assert after.pop("attachments") == 0
        assert after == before

        # re-run at head is a no-op (entrypoint.sh runs upgrade on every boot)
        command.stamp(cfg, PRE_018)
        command.upgrade(cfg, REV_018)
        again = _counts(engine)
        again.pop("attachments")
        assert again == before

        command.downgrade(cfg, PRE_018)
        assert not _has_table(engine, "attachments")
        assert not any(_has_index(engine, i) for i in INDEXES)
        assert _counts(engine) == before
    finally:
        engine.dispose()


def test_018_constraints_cascade_and_set_null(scratch_url):
    cfg, command = _cfg(scratch_url)
    command.upgrade(cfg, REV_018)
    engine = create_engine(scratch_url)
    try:
        thread_id, msg_id = uuid.uuid4(), uuid.uuid4()
        with engine.begin() as c:
            c.execute(text("INSERT INTO threads (id, title) VALUES (:i, 'zz018-thread')"), {"i": thread_id})
            c.execute(
                text("INSERT INTO messages (id, thread_id, seq, role) VALUES (:m, :t, 1, 'user')"),
                {"m": msg_id, "t": thread_id},
            )
            acct = c.execute(text("INSERT INTO accounts (name) VALUES ('ZZ018 Cash') RETURNING id")).scalar()
            att = _insert_attachment(c, thread_id, m=msg_id, a=acct)
            row = c.execute(
                text("SELECT extracted_text, rows::text, meta::text, purged_at FROM attachments WHERE id=:i"),
                {"i": att},
            ).one()
            assert row == ("", "[]", "{}", None)

        def rejected(**over) -> None:
            with pytest.raises(IntegrityError):
                with engine.begin() as c:
                    _insert_attachment(c, thread_id, **over)

        rejected(k="xlsx")
        rejected(s="needs_password")  # a response status, never stored

        with engine.begin() as c:
            c.execute(text("DELETE FROM messages WHERE id=:m"), {"m": msg_id})
            c.execute(text("DELETE FROM accounts WHERE id=:a"), {"a": acct})
        with engine.connect() as c:
            assert c.execute(
                text("SELECT message_id, account_id FROM attachments WHERE id=:i"), {"i": att}
            ).one() == (None, None)
        with engine.begin() as c:
            c.execute(text("DELETE FROM threads WHERE id=:t"), {"t": thread_id})
        with engine.connect() as c:
            assert c.execute(text("SELECT count(*) FROM attachments")).scalar() == 0
    finally:
        engine.dispose()


# --- model parity (conftest's monai_test, already migrated to head) ---------


def test_models_match_018_columns():
    from backend.db import engine
    from backend.models import Attachment

    with engine.connect() as c:
        db_cols = {
            r[0]: r[1]
            for r in c.execute(
                text("SELECT column_name, is_nullable FROM information_schema.columns WHERE table_name='attachments'")
            )
        }
    model_cols = {c.name: ("YES" if c.nullable else "NO") for c in Attachment.__table__.columns}
    assert model_cols == db_cols
