"""
MCP server — API-key-gated external tool surface (MCP-01..MCP-04, MCPW-01..03).

Registers the 16 read callables in backend.tools.READ_TOOL_NAMES (MCP-02) plus
four curated write wrappers from backend.mcp_writes (Phase 32), all with
hand-authored external-LLM-facing descriptions (D-05). The write wrappers are
registered here only and never in tools.TOOLS, so the chat agent surface is
unchanged (D-02). They only create, replace or reject pending proposals;
approval needs the 6-character code the owner reads in monai.

Each read callable self-manages its own DB session and returns a plain
JSON-serializable dict; that dict is returned unchanged as the MCP tool
result — no adapter, no formatting. FastMCP logs tool arguments, so an
argument-redacting filter is installed at import (D-22).
"""

import logging

from fastmcp import FastMCP

from backend.mcp_writes import NEXT_STEP, WRITE_TOOLS
from backend.tools import PERIODS, READ_TOOL_NAMES, TOOLS


class _RedactToolArgs(logging.Filter):
    """FastMCP logs call arguments at DEBUG and validation input at WARNING;
    a confirm code must never be written. Keep the record, drop the values."""

    def filter(self, record: logging.LogRecord) -> bool:
        args, msg = record.args, str(record.msg)
        if isinstance(args, tuple) and len(args) >= 2:
            if "Handler called:" in msg:
                record.args = (args[0], "<redacted>", *args[2:])
            elif msg.startswith("Invalid arguments for tool"):
                record.args = (args[0], "<redacted>")
        return True


for _name in ("fastmcp.server.mixins.mcp_operations", "fastmcp.server.server"):
    logging.getLogger(_name).addFilter(_RedactToolArgs())
# sse_starlette logs every SSE chunk at DEBUG, and a validation-error chunk echoes
# the submitted arguments; pin it so a root DEBUG setting cannot log a code (T-32-38).
logging.getLogger("sse_starlette").setLevel(logging.INFO)

# Valid named periods, shared across every period-taking tool's description
# (D-05) — sourced from backend.tools.PERIODS, never hard-coded.
_PERIOD_HELP = (
    "period must be one of: " + ", ".join(p for p in PERIODS if p != "custom")
    + '. Or pass period="custom" with ISO start_date and end_date (YYYY-MM-DD, end_date inclusive).'
)

# Hand-authored, external-LLM-facing descriptions (D-05). Reuses each
# callable's docstring prose as a base where it already reads well.
MCP_DESCRIPTIONS: dict[str, str] = {
    "spending_total": "Total money spent (expenses only, transfers excluded) over a period. " + _PERIOD_HELP,
    "income_total": "Total money received (income only, transfers excluded) over a period. " + _PERIOD_HELP,
    "net_total": "Net cash flow (income minus expenses, transfers excluded) over a period. " + _PERIOD_HELP,
    "spending_by_category": (
        "Top spending categories (expenses only) over a period, rolled up to top-level "
        "category groups — each group's total includes all its descendant subcategories; "
        "per-subcategory breakdown under 'children'. Transfers and system categories "
        "excluded. " + _PERIOD_HELP
    ),
    "spending_in_category": (
        "Total spent in one category INCLUDING all of its descendant subcategories — a "
        "parent/group name sums its entire subtree (case-insensitive name match). "
        + _PERIOD_HELP
    ),
    "spending_before_after_purchase": (
        "Compare category spending before vs. after the earliest 'buy' event for a given ticker in "
        "portfolio_events, using equal-length before/after windows. Returns a structured error if no "
        "buy event exists for the ticker, or if the purchase date is today/future (no 'after' window yet)."
    ),
    "transaction_count": (
        "Count transactions over a period. kind: all | expense | income. " + _PERIOD_HELP
    ),
    "largest_transactions": (
        "Largest individual transactions by magnitude over a period. kind: expense | income. " + _PERIOD_HELP
    ),
    "average_daily_spending": "Average spending per day over a period. " + _PERIOD_HELP,
    "monthly_trend": (
        "Month-over-month income/expense/net for the last N months (months clamped to a minimum of 6; "
        "a rolling window, not a calendar-year bound). Transfers excluded."
    ),
    "account_balances": (
        "Per-account current balance (all-time) plus period_net (scoped to an already-resolved "
        "[period_start, period_end) window). Transfers excluded from both sums. Accounts with no "
        "transactions appear with 0/0."
    ),
    "list_categories": (
        "The full category tree: top-level groups with nested children (id, name, kind, "
        "icon, effective color). Helps map a vague term to a real category or group name."
    ),
    "find_transactions": (
        "Search/filter individual transactions by merchant, category, period, and kind (all | expense | "
        "income); returns ids, dates, amounts, categories, merchants, and account ids. Rows are ordered "
        "most-recent-first. " + _PERIOD_HELP
    ),
    "find_platforms": "Search/filter investment platforms by name substring; returns ids, names, and kinds.",
    "find_accounts": "Search/filter accounts by name substring; returns ids, names, types, and currencies.",
    "net_worth": (
        "Single trustworthy net worth = liquid accounts + investment platforms, each "
        "counted exactly once. Returns total, liquid_total, investment_total, "
        "liquid_accounts, investment_groups, accounts_covered, accounts_total."
    ),
    "propose_transactions": (
        "Propose transactions for the owner to approve; nothing is written until approved. "
        'Single row: rows=[{"date": "2026-01-15", "amount": -45000, "account": "Main Checking", '
        '"merchant": "Coffee Shop"}]. Up to 500 rows (for example every line read from a statement) '
        "go in one call as one batch. amount is signed (negative = expense, positive = income); "
        "account must be an existing liquid account (call find_accounts); category, if given, must be "
        "an existing category (call list_categories); dates are YYYY-MM-DD, not in the future. Rows that "
        "look like an existing transaction or another pending row (same account and amount within 3 days) "
        "are returned in duplicates for the owner to review and are still proposed. To fix a pending "
        "proposal call again with replaces=<proposal_id>. " + NEXT_STEP
    ),
    "propose_transfer": (
        "Propose one transfer between two existing liquid accounts in the same currency (two ledger rows); "
        "nothing is written until approved. amount is a positive magnitude: the source is debited and the "
        "destination credited. date is YYYY-MM-DD, not in the future. replaces=<proposal_id> fixes a "
        "pending one. " + NEXT_STEP
    ),
    "confirm_proposal": (
        "Apply a pending proposal this MCP client created, using the 6-character code the owner reads in "
        "monai. Never guess a code. Send the code as a string. Wrong codes count: 5 wrong codes lock the "
        "proposal for MCP, and an hourly limit stops MCP confirms. The owner can always approve in monai."
    ),
    "reject_proposal": (
        "Discard a pending proposal this MCP client created; needs no code. Proposals from other "
        "channels must be rejected in monai."
    ),
}


def build_mcp() -> FastMCP:
    """Build the FastMCP instance: 16 reads plus 4 curated writes.

    Reads come from backend.tools.READ_TOOL_NAMES (the pre-mutation snapshot,
    never TOOLS directly, since TOOLS also holds the chat propose_* tools by
    the time this module loads); writes come from backend.mcp_writes.WRITE_TOOLS
    only (D-01, D-02).
    """
    mcp = FastMCP("monai finance")
    for name in READ_TOOL_NAMES:
        fn = TOOLS[name]
        mcp.tool(name=name, description=MCP_DESCRIPTIONS.get(name, fn.__doc__ or name))(fn)
    for name, fn in WRITE_TOOLS.items():
        mcp.tool(name=name, description=MCP_DESCRIPTIONS[name])(fn)
    return mcp
