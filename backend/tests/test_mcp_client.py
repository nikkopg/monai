"""Outbound MCP client (Phase 41-03): transports, launcher, hashing, adapter, wrapper.

Synthetic values only; the server under test is backend/evals/ext_test_server.py.
"""

import asyncio
import contextlib
import socket
import sys
import time

import pytest
from fastmcp import Client
from fastmcp.client.transports import FastMCPTransport, StdioTransport

from backend import config, mcp_client as mc
from backend.evals import ext_test_server as srv

SERVER = [srv.__file__]  # by path: the stdio child runs in a work dir outside the repo
FORBIDDEN = {"DATABASE_URL", "MONAI_API_KEY", "MONAI_APPROVER_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"}


def spec(**kw) -> mc.ServerSpec:
    base = dict(id=None, slug="zz-synth", transport="http", url="https://notes.example.com/mcp",
                headers={}, command=None, args=(), env={})
    return mc.ServerSpec(**{**base, **kw})


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextlib.asynccontextmanager
async def serve(mode: str, variant: str = "base"):
    """The synthetic server as a child process on a free port; yields its URL."""
    port = free_port()
    proc = await asyncio.create_subprocess_exec(
        sys.executable, *SERVER, mode, str(port), variant,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            with contextlib.suppress(OSError):
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    break
            await asyncio.sleep(0.2)
        else:
            raise AssertionError("synthetic server did not start")
        yield f"http://127.0.0.1:{port}/{'mcp' if mode == 'http' else 'sse'}"
    finally:
        proc.kill()
        await proc.wait()


def stdio_spec(tmp_path, **kw) -> mc.ServerSpec:
    return spec(transport="stdio", url=None, **kw)


@pytest.fixture
def stdio_transport(tmp_path, monkeypatch):
    """build_transport -> the synthetic server as a real child, base under tmp_path."""
    def build(variant="base", env=None):
        return StdioTransport(
            command=sys.executable, args=[*SERVER, "stdio", "0", variant],
            env=mc.child_env(env or {"ZZ_OWN": "1"}, str(tmp_path)),
            cwd=mc.work_dir("zz-synth", str(tmp_path)), keep_alive=False,
        )
    return build


async def tool_names(client) -> list[str]:
    return sorted(t.name for t in await mc.list_server_tools(client))


# ── transports ──────────────────────────────────────────────────────────────

async def test_transports_list_the_same_tools(stdio_transport):
    async with Client(FastMCPTransport(srv.build())) as c:
        want = await tool_names(c)
    assert "echo" in want and "lookup" in want
    async with Client(stdio_transport(), init_timeout=15, timeout=15) as c:
        assert await tool_names(c) == want
    for mode in ("http", "sse"):
        async with serve(mode) as url:
            s = spec(transport=mode, url=url)
            client = await mc.open_client(s)
            try:
                assert await tool_names(client) == want
                res = await client.call_tool("lookup", {})
                assert res.content[0].text == srv.HOSTILE  # byte for byte
            finally:
                await mc.close_client(client)


# ── argv ────────────────────────────────────────────────────────────────────

def test_argv_allowlist_and_dash_y(monkeypatch):
    monkeypatch.setattr(mc.os, "geteuid", lambda: 1000)
    with pytest.raises(ValueError):
        mc.stdio_argv("bash", ["-c", "true"])
    assert mc.stdio_argv("npx", ["@example/notes-mcp@1.2.3"]) == ("npx", ["-y", "@example/notes-mcp@1.2.3"])
    assert mc.stdio_argv("uvx", ["example-mcp==1.2.3"]) == ("uvx", ["example-mcp==1.2.3"])


def test_argv_root_drops_to_unprivileged_uid(monkeypatch):
    monkeypatch.setattr(mc.os, "geteuid", lambda: 0)
    monkeypatch.setattr(mc.shutil, "which", lambda name: "/usr/bin/setpriv")
    cmd, args = mc.stdio_argv("npx", ["@example/notes-mcp@1.2.3"])
    assert cmd == "setpriv" and isinstance(args, list)
    assert args == ["--reuid=10001", "--regid=10001", "--clear-groups", "--no-new-privs",
                    "--inh-caps=-all", "--bounding-set=-all", "--", "npx", "-y", "@example/notes-mcp@1.2.3"]


def test_argv_root_without_setpriv_refuses(monkeypatch):
    monkeypatch.setattr(mc.os, "geteuid", lambda: 0)
    monkeypatch.setattr(mc.shutil, "which", lambda name: None)
    with pytest.raises(ValueError):
        mc.stdio_argv("npx", ["x@1.0.0"])


# ── child env ───────────────────────────────────────────────────────────────

async def test_child_env_has_no_backend_secrets(monkeypatch, stdio_transport):
    for k in FORBIDDEN:
        monkeypatch.setenv(k, "synthetic-value-0123456789")
    async with Client(stdio_transport(), init_timeout=15, timeout=15) as c:
        keys = set((await c.call_tool("env_dump", {})).data["keys"])
    assert not FORBIDDEN & keys and "ZZ_OWN" in keys
    assert keys <= {"HOME", "LOGNAME", "PATH", "SHELL", "TERM", "USER", "LC_CTYPE", "TMPDIR",
                    "npm_config_cache", "UV_CACHE_DIR", "XDG_CACHE_HOME", "ZZ_OWN"}


def test_child_env_monai_keys_win(tmp_path):
    env = mc.child_env({"HOME": "/zz", "ZZ_OWN": "1"}, str(tmp_path))
    assert env["HOME"].startswith(str(tmp_path)) and env["ZZ_OWN"] == "1"


def test_env_name_denylist():
    for bad in ("PATH", "HOME", "TMPDIR", "LD_PRELOAD", "NODE_OPTIONS", "PYTHONPATH", "PYTHONSTARTUP",
                "npm_config_cache", "UV_CACHE_DIR", "XDG_CACHE_HOME", "has space"):
        assert not mc.env_name_allowed(bad), bad
    assert mc.env_name_allowed("ZZ_TOKEN")


# ── destination ─────────────────────────────────────────────────────────────

def test_destination_and_leaves_machine():
    remote = spec(url="https://notes.example.com/mcp")
    assert mc.destination(remote) == "notes.example.com" and mc.leaves_machine(remote)
    for url in ("http://127.0.0.1:18431/mcp", "http://localhost:9/mcp", "http://[::1]:9/mcp"):
        assert not mc.leaves_machine(spec(url=url)), url
    local = spec(transport="stdio", url=None, command="npx", args=("-y", "@example/notes-mcp@1.2.3"))
    assert mc.destination(local) == "local command: npx @example/notes-mcp@1.2.3"
    assert not mc.leaves_machine(local)


# ── timeouts and lifecycle ──────────────────────────────────────────────────

async def test_timeout_mute_server_fails_fast_and_close_is_quiet(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "EXT_CONNECT_TIMEOUT_SECONDS", 2.0)
    mute = StdioTransport(command=sys.executable, args=["-c", "import time; time.sleep(60)"],
                          cwd=str(tmp_path), keep_alive=False)
    monkeypatch.setattr(mc, "build_transport", lambda s: mute)
    t0 = time.monotonic()
    with pytest.raises(mc.ExtUnavailable) as e:
        await mc.open_client(spec(transport="stdio", url=None))
    assert time.monotonic() - t0 < 10
    assert e.value.error_class and "tmp" not in str(e.value)
    failed = Client(mute, init_timeout=1, timeout=1)
    with contextlib.suppress(Exception):
        await failed.__aenter__()
    await mc.close_client(failed)  # must not raise


async def test_lifecycle_open_list_close(monkeypatch):
    monkeypatch.setattr(mc, "build_transport", lambda s: FastMCPTransport(srv.build()))

    async def run():
        client = await mc.open_client(spec())
        assert client.is_connected()
        assert "echo" in await tool_names(client)
        await mc.close_client(client)
        return client

    client = await asyncio.create_task(run())
    assert not client.is_connected()
