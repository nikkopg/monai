"""
Parameterized SQL tools — correct by construction.

The AI layer never writes raw SQL for money questions. Instead it picks one of
these tools and fills typed parameters; the SQL here is hand-written and tested.
Relative dates ("this year", "last month") are resolved in Python via named
periods, so the model can never get the year/boundaries wrong.

Sign convention (from the data):
  - expense = amount < 0   ("spending", "spent", "cost")
  - income  = amount > 0   ("earned", "received")
All aggregates exclude transfers (is_transfer = false) unless stated otherwise.
"""

import datetime

from sqlalchemy import text

from backend.db import engine

# Named periods the router can choose from. Resolved to [start, end) date bounds.
PERIODS = (
    "this_month", "last_month", "this_year", "last_year",
    "last_30_days", "last_90_days", "all_time", "custom",
)


def _first_of_next_month(d: datetime.date) -> datetime.date:
    return datetime.date(d.year + 1, 1, 1) if d.month == 12 else datetime.date(d.year, d.month + 1, 1)


def resolve_period(
    period: str = "all_time",
    start_date: str | None = None,
    end_date: str | None = None,
) -> tuple[datetime.date | None, datetime.date | None]:
    """Return [start_inclusive, end_exclusive). None means unbounded."""
    today = datetime.date.today()
    period = (period or "all_time").lower()

    if period == "all_time":
        return None, None
    if period == "custom":
        s = datetime.date.fromisoformat(start_date) if start_date else None
        e = datetime.date.fromisoformat(end_date) if end_date else None
        # end_date is inclusive from a user's POV → make exclusive
        if e is not None:
            e = e + datetime.timedelta(days=1)
        return s, e
    if period == "this_month":
        s = today.replace(day=1)
        return s, _first_of_next_month(s)
    if period == "last_month":
        this_start = today.replace(day=1)
        last_start = datetime.date(this_start.year - 1, 12, 1) if this_start.month == 1 \
            else datetime.date(this_start.year, this_start.month - 1, 1)
        return last_start, this_start
    if period == "this_year":
        return datetime.date(today.year, 1, 1), datetime.date(today.year + 1, 1, 1)
    if period == "last_year":
        return datetime.date(today.year - 1, 1, 1), datetime.date(today.year, 1, 1)
    if period == "last_30_days":
        return today - datetime.timedelta(days=30), today + datetime.timedelta(days=1)
    if period == "last_90_days":
        return today - datetime.timedelta(days=90), today + datetime.timedelta(days=1)

    raise ValueError(f"Unknown period {period!r}. Valid: {PERIODS}")


def _date_clause(start, end, params: dict) -> str:
    parts = []
    if start is not None:
        parts.append("date >= :start")
        params["start"] = start.isoformat()
    if end is not None:
        parts.append("date < :end")
        params["end"] = end.isoformat()
    return (" AND " + " AND ".join(parts)) if parts else ""


def _currency() -> str:
    with engine.connect() as c:
        row = c.execute(text("SELECT currency FROM transactions LIMIT 1")).fetchone()
    return row[0] if row else ""


def _period_label(period, start, end) -> str:
    if period == "all_time":
        return "all time"
    if start and end:
        return f"{start.isoformat()} to {(end - datetime.timedelta(days=1)).isoformat()}"
    return period


# --------------------------------------------------------------------------
# Tools — each returns a structured dict. Formatting happens in format_answer.
# --------------------------------------------------------------------------

def spending_total(period="all_time", start_date=None, end_date=None) -> dict:
    """Total money spent (expenses only, transfers excluded) in a period."""
    s, e = resolve_period(period, start_date, end_date)
    p: dict = {}
    sql = (
        "SELECT COALESCE(SUM(-amount), 0) FROM transactions "
        "WHERE amount < 0 AND is_transfer = false" + _date_clause(s, e, p)
    )
    with engine.connect() as c:
        total = float(c.execute(text(sql), p).scalar() or 0)
    return {"tool": "spending_total", "total": total, "period": _period_label(period, s, e)}


def income_total(period="all_time", start_date=None, end_date=None) -> dict:
    """Total money received (income only, transfers excluded) in a period."""
    s, e = resolve_period(period, start_date, end_date)
    p: dict = {}
    sql = (
        "SELECT COALESCE(SUM(amount), 0) FROM transactions "
        "WHERE amount > 0 AND is_transfer = false" + _date_clause(s, e, p)
    )
    with engine.connect() as c:
        total = float(c.execute(text(sql), p).scalar() or 0)
    return {"tool": "income_total", "total": total, "period": _period_label(period, s, e)}


def net_total(period="all_time", start_date=None, end_date=None) -> dict:
    """Net cash flow (income minus expenses, transfers excluded)."""
    s, e = resolve_period(period, start_date, end_date)
    p: dict = {}
    sql = (
        "SELECT COALESCE(SUM(amount), 0) FROM transactions "
        "WHERE is_transfer = false" + _date_clause(s, e, p)
    )
    with engine.connect() as c:
        total = float(c.execute(text(sql), p).scalar() or 0)
    return {"tool": "net_total", "net": total, "period": _period_label(period, s, e)}


def spending_by_category(period="all_time", start_date=None, end_date=None, limit=5) -> dict:
    """Top spending categories (expenses only) in a period."""
    s, e = resolve_period(period, start_date, end_date)
    p: dict = {"lim": max(1, min(int(limit), 50))}
    sql = (
        "SELECT category, SUM(-amount) AS total FROM transactions "
        "WHERE amount < 0 AND is_transfer = false" + _date_clause(s, e, p) +
        " GROUP BY category ORDER BY total DESC LIMIT :lim"
    )
    with engine.connect() as c:
        rows = [(r[0], float(r[1])) for r in c.execute(text(sql), p).fetchall()]
    return {"tool": "spending_by_category", "rows": rows, "period": _period_label(period, s, e)}


def spending_in_category(category: str, period="all_time", start_date=None, end_date=None) -> dict:
    """Total spent in a specific category (substring match on category/raw_category)."""
    s, e = resolve_period(period, start_date, end_date)
    p: dict = {"cat": f"%{category}%"}
    sql = (
        "SELECT COALESCE(SUM(-amount), 0) FROM transactions "
        "WHERE amount < 0 AND is_transfer = false "
        "AND (category ILIKE :cat OR raw_category ILIKE :cat)" + _date_clause(s, e, p)
    )
    with engine.connect() as c:
        total = float(c.execute(text(sql), p).scalar() or 0)
    return {"tool": "spending_in_category", "category": category, "total": total,
            "period": _period_label(period, s, e)}


def transaction_count(period="all_time", start_date=None, end_date=None, kind="all") -> dict:
    """Count transactions in a period. kind: all | expense | income."""
    s, e = resolve_period(period, start_date, end_date)
    p: dict = {}
    sign = {"expense": " AND amount < 0", "income": " AND amount > 0", "all": ""}.get(kind, "")
    sql = (
        "SELECT COUNT(*) FROM transactions WHERE is_transfer = false"
        + sign + _date_clause(s, e, p)
    )
    with engine.connect() as c:
        n = int(c.execute(text(sql), p).scalar() or 0)
    return {"tool": "transaction_count", "count": n, "kind": kind,
            "period": _period_label(period, s, e)}


def largest_transactions(period="all_time", start_date=None, end_date=None, limit=5, kind="expense") -> dict:
    """Largest individual transactions by magnitude. kind: expense | income."""
    s, e = resolve_period(period, start_date, end_date)
    p: dict = {"lim": max(1, min(int(limit), 50))}
    sign = "amount < 0" if kind == "expense" else "amount > 0"
    order = "amount ASC" if kind == "expense" else "amount DESC"
    sql = (
        "SELECT date, ABS(amount) AS mag, category, merchant FROM transactions "
        f"WHERE {sign} AND is_transfer = false" + _date_clause(s, e, p) +
        f" ORDER BY {order} LIMIT :lim"
    )
    with engine.connect() as c:
        rows = [
            {"date": r[0].date().isoformat(), "amount": float(r[1]),
             "category": r[2], "merchant": r[3]}
            for r in c.execute(text(sql), p).fetchall()
        ]
    return {"tool": "largest_transactions", "rows": rows, "kind": kind,
            "period": _period_label(period, s, e)}


def average_daily_spending(period="this_month", start_date=None, end_date=None) -> dict:
    """Average spending per day over the period."""
    s, e = resolve_period(period, start_date, end_date)
    p: dict = {}
    total_sql = (
        "SELECT COALESCE(SUM(-amount), 0) FROM transactions "
        "WHERE amount < 0 AND is_transfer = false" + _date_clause(s, e, p)
    )
    with engine.connect() as c:
        total = float(c.execute(text(total_sql), p).scalar() or 0)
        if s is not None and e is not None:
            days = (e - s).days
        else:
            row = c.execute(text("SELECT MIN(date), MAX(date) FROM transactions")).fetchone()
            days = ((row[1].date() - row[0].date()).days + 1) if row and row[0] else 1
    days = max(days, 1)
    return {"tool": "average_daily_spending", "average": total / days, "days": days,
            "total": total, "period": _period_label(period, s, e)}


def list_categories() -> dict:
    """List distinct expense categories with their total spend (helps map vague terms)."""
    sql = (
        "SELECT category, SUM(-amount) AS total FROM transactions "
        "WHERE amount < 0 AND is_transfer = false "
        "GROUP BY category ORDER BY total DESC LIMIT 40"
    )
    with engine.connect() as c:
        rows = [(r[0], float(r[1])) for r in c.execute(text(sql)).fetchall()]
    return {"tool": "list_categories", "rows": rows}


# Registry: name -> callable
TOOLS = {
    "spending_total": spending_total,
    "income_total": income_total,
    "net_total": net_total,
    "spending_by_category": spending_by_category,
    "spending_in_category": spending_in_category,
    "transaction_count": transaction_count,
    "largest_transactions": largest_transactions,
    "average_daily_spending": average_daily_spending,
    "list_categories": list_categories,
}


def _fmt(amount: float, currency: str) -> str:
    return f"{currency} {amount:,.2f}"


def format_answer(result: dict, currency: str | None = None) -> str:
    """Render a tool result dict as a natural-language answer with correct currency."""
    cur = currency or _currency()
    tool = result.get("tool")
    period = result.get("period", "")
    suffix = f" ({period})" if period and period != "all time" else (" (all time)" if period == "all time" else "")

    if tool == "spending_total":
        return f"You spent {_fmt(result['total'], cur)}{suffix}."
    if tool == "income_total":
        return f"Your income was {_fmt(result['total'], cur)}{suffix}."
    if tool == "net_total":
        net = result["net"]
        word = "positive" if net >= 0 else "negative"
        return f"Your net cash flow was {_fmt(net, cur)} ({word}){suffix}."
    if tool == "spending_by_category":
        if not result["rows"]:
            return f"No spending found{suffix}."
        lines = [f"{i+1}. {c}: {_fmt(t, cur)}" for i, (c, t) in enumerate(result["rows"])]
        return f"Top spending categories{suffix}:\n" + "\n".join(lines)
    if tool == "spending_in_category":
        return f"You spent {_fmt(result['total'], cur)} on \"{result['category']}\"{suffix}."
    if tool == "transaction_count":
        k = result["kind"]
        kind_word = {"all": "transactions", "expense": "expenses", "income": "income entries"}.get(k, "transactions")
        return f"You made {result['count']} {kind_word}{suffix}."
    if tool == "largest_transactions":
        if not result["rows"]:
            return f"No transactions found{suffix}."
        lines = [
            f"{i+1}. {r['date']} — {_fmt(r['amount'], cur)} — {r['category']}"
            + (f" ({r['merchant']})" if r['merchant'] else "")
            for i, r in enumerate(result["rows"])
        ]
        return f"Largest {result['kind']}s{suffix}:\n" + "\n".join(lines)
    if tool == "average_daily_spending":
        return (f"You spent an average of {_fmt(result['average'], cur)} per day "
                f"over {result['days']} days{suffix} (total {_fmt(result['total'], cur)}).")
    if tool == "list_categories":
        lines = [f"- {c}: {_fmt(t, cur)}" for c, t in result["rows"][:20]]
        return "Your expense categories by total spend:\n" + "\n".join(lines)

    return str(result)
