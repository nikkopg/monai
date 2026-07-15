"""
MCP server — read-only, API-key-gated external tool surface (MCP-01..MCP-04).

Registers backend.tools.TOOLS (the 15 read callables — single source of truth,
MCP-02) as MCP tools with hand-authored external-LLM-facing descriptions
(D-05). The write/propose_* tools are never registered here (D-03/MCP-03) —
an external client cannot even see them in tools/list, let alone call them.

Each TOOLS callable self-manages its own DB session and returns a plain
JSON-serializable dict; that dict is returned unchanged as the MCP tool
result — no adapter, no formatting.
"""

from fastmcp import FastMCP

from backend.tools import PERIODS, READ_TOOL_NAMES, TOOLS

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
    "spending_by_category": "Top spending categories (expenses only) over a period, ranked by total. " + _PERIOD_HELP,
    "spending_in_category": (
        "Total spent in a specific category (substring match on category/raw_category) over a period. "
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
    "list_categories": "List distinct expense categories with their total spend (helps map a vague term to a real category).",
    "find_transactions": (
        "Search/filter individual transactions by merchant, category, period, and kind (all | expense | "
        "income); returns ids, dates, amounts, categories, merchants, and account ids. Rows are ordered "
        "most-recent-first. " + _PERIOD_HELP
    ),
    "find_platforms": "Search/filter investment platforms by name substring; returns ids, names, and kinds.",
    "find_accounts": "Search/filter accounts by name substring; returns ids, names, types, and currencies.",
}


def build_mcp() -> FastMCP:
    """Build the FastMCP instance with the 15 read-only callables registered.

    Registers ONLY the names in backend.tools.READ_TOOL_NAMES — never the
    propose_* write tools (D-03). By the time this module loads,
    backend.tools.TOOLS itself has already been mutated to 26 entries (15
    read + 11 write, via TOOLS.update() at the bottom of tools.py), so
    iterating TOOLS directly would leak write tools onto the MCP surface;
    READ_TOOL_NAMES is the pre-mutation snapshot that keeps this read-only
    by construction. Each callable's dict return is unchanged; it serializes
    cleanly as an MCP structured tool result.
    """
    mcp = FastMCP("monai finance (read-only)")
    for name in READ_TOOL_NAMES:
        fn = TOOLS[name]
        mcp.tool(name=name, description=MCP_DESCRIPTIONS.get(name, fn.__doc__ or name))(fn)
    return mcp
