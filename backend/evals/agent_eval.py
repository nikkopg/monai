"""
Opt-in golden-question eval for the production agent loop.

What this is: a standalone script, NOT a pytest test and NOT collected by
default pytest or CI (backend/evals/ sits outside pyproject.toml's
testpaths). It sends ~20 scripted questions through backend.query.agent_stream
— the real, production agent loop — driven by whatever real LLM is
configured via LLM_PROVIDER / the matching model env var. It runs only
against monai_test, never the live monai database; a module-top guard
refuses to proceed otherwise, before any backend import.

It seeds its own synthetic ZZEval rows (one account, three categories, the
four case rows, a recurring series with a transfer decoy and a
portfolio-linked decoy, one platform and their portfolio events) before
running, and removes every ZZEval row and every pending proposal it created
afterwards, in a `finally` block that
also runs on Ctrl-C. It never approves a proposal.

Cases 15-17 and 20 are multi-turn: their history is built in memory with
plan_history and they create no threads. Cases 18-20 cover Phase 38 (a
read-only tool subset, an ordered two-write request, a long summarised thread).

Usage:
    env -u DATABASE_URL .venv/bin/python -m backend.evals.agent_eval \
        [--self-check] [--seed-check] [--case N ...]

    --self-check   run the answer-number parser's asserts only. No DB, no LLM.
    --seed-check   run the DB guard, head check, seed, probes and teardown.
                   No LLM.
    --case N       run only case N (repeatable). Default: run all 20 cases.

Exit code 0 means every selected case passed (or, for --self-check /
--seed-check, that check passed). Exit code 1 otherwise.
"""

import argparse
import asyncio
import calendar
import datetime
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from sqlalchemy.engine.url import make_url

# ---------------------------------------------------------------------------
# Live-DB guard — mirrors backend/tests/conftest.py:36-63.
# Deliberately duplicated, not imported: importing conftest.py would re-run
# its create-and-migrate bootstrap (this script must never create or migrate
# a database), and moving the guard into a shared module would break
# test_conftest_guard.py, which relies on the guard running at conftest
# collection time. Keep this block in sync BY HAND
# with conftest.py's guard if that guard ever changes.
#
# This block must run, and finish, before any `from backend...`/`import
# backend...` statement anywhere below — backend/db.py builds its engine
# from DATABASE_URL at import time.
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_TEST_URL = "postgresql+psycopg://monai:monai@localhost:5434/monai_test"
os.environ.setdefault("DATABASE_URL", _DEFAULT_TEST_URL)

_TEST_DB = make_url(os.environ["DATABASE_URL"])
# A query-string dbname= replaces the path database at connect time (the
# psycopg dialect merges url.query over it), so the path name checked below
# would not be the database actually used. Refuse it with any value —
# make_url silently drops an empty ?dbname=, hence the raw parse as well.
if "dbname" in _TEST_DB.query or "dbname" in parse_qs(
    urlsplit(os.environ["DATABASE_URL"]).query, keep_blank_values=True
):
    raise SystemExit(
        "Refusing to run the agent eval: DATABASE_URL overrides the "
        "database with a query-string dbname=. Name the test database in "
        "the URL path only."
    )
if _TEST_DB.database == "monai":
    raise SystemExit(
        "Refusing to run the agent eval against the live 'monai' database. "
        "Unset DATABASE_URL (it defaults to monai_test) or point it at a "
        "test database."
    )
if not _TEST_DB.database or not re.fullmatch(r"[A-Za-z0-9_]+", _TEST_DB.database):
    raise SystemExit(
        f"Refusing to run the agent eval: DATABASE_URL names an invalid "
        f"database {_TEST_DB.database!r}. Database names must match "
        f"[A-Za-z0-9_]+."
    )


# ---------------------------------------------------------------------------
# Answer-number extraction + matching. Pure stdlib, no DB, no
# LLM — this is the logic that decides pass/fail, so it gets its own
# --self-check with no side effects.
# ---------------------------------------------------------------------------


_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_ISO_DATE_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?\b"
)
_GLUED_PREFIX_RE = re.compile(r"(?i)\b(Rp\.?|IDR)(?=\d)")

# scale word -> multiplier. Order matters for the alternation built below:
# "million" must be tried before the single-letter "m", otherwise "m" would
# match the "m" inside "million" and leave "illion" dangling (it wouldn't —
# \b after the scale group blocks that — but longest-first keeps intent
# obvious and avoids relying on that fence alone).
#
# "M" is read as million (English usage), never as Indonesian miliar; an
# answer that writes miliar as "M" fails as a mis-scaled figure.
_SCALE_WORDS = {
    "ribu": 1e3, "rb": 1e3, "k": 1e3, "thousand": 1e3,
    "juta": 1e6, "jt": 1e6, "million": 1e6, "mil": 1e6, "mio": 1e6, "mn": 1e6, "m": 1e6,
    "miliar": 1e9, "billion": 1e9, "bn": 1e9, "b": 1e9,
    "triliun": 1e12, "trillion": 1e12, "tn": 1e12, "t": 1e12,
}
_SCALE_PATTERN = "|".join(sorted(_SCALE_WORDS, key=len, reverse=True))

# Letters glued straight onto a number that are not a scale word ("4.3lakh",
# "1.5bil") make the figure unplaceable. Only these glued suffixes are safe
# to ignore (ordinals, a repeat count, a currency code).
_GLUED_OK = {"st", "nd", "rd", "th", "x", "idr", "rp", "usd"}

# Tolerance sentinel for an unplaceable token: it never matches anything, so
# a figure the parser can't read fails the case instead of vanishing.
_UNPLACEABLE = -1.0

# ponytail: regex heuristic, not a real number grammar — a lone "1.234" with
# 3 trailing digits after one separator reads as grouping (Indonesian-style),
# never as a 3-decimal fraction; spelled-out numbers ("one million") are
# ignored entirely; an unknown scale word after a SPACE ("1.5 zillion") is
# not caught (only glued ones are), since "3 items" must stay a plain count;
# every new format this misses needs its own self-check assert and a tweak
# here, not a rewrite.
_TOKEN_RE = re.compile(
    r"(?<![\w.,])"
    r"(?P<num>\d+(?:[.,]\d+)*)"
    r"(?:\s*(?P<scale>" + _SCALE_PATTERN + r")\b|(?P<glued>[A-Za-z]+))?"
    r"(?!\d)"
    r"(?!\s?%)",
    re.IGNORECASE,
)

_MONTHS = (
    "january|february|march|april|may|june|july|august|september|october|"
    "november|december|januari|februari|maret|mei|juni|juli|agustus|oktober|"
    "desember|jan|feb|mar|apr|jun|jul|aug|agu|sept|sep|oct|okt|nov|dec|des"
)
# Text right before a bare 1900-2100 integer that marks it as a year ("in
# 2024", "March 2024", "March 14, 2024", "year (2026)", "Q1 2024"). Without
# one of these cues the integer is kept as an amount ("Rp 2000 fee").
_YEAR_CUE_RE = re.compile(
    r"(?i)\b(?:in|since|during|year|tahun|q[1-4]|(?:" + _MONTHS + r")\.?"
    r"(?:\s+\d{1,2}(?:st|nd|rd|th)?,?)?)\W{0,3}$"
)


def _parse_number_str(raw: str) -> tuple[float, int]:
    """Return (value, decimal_digit_count). decimal_digit_count is 0 when
    every separator in `raw` turned out to be thousands-grouping."""
    seps = [i for i, ch in enumerate(raw) if ch in ".,"]
    if not seps:
        return float(raw), 0
    last = seps[-1]
    tail = raw[last + 1:]
    if re.fullmatch(r"\d{1,2}", tail):
        integer_part = re.sub(r"[.,]", "", raw[:last])
        return float(f"{integer_part}.{tail}"), len(tail)
    return float(re.sub(r"[.,]", "", raw)), 0


def extract_numbers(text: str) -> list[tuple[float, float]]:
    """Pull plausible monetary/count figures out of free LLM answer text.

    Returns (value, tolerance) pairs. A token matches a trace leaf when
    abs(abs(value) - leaf) <= tolerance (numbers_ok does that comparison).
    Drops UUIDs, ISO dates, percentages, 1900-2100 integers preceded by a
    year cue (_YEAR_CUE_RE) and anything under 100 in absolute value (small
    counts, day numbers). A number with unknown letters glued on comes back
    as (mantissa, _UNPLACEABLE), which never matches.
    """
    cleaned = _UUID_RE.sub(" ", text)
    cleaned = _ISO_DATE_RE.sub(" ", cleaned)
    cleaned = _GLUED_PREFIX_RE.sub(lambda m: m.group(0) + " ", cleaned)

    out: list[tuple[float, float]] = []
    for m in _TOKEN_RE.finditer(cleaned):
        raw_num = m.group("num")
        scale_word = m.group("scale")
        glued = (m.group("glued") or "").lower()
        try:
            value, decimals = _parse_number_str(raw_num)
        except ValueError:
            continue
        if glued and glued not in _GLUED_OK:
            out.append((value, _UNPLACEABLE))
            continue
        if scale_word:
            scale = _SCALE_WORDS[scale_word.lower()]
            value *= scale
            # Half a unit of the last quoted digit, capped at 5% of the value
            # so "about 1jt" can't claim a 1.49M leaf.
            tolerance = min(0.5 * (10 ** -decimals) * scale, 0.05 * value)
        else:
            if (
                re.fullmatch(r"\d+", raw_num)
                and 1900 <= value <= 2100
                and _YEAR_CUE_RE.search(cleaned[max(0, m.start() - 30):m.start()])
            ):
                continue  # a year, not an amount
            tolerance = 1.0
        if abs(value) < 100:
            continue  # small count / day number
        out.append((value, tolerance))
    return out


def _flatten_numbers(obj) -> list[float]:
    """Walk dicts/lists/tuples recursively, returning abs() of every numeric
    leaf. int/float leaves convert directly; numeric-string leaves parse
    (trace results that were Decimal before agent_stream's default=str
    serialization); bool leaves and unparseable strings are skipped."""
    out: list[float] = []

    def _walk(o) -> None:
        if isinstance(o, dict):
            for v in o.values():
                _walk(v)
        elif isinstance(o, (list, tuple)):
            for v in o:
                _walk(v)
        elif isinstance(o, bool):
            return
        elif isinstance(o, (int, float)):
            out.append(abs(o))
        elif isinstance(o, str):
            try:
                out.append(abs(float(o.strip())))
            except (TypeError, ValueError):
                pass

    _walk(obj)
    return out


def numbers_ok(answer: str, question: str, trace: list) -> tuple[bool, list[float]]:
    """True (and []) when every number in `answer` matches a number the
    trace actually returned (within tolerance), after dropping any number
    that merely echoes the question. Otherwise False plus the unmatched
    values."""
    question_tokens = extract_numbers(question)
    leaves = _flatten_numbers([step.get("result") for step in trace])

    unmatched: list[float] = []
    for value, tolerance in extract_numbers(answer):
        if tolerance == _UNPLACEABLE:
            unmatched.append(value)  # unreadable figure: fail, never skip
            continue
        if any(abs(abs(value) - abs(qv)) <= qtol for qv, qtol in question_tokens):
            continue  # echoes the question, not a claimed figure
        if any(abs(abs(value) - leaf) <= tolerance for leaf in leaves):
            continue
        unmatched.append(value)
    return (len(unmatched) == 0, unmatched)


def _self_check() -> None:
    """Pure-function asserts for extract_numbers/numbers_ok. No DB, no LLM —
    `backend.db` must never end up in sys.modules from this path."""
    assert "backend.db" not in sys.modules

    def vals(text: str) -> list[float]:
        return [v for v, _ in extract_numbers(text)]

    assert vals("You spent IDR 1,234,567.00 this month.") == [1234567.0]
    assert vals("Anda belanja Rp 1.234.567 bulan ini.") == [1234567.0]
    assert vals("Totalnya 1.234.567,89.") == [1234567.89]
    assert extract_numbers("That's about 1.2jt total.") == [(1200000.0, 50000.0)]
    assert vals(
        "In 2024 you spent 500rb on 2024-03-14 across 3 transactions."
    ) == [500000.0]
    assert vals("Roughly 2.5M, or 1.2 million, or 43k.") == [
        2500000.0,
        1200000.0,
        43000.0,
    ]
    assert vals(
        "Up 150% on proposal 3f2a9c1e-1b2c-4d5e-8f90-123456789abc"
    ) == []

    assert numbers_ok(
        "You spent Rp 43.000", "how much", [{"result": {"total": "43000.00"}}]
    ) == (True, [])
    assert numbers_ok(
        "You spent 44,000", "how much", [{"result": {"total": 43000.0}}]
    ) == (False, [44000.0])
    assert numbers_ok(
        "Added 25,000 and 60,000",
        "add coffee 25000 and lunch 60000",
        [],
    ) == (True, [])
    assert numbers_ok(
        "about 1.2jt", "q", [{"result": {"total": 1234567}}]
    ) == (True, [])
    assert numbers_ok(
        "Logged -25,000", "q", [{"result": {"after": {"amount": "-25000"}}}]
    ) == (True, [])

    # Every scale word the parser knows is applied, not dropped as a small count.
    assert vals("Net worth 1.5B, or 1.5bn, or 2.3 thousand, or 1.2 mil.") == [
        1.5e9, 1.5e9, 2300.0, 1.2e6,
    ]
    assert vals("About 3 triliun, or 2.5 mio.") == [3e12, 2.5e6]
    # Unknown letters glued to a number fail the case instead of vanishing,
    # even when a trace leaf equals the bare mantissa.
    assert extract_numbers("Worth 4.3lakh") == [(4.3, _UNPLACEABLE)]
    assert numbers_ok("Worth 4.3lakh", "q", [{"result": {"total": 4.3}}]) == (False, [4.3])
    assert vals("On the 14th you paid 43000IDR.") == [43000.0]
    # A bare 1900-2100 integer is dropped as a year only after a year cue.
    assert vals("You spent 2000 on fees and Rp 2050 on admin.") == [2000.0, 2050.0]
    assert vals("In March 2024, since 2023, this year (2026): 43,000.") == [43000.0]
    assert vals("On March 14, 2024 you spent 43,000.") == [43000.0]
    # Scaled tolerance is capped at 5% of the value.
    assert numbers_ok("about 1jt", "q", [{"result": {"total": 1490000}}]) == (False, [1e6])
    assert numbers_ok("about 1jt", "q", [{"result": {"total": 1040000}}]) == (True, [])
    assert numbers_ok("about 2 billion", "q", [{"result": {"total": 1.6e9}}]) == (False, [2e9])

    # A step_args case matches answer figures only against the steps that
    # passed, so quoting a wrong-range sibling call's total fails.
    fake_case = {
        "id": 0, "question": "q", "tools": ["spending_total"],
        "step_args": lambda s: s["args"]["period"] == "this_year",
        "answer": "numbers", "needs_number": True,
    }
    right = {"tool": "spending_total", "args": {"period": "this_year"}, "result": {"total": 43000.0}}
    wrong = {"tool": "spending_total", "args": {"period": "all_time"}, "result": {"total": 134000.0}}
    assert _check_case(fake_case, {"text": "You spent 43,000", "trace": [right, wrong]})["passed"]
    assert not _check_case(fake_case, {"text": "You spent 134,000", "trace": [right, wrong]})["passed"]

    # Multi-turn helpers (pure): history markers and the calendar-month maths.
    assert _has_marker("[2026-10-11] You spent 5")
    assert _has_marker("You spent 5 [tools used: x()]")
    assert not _has_marker("You spent 5 on 2026-10-11")
    assert _month_before(datetime.date(2026, 3, 10), 2) == ("2026-01-01", "2026-01-31")
    assert _month_before(datetime.date(2026, 1, 20), 2) == ("2025-11-01", "2025-11-30")
    assert _stale_stamp(datetime.date(2026, 10, 11)) == datetime.date(2026, 8, 15)

    # Teardown contract: Ctrl-C mid-run, or a failure building the LLM
    # client, must still purge every proposal id collected so far. The DB
    # and LLM hooks are stubbed, so this stays offline.
    g = globals()
    saved = {k: g[k] for k in ("_check_db", "_seed", "_header_line", "_run_case", "_purge")}
    purged: list[list[str]] = []

    async def interrupted_case(question: str, proposal_ids: list[str], history=None) -> dict:
        proposal_ids.append("synthetic-proposal-id")
        raise KeyboardInterrupt

    def broken_header() -> str:
        raise RuntimeError("no LLM configured")

    try:
        g.update(
            _check_db=lambda: None, _seed=lambda: None, _header_line=lambda: "(stub header)",
            _run_case=interrupted_case, _purge=lambda ids: purged.append(list(ids)),
        )
        try:
            main([])
            raise AssertionError("KeyboardInterrupt was swallowed")
        except KeyboardInterrupt:
            pass
        assert purged == [["synthetic-proposal-id"]], purged

        purged.clear()
        g["_header_line"] = broken_header
        try:
            main([])
            raise AssertionError("header failure was swallowed")
        except RuntimeError:
            pass
        assert purged == [[]], purged
    finally:
        g.update(saved)

    assert "backend.db" not in sys.modules
    print("self-check OK")


# ---------------------------------------------------------------------------
# Seed data. Synthetic ZZEval-prefixed names so they never collide with real
# categories — "food"/"groceries" would, via migration 009's category tree.
# ---------------------------------------------------------------------------

MARKER = "ZZEval"
ACCOUNT = "ZZEval Wallet"
PARENT = "ZZEval Hobbies"
CHILD = "ZZEval Pottery"
UNKNOWN = "Yachts"
RECUR_CAT = "ZZEval Subscriptions"
RECUR_MERCHANT = "ZZEval Streaming"
TRANSFER_DECOY = "ZZEval Transfer Out"
LINKED_DECOY = "ZZEval Broker Topup"
EVAL_PLATFORM = "ZZEval Platform"
EVAL_TICKER = "ZZEVAL"
_EVAL_CATS = [PARENT, CHILD, RECUR_CAT]


def _seed_rows(today: datetime.date) -> list[tuple[datetime.date, int, str]]:
    """Four synthetic ZZEval child-category expenses, all under CHILD.
    Dates are computed from resolve_period so the relative-period
    cases are never empty regardless of when the eval runs; one fixed 2024-03
    row covers the absolute-range case. Amounts are plain integers
    that pass the pre-push MONEY/SHORTHAND regexes."""
    from backend.tools import resolve_period

    last_week_start, _ = resolve_period("last_week")
    last_month_start, _ = resolve_period("last_month")
    return [
        (today, -43000, "ZZEval Clay Supply"),
        (last_week_start + datetime.timedelta(days=2), -58000, "ZZEval Glaze Co"),
        (last_month_start + datetime.timedelta(days=9), -127000, "ZZEval Kiln Rental"),
        (datetime.date(2024, 3, 14), -91000, "ZZEval Studio Fee"),
    ]


def _recurring_seed_rows(
    today: datetime.date,
) -> list[tuple[datetime.date, int, str, bool, bool]]:
    """(date, amount, merchant, is_transfer, linked) for three monthly-cadence
    series of 5 rows each, at today - 30*k days. RECUR_MERCHANT is the
    largest amount so leftover monai_test groups cannot push it out of the
    default top-20 (sorted by monthly cost). The two decoys must NOT be
    detected: one by is_transfer, one only by its portfolio_events link."""
    rows: list[tuple[datetime.date, int, str, bool, bool]] = []
    for k in range(5):
        d = today - datetime.timedelta(days=30 * k)
        rows.append((d, -249000, RECUR_MERCHANT, False, False))
        rows.append((d, -88000, TRANSFER_DECOY, True, False))
        rows.append((d, -212000, LINKED_DECOY, False, True))
    return rows


def _seeded_sum_in(period_name: str) -> float:
    """Absolute sum of this run's seed rows dated inside resolve_period
    (period_name). Never a hardcoded total."""
    from backend.tools import resolve_period

    s, e = resolve_period(period_name)
    total = 0.0
    for d, amount, _m in _seed_rows(datetime.date.today()):
        if (s is None or d >= s) and (e is None or d < e):
            total += abs(amount)
    return total


# ---------------------------------------------------------------------------
# Fail-fast migrated-DB check. Mirrors conftest.py:88-124's alembic
# shadow workaround for the HEAD LOOKUP only — never its command.upgrade
# call. Creates and migrates nothing.
# ---------------------------------------------------------------------------


def _check_db() -> None:
    cached = sys.modules.get("alembic")
    if cached is None or not hasattr(cached, "op"):
        if cached is not None:
            del sys.modules["alembic"]
        shadow_init = (_REPO_ROOT / "alembic" / "__init__.py").resolve()
        original_path = list(sys.path)
        try:
            sys.path = [
                p for p in sys.path
                if (Path(p or ".") / "alembic" / "__init__.py").resolve() != shadow_init
            ]
            import alembic  # noqa: F401 — repopulates sys.modules["alembic"] correctly
        finally:
            sys.path = original_path

    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import text as sa_text
    from backend.db import engine

    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "alembic"))
    head_rev = ScriptDirectory.from_config(cfg).get_current_head()

    remediation = (
        "Run the backend suite once (env -u DATABASE_URL .venv/bin/pytest "
        f"backend/tests -q), or run `DATABASE_URL={_DEFAULT_TEST_URL} "
        "alembic upgrade head`. Always spell out DATABASE_URL — bare "
        "alembic defaults to the live DB."
    )
    try:
        with engine.connect() as conn:
            current_rev = conn.execute(sa_text("SELECT version_num FROM alembic_version")).scalar()
    except Exception as e:
        raise SystemExit(f"monai_test is missing or unreachable ({e}). {remediation}")
    if current_rev != head_rev:
        raise SystemExit(
            f"monai_test is at revision {current_rev!r}, head is {head_rev!r}. {remediation}"
        )


# ---------------------------------------------------------------------------
# Purge / seed / leftover-count. Exact eval-only names
# only — never a broader name-pattern sweep that could catch another test's
# leaked rows.
# ---------------------------------------------------------------------------


# Shared by _purge and _leftovers so the count covers exactly the rows the
# purge deletes.
_EVAL_TXN_WHERE = (
    "account_id IN (SELECT id FROM accounts WHERE name = :acct) "
    "OR category_id IN (SELECT id FROM categories WHERE name = ANY(:cats))"
)


def _purge(proposal_ids: list[str]) -> None:
    from sqlalchemy import text as sa_text
    from backend.db import engine

    with engine.begin() as c:
        # Events first: they reference platforms and eval transactions.
        c.execute(
            sa_text("DELETE FROM portfolio_events WHERE ticker = :tick"),
            {"tick": EVAL_TICKER},
        )
        c.execute(
            sa_text("DELETE FROM transactions WHERE " + _EVAL_TXN_WHERE),
            {"acct": ACCOUNT, "cats": _EVAL_CATS},
        )
        c.execute(
            sa_text("DELETE FROM platforms WHERE name = :name"), {"name": EVAL_PLATFORM}
        )
        # Child before parent — FK order.
        c.execute(sa_text("DELETE FROM categories WHERE name = :name"), {"name": CHILD})
        c.execute(sa_text("DELETE FROM categories WHERE name = :name"), {"name": PARENT})
        c.execute(sa_text("DELETE FROM categories WHERE name = :name"), {"name": RECUR_CAT})
        c.execute(sa_text("DELETE FROM accounts WHERE name = :name"), {"name": ACCOUNT})
        # Guard (research C6): the eval creates no threads (D-22a), but drop any
        # eval-titled one; messages cascade, proposals keep their rows.
        c.execute(sa_text("DELETE FROM threads WHERE title LIKE :tp"), {"tp": MARKER + "%"})
        # Exact ids only (pending, or flipped to expired by a lazy-expiry read).
        # A SIGKILL'd run's proposals are not swept
        # by the next run; they are inert (never confirmed) test-DB rows.
        c.execute(
            sa_text(
                "DELETE FROM proposals WHERE status IN ('pending', 'expired') AND "
                "id = ANY(CAST(:ids AS uuid[]))"
            ),
            {"ids": [pid for pid in proposal_ids if pid]},
        )


def _seed() -> None:
    """Purge any leftovers from a killed prior run (the seed names are
    unique), then commit the account/categories/four transactions in one
    transaction — agent tool calls open their own sessions, so a
    seed that's only rolled back would be invisible to them."""
    from sqlalchemy import text as sa_text
    from backend.db import engine

    _purge([])

    rows = _seed_rows(datetime.date.today())
    with engine.begin() as c:
        account_id = c.execute(
            sa_text(
                "INSERT INTO accounts (name, type, currency) "
                "VALUES (:name, 'liquid', 'IDR') RETURNING id"
            ),
            {"name": ACCOUNT},
        ).scalar()
        parent_id = c.execute(
            sa_text(
                "INSERT INTO categories (name, parent_id, kind, is_system) "
                "VALUES (:name, NULL, 'expense', false) RETURNING id"
            ),
            {"name": PARENT},
        ).scalar()
        child_id = c.execute(
            sa_text(
                "INSERT INTO categories (name, parent_id, kind, is_system) "
                "VALUES (:name, :pid, 'expense', false) RETURNING id"
            ),
            {"name": CHILD, "pid": parent_id},
        ).scalar()
        for d, amount, merchant in rows:
            c.execute(
                sa_text(
                    "INSERT INTO transactions "
                    "(date, amount, currency, category, category_id, merchant, account_id, is_transfer) "
                    "VALUES (:d, :amt, 'IDR', :cat, :cid, :m, :aid, false)"
                ),
                {"d": d, "amt": amount, "cat": CHILD, "cid": child_id, "m": merchant, "aid": account_id},
            )
        recur_id = c.execute(
            sa_text(
                "INSERT INTO categories (name, parent_id, kind, is_system) "
                "VALUES (:name, NULL, 'expense', false) RETURNING id"
            ),
            {"name": RECUR_CAT},
        ).scalar()
        platform_id = c.execute(
            sa_text(
                "INSERT INTO platforms (name, kind) VALUES (:n, 'test') "
                "ON CONFLICT (name) DO UPDATE SET kind = 'test' RETURNING id"
            ),
            {"n": EVAL_PLATFORM},
        ).scalar()
        for d, amount, merchant, is_transfer, linked in _recurring_seed_rows(datetime.date.today()):
            txn_id = c.execute(
                sa_text(
                    "INSERT INTO transactions "
                    "(date, amount, currency, category, category_id, merchant, account_id, is_transfer) "
                    "VALUES (:d, :amt, 'IDR', :cat, :cid, :m, :aid, :tr) RETURNING id"
                ),
                {"d": d, "amt": amount, "cat": RECUR_CAT, "cid": recur_id, "m": merchant,
                 "aid": account_id, "tr": is_transfer},
            ).scalar()
            if linked:
                # Raw SQL: no holdings recompute runs (recompute-clobbers hazard).
                c.execute(
                    sa_text(
                        "INSERT INTO portfolio_events "
                        "(date, ticker, event_type, quantity, price, platform_id, transaction_id) "
                        "VALUES (:d, :tick, 'buy', 1, 100000, :pid, :tid)"
                    ),
                    {"d": d, "tick": EVAL_TICKER, "pid": platform_id, "tid": txn_id},
                )


def _leftovers(proposal_ids: list[str]) -> int:
    from sqlalchemy import text as sa_text
    from backend.db import engine

    with engine.connect() as c:
        n = c.execute(
            sa_text(
                "SELECT "
                "(SELECT count(*) FROM accounts WHERE name = :acct) + "
                "(SELECT count(*) FROM categories WHERE name = ANY(:cats)) + "
                "(SELECT count(*) FROM transactions WHERE " + _EVAL_TXN_WHERE + ") + "
                "(SELECT count(*) FROM portfolio_events WHERE ticker = :tick) + "
                "(SELECT count(*) FROM platforms WHERE name = :plat) + "
                "(SELECT count(*) FROM threads WHERE title LIKE :tp) + "
                "(SELECT count(*) FROM proposals WHERE status IN ('pending', 'expired') AND "
                "id = ANY(CAST(:ids AS uuid[])))"
            ),
            {"acct": ACCOUNT, "cats": _EVAL_CATS, "tick": EVAL_TICKER, "plat": EVAL_PLATFORM,
             "tp": MARKER + "%", "ids": [pid for pid in proposal_ids if pid]},
        ).scalar()
    return int(n or 0)


# ---------------------------------------------------------------------------
# Probes — no LLM. Prove the subtree, case-insensitive,
# unknown-category and period data paths the 20 cases rely on, plus the
# Phase 38 subset (P11) and summary-aware history (P12) wiring.
# ---------------------------------------------------------------------------

_PROBE_COUNT = 12


def _run_probes() -> list[str]:
    from backend.tools import (
        spending_in_category, find_transactions, spending_total, net_worth_tool,
        recurring_charges, compare_periods,
    )

    failures: list[str] = []

    p1 = spending_in_category(PARENT, period="this_year")
    expected_p1 = _seeded_sum_in("this_year")
    if not (p1.get("total", 0) > 0 and p1.get("total", 0) >= expected_p1 - 1e-6):
        failures.append(f"P1: spending_in_category(PARENT, this_year) = {p1!r}")

    p2 = spending_in_category(PARENT.lower(), period="this_year")
    if p2.get("total") != p1.get("total"):
        failures.append(f"P2: spending_in_category(parent.lower()) = {p2!r} != P1 {p1!r}")

    p3 = spending_in_category(UNKNOWN, period="this_year")
    if "error" not in p3:
        failures.append(f"P3: spending_in_category(UNKNOWN) did not error: {p3!r}")

    p4 = find_transactions(category=PARENT)
    if not (p4.get("rows") and p4["rows"][0]["category"] == CHILD):
        failures.append(f"P4: find_transactions(category=PARENT) rows[0] = {p4!r}")

    for period_name in ("this_month", "last_month", "last_week"):
        res = spending_total(period_name)
        expected = _seeded_sum_in(period_name)
        if not (res.get("total", 0) > 0 and res.get("total", 0) >= expected - 1e-6):
            failures.append(f"P5: spending_total({period_name}) = {res!r}, expected >= {expected}")
    march = spending_total("custom", start_date="2024-03-01", end_date="2024-03-31")
    if not (march.get("total", 0) >= 91000 - 1e-6):
        failures.append(f"P5: spending_total(custom, 2024-03) = {march!r}")

    p6 = net_worth_tool()
    if not (isinstance(p6, dict) and isinstance(p6.get("total"), (int, float))):
        failures.append(f"P6: net_worth_tool() total = {p6!r}")

    # P7: case 5's check rejects the cross-step false pass (an all_time total
    # quoted while a different step carries the this_year range) and accepts
    # the honest single-step answer.
    case5 = next(c for c in CASES if c["id"] == 5)
    all_time = {"tool": "spending_in_category", "args": {"category": PARENT},
                "result": spending_in_category(PARENT)}
    pottery = {"tool": "find_transactions", "args": {"category": CHILD, "period": "this_year"},
               "result": find_transactions(category=CHILD, period="this_year")}
    honest = {"tool": "spending_in_category", "args": {"category": PARENT, "period": "this_year"},
              "result": p1}
    bad = _check_case(case5, {"text": f"You spent {all_time['result']['total']:,.0f}.",
                              "trace": [all_time, pottery]})
    good = _check_case(case5, {"text": f"You spent {p1['total']:,.0f}.", "trace": [honest]})
    if bad["passed"] or not good["passed"]:
        failures.append(f"P7: case-5 check cross-step passed={bad['passed']}, honest passed={good['passed']}")

    # P8: recurring_charges finds the seeded monthly series, neither decoy, and
    # case 13's check accepts the honest step and rejects a decoy-tainted one.
    rc = recurring_charges()
    labels = [str(g.get("label", "")).lower() for g in rc.get("groups", [])]
    mine = [g for g in rc.get("groups", []) if str(g.get("label", "")).lower() == RECUR_MERCHANT.lower()]
    if not (mine and mine[0].get("cadence") == "monthly" and mine[0].get("status") == "active"
            and TRANSFER_DECOY.lower() not in labels and LINKED_DECOY.lower() not in labels):
        failures.append(f"P8: recurring_charges() labels={labels!r}, match={mine!r}")
    case13 = next(c for c in CASES if c["id"] == 13)
    honest13 = {"tool": "recurring_charges", "args": {}, "result": rc}
    tainted = {**rc, "groups": [*rc.get("groups", []), {"label": LINKED_DECOY}]}
    bad13 = {"tool": "recurring_charges", "args": {}, "result": tainted}
    if not case13["step_args"](honest13) or case13["step_args"](bad13):
        failures.append(
            f"P8: case-13 check honest={case13['step_args'](honest13)}, "
            f"decoy-tainted={case13['step_args'](bad13)}"
        )

    # P9: compare_periods totals agree with spending_total, and case 14's check
    # is order-insensitive but rejects the wrong pair.
    cp = compare_periods("last_month", "this_month")
    if "error" in cp:
        failures.append(f"P9: compare_periods error: {cp!r}")
    else:
        sp = cp["totals"]["spending"]
        if sp["current"] != spending_total("this_month")["total"] or sp["base"] != spending_total("last_month")["total"]:
            failures.append(f"P9: compare_periods totals {sp!r} != spending_total")
    case14 = next(c for c in CASES if c["id"] == 14)
    ok_args = [{"period_a": "last_month", "period_b": "this_month"},
               {"period_a": "this_month", "period_b": "last_month"}]
    bad_args = {"period_a": "last_month", "period_b": "last_month"}
    got = [case14["step_args"]({"tool": "compare_periods", "args": a, "result": cp}) for a in ok_args]
    got_bad = case14["step_args"]({"tool": "compare_periods", "args": bad_args, "result": cp})
    if not all(got) or got_bad:
        failures.append(f"P9: case-14 check ok={got}, wrong-pair={got_bad}")

    # P10: history wiring and the multi-turn checks, positive and negative.
    from backend import config
    from backend.chat_history import EARLIER_DATES_NOTE, build_history

    today = _query_today()
    h = build_history(_stale_history(today), config.CHAT_HISTORY_TOKEN_BUDGET, today)
    stamp = "[" + _stale_stamp(today).isoformat() + "]"
    if not (
        len(h) == 2
        and stamp in h[0].content and EARLIER_DATES_NOTE in h[0].content
        and h[1].content.splitlines()[-1].startswith("[tools used: spending_in_category(")
    ):
        failures.append(f"P10: stale history did not build as expected: {[m.content for m in h]!r}")
    else:
        case15, case16, case17 = (next(c for c in CASES if c["id"] == i) for i in (15, 16, 17))

        def sic(**args):
            return {"tool": "spending_in_category", "args": {"category": PARENT, **args}, "result": {}}

        s, e = _month_before(_stale_stamp(today), 2)
        cmp_ok = {"tool": "compare_periods", "result": {"totals": {}},
                  "args": {"period_a": "last_month", "period_b": "this_month"}}
        cmp_bad = {**cmp_ok, "args": {"period_a": "last_month", "period_b": "last_month"}}
        checks = [
            ("case 17 expected month", case17["step_args"](sic(period="custom", start_date=s, end_date=e)), True),
            ("case 17 last_month", case17["step_args"](sic(period="last_month")), False),
            ("case 15 this_month", case15["step_args"](sic(period="this_month")), True),
            ("case 15 last_month", case15["step_args"](sic(period="last_month")), False),
            ("case 16 last/this pair", case16["step_args"](cmp_ok), True),
            ("case 16 last/last pair", case16["step_args"](cmp_bad), False),
        ]
        for name, got_p10, want in checks:
            if got_p10 is not want:
                failures.append(f"P10: {name} returned {got_p10}, expected {want}")
                break

    # P11: per-turn tool subset (D-02, D-04a), no LLM.
    from backend.agent_loop import tools_for_turn
    from backend.tools import READ_TOOL_NAMES, TOOLS

    q18, q19, q12 = (next(c for c in CASES if c["id"] == i)["question"] for i in (18, 19, 12))
    sub18 = tools_for_turn(q18)
    if sub18 != READ_TOOL_NAMES or any(n.startswith("propose_") for n in sub18):
        failures.append("P11: case 18 question did not get the read-only subset")
    if tools_for_turn(q12) != frozenset(TOOLS) or tools_for_turn(q19) != frozenset(TOOLS):
        failures.append("P11: case 12/19 questions did not get every tool")
    offered = _turn_messages("Add a coffee", {"text": "Proposed.", "trace": []}, datetime.datetime.now().astimezone())
    offered[1]["parts"]["proposals"] = [{"id": "x"}]
    if tools_for_turn("yes, do that", offered) != frozenset(TOOLS):
        failures.append("P11: sticky write intent after a proposal did not keep every tool")

    # P12: summary-aware, budget-trimmed history (D-20, D-30), no LLM.
    from backend.chat_history import plan_history

    long_h = _long_history(today)
    hist, to_compact = plan_history(
        long_h, config.CHAT_HISTORY_TOKEN_BUDGET, today, summary=LONG_SUMMARY)
    if not hist or not hist[0].content.startswith("Summary of earlier conversation"):
        failures.append("P12: summary did not lead the planned history")
    if len(hist) - 1 >= len(long_h):
        failures.append(f"P12: long thread was not budget-trimmed ({len(hist) - 1} of {len(long_h)} messages kept)")
    if not to_compact:
        failures.append("P12: trimmed long thread returned nothing to compact")
    if re.search(r"\d", LONG_SUMMARY):
        failures.append("P12: LONG_SUMMARY holds a digit")

    return failures


def _do_seed_check() -> int:
    _check_db()
    try:
        _seed()
        failures = _run_probes()
    finally:
        _purge([])
    n_left = _leftovers([])
    if n_left > 0:
        print(f"teardown left {n_left} eval rows")
    else:
        print("teardown: 0 eval rows left")
    if failures:
        for f in failures:
            print(f"PROBE FAILED: {f}")
        return 1
    if n_left > 0:
        return 1
    print(f"seed-check OK ({len(CASES)} cases, {_PROBE_COUNT} probes)")
    return 0


# ---------------------------------------------------------------------------
# The 20 golden cases.
# ---------------------------------------------------------------------------


def _period_range(period: str, start: str | None = None, end: str | None = None):
    from backend.tools import resolve_period

    return resolve_period(period, start, end)


def _resolved_args(step: dict):
    args = step.get("args") or {}
    try:
        return _period_range(args.get("period", "all_time"), args.get("start_date"), args.get("end_date"))
    except (ValueError, TypeError):
        return (None, "PARSE-ERROR")


def _resolved_pair(step: dict):
    """Two-sided resolver for compare_periods: the set of resolved ranges for
    the a_/b_ sides (order-insensitive, D-11), or None if either side fails."""
    args = step.get("args") or {}
    try:
        return {
            _period_range(args.get("period_a", "all_time"), args.get("a_start_date"), args.get("a_end_date")),
            _period_range(args.get("period_b", "all_time"), args.get("b_start_date"), args.get("b_end_date")),
        }
    except (ValueError, TypeError):
        return None


def _recurring_step(step: dict) -> bool:
    r = step.get("result")
    if not isinstance(r, dict):
        return False
    labels = [str(g.get("label", "")).lower() for g in r.get("groups") or []]
    return (
        RECUR_MERCHANT.lower() in labels
        and TRANSFER_DECOY.lower() not in labels
        and LINKED_DECOY.lower() not in labels
    )


def _compare_step(step: dict) -> bool:
    r = step.get("result")
    return (
        isinstance(r, dict) and "error" not in r
        and _resolved_pair(step) == {_period_range("last_month"), _period_range("this_month")}
    )


def _steps_for(trace: list, tool_names: list[str]) -> list[dict]:
    return [s for s in trace if s.get("tool") in tool_names]


def _category_arg_matches(step: dict, expected_lower: str) -> bool:
    return ((step.get("args") or {}).get("category") or "").strip().lower() == expected_lower


# Per-step args checks ("step_args"): each takes ONE step of the case's
# tools and every condition must hold on that same step. _check_case also
# matches answer figures only against the steps that pass, so a sibling call
# with the wrong range can't supply the quoted number.


def _range_is(period_name: str):
    return lambda step: _resolved_args(step) == _period_range(period_name)


def _custom_march_step(step: dict) -> bool:
    return (
        (step.get("args") or {}).get("period") == "custom"
        and _resolved_args(step) == _period_range("custom", "2024-03-01", "2024-03-31")
    )


def _hobbies_step(step: dict) -> bool:
    """Category PARENT and range this_year on this step, plus either a total
    exactly equal to the seeded this_year child sum or rows that are all
    CHILD. An all_time total (which includes the 2024 row) fails."""
    if not (
        _category_arg_matches(step, PARENT.lower())
        and _resolved_args(step) == _period_range("this_year")
    ):
        return False
    r = step.get("result") if isinstance(step.get("result"), dict) else {}
    if isinstance(r.get("total"), (int, float)):
        return abs(r["total"] - _seeded_sum_in("this_year")) < 1e-6
    rows = r.get("rows")
    return bool(rows) and all(row.get("category") == CHILD for row in rows)


def _unknown_category_step(step: dict) -> bool:
    return (
        "yacht" in ((step.get("args") or {}).get("category") or "").lower()
        and isinstance(step.get("result"), dict) and "error" in step["result"]
    )


def _last_in_hobbies_step(step: dict) -> bool:
    r = step.get("result")
    return (
        _category_arg_matches(step, PARENT.lower())
        and isinstance(r, dict) and bool(r.get("rows"))
        and r["rows"][0].get("category") == CHILD
    )


def _args_two_proposals(trace, payload):
    steps = _steps_for(trace, ["propose_add_transaction"])
    if len(steps) != 2:
        return False
    try:
        amounts = {abs(float((s.get("args") or {}).get("amount"))) for s in steps}
    except (TypeError, ValueError):
        return False
    if amounts != {25000.0, 60000.0}:
        return False
    return len(payload.get("proposals") or []) == 2


def _answer_has_parent_name(text: str) -> bool:
    return PARENT.lower() in text.lower()


def _hobbies_range_step(period_name: str):
    """Check: category PARENT (ci) and the step's range == the named period."""
    return lambda step: (
        _category_arg_matches(step, PARENT.lower())
        and _resolved_args(step) == _period_range(period_name)
    )


def _carried_step(step: dict) -> bool:
    """Case 16: the final turn re-queries itself: a clean compare_periods over
    {last_month, this_month}, or a PARENT query over either of those months."""
    r = step.get("result")
    if step.get("tool") == "compare_periods":
        return (
            isinstance(r, dict) and "error" not in r
            and _resolved_pair(step) == {_period_range("last_month"), _period_range("this_month")}
        )
    return _category_arg_matches(step, PARENT.lower()) and _resolved_args(step) in (
        _period_range("last_month"), _period_range("this_month"),
    )


def _month_before(d: datetime.date, k: int) -> tuple[str, str]:
    """(first_day, last_day) ISO strings of the calendar month k months before d's."""
    idx = d.year * 12 + d.month - 1 - k
    y, m = divmod(idx, 12)
    m += 1
    return f"{y:04d}-{m:02d}-01", f"{y:04d}-{m:02d}-{calendar.monthrange(y, m)[1]:02d}"


def _stale_stamp(today: datetime.date) -> datetime.date:
    """The 15th of the month two months before today: the stale history date."""
    return datetime.date.fromisoformat(_month_before(today, 2)[0]).replace(day=15)


def _query_today() -> datetime.date:
    from backend.query import _today

    return _today()


def _stale_step(step: dict) -> bool:
    """Case 17: PARENT over the calendar month two months before the stamped
    history date. The stamped turn asked 'last month' (stamp month - 1), so
    'the month before that' is stamp month - 2."""
    return (
        _category_arg_matches(step, PARENT.lower())
        and _resolved_args(step)
        == _period_range("custom", *_month_before(_stale_stamp(_query_today()), 2))
    )


def _stale_history(today: datetime.date) -> list[dict]:
    """Synthetic prior turn stamped _stale_stamp(today). 4321 is deliberately
    absent from every seed, so copying it into an answer fails numbers_ok."""
    at = datetime.datetime.combine(_stale_stamp(today), datetime.time(10, 0)).astimezone()
    return [
        {"role": "user", "content": "How much did I spend on ZZEval Hobbies last month?",
         "status": "complete", "parts": None, "created_at": at},
        {"role": "assistant", "content": "You spent 4321 on ZZEval Hobbies last month.",
         "status": "complete",
         "parts": {"steps": [{"tool": "spending_in_category",
                              "args": {"category": PARENT, "period": "last_month"}}]},
         "created_at": at},
    ]


def _args_two_ordered(trace, payload):
    """Case 19: exactly one add_account and one rename_category proposal, no
    other propose_* step, two distinct ids, operations in the stated order."""
    proposes = [s for s in trace if str(s.get("tool", "")).startswith("propose_")]
    if sorted(s["tool"] for s in proposes) != ["propose_add_account", "propose_rename_category"]:
        return False
    proposals = payload.get("proposals") or []
    return (
        len(proposals) == 2
        and len({p.get("id") for p in proposals}) == 2
        and [p.get("operation") for p in proposals] == ["add_account", "rename_category"]
    )


LONG_SUMMARY = (
    "The owner asked several times about ZZEval Hobbies spending by month and about "
    "ZZEval Streaming charges; no changes were proposed."
)


def _long_history(today: datetime.date) -> list[dict]:
    """30 synthetic pairs stamped earlier today, long enough to overflow the
    history budget. 7777 is deliberately absent from every seed, so copying it
    into an answer fails numbers_ok."""
    at = datetime.datetime.combine(today, datetime.time(0, 5)).astimezone()
    out: list[dict] = []
    for i in range(30):
        topic = PARENT if i % 2 == 0 else "ZZEval Streaming"
        out.append({"role": "user", "status": "complete", "parts": None, "created_at": at,
                    "content": f"Question {i}: " + f"what did I spend on {topic} in the earlier months? " * 4})
        out.append({"role": "assistant", "status": "complete", "created_at": at,
                    "content": f"Answer {i}: " + f"you spent 7777 on {topic} in that period. " * 11,
                    "parts": {"steps": [{"tool": "spending_in_category",
                                         "args": {"category": PARENT, "period": "last_month"}}]}})
    return out


CASES: list[dict] = [
    {
        "id": 1, "question": "How much did I spend this month?",
        "tools": ["spending_total"], "step_args": _range_is("this_month"),
        "args_desc": "period range == this_month",
        "answer": "numbers", "needs_number": True,
    },
    {
        "id": 2, "question": "How much did I spend last month?",
        "tools": ["spending_total"], "step_args": _range_is("last_month"),
        "args_desc": "period range == last_month",
        "answer": "numbers", "needs_number": True,
    },
    {
        "id": 3, "question": "How much did I spend between 2024-03-01 and 2024-03-31?",
        "tools": ["spending_total"], "step_args": _custom_march_step,
        "args_desc": "period == 'custom' and range == resolve_period('custom', '2024-03-01', '2024-03-31')",
        "answer": "numbers", "needs_number": True,
    },
    {
        "id": 4, "question": "How much did I spend last week?",
        "tools": ["spending_total"], "step_args": _range_is("last_week"),
        "args_desc": "range == resolve_period('last_week') computed at run time",
        "answer": "numbers", "needs_number": True,
    },
    {
        "id": 5, "question": "How much did I spend on ZZEval Hobbies this year?",
        "tools": ["spending_in_category", "find_transactions"], "step_args": _hobbies_step,
        "args_desc": "one step: category (ci) == PARENT, range == this_year, and total == seeded this_year child sum (or every row is CHILD)",
        "answer": "numbers", "needs_number": True,
    },
    {
        "id": 6, "question": "how much did i spend on zzeval hobbies this year",
        "tools": ["spending_in_category", "find_transactions"], "step_args": _hobbies_step,
        "args_desc": "same as case 5",
        "answer": "numbers", "needs_number": True,
    },
    {
        "id": 7, "question": "How much did I spend on Yachts this year?",
        "tools": ["spending_in_category", "find_transactions"], "step_args": _unknown_category_step,
        "args_desc": "category contains 'yacht' (ci) and that step's result has an 'error' key",
        "answer": "numbers", "needs_number": False,
    },
    {
        "id": 8, "question": "What's my net worth right now?",
        "tools": ["net_worth"], "args": None, "args_desc": "n/a",
        "answer": "numbers", "needs_number": True,
    },
    {
        "id": 9, "question": "What categories do I have?",
        "tools": ["list_categories"], "args": None, "args_desc": "n/a",
        "answer": _answer_has_parent_name, "needs_number": False,
    },
    {
        "id": 10, "question": "What was my biggest expense last month?",
        "tools": ["largest_transactions"], "step_args": _range_is("last_month"),
        "args_desc": "range == last_month",
        "answer": "numbers", "needs_number": True,
    },
    {
        "id": 11, "question": "Show my last transaction in ZZEval Hobbies.",
        "tools": ["find_transactions"], "step_args": _last_in_hobbies_step,
        "args_desc": "category (ci) == PARENT and result rows[0].category == CHILD",
        "answer": "numbers", "needs_number": True,
    },
    {
        "id": 12, "question": "Add coffee 25000 and lunch 60000 to my ZZEval Wallet account.",
        "tools": ["propose_add_transaction"], "args": _args_two_proposals,
        "args_desc": "exactly 2 propose_add_transaction steps, amounts {25000, 60000}, 2 proposals",
        "answer": "numbers", "needs_number": False,
    },
    {
        "id": 13, "question": "What are my recurring charges?",
        "tools": ["recurring_charges"], "step_args": _recurring_step,
        "args_desc": "a recurring_charges step whose groups include ZZEval Streaming and neither decoy",
        "answer": "numbers", "needs_number": True,
    },
    {
        "id": 14, "question": "Compare my spending last month against this month",
        "tools": ["compare_periods"], "step_args": _compare_step,
        "args_desc": "a compare_periods step whose two resolved ranges == {last_month, this_month} (either order), no error",
        "answer": "numbers", "needs_number": True,
    },
    # Cases 15-17 are multi-turn: "turns" are the questions in order (the last
    # is graded), "history" optionally seeds synthetic prior messages.
    {
        "id": 15,
        "turns": ["How much did I spend on ZZEval Hobbies last month?", "and this month?"],
        "question": "and this month?",
        "tools": ["spending_in_category", "find_transactions"],
        "step_args": _hobbies_range_step("this_month"),
        "args_desc": "final turn: category (ci) == PARENT and range == this_month",
        "answer": "numbers", "needs_number": True,
    },
    {
        "id": 16,
        "turns": [
            "How much did I spend on ZZEval Hobbies last month?",
            "and this month?",
            "What's the difference between those two?",
        ],
        "question": "What's the difference between those two?",
        "tools": ["compare_periods", "spending_in_category", "find_transactions"],
        "step_args": _carried_step,
        "args_desc": "final turn makes its own compare_periods {last_month, this_month} or PARENT re-query; numbers only from this turn's trace",
        "answer": "numbers", "needs_number": True,
    },
    {
        "id": 17,
        "history": _stale_history,
        "turns": ["and the month before that?"],
        "question": "and the month before that?",
        "tools": ["spending_in_category", "find_transactions"],
        "step_args": _stale_step,
        "args_desc": "range == the calendar month two months before the stamped history date; category PARENT",
        # A zero month may be phrased without digits, so the args check carries
        # this case; any stated figure must still come from this turn's trace.
        "answer": "numbers", "needs_number": False,
    },
    # Cases 18-20 cover Phase 38: tool subset, ordered two-write, long summarised thread.
    {
        "id": 18, "question": "How much did I spend on ZZEval Hobbies last month?",
        "tools": ["spending_in_category", "find_transactions"],
        "step_args": _hobbies_range_step("last_month"), "no_writes": True,
        "args_desc": "PARENT over last_month; trace has no propose_* step (subset)",
        "answer": "numbers", "needs_number": True,
    },
    {
        "id": 19,
        "question": "Add an account named ZZEval Savings and rename the category ZZEval Pottery to ZZEval Ceramics.",
        "tools": ["propose_add_account", "propose_rename_category"], "args": _args_two_ordered,
        "args_desc": "exactly 2 proposals, distinct ids, operations [add_account, rename_category] in order",
        # The answer must describe the changes, not reply to the tail reminder
        # ("Understood. I will ensure...", seen live on 2026-10-18 with a user-role reminder).
        "answer": lambda text: "zzeval savings" in text.lower(), "needs_number": False,
    },
    {
        "id": 20,
        "history": _long_history, "summary": LONG_SUMMARY,
        "turns": ["How much did I spend on ZZEval Hobbies this month?"],
        "question": "How much did I spend on ZZEval Hobbies this month?",
        "tools": ["spending_in_category", "find_transactions"],
        "step_args": _hobbies_range_step("this_month"),
        "args_desc": "long budget-trimmed thread with a summary; this_month PARENT re-query; no figure from history",
        "answer": "numbers", "needs_number": True,
    },
]


# ---------------------------------------------------------------------------
# Runner — drives the real agent_stream loop.
# ---------------------------------------------------------------------------


async def _run_case(question: str, proposal_ids: list[str], history=None, prior=None) -> dict:
    """Drive agent_stream once and return the answer payload. Every proposal
    id is appended to the caller-owned `proposal_ids` the moment its
    tool_result arrives (not just from the final answer's proposals list),
    so the caller's `finally` still purges it if the run crashes or is
    interrupted mid-stream. `history` is the replayed prior turns of a
    multi-turn case (None for the single-turn cases); `prior` is its message
    dicts, which with the question pick the turn's tool subset like chat does."""
    from backend.agent_loop import tools_for_turn
    from backend.query import agent_stream

    answer: dict = {"text": "", "trace": [], "proposals": []}
    async for line in agent_stream(
        question, history=history, tool_names=tools_for_turn(question, prior)
    ):
        if not line.startswith("data: "):
            continue
        raw = line[len("data: "):].strip()
        if raw == "[DONE]":
            break
        payload = json.loads(raw)
        if payload.get("type") == "tool_result":
            result = (payload.get("step") or {}).get("result")
            if isinstance(result, dict) and result.get("proposal_id"):
                proposal_ids.append(result["proposal_id"])
        elif payload.get("type") == "answer":
            answer = payload
        elif payload.get("type") == "error":
            # Typed stream error (Phase 34): a failed case, not an empty answer.
            # Keep its proposals so the purge loop below still removes them.
            answer = {"text": "", "trace": [], "proposals": payload.get("proposals") or [],
                      "error": payload.get("code")}
    for p in answer.get("proposals") or []:
        if p.get("id"):
            proposal_ids.append(p["id"])
    return answer


def _turn_messages(question: str, result: dict, at: datetime.datetime) -> list[dict]:
    """One finished turn as two build_history message dicts (in memory only)."""
    steps = [{"tool": s.get("tool"), "args": s.get("args") or {}} for s in result.get("trace") or []]
    return [
        {"role": "user", "content": question, "status": "complete", "parts": None, "created_at": at},
        {"role": "assistant", "content": result.get("text") or "",
         "status": "error" if result.get("error") else "complete",
         "parts": {"steps": steps}, "created_at": at},
    ]


async def _run_multi_case(case: dict, proposal_ids: list[str]) -> dict:
    """Run a multi-turn case through the real history builder, in memory only
    (D-22a: no threads or messages rows). Earlier turns are replayed via
    plan_history before every turn; the returned result is the final turn's,
    with `prior_error` set to the first earlier turn's error code, if any."""
    from backend import config
    from backend.chat_history import plan_history
    from backend.query import _today

    today = _today()
    messages = case["history"](today) if "history" in case else []
    prior_error = None
    turns = case["turns"]
    def plan():
        return plan_history(
            messages, config.CHAT_HISTORY_TOKEN_BUDGET, today,
            summary=case.get("summary"), upto_seq=case.get("upto_seq", 0),
        )[0]

    for turn in turns[:-1]:
        result = await _run_case(turn, proposal_ids, history=plan(), prior=messages)
        prior_error = prior_error or result.get("error")
        messages.extend(_turn_messages(turn, result, datetime.datetime.now().astimezone()))
    final = await _run_case(turns[-1], proposal_ids, history=plan(), prior=messages)
    return {**final, "prior_error": prior_error}


_MARKER_RE = re.compile(r"\[\d{4}-\d{2}-\d{2}\]")


def _has_marker(text: str) -> bool:
    """True when an answer echoes history scaffolding: '[tools used:' or a
    bracketed '[YYYY-MM-DD]' stamp (Pitfall 5)."""
    return "[tools used:" in text or bool(_MARKER_RE.search(text))


def _has_number(text: str) -> bool:
    return len(extract_numbers(text)) > 0


def _check_case(case: dict, result: dict) -> dict:
    trace = (result or {}).get("trace") or []
    answer_text = (result or {}).get("text") or ""

    steps = _steps_for(trace, case["tools"])
    tool_ok = len(steps) > 0

    step_args = case.get("step_args")
    trace_args = case.get("args")
    args_na = step_args is None and trace_args is None
    number_trace = trace
    if step_args is not None:
        # Answer figures may only come from the steps that passed the args
        # check, never from a sibling call with the wrong range/category.
        number_trace = [s for s in steps if step_args(s)]
        args_ok = bool(number_trace)
    elif args_na:
        args_ok = True
    elif not tool_ok:
        args_ok = False
    else:
        args_ok = bool(trace_args(trace, result or {}))

    numbers_na = not isinstance(case["answer"], str)
    if case["answer"] == "numbers":
        ok, unmatched = numbers_ok(answer_text, case["question"], number_trace)
    else:
        ok, unmatched = bool(case["answer"](answer_text)), []

    needs_number_failed = bool(case.get("needs_number")) and not _has_number(answer_text)
    if needs_number_failed:
        ok = False

    if case.get("no_writes") and any(str(s.get("tool", "")).startswith("propose_") for s in trace):
        args_ok = False

    error = (result or {}).get("error")
    passed = tool_ok and args_ok and ok and not error
    return {
        "id": case["id"], "question": case["question"],
        "tool_ok": tool_ok, "args_ok": args_ok, "args_na": args_na,
        "numbers_ok": ok, "numbers_na": numbers_na,
        "passed": passed, "unmatched": unmatched,
        "needs_number_failed": needs_number_failed,
        "trace": trace, "text": answer_text, "error": error,
    }


async def _run_all_cases(selected: list[dict], proposal_ids: list[str]) -> list[dict]:
    results = []
    for case in selected:
        if "turns" in case:
            result = await _run_multi_case(case, proposal_ids)
            r = _check_case(case, result)
            r["prior_error"] = result.get("prior_error")
            r["marker"] = _has_marker(r["text"])
            r["passed"] = r["passed"] and not r["prior_error"] and not r["marker"]
        else:
            r = _check_case(case, await _run_case(case["question"], proposal_ids))
        results.append(r)
    return results


def _header_line() -> str:
    from backend.query import _get_llm

    provider = os.environ.get("LLM_PROVIDER") or "ollama"
    model = getattr(_get_llm(), "model", "?")
    db = make_url(os.environ["DATABASE_URL"]).database
    return f"provider={provider} model={model} db={db}"


# ---------------------------------------------------------------------------
# Output — plain-text table + failing-case detail blocks. No results
# file, no JSON mode.
# ---------------------------------------------------------------------------


def _mark(value: bool, na: bool = False) -> str:
    if na:
        return "–"
    return "✓" if value else "✗"


def _print_table(results: list[dict]) -> None:
    print(f"{'id':<3} {'question':<40} {'tool':<5} {'args':<5} {'numbers':<8} {'result'}")
    for r in results:
        q = r["question"][:40]
        print(
            f"{r['id']:<3} {q:<40} {_mark(r['tool_ok']):<5} "
            f"{_mark(r['args_ok'], r['args_na']):<5} {_mark(r['numbers_ok'], r['numbers_na']):<8} "
            f"{'PASS' if r['passed'] else 'FAIL'}"
        )


def _print_detail(case: dict, r: dict) -> None:
    print(f"--- Case {r['id']} FAILED: {r['question']} ---")
    print(f"  expected tools: {case['tools']}")
    print(f"  expected args: {case.get('args_desc', 'n/a')}")
    if not r["trace"]:
        print("  trace: (empty)")
    for s in r["trace"]:
        print(f"  trace step: tool={s.get('tool')} args={json.dumps(s.get('args'), default=str)}")
    if r.get("error"):
        print(f"  stream error: {r['error']}")
    if r.get("prior_error"):
        print(f"  prior turn error: {r['prior_error']}")
    if r.get("marker"):
        print("  answer echoes a history marker")
    if r["unmatched"]:
        print(f"  unmatched numbers: {r['unmatched']}")
    if r["needs_number_failed"]:
        print("  missing-number: case needs a figure in the answer but none survived extraction")
    print(f"  answer text (first 300 chars): {r['text'][:300]!r}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m backend.evals.agent_eval",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="run the answer-number parser's asserts only (no DB, no LLM)",
    )
    parser.add_argument(
        "--seed-check",
        action="store_true",
        help="run the DB guard, head check, seed, probes and teardown (no LLM)",
    )
    parser.add_argument(
        "--case",
        action="append",
        type=int,
        default=None,
        help="run only this case id (repeatable). Default: run all 20 cases.",
    )
    args = parser.parse_args(argv)

    if args.self_check:
        _self_check()
        return 0

    if args.seed_check:
        return _do_seed_check()

    valid_ids = {c["id"] for c in CASES}
    if args.case:
        bad = [i for i in args.case if i not in valid_ids]
        if bad:
            parser.error(f"unknown case id(s): {bad}")
        selected = [c for c in CASES if c["id"] in args.case]
    else:
        selected = CASES

    # Caller-owned and mutated in place, so the finally sees every id
    # collected before a crash or Ctrl-C. Seeding and the header (which
    # builds the LLM client) sit inside the try so their failures purge too.
    proposal_ids: list[str] = []
    _check_db()
    try:
        _seed()
        print(_header_line())
        results = asyncio.run(_run_all_cases(selected, proposal_ids))
    finally:
        _purge(proposal_ids)

    _print_table(results)
    passed = sum(1 for r in results if r["passed"])
    print(f"RESULT: {passed}/{len(selected)} passed")
    for case, r in zip(selected, results):
        if not r["passed"]:
            _print_detail(case, r)

    n_left = _leftovers(proposal_ids)
    if n_left > 0:
        print(f"teardown left {n_left} eval rows")
        return 1
    print("teardown: 0 eval rows left")
    return 0 if passed == len(selected) else 1


if __name__ == "__main__":
    raise SystemExit(main())
