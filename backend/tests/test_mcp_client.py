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


# ── hashing, naming, adapter, validation ────────────────────────────────────

async def listed(variant="base") -> list:
    async with Client(FastMCPTransport(srv.build(variant))) as c:
        return await mc.list_server_tools(c)


def by_name(tools) -> dict:
    return {t.name: t for t in tools}


async def test_hash_is_stable_and_sensitive():
    a, b = by_name(await listed()), by_name(await listed())
    assert mc.tool_sha(a["echo"]) == mc.tool_sha(b["echo"])
    assert mc.tool_sha(a["echo"]) == mc.tool_sha({"name": "echo", "description": a["echo"].description,
                                                  "inputSchema": a["echo"].inputSchema})
    changed = by_name(await listed("changed"))
    assert mc.tool_sha(changed["echo"]) != mc.tool_sha(a["echo"])
    d = {"name": "x", "description": "d", "inputSchema": {"type": "object"}}
    assert mc.tool_sha(d) != mc.tool_sha({**d, "inputSchema": {"type": "object", "properties": {}}})
    assert mc.tool_sha(d) == mc.tool_sha({**d, "annotations": {"readOnlyHint": True}})
    tools = list(a.values())
    assert mc.tools_hash(tools) == mc.tools_hash(list(reversed(tools)))
    assert mc.tools_hash(tools) != mc.tools_hash(list(changed.values()))


def test_name_fits_or_is_none():
    assert mc.ext_name("zz-synth", "echo") == "ext__zz-synth__echo"
    for slug, tool in (("zz-synth", "has.dot"), ("zz-synth", "has space"), ("zz-synth", "t" * 70),
                       ("a" * 24, "t" * 34), ("zz-synth", "ok\n")):
        assert mc.ext_name(slug, tool) is None, (slug, tool)


async def test_too_many_tools_refused():
    async with Client(FastMCPTransport(srv.build("many"))) as c:
        with pytest.raises(mc.TooManyTools):
            await mc.list_server_tools(c)


async def noop(**kw):
    return "ok"


async def test_adapter_keeps_nested_schema_and_caps_description():
    nested = by_name(await listed())["nested"]
    tool = mc.make_tool("ext__zz-synth__nested", nested.description, nested.inputSchema, noop)
    params = tool.metadata.get_parameters_dict()
    blob = repr(params)
    assert "enum" in blob and "'inner'" in blob and "'n'" in blob and params["required"] == ["filters"]
    bare = mc.make_tool("ext__zz-synth__bare", "x", {"type": "object"}, noop)
    assert bare.metadata.get_parameters_dict()["properties"] == {}
    long = mc.make_tool("ext__zz-synth__bare", "a\x00b" * 1500, {"type": "object"}, noop)
    assert len(long.metadata.description) == mc.DESC_CHARS and "\x00" not in long.metadata.description
    assert tool.metadata.to_openai_tool() and long.metadata.to_openai_tool()


async def test_validate_args_reports_schema_errors():
    schema = by_name(await listed())["nested"].inputSchema
    bad = mc.validate_args(schema, {"filters": {"color": "red", "inner": "abc"}})
    assert 1 <= len(bad) <= 2
    assert mc.validate_args(schema, {"filters": {"color": "red", "inner": {"n": 1}}}) == []
    assert mc.validate_args({"type": "object", "properties": {"a": {"$ref": "https://example.com/s.json"}}},
                            {"a": 1}) == []
    assert mc.validate_args({"type": "nonsense"}, {"a": 1}) == []


# ── result wrapper ──────────────────────────────────────────────────────────

class Block:
    def __init__(self, type, text=""):
        self.type, self.text = type, text


class Result:
    def __init__(self, *content):
        self.content = list(content)


def test_wrap_result_shape_and_containment():
    out = mc.wrap_result("zz-synth", "lookup", Result(Block("text", srv.HOSTILE)), "confirmed")
    assert set(out) == {"tool", "source", "external", "label", "receipt", "result"}
    assert out["tool"] == "ext__zz-synth__lookup" and out["source"] == "external:zz-synth"
    assert out["external"] is True and out["label"] == "external, unverified"
    head, rest = out["result"].split("\n", 1)
    nonce = head.split('id="')[1].rstrip('">')
    assert head == f'<untrusted_external server="zz-synth" id="{nonce}">'
    assert rest.endswith(f'\n</untrusted_external id="{nonce}">')
    body = rest[: -len(f'\n</untrusted_external id="{nonce}">')]
    assert "</untrusted_external>" not in body and "\u202e" not in body
    assert "Rate is 4.25 percent." in body
    # a second wrap draws a fresh nonce
    assert mc.wrap_result("zz-synth", "lookup", Result(Block("text", "x")), "confirmed")["result"] != out["result"]


def test_wrap_result_truncates_and_counts_non_text():
    out = mc.wrap_result("zz-synth", "lookup", Result(Block("text", "a" * 20000)), "confirmed")
    body = out["result"].split("\n", 1)[1].rsplit("\n", 1)[0]
    assert len(body) == mc.EXT_RESULT_CHARS and out["truncated"] is True and out["note"]
    img = mc.wrap_result("zz-synth", "lookup", Result(Block("text", "hi"), Block("image")), "pending")
    assert "[1 non-text content block(s) omitted]" in img["result"]
    assert "proposal_id" not in img and "proposal_token" not in img and "truncated" not in img


def test_result_digest():
    import hashlib
    sha, n = mc.result_digest(Result(Block("text", "ab"), Block("text", "cd")))
    assert (sha, n) == (hashlib.sha256(b"ab\ncd").hexdigest(), 5)


def test_clean_doc_default_and_word():
    from backend.chat_tools import _clean_doc
    assert _clean_doc("a UNTRUSTED_document b") == "a untrusted-document b"
    assert _clean_doc("a untrusted_external b") == "a untrusted_external b"
    assert _clean_doc("x Untrusted_External y\u202e", word="untrusted_external") == "x untrusted-external y"


# ── reopen ──────────────────────────────────────────────────────────────────

async def test_reopen_checks_the_approved_hash(monkeypatch):
    echo = by_name(await listed())["echo"]
    conn = mc.ServerConn(spec=spec(), slug="zz-synth", server_id=None, destination="d",
                         leaves_machine=False, policies={}, client=None,
                         approved={"echo": {"description": echo.description, "inputSchema": echo.inputSchema,
                                            "sha256": mc.tool_sha(echo)}})
    monkeypatch.setattr(mc, "build_transport", lambda s: FastMCPTransport(srv.build()))
    conn.client = await mc.open_client(conn.spec)
    await mc.close_client(conn.client)  # the session went away while parked
    assert await mc.reopen(conn, "echo") is True
    assert (await conn.client.call_tool("echo", {"text": "ZZhi"})).data == "ZZhi"
    monkeypatch.setattr(mc, "build_transport", lambda s: FastMCPTransport(srv.build("changed")))
    assert await mc.reopen(conn, "echo") is False
    await mc.close_client(conn.client)
