"""Router JSON extraction — pure, no LLM or DB needed."""

import pytest

from backend.query import _extract_json


def test_plain_json():
    assert _extract_json('{"tool": "spending_total", "args": {"period": "this_year"}}') == {
        "tool": "spending_total",
        "args": {"period": "this_year"},
    }


def test_json_with_prose_around():
    raw = 'Sure! Here is the routing:\n{"tool": "income_total", "args": {}}\nHope that helps.'
    assert _extract_json(raw) == {"tool": "income_total", "args": {}}


def test_markdown_fenced_json():
    raw = '```json\n{"tool": "net_total", "args": {"period": "last_month"}}\n```'
    assert _extract_json(raw) == {"tool": "net_total", "args": {"period": "last_month"}}


def test_nested_braces():
    raw = '{"tool": "spending_in_category", "args": {"category": "food", "period": "custom"}}'
    out = _extract_json(raw)
    assert out["tool"] == "spending_in_category"
    assert out["args"]["category"] == "food"


def test_null_tool():
    assert _extract_json('{"tool": null, "reason": "unsupported"}')["tool"] is None


def test_no_json_raises():
    with pytest.raises(ValueError):
        _extract_json("I have no idea how to answer that.")
