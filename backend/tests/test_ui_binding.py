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

_NEXT_COMMAND_RE = re.compile(r"next (?:dev|start)\b[^\"'`\n]*")
_LOCALHOST_RE = re.compile(r"-H 127\.0\.0\.1(?:\s|$)")


def _next_commands(text: str) -> list[str]:
    """Return every `next dev`/`next start` invocation found in text."""
    return _NEXT_COMMAND_RE.findall(text)


def _binds_localhost(cmd: str) -> bool:
    """True iff cmd carries -H 127.0.0.1 as a whole token (not 127.0.0.10)."""
    return bool(_LOCALHOST_RE.search(cmd))


@pytest.mark.parametrize("filename", ["package.json", "playwright.config.ts"])
def test_ui_servers_bind_localhost(filename):
    text = (UI / filename).read_text(encoding="utf-8")
    commands = _next_commands(text)
    assert commands, f"{filename}: no next dev/start command found (guard is vacuous)"

    unbound = [c for c in commands if not _binds_localhost(c)]
    assert unbound == [], f"{filename}: command(s) missing -H 127.0.0.1: {unbound}"


def test_guard_flags_unbound_command():
    """Self-check (D-12): the guard must actually fail on a bare command."""
    found = _next_commands('"dev": "next dev -p 3099"')
    assert found == ["next dev -p 3099"]
    assert not _binds_localhost(found[0])
    assert _binds_localhost("next dev -H 127.0.0.1 -p 3099")
