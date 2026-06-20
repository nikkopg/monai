"""
AI query layer — tool router (correct by construction).

The LLM does ONE job: read the question and emit JSON naming a tool + arguments.
It never writes SQL. The tool SQL is hand-written and tested in tools.py, and
relative dates are resolved in Python, so the model cannot get the year, the
expense/income sign, or column names wrong.

If the model can't map the question to a tool, we say so rather than fabricate
an answer — for a money app, refusing beats a confident wrong number.
"""

import datetime
import json
import re

from backend.config import configure_llm
from backend.tools import PERIODS, TOOLS, format_answer, _currency

_llm = None

_TOOL_SPEC = """\
Available tools (choose exactly one):

- spending_total(period, start_date?, end_date?)
    Total money SPENT (expenses). Use for "how much did I spend".
- income_total(period, start_date?, end_date?)
    Total money RECEIVED (income/salary). Use for "how much did I earn/receive".
- net_total(period, start_date?, end_date?)
    Net cash flow = income minus expenses.
- spending_by_category(period, limit?, start_date?, end_date?)
    Top spending categories ranked by amount. Use for "top categories", "where did my money go".
- spending_in_category(category, period, start_date?, end_date?)
    Spend in ONE named category. category is a search term like "food", "transport", "restaurant".
- transaction_count(period, kind?, start_date?, end_date?)
    Count of transactions. kind: all | expense | income.
- largest_transactions(period, limit?, kind?, start_date?, end_date?)
    Biggest individual transactions. kind: expense | income.
- average_daily_spending(period, start_date?, end_date?)
    Average spend per day.
- list_categories()
    List all expense categories. Use when the user asks what categories exist, or
    when you need to discover the right category name.

period MUST be one of: {periods}
Use "custom" with start_date and end_date (YYYY-MM-DD) only for specific date ranges.
"""

_PROMPT = """\
You route personal-finance questions to a tool. TODAY is {today}.

{tools}

Respond with ONLY a JSON object, no prose, no markdown fences:
{{"tool": "<tool_name>", "args": {{ ... }}}}

If the question cannot be answered by any tool, respond with:
{{"tool": null, "reason": "<short reason>"}}

Examples:
Q: How much did I spend last month?
{{"tool": "spending_total", "args": {{"period": "last_month"}}}}

Q: What were my top 3 spending categories this year?
{{"tool": "spending_by_category", "args": {{"period": "this_year", "limit": 3}}}}

Q: How much did I spend on food in 2024?
{{"tool": "spending_in_category", "args": {{"category": "food", "period": "custom", "start_date": "2024-01-01", "end_date": "2024-12-31"}}}}

Q: What's my total income this year?
{{"tool": "income_total", "args": {{"period": "this_year"}}}}

Q: My 5 biggest purchases ever?
{{"tool": "largest_transactions", "args": {{"period": "all_time", "limit": 5, "kind": "expense"}}}}

Question: {question}
JSON:"""


def _get_llm():
    global _llm
    if _llm is None:
        configure_llm()
        from llama_index.core import Settings
        _llm = Settings.llm
    return _llm


def _extract_json(textval: str) -> dict:
    """Pull the first {...} JSON object out of the model's reply."""
    textval = textval.strip()
    # strip markdown fences if present
    textval = re.sub(r"^```(?:json)?|```$", "", textval, flags=re.MULTILINE).strip()
    start = textval.find("{")
    if start == -1:
        raise ValueError("no JSON object in model output")
    depth = 0
    for i in range(start, len(textval)):
        if textval[i] == "{":
            depth += 1
        elif textval[i] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(textval[start:i + 1])
    raise ValueError("unbalanced JSON in model output")


def route(question: str) -> dict:
    """Ask the LLM to pick a tool. Returns the parsed routing dict."""
    llm = _get_llm()
    prompt = _PROMPT.format(
        today=datetime.date.today().isoformat(),
        tools=_TOOL_SPEC.format(periods=", ".join(PERIODS)),
        question=question,
    )
    raw = str(llm.complete(prompt))
    return _extract_json(raw)


def ask(question: str) -> str:
    """Route the question to a tool, execute it, and format the answer."""
    try:
        routing = route(question)
    except Exception as e:
        return f"I couldn't interpret that question reliably ({e}). Try rephrasing."

    tool_name = routing.get("tool")
    if not tool_name:
        reason = routing.get("reason", "no matching tool")
        return (
            f"I can't answer that one reliably yet ({reason}). "
            "I can total spending or income, break spending down by category, "
            "count transactions, find your largest transactions, or compute average "
            "daily spending — over any period."
        )

    fn = TOOLS.get(tool_name)
    if fn is None:
        return f"Unknown tool '{tool_name}'. Please rephrase."

    args = routing.get("args", {}) or {}
    try:
        result = fn(**args)
    except TypeError as e:
        return f"I picked the right tool ({tool_name}) but the parameters were off ({e}). Try rephrasing."
    except Exception as e:
        return f"Query failed running {tool_name}: {e}"

    return format_answer(result, _currency())


def reset_engine() -> None:
    """Kept for API compatibility; the router holds no per-import state."""
    global _llm
    _llm = None
