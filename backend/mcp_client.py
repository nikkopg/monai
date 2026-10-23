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
import hashlib
import ipaddress
import json
import os
import re
import secrets
import shutil
import urllib.parse
from dataclasses import dataclass

import anyio
from fastmcp import Client
from fastmcp.client.transports import SSETransport, StdioTransport, StreamableHttpTransport
from jsonschema import Draft202012Validator
from jsonschema.exceptions import relevance
from llama_index.core.tools import FunctionTool, ToolMetadata
from pydantic import BaseModel

from backend import config
from backend.chat_tools import _clean_doc

EXT_TOOL_CAP = 16  # tools offered to the model per turn
EXT_RESULT_CHARS = 6000
MAX_TOOLS = 200
MAX_LIST_PAGES = 5
DESC_CHARS = 1000  # providers reject descriptions over 1024 characters
NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

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


# ── hashing, naming, adapter ────────────────────────────────────────────────

def _field(t, key):
    return t.get(key) if isinstance(t, dict) else getattr(t, key, None)


def tool_sha(t) -> str:
    """Hash of what the owner approved: name, description, inputSchema (D-10).
    Annotations, title and outputSchema are left out; they do not steer the model."""
    canon = {"name": _field(t, "name"), "description": _field(t, "description") or "",
             "inputSchema": _field(t, "inputSchema")}
    return hashlib.sha256(
        json.dumps(canon, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def tools_hash(tools) -> str:
    """Order-independent hash of a whole tool list (what Test returns and Enable echoes)."""
    pairs = sorted((_field(t, "name"), tool_sha(t)) for t in tools)
    return hashlib.sha256(json.dumps(pairs, separators=(",", ":")).encode()).hexdigest()


def ext_name(slug: str, tool: str) -> str | None:
    """ext__<slug>__<tool> if it fits the provider name rule; never a renamed tool (D-12)."""
    name = f"ext__{slug}__{tool}"
    return name if NAME_RE.fullmatch(name) else None


def normalize_schema(s) -> dict:
    """A bare {"type": "object"} has no properties, which some providers reject."""
    out = dict(s) if isinstance(s, dict) else {}
    out["type"] = "object"
    if not isinstance(out.get("properties"), dict):
        out["properties"] = {}
    return out


def make_tool(name: str, description: str, schema, async_fn) -> FunctionTool:
    """A LlamaIndex tool for an external tool. The schema is the server's own JSON
    schema, passed through a model class that returns it as is; tool_metadata means
    nothing is introspected from the function, so no `db` parameter can leak."""
    norm = normalize_schema(schema)

    class _Raw(BaseModel):
        @classmethod
        def model_json_schema(cls, *a, **k):
            return norm

    desc = _clean_doc(description or "", word="untrusted_external")[:DESC_CHARS]
    return FunctionTool.from_defaults(
        async_fn=async_fn,
        tool_metadata=ToolMetadata(name=name, description=desc, fn_schema=_Raw),
    )


def validate_args(schema, args) -> list[str]:
    """First schema errors for the model's args, so a bad call is retried instead of
    asking the owner (A-06). An unusable schema or ref gives [] and the call still asks."""
    try:
        Draft202012Validator.check_schema(schema)
        errors = sorted(Draft202012Validator(schema).iter_errors(args), key=relevance, reverse=True)
        return [
            (".".join(map(str, e.absolute_path)) + ": " if e.absolute_path else "") + e.message[:200]
            for e in errors[:2]
        ]
    except Exception:  # SchemaError, unresolvable $ref (never fetched), anything odd
        return []


# ── results ─────────────────────────────────────────────────────────────────

def _texts(call_result) -> tuple[list[str], int]:
    blocks = call_result.content
    texts = [c.text for c in blocks if getattr(c, "type", "") == "text"]
    return texts, len(blocks) - len(texts)


def result_digest(call_result) -> tuple[str, int]:
    """sha256 and byte length of the result text, for the receipt row (D-21)."""
    raw = "\n".join(_texts(call_result)[0]).encode()
    return hashlib.sha256(raw).hexdigest(), len(raw)


def wrap_result(slug: str, tool: str, call_result, receipt: str) -> dict:
    """The only shape an external result reaches the model in: labelled, bounded,
    cleaned, inside a block the text cannot close (D-23, A-05)."""
    texts, other = _texts(call_result)
    body = _clean_doc("\n".join(texts), word="untrusted_external")
    cut = len(body) > EXT_RESULT_CHARS
    body = body[:EXT_RESULT_CHARS]
    if other:
        body += f"\n[{other} non-text content block(s) omitted]"
    nonce = secrets.token_hex(4)
    out = {
        "tool": f"ext__{slug}__{tool}", "source": f"external:{slug}", "external": True,
        "label": "external, unverified", "receipt": receipt,
        "result": (f'<untrusted_external server="{slug}" id="{nonce}">\n{body}\n'
                   f'</untrusted_external id="{nonce}">'),
    }
    if cut:
        out |= {"truncated": True, "note": f"result cut at {EXT_RESULT_CHARS} characters"}
    return out


# ── a held connection ───────────────────────────────────────────────────────

@dataclass
class ServerConn:
    spec: ServerSpec
    slug: str
    server_id: object
    destination: str
    leaves_machine: bool
    policies: dict
    approved: dict  # tool name -> {description, inputSchema, sha256}
    client: object = None


async def reopen(conn: ServerConn, tool: str) -> bool:
    """A parked turn may find its session gone: reconnect and confirm the tool is
    still exactly what was approved. Never sends anything (A-09)."""
    await close_client(conn.client)
    conn.client = await open_client(conn.spec)
    return any(
        _field(t, "name") == tool and tool_sha(t) == conn.approved[tool]["sha256"]
        for t in await list_server_tools(conn.client)
    )
