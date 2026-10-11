"""Tests for migration 017 (chat threads/messages, proposals.turn_id/message_id) on a scratch DB.

Migration tests run against `monai_test_mig017`, created and dropped on the same
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
MIGRATION_PATH = REPO_ROOT / "alembic" / "versions" / "017_chat_threads_messages.py"
PRE_017 = "b6e2d9f4a170"
REV_017 = "edebc52384d8"
SCRATCH_DB = "monai_test_mig017"

COUNTS_SQL = text(
    "SELECT table_name, (xpath('/row/c/text()', query_to_xml("
    "format('select count(*) as c from %I.%I', table_schema, table_name), "
    "false, true, '')))[1]::text::bigint AS n "
    "FROM information_schema.tables "
    "WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY 1"
)

INDEXES = ("ix_threads_updated_at", "ix_proposals_turn_id")


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


def test_017_imports_nothing_from_backend():
    src = MIGRATION_PATH.read_text()
    assert not re.search(r"^\s*(from|import)\s+backend\b", src, re.MULTILINE)
    assert '"b6e2d9f4a170"' in src and '"edebc52384d8"' in src


def test_017_upgrade_rerun_downgrade_preserve_rows(scratch_url):
    cfg, command = _cfg(scratch_url)
    command.upgrade(cfg, PRE_017)
    engine = create_engine(scratch_url)
    try:
        with engine.connect() as c:
            assert c.execute(text("SELECT current_database()")).scalar() == SCRATCH_DB

        with engine.begin() as c:
            c.execute(
                text(
                    "INSERT INTO proposals (id, token, operation, payload, status, expires_at) "
                    "VALUES (gen_random_uuid(), 'zz017-token-a', 'add_transaction', "
                    "CAST('{\"operation\":\"add_transaction\",\"rows\":[]}' AS jsonb), "
                    "'pending', now() + interval '15 minutes')"
                )
            )

        before = _counts(engine)
        command.upgrade(cfg, REV_017)
        with engine.connect() as c:
            assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() == REV_017
            row = c.execute(
                text("SELECT turn_id, message_id FROM proposals WHERE token='zz017-token-a'")
            ).one()
        assert row == (None, None)
        assert _has_table(engine, "threads") and _has_table(engine, "messages")
        assert _has_column(engine, "proposals", "turn_id")
        assert _has_column(engine, "proposals", "message_id")
        assert all(_has_index(engine, i) for i in INDEXES)
        after = _counts(engine)
        assert after.pop("threads") == 0 and after.pop("messages") == 0
        assert after == before

        # re-run at head is a no-op (entrypoint.sh runs upgrade on every boot)
        command.stamp(cfg, PRE_017)
        command.upgrade(cfg, REV_017)
        again = _counts(engine)
        again.pop("threads"), again.pop("messages")
        assert again == before

        command.downgrade(cfg, PRE_017)
        assert not _has_table(engine, "threads") and not _has_table(engine, "messages")
        assert not _has_column(engine, "proposals", "turn_id")
        assert not _has_column(engine, "proposals", "message_id")
        assert not any(_has_index(engine, i) for i in INDEXES)
        assert _counts(engine) == before
    finally:
        engine.dispose()


def test_017_constraints_cascade_and_set_null(scratch_url):
    cfg, command = _cfg(scratch_url)
    command.upgrade(cfg, REV_017)
    engine = create_engine(scratch_url)
    try:
        thread_id, user_msg, asst_msg = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        turn_id = uuid.uuid4()
        with engine.begin() as c:
            c.execute(
                text("INSERT INTO threads (id, title) VALUES (:i, 'ZZ017 thread')"), {"i": thread_id}
            )
            t = c.execute(
                text("SELECT title, summary, summary_upto_seq FROM threads WHERE id=:i"), {"i": thread_id}
            ).one()
            assert t == ("ZZ017 thread", None, 0)
            # a bare thread picks up the title default too
            default_title = c.execute(text("INSERT INTO threads DEFAULT VALUES RETURNING title")).scalar()
            assert default_title == ""
            c.execute(
                text(
                    "INSERT INTO messages (id, thread_id, seq, role) VALUES "
                    "(:u, :t, 1, 'user'), (:a, :t, 2, 'assistant')"
                ),
                {"u": user_msg, "a": asst_msg, "t": thread_id},
            )
            m = c.execute(
                text("SELECT content, parts::text, status FROM messages WHERE id=:i"), {"i": asst_msg}
            ).one()
            assert m == ("", "{}", "complete")

        def rejected(sql: str, **params) -> None:
            with pytest.raises(IntegrityError):
                with engine.begin() as c:
                    c.execute(text(sql), params)

        ins = "INSERT INTO messages (thread_id, seq, role, status) VALUES (:t, :s, :r, :st)"
        rejected(ins, t=thread_id, s=3, r="system", st="complete")
        rejected(ins, t=thread_id, s=3, r="user", st="pending")
        rejected(ins, t=thread_id, s=2, r="user", st="complete")

        with engine.begin() as c:
            c.execute(
                text(
                    "INSERT INTO proposals (id, token, operation, payload, status, expires_at, "
                    "turn_id, message_id) VALUES (gen_random_uuid(), 'zz017-token-b', 'add_transaction', "
                    "CAST('{}' AS jsonb), 'pending', now() + interval '15 minutes', :turn, :m)"
                ),
                {"turn": turn_id, "m": asst_msg},
            )
            c.execute(text("DELETE FROM threads WHERE id=:i"), {"i": thread_id})
        with engine.connect() as c:
            assert c.execute(
                text("SELECT count(*) FROM messages WHERE thread_id=:i"), {"i": thread_id}
            ).scalar() == 0
            p = c.execute(
                text("SELECT message_id, turn_id FROM proposals WHERE token='zz017-token-b'")
            ).one()
        assert p == (None, turn_id)
    finally:
        engine.dispose()


# --- model parity (conftest's monai_test, already migrated to head) ---------


def test_models_match_017_columns():
    from backend.db import engine
    from backend.models import Message, Proposal, Thread

    with engine.connect() as c:
        for model in (Thread, Message, Proposal):
            table = model.__table__.name
            db_cols = {
                r[0]
                for r in c.execute(
                    text("SELECT column_name FROM information_schema.columns WHERE table_name=:t"),
                    {"t": table},
                )
            }
            assert set(model.__table__.columns.keys()) == db_cols, table


def test_orm_thread_delete_cascades():
    from backend.db import SessionLocal
    from backend.models import Message, Thread

    with SessionLocal() as db:
        thread = Thread(title="ZZ017 orm")
        thread.messages = [
            Message(seq=1, role="user", content="ZZ017 q"),
            Message(seq=2, role="assistant"),
        ]
        db.add(thread)
        db.commit()
        tid = thread.id
        try:
            db.refresh(thread)
            assert [m.status for m in thread.messages] == ["complete", "complete"]
            assert thread.messages[1].parts == {}
            db.delete(thread)
            db.commit()
            left = db.execute(
                text("SELECT count(*) FROM messages WHERE thread_id=:i"), {"i": tid}
            ).scalar()
            assert left == 0
        finally:
            db.rollback()
            db.execute(text("DELETE FROM threads WHERE id=:i"), {"i": tid})
            db.commit()
