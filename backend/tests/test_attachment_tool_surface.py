"""Phase 39 (39-07): pins what the model sees of the chat-only tools (attachments, Phase 40 load_skill).

Regenerate deliberately, under Python 3.12 in its own commit (see 35-03):
    UPDATE_TOOL_SNAPSHOT=1 pytest backend/tests/test_attachment_tool_surface.py
"""
import json
import os
from pathlib import Path

import pytest

from backend import chat_tools, query
from backend.tests.test_mcp import _all_keys, _norm_description

SNAPSHOT = Path(__file__).parent / "attachment_tool_surface.json"


def _entries() -> list[dict]:
    tools = [query._llm_tool(n, fn) for n, fn in chat_tools.CHAT_ONLY_TOOLS.items()]
    return [
        {
            "name": t.metadata.name,
            "description": _norm_description(t.metadata.description),
            "fn_schema": t.metadata.fn_schema.model_json_schema(),
        }
        for t in tools
    ]


def test_attachment_tool_surface_snapshot():
    rendered = json.dumps(_entries(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if os.environ.get("UPDATE_TOOL_SNAPSHOT") == "1":
        SNAPSHOT.write_text(rendered, encoding="utf-8")
        return
    if not SNAPSHOT.exists():
        pytest.fail(f"{SNAPSHOT} is missing; regenerate deliberately with UPDATE_TOOL_SNAPSHOT=1 under Python 3.12.")
    assert rendered == SNAPSHOT.read_text(encoding="utf-8"), (
        "The attachment tool surface changed. If reviewed, regenerate with UPDATE_TOOL_SNAPSHOT=1 under Python 3.12."
    )


def test_attachment_tools_are_id_only():
    schemas = {e["name"]: e["fn_schema"] for e in _entries()}
    for schema in schemas.values():
        assert not {"db", "session", "token", "rows", "account"} & set(_all_keys(schema))
    assert schemas["read_attachment"]["required"] == ["attachment_id"]
    assert set(schemas["read_attachment"]["properties"]) == {"attachment_id", "page"}
    assert schemas["propose_statement_rows"]["required"] == ["attachment_id"]
    assert set(schemas["propose_statement_rows"]["properties"]) == {"attachment_id"}
    assert schemas["load_skill"]["required"] == ["name"]
    assert set(schemas["load_skill"]["properties"]) == {"name", "file"}
