"""
monai PoC — Streamlit chat UI.

Run:
    LLM_PROVIDER=ollama streamlit run poc/app.py

The 10 pre-defined test questions are shown as quick-fire buttons.
Pass/fail results are tracked in session state for the A→C handoff report.
"""

import datetime
import sqlite3
import sys
from pathlib import Path

import streamlit as st

# Add project root to path so poc.* imports work
sys.path.insert(0, str(Path(__file__).parent.parent))

from poc.db import DB_PATH, init_db
from poc.query import ask

# Pre-defined test questions (D10 — must be defined before any code)
TEST_QUESTIONS = [
    "How much did I spend in total this month?",
    "How much did I spend on food and drinks this month?",
    "What were my top 3 spending categories last month?",
    "How much did I spend in total last month?",
    "What is my total income vs total expenses this year?",
    "Which day had my highest single expense?",
    "How many transactions did I make this month?",
    "What is my average daily spending this month?",
    "How much did I spend on free time activities?",
    "What are my 5 most expensive individual transactions?",
]


def main():
    st.set_page_config(page_title="monai", page_icon="💰", layout="wide")
    st.title("monai — personal wealth intelligence")

    # Check DB exists
    if not DB_PATH.exists():
        st.error(
            f"Database not found at `{DB_PATH}`. "
            "Run `python -m poc.load <path/to/export.csv>` first."
        )
        st.stop()

    # Session state
    if "history" not in st.session_state:
        st.session_state.history = []
    if "test_results" not in st.session_state:
        st.session_state.test_results = {}

    # Sidebar — stats + test suite
    with st.sidebar:
        st.header("Database")
        try:
            conn = sqlite3.connect(DB_PATH)
            n_tx = conn.execute(
                "SELECT COUNT(*) FROM transactions WHERE is_transfer = 0"
            ).fetchone()[0]
            n_acc = conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
            currency = conn.execute(
                "SELECT currency FROM transactions LIMIT 1"
            ).fetchone()
            conn.close()
            st.metric("Transactions", n_tx)
            st.metric("Accounts", n_acc)
            if currency:
                st.metric("Currency", currency[0])
        except Exception as e:
            st.warning(f"Could not read DB: {e}")

        st.divider()
        st.header("Test Suite (A→C exit criteria)")
        st.caption("Run all 10 to check handoff readiness (need 7/10 pass).")

        if st.button("Run all 10 questions"):
            with st.spinner("Running test suite…"):
                today = datetime.date.today().isoformat()
                for q in TEST_QUESTIONS:
                    try:
                        answer = ask(q, today=today)
                        st.session_state.test_results[q] = ("pass", answer)
                    except Exception as e:
                        st.session_state.test_results[q] = ("fail", str(e))

        if st.session_state.test_results:
            passed = sum(
                1
                for s, _ in st.session_state.test_results.values()
                if s == "pass"
            )
            st.metric("Passed", f"{passed}/10")
            for q, (status, _) in st.session_state.test_results.items():
                icon = "✅" if status == "pass" else "❌"
                st.write(f"{icon} {q[:55]}…" if len(q) > 55 else f"{icon} {q}")

    # Main — chat
    col1, col2 = st.columns([3, 1])
    with col1:
        st.subheader("Ask about your finances")

    with col2:
        if st.button("Clear chat"):
            st.session_state.history = []

    # Quick question buttons
    st.caption("Quick questions:")
    cols = st.columns(3)
    for i, q in enumerate(TEST_QUESTIONS[:6]):
        short = q[:40] + "…" if len(q) > 40 else q
        if cols[i % 3].button(short, key=f"quick_{i}"):
            st.session_state.history.append(("user", q))

    # Chat input
    user_input = st.chat_input("Ask anything about your spending…")
    if user_input:
        st.session_state.history.append(("user", user_input))

    # Render conversation
    for role, msg in st.session_state.history:
        with st.chat_message(role):
            if role == "user":
                st.write(msg)
            else:
                st.write(msg)

    # Generate answer for last unanswered user message
    if (
        st.session_state.history
        and st.session_state.history[-1][0] == "user"
    ):
        last_question = st.session_state.history[-1][1]
        with st.chat_message("assistant"):
            with st.spinner("Thinking…"):
                try:
                    today = datetime.date.today().isoformat()
                    answer = ask(last_question, today=today)
                    st.write(answer)
                    st.session_state.history.append(("assistant", answer))
                except Exception as e:
                    error_msg = f"Error: {e}"
                    st.error(error_msg)
                    st.session_state.history.append(("assistant", error_msg))


if __name__ == "__main__":
    main()
