"""
Opt-in golden-question eval for the production agent loop (EVAL-01).

What this is: a standalone script, NOT a pytest test and NOT collected by
default pytest or CI (backend/evals/ sits outside pyproject.toml's
testpaths). It sends ~12 scripted questions through backend.query.agent_stream
— the real, production agent loop — driven by whatever real LLM is
configured via LLM_PROVIDER / the matching model env var. It runs only
against monai_test, never the live monai database; a module-top guard
refuses to proceed otherwise, before any backend import.

It seeds its own synthetic ZZEval rows (one account, a parent+child category
pair, four transactions) before running, and removes every ZZEval row and
every pending proposal it created afterwards, in a `finally` block that
also runs on Ctrl-C. It never approves a proposal.

Usage:
    env -u DATABASE_URL .venv/bin/python -m backend.evals.agent_eval \
        [--self-check] [--seed-check] [--case N ...]

    --self-check   run the answer-number parser's asserts only. No DB, no LLM.
    --seed-check   run the DB guard, head check, seed, probes and teardown.
                   No LLM.
    --case N       run only case N (repeatable). Default: run all 12 cases.

Exit code 0 means every selected case passed (or, for --self-check /
--seed-check, that check passed). Exit code 1 otherwise.
"""

import argparse
import os
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from sqlalchemy.engine.url import make_url

# ---------------------------------------------------------------------------
# Live-DB guard (D-02, D-05) — mirrors backend/tests/conftest.py:36-63.
# Deliberately duplicated, not imported: importing conftest.py would re-run
# its create-and-migrate bootstrap, which D-06 forbids for this script, and
# an extraction would put test_conftest_guard.py's collection-time contract
# at risk (see 29-RESEARCH.md Pitfall 2). Keep this block in sync BY HAND
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
# Answer-number extraction + matching (D-09, D-17). Pure stdlib, no DB, no
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
_SCALE_WORDS = {
    "juta": 1e6, "million": 1e6, "jt": 1e6, "m": 1e6,
    "miliar": 1e9, "billion": 1e9,
    "ribu": 1e3, "rb": 1e3, "k": 1e3,
}
_SCALE_PATTERN = "|".join(sorted(_SCALE_WORDS, key=len, reverse=True))

# ponytail: regex heuristic, not a real number grammar — a lone "1.234" with
# 3 trailing digits after one separator reads as grouping (Indonesian-style),
# never as a 3-decimal fraction; spelled-out numbers ("one million") are
# ignored entirely; every new format this misses needs its own self-check
# assert and a tweak here, not a rewrite.
_TOKEN_RE = re.compile(
    r"(?<![\w.,])"
    r"(?P<num>\d+(?:[.,]\d+)*)"
    r"(?:\s*(?P<scale>" + _SCALE_PATTERN + r")\b)?"
    r"(?!\d)"
    r"(?!\s?%)",
    re.IGNORECASE,
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
    Drops UUIDs, ISO dates, percentages, bare 1900-2100 years and anything
    under 100 in absolute value (small counts, day numbers).
    """
    cleaned = _UUID_RE.sub(" ", text)
    cleaned = _ISO_DATE_RE.sub(" ", cleaned)
    cleaned = _GLUED_PREFIX_RE.sub(lambda m: m.group(0) + " ", cleaned)

    out: list[tuple[float, float]] = []
    for m in _TOKEN_RE.finditer(cleaned):
        raw_num = m.group("num")
        scale_word = m.group("scale")
        try:
            value, decimals = _parse_number_str(raw_num)
        except ValueError:
            continue
        if scale_word:
            scale = _SCALE_WORDS[scale_word.lower()]
            value *= scale
            tolerance = 0.5 * (10 ** -decimals) * scale
        else:
            if re.fullmatch(r"\d+", raw_num) and 1900 <= value <= 2100:
                continue  # bare year
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

    assert "backend.db" not in sys.modules
    print("self-check OK")


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
    args = parser.parse_args(argv)

    if args.self_check:
        _self_check()
        return 0

    print("Only --self-check is implemented so far.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
