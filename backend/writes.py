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

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.importer import _get_or_create_account
from backend.models import Account, AuditLog, Holding, Platform, PortfolioEvent, PriceCache, Transaction
from backend.portfolio import recompute_holding_from_events


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


def apply_add_platform(db: Session, after: dict) -> Platform:
    """Insert a new investment platform (D-12)."""
    plat = Platform(
        name=after["name"],
        kind=after.get("kind"),
    )
    db.add(plat)
    db.flush()  # LOAD-BEARING: populates plat.id before the AuditLog row below
    db.add(AuditLog(entity="platform", entity_id=plat.id, operation="add",
                    before=None, after=after))
    return plat


def apply_edit_platform(db: Session, platform_id: int, after: dict, before: dict | None) -> Platform:
    """Partial-update an existing platform. None fields in `after` are left unchanged."""
    plat = db.get(Platform, platform_id)
    if plat is None:
        raise ValueError(f"Platform {platform_id} not found during confirm")
    if after.get("name") is not None:
        plat.name = after["name"]
    if after.get("kind") is not None:
        plat.kind = after["kind"]
    db.add(AuditLog(entity="platform", entity_id=platform_id, operation="edit",
                    before=before, after=after))
    return plat


def apply_delete_platform(db: Session, platform_id: int, before: dict | None, reassign_to: int | None = None) -> int:
    """Delete a platform, optionally reassigning its holdings first (D-12).

    When `reassign_to` is provided, dependent holdings are moved to that
    platform (via a single parameterized UPDATE) BEFORE the platform is
    deleted, and the reassignment target + row count are recorded in the
    single AuditLog row this function writes — mirroring apply_delete_account
    exactly (WARNING 1 fix), only the reassigned column is holdings.platform_id.
    Returns the reassignment count (0 when reassign_to is None).
    """
    reassigned_count = 0
    audit_after: dict | None = None

    if reassign_to is not None:
        result = db.execute(
            text("UPDATE holdings SET platform_id = :reassign_to WHERE platform_id = :pid"),
            {"reassign_to": reassign_to, "pid": platform_id},
        )
        reassigned_count = result.rowcount
        audit_after = {"reassign_to": reassign_to, "reassigned_count": reassigned_count}

    plat = db.get(Platform, platform_id)
    if plat is not None:
        db.delete(plat)
    db.add(AuditLog(entity="platform", entity_id=platform_id, operation="delete",
                    before=before, after=audit_after))
    return reassigned_count


def apply_add_portfolio_event(db: Session, after: dict) -> PortfolioEvent:
    """Insert a buy/sell/dividend event, then recompute the holding (D-01/INV-07).

    `portfolio_events` is the source of truth for a position (D-01). After the
    row is inserted + audited, `recompute_holding_from_events` re-derives the
    holding's quantity/avg_cost from the full ledger so the position always
    falls out of the events, never a mutable running total. Money goes through
    `Decimal(str(...))` (FND-03). Does NOT commit — caller owns the transaction.

    NOTE: input validation (event_type ∈ {buy,sell,dividend}, positive
    quantity/price) happens at the schema boundary (PortfolioEventCreate) BEFORE
    this runs — the recompute never sanitizes its own inputs (T-05-03-EVT).
    """
    ev = PortfolioEvent(
        date=date.fromisoformat(after["date"]) if after.get("date") else datetime.now(timezone.utc).date(),
        ticker=after["ticker"],
        event_type=after["event_type"],
        quantity=Decimal(str(after["quantity"])),  # LOAD-BEARING: str() before Decimal() avoids float artifacts
        price=Decimal(str(after["price"])),
    )
    db.add(ev)
    db.flush()  # LOAD-BEARING: populates ev.id before the AuditLog row below
    db.add(AuditLog(entity="portfolio_event", entity_id=ev.id, operation="add",
                    before=None, after=after))
    # D-01: position derives from the ledger — recompute after every event.
    recompute_holding_from_events(db, after["ticker"])
    # Set-when-provided: a later event with these fields omitted must NOT clobber
    # an existing platform/asset_type assignment back to null (matches the
    # None-means-keep convention in apply_edit_holding above).
    if after.get("platform_id") is not None or after.get("asset_type") is not None:
        # Session is autoflush=False (db.py) — recompute's newly-added Holding is
        # still pending, so flush before the lookup or the query misses it.
        db.flush()
        holding = db.query(Holding).filter(Holding.ticker == after["ticker"]).one_or_none()
        if holding is not None:
            if after.get("platform_id") is not None:
                holding.platform_id = after["platform_id"]
            if after.get("asset_type") is not None:
                holding.asset_type = after["asset_type"]
    return ev


def apply_add_holding(db: Session, after: dict) -> Holding:
    """D-03 direct override: insert a holding row directly (bypasses the ledger).

    The escape hatch for seeding a position without an event history. Still
    audited (entity="holding") — no write path bypasses the audit helper (D-16).
    Money via Decimal(str(...)). Does NOT commit.
    """
    holding = Holding(
        ticker=after["ticker"],
        quantity=Decimal(str(after["quantity"])),
        avg_cost=Decimal(str(after["avg_cost"])),
        purchase_date=date.fromisoformat(after["purchase_date"]) if after.get("purchase_date") else None,
        currency=after.get("currency", "IDR"),
        asset_type=after.get("asset_type"),
        platform_id=after.get("platform_id"),
        coingecko_id=after.get("coingecko_id"),
    )
    db.add(holding)
    db.flush()  # LOAD-BEARING: populates holding.id before the AuditLog row below
    db.add(AuditLog(entity="holding", entity_id=holding.id, operation="add",
                    before=None, after=after))
    return holding


def apply_edit_holding(db: Session, holding_id: int, after: dict, before: dict | None) -> Holding:
    """D-03 direct override: partial-update a holding. None fields left unchanged."""
    holding = db.get(Holding, holding_id)
    if holding is None:
        raise ValueError(f"Holding {holding_id} not found")
    if after.get("ticker") is not None:
        holding.ticker = after["ticker"]
    if after.get("quantity") is not None:
        holding.quantity = Decimal(str(after["quantity"]))
    if after.get("avg_cost") is not None:
        holding.avg_cost = Decimal(str(after["avg_cost"]))
    if after.get("purchase_date") is not None:
        holding.purchase_date = date.fromisoformat(after["purchase_date"])
    if after.get("asset_type") is not None:
        holding.asset_type = after["asset_type"]
    if after.get("platform_id") is not None:
        holding.platform_id = after["platform_id"]
    if after.get("coingecko_id") is not None:
        holding.coingecko_id = after["coingecko_id"]
    db.add(AuditLog(entity="holding", entity_id=holding_id, operation="edit",
                    before=before, after=after))
    return holding


def apply_delete_holding(db: Session, holding_id: int, before: dict | None) -> None:
    """D-03 direct override: delete a holding by id (no-op if gone) and audit it."""
    holding = db.get(Holding, holding_id)
    if holding is not None:
        db.delete(holding)
    db.add(AuditLog(entity="holding", entity_id=holding_id, operation="delete",
                    before=before, after=None))


def apply_set_price(db: Session, ticker: str, price, source: str = "manual") -> PriceCache:
    """Manual price override (INV-04, D-11): insert a fresh price_cache row.

    Writes a new row rather than mutating — the newest row (by fetched_at) is
    "current price", so a manual override immediately wins and is later replaced
    by the next successful live fetch (D-11). Money via Decimal(str(...)).
    Audited (entity="price_cache", D-16). Does NOT commit — caller owns the txn.
    """
    row = PriceCache(
        ticker=ticker,
        price=Decimal(str(price)),  # LOAD-BEARING: str() before Decimal() avoids float artifacts
        currency="IDR",
        source=source,
    )
    db.add(row)
    db.flush()  # LOAD-BEARING: populates row.id before the AuditLog row below
    db.add(AuditLog(entity="price_cache", entity_id=row.id, operation="add",
                    before=None, after={"ticker": ticker, "price": str(price), "source": source}))
    return row


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
