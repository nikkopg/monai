"""Tests for migration 015 (FOUND-04, D-01, D-03) on a throwaway scratch database.

Runs against `monai_test_mig015`, created and dropped on the same server as
conftest's guarded DATABASE_URL. Never touches the live `monai`, and never
downgrades `monai_test` itself. All seed values are synthetic.
"""
import os
import re
import secrets
from pathlib import Path

import pytest
import sqlalchemy.exc
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = REPO_ROOT / "alembic" / "versions" / "015_proposals_approval.py"
PRE_015 = "e7f3b1a9c204"
REV_015 = "f5c8a2d7e319"
SCRATCH_DB = "monai_test_mig015"
NEW_COLUMNS = {"channel", "supersedes_id", "code", "failed_attempts", "status_changed_at"}

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
    # conftest already put the real alembic package in sys.modules
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    cfg.attributes["sqlalchemy.url"] = url  # raw string, never str(URL)
    return cfg, command


def _proposal_columns(engine) -> set[str]:
    with engine.connect() as c:
        return {
            r[0]
            for r in c.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'proposals'"
                )
            )
        }


def _has_objects(engine) -> tuple[bool, set[str]]:
    with engine.connect() as c:
        ck = c.execute(
            text(
                "SELECT count(*) FROM pg_constraint WHERE conname = 'ck_proposals_channel' "
                "AND conrelid = 'proposals'::regclass"
            )
        ).scalar()
        idx = {
            r[0]
            for r in c.execute(
                text(
                    "SELECT indexname FROM pg_indexes WHERE tablename = 'proposals' "
                    "AND indexname IN ('ix_proposals_status_changed_at', 'ix_proposals_pending_expires')"
                )
            )
        }
    return bool(ck), idx


@pytest.fixture()
def scratch_url(monkeypatch):
    # alembic/env.py calls logging.config.fileConfig, which disables every
    # existing logger and would break caplog tests that run later; no-op it.
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


def test_015_imports_nothing_from_backend():
    src = MIGRATION_PATH.read_text()
    assert not re.search(r"^\s*(from|import)\s+backend\b", src, re.MULTILINE)
    assert '"e7f3b1a9c204"' in src and '"f5c8a2d7e319"' in src


_INSERT = text(
    "INSERT INTO proposals (id, token, operation, payload, status, expires_at, created_at, confirmed_at) "
    "VALUES (gen_random_uuid(), :tok, 'add_transaction', "
    "CAST('{\"operation\": \"add_transaction\", \"rows\": []}' AS jsonb), :st, "
    "'2020-01-01 00:15:00+00', '2020-01-01 00:00:00+00', :conf)"
)


def test_015_upgrade_rerun_downgrade_preserve_rows(scratch_url):
    cfg, command = _cfg(scratch_url)
    command.upgrade(cfg, PRE_015)
    engine = create_engine(scratch_url)
    try:
        with engine.connect() as c:
            assert c.execute(text("SELECT current_database()")).scalar() == SCRATCH_DB

        seeds = [
            ("confirmed", "2020-01-01 00:01:00+00"),
            ("rejected", None),
            ("pending", None),
        ]
        with engine.begin() as c:
            for st, conf in seeds:
                c.execute(_INSERT, {"tok": secrets.token_urlsafe(32), "st": st, "conf": conf})

        before = _counts(engine)
        command.upgrade(cfg, REV_015)
        with engine.connect() as c:
            assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() == REV_015
        assert _counts(engine) == before

        with engine.connect() as c:
            bad = c.execute(
                text(
                    "SELECT count(*) FROM proposals WHERE channel <> 'chat' OR failed_attempts <> 0 "
                    "OR code IS NOT NULL OR supersedes_id IS NOT NULL "
                    "OR status_changed_at IS DISTINCT FROM COALESCE(confirmed_at, created_at)"
                )
            ).scalar()
        assert bad == 0

        ck, idx = _has_objects(engine)
        assert ck and idx == {"ix_proposals_status_changed_at", "ix_proposals_pending_expires"}

        with pytest.raises(sqlalchemy.exc.IntegrityError):
            with engine.begin() as c:
                c.execute(
                    text(
                        "INSERT INTO proposals (id, token, operation, payload, status, expires_at, channel) "
                        "VALUES (gen_random_uuid(), :tok, 'add_transaction', CAST('{}' AS jsonb), "
                        "'pending', '2020-01-01 00:15:00+00', 'bogus')"
                    ),
                    {"tok": secrets.token_urlsafe(32)},
                )
        assert _counts(engine) == before

        cols = _proposal_columns(engine)
        command.stamp(cfg, PRE_015)
        command.upgrade(cfg, REV_015)
        assert _counts(engine) == before
        assert _proposal_columns(engine) == cols

        command.downgrade(cfg, PRE_015)
        assert not (_proposal_columns(engine) & NEW_COLUMNS)
        ck, idx = _has_objects(engine)
        assert not ck and not idx
        assert _counts(engine) == before
    finally:
        engine.dispose()
