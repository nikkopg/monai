"""
Chat attachments (Phase 39): storage lifecycle.

Files are parsed once, at upload, in code (D-04); the model only ever sees the
stored text or rows. The raw bytes are kept for `RAW_RETENTION_DAYS` and then
purged (D-07) while `extracted_text`, `rows`, `meta` and any proposals made from
the file remain. Plans 39-04..06 add the parsers to this module.

pdfplumber and Pillow must only ever be imported inside functions here, never at
module level: main.py imports this module at startup and the 3.12 snapshot
image predates pdfplumber.

PDF statements are read in code and accepted only when their own printed
balances reconcile (D-09). The currency is the picked account's: statements are
not currency-detected. Having an LLM structure an unrecognised layout is
deferred (AIEX), so such a file is refused with a reason but stays askable.
"""

import calendar
import codecs
import csv
import io
import ipaddress
import os
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend import settings
from backend.importer import REQUIRED_COLUMNS
from backend.mcp_writes import _clean_text

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
RAW_RETENTION_DAYS = 7
MAX_ROWS = 500
MAX_TEXT_CHARS = 500_000
SEP_ASSUMPTION = 'Amounts read with "." as the thousands separator and "," as decimals.'
DMY_ASSUMPTION = "Dates read day first."
ALLOWED_TYPES_TEXT = "Allowed types: CSV, PDF, PNG, JPEG, WebP"


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


# ---------------------------------------------------------------------------
# Text-PDF statements (D-09, D-09a, D-10): rows are accepted only when they reconcile.
# ---------------------------------------------------------------------------

MAX_PDF_PAGES = 60


class NeedsPassword(Exception):
    """The PDF needs a password (wrong=False) or the one given did not open it (wrong=True).

    The message is fixed text: the password never enters an exception, note or log.
    """

    def __init__(self, wrong: bool):
        super().__init__("That password didn't open the file." if wrong else "This PDF needs a password.")
        self.wrong = wrong


def open_pdf(data: bytes, password: str | None):
    """An open pdfplumber PDF (use `with`); NeedsPassword when it can't be decrypted."""
    import pdfplumber
    from pdfminer.pdfdocument import PDFPasswordIncorrect
    from pdfplumber.utils.exceptions import PdfminerException

    try:
        return pdfplumber.open(io.BytesIO(data), password=password or "")
    except PdfminerException as e:
        if e.args and isinstance(e.args[0], PDFPasswordIncorrect):
            raise NeedsPassword(bool(password)) from None
        raise


def classify_pdf(data: bytes, password: str | None) -> tuple[str, int]:
    """("pdf_text" | "pdf_scanned", page count); scanned means no text layer on the first 3 pages."""
    with open_pdf(data, password) as pdf:
        return ("pdf_text" if any(p.chars for p in pdf.pages[:3]) else "pdf_scanned"), len(pdf.pages)


# Per-bank vocabulary as data over one generic line parser. The parser uses the union
# of every layout's words; a layout matters for `name` and its own rules. Adding a
# bank is a fixture plus an entry here.
LAYOUTS = (
    {   # BCA e-statement: credits carry no marker, the running balance shows on some rows only
        "name": "bca_like",
        "header_words": ("tanggal", "keterangan", "mutasi", "saldo"),
        "footer_labels": (("mutasi cr", "cr"), ("mutasi db", "db")),
        "unmarked_credit": True,
    },
    {
        "name": "mandiri_like",
        "header_words": ("tanggal", "keterangan", "debit", "kredit", "saldo"),
        "footer_labels": (("total kredit", "cr"), ("total debit", "db")),
    },
    {
        "name": "generic",
        "header_words": (),
        "open_labels": ("saldo awal", "opening balance", "beginning balance"),
        "close_labels": ("saldo akhir", "closing balance", "ending balance"),
        "footer_labels": (("total credits", "cr"), ("total debits", "db")),
        "carried_labels": ("saldo pindahan", "brought forward", "carried forward"),
        "skip_words": ("halaman", "page", "periode", "period", "tanggal", "keterangan", "description"),
    },
)


def _words(key: str) -> tuple[str, ...]:
    return tuple(w for L in LAYOUTS for w in L.get(key, ()))


_AMT = r"[-(+]?\d[\d.,]*[.,]\d{1,2}\)?(?:\s?(?:DB|CR|D|K)\b)?"  # always has 1-2 decimals
_TX = re.compile(
    rf"^(?P<d>\d{{2}}[/-]\d{{2}}(?:[/-]\d{{2,4}})?)\s+(?P<desc>.+?)\s+(?P<a1>{_AMT})(?:\s+(?P<a2>{_AMT}))?$", re.I
)
_OPEN = re.compile(rf"(?i)\b(?:{'|'.join(map(re.escape, _words('open_labels')))})\b\W*(?P<a>{_AMT})\s*$")
_CLOSE = re.compile(rf"(?i)\b(?:{'|'.join(map(re.escape, _words('close_labels')))})\b\W*(?P<a>{_AMT})\s*$")
_FOOT_KIND = {label: kind for label, kind in _words("footer_labels")}
_FOOT = re.compile(
    rf"(?i)\b(?P<label>{'|'.join(map(re.escape, _FOOT_KIND))})\b\s+(?P<n>\d+)\s+(?P<a>{_AMT})\s*$"
)
_CARRIED, _SKIP = _words("carried_labels"), _words("skip_words")

_MONTHS = {
    n: i
    for i, names in enumerate(
        [("jan", "januari", "january"), ("feb", "februari", "february"), ("mar", "maret", "march"),
         ("apr", "april"), ("mei", "may"), ("jun", "juni", "june"), ("jul", "juli", "july"),
         ("agu", "agt", "ags", "agustus", "aug", "august"), ("sep", "sept", "september"),
         ("okt", "oct", "oktober", "october"), ("nov", "nopember", "november"),
         ("des", "dec", "desember", "december")], 1)
    for n in names
}
_PERIOD_LINE = re.compile(r"(?i)\b(?:periode|period)\b(?P<rest>.*)")
_FULL_DATE = re.compile(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})")
_MONTH_YEAR = re.compile(r"([A-Za-z]+)\.?\s+(\d{4})")


def _period(text: str) -> tuple[date, date] | None:
    """(start, end) from a Periode/Period line, as dd/mm/yyyy - dd/mm/yyyy or month name and year; else None."""
    for line in _PERIOD_LINE.finditer(text):
        rest = line["rest"]
        try:
            days = [date(int(y), int(m), int(d)) for d, m, y in _FULL_DATE.findall(rest)]
        except ValueError:
            continue
        if len(days) >= 2:
            return min(days), max(days)
        my = [(_MONTHS[n.lower()], int(y)) for n, y in _MONTH_YEAR.findall(rest) if n.lower() in _MONTHS]
        if my:
            (m0, y0), (m1, y1) = my[0], my[-1]
            return date(y0, m0, 1), date(y1, m1, calendar.monthrange(y1, m1)[1])
    return None


def _row_date(token: str, period: tuple[date, date] | None) -> str:
    """ISO date; a year-less dd/mm takes its year from the period (ValueError if it fits none of them)."""
    if len(token) > 5:
        return parse_date(token, "dmy")
    d, mo = int(token[:2]), int(token[3:])
    for y in range(period[0].year, period[1].year + 1):
        try:
            day = date(y, mo, d)
        except ValueError:
            continue
        if period[0] <= day <= period[1]:
            return day.isoformat()
    raise ValueError("outside the period")


def _fmt_like(d: Decimal, sep: str) -> str:
    """d with two decimals, grouped in the file's own style ("." decimals: 1,234.50; "," decimals: 1.234,50)."""
    s = f"{d:,.2f}"
    return s if sep == "." else s.translate({44: 46, 46: 44})


def parse_pdf_statement(data: bytes, password: str | None, *, account_currency: str) -> Parsed:
    """A text PDF statement into candidate rows, or a refusal with a numeric reason.

    Accepted only when opening + rows == closing and, wherever a running balance
    is printed, previous + amount == balance, all in exact Decimal (footer totals
    too when printed). A row's sign comes from its DB/CR marker, else from the
    balance delta; BCA-like layouts print no marker on credits, so an unmarked
    amount there is a credit. Otherwise the file is refused, never guessed. White text is
    counted and kept; characters under 2 pt or off the page are dropped and
    counted (D-09a). Raises NeedsPassword. `account_currency` is the picked
    account's: statements are not currency-detected.
    """
    meta = {"layout": "generic", "invariant": "none", "hidden_white_chars": 0, "dropped_chars": 0}
    with open_pdf(data, password) as pdf:
        meta["pages"] = len(pdf.pages)
        if meta["pages"] > MAX_PDF_PAGES:
            return Parsed("pdf_text", "refused", [], "", meta, f"{meta['pages']} pages exceed the {MAX_PDF_PAGES}-page limit.")
        texts = []
        for page in pdf.pages:
            x0, top, x1, bottom = page.bbox

            def gone(c):
                return c["size"] < 2 or c["x1"] < x0 or c["x0"] > x1 or c["bottom"] < top or c["top"] > bottom

            meta["dropped_chars"] += sum(map(gone, page.chars))
            meta["hidden_white_chars"] += sum(_is_white(c) and not gone(c) for c in page.chars)
            texts.append(page.filter(lambda o: o.get("object_type") != "char" or not gone(o)).extract_text() or "")
    return _reconcile("\n".join(texts)[:MAX_TEXT_CHARS], meta)


def _is_white(char: dict) -> bool:
    color = char.get("non_stroking_color")
    color = tuple(color) if isinstance(color, (list, tuple)) else (color,)
    return bool(color) and all(v == 1 for v in color)


def _reconcile(text: str, meta: dict) -> Parsed:
    """Read the statement lines in `text` and apply the balance invariants."""
    low = text.casefold()
    layout = next(L for L in LAYOUTS if all(w in low for w in L["header_words"]))
    period = _period(text)
    meta.update(layout=layout["name"], period=period and {"start": period[0].isoformat(), "end": period[1].isoformat()})

    def refuse(note: str) -> Parsed:
        return Parsed("pdf_text", "refused", [], text, meta, note)

    opening = closing = prev = None
    foot, rows = {}, []
    for line in (ln.strip() for ln in text.splitlines()):
        lowline = line.casefold()
        if any(w in lowline for w in _CARRIED):
            prev = None
        elif m := _OPEN.search(line):
            opening, prev = m["a"], None
        elif m := _CLOSE.search(line):
            closing, prev = m["a"], None
        elif m := _FOOT.search(line):
            foot[_FOOT_KIND[m["label"].casefold()]] = (int(m["n"]), m["a"])
            prev = None
        elif m := _TX.match(line):
            prev = {"d": m["d"], "desc": m["desc"], "a1": m["a1"], "a2": m["a2"], "lines": [line]}
            rows.append(prev)
        elif any(w in lowline for w in _SKIP):
            prev = None
        elif prev:  # a continuation line joins the row above
            prev["desc"] += " " + line
            prev["lines"].append(line)

    if opening is None:
        return refuse("No opening balance found.")
    if closing is None:
        return refuse("No closing balance found.")
    meta["row_count"] = len(rows)
    if not rows:
        return refuse("No transaction rows were recognised.")
    if len(rows) > MAX_ROWS:
        return refuse(f"{len(rows)} rows exceed the {MAX_ROWS}-row batch limit.")
    if period is None and any(len(r["d"]) == 5 for r in rows):
        return refuse("No statement period found, so the year of each row is unknown.")

    tokens = [opening, closing] + [t for r in rows for t in (r["a1"], r["a2"]) if t] + [a for _, a in foot.values()]
    sep, evidence = infer_decimal_sep_with_evidence(tokens)
    meta["separator"] = {"sep": sep, "evidence": evidence}

    def show(d):
        return _fmt_like(d, sep)

    try:
        start, end = parse_amount(opening, sep), parse_amount(closing, sep)
        footer = {k: (n, abs(parse_amount(a, sep))) for k, (n, a) in foot.items()}
    except ValueError:
        return refuse("A balance or footer total can't be read.")
    meta.update(opening=format(start, "f"), closing=format(end, "f"))

    out, running, checked = [], start, 0
    for n, r in enumerate(rows, 1):
        try:
            iso = _row_date(r["d"], period)
        except ValueError:
            return refuse(f"Row {n} ({r['d']}) has a date that can't be read or lies outside the statement period.")
        try:
            sign, amt = _clean(r["a1"])[0], parse_amount(r["a1"], sep)
            bal = parse_amount(r["a2"], sep) if r["a2"] else None
        except ValueError:
            return refuse(f"Row {n} ({iso}) has an amount that can't be read.")
        if sign is None and not layout.get("unmarked_credit"):
            if bal is None:
                return refuse(f"Row {n} ({iso}) has no debit or credit marker and no balance to tell its direction.")
            amt = next((s for s in (amt, -amt) if running + s == bal), None)  # credit first
            if amt is None:
                return refuse(f"Running balance off at {iso}: {show(bal)} fits neither a credit nor a debit of {r['a1']}.")
        if bal is not None:
            if running + amt != bal:
                return refuse(f"Running balance off at {iso}: expected {show(running + amt)} got {show(bal)}.")
            checked += 1
        running += amt
        out.append({
            "date": iso,
            "amount": format(amt, "f"),
            "merchant": _clean_text(r["desc"], None) or None,
            "notes": None,
            "category": None,
            "raw_line": _clean_text(" / ".join(r["lines"]), 200),
            "llm_read": False,
            "assumptions": [],
        })

    if running != end:
        return refuse(f"Closing balance off by {show(running - end)}.")
    amounts = [Decimal(r["amount"]) for r in out]
    for kind, vals in (("cr", [a for a in amounts if a > 0]), ("db", [-a for a in amounts if a < 0])):
        if kind in footer and footer[kind] != (len(vals), sum(vals)):
            return refuse("The statement's footer totals don't match its rows.")
    meta["invariant"] = "running balance verified" if checked == len(rows) else "balance verified"
    return Parsed("pdf_text", "ok", out, text, meta)


# ---------------------------------------------------------------------------
# File type and name (D-06)
# ---------------------------------------------------------------------------

def sniff(data: bytes) -> tuple[str, str] | None:
    """(kind, mime) from magic bytes only, or None; the client's type and name are never consulted.

    A PDF may carry up to 1 KiB of leading junk, as Acrobat allows. A CSV is
    anything that decodes, has no NUL in the first 8 KiB (unless UTF-16 with a
    BOM) and has a delimiter in its first line.
    """
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image", "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image", "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image", "image/webp"
    if b"%PDF-" in data[:1024]:
        return "pdf", "application/pdf"
    if b"\x00" in data[:8192] and not data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return None
    text = _decode(data)[0].lstrip()
    if text and _detect_delimiter(text.splitlines()[0]):
        return "csv", "text/csv"
    return None


def safe_filename(name: str) -> str:
    """Basename without control or bidi characters, at most 80 characters; "file" if nothing is left.

    Display only: attachments are stored by generated id, never by this name.
    """
    return _clean_text(os.path.basename(name.replace("\\", "/")), 80) or "file"


# ---------------------------------------------------------------------------
# Locality (D-14, D-14a): where would this file go?
# ---------------------------------------------------------------------------

_CLOUD_TAG = re.compile(r"(?:^|[-:])cloud$", re.I)
_DOCKER_HOSTS = {"localhost", "host.docker.internal", "gateway.docker.internal"}


def _host(base_url: str) -> str:
    return (urlsplit(base_url if "//" in base_url else "//" + base_url).hostname or "").lower()


def _is_loopback(base_url: str) -> bool:
    h = _host(base_url)
    if h in _DOCKER_HOSTS:
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def locality(provider: str, model: str, base_url: str) -> dict:
    """{"local": bool, "destination": str | None}; destination names where the file would be sent."""
    if provider == "ollama":
        if not _CLOUD_TAG.search(model) and _is_loopback(base_url):
            return {"local": True, "destination": None}
        dest = f"Ollama Cloud ({model})" if _CLOUD_TAG.search(model) else f"Ollama at {_host(base_url)} ({model})"
    else:
        dest = {"claude": "Anthropic", "openai": "OpenAI"}.get(provider, provider) + f" ({model})"
    return {"local": False, "destination": dest}


def current_locality(db: Session) -> dict:
    """locality() for the configured provider and model.

    Provider and model come from the effective settings (the Settings page
    overrides env); the base URL from OLLAMA_BASE_URL, the same default
    configure_llm uses. The compose stack runs with network_mode: host, so
    localhost is the host's own Ollama daemon. The default config is NOT local
    (D-14): its model tag ends in -cloud.
    """
    eff = settings.get_effective_settings(db)
    return locality(
        eff["llm_provider"], eff["llm_model"], os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    )


# ---------------------------------------------------------------------------
# Images and scanned PDFs (D-11): capped, EXIF-free PNGs for the vision read.
# ---------------------------------------------------------------------------

MAX_IMAGE_PIXELS = 40_000_000
MAX_VISION_PAGES = 5
MAX_IMAGE_SIDE = 2000
_RENDER_DPI = 150


class ImageRefused(ValueError):
    """The image can't be sent to a model; the message is fixed text, safe to show."""


_TOO_LARGE = "The image is too large to read safely."


def _to_png(im) -> bytes:
    """RGB, at most MAX_IMAGE_SIDE a side, as PNG. No exif argument is passed, so EXIF (GPS included) is dropped."""
    im = im.convert("RGB")
    im.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def prepare_images(data: bytes, kind: str, password: str | None = None) -> list[bytes]:
    """PNG bytes for the model: one for an image, up to MAX_VISION_PAGES for a scanned PDF.

    Raises ImageRefused (bomb, unreadable) or NeedsPassword. Pillow's pixel
    warning is turned into an error so a bomb is refused before it is decoded.
    """
    import warnings

    from PIL import Image, ImageOps

    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            if kind == "image":
                Image.open(io.BytesIO(data)).verify()  # verify() spoils the image, so open it again
                return [_to_png(ImageOps.exif_transpose(Image.open(io.BytesIO(data))))]
            with open_pdf(data, password) as pdf:
                pages = pdf.pages[:MAX_VISION_PAGES]
                # a huge MediaBox would be rasterised in full before any pixel check
                if any(p.width * p.height * (_RENDER_DPI / 72) ** 2 > MAX_IMAGE_PIXELS for p in pages):
                    raise ImageRefused(_TOO_LARGE)
                return [_to_png(p.to_image(resolution=_RENDER_DPI).original) for p in pages]
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ImageRefused(_TOO_LARGE) from None
    except (ImageRefused, NeedsPassword):
        raise
    except Exception:
        raise ImageRefused("The image could not be read.") from None
