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

import codecs
import csv
import io
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.importer import REQUIRED_COLUMNS
from backend.mcp_writes import _clean_text

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
RAW_RETENTION_DAYS = 7
MAX_ROWS = 500
MAX_TEXT_CHARS = 500_000
SEP_ASSUMPTION = 'Amounts read with "." as the thousands separator and "," as decimals.'
DMY_ASSUMPTION = "Dates read day first."


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


# ---------------------------------------------------------------------------
# CSV (D-08, D-08a): parsed by code only, no model.
# ---------------------------------------------------------------------------

@dataclass
class Parsed:
    """What a parser hands back: `status` is "ok", "refused" or "llm_read".

    Each row dict is
    {"date": "YYYY-MM-DD", "amount": "<Decimal string, format(d, 'f')>",
     "merchant": str | None, "notes": str | None, "category": str | None,
     "raw_line": str | None (<= 200 chars), "llm_read": bool,
     "assumptions": list[str]}. Expenses are negative.

    `text` is what the model may be asked about, even when the rows were refused.
    """

    kind: str
    status: str
    rows: list[dict]
    text: str
    meta: dict
    note: str | None = None

    @property
    def askable(self) -> bool:
        return bool(self.text.strip())


SYNONYMS = {
    "date": ("date", "tanggal", "tgl", "transaction date", "posting date"),
    "description": ("description", "keterangan", "uraian", "note", "notes", "memo", "merchant", "payee"),
    "amount": ("amount", "jumlah", "nominal", "mutasi"),
    "debit": ("debit", "db", "keluar", "withdrawal"),
    "credit": ("credit", "cr", "kredit", "masuk", "deposit"),
}
_ISO = re.compile(r"^\s*(\d{4})[/.\-](\d{1,2})[/.\-](\d{1,2})")
_DMY = re.compile(r"^\s*(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2}|\d{4})(?!\d)")


def _decode(data: bytes) -> tuple[str, str]:
    """(text, encoding name): UTF-16 if it has a BOM, UTF-8 (BOM allowed), else cp1252."""
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return data.decode("utf-16", errors="replace"), "utf-16"
    try:
        return data.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace"), "cp1252"


def _detect_delimiter(first_line: str) -> str | None:
    """The most frequent of ; , tab outside double quotes, or None if there is none."""
    bare = re.sub(r'"[^"]*"', "", first_line)
    best = max((";", ",", "\t"), key=bare.count)
    return best if bare.count(best) else None


def _norm(header: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", "", header).casefold().split())


def infer_date_order(values) -> tuple[str, str]:
    """("iso" | "dmy" | "mdy", "values" | "none"), once per file; ValueError if both orders occur.

    Any first part > 12 means day first, any second part > 12 month first. With no
    evidence the order is day first (the Indonesian convention) and the caller flags
    every row.
    """
    first = second = other = iso = False
    for v in values:
        if _ISO.match(v):
            iso = True
        elif m := _DMY.match(v):
            other = True
            first |= int(m[1]) > 12
            second |= int(m[2]) > 12
    if first and second:
        raise ValueError("dates in both orders")
    if first or second:
        return ("dmy" if first else "mdy"), "values"
    return ("iso", "values") if iso and not other else ("dmy", "none")


def parse_date(value: str, order: str) -> str:
    """ISO date string from an ISO or d/m/y or m/d/y value (time ignored); two-digit years pivot at 70."""
    if m := _ISO.match(value):
        y, mo, d = map(int, m.groups())
    elif m := _DMY.match(value):
        a, b, c = m.groups()
        d, mo = (int(b), int(a)) if order == "mdy" else (int(a), int(b))
        y = int(c) + (0 if len(c) == 4 else 2000 if int(c) < 70 else 1900)
    else:
        raise ValueError("unreadable date")
    return date(y, mo, d).isoformat()


def _n(n: int, noun: str) -> str:
    return f"{n} {noun}" + ("" if n == 1 else "s")


def parse_csv_attachment(data: bytes, *, account_name: str, account_currency: str) -> Parsed:
    """A CSV into candidate rows, or a refusal with a one-sentence reason.

    Wallet exports are detected first and keep only the picked account's
    non-transfer rows (D-08a). Anything else is mapped through SYNONYMS and is
    refused, listing the headers found, unless date and amount (or a debit and
    credit pair) each resolve to exactly one column. Separator and date order are
    inferred once per file. A refusal never quotes a cell value, and the text stays
    askable.
    """
    text, encoding = _decode(data)
    text = text[:MAX_TEXT_CHARS]
    meta = {"encoding": encoding, "invariant": "none", "skipped_other_account": 0, "skipped_transfer": 0}

    def refuse(note: str) -> Parsed:
        return Parsed("csv", "refused", [], text, meta, note)

    delim = _detect_delimiter(text.lstrip().splitlines()[0]) if text.strip() else None
    if delim is None:
        return refuse("No header row with a delimiter was found.")
    meta["delimiter"] = delim
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    table = [(reader.line_num, r) for r in reader if any(c.strip() for c in r)]
    headers = [h.strip() for h in table[0][1]]
    meta["headers"] = headers

    def cell(r, i):
        return r[i].strip() if i is not None and i < len(r) else ""

    idx = {h.casefold(): i for i, h in enumerate(headers)}
    wallet = REQUIRED_COLUMNS <= idx.keys()
    meta["format"] = "wallet" if wallet else "generic"
    if wallet:
        items, acct = [], account_name.strip().casefold()
        for line, r in table[1:]:
            if cell(r, idx["account"]).casefold() != acct:
                meta["skipped_other_account"] += 1
            elif cell(r, idx["transfer"]).lower() == "true":
                meta["skipped_transfer"] += 1
            else:
                items.append((line, r))
        wrong = [c for _, r in items if (c := cell(r, idx["currency"]).upper()) != account_currency.upper()]
        if wrong:
            cur = ", ".join(sorted({_clean_text(c, 8) for c in wrong}))
            return refuse(
                f"{_n(len(wrong), 'row')} {'is' if len(wrong) == 1 else 'are'} in {cur}, "
                f"not {account_currency}; nothing was proposed."
            )
        col = {
            "date": idx["date"], "amount": idx["amount"], "debit": None, "credit": None,
            "merchant": idx.get("payee"), "notes": idx["note"], "category": idx["category"],
        }
        skipped = [
            f"{_n(n, noun)}"
            for n, noun in ((meta["skipped_other_account"], "row from other accounts"), (meta["skipped_transfer"], "transfer row"))
            if n
        ]
        note = f"Skipped {' and '.join(skipped)}." if skipped else None
    else:
        items, note = table[1:], None
        roles = {role: [i for i, h in enumerate(headers) if _norm(h) in syn] for role, syn in SYNONYMS.items()}
        dates, amts, debs, creds = (roles[k] for k in ("date", "amount", "debit", "credit"))
        pair = not amts and len(debs) == 1 and len(creds) == 1
        if len(dates) != 1 or not (pair or (len(amts) == 1 and not debs and not creds)):
            why = (
                "No date column." if not dates
                else "More than one date column." if len(dates) > 1
                else "No single amount column, or debit and credit pair."
            )
            return refuse(f"{why} Headers found: {', '.join(_clean_text(h, 40) for h in headers)}.")
        col = {
            "date": dates[0], "amount": amts[0] if amts else None,
            "debit": debs[0] if pair else None, "credit": creds[0] if pair else None,
            "merchant": (roles["description"] or [None])[0], "notes": None, "category": None,
        }

    meta["row_count"] = len(items)
    if not items:
        return refuse("No transaction rows to propose.")
    if len(items) > MAX_ROWS:
        return refuse(f"{len(items)} rows exceed the {MAX_ROWS}-row batch limit.")

    amount_cols = [col[k] for k in ("amount", "debit", "credit") if col[k] is not None]
    if wallet:
        sep, sep_ev = ".", "format"  # the export is machine-formatted
    else:
        sep, sep_ev = infer_decimal_sep_with_evidence([cell(r, i) for _, r in items for i in amount_cols])
    try:
        order, date_ev = infer_date_order([cell(r, col["date"]) for _, r in items])
    except ValueError:
        return refuse("Dates in this file can't be read in one order.")
    assumptions = ([SEP_ASSUMPTION] if sep_ev == "none" else []) + ([DMY_ASSUMPTION] if date_ev == "none" else [])
    meta.update(separator={"sep": sep, "evidence": sep_ev}, date_order={"order": order, "evidence": date_ev},
                assumptions=assumptions)

    rows = []
    for line, r in items:
        try:
            day = parse_date(cell(r, col["date"]), order)
        except ValueError:
            return refuse(f"Line {line} has a date that can't be read.")
        try:
            if col["debit"] is not None:
                dr, cr = cell(r, col["debit"]), cell(r, col["credit"])
                if dr and cr:
                    return refuse(f"Line {line} has both a debit and a credit amount.")
                amount = -abs(parse_amount(dr, sep)) if dr else abs(parse_amount(cr, sep))
            else:
                amount = parse_amount(cell(r, col["amount"]), sep)
        except ValueError:
            return refuse(f"Line {line} has an amount that can't be read.")
        notes = _clean_text(cell(r, col["notes"]), None) or None
        rows.append({
            "date": day,
            "amount": format(amount, "f"),
            "merchant": _clean_text(cell(r, col["merchant"]), None) or notes,
            "notes": notes,
            "category": _clean_text(cell(r, col["category"]), None) or None,
            "raw_line": _clean_text(delim.join(r), 200),
            "llm_read": False,
            "assumptions": list(assumptions),
        })
    return Parsed("csv", "ok", rows, text, meta, note)
