"""
Startup timezone check tests (DEPLOY-04 / D-08).

Unit tests for backend.main._check_timezone. No DB and no dependency on the
test runner's own TZ: the process timezone is controlled via a fixture that
sets a POSIX fixed-offset TZ string and calls time.tzset(); the DB check is
driven with a stub session_factory (never a live connection).
"""

import contextlib
import logging
import os
import time

import pytest

from backend.main import _check_timezone


@pytest.fixture()
def process_tz():
    """Set the process TZ via a POSIX fixed-offset string + time.tzset().

    Restores the original TZ (or deletes it, if it was absent) in this
    fixture's own teardown and calls time.tzset() again — not via
    monkeypatch.setenv, whose undo runs AFTER this fixture's teardown and
    would leave tzset() applied against the still-patched value.
    """
    original = os.environ.get("TZ")

    def _set(posix_tz: str) -> None:
        os.environ["TZ"] = posix_tz
        time.tzset()

    yield _set

    if original is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = original
    time.tzset()


def _stub_session_factory(tz_value: str):
    """A session_factory context manager whose execute(...).scalar() returns tz_value."""

    class _Result:
        def scalar(self):
            return tz_value

    class _Session:
        def execute(self, *_args, **_kwargs):
            return _Result()

    @contextlib.contextmanager
    def factory():
        yield _Session()

    return factory


def _raising_session_factory():
    """A session_factory that raises when entered (DB unreachable)."""

    @contextlib.contextmanager
    def factory():
        raise RuntimeError("connection refused")
        yield  # pragma: no cover

    return factory


def _warnings(caplog):
    return [r for r in caplog.records if r.name == "backend.main" and r.levelno == logging.WARNING]


def _infos(caplog):
    return [r for r in caplog.records if r.name == "backend.main" and r.levelno == logging.INFO]


def test_matching_process_and_db_tz_logs_no_warning(process_tz, caplog):
    process_tz("WIB-7")
    caplog.set_level(logging.INFO, logger="backend.main")

    _check_timezone(_stub_session_factory("Asia/Jakarta"))

    assert _warnings(caplog) == []
    infos = _infos(caplog)
    assert any("+07:00" in r.message for r in infos)
    assert any("Asia/Jakarta" in r.message for r in infos)


def test_utc_process_logs_one_warning(process_tz, caplog):
    process_tz("UTC0")
    caplog.set_level(logging.INFO, logger="backend.main")

    _check_timezone(_stub_session_factory("Asia/Jakarta"))

    warnings = _warnings(caplog)
    assert len(warnings) == 1
    assert "+07:00" in warnings[0].message


def test_mismatched_db_tz_logs_one_warning(process_tz, caplog):
    process_tz("WIB-7")
    caplog.set_level(logging.INFO, logger="backend.main")

    _check_timezone(_stub_session_factory("UTC"))

    warnings = _warnings(caplog)
    assert len(warnings) == 1
    assert "UTC" in warnings[0].message


def test_db_unreachable_logs_one_warning_and_does_not_raise(process_tz, caplog):
    process_tz("WIB-7")
    caplog.set_level(logging.INFO, logger="backend.main")

    _check_timezone(_raising_session_factory())  # must not raise

    warnings = _warnings(caplog)
    assert len(warnings) == 1
    assert "could not" in warnings[0].message.lower()
