"""
Chat attachments (Phase 39): storage lifecycle.

Files are parsed once, at upload, in code (D-04); the model only ever sees the
stored text or rows. The raw bytes are kept for `RAW_RETENTION_DAYS` and then
purged (D-07) while `extracted_text`, `rows`, `meta` and any proposals made from
the file remain. Plans 39-04..06 add the parsers to this module.

pdfplumber and Pillow must only ever be imported inside functions here, never at
module level: main.py imports this module at startup and the 3.12 snapshot
image predates pdfplumber.
"""

import re
from decimal import Decimal, InvalidOperation

from sqlalchemy import text
from sqlalchemy.orm import Session

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
RAW_RETENTION_DAYS = 7


def purge_expired(db: Session) -> int:
    """NULL `raw` and stamp `purged_at` on attachments older than the retention
    window that still hold bytes, then commit. Returns the number purged.

    Idempotent: a purged row has raw NULL and drops out of the WHERE. Called
    lazily at the top of the upload route, `read_attachment` and the thread
    detail, as well as by the daily scheduler job.
    """
    result = db.execute(
        text(
            "UPDATE attachments SET raw = NULL, purged_at = now() "
            "WHERE purged_at IS NULL AND raw IS NOT NULL "
            "AND created_at < now() - make_interval(days => :d)"
        ),
        {"d": RAW_RETENTION_DAYS},
    )
    db.commit()
    return result.rowcount


# ---------------------------------------------------------------------------
# Amounts (D-12): one parser, exact Decimal, separator inferred once per file.
# ---------------------------------------------------------------------------

_CUR = re.compile(r"(?i)^(?:rp\.?|idr|usd|sgd|eur|us\$|s\$|\$|\u20ac)\s*|\s*(?:rp\.?|idr|usd|sgd|eur)$")
_TAIL = re.compile(r"(?i)\s*(db|cr|d|k|c)\.?$")
_NEG_TAIL = {"db", "d"}
_MINUS = str.maketrans({"\u2212": "-", "\u2013": "-", "\u00a0": " ", "\u202f": " ", "\u2009": " "})
_BODY = re.compile(r"^[0-9][0-9.,' ]*$")


def _clean(raw: str) -> tuple[int | None, str]:
    """Split a printed amount into (sign, digits-and-separators); ValueError if not an amount."""
    s = raw.translate(_MINUS).strip()
    sign = None
    if s.startswith("(") and s.endswith(")"):
        sign, s = -1, s[1:-1].strip()
    if s[:1] in ("+", "-"):  # a tuple: "" in "+-" is True and s[0] would then raise
        sign, s = (-1 if s[0] == "-" else 1), s[1:].strip()
    if s.endswith("-"):
        sign, s = -1, s[:-1].strip()
    s = _CUR.sub("", s).strip()
    m = _TAIL.search(s)
    if m and s[: m.start()].strip():
        sign = -1 if m.group(1).lower() in _NEG_TAIL else 1
        s = s[: m.start()].strip()
    s = _CUR.sub("", s).strip().replace(" ", "").replace("'", "")
    if sign is None and s[:1] in ("+", "-"):
        sign, s = (-1 if s[0] == "-" else 1), s[1:]
    if not _BODY.match(s):
        raise ValueError("not an amount")
    return sign, s


def _decide(body: str) -> str | None:
    """'.' | ',' | None: which character is the decimal separator, judged from one value."""
    d, c = body.count("."), body.count(",")
    if d and c:
        return "." if body.rfind(".") > body.rfind(",") else ","
    sep = "." if d else "," if c else None
    if sep is None:
        return None
    if body.count(sep) > 1:  # a repeated separator is thousands
        return "," if sep == "." else "."
    return sep if len(body.rsplit(sep, 1)[1]) in (1, 2) else None  # "1.250" is ambiguous


def infer_decimal_sep_with_evidence(values) -> tuple[str, str]:
    """Decimal separator for a whole amount column, plus "values" or "none" as evidence.

    Call once per file. With no evidence (or a tie) the IDR convention "," is
    returned with evidence "none"; the caller flags every row.
    """
    votes = {".": 0, ",": 0}
    for v in values:
        try:
            r = _decide(_clean(v)[1])
        except ValueError:
            continue
        if r:
            votes[r] += 1
    if votes["."] == votes[","]:
        # ponytail: IDR default when the file gives no evidence; rows are flagged, a PDF invariant catches a wrong guess
        return ",", "none"
    return ("." if votes["."] > votes[","] else ","), "values"


def infer_decimal_sep(values) -> str:
    """The decimal separator only; see infer_decimal_sep_with_evidence."""
    return infer_decimal_sep_with_evidence(values)[0]


def parse_amount(raw: str, decimal_sep: str = ",") -> Decimal:
    """Exact Decimal from a printed amount; ValueError on anything irregular.

    DB / D markers mean money out and CR / K / C money in, as the bank prints
    them. Whether an unsigned magnitude in a Debit column is an expense is
    decided by the column or the balance delta, not here. Serialise with
    format(d, "f").
    """
    sign, body = _clean(raw)
    th = "." if decimal_sep == "," else ","
    if body.count(decimal_sep) > 1:
        raise ValueError("ambiguous separators")
    ip, _, fp = body.partition(decimal_sep)
    if th in fp:
        raise ValueError("thousands separator after decimal")
    groups = ip.split(th)
    if len(groups) > 1 and (not 1 <= len(groups[0]) <= 3 or any(len(g) != 3 for g in groups[1:])):
        raise ValueError("irregular grouping")
    try:
        d = Decimal("".join(groups) + ("." + fp if fp else ""))
    except InvalidOperation:
        raise ValueError("not an amount") from None
    return -d if sign == -1 else d
