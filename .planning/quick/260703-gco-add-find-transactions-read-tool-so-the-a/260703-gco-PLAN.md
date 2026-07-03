---
phase: quick-260703-gco
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/tools.py
  - backend/query.py
  - backend/tests/test_tools.py
autonomous: true
requirements:
  - CHAT-FIND-TX
must_haves:
  truths:
    - "The agent can call find_transactions with a merchant name and get back rows that include each transaction's id."
    - "find_transactions filters by merchant (case-insensitive partial), category (exact), kind (all/expense/income), and period, returning most-recent-first."
    - "The FunctionAgent actually exposes find_transactions as a callable tool (imported and wrapped in FunctionTool)."
  artifacts:
    - "backend/tools.py::find_transactions"
    - "backend/tools.py TOOLS registry entry for find_transactions"
    - "backend/query.py import tuple + read_tools list entry for find_transactions"
    - "backend/tests/test_tools.py find_transactions integration tests"
  key_links:
    - "find_transactions rows[0].id → propose_edit_transaction(transaction_id) / propose_delete_transaction(transaction_id)"
    - "query.py read_tools list → FunctionAgent tool visibility (without this the agent cannot call the tool)"
---

<objective>
Add a `find_transactions` read tool so the chat agent can resolve a merchant name (e.g. "my last Gojek transaction") to a concrete transaction `id`, which it then passes to `propose_edit_transaction`/`propose_delete_transaction`.

Purpose: Closes a real Phase 2 tool-coverage gap — none of the 8 existing read tools expose a transaction's `id`, and there is no merchant/category search tool, so the agent has no path from "the Gojek transaction" to a numeric `transaction_id`.

Output: New parameterized read tool in `backend/tools.py`, registered in `TOOLS`, wired into the FunctionAgent in `backend/query.py`, and covered by DB-integration tests in `backend/tests/test_tools.py`.
</objective>

<execution_context>
@/home/user/monai/.claude/gsd-core/workflows/execute-plan.md
@/home/user/monai/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@backend/tools.py
@backend/query.py
@backend/tests/test_tools.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Implement and register find_transactions in backend/tools.py</name>
  <files>backend/tools.py</files>
  <action>
Add a new read tool `find_transactions` immediately after `list_categories` (before the read-tools `TOOLS` registry at ~line 244). Follow the EXACT conventions of `largest_transactions` and `transaction_count`.

Signature:
`def find_transactions(merchant: str | None = None, category: str | None = None, period="all_time", start_date=None, end_date=None, kind="all", limit=10) -> dict:`

Docstring: one line describing that it searches/filters individual transactions and returns their ids, dates, amounts, categories, merchants, and account ids — so the agent can resolve a merchant/category to a transaction id before proposing an edit or delete. Note the sign convention for kind and that transfers are excluded.

Implementation rules:
- Resolve dates with `s, e = resolve_period(period, start_date, end_date)`.
- Build the params dict starting with the clamped limit exactly like `largest_transactions`: `p: dict = {"lim": max(1, min(int(limit), 50))}`.
- Build a list of WHERE clause fragments starting with `["is_transfer = false"]`. This mirrors the transfers-excluded convention of the other read tools. Document in the docstring that transfers are excluded (the recategorize use case targets normal spend rows, not transfers); this is the deliberate choice required by the constraints.
- If `merchant is not None`: append clause `"merchant ILIKE :merchant"` and set `p["merchant"] = f"%{merchant}%"`. The wildcards go in the BOUND PARAM VALUE, never in the SQL string — case-insensitive partial match.
- If `category is not None`: append clause `"category = :category"` and set `p["category"] = category`. Exact match (per constraints), parameterized.
- kind sign filter like `transaction_count`: map `{"expense": "amount < 0", "income": "amount > 0"}`; for `"all"` (or unknown) add no sign clause.
- Compose SQL as: `"SELECT id, date, amount, category, merchant, account_id FROM transactions WHERE " + " AND ".join(clauses) + _date_clause(s, e, p) + " ORDER BY date DESC LIMIT :lim"`. `_date_clause` returns a leading `" AND ..."` fragment, so joining it after the assembled WHERE clauses is correct. ORDER BY date DESC makes `rows[0]` the most recent ("my last X") transaction.
- Execute with `with engine.connect() as c:` and build row dicts. `date` is a datetime column (see `largest_transactions` calling `.date()`); emit `"date": r[1].date().isoformat()`. Emit the SIGNED amount as `"amount": float(r[2])` (do NOT use ABS — callers need to know expense vs income and the true value). Include `"id": r[0]`, `"category": r[3]`, `"merchant": r[4]`, `"account_id": r[5]`.
- Return `{"tool": "find_transactions", "rows": rows, "kind": kind, "period": _period_label(period, s, e)}`.

Then register it in the read-tools `TOOLS` dict (the one ending at ~line 254): add `"find_transactions": find_transactions,` as the final entry.

Do NOT modify any `propose_*` write tool or the write-tools `TOOLS.update({...})` block. Do NOT add an account-lookup tool.
  </action>
  <verify>
    <automated>cd /home/user/monai && python -c "from backend.tools import find_transactions, TOOLS; assert TOOLS['find_transactions'] is find_transactions; import inspect; sig=inspect.signature(find_transactions); assert list(sig.parameters)==['merchant','category','period','start_date','end_date','kind','limit'], list(sig.parameters); print('ok')"</automated>
  </verify>
  <done>find_transactions exists with the exact signature, is present in the read-tools TOOLS registry, uses parameterized SQL (no f-string interpolation of merchant/category values), and returns rows containing id/date/amount/category/merchant/account_id ordered by date DESC.</done>
</task>

<task type="auto">
  <name>Task 2: Wire find_transactions into the FunctionAgent in backend/query.py</name>
  <files>backend/query.py</files>
  <action>
Two edits inside `_get_agent_workflow()` (~lines 84-109):

1. In the `from backend.tools import (...)` tuple, add `find_transactions` to the read-tools group (the block after the `# Read tools` comment, alongside `average_daily_spending, list_categories`).

2. In the `read_tools = [...]` list, add `FunctionTool.from_defaults(fn=find_transactions),` as the final read-tools entry (after the `list_categories` entry).

Do NOT touch `write_tools`, the system prompt, or any other wiring. Without both edits the FunctionAgent cannot see the tool — this is the load-bearing part of the fix.
  </action>
  <verify>
    <automated>cd /home/user/monai && python -c "import ast; src=open('backend/query.py').read(); t=ast.parse(src); assert src.count('find_transactions')>=2, src.count('find_transactions'); assert 'FunctionTool.from_defaults(fn=find_transactions)' in src; print('ok')"</automated>
  </verify>
  <done>find_transactions is both imported in the read-tools import tuple and wrapped via FunctionTool.from_defaults in the read_tools list; query.py parses cleanly.</done>
</task>

<task type="auto">
  <name>Task 3: Add find_transactions integration tests to backend/tests/test_tools.py</name>
  <files>backend/tests/test_tools.py</files>
  <action>
Add test methods inside the existing `TestToolSQL` class, following the established pattern: each test takes the `db_available` fixture (so it skips cleanly when Postgres is unreachable) and imports `find_transactions` locally at the top of the method.

Cover:
- Returned rows include an `id` key (the critical fix). Call `find_transactions(limit=5)`; for every row assert `"id" in row` and `isinstance(row["id"], int)`, and assert the row also contains `date`, `amount`, `category`, `merchant`, `account_id` keys.
- Ordering: rows are most-recent-first — assert the list of `row["date"]` values equals its own `sorted(..., reverse=True)`.
- Limit clamping: `find_transactions(limit=999)` returns at most 50 rows; `find_transactions(limit=0)` returns at least 0 and the call does not raise (clamp floor is 1).
- kind filter: every row from `find_transactions(kind="expense")` has `amount < 0`; every row from `find_transactions(kind="income")` has `amount > 0`.
- category filter: pull a category from `list_categories()["rows"]` (skip the assertion body if there are none), call `find_transactions(category=<that name>)`, and assert every returned row has `row["category"] == <that name>` (exact match).
- merchant partial match: this is data-dependent, so make it robust — call `find_transactions(limit=1)`; if a row exists and its `merchant` is non-empty, take a lowercase substring of that merchant, call `find_transactions(merchant=<substring>)`, and assert at least one returned row's merchant (lowercased) contains that substring (case-insensitive partial). If no merchant data exists, the assertion is trivially skipped.

Do NOT add a module-level DB dependency or change the existing `db_available` fixture or the pure `TestResolvePeriod` tests.
  </action>
  <verify>
    <automated>cd /home/user/monai && python -m pytest backend/tests/test_tools.py -q 2>&1 | tail -20</automated>
  </verify>
  <done>New find_transactions tests are added to TestToolSQL, collect without import/collection errors, and either pass or skip cleanly when the DB is unavailable (no failures). Tests assert rows include an int id plus date/amount/category/merchant/account_id, verify DESC ordering, limit clamping, kind sign filter, exact category match, and case-insensitive merchant partial match.</done>
</task>

</tasks>

<verification>
- `python -c "from backend.tools import find_transactions, TOOLS; assert 'find_transactions' in TOOLS"` succeeds.
- `python -c "import backend.query"` imports without error.
- `python -m pytest backend/tests/test_tools.py -q` reports no failures (passes or skips depending on DB availability).
- Manual grep confirms no f-string/`%`-interpolation of `merchant` or `category` values into SQL — only bound params (`:merchant`, `:category`).
</verification>

<success_criteria>
- The agent has a tool that returns transaction `id`s filtered by merchant/category/kind/period, ordered most-recent-first.
- The tool is registered in the read-tools `TOOLS` registry AND exposed to the FunctionAgent via `read_tools` in `query.py`.
- All parameterized SQL conventions (`resolve_period`, `_date_clause`, `text()` bound params, `engine.connect()`, limit clamp) match the existing read tools.
- No write tool touched; no account-lookup tool added.
- Tests cover id presence, ordering, limit clamp, kind filter, exact category filter, and merchant partial match, and skip cleanly without a DB.
</success_criteria>

<output>
Create `.planning/quick/260703-gco-add-find-transactions-read-tool-so-the-a/260703-gco-SUMMARY.md` when done.
</output>
