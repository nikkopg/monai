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


# Registry: name -> callable (read tools)
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
    purchase_date: str | None = None,
    currency: str = "IDR",
    asset_type: str | None = None,
) -> dict:
    """Propose adding a new holding (investment position). Returns a proposal for user confirmation.
    Does NOT add any data — user must approve. D-05: holdings row CRUD only, no portfolio_events.
    """
    after = {
        "ticker": ticker,
        "quantity": str(Decimal(str(quantity))),
        "avg_cost": str(Decimal(str(avg_cost))),
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
