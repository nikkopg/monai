"""Phase 41 D-27 guards: external tools are per-run only and never join monai's own surfaces.
Synthetic servers and slugs `zz-*`; the isolated monai_test database. The stdio environment
scrub guard lives in test_mcp_client.py (`-k child_env`)."""
import subprocess
from pathlib import Path

import pytest

from backend import agent_loop, chat_tools, sources, tools as T
from backend.tests.test_mcp import _mcp_session, _tools_list
from backend.tests.test_ext_session import Env, env  # noqa: F401  (env is a fixture)

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_COMMIT = "44849ee"  # the Phase 41 base: the three surface snapshots must not move
SNAPSHOTS = ["backend/tests/agent_tool_surface.json", "backend/tests/mcp_tool_surface.json",
             "backend/tests/attachment_tool_surface.json"]
PINNED_QUESTIONS = ["what is in this file?", "total debits?", "and last month?", "import this file"]


def _ext(names):
    return [n for n in names if n.startswith("ext__")]


async def test_no_external_name_on_any_surface(env, client, api_key):  # noqa: F811
    await env.add()
    before = set(T.TOOLS)
    s = await env.open()
    try:
        assert s.tools and set(s.names).isdisjoint(T.TOOLS)  # per-run tools only
    finally:
        await s.aclose()
    assert set(T.TOOLS) == before
    for surface in (T.TOOLS, T.READ_TOOL_NAMES, chat_tools.CHAT_READ_NAMES, chat_tools.CHAT_ONLY_TOOLS):
        assert not _ext(surface)
    with client:
        listed = _tools_list(client, _mcp_session(client, api_key))
    assert listed and not _ext(t["name"] for t in listed)


@pytest.mark.parametrize("path", SNAPSHOTS)
def test_snapshots_unchanged(path):
    shown = subprocess.run(["git", "show", f"{SNAPSHOT_COMMIT}:{path}"], cwd=ROOT, capture_output=True)
    if shown.returncode:
        pytest.skip(f"{SNAPSHOT_COMMIT} is not in this clone's history")
    assert (ROOT / path).read_bytes() == shown.stdout


async def test_attachment_pin_ignores_servers(env):  # noqa: F811
    bare = {q: agent_loop.tools_for_turn(q, attachment_thread=True) for q in PINNED_QUESTIONS}
    await env.add()
    for q, names in bare.items():
        got = agent_loop.tools_for_turn(q, attachment_thread=True)
        assert got == names and not _ext(got)


async def test_disabled_server_never_constructed(env):  # noqa: F811
    await env.add(slug="zz-off", enabled=False)
    await env.add(slug="zz-unsel", selected=False)
    s = await env.open()
    try:
        assert env.built == [] and s.tools == [] and s.notices == []
    finally:
        await s.aclose()


def test_no_tool_module_writes_server_config():
    for module in ("tools.py", "chat_tools.py", "mcp_server.py", "mcp_writes.py"):
        src = (ROOT / "backend" / module).read_text()
        for word in ("mcp_servers", "McpServer", "mcp_client_api"):
            assert word not in src, f"{module} mentions {word}"


def test_external_results_never_make_chips():
    name = "ext__zz-synth__echo"
    assert sources.source_for(name, {}, {"tool": name, "result": "zz"}) == []
