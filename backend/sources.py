"""Source chips: which tool and which period stand behind an answer's numbers.

A chip is a small JSON-safe dict (Phase 37, STRM-04/STRM-05):

    {tool, label, period_label, date_from?, date_to?, category?, type?,
     linked, cashflow?}

`source_for(tool, args, result)` maps ONE executed read-tool call to 0..2
chips. Dates are absolute ISO strings (`date_to` inclusive) so a chip never
re-resolves a named period later. They come from `tools.resolve_period` (the
same function, with the same `date.today()`, the tool itself used) or, where
the tool result already carries its windows (`compare_periods`,
`spending_before_after_purchase`), from that result. A `linked` chip carries
`cashflow: True`: opening it on GET /transactions with `cashflow=true`
returns the rows the tool summed (proven in test_source_parity.py). A plain
chip (`linked: False`) only names the tool and period.

Pure apart from the category lookup. Never raises: any problem yields [] and
a warning that names only the exception class (no args, no values).
No read tool takes an account argument, so chips never name an account.
"""

import datetime
import inspect
import logging

from backend import tools

logger = logging.getLogger(__name__)

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_ONE_DAY = datetime.timedelta(days=1)


def _default(tool: str, param: str):
    p = inspect.signature(tools.TOOLS[tool]).parameters.get(param)
    return None if p is None or p.default is inspect.Parameter.empty else p.default


def _window(tool: str, args: dict):
    """(start_inclusive, end_inclusive), None where unbounded."""
    s, e = tools.resolve_period(
        args.get("period") or _default(tool, "period") or "all_time",
        args.get("start_date"), args.get("end_date"),
    )
    return s, (e - _ONE_DAY if e is not None else None)


def _dmy(d: datetime.date) -> str:
    return f"{d.day} {_MONTHS[d.month - 1]} {d.year}"


def _label(start, end) -> str:
    if start is None and end is None:
        return "All time"
    if end is None:
        return f"since {_dmy(start)}"
    if start is None:
        return f"until {_dmy(end)}"
    if start == end:
        return _dmy(start)
    if start.year == end.year and (start.month, start.day) == (1, 1) and (end.month, end.day) == (12, 31):
        return str(start.year)
    if (start.year, start.month, start.day) == (end.year, end.month, 1) and end + _ONE_DAY == _next_month(start):
        return f"{_MONTHS[start.month - 1]} {start.year}"
    if start.year == end.year:
        return f"{start.day} {_MONTHS[start.month - 1]} – {_dmy(end)}"
    return f"{_dmy(start)} – {_dmy(end)}"


def _next_month(d: datetime.date) -> datetime.date:
    return datetime.date(d.year + (d.month == 12), d.month % 12 + 1, 1)


def _chip(tool, label, start, end, *, category=None, type_=None, linked=True, period_label=None) -> dict:
    chip = {"tool": tool, "label": label, "period_label": period_label or _label(start, end)}
    if start is not None:
        chip["date_from"] = start.isoformat()
    if end is not None:
        chip["date_to"] = end.isoformat()
    if category is not None:
        chip["category"] = category
    if type_ is not None:
        chip["type"] = type_
    chip["linked"] = linked
    if linked:
        chip["cashflow"] = True
    return chip


def _category(args: dict, result: dict):
    node = tools._find_category_node(args.get("category") or result.get("category"))
    return node["name"] if node else None


def _build(tool: str, args: dict, result: dict) -> list[dict]:
    today = datetime.date.today()  # same clock resolve_period uses
    # ponytail: dates resolve microseconds after the tool ran, so a turn crossing
    # midnight can be one day off; upgrade path is passing the tool's own bounds
    # through its result.
    simple = {
        "spending_total": ("Spending", "expense"),
        "income_total": ("Income", "income"),
        "net_total": ("Net", None),
        "spending_by_category": ("Spending by category", "expense"),
        "average_daily_spending": ("Daily average", "expense"),
    }
    if tool in simple:
        label, typ = simple[tool]
        s, e = _window(tool, args)
        return [_chip(tool, label, s, e, type_=typ)]
    if tool == "spending_in_category":
        cat = _category(args, result)
        if cat is None:
            return []
        s, e = _window(tool, args)
        return [_chip(tool, "Spending", s, e, category=cat, type_="expense")]
    if tool == "spending_before_after_purchase":
        cat = _category(args, result)
        if cat is None:
            return []
        pivot = datetime.date.fromisoformat(result["pivot_date"])
        n = datetime.timedelta(days=int(result["window_days"]))
        return [
            _chip(tool, "Spending", pivot - n, pivot - _ONE_DAY, category=cat, type_="expense"),
            _chip(tool, "Spending", pivot, pivot + n, category=cat, type_="expense"),
        ]
    if tool == "transaction_count":
        s, e = _window(tool, args)
        kind = args.get("kind") or _default(tool, "kind")
        return [_chip(tool, "Transactions", s, e, type_=kind if kind in ("expense", "income") else None)]
    if tool == "largest_transactions":
        s, e = _window(tool, args)
        # tools.largest_transactions treats every kind but "expense" as income
        income = (args.get("kind") or _default(tool, "kind")) != "expense"
        return [_chip(tool, "Largest income" if income else "Largest expenses", s, e,
                      type_="income" if income else "expense")]
    if tool == "monthly_trend":
        m = max(int(args.get("months") or 6), 6)
        y, mo = divmod(today.year * 12 + today.month - 1 - m, 12)
        start = datetime.date(y, mo + 1, 1)
        return [_chip(tool, "Trend", start, None, period_label=f"since {_MONTHS[start.month - 1]} {start.year}")]
    if tool == "compare_periods":
        return [
            _chip(tool, "Spending", datetime.date.fromisoformat(side["start"]),
                  datetime.date.fromisoformat(side["end_inclusive"]), type_="expense")
            for side in (result["base"], result["current"])
        ]
    if tool == "recurring_charges":
        m = int(result.get("months") or max(3, min(int(args.get("months") or 24), 60)))
        return [_chip(tool, "Recurring", today - datetime.timedelta(days=int(m * 30.44)), today,
                      linked=False, period_label=f"last {m} months")]
    if tool in ("account_balances", "net_worth"):
        label = "Account balances" if tool == "account_balances" else "Net worth"
        return [_chip(tool, label, None, None, linked=False, period_label=f"as of {_dmy(today)}")]
    return []  # list_categories and the find_* lookups carry no figures (D-13)


def source_for(tool: str, args: dict | None, result) -> list[dict]:
    """Chips for one executed tool call; [] for writes, errors and garbage."""
    # A real read result carries its own {"tool": name}; a raised tool arrives as
    # {"raw": <exception text>} and must not earn a citation (Pitfall 21).
    if (tool not in tools.READ_TOOL_NAMES or not isinstance(result, dict)
            or result.get("tool") != tool or "error" in result):
        return []
    try:
        chips = _build(tool, args or {}, result)
    except Exception as exc:  # never break a turn over a citation
        logger.warning("source mapping failed for %s: %s", tool, type(exc).__name__)
        return []
    out: list[dict] = []
    for chip in chips:
        if chip not in out:
            out.append(chip)
    return out
