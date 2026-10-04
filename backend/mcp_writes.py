"""Curated MCP write wrappers (Phase 32) plus the duplicate-flag helper.

The wrappers fix channel "mcp" themselves and are registered on FastMCP only,
never in tools.TOOLS (D-02, D-03). Every refusal is a fixed-text ToolError and
no token, code or key is ever returned or logged (D-21). backend.main imports
this module's helper, so anything from backend.main is imported lazily inside
functions.
"""
import unicodedata
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from backend.models import Proposal

CAPTURE_OPS = ("add_transaction", "add_transfer")
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
