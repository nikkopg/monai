"""
Guard self-test for backend/tests/conftest.py's live-database refusal
(TEST-01 criterion 2, D-03, D-09).

Proves:
  - The guard refuses DATABASE_URL when the parsed database name is exactly
    "monai" — with and without a trailing query string, since the check
    parses the database name component; it never does a string-suffix match.
  - The guard refuses any query-string dbname= (including an empty one),
    which would otherwise replace the path database at connect time.
  - The guard proceeds (no refusal) for the session's own test database name
    (monai_test locally, the postgres service database in CI) — a name that
    merely *contains* "monai" is not refused.

Why the refused cases use a dead port (127.0.0.1:1): if the guard's exact-
match check ever regresses to a substring/suffix match, or is removed
entirely, the child pytest process would otherwise try to actually connect
to a real database and could hang or, worse, silently succeed against
whatever happens to be listening. Port 1 is never a real Postgres, so a
regressed guard still can't reach a database — the missing "Refusing to
run" text in the child's output is what fails this test, not a connection
error being mistaken for the correct outcome.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy.engine.url import make_url

_REPO_ROOT = Path(__file__).resolve().parents[2]

_DEAD_PORT_MONAI_URL = "postgresql+psycopg://monai:monai@127.0.0.1:1/monai"
_DEAD_PORT_MONAI_URL_WITH_QUERY = (
    "postgresql+psycopg://monai:monai@127.0.0.1:1/monai?connect_timeout=1"
)
# A query-string dbname= replaces the path database at connect time, so both
# must be refused even though the path names a test database (CR-01).
_DEAD_PORT_DBNAME_OVERRIDE_URL = (
    "postgresql+psycopg://monai:monai@127.0.0.1:1/monai_test?dbname=monai"
)
_DEAD_PORT_EMPTY_DBNAME_URL = "postgresql+psycopg://monai:monai@127.0.0.1:1/monai_test?dbname="


def _run_pytest(database_url: str) -> subprocess.CompletedProcess:
    """Run the collection of a trivial, DB-free test file as a subprocess
    with DATABASE_URL set, so this module never imports conftest.py's guard
    into the parent test process's own already-checked environment."""
    return subprocess.run(
        [
            sys.executable, "-m", "pytest",
            "backend/tests/test_router.py",
            "--collect-only", "-q", "-p", "no:cacheprovider",
        ],
        cwd=_REPO_ROOT,
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        timeout=180,
    )


@pytest.mark.parametrize(
    "database_url",
    [
        _DEAD_PORT_MONAI_URL,
        _DEAD_PORT_MONAI_URL_WITH_QUERY,
        _DEAD_PORT_DBNAME_OVERRIDE_URL,
        _DEAD_PORT_EMPTY_DBNAME_URL,
    ],
)
def test_refuses_live_database_name(database_url: str) -> None:
    result = _run_pytest(database_url)
    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert "Refusing to run" in combined


def test_allows_test_database_name() -> None:
    # conftest.py has already defaulted and checked DATABASE_URL by the time
    # this test process is running — reuse whatever it settled on.
    test_url = os.environ["DATABASE_URL"]
    assert make_url(test_url).database != "monai"  # precondition

    result = _run_pytest(test_url)
    combined = result.stdout + result.stderr
    assert result.returncode == 0
    assert "Refusing to run" not in combined
