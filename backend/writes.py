"""
Shared write mutations for monai (D-02).

This module is the single source of truth for every data-mutating operation
in the app. It is called by BOTH the agent propose->confirm path
(backend/main.py:_execute_proposal_payload) and the direct REST endpoints
(Plan 03) so that audit-log writes (CHAT-06) and Decimal handling (FND-03)
can never diverge between the two call paths.

Every apply_* function:
  - performs exactly one entity mutation (add/edit/delete/rename/merge)
  - writes exactly one AuditLog row recording before/after state
  - never commits the session itself — the caller owns the transaction boundary
"""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.importer import _get_or_create_account
from backend.models import Account, AuditLog, Transaction


def apply_add_transaction(db: Session, after: dict) -> Transaction:
    """Insert a new transaction, resolving/creating its account by name."""
    account_name = after.get("account", "Unknown")
    currency = after.get("currency", "IDR")
    acc = _get_or_create_account(db, account_name, currency)
    tx = Transaction(
        date=datetime.fromisoformat(after["date"]) if after.get("date") else datetime.now(timezone.utc),
        amount=Decimal(str(after["amount"])),  # LOAD-BEARING: str() before Decimal() avoids float artifacts
        currency=currency,
        category=after.get("category"),
        raw_category=after.get("category"),
        merchant=after.get("merchant"),
        notes=after.get("notes"),
        account_id=acc.id,
        is_transfer=after.get("is_transfer", False),
    )
    db.add(tx)
    db.flush()  # LOAD-BEARING: populates tx.id before the AuditLog row below
    db.add(AuditLog(entity="transaction", entity_id=tx.id, operation="add",
                    before=None, after=after))
    return tx


def apply_edit_transaction(db: Session, tx_id: int, after: dict, before: dict | None) -> Transaction:
    """Partial-update an existing transaction. None fields in `after` are left unchanged."""
    tx = db.get(Transaction, tx_id)
    if tx is None:
        raise ValueError(f"Transaction {tx_id} not found during confirm")
    if after.get("category") is not None:
        tx.category = after["category"]
    if after.get("merchant") is not None:
        tx.merchant = after["merchant"]
    if after.get("amount") is not None:
        tx.amount = Decimal(str(after["amount"]))  # LOAD-BEARING: str() before Decimal() avoids float artifacts
    if after.get("notes") is not None:
        tx.notes = after["notes"]
    db.add(AuditLog(entity="transaction", entity_id=tx_id, operation="edit",
                    before=before, after=after))
    return tx


def apply_delete_transaction(db: Session, tx_id: int, before: dict | None) -> None:
    """Delete a transaction by id (no-op if already gone) and audit it."""
    tx = db.get(Transaction, tx_id)
    if tx is not None:
        db.delete(tx)
    db.add(AuditLog(entity="transaction", entity_id=tx_id, operation="delete",
                    before=before, after=None))


def apply_add_account(db: Session, after: dict) -> Account:
    """Insert a new account."""
    acc = Account(
        name=after["name"],
        type=after.get("type"),
        currency=after.get("currency"),
    )
    db.add(acc)
    db.flush()  # LOAD-BEARING: populates acc.id before the AuditLog row below
    db.add(AuditLog(entity="account", entity_id=acc.id, operation="add",
                    before=None, after=after))
    return acc


def apply_edit_account(db: Session, acc_id: int, after: dict, before: dict | None) -> Account:
    """Partial-update an existing account. None fields in `after` are left unchanged."""
    acc = db.get(Account, acc_id)
    if acc is None:
        raise ValueError(f"Account {acc_id} not found during confirm")
    if after.get("name") is not None:
        acc.name = after["name"]
    if after.get("type") is not None:
        acc.type = after["type"]
    if after.get("currency") is not None:
        acc.currency = after["currency"]
    db.add(AuditLog(entity="account", entity_id=acc_id, operation="edit",
                    before=before, after=after))
    return acc


def apply_delete_account(db: Session, acc_id: int, before: dict | None, reassign_to: int | None = None) -> int:
    """Delete an account, optionally reassigning its transactions first.

    When `reassign_to` is provided, dependent transactions are moved to that
    account (via a single parameterized UPDATE) BEFORE the account is
    deleted, and the reassignment target + row count are recorded in the
    single AuditLog row this function writes — so the reassignment is fully
    audited in one place rather than as an un-audited inline bulk update in
    the calling endpoint (WARNING 1 fix). Returns the reassignment count
    (0 when reassign_to is None, i.e. a plain audited delete).
    """
    reassigned_count = 0
    audit_after: dict | None = None

    if reassign_to is not None:
        result = db.execute(
            text("UPDATE transactions SET account_id = :reassign_to WHERE account_id = :acc_id"),
            {"reassign_to": reassign_to, "acc_id": acc_id},
        )
        reassigned_count = result.rowcount
        audit_after = {"reassign_to": reassign_to, "reassigned_count": reassigned_count}

    acc = db.get(Account, acc_id)
    if acc is not None:
        db.delete(acc)
    db.add(AuditLog(entity="account", entity_id=acc_id, operation="delete",
                    before=before, after=audit_after))
    return reassigned_count


def apply_rename_category(db: Session, old_name: str, new_name: str) -> int:
    """Rename a category across all transactions. Returns affected row count."""
    result = db.execute(
        text("UPDATE transactions SET category = :new WHERE category = :old"),
        {"new": new_name, "old": old_name},
    )
    db.add(AuditLog(entity="category", entity_id=None, operation="rename",
                    before={"category": old_name}, after={"category": new_name}))
    return result.rowcount


def apply_merge_category(db: Session, from_name: str, into_name: str) -> int:
    """Merge one category into another across all transactions. Returns affected row count."""
    result = db.execute(
        text("UPDATE transactions SET category = :into WHERE category = :from"),
        {"into": into_name, "from": from_name},
    )
    db.add(AuditLog(entity="category", entity_id=None, operation="merge",
                    before={"category": from_name}, after={"category": into_name}))
    return result.rowcount
