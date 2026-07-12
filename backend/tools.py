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

Write tools (propose_*) are proposal-producers: they create a Proposal row and
return {tool, proposal_id, proposal_token, summary, before, after}. They never
mutate target tables (transactions, accounts, holdings). The confirm endpoint in
main.py applies the write atomically when the user approves.
"""

import datetime
import secrets
from datetime import timezone, timedelta
from decimal import Decimal

from sqlalchemy import text

from backend.db import engine, get_session_sync

# Named periods the router can choose from. Resolved to [start, end) date bounds.
PERIODS = (
    "this_week", "last_week",
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
    if period == "this_week":
        # ISO week: Monday (weekday()==0) start, half-open through next Monday.
        monday = today - datetime.timedelta(days=today.weekday())
        return monday, monday + datetime.timedelta(days=7)
    if period == "last_week":
        # The full week before this_week: its end is exactly this_week's start,
        # mirroring how last_month's end is this_month's start.
        monday = today - datetime.timedelta(days=today.weekday())
        return monday - datetime.timedelta(days=7), monday
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
    """Total money spent (expenses only, transfers excluded) in a period.

    period: named (all_time/this_month/last_month/this_year/last_year/
      last_30_days/last_90_days) or "custom" with ISO start_date/end_date
      (end inclusive). Use custom for a specific month, year, or date range.
    """
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
    """Total money received (income only, transfers excluded) in a period.

    period: named or "custom" with ISO start_date/end_date (end inclusive).
    Use custom for a specific month, year, or date range.
    """
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
    """Net cash flow (income minus expenses, transfers excluded).

    period: named or "custom" with ISO start_date/end_date (end inclusive).
    Use custom for a specific month, year, or date range.
    """
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
    """Top spending categories (expenses only) in a period.

    period: one of all_time, this_month, last_month, this_year, last_year,
      last_30_days, last_90_days, or "custom". For a specific month/year/range
      pass period="custom" with ISO start_date/end_date (end_date inclusive).
    """
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
    """Total spent in a specific category (substring match on category/raw_category).

    period: one of all_time, this_month, last_month, this_year, last_year,
      last_30_days, last_90_days, or "custom". For a specific month/year/range
      (e.g. "food in June 2026") pass period="custom" with start_date and
      end_date as ISO YYYY-MM-DD; end_date is inclusive. Leaving period at the
      "all_time" default when the user asked about a specific month sums every
      year on record and returns a wrong, inflated total.
    """
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


def spending_before_after_purchase(ticker: str, category: str) -> dict:
    """CHAT-03: 'since I bought BBCA, how has my eating-out spending changed?'

    Pivot date = earliest 'buy' event for this ticker in portfolio_events
    (D-15). Compares category spending in the N days before vs N days after
    that date, where N = days elapsed since the purchase (equal-length
    windows, so the comparison isn't skewed by an arbitrarily longer "after"
    window as time passes).

    Reuses spending_in_category()'s period="custom" contract (end_date
    inclusive) — no new date-range SQL. When there is no buy event, or the
    purchase is dated today/future (no "after" window yet), returns a
    structured error dict instead of a fabricated number.
    """
    with engine.connect() as c:
        pivot = c.execute(
            text("SELECT MIN(date) FROM portfolio_events "
                 "WHERE ticker = :ticker AND event_type = 'buy'"),
            {"ticker": ticker},
        ).scalar()

    if pivot is None:
        return {"tool": "spending_before_after_purchase",
                "error": f"No buy event found for ticker '{ticker}' — nothing to compare against."}

    today = datetime.date.today()
    n_days = (today - pivot).days
    if n_days < 1:
        return {"tool": "spending_before_after_purchase",
                "error": f"Purchase of {ticker} was today or in the future — no 'after' window yet."}

    # Equal-length windows. end_date is inclusive per spending_in_category's
    # custom-period contract: before = [pivot-n_days, pivot-1], after = [pivot, today].
    before_start = pivot - datetime.timedelta(days=n_days)
    before = spending_in_category(category, period="custom",
                                  start_date=before_start.isoformat(),
                                  end_date=(pivot - datetime.timedelta(days=1)).isoformat())
    after = spending_in_category(category, period="custom",
                                 start_date=pivot.isoformat(),
                                 end_date=today.isoformat())

    delta = after["total"] - before["total"]
    return {
        "tool": "spending_before_after_purchase",
        "ticker": ticker,
        "category": category,
        "pivot_date": pivot.isoformat(),
        "window_days": n_days,
        "before_total": before["total"],
        "after_total": after["total"],
        "delta": delta,
        "delta_pct": (delta / before["total"] * 100) if before["total"] else None,
    }


def transaction_count(period="all_time", start_date=None, end_date=None, kind="all") -> dict:
    """Count transactions in a period. kind: all | expense | income.

    period: named or "custom" with ISO start_date/end_date (end inclusive).
    Use custom for a specific month, year, or date range.
    """
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
    """Largest individual transactions by magnitude. kind: expense | income.

    period: named or "custom" with ISO start_date/end_date (end inclusive).
    Use custom for a specific month, year, or date range.
    """
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
    """Average spending per day over the period.

    period: named or "custom" with ISO start_date/end_date (end inclusive).
    Use custom for a specific month, year, or date range.
    """
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


def monthly_trend(months: int = 6) -> dict:
    """Month-over-month income/expense/net for the last N months (CASH-02).

    months: clamped to a minimum of 6 (>=6-month rolling window, not a
      calendar-year bound — early-in-the-year calls still return a full
      trailing window). Transfers excluded.
    """
    months = max(months, 6)
    p: dict = {"months": months}
    sql = (
        "SELECT date_trunc('month', date) AS month, "
        "COALESCE(SUM(amount) FILTER (WHERE amount > 0), 0) AS income, "
        "COALESCE(SUM(-amount) FILTER (WHERE amount < 0), 0) AS expense "
        "FROM transactions "
        "WHERE is_transfer = false "
        "AND date >= date_trunc('month', CURRENT_DATE) - (:months || ' months')::interval "
        "GROUP BY 1 ORDER BY 1"
    )
    with engine.connect() as c:
        rows = [
            {
                "month": r[0].date().isoformat()[:7],
                "income": float(r[1]),
                "expense": float(r[2]),
                "net": float(r[1]) - float(r[2]),
            }
            for r in c.execute(text(sql), p).fetchall()
        ]
    return {"tool": "monthly_trend", "rows": rows}


def account_balances(period_start=None, period_end=None) -> dict:
    """Per-account current_balance (all-time) + period_net (scoped) — CASH-03/D-04.

    period_start/period_end: an already-resolved [start_inclusive, end_exclusive)
    tuple, e.g. from resolve_period() called once by the caller (Plan 03 endpoint).
    This function does NOT call resolve_period itself. current_balance sums ALL
    of an account's non-transfer transactions regardless of period; period_net
    sums only the in-period ones. Accounts with zero transactions appear with
    0/0 (LEFT JOIN). Transfers excluded from both sums.
    """
    p: dict = {}
    period_parts = []
    if period_start is not None:
        period_parts.append("t.date >= :period_start")
        p["period_start"] = period_start.isoformat()
    if period_end is not None:
        period_parts.append("t.date < :period_end")
        p["period_end"] = period_end.isoformat()
    period_predicate = (" AND " + " AND ".join(period_parts)) if period_parts else ""
    sql = (
        "SELECT a.id, a.name, "
        "COALESCE(SUM(t.amount), 0) AS current_balance, "
        f"COALESCE(SUM(t.amount) FILTER (WHERE true{period_predicate}), 0) AS period_net "
        "FROM accounts a "
        "LEFT JOIN transactions t ON t.account_id = a.id AND t.is_transfer = false "
        "GROUP BY a.id, a.name ORDER BY a.name"
    )
    with engine.connect() as c:
        rows = [
            {"id": r[0], "name": r[1], "current_balance": float(r[2]), "period_net": float(r[3])}
            for r in c.execute(text(sql), p).fetchall()
        ]
    return {"tool": "account_balances", "rows": rows}


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


def find_transactions(
    merchant: str | None = None,
    category: str | None = None,
    period="all_time",
    start_date=None,
    end_date=None,
    kind="all",
    limit=10,
) -> dict:
    """Search/filter individual transactions and return their ids, dates, amounts,
    categories, merchants, and account ids, so the agent can resolve a merchant or
    category (e.g. "my last Gojek transaction") to a concrete transaction id before
    calling propose_edit_transaction or propose_delete_transaction. amount is signed
    (negative=expense, positive=income); kind: all | expense | income. Transfers are
    always excluded (is_transfer = false), matching the other read tools. Rows are
    ordered most-recent-first, so rows[0] is "my last X".
    """
    s, e = resolve_period(period, start_date, end_date)
    p: dict = {"lim": max(1, min(int(limit), 50))}
    clauses = ["is_transfer = false"]
    if merchant is not None:
        clauses.append("merchant ILIKE :merchant")
        p["merchant"] = f"%{merchant}%"
    if category is not None:
        clauses.append("category = :category")
        p["category"] = category
    sign = {"expense": "amount < 0", "income": "amount > 0"}.get(kind)
    if sign:
        clauses.append(sign)
    sql = (
        "SELECT id, date, amount, category, merchant, account_id FROM transactions WHERE "
        + " AND ".join(clauses) + _date_clause(s, e, p) +
        " ORDER BY date DESC LIMIT :lim"
    )
    with engine.connect() as c:
        rows = [
            {"id": r[0], "date": r[1].date().isoformat(), "amount": float(r[2]),
             "category": r[3], "merchant": r[4], "account_id": r[5]}
            for r in c.execute(text(sql), p).fetchall()
        ]
    return {"tool": "find_transactions", "rows": rows, "kind": kind,
            "period": _period_label(period, s, e)}


def find_platforms(name: str | None = None, limit: int = 10) -> dict:
    """Search/filter investment platforms and return their ids, names, and kinds,
    so the agent can resolve a platform name (e.g. "bibit") to a concrete
    platform_id before calling propose_add_holding. Rows are ordered by name.
    """
    p: dict = {"lim": max(1, min(int(limit), 50))}
    clauses = []
    if name is not None:
        clauses.append("name ILIKE :name")
        p["name"] = f"%{name}%"
    sql = (
        "SELECT id, name, kind FROM platforms" +
        (" WHERE " + " AND ".join(clauses) if clauses else "") +
        " ORDER BY name LIMIT :lim"
    )
    with engine.connect() as c:
        rows = [_platform_to_dict(r) for r in c.execute(text(sql), p).fetchall()]
    return {"tool": "find_platforms", "rows": rows}


def find_accounts(name: str | None = None, limit: int = 10) -> dict:
    """Search/filter accounts and return their ids, names, types, and
    currencies, so the agent can resolve an account name (e.g. "BCA") to a
    concrete account_id before calling propose_edit_account/propose_delete_account.
    Rows are ordered by name.
    """
    from backend.models import Account

    p: dict = {"lim": max(1, min(int(limit), 50))}
    with get_session_sync() as db:
        q = db.query(Account)
        if name is not None:
            q = q.filter(Account.name.ilike(f"%{name}%"))
        rows = [_account_to_dict(a) for a in q.order_by(Account.name).limit(p["lim"]).all()]
    return {"tool": "find_accounts", "rows": rows}


# Registry: name -> callable (read tools)
TOOLS = {
    "spending_total": spending_total,
    "income_total": income_total,
    "net_total": net_total,
    "spending_by_category": spending_by_category,
    "spending_in_category": spending_in_category,
    "spending_before_after_purchase": spending_before_after_purchase,
    "transaction_count": transaction_count,
    "largest_transactions": largest_transactions,
    "average_daily_spending": average_daily_spending,
    "list_categories": list_categories,
    "find_transactions": find_transactions,
    "find_platforms": find_platforms,
    "find_accounts": find_accounts,
    "monthly_trend": monthly_trend,
    "account_balances": account_balances,
}


# ---------------------------------------------------------------------------
# Helpers for write tools
# ---------------------------------------------------------------------------

def _make_proposal(operation: str, payload: dict) -> tuple[str, str]:
    """Insert a Proposal row; return (proposal_id_str, token).

    proposal_token is returned to the caller so the SSE answer event can carry
    it to the originating session — it is NEVER stored in the trace or returned
    by GET /proposals (T-02-07).
    """
    from backend.models import Proposal

    token = secrets.token_urlsafe(32)
    expires_at = datetime.datetime.now(timezone.utc) + timedelta(minutes=15)
    with get_session_sync() as db:
        proposal = Proposal(
            token=token,
            operation=operation,
            payload=payload,
            status="pending",
            expires_at=expires_at,
        )
        db.add(proposal)
        db.commit()
        db.refresh(proposal)
        proposal_id = str(proposal.id)
    return proposal_id, token


def _tx_to_dict(tx) -> dict:
    """Serialize a Transaction ORM row to a JSON-safe dict."""
    return {
        "id": tx.id,
        "date": tx.date.isoformat() if tx.date else None,
        "amount": str(tx.amount),
        "currency": tx.currency,
        "category": tx.category,
        "merchant": tx.merchant,
        "notes": tx.notes,
        "account_id": tx.account_id,
        "is_transfer": tx.is_transfer,
    }


def _account_to_dict(acc) -> dict:
    return {"id": acc.id, "name": acc.name, "type": acc.type, "currency": acc.currency}


def _platform_to_dict(p) -> dict:
    return {"id": p[0], "name": p[1], "kind": p[2]}


def _holding_to_dict(h) -> dict:
    return {
        "id": h.id,
        "ticker": h.ticker,
        "quantity": str(h.quantity),
        "avg_cost": str(h.avg_cost),
        "purchase_date": h.purchase_date.isoformat() if h.purchase_date else None,
        "currency": h.currency,
        "asset_type": h.asset_type,
    }


def _diff_summary(before: dict, after: dict) -> str:
    changes = []
    for k in after:
        if k in before and str(before[k]) != str(after[k]):
            changes.append(f"{k}: {before[k]} → {after[k]}")
    return ", ".join(changes) if changes else "no changes"


# ---------------------------------------------------------------------------
# Write tools — proposal-producers (never mutate target tables directly)
# ---------------------------------------------------------------------------

def propose_add_transaction(
    date: str,
    amount: float,
    account: str,
    category: str | None = None,
    merchant: str | None = None,
    notes: str | None = None,
    currency: str = "IDR",
    is_transfer: bool = False,
) -> dict:
    """Propose adding a new transaction. Returns a proposal for user confirmation.
    Does NOT add any data — user must approve. amount is signed (negative=expense, positive=income).
    """
    after = {
        "date": date,
        "amount": str(Decimal(str(amount))),
        "account": account,
        "category": category,
        "merchant": merchant,
        "notes": notes,
        "currency": currency,
        "is_transfer": is_transfer,
    }
    payload = {"operation": "add_transaction", "rows": [{"before": None, "after": after}]}
    proposal_id, proposal_token = _make_proposal("add_transaction", payload)
    return {
        "tool": "propose_add_transaction",
        "proposal_id": proposal_id,
        "proposal_token": proposal_token,
        "summary": f"Add transaction: {amount} {currency} on {date}" + (f" at {merchant}" if merchant else ""),
        "before": None,
        "after": after,
    }


def propose_edit_transaction(
    transaction_id: int,
    category: str | None = None,
    merchant: str | None = None,
    amount: float | None = None,
    notes: str | None = None,
) -> dict:
    """Propose editing a transaction. Only provided fields will be changed.
    Returns a proposal for user confirmation. Does NOT change any data — user must approve.
    """
    from backend.models import Transaction

    with get_session_sync() as db:
        tx = db.get(Transaction, transaction_id)
        if tx is None:
            return {"tool": "propose_edit_transaction", "error": f"Transaction {transaction_id} not found"}
        before = _tx_to_dict(tx)

    after = {**before}
    if category is not None:
        after["category"] = category
    if merchant is not None:
        after["merchant"] = merchant
    if amount is not None:
        after["amount"] = str(Decimal(str(amount)))
    if notes is not None:
        after["notes"] = notes

    payload = {
        "operation": "edit_transaction",
        "rows": [{"id": transaction_id, "before": before, "after": after}],
    }
    proposal_id, proposal_token = _make_proposal("edit_transaction", payload)
    return {
        "tool": "propose_edit_transaction",
        "proposal_id": proposal_id,
        "proposal_token": proposal_token,
        "summary": f"Edit transaction #{transaction_id}: {_diff_summary(before, after)}",
        "before": before,
        "after": after,
    }


def propose_delete_transaction(transaction_id: int) -> dict:
    """Propose deleting a transaction. Returns a proposal for user confirmation.
    Does NOT delete any data — user must approve.
    """
    from backend.models import Transaction

    with get_session_sync() as db:
        tx = db.get(Transaction, transaction_id)
        if tx is None:
            return {"tool": "propose_delete_transaction", "error": f"Transaction {transaction_id} not found"}
        before = _tx_to_dict(tx)

    payload = {
        "operation": "delete_transaction",
        "rows": [{"id": transaction_id, "before": before, "after": None}],
    }
    proposal_id, proposal_token = _make_proposal("delete_transaction", payload)
    return {
        "tool": "propose_delete_transaction",
        "proposal_id": proposal_id,
        "proposal_token": proposal_token,
        "summary": f"Delete transaction #{transaction_id}" + (f" ({before.get('merchant', '')}, {before.get('amount')})" if before else ""),
        "before": before,
        "after": None,
    }


def propose_add_account(
    name: str,
    type: str | None = None,
    currency: str | None = None,
) -> dict:
    """Propose adding a new account. Returns a proposal for user confirmation.
    Does NOT add any data — user must approve.
    """
    after = {"name": name, "type": type, "currency": currency}
    payload = {"operation": "add_account", "rows": [{"before": None, "after": after}]}
    proposal_id, proposal_token = _make_proposal("add_account", payload)
    return {
        "tool": "propose_add_account",
        "proposal_id": proposal_id,
        "proposal_token": proposal_token,
        "summary": f"Add account: {name}",
        "before": None,
        "after": after,
    }


def propose_edit_account(
    account_id: int,
    name: str | None = None,
    type: str | None = None,
    currency: str | None = None,
) -> dict:
    """Propose editing an account. Only provided fields will be changed.
    Returns a proposal for user confirmation. Does NOT change any data — user must approve.
    """
    from backend.models import Account

    with get_session_sync() as db:
        acc = db.get(Account, account_id)
        if acc is None:
            return {"tool": "propose_edit_account", "error": f"Account {account_id} not found"}
        before = _account_to_dict(acc)

    after = {**before}
    if name is not None:
        after["name"] = name
    if type is not None:
        after["type"] = type
    if currency is not None:
        after["currency"] = currency

    payload = {
        "operation": "edit_account",
        "rows": [{"id": account_id, "before": before, "after": after}],
    }
    proposal_id, proposal_token = _make_proposal("edit_account", payload)
    return {
        "tool": "propose_edit_account",
        "proposal_id": proposal_id,
        "proposal_token": proposal_token,
        "summary": f"Edit account #{account_id}: {_diff_summary(before, after)}",
        "before": before,
        "after": after,
    }


def propose_delete_account(account_id: int) -> dict:
    """Propose deleting an account. Blocked if the account has any transactions — reassign them first.
    Returns a proposal for user confirmation if allowed. Does NOT delete any data — user must approve.
    """
    from backend.models import Account

    with get_session_sync() as db:
        acc = db.get(Account, account_id)
        if acc is None:
            return {"tool": "propose_delete_account", "error": f"Account {account_id} not found"}

        # D-06: block orphaning delete — count dependent transactions
        count_sql = "SELECT COUNT(*) FROM transactions WHERE account_id = :aid"
        with engine.connect() as c:
            tx_count = int(c.execute(text(count_sql), {"aid": account_id}).scalar() or 0)

        if tx_count > 0:
            return {
                "tool": "propose_delete_account",
                "error": (
                    f"Cannot delete account #{account_id}: it has {tx_count} transactions. "
                    "Reassign or remove those first."
                ),
            }

        before = _account_to_dict(acc)

    payload = {
        "operation": "delete_account",
        "rows": [{"id": account_id, "before": before, "after": None}],
    }
    proposal_id, proposal_token = _make_proposal("delete_account", payload)
    return {
        "tool": "propose_delete_account",
        "proposal_id": proposal_id,
        "proposal_token": proposal_token,
        "summary": f"Delete account #{account_id} ({before.get('name', '')})",
        "before": before,
        "after": None,
    }


def propose_rename_category(old_name: str, new_name: str) -> dict:
    """Propose renaming a category across all transactions. Non-orphaning — always allowed.
    Returns a proposal for user confirmation. Does NOT change any data — user must approve.
    """
    count_sql = "SELECT COUNT(*) FROM transactions WHERE category = :cat"
    with engine.connect() as c:
        affected_count = int(c.execute(text(count_sql), {"cat": old_name}).scalar() or 0)

    payload = {
        "operation": "rename_category",
        "rows": [{"old_name": old_name, "new_name": new_name, "affected_count": affected_count}],
    }
    proposal_id, proposal_token = _make_proposal("rename_category", payload)
    return {
        "tool": "propose_rename_category",
        "proposal_id": proposal_id,
        "proposal_token": proposal_token,
        "summary": f"Rename category '{old_name}' → '{new_name}' ({affected_count} transactions affected)",
        "before": {"category": old_name, "affected_count": affected_count},
        "after": {"category": new_name, "affected_count": affected_count},
    }


def propose_merge_category(from_name: str, into_name: str) -> dict:
    """Propose merging one category into another. Non-orphaning — always allowed.
    All transactions in from_name will be recategorized to into_name.
    Returns a proposal for user confirmation. Does NOT change any data — user must approve.
    """
    count_sql = "SELECT COUNT(*) FROM transactions WHERE category = :cat"
    with engine.connect() as c:
        affected_count = int(c.execute(text(count_sql), {"cat": from_name}).scalar() or 0)

    payload = {
        "operation": "merge_category",
        "rows": [{"from_name": from_name, "into_name": into_name, "affected_count": affected_count}],
    }
    proposal_id, proposal_token = _make_proposal("merge_category", payload)
    return {
        "tool": "propose_merge_category",
        "proposal_id": proposal_id,
        "proposal_token": proposal_token,
        "summary": f"Merge category '{from_name}' into '{into_name}' ({affected_count} transactions affected)",
        "before": {"category": from_name, "affected_count": affected_count},
        "after": {"category": into_name, "affected_count": affected_count},
    }


def propose_add_holding(
    ticker: str,
    quantity: float,
    avg_cost: float,
    platform_id: int | None = None,
    purchase_date: str | None = None,
    currency: str = "IDR",
    asset_type: str | None = None,
) -> dict:
    """Propose adding a new holding (investment position). Returns a proposal for user confirmation.
    Does NOT add any data — user must approve. D-05: holdings row CRUD only, no portfolio_events.
    platform_id is required by the holdings schema (multi-platform, D-17) — use
    find_platforms to resolve a platform name to its id before calling this.
    """
    after = {
        "ticker": ticker,
        "quantity": str(Decimal(str(quantity))),
        "avg_cost": str(Decimal(str(avg_cost))),
        "platform_id": platform_id,
        "purchase_date": purchase_date,
        "currency": currency,
        "asset_type": asset_type,
    }
    payload = {"operation": "add_holding", "rows": [{"before": None, "after": after}]}
    proposal_id, proposal_token = _make_proposal("add_holding", payload)
    return {
        "tool": "propose_add_holding",
        "proposal_id": proposal_id,
        "proposal_token": proposal_token,
        "summary": f"Add holding: {quantity} {ticker} @ {avg_cost} {currency}",
        "before": None,
        "after": after,
    }


def propose_edit_holding(
    holding_id: int,
    quantity: float | None = None,
    avg_cost: float | None = None,
    purchase_date: str | None = None,
    currency: str | None = None,
    asset_type: str | None = None,
) -> dict:
    """Propose editing a holding. Only provided fields will be changed.
    Returns a proposal for user confirmation. Does NOT change any data — user must approve.
    D-05: holdings row CRUD only, no portfolio_events.
    """
    from backend.models import Holding

    with get_session_sync() as db:
        h = db.get(Holding, holding_id)
        if h is None:
            return {"tool": "propose_edit_holding", "error": f"Holding {holding_id} not found"}
        before = _holding_to_dict(h)

    after = {**before}
    if quantity is not None:
        after["quantity"] = str(Decimal(str(quantity)))
    if avg_cost is not None:
        after["avg_cost"] = str(Decimal(str(avg_cost)))
    if purchase_date is not None:
        after["purchase_date"] = purchase_date
    if currency is not None:
        after["currency"] = currency
    if asset_type is not None:
        after["asset_type"] = asset_type

    payload = {
        "operation": "edit_holding",
        "rows": [{"id": holding_id, "before": before, "after": after}],
    }
    proposal_id, proposal_token = _make_proposal("edit_holding", payload)
    return {
        "tool": "propose_edit_holding",
        "proposal_id": proposal_id,
        "proposal_token": proposal_token,
        "summary": f"Edit holding #{holding_id} ({before.get('ticker', '')}): {_diff_summary(before, after)}",
        "before": before,
        "after": after,
    }


def propose_delete_holding(holding_id: int) -> dict:
    """Propose deleting a holding. Returns a proposal for user confirmation.
    Does NOT delete any data — user must approve. D-05: holdings row CRUD only, no portfolio_events.
    """
    from backend.models import Holding

    with get_session_sync() as db:
        h = db.get(Holding, holding_id)
        if h is None:
            return {"tool": "propose_delete_holding", "error": f"Holding {holding_id} not found"}
        before = _holding_to_dict(h)

    payload = {
        "operation": "delete_holding",
        "rows": [{"id": holding_id, "before": before, "after": None}],
    }
    proposal_id, proposal_token = _make_proposal("delete_holding", payload)
    return {
        "tool": "propose_delete_holding",
        "proposal_id": proposal_id,
        "proposal_token": proposal_token,
        "summary": f"Delete holding #{holding_id} ({before.get('ticker', '')})",
        "before": before,
        "after": None,
    }


# Extend the TOOLS registry with write tools (proposal-producers)
TOOLS.update({
    "propose_add_transaction": propose_add_transaction,
    "propose_edit_transaction": propose_edit_transaction,
    "propose_delete_transaction": propose_delete_transaction,
    "propose_add_account": propose_add_account,
    "propose_edit_account": propose_edit_account,
    "propose_delete_account": propose_delete_account,
    "propose_rename_category": propose_rename_category,
    "propose_merge_category": propose_merge_category,
    "propose_add_holding": propose_add_holding,
    "propose_edit_holding": propose_edit_holding,
    "propose_delete_holding": propose_delete_holding,
})


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
