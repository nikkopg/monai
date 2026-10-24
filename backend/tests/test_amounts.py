"""Phase 39 amount parsing (D-12); synthetic values only."""
import re
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text

from backend import attachments as att
from backend.attachments import (
    infer_decimal_sep,
    infer_decimal_sep_with_evidence,
    parse_amount,
)

COMMA = [  # decimal_sep=","
    ("1.250.000,00", "1250000.00"),
    ("Rp 1.250.000", "1250000"),
    ("IDR1.250.000,50", "1250000.50"),
    ("(1.250.000,00)", "-1250000.00"),
    ("-1.250.000", "-1250000"),
    ("1.250.000,00 DB", "-1250000.00"),
    ("1.250.000,00 CR", "1250000.00"),
    ("1.250.000,00 D", "-1250000.00"),
    ("50.000 K", "50000"),
    ("0,5", "0.5"),
    ("12,50", "12.50"),
    ("−1.250,00", "-1250.00"),
]
DOT = [  # decimal_sep="."
    ("1,250,000.00", "1250000.00"),
    ("$1,250.50", "1250.50"),
    ("1,250,000", "1250000"),
    ("50,500.00 DB", "-50500.00"),
    ("-12.5", "-12.5"),
    ("(250.00)", "-250.00"),
    ("1250.50", "1250.50"),
    ("1250", "1250"),
]


@pytest.mark.parametrize("raw,want", COMMA)
def test_parse_comma_decimal(raw, want):
    assert parse_amount(raw, ",") == Decimal(want)


@pytest.mark.parametrize("raw,want", DOT)
def test_parse_dot_decimal(raw, want):
    assert parse_amount(raw, ".") == Decimal(want)


@pytest.mark.parametrize("raw", ["1.25.000,00", "12abc", "1,250.00.00", "", "--5", "1.2345,00"])
def test_rejects_irregular(raw):
    with pytest.raises(ValueError):
        parse_amount(raw, ",")


def test_exact_decimal_serialisation():
    d = parse_amount("1.250.000,00", ",")
    assert str(d) == "1250000.00"
    assert format(d, "f") == "1250000.00"


@pytest.mark.parametrize(
    "values,want",
    [
        (["1.250.000,00", "50.500,00", "1.250"], ","),
        (["1,250,000.00", "50,500.00", "1,250"], "."),
        (["1.250", "500.000", "20.000"], ","),
        (["1.5", "2.25", "10"], "."),
    ],
)
def test_infer_decimal_sep(values, want):
    assert infer_decimal_sep(values) == want


def test_no_evidence_defaults_to_idr_and_reads_thousands():
    values = ["1.250", "500.000", "20.000"]
    assert infer_decimal_sep_with_evidence(values) == (",", "none")
    assert parse_amount("1.250", ",") == Decimal(1250)
    assert infer_decimal_sep_with_evidence(["1.250,00"]) == (",", "values")


def test_no_float_in_money_paths():
    # Pieces, so this file does not trip a repo-wide grep for the rule it enforces.
    call = re.compile(r"\b" + "flo" + "at" + r"\s*\(")
    annotation = re.compile(r"(?:->|:)\s*" + "flo" + "at" + r"\b")
    root = Path(att.__file__).parent
    for name in ("attachments.py", "chat_tools.py"):
        path = root / name
        if not path.exists():
            continue
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            assert not call.search(line), f"{name}:{n} binary float call"
            assert not annotation.search(line), f"{name}:{n} binary float annotation"
            if "json.loads(" in line:
                assert "parse_float=str" in line, f"{name}:{n} json.loads without parse_float=str"


def test_idr_amount_round_trips_upload_to_ledger(client, api_key, approver_key):
    """1.250.000,00 stays an exact decimal string from the file to the transaction and its audit row (D-12)."""
    from backend import chat_tools, tools
    from backend.db import SessionLocal
    from backend.models import Account, AuditLog, Transaction
    from backend.tests.test_write_endpoints import _cleanup_account

    name, tid = "ZZ39 Round Cash", uuid.uuid4()
    db = SessionLocal()
    _cleanup_account(db, name)
    acct = Account(name=name, type="liquid", currency="IDR")
    db.add(acct)
    db.commit()
    pid = None
    try:
        csv_text = "Tanggal;Keterangan;Debit;Kredit\n25/03/2026;ZZ Sewa;1.250.000,00;\n"
        r = client.post(f"/threads/{tid}/attachments", headers={"MONAI_API_KEY": api_key},
                        data={"account_id": acct.id}, files={"file": ("zz39.csv", csv_text.encode(), "text/csv")})
        assert r.status_code == 200 and r.json()["status"] == "ok", r.text
        aid = r.json()["attachment_id"]
        assert db.execute(text("SELECT rows->0->>'amount' FROM attachments WHERE id = :a"), {"a": aid}).scalar() == "-1250000.00"

        token = tools.CURRENT_THREAD_ID.set(tid)
        try:
            pid = chat_tools.propose_statement_rows(aid)["proposal_id"]
        finally:
            tools.CURRENT_THREAD_ID.reset(token)
        payload = db.execute(text("SELECT payload FROM proposals WHERE id = :i"), {"i": pid}).scalar()
        assert payload["rows"][0]["after"]["amount"] == "-1250000.00"

        r = client.post(f"/proposals/{pid}/approve", headers={"MONAI_APPROVER_KEY": approver_key})
        assert r.status_code == 200, r.text
        db.expire_all()
        tx = db.query(Transaction).filter(Transaction.account_id == acct.id).one()
        assert tx.amount == Decimal("-1250000.00") and tx.amount.as_tuple().exponent == -2
        after = db.query(AuditLog).filter(AuditLog.entity == "transaction", AuditLog.entity_id == tx.id).one().after
        assert after["amount"] == "-1250000.00" and after["attachment_id"] == aid and after["sha256"]
    finally:
        db.rollback()
        if pid:
            db.execute(text("UPDATE proposals SET supersedes_id = NULL WHERE id = :i"), {"i": pid})
            db.execute(text("DELETE FROM proposals WHERE id = :i"), {"i": pid})
        db.execute(text("DELETE FROM threads WHERE id = :t"), {"t": tid})
        db.commit()
        _cleanup_account(db, name)
        db.close()
