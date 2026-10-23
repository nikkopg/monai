"""
Outbound MCP client (Phase 41): connect to servers the owner added.

External tools never enter tools.TOOLS, READ_TOOL_NAMES or monai's own MCP
surface. Only the base fastmcp transports are used, with keep_alive=False and
explicit timeouts (A-02): the helper npx/uvx transports copy the whole backend
environment, and the library has no default timeouts. A stdio child runs as
uid 10001 when the backend is root (A-01). Errors surfaced to callers are fixed
copy plus an exception class, never exception text, because httpx messages
carry URLs (Pitfall 8).
"""

import asyncio
import ipaddress
import os
import re
import shutil
import urllib.parse
from dataclasses import dataclass

import anyio
from fastmcp import Client
from fastmcp.client.transports import SSETransport, StdioTransport, StreamableHttpTransport

from backend import config

MAX_TOOLS = 200
MAX_LIST_PAGES = 5

ALLOWED_COMMANDS = ("npx", "uvx")
EXT_UID = 10001
# Names a server env must not set: they would move the child's home, caches or loader.
_ENV_DENY = frozenset(
    {"PATH", "HOME", "TMPDIR", "NODE_OPTIONS", "PYTHONPATH", "PYTHONSTARTUP",
     "npm_config_cache", "UV_CACHE_DIR", "XDG_CACHE_HOME"}
)
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_LOCAL_HOSTS = ("localhost",)


class ExtUnavailable(Exception):
    """The server could not be reached or used. Fixed copy only (Pitfall 8)."""

    def __init__(self, message: str, error_class: str = ""):
        super().__init__(message)
        self.error_class = error_class


class TooManyTools(ExtUnavailable):
    pass


@dataclass(frozen=True)
class ServerSpec:
    """A McpServer row copied to plain values, so no ORM object crosses an await."""

    id: object
    slug: str
    transport: str
    url: str | None
    headers: dict
    command: str | None
    args: tuple
    env: dict


def spec_from_row(row) -> ServerSpec:
    return ServerSpec(
        id=row.id, slug=row.slug, transport=row.transport, url=row.url,
        headers=dict(row.headers or {}), command=row.command,
        args=tuple(row.args or ()), env=dict(row.env or {}),
    )


def env_name_allowed(name: str) -> bool:
    return bool(_ENV_NAME_RE.match(name)) and name not in _ENV_DENY and not name.startswith("LD_")


def stdio_argv(command: str, args) -> tuple[str, list[str]]:
    """The command and argument list for a stdio server; never a shell line (D-05)."""
    if command not in ALLOWED_COMMANDS:
        raise ValueError("command must be npx or uvx")
    argv = [command, *(["-y"] if command == "npx" else []), *args]
    if os.geteuid() != 0:  # host dev: already unprivileged
        return argv[0], argv[1:]
    if shutil.which("setpriv") is None:
        raise ValueError("cannot isolate a local command here (setpriv missing)")
    # The backend is root in its container: drop the child to an unprivileged uid
    # so it cannot read the backend's /proc/<pid>/environ (A-01).
    return "setpriv", [
        f"--reuid={EXT_UID}", f"--regid={EXT_UID}", "--clear-groups", "--no-new-privs",
        "--inh-caps=-all", "--bounding-set=-all", "--", *argv,
    ]


def child_env(env: dict, base: str) -> dict:
    """The child's whole environment: the server's own env, then monai's keys on top.
    Built from this allowlist only, never from a copy of os.environ: the backend's
    environment holds the database password and both API keys (D-05, A-02)."""
    return {
        **env,
        "HOME": f"{base}/home", "TMPDIR": f"{base}/tmp", "npm_config_cache": f"{base}/npm",
        "UV_CACHE_DIR": f"{base}/uv", "XDG_CACHE_HOME": f"{base}/xdg",
    }


def work_dir(slug: str, base: str) -> str:
    """cwd for a stdio child, outside any project tree (Pitfall 12). Created here so a
    fresh volume works; chowned to the child's uid when the backend is root."""
    cwd = f"{base}/work/{slug}"
    dirs = [cwd, *(f"{base}/{d}" for d in ("home", "tmp", "npm", "uv", "xdg"))]
    for d in dirs:
        os.makedirs(d, exist_ok=True)
        if os.geteuid() == 0:
            os.chown(d, EXT_UID, EXT_UID)
    return cwd


def build_transport(spec: ServerSpec):
    # Looked up on the module by callers, so tests can replace it.
    if spec.transport == "http":
        return StreamableHttpTransport(spec.url, headers=dict(spec.headers))
    if spec.transport == "sse":
        return SSETransport(spec.url, headers=dict(spec.headers))
    base = config.MONAI_EXT_HOME
    command, args = stdio_argv(spec.command, spec.args)
    return StdioTransport(
        command=command, args=args, env=child_env(spec.env, base),
        cwd=work_dir(spec.slug, base), keep_alive=False,  # True leaves the process running
    )


def destination(spec: ServerSpec) -> str:
    """Where a call goes, for the approval card (D-26)."""
    if spec.transport in ("http", "sse"):
        return urllib.parse.urlsplit(spec.url).hostname or ""
    package = next((a for a in spec.args if not a.startswith("-")), "")
    return f"local command: {spec.command} {package}".rstrip()


def leaves_machine(spec: ServerSpec) -> bool:
    if spec.transport not in ("http", "sse"):
        return False
    host = urllib.parse.urlsplit(spec.url).hostname or ""
    if host in _LOCAL_HOSTS:
        return False
    try:
        return not ipaddress.ip_address(host).is_loopback
    except ValueError:
        return True


async def close_client(client) -> None:
    """Close without ever raising: close() re-raises a failed connect's error (s12)."""
    with anyio.CancelScope(shield=True):
        try:
            await client.close()
        except Exception:
            pass


async def open_client(spec: ServerSpec) -> Client:
    client = Client(
        build_transport(spec),
        timeout=config.EXT_CALL_TIMEOUT_SECONDS,
        init_timeout=config.EXT_CONNECT_TIMEOUT_SECONDS,
    )
    try:
        async with asyncio.timeout(config.EXT_CONNECT_TIMEOUT_SECONDS + 5):  # no library default
            await client.__aenter__()
    except BaseException as e:
        await close_client(client)
        if isinstance(e, Exception):
            raise ExtUnavailable("Couldn't connect", error_class=type(e).__name__) from None
        raise
    return client


async def list_server_tools(client) -> list:
    """Every tool the server lists, bounded against a hostile server (A-10)."""
    try:
        tools = await client.list_tools(max_pages=MAX_LIST_PAGES)
    except RuntimeError:  # fastmcp's page-limit error
        raise TooManyTools("Too many tools") from None
    if len(tools) > MAX_TOOLS:
        raise TooManyTools("Too many tools")
    return tools
