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
from backend.models import Account, AuditLog, Category, Holding, Platform, PortfolioEvent, PriceCache, Transaction
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
    """Delete a platform, optionally reassigning its holdings + events first (D-12).

    When `reassign_to` is provided, dependent holdings AND their portfolio_events
    are moved to that platform (via parameterized UPDATEs) BEFORE the platform is
    deleted, and the reassignment target + row count are recorded in the single
    AuditLog row this function writes — mirroring apply_delete_account exactly
    (WARNING 1 fix). Returns the holdings reassignment count (0 when reassign_to
    is None).

    Position identity is now (ticker, platform_id) (Quick 260711-rb2), so a
    reassignment that would collide with an existing (ticker, platform_id) on
    the target platform is rejected up front — merging positions is a later
    feature, not an implicit side effect of a platform delete.
    ponytail: reject colliding reassignment; position-merge is a later feature.
    """
    reassigned_count = 0
    audit_after: dict | None = None

    if reassign_to is not None:
        collision = db.execute(
            text(
                "SELECT h1.ticker FROM holdings h1 "
                "JOIN holdings h2 ON h1.ticker = h2.ticker "
                "WHERE h1.platform_id = :pid AND h2.platform_id = :reassign_to"
            ),
            {"pid": platform_id, "reassign_to": reassign_to},
        ).first()
        if collision is not None:
            raise ValueError(
                f"Cannot reassign: {collision[0]} already exists on the target "
                "platform — merge positions manually first."
            )

        result = db.execute(
            text("UPDATE holdings SET platform_id = :reassign_to WHERE platform_id = :pid"),
            {"reassign_to": reassign_to, "pid": platform_id},
        )
        reassigned_count = result.rowcount
        db.execute(
            text("UPDATE portfolio_events SET platform_id = :reassign_to WHERE platform_id = :pid"),
            {"reassign_to": reassign_to, "pid": platform_id},
        )
        audit_after = {"reassign_to": reassign_to, "reassigned_count": reassigned_count}

    plat = db.get(Platform, platform_id)
    if plat is not None:
        db.delete(plat)
    db.add(AuditLog(entity="platform", entity_id=platform_id, operation="delete",
                    before=before, after=audit_after))
    return reassigned_count


def apply_add_portfolio_event(db: Session, after: dict) -> PortfolioEvent:
    """Insert a buy/sell/dividend event, then recompute the position (D-01/INV-07).

    `portfolio_events` is the source of truth for a position (D-01). Position
    identity is (ticker, platform_id) (Quick 260711-rb2) — platform_id is
    required (the schema guarantees it; PortfolioEventCreate.platform_id is a
    non-optional int). After the row is inserted + audited,
    `recompute_holding_from_events` re-derives that position's quantity/avg_cost
    from its own (ticker, platform_id) slice of the ledger so the position
    always falls out of the events, never a mutable running total. Money goes
    through `Decimal(str(...))` (FND-03). Does NOT commit — caller owns the
    transaction.

    NOTE: input validation (event_type ∈ {buy,sell,dividend}, positive
    quantity/price) happens at the schema boundary (PortfolioEventCreate) BEFORE
    this runs — the recompute never sanitizes its own inputs (T-05-03-EVT).

    T-07-02-CUR: one currency per position. If a parent holding already
    exists for (ticker, platform_id), the event's currency is validated
    against it — a mismatch raises ValueError (mapped to 422 at the API
    boundary) rather than silently blending two currencies into one
    average-cost pool. An event that omits its own currency defaults to the
    holding's currency (or "IDR" if this is the position's first event).
    """
    existing_holding = db.query(Holding).filter(
        Holding.ticker == after["ticker"], Holding.platform_id == after["platform_id"]
    ).one_or_none()
    event_currency = after.get("currency")
    if event_currency is None:
        event_currency = existing_holding.currency if existing_holding is not None else "IDR"
    elif existing_holding is not None and event_currency != existing_holding.currency:
        raise ValueError(
            f"event currency {event_currency} does not match holding currency "
            f"{existing_holding.currency} (one currency per position)"
        )

    ev = PortfolioEvent(
        date=date.fromisoformat(after["date"]) if after.get("date") else datetime.now(timezone.utc).date(),
        ticker=after["ticker"],
        event_type=after["event_type"],
        quantity=Decimal(str(after["quantity"])),  # LOAD-BEARING: str() before Decimal() avoids float artifacts
        price=Decimal(str(after["price"])),
        platform_id=after["platform_id"],
        currency=event_currency,
    )
    db.add(ev)
    db.flush()  # LOAD-BEARING: populates ev.id before the AuditLog row below
    db.add(AuditLog(entity="portfolio_event", entity_id=ev.id, operation="add",
                    before=None, after=after))
    # D-01: position derives from the ledger — recompute after every event.
    recompute_holding_from_events(db, after["ticker"], after["platform_id"])
    # Set-when-provided: a later event with asset_type omitted must NOT clobber
    # an existing asset_type assignment back to null (matches the None-means-keep
    # convention in apply_edit_holding above). platform_id is now identity — it's
    # set by the recompute upsert above, not here.
    if after.get("asset_type") is not None:
        # Session is autoflush=False (db.py) — recompute's newly-added Holding is
        # still pending, so flush before the lookup or the query misses it.
        db.flush()
        holding = db.query(Holding).filter(
            Holding.ticker == after["ticker"], Holding.platform_id == after["platform_id"]
        ).one_or_none()
        if holding is not None:
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


# ---------------------------------------------------------------------------
# Categories (CAT-01/CAT-02) — self-referential hierarchy, 3-level depth cap.
# ---------------------------------------------------------------------------

def _category_depth(db: Session, category_id: int | None) -> int:
    """1-based depth of an EXISTING category node (root = 1, child = 2, ...).

    Walks the parent_id chain via bound-parameter SELECTs (the tree is tiny
    — max depth 3 — so no recursive CTE is needed)."""
    depth = 0
    current = category_id
    while current is not None:
        row = db.execute(text("SELECT parent_id FROM categories WHERE id = :id"), {"id": current}).first()
        if row is None:
            break
        depth += 1
        current = row[0]
    return depth


def _subtree_height(db: Session, category_id: int) -> int:
    """Height of category_id's own subtree (0 = leaf, 1 = has children, ...)."""
    children = db.execute(
        text("SELECT id FROM categories WHERE parent_id = :id"), {"id": category_id}
    ).scalars().all()
    if not children:
        return 0
    return 1 + max(_subtree_height(db, c) for c in children)


def _root_kind(db: Session, category_id: int) -> str | None:
    """Walk up the parent chain to the root and return ITS kind (D-03) —
    every non-root category's kind is forced to inherit its root's."""
    current = category_id
    kind = None
    while current is not None:
        row = db.execute(text("SELECT kind, parent_id FROM categories WHERE id = :id"), {"id": current}).first()
        if row is None:
            break
        kind, current = row[0], row[1]
    return kind


def _descendant_ids(db: Session, category_id: int) -> list[int]:
    """category_id plus every descendant's id (includes itself — a
    self-reference is treated as the degenerate case of "own descendant")."""
    ids = [category_id]
    children = db.execute(
        text("SELECT id FROM categories WHERE parent_id = :id"), {"id": category_id}
    ).scalars().all()
    for c in children:
        ids.extend(_descendant_ids(db, c))
    return ids


def apply_add_category(db: Session, after: dict) -> Category:
    """Insert a category (CAT-01). Root requires kind ('expense'|'income') +
    color; a child's kind is always forced to its root's kind (D-03) and its
    color may be omitted to inherit the parent's swatch (D-14). Uniqueness
    ((name, parent_id), or name alone at root) is pre-checked so a violation
    surfaces as a ValueError, not a leaked IntegrityError."""
    name = after["name"]
    parent_id = after.get("parent_id")

    if parent_id is not None:
        parent = db.get(Category, parent_id)
        if parent is None:
            raise ValueError(f"Parent category {parent_id} not found")
        if _category_depth(db, parent_id) >= 3:
            raise ValueError("Category depth cap (3 levels) exceeded — cannot add under a level-3 category")
        kind = _root_kind(db, parent_id)
        color = after.get("color")
    else:
        kind = after.get("kind")
        if kind not in ("expense", "income"):
            raise ValueError("Root category requires kind 'expense' or 'income'")
        color = after.get("color")
        if not color:
            raise ValueError("Root category requires a color")

    collision = db.execute(
        text("SELECT id FROM categories WHERE name = :name AND parent_id IS NOT DISTINCT FROM :pid"),
        {"name": name, "pid": parent_id},
    ).first()
    if collision is not None:
        raise ValueError(f"Category {name!r} already exists under this parent")

    cat = Category(name=name, parent_id=parent_id, kind=kind, color=color, icon=after.get("icon"), is_system=False)
    db.add(cat)
    db.flush()  # LOAD-BEARING: populates cat.id before the AuditLog row below
    db.add(AuditLog(entity="category", entity_id=cat.id, operation="add", before=None, after=after))
    return cat


def apply_edit_category(db: Session, cat_id: int, after: dict, before: dict | None) -> Category:
    """Partial-update a category. `after` keys present (not their None-ness)
    decide what changed — callers must pass exclude_unset, not exclude_none,
    so an explicit parent_id (including a future re-root-to-None case) is
    distinguishable from "not provided". System rows (is_system) reject
    name/parent_id changes but allow color/icon (D-04). Re-parenting
    re-validates the depth cap for the node's WHOLE subtree (not just
    itself) and re-derives kind from the new root."""
    cat = db.get(Category, cat_id)
    if cat is None:
        raise ValueError(f"Category {cat_id} not found")

    renaming = "name" in after and after["name"] is not None and after["name"] != cat.name
    reparenting = "parent_id" in after and after["parent_id"] != cat.parent_id

    if cat.is_system and (renaming or reparenting):
        raise ValueError("System categories (Transfer/Uncategorized) cannot be renamed or re-parented")

    new_name = after["name"] if renaming else cat.name
    new_parent_id = after["parent_id"] if reparenting else cat.parent_id

    if renaming or reparenting:
        collision = db.execute(
            text(
                "SELECT id FROM categories WHERE name = :name AND parent_id IS NOT DISTINCT FROM :pid "
                "AND id != :id"
            ),
            {"name": new_name, "pid": new_parent_id, "id": cat_id},
        ).first()
        if collision is not None:
            raise ValueError(f"Category {new_name!r} already exists under this parent")

    new_kind = cat.kind
    if reparenting:
        height = _subtree_height(db, cat_id)
        if new_parent_id is not None:
            if db.get(Category, new_parent_id) is None:
                raise ValueError(f"Parent category {new_parent_id} not found")
            if new_parent_id in _descendant_ids(db, cat_id):
                raise ValueError("Cannot re-parent a category under itself or its own descendant")
            parent_depth = _category_depth(db, new_parent_id)
            if parent_depth + 1 + height > 3:
                raise ValueError("Category depth cap (3 levels) exceeded by this re-parent")
            new_kind = _root_kind(db, new_parent_id)
        else:
            if 1 + height > 3:
                raise ValueError("Category depth cap (3 levels) exceeded by this re-parent")
            new_kind = after.get("kind") or cat.kind

    cat.name = new_name
    cat.parent_id = new_parent_id
    cat.kind = new_kind
    if "color" in after:
        cat.color = after["color"]
    if "icon" in after:
        cat.icon = after["icon"]

    db.add(AuditLog(entity="category", entity_id=cat_id, operation="edit", before=before, after=after))
    return cat


def apply_delete_category(db: Session, cat_id: int, before: dict | None, reassign_to: int | None = None) -> int:
    """Delete a category, optionally reassigning its TRANSACTIONS first
    (CAT-02). Mirrors apply_delete_account's shape. System rows are always
    rejected. Deleting a category that still has child categories is a
    caller-side precondition (main.py's child_count check) — reassign_to only
    ever moves transactions.category_id, never subcategories, so a category
    with children can never be safely deleted here (the parent_id FK has no
    ondelete and RESTRICTs at the DB level as a backstop). The reassign
    target must exist and must not be the node itself or one of its own
    descendants."""
    cat = db.get(Category, cat_id)
    if cat is None:
        raise ValueError(f"Category {cat_id} not found")
    if cat.is_system:
        raise ValueError("System categories (Transfer/Uncategorized) cannot be deleted")

    reassigned_count = 0
    audit_after: dict | None = None

    if reassign_to is not None:
        if reassign_to in _descendant_ids(db, cat_id):
            raise ValueError("Cannot reassign to the category itself or one of its own descendants")
        target = db.get(Category, reassign_to)
        if target is None:
            raise ValueError(f"Reassign target category {reassign_to} not found")

        result = db.execute(
            text("UPDATE transactions SET category_id = :reassign_to WHERE category_id = :cat_id"),
            {"reassign_to": reassign_to, "cat_id": cat_id},
        )
        reassigned_count = result.rowcount
        audit_after = {"reassign_to": reassign_to, "reassigned_count": reassigned_count}

    db.delete(cat)
    db.add(AuditLog(entity="category", entity_id=cat_id, operation="delete", before=before, after=audit_after))
    return reassigned_count


def apply_rename_category(db: Session, old_name: str, new_name: str) -> int:
    """Rename a category — a single-row UPDATE of categories.name (D-11).
    Resolves old_name to a unique categories row (ambiguous — the same leaf
    name under two different parents — or missing name raises ValueError);
    system rows reject rename. Returns the count of transactions currently
    attached via category_id — INFORMATIONAL only, this touches ZERO
    transaction rows (they follow the rename via the FK, and their legacy
    `transactions.category` string is never touched)."""
    matches = db.execute(
        text("SELECT id, parent_id, is_system FROM categories WHERE name = :name"), {"name": old_name}
    ).fetchall()
    if not matches:
        raise ValueError(f"Category {old_name!r} not found")
    if len(matches) > 1:
        raise ValueError(f"Category name {old_name!r} is ambiguous ({len(matches)} matches) — resolve by id")
    cat_id, parent_id, is_system = matches[0]
    if is_system:
        raise ValueError("System categories (Transfer/Uncategorized) cannot be renamed")

    collision = db.execute(
        text("SELECT id FROM categories WHERE name = :name AND parent_id IS NOT DISTINCT FROM :pid AND id != :id"),
        {"name": new_name, "pid": parent_id, "id": cat_id},
    ).first()
    if collision is not None:
        raise ValueError(f"Category {new_name!r} already exists under this parent")

    affected = int(
        db.execute(text("SELECT COUNT(*) FROM transactions WHERE category_id = :id"), {"id": cat_id}).scalar() or 0
    )
    db.execute(text("UPDATE categories SET name = :new WHERE id = :id"), {"new": new_name, "id": cat_id})
    db.add(AuditLog(entity="category", entity_id=cat_id, operation="rename",
                    before={"category": old_name}, after={"category": new_name}))
    return affected


def apply_merge_category(db: Session, from_name: str, into_name: str) -> int:
    """Merge one category's transactions into another (D-11). Resolves both
    names to unique categories rows (ambiguous/missing -> ValueError); a
    source with child categories is rejected (merge subcategories first —
    keeps the depth-cap invariant simple). Moves transactions.category_id
    via one bound-parameter UPDATE, deletes the source row, and writes one
    AuditLog row. Returns the moved transaction count."""
    from_matches = db.execute(
        text("SELECT id, is_system FROM categories WHERE name = :name"), {"name": from_name}
    ).fetchall()
    if not from_matches:
        raise ValueError(f"Category {from_name!r} not found")
    if len(from_matches) > 1:
        raise ValueError(f"Category name {from_name!r} is ambiguous ({len(from_matches)} matches) — resolve by id")
    from_id, from_is_system = from_matches[0]
    if from_is_system:
        raise ValueError("System categories (Transfer/Uncategorized) cannot be merged")

    into_matches = db.execute(
        text("SELECT id FROM categories WHERE name = :name"), {"name": into_name}
    ).fetchall()
    if not into_matches:
        raise ValueError(f"Category {into_name!r} not found")
    if len(into_matches) > 1:
        raise ValueError(f"Category name {into_name!r} is ambiguous ({len(into_matches)} matches) — resolve by id")
    into_id = into_matches[0][0]

    child_count = int(
        db.execute(text("SELECT COUNT(*) FROM categories WHERE parent_id = :id"), {"id": from_id}).scalar() or 0
    )
    if child_count > 0:
        raise ValueError(f"Category {from_name!r} has subcategories — merge them first")

    result = db.execute(
        text("UPDATE transactions SET category_id = :into WHERE category_id = :from_id"),
        {"into": into_id, "from_id": from_id},
    )
    moved = result.rowcount
    db.execute(text("DELETE FROM categories WHERE id = :id"), {"id": from_id})
    db.add(AuditLog(entity="category", entity_id=from_id, operation="merge",
                    before={"category": from_name}, after={"category": into_name}))
    return moved
