"""
Phase 37 (STRM-04, D-12/D-12a/D-12b/D-13/D-15a) — the pure tool-to-chip mapper.

`sources.source_for(tool, args, result)` turns one executed read-tool call
into 0..2 source chips with ABSOLUTE ISO dates (resolved through
`tools.resolve_period` or read from the tool result), never raises, and never
carries an `account_id`. The expectations table below has exactly one row per
`tools.READ_TOOL_NAMES` entry, so adding a read tool without deciding its chip
fails here. No database: the category lookup is monkeypatched. All values are
synthetic (year 2001).
"""

import datetime
import json

import pytest

from backend import sources, tools

# kind: linked | plain | none ; n: number of chips for a representative call.
EXPECTED = {
    "spending_total": ("linked", 1),
    "income_total": ("linked", 1),
    "net_total": ("linked", 1),
    "spending_by_category": ("linked", 1),
    "spending_in_category": ("linked", 1),
    "spending_before_after_purchase": ("linked", 2),
    "transaction_count": ("linked", 1),
    "largest_transactions": ("linked", 1),
    "average_daily_spending": ("linked", 1),
    "monthly_trend": ("linked", 1),
    "compare_periods": ("linked", 2),
    "recurring_charges": ("plain", 1),
    "account_balances": ("plain", 1),
    "net_worth": ("plain", 1),
    "list_categories": ("none", 0),
    "find_transactions": ("none", 0),
    "find_platforms": ("none", 0),
    "find_accounts": ("none", 0),
}

MARCH = {"period": "custom", "start_date": "2001-03-01", "end_date": "2001-03-31"}

# Representative (args, result) per read tool.
CASES = {
    "spending_total": (MARCH, {"tool": "spending_total", "total": 1}),
    "income_total": (MARCH, {"tool": "income_total", "total": 1}),
    "net_total": (MARCH, {"tool": "net_total", "net": 1}),
    "spending_by_category": (MARCH, {"tool": "spending_by_category", "rows": []}),
    "spending_in_category": ({**MARCH, "category": "food"}, {"tool": "spending_in_category", "total": 1}),
    "spending_before_after_purchase": (
        {"ticker": "ZZZ", "category": "food"},
        {"tool": "spending_before_after_purchase", "pivot_date": "2001-03-11", "window_days": 10},
    ),
    "transaction_count": (MARCH, {"tool": "transaction_count", "count": 1}),
    "largest_transactions": (MARCH, {"tool": "largest_transactions", "rows": []}),
    "average_daily_spending": (MARCH, {"tool": "average_daily_spending", "total": 1}),
    "monthly_trend": ({"months": 3}, {"tool": "monthly_trend", "rows": []}),
    "compare_periods": (
        {},
        {
            "tool": "compare_periods",
            "base": {"start": "2001-02-01", "end_inclusive": "2001-02-28"},
            "current": {"start": "2001-03-01", "end_inclusive": "2001-03-31"},
        },
    ),
    "recurring_charges": ({}, {"tool": "recurring_charges", "months": 12}),
    "account_balances": ({}, {"tool": "account_balances"}),
    "net_worth": ({}, {"tool": "net_worth"}),
    "list_categories": ({}, {"tool": "list_categories"}),
    "find_transactions": ({}, {"tool": "find_transactions"}),
    "find_platforms": ({}, {"tool": "find_platforms"}),
    "find_accounts": ({}, {"tool": "find_accounts"}),
}


@pytest.fixture(autouse=True)
def _fake_categories(monkeypatch):
    monkeypatch.setattr(
        tools, "_find_category_node",
        lambda name: {"name": "Food"} if (name or "").lower() == "food" else None,
    )


def test_expected_table_covers_every_read_tool():
    assert set(EXPECTED) == set(tools.READ_TOOL_NAMES)
    assert set(CASES) == set(tools.READ_TOOL_NAMES)


@pytest.mark.parametrize("tool", sorted(EXPECTED))
def test_chip_kind_and_count_per_read_tool(tool):
    kind, n = EXPECTED[tool]
    args, result = CASES[tool]
    chips = sources.source_for(tool, args, result)
    assert len(chips) == n
    for chip in chips:
        assert chip["tool"] == tool
        assert chip["linked"] is (kind == "linked")
        assert ("cashflow" in chip) is (kind == "linked")
        assert "account_id" not in chip
        json.dumps(chip)  # str / bool only, no default= needed


def test_spending_total_custom_month():
    (chip,) = sources.source_for("spending_total", MARCH, {"total": 1})
    assert chip == {
        "tool": "spending_total", "label": "Spending", "period_label": "Mar 2001",
        "date_from": "2001-03-01", "date_to": "2001-03-31",
        "type": "expense", "linked": True, "cashflow": True,
    }


def test_named_period_matches_resolve_period():
    s, e = tools.resolve_period("last_month")
    (chip,) = sources.source_for("spending_total", {"period": "last_month"}, {"total": 1})
    assert chip["date_from"] == s.isoformat()
    assert chip["date_to"] == (e - datetime.timedelta(days=1)).isoformat()


def test_all_time_has_no_dates_and_average_defaults_to_this_month():
    (chip,) = sources.source_for("spending_total", {}, {"total": 1})
    assert chip["period_label"] == "All time"
    assert "date_from" not in chip and "date_to" not in chip
    s, e = tools.resolve_period("this_month")
    (avg,) = sources.source_for("average_daily_spending", {}, {"total": 1})
    assert avg["date_from"] == s.isoformat()
    assert avg["date_to"] == (e - datetime.timedelta(days=1)).isoformat()


def test_category_resolution():
    (chip,) = sources.source_for("spending_in_category", {**MARCH, "category": "FOOD"}, {"total": 1})
    assert chip["category"] == "Food" and chip["type"] == "expense"
    assert sources.source_for("spending_in_category", {**MARCH, "category": "nope"}, {"total": 1}) == []


def test_kind_drives_type_and_label():
    for kind, typ in (("expense", "expense"), ("income", "income"), ("all", None)):
        (chip,) = sources.source_for("transaction_count", {**MARCH, "kind": kind}, {"count": 1})
        assert chip.get("type") == typ and chip["label"] == "Transactions"
    (inc,) = sources.source_for("largest_transactions", {**MARCH, "kind": "income"}, {"rows": []})
    assert inc["label"] == "Largest income" and inc["type"] == "income"
    (exp,) = sources.source_for("largest_transactions", MARCH, {"rows": []})
    assert exp["label"] == "Largest expenses" and exp["type"] == "expense"


def test_compare_periods_and_before_after_use_result_dates():
    base, cur = sources.source_for("compare_periods", {}, CASES["compare_periods"][1])
    assert (base["period_label"], cur["period_label"]) == ("Feb 2001", "Mar 2001")
    assert base["type"] == cur["type"] == "expense"
    before, after = sources.source_for(
        "spending_before_after_purchase", {"ticker": "ZZZ", "category": "food"},
        CASES["spending_before_after_purchase"][1],
    )
    assert (before["date_from"], before["date_to"]) == ("2001-03-01", "2001-03-10")
    assert (after["date_from"], after["date_to"]) == ("2001-03-11", "2001-03-21")
    assert before["category"] == after["category"] == "Food"


def test_monthly_trend_clamps_to_six_months_open_ended():
    today = datetime.date.today()
    y, m = divmod(today.year * 12 + today.month - 1 - 6, 12)
    first = datetime.date(y, m + 1, 1)
    (chip,) = sources.source_for("monthly_trend", {"months": 3}, {"rows": []})
    assert chip["date_from"] == first.isoformat() and "date_to" not in chip
    assert chip["period_label"] == f"since {first.strftime('%b %Y')}"


def test_plain_chips():
    (rec,) = sources.source_for("recurring_charges", {}, {"months": 12})
    assert rec["period_label"] == "last 12 months" and rec["linked"] is False
    assert rec["date_to"] == datetime.date.today().isoformat()
    (nw,) = sources.source_for("net_worth", {}, {"tool": "net_worth"})
    assert nw["label"] == "Net worth" and nw["period_label"].startswith("as of ")
    assert "date_from" not in nw


@pytest.mark.parametrize(
    "start,end,label",
    [
        ("2001-03-01", "2001-03-31", "Mar 2001"),
        ("2001-01-01", "2001-12-31", "2001"),
        ("2001-03-14", "2001-03-14", "14 Mar 2001"),
        ("2001-03-01", "2001-03-15", "1 Mar – 15 Mar 2001"),
        ("2000-12-15", "2001-01-14", "15 Dec 2000 – 14 Jan 2001"),
    ],
)
def test_period_label_shapes(start, end, label):
    (chip,) = sources.source_for(
        "spending_total", {"period": "custom", "start_date": start, "end_date": end}, {"total": 1}
    )
    assert chip["period_label"] == label


def test_open_ended_labels():
    (a,) = sources.source_for("spending_total", {"period": "custom", "start_date": "2001-03-01"}, {"total": 1})
    assert a["period_label"] == "since 1 Mar 2001" and "date_to" not in a
    (b,) = sources.source_for("spending_total", {"period": "custom", "end_date": "2001-03-31"}, {"total": 1})
    assert b["period_label"] == "until 31 Mar 2001" and "date_from" not in b


def test_garbage_yields_empty_and_never_raises():
    for name in tools.TOOLS:
        if name not in tools.READ_TOOL_NAMES:
            assert sources.source_for(name, {}, {"tool": name}) == []
    assert sources.source_for("nope", {}, {"total": 1}) == []
    assert sources.source_for("spending_total", MARCH, {"error": "x"}) == []
    assert sources.source_for("spending_total", MARCH, "text") == []
    assert sources.source_for("spending_total", MARCH, None) == []
    assert sources.source_for("spending_total", {"period": "bogus"}, {"total": 1}) == []
    assert sources.source_for("spending_total", None, {"total": 1})[0]["period_label"] == "All time"


def test_identical_chips_are_deduped():
    same = {"base": {"start": "2001-03-01", "end_inclusive": "2001-03-31"},
            "current": {"start": "2001-03-01", "end_inclusive": "2001-03-31"}}
    assert len(sources.source_for("compare_periods", {}, same)) == 1
