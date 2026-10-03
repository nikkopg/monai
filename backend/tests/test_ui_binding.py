"""
UI server binding guard (TD-03).

monai is a single-user finance app: every UI dev/start/e2e Next.js server
must listen on 127.0.0.1 only, never the LAN. CI has no UI test runner, so
this check lives in the backend suite instead, where CI already runs it.

No DB, no fixtures, no backend import — this module only reads two files
under ui/.
"""

import re
from pathlib import Path

import pytest

UI = Path(__file__).resolve().parents[2] / "ui"

# `next`, any whitespace, then dev/start; runs to the end of the enclosing
# string, so a template string's later lines are included.
_NEXT_COMMAND_RE = re.compile(r"next\s+(?:dev|start)\b[^\"'`]*")
# -H/--hostname as a whole token, value after a space or "=".
_HOST_FLAG_RE = re.compile(r"(?<!\S)(?:-H|--hostname)(?:\s+|=)([^\s;,&|]+)")


def _next_commands(text: str) -> list[str]:
    """Return every `next dev`/`next start` invocation found in text."""
    return _NEXT_COMMAND_RE.findall(text)


def _binds_localhost(cmd: str) -> bool:
    """True iff the LAST host flag in cmd is 127.0.0.1. Next's arg parser
    lets the last -H/--hostname win, so an earlier 127.0.0.1 proves nothing."""
    hosts = _HOST_FLAG_RE.findall(cmd)
    return bool(hosts) and hosts[-1] == "127.0.0.1"


@pytest.mark.parametrize("filename", ["package.json", "playwright.config.ts"])
def test_ui_servers_bind_localhost(filename):
    text = (UI / filename).read_text(encoding="utf-8")
    # Catches what the per-command check can't see, e.g. an
    # `npm run dev -- -H 0.0.0.0` passthrough script.
    assert "0.0.0.0" not in text, f"{filename}: mentions 0.0.0.0"

    commands = _next_commands(text)
    assert commands, f"{filename}: no next dev/start command found (guard is vacuous)"

    unbound = [c for c in commands if not _binds_localhost(c)]
    assert unbound == [], f"{filename}: command(s) not bound to 127.0.0.1: {unbound}"


def test_guard_flags_unbound_command():
    """Self-check (D-12): the guard must fail on every known bypass."""
    found = _next_commands('"dev": "next dev -p 3099"')
    assert found == ["next dev -p 3099"]
    assert not _binds_localhost(found[0])

    for bad in (
        "next dev -H 127.0.0.1 -p 3099 -H 0.0.0.0",  # later flag overrides
        "next dev -H 127.0.0.1 --hostname=0.0.0.0",
        "next dev -H 127.0.0.10 -p 3099",
    ):
        assert not _binds_localhost(bad), bad
    assert _next_commands('"x": "next  dev -H 0.0.0.0"') == ["next  dev -H 0.0.0.0"]
    assert _next_commands('"x": "next\tstart -p 1"') == ["next\tstart -p 1"]

    for good in (
        "next dev -H 127.0.0.1 -p 3099",
        "next dev --hostname 127.0.0.1",
        "next dev -H=127.0.0.1",
    ):
        assert _binds_localhost(good), good
