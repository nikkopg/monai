"""
AI query layer over the monai SQLite database.

Uses LlamaIndex NLSQLTableQueryEngine to translate natural-language questions
into SQL. Results are cached per (question, today's date) so repeated questions
are instant without hitting the LLM.
"""

import datetime
from functools import lru_cache
from pathlib import Path

from sqlalchemy import create_engine

from llama_index.core import SQLDatabase
from llama_index.core.query_engine import NLSQLTableQueryEngine

from poc.config import configure_llm
from poc.db import DB_PATH

_engine = None
_query_engine = None

# Injected into every system prompt so relative date expressions work reliably.
_DATE_CONTEXT = """
You are a financial data assistant. The database has two tables:
  - transactions: id, date, amount, currency, category, raw_category, merchant,
                  notes, account_id, is_transfer
  - accounts: id, name, type, currency
  - date_helpers (view): current_month_start, current_month_end, last_month_start,
                         last_month_end, current_year_start, q1_end, q2_start,
                         q2_end, q3_start, q3_end, q4_start, q4_end

Rules:
  - TODAY is {today}.
  - Use the date_helpers view for relative date queries ("last month", "this year", etc.).
  - ALWAYS filter WHERE is_transfer = 0 unless the user explicitly asks about transfers.
  - Amounts are stored as signed floats: negative = expense, positive = income.
  - All amounts are in {currency}.

Answer only from the data. If uncertain, say so.
"""


def _build_engine(db_path: Path = DB_PATH):
    global _engine, _query_engine
    configure_llm()

    engine = create_engine(f"sqlite:///{db_path}")
    # date_helpers is a VIEW — SQLAlchemy's reflection skips views, so it must
    # NOT appear in include_tables. The LLM learns about it from context_str
    # and can still reference it in generated SQL since it exists in SQLite.
    sql_db = SQLDatabase(engine, include_tables=["transactions", "accounts"])

    from sqlalchemy import text
    with engine.connect() as conn:
        row = conn.execute(text("SELECT currency FROM transactions LIMIT 1")).fetchone()
        currency = row[0] if row else "unknown"

    today = datetime.date.today().isoformat()
    context = _DATE_CONTEXT.format(today=today, currency=currency)

    _engine = engine
    _query_engine = NLSQLTableQueryEngine(
        sql_database=sql_db,
        tables=["transactions", "accounts"],
        context_str=context,
    )
    return _query_engine


def _get_query_engine(db_path: Path = DB_PATH):
    global _query_engine
    if _query_engine is None:
        _build_engine(db_path)
    return _query_engine


@lru_cache(maxsize=256)
def ask(question: str, today: str = "", db_path: str = str(DB_PATH)) -> str:
    """
    Ask a natural-language question about your financial data.

    Results are cached per (question, today) so repeated questions in the same
    session are instant.

    Args:
        question: Natural language question, e.g. "How much did I spend on food last month?"
        today: Today's date as YYYY-MM-DD string (used as cache key). Defaults to today.
        db_path: Path to the SQLite database.

    Returns:
        Answer string from the LLM.
    """
    if not today:
        today = datetime.date.today().isoformat()

    qe = _get_query_engine(Path(db_path))
    response = qe.query(question)
    return str(response)
