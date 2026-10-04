"""Curated MCP write wrappers (Phase 32) plus the duplicate-flag helper.

The wrappers fix channel "mcp" themselves and are registered on FastMCP only,
never in tools.TOOLS (D-02, D-03). Every refusal is a fixed-text ToolError and
no token, code or key is ever returned or logged (D-21). backend.main imports
this module's helper, so anything from backend.main is imported lazily inside
functions.
"""
import functools
import logging
import re
import unicodedata
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import NoReturn
from zoneinfo import ZoneInfo

from fastmcp.exceptions import ToolError
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from backend.db import get_session_sync
from backend.models import Proposal
from backend.proposals import transition
from backend.tools import _make_proposal

logger = logging.getLogger(__name__)

CAPTURE_OPS = ("add_transaction", "add_transfer")
MAX_BATCH_ROWS = 500
MAX_ATTEMPTS = 5
NEXT_STEP = "Ask the owner for the 6-character code shown in monai, then call confirm_proposal. Never guess a code."
_GENERIC = "Could not complete this request. Nothing was changed."
_MERCHANT_MAX = 512
_JAKARTA = ZoneInfo("Asia/Jakarta")
_MAX_FLAGS = 5
_FLAG_WINDOW_DAYS = 3


def _clean_text(value: str | None, limit: int = 80) -> str | None:
    """Strip control/format characters and cap length (ledger text flows to an LLM)."""
    if value is None:
        return None
    kept = "".join(c for c in value if unicodedata.category(c)[0] != "C" and c not in "  ")
    return kept[:limit]


def _entries(p: Proposal, ids: dict[str, int]):
    """Yield (row_index, account_id, amount, day, skipped) per matchable payload entry.

    A transfer row yields both legs. Any missing or unparseable field drops that
    entry (chat payloads may hold None dates or odd names).
    """
    for i, row in enumerate((p.payload or {}).get("rows") or []):
        try:
            after = row["after"]
            legs = [after["leg_a"], after["leg_b"]] if p.operation == "add_transfer" else [after]
        except (KeyError, TypeError):
            continue
        for leg in legs:
            try:
                amount = Decimal(str(leg["amount"]))
                if not amount.is_finite():
                    continue
                yield (i, ids[leg["account"]], amount,
                       date.fromisoformat(str(leg["date"])[:10]), bool(row.get("skip")))
            except (KeyError, TypeError, ValueError, InvalidOperation):
                continue


def duplicate_flags(db: Session, proposals: list[Proposal]) -> dict[uuid.UUID, list[list[dict]]]:
    """Advisory duplicate flags, one list per payload row (D-17, D-18).

    A row is flagged when another row has the same account id, the same exact
    amount and a date within 3 days: in the ledger (transfer legs included),
    in any other pending unexpired capture proposal, or elsewhere in its own
    batch. Skipped rows are not match targets but keep their own flags. Flags
    never block. Three queries total; both sides are Jakarta wall-clock days.
    """
    ids = {name: i for name, i in db.execute(text("SELECT name, id FROM accounts"))}
    targets = (
        db.query(Proposal)
        .filter(Proposal.status == "pending", Proposal.expires_at > func.now(),
                Proposal.operation.in_(CAPTURE_OPS))
        .order_by(Proposal.created_at, Proposal.id)
        .all()
    )
    by_key: dict[tuple, list[tuple]] = {}
    for t in targets:
        for j, acc, amt, day, skipped in _entries(t, ids):
            if not skipped:
                by_key.setdefault((acc, amt), []).append((t.id, j, day))

    subjects = {
        p.id: list(_entries(p, ids)) for p in proposals if p.operation in CAPTURE_OPS
    }
    flat = [e for es in subjects.values() for e in es]
    ledger: dict[tuple, list] = {}
    if flat:
        days = [e[3] for e in flat]
        lo = datetime.combine(min(days) - timedelta(days=_FLAG_WINDOW_DAYS), datetime.min.time())
        hi = datetime.combine(max(days) + timedelta(days=_FLAG_WINDOW_DAYS + 1), datetime.min.time())
        rows = db.execute(
            text(
                "SELECT id, date, amount, merchant, account_id FROM transactions "
                "WHERE account_id = ANY(:ids) AND amount = ANY(:amts) "
                "AND date >= :lo AND date < :hi ORDER BY date, id"
            ),
            {"ids": list({e[1] for e in flat}), "amts": list({e[2] for e in flat}), "lo": lo, "hi": hi},
        ).all()
        for r in rows:
            ledger.setdefault((r.account_id, r.amount), []).append(r)

    out: dict[uuid.UUID, list[list[dict]]] = {}
    for p in proposals:
        if p.operation not in CAPTURE_OPS:
            continue
        flags: list[list[dict]] = [[] for _ in (p.payload or {}).get("rows") or []]
        for j, acc, amt, day, _skipped in subjects[p.id]:
            row_flags = flags[j]
            for tx in ledger.get((acc, amt), []):
                if abs((tx.date.date() - day).days) <= _FLAG_WINDOW_DAYS:
                    row_flags.append({
                        "kind": "transaction", "id": tx.id, "date": tx.date.date().isoformat(),
                        "amount": str(tx.amount), "merchant": _clean_text(tx.merchant),
                    })
            for pid, k, tday in by_key.get((acc, amt), []):
                if (pid, k) != (p.id, j) and abs((tday - day).days) <= _FLAG_WINDOW_DAYS:
                    row_flags.append({"kind": "proposal", "id": str(pid), "row": k})
        # De-duplicate (two transfer legs can hit the same target); ledger flags come first.
        for j, row_flags in enumerate(flags):
            seen, uniq = set(), []
            for f in sorted(row_flags, key=lambda f: f["kind"] != "transaction"):
                key = (f["kind"], f["id"], f.get("row"))
                if key not in seen:
                    seen.add(key)
                    uniq.append(f)
            flags[j] = uniq[:_MAX_FLAGS]
        out[p.id] = flags
    return out


# ---------------------------------------------------------------------------
# Fixed-message contract (D-21)
# ---------------------------------------------------------------------------

def _refuse(msg: str) -> NoReturn:
    """Refusals are ToolErrors so clients see isError true (A5)."""
    raise ToolError(msg, log_level=logging.INFO)


def _safe(fn):
    """ToolErrors pass through; anything else becomes one fixed text.

    Only the exception type name is logged: exception text can carry SQL
    parameters, which must never reach MCP output or logs.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ToolError:
            raise
        except Exception as e:
            logger.error("mcp write tool %s failed: %s", fn.__name__, type(e).__name__)
            raise ToolError(_GENERIC, log_level=logging.INFO) from None

    return wrapper


class TxnRow(BaseModel):
    """One proposed transaction row; no currency or is_transfer (D-04)."""

    model_config = ConfigDict(extra="forbid")

    date: str = Field(description="YYYY-MM-DD, not in the future")
    amount: str | int | float = Field(description="Signed: negative = expense, positive = income")
    account: str = Field(description="Existing liquid account name (see find_accounts)")
    merchant: str | None = None
    category: str | None = None
    notes: str | None = None


# ---------------------------------------------------------------------------
# Validation (D-05); no message echoes a submitted value
# ---------------------------------------------------------------------------

def _parse_day(value) -> date | None:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _parse_amount(value) -> Decimal | None:
    """Finite, below 10**16, at most 2 decimals; returned quantized. Zero is the caller's call."""
    try:
        d = Decimal(str(value))
    except InvalidOperation:
        return None
    if not d.is_finite() or abs(d) >= Decimal(10) ** 16:
        return None
    q = d.quantize(Decimal("0.01"))
    return q if q == d else None


def _load_refs(db: Session):
    """(liquid accounts by casefolded name, casefolded -> canonical category)."""
    accounts: dict[str, list] = {}
    for id_, name, currency in db.execute(text("SELECT id, name, currency FROM accounts WHERE type = 'liquid'")):
        accounts.setdefault(name.strip().casefold(), []).append((id_, name, currency or "IDR"))
    cats: dict[str, str] = {}
    for (name,) in db.execute(text("SELECT name FROM categories ORDER BY id")):
        cats.setdefault(name.strip().casefold(), name)  # lowest id wins a case-insensitive tie
    return accounts, cats


def _resolve_account(accounts, name):
    hits = accounts.get(name.strip().casefold(), []) if isinstance(name, str) else []
    if not hits:
        return None, "unknown account, call find_accounts"
    if len(hits) > 1:
        return None, "account name matches more than one account, call find_accounts"
    return hits[0], None


def _date_error(value, today: date) -> str | None:
    day = _parse_day(value)
    if day is None:
        return "date must be YYYY-MM-DD"
    return "date is in the future" if day > today else None


def _text_error(label: str, value, limit: int | None = None) -> str | None:
    if value is None:
        return None
    if "\x00" in value:  # Postgres text and JSONB cannot hold NUL
        return f"{label} contains an invalid character"
    if limit and len(value) > limit:
        return f"{label} is longer than {limit} characters"
    return None


# ---------------------------------------------------------------------------
# Propose, reject, replace
# ---------------------------------------------------------------------------

def _supersede(db: Session, replaces: str) -> uuid.UUID:
    """Supersede the caller's own pending, unlocked capture proposal (D-14).

    Same session as the insert of its replacement, so any later failure rolls
    both back. Cross-operation replace is allowed.
    """
    from fastapi import HTTPException

    from backend.main import _require_pending

    try:
        pid = uuid.UUID(str(replaces))
    except ValueError:
        _refuse("No proposal with that id.")
    old = db.get(Proposal, pid, with_for_update=True)
    if old is None:
        _refuse("No proposal with that id.")
    if old.channel != "mcp":
        _refuse("Only proposals created over MCP can be replaced; change this one in monai.")
    if old.operation not in CAPTURE_OPS:
        _refuse("Only transaction and transfer proposals can be replaced.")
    try:
        _require_pending(old)
    except HTTPException as e:
        if e.status_code == 410:
            _refuse("That proposal expired; propose again without replaces.")
        _refuse(f"That proposal is already {old.status}; propose again without replaces.")
    if old.failed_attempts >= MAX_ATTEMPTS:
        _refuse("That proposal is locked after 5 wrong codes and cannot be replaced; "
                "the owner can approve or reject it in monai.")
    transition(old, "superseded")
    db.flush()
    return old.id


def _create(db: Session, operation: str, payload: dict, replaces: str | None, summary: str, many: bool) -> dict:
    """Insert one mcp proposal (superseding `replaces`) and commit once.

    The token _make_proposal returns is discarded; flags are computed after the
    supersede flush so a replacement is not flagged against its predecessor.
    """
    old_id = _supersede(db, replaces) if replaces else None
    pid, _ = _make_proposal(operation, payload, "mcp", db=db, supersedes_id=old_id)
    p = db.get(Proposal, uuid.UUID(pid))
    flags = duplicate_flags(db, [p])[p.id]
    dups = [{"row": i, "matches": f} for i, f in enumerate(flags) if f]
    if dups:
        summary += f", {len(dups)} flagged as possible duplicate(s)" if many else ", flagged as a possible duplicate"
    result = {
        "proposal_id": str(p.id),
        "summary": summary,
        "row_count": len(payload["rows"]),
        "expires_at": p.expires_at.isoformat(),
        "duplicates": dups,
        "next_step": NEXT_STEP,
    }
    db.commit()
    return result


@_safe
def propose_transactions(rows: list[TxnRow], replaces: str | None = None) -> dict:
    if not rows:
        _refuse("Send at least one row.")
    if len(rows) > MAX_BATCH_ROWS:
        _refuse(f"Too many rows ({len(rows)}). Send at most {MAX_BATCH_ROWS} rows per call; "
                "split the batch into several calls.")
    today = datetime.now(_JAKARTA).date()
    errors: list[str] = []
    out: list[dict] = []
    names: set[str] = set()
    with get_session_sync() as db:
        accounts, cats = _load_refs(db)
        for i, r in enumerate(rows):
            errs = []
            acct, err = _resolve_account(accounts, r.account)
            if err:
                errs.append(err)
            category = None
            if r.category:
                category = cats.get(r.category.strip().casefold())
                if category is None:
                    errs.append("unknown category, call list_categories")
            amount = _parse_amount(r.amount)
            if amount is None or amount == 0:
                errs.append("amount must be a non-zero number with at most 2 decimals")
            errs += [e for e in (_date_error(r.date, today),
                                 _text_error("merchant", r.merchant, _MERCHANT_MAX),
                                 _text_error("notes", r.notes)) if e]
            if errs:
                errors += [f"row {i}: {e}" for e in errs]
                continue
            names.add(acct[1])
            out.append({"before": None, "after": {
                "date": r.date, "amount": str(amount), "account": acct[1], "category": category,
                "merchant": r.merchant, "notes": r.notes, "currency": acct[2], "is_transfer": False,
            }})
        if errors:
            more = f", and {len(errors) - 20} more" if len(errors) > 20 else ""
            _refuse("Nothing was proposed. Fix these rows (numbered from 0) and call again: "
                    + "; ".join(errors[:20]) + more)
        n = len(out)
        return _create(db, "add_transaction", {"operation": "add_transaction", "rows": out}, replaces,
                       f"Add {n} transaction(s) to {', '.join(sorted(names))}", many=True)


@_safe
def propose_transfer(
    from_account: str,
    to_account: str,
    amount: str | int | float,
    date: str,
    notes: str | None = None,
    replaces: str | None = None,
) -> dict:
    today = datetime.now(_JAKARTA).date()
    errors: list[str] = []
    with get_session_sync() as db:
        accounts, _ = _load_refs(db)
        src, err = _resolve_account(accounts, from_account)
        if err:
            errors.append(f"from_account: {err}")
        dst, err = _resolve_account(accounts, to_account)
        if err:
            errors.append(f"to_account: {err}")
        if src and dst and src[0] == dst[0]:
            errors.append("from_account and to_account must be different accounts")
        elif src and dst and src[2] != dst[2]:
            errors.append("Both accounts must use the same currency.")
        mag = _parse_amount(amount)
        if mag is None or mag <= 0:
            errors.append("amount must be a positive number with at most 2 decimals")
        errors += [e for e in (_date_error(date, today), _text_error("notes", notes)) if e]
        if errors:
            _refuse("Nothing was proposed. " + "; ".join(errors))
        cur = src[2]
        leg = lambda acct, amt: {"account": acct[1], "amount": str(amt), "currency": cur, "date": date, "notes": notes}
        payload = {"operation": "add_transfer",
                   "rows": [{"before": None, "after": {"leg_a": leg(src, -mag), "leg_b": leg(dst, mag)}}]}
        return _create(db, "add_transfer", payload, replaces,
                       f"Transfer {mag} {cur} from {src[1]} to {dst[1]} on {date}", many=False)


@_safe
def reject_proposal(proposal_id: str) -> dict:
    """Reject the caller's own pending MCP capture proposal. No code needed (D-13)."""
    try:
        pid = uuid.UUID(str(proposal_id))
    except ValueError:
        _refuse("No proposal with that id.")
    with get_session_sync() as db:
        p = db.get(Proposal, pid, with_for_update=True)
        if p is None:
            _refuse("No proposal with that id.")
        if p.channel != "mcp":
            _refuse("This proposal was not created over MCP; reject this in monai.")
        if p.operation not in CAPTURE_OPS:
            _refuse("Only transaction and transfer proposals can be rejected over MCP; reject this in monai.")
        if p.status != "pending":
            _refuse(f"This proposal is already {p.status}.")
        transition(p, "rejected")  # locked proposals may be rejected too
        db.commit()
        return {"proposal_id": str(p.id), "status": "rejected"}
