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

from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.importer import _get_or_create_account
from backend.models import (
    Account, AuditLog, Category, ClosedPosition, Holding, Platform, PortfolioEvent, PriceCache, Transaction,
)
from backend.portfolio import recompute_holding_from_events

# Mirrors migration 020's CHECK on accounts.currency; fx.py names only BASE.
ACCOUNT_CURRENCIES = ("IDR", "USD")


def resolve_category_id(db: Session, name: str | None) -> int:
    """Resolve a category name to its id (D-08 dual-write helper, CAT-03).

    Exact (untrimmed) match on categories.name at any level in the tree.
    Multiple matches (the same name under two different parents) -> the
    lowest id, deterministically — a documented tie-break, never a guess or
    a raise. None, empty string, or no match at all -> the Uncategorized
    system row's id (D-04/Pitfall 2): unknown or missing categories are
    never left NULL and never raise an IntegrityError; the original string
    (if any) is still preserved via the caller's legacy `category` column,
    so nothing is lost.
    """
    if name:
        row = db.execute(
            text("SELECT id FROM categories WHERE name = :name ORDER BY id ASC LIMIT 1"),
            {"name": name},
        ).first()
        if row is not None:
            return row[0]
    uncategorized = db.execute(
        text("SELECT id FROM categories WHERE name = 'Uncategorized' AND is_system = true LIMIT 1")
    ).first()
    if uncategorized is None:
        raise ValueError("Uncategorized system category not found — check migration 009 seeding")
    return uncategorized[0]


def apply_add_transaction(db: Session, after: dict) -> Transaction:
    """Insert a new transaction, resolving/creating its account by name.

    The account decides the currency (D-01): an absent/blank payload currency
    means the account's; a different one is refused with ValueError (the
    composite FK in migration 020 would otherwise surface it as a 500).
    """
    account_name = after.get("account", "Unknown")
    # Check the currency BEFORE creating the account, so a refusal never leaves a stray flushed row.
    existing = db.query(Account).filter(Account.name == account_name).one_or_none()
    target = existing.currency if existing is not None else "IDR"  # auto-created accounts are IDR
    given = (after.get("currency") or "").strip().upper()
    if given and given != target:
        raise ValueError(f"Account '{account_name}' is in {target}; this row is in {given}")
    acc = existing or _get_or_create_account(db, account_name)
    currency = acc.currency
    category_name = after.get("category")
    tx = Transaction(
        date=datetime.fromisoformat(after["date"]) if after.get("date") else datetime.now(timezone.utc),
        amount=Decimal(str(after["amount"])),  # LOAD-BEARING: str() before Decimal() avoids float artifacts
        currency=currency,
        category=category_name,
        raw_category=category_name,
        category_id=resolve_category_id(db, category_name),  # D-08 dual-write
        merchant=after.get("merchant"),
        notes=after.get("notes"),
        account_id=acc.id,
        is_transfer=after.get("is_transfer", False),
    )
    db.add(tx)
    db.flush()  # LOAD-BEARING: populates tx.id before the AuditLog row below
    db.add(AuditLog(entity="transaction", entity_id=tx.id, operation="add",
                    before=None, after={**after, "currency": currency}))
    return tx


def apply_add_balance_adjustment(
    db: Session, account_id: int, target_balance, as_of: date | None = None
) -> Transaction:
    """Reconcile an account's derived balance to `target_balance` (ACCT-02, D-07, D-08).

    Writes ONE 'Adjustment'-tagged Transaction whose amount is the delta
    between `target_balance` and the account's current derived balance — a
    FRESH, UNFILTERED SUM(amount) over ALL of the account's transactions,
    transfer rows included (Finding 2: `tools.py:account_balances` excludes
    is_transfer rows and is the WRONG basis for this delta). The row is
    tagged `is_transfer=True` so it is excluded from spending/income/net
    cashflow totals (D-08) while still counting toward the unfiltered
    derived-balance SUM. No stored balance column is written — the balance
    stays derived.

    `as_of` (D-08, revised decision 1, 2026-09-24) is an optional back-dated
    anchor: the target balance is reconciled against the account's derived
    balance as of the CLOSE of that date (inclusive), and the adjustment row
    is written dated `as_of` instead of now. This lets the user enter a real
    historical statement balance and close an adjustment window for
    `backend/reconstruction.py`'s honesty model (RECON-03). If the account
    has a later Adjustment (the first one dated after `as_of`), that
    adjustment is a FIXED amount that already absorbed the same drift —
    without correction the drift would be double-counted into every balance
    from `as_of` onward, including `net_worth()`. So that later Adjustment's
    amount is reduced by this call's delta X, in the same session
    transaction and audit-logged as an 'edit' (via `apply_edit_transaction`),
    which keeps the balance at and after it — and the all-time sum —
    unchanged: only the window [as_of, that adjustment's date) shifts, which
    is the intended historical correction. An `as_of` on the same day as an
    existing Adjustment on this account is rejected before any write —
    same-day anchor ordering is ambiguous. When `as_of` is omitted, or no
    later Adjustment exists, behaviour is byte-for-byte identical to before
    D-08: the all-time unfiltered SUM, and today's date via
    `apply_add_transaction`'s `datetime.now(timezone.utc)` fallback. The
    caller owns the transaction boundary — this function never commits.

    Deliberate scope boundary: `as_of` is a Python-level capability only. No
    REST endpoint passes it — both `backend/main.py` call sites omit it, and
    grepping main.py for `as_of` finds nothing — and it is intentionally
    absent from `backend.tools.propose_add_balance_adjustment`, the
    agent-facing wrapper — that wrapper's signature is introspected to build
    both the LlamaIndex and the MCP tool schemas, so adding a parameter
    there would silently hand the model a capability to rewrite financial
    history.
    """
    next_adjustment = None
    if as_of is not None:
        if not isinstance(as_of, date):
            raise ValueError("as_of must be a datetime.date")
        # LOAD-BEARING: transactions.date is a DateTime, not a bare Date, so a
        # same-day row recorded any time after midnight would be silently
        # dropped by a direct `date <= as_of` comparison against that
        # datetime column. Using an exclusive next-day bound instead keeps
        # the whole row set through the close of `as_of` (inclusive
        # semantics) while matching this codebase's half-open `date <
        # :bound` convention used everywhere else.
        as_of_excl = as_of + timedelta(days=1)

        # Revised decision 1: find the first later Adjustment on this
        # account, if any, BEFORE any mutation — every raising check (this
        # lookup's same-day rejection, and apply_edit_transaction's own
        # paired-leg guard below) must run before the first write, so a
        # failure leaves no partial writes.
        next_adjustment = db.execute(
            text(
                "SELECT id, date::date AS adj_date, amount FROM transactions "
                "WHERE account_id = :id AND category = 'Adjustment' "
                "AND date::date >= :as_of ORDER BY date, id LIMIT 1"
            ),
            {"id": account_id, "as_of": as_of},
        ).first()
        if next_adjustment is not None and next_adjustment.adj_date == as_of:
            raise ValueError(
                f"as_of {as_of.isoformat()} is the same day as an existing adjustment "
                "on this account — same-day anchor ordering is ambiguous; "
                "choose a different date"
            )

        current = db.execute(
            text(
                "SELECT COALESCE(SUM(amount), 0) FROM transactions "
                "WHERE account_id = :id AND date < :as_of_excl"
            ),
            {"id": account_id, "as_of_excl": as_of_excl},
        ).scalar()
    else:
        current = db.execute(
            text("SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE account_id = :id"),
            {"id": account_id},
        ).scalar()
    # Quantize to the column's 2 dp so the audit row records what is stored (WR-03).
    delta = (Decimal(str(target_balance)) - Decimal(str(current))).quantize(Decimal("0.01"), ROUND_HALF_UP)
    account = db.get(Account, account_id)
    after = {
        "account": account.name if account is not None else "Unknown",
        "currency": account.currency if account is not None else "IDR",
        # LOAD-BEARING: str(), not the Decimal itself — AuditLog JSON-serializes
        # `after`, and apply_add_transaction re-applies Decimal(str(x)) on its own.
        "amount": str(delta),
        "category": "Adjustment",
        "is_transfer": True,
    }
    if as_of is not None:
        after["date"] = as_of.isoformat()
        if next_adjustment is not None:
            # The later Adjustment already absorbed this drift as a fixed
            # amount — subtract delta so the balance at and after it does
            # not move (revised decision 1). str() amounts only: AuditLog
            # JSON-serializes before/after, and Decimal isn't serializable.
            next_amount = Decimal(str(next_adjustment.amount))
            apply_edit_transaction(
                db,
                next_adjustment.id,
                after={"amount": str(next_amount - delta)},
                before={"amount": str(next_amount)},
            )
    return apply_add_transaction(db, after)


def apply_edit_transaction(
    db: Session, tx_id: int, after: dict, before: dict | None, allow_paired: bool = False
) -> Transaction:
    """Partial-update an existing transaction. None fields in `after` are left unchanged."""
    tx = db.get(Transaction, tx_id)
    if tx is None:
        raise ValueError(f"Transaction {tx_id} not found during confirm")
    if tx.transfer_pair_id is not None and not allow_paired:
        raise ValueError(
            f"Transaction {tx_id} is one leg of transfer pair {tx.transfer_pair_id} — "
            "use the pair-aware transfer function, or pass allow_paired=True (D-04)"
        )
    if after.get("category") is not None:
        tx.category = after["category"]
        tx.category_id = resolve_category_id(db, after["category"])  # D-08 dual-write, re-resolve on change
    if after.get("merchant") is not None:
        tx.merchant = after["merchant"]
    if after.get("amount") is not None:
        tx.amount = Decimal(str(after["amount"]))  # LOAD-BEARING: str() before Decimal() avoids float artifacts
    if after.get("notes") is not None:
        tx.notes = after["notes"]
    db.add(AuditLog(entity="transaction", entity_id=tx_id, operation="edit",
                    before=before, after=after))
    return tx


def apply_delete_transaction(db: Session, tx_id: int, before: dict | None, allow_paired: bool = False) -> None:
    """Delete a transaction by id (no-op if already gone) and audit it."""
    tx = db.get(Transaction, tx_id)
    if tx is not None:
        if tx.transfer_pair_id is not None and not allow_paired:
            raise ValueError(
                f"Transaction {tx_id} is one leg of transfer pair {tx.transfer_pair_id} — "
                "use the pair-aware transfer function, or pass allow_paired=True (D-04)"
            )
        db.delete(tx)
    db.add(AuditLog(entity="transaction", entity_id=tx_id, operation="delete",
                    before=before, after=None))


def _transaction_snapshot(tx: Transaction) -> dict:
    """Audit `before` snapshot for a transaction row (same shape the REST
    delete endpoint builds inline) — used for sibling legs deleted as a pair."""
    return {
        "id": tx.id,
        "date": tx.date.isoformat() if tx.date else None,
        "amount": str(tx.amount),
        "currency": tx.currency,
        "category": tx.category,
        "merchant": tx.merchant,
        "notes": tx.notes,
        "account_id": tx.account_id,
        "is_transfer": tx.is_transfer,
    }


def apply_delete_transaction_or_pair(db: Session, tx_id: int, before: dict | None) -> list[int]:
    """Delete a transaction; if it is one leg of a transfer, delete BOTH legs.

    The pair-aware wrapper the D-04 guard in apply_delete_transaction points to
    (Phase 16 UAT#3): deleting a single leg would leave a half-transfer with
    money unconserved, so a transfer is always deleted whole. The single-leg
    guard/primitive stays intact — this composes it with allow_paired=True and
    audits every leg. Returns the deleted ids. Does NOT commit (caller owns the
    transaction boundary, D-01).
    """
    tx = db.get(Transaction, tx_id)
    if tx is not None and tx.transfer_pair_id is not None:
        legs = db.query(Transaction).filter(
            Transaction.transfer_pair_id == tx.transfer_pair_id
        ).all()
        for leg in legs:
            leg_before = before if leg.id == tx_id else _transaction_snapshot(leg)
            apply_delete_transaction(db, leg.id, leg_before, allow_paired=True)
        return [leg.id for leg in legs]
    apply_delete_transaction(db, tx_id, before)
    return [tx_id]


def currency_of_account(db: Session, name: str) -> str:
    """Currency of the account called `name` (exact-name lookup).

    A missing account reads as "IDR": apply_add_transaction would auto-create
    it as IDR, so that is the currency its leg would carry.
    """
    acc = db.query(Account).filter(Account.name == name).one_or_none()
    return acc.currency if acc is not None else "IDR"


def _positive_amount(value, label: str) -> Decimal:
    """Parse a second amount: finite and > 0, else ValueError (T-45-01)."""
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise ValueError(f"{label} must be a positive amount")
    if not amount.is_finite() or amount <= 0:
        raise ValueError(f"{label} must be a positive amount")
    return amount


def apply_add_transfer(
    db: Session, leg_a_after: dict, leg_b_after: dict, to_amount=None
) -> tuple[Transaction, Transaction]:
    """Insert a paired liquid->liquid transfer (XFER-01/D-03/D-09, MOVE-01/D-06).

    Composes `apply_add_transaction` twice — one call per leg — so each leg
    gets account resolution by name, the Decimal money idiom, and its own
    AuditLog row (D-02) for free from the primitive; this function writes no
    extra audit row. Each leg keeps its own amount + currency independently
    (D-09 dual-currency, no new columns). After both legs flush (the
    primitive already flushes to populate `.id`), both legs' transfer_pair_id
    is set to leg A's own id (shared-group-id convention, D-03 — matches
    migration 011's `min(id)` scheme). Does NOT commit — caller owns the
    single transaction boundary (D-01).

    Two accounts in different currencies need BOTH amounts: leg A's amount is
    what leaves the from account, `to_amount` (unsigned, in the destination's
    currency) is what arrives. Neither is computed from the other and no rate
    is stored (MOVE-04). Two accounts in the same currency move one amount, so
    a `to_amount` that differs is refused. Every refusal happens before either
    leg is written, so it leaves nothing behind.
    """
    given = None if to_amount is None else _positive_amount(to_amount, "to_amount")
    a = currency_of_account(db, leg_a_after.get("account", "Unknown"))
    b = currency_of_account(db, leg_b_after.get("account", "Unknown"))
    if a != b:
        if given is None:
            raise ValueError(f"Transfers between {a} and {b} accounts need both amounts")
        leg_b_after = {**leg_b_after, "amount": str(given)}
    elif given is not None and given != abs(Decimal(str(leg_a_after["amount"]))):
        raise ValueError(f"A transfer between two {a} accounts moves one amount; record a fee as a separate expense")
    leg_a = apply_add_transaction(db, {**leg_a_after, "is_transfer": True})
    leg_b = apply_add_transaction(db, {**leg_b_after, "is_transfer": True})
    leg_a.transfer_pair_id = leg_a.id
    leg_b.transfer_pair_id = leg_a.id
    return leg_a, leg_b


def currency_of_holding(db: Session, ticker: str, platform_id: int) -> str | None:
    """Currency of the existing (ticker, platform_id) position, or None when there is none."""
    holding = db.query(Holding).filter(
        Holding.ticker == ticker, Holding.platform_id == platform_id
    ).one_or_none()
    return holding.currency if holding is not None else None


def _funded_event_currency(db: Session, after: dict) -> str:
    """Event currency of a funded trade: explicit, else the holding's, else the cash account's (D-02).

    Checked before the cash leg is written, so a position mismatch leaves nothing behind.
    """
    explicit = (after.get("event_currency") or "").strip()
    ev_ccy = (
        (_account_currency(explicit) if explicit else None)
        or currency_of_holding(db, after["ticker"], after["platform_id"])
        or currency_of_account(db, after["source_account_name"])
    )
    _check_position_target(db, after["ticker"], after["platform_id"], ev_ccy)
    return ev_ccy


def apply_add_funded_buy(db: Session, after: dict) -> dict:
    """Insert a funded 'buy' — cash leg + portfolio event, one commit boundary (XFER-03).

    `after` carries both the cash side (source_account_name, optional
    cash_currency, cash_amount) and the investment side (ticker, quantity,
    price, platform_id, optional event_currency) as one dict (locked contract,
    Plan 13-01). The cash leg DEBITS the liquid source account (negative
    amount, is_transfer=True, category='Investment' — the human-readable
    disambiguator that keeps the leg out of spending/income totals while
    remaining distinguishable from a plain transfer, D-08/Open-Question-2) in
    the account's own currency; a given cash_currency that differs is refused,
    never relabelled. The event currency defaults to the existing position's,
    else the account's (D-02). The investment leg is a 'buy' PortfolioEvent,
    which already triggers `recompute_holding_from_events` internally (D-06) —
    this function never hand-rolls a holding update. The two amounts are
    stored as entered, never cross-checked against each other, and no live FX
    rate is ever called here (D-10); `recompute_holding_from_events` resolves
    historical, date-keyed rates itself when it needs an IDR valuation. Does
    NOT commit.
    """
    ev_ccy = _funded_event_currency(db, after)
    cash_amount = -abs(after["cash_amount"])  # buy DEBITS the source; Decimal() happens inside apply_add_transaction
    tx = apply_add_transaction(db, {
        "account": after["source_account_name"],
        "amount": cash_amount,
        "currency": after.get("cash_currency"),
        "category": "Investment",
        "is_transfer": True,
        "date": after.get("date"),
        "notes": after.get("notes"),
    })
    ev = apply_add_portfolio_event(db, {
        "ticker": after["ticker"],
        "event_type": "buy",
        "quantity": after["quantity"],
        "price": after["price"],
        "platform_id": after["platform_id"],
        "currency": ev_ccy,
        "date": after.get("date"),
        "asset_type": after.get("asset_type"),
    })
    ev.source_account_id = tx.account_id
    ev.transaction_id = tx.id  # both rows flushed by their primitives
    return {"transaction": tx, "portfolio_event": ev}


def apply_add_funded_sell(db: Session, after: dict) -> dict:
    """Insert a funded 'sell' — cash leg + portfolio event, one commit boundary (XFER-03).

    Near-mirror of `apply_add_funded_buy`: the cash leg CREDITS the liquid
    destination account (positive amount) instead of debiting it, and the
    investment leg is a 'sell' PortfolioEvent (which already realizes P&L via
    `recompute_holding_from_events`, D-06 — never hand-rolled here). Same
    is_transfer/category tagging, currency handling (cash in the account's
    currency, event currency per D-02), and no-live-FX contract (D-10) as the
    buy side. A sell that takes the ledger quantity to exactly zero also closes
    the position (`close_position_if_flat`); the cash leg is kept. Does NOT commit.
    """
    ev_ccy = _funded_event_currency(db, after)
    cash_amount = abs(after["cash_amount"])  # sell CREDITS the destination; Decimal() happens inside apply_add_transaction
    tx = apply_add_transaction(db, {
        "account": after["source_account_name"],
        "amount": cash_amount,
        "currency": after.get("cash_currency"),
        "category": "Investment",
        "is_transfer": True,
        "date": after.get("date"),
        "notes": after.get("notes"),
    })
    ev = apply_add_portfolio_event(db, {
        "ticker": after["ticker"],
        "event_type": "sell",
        "quantity": after["quantity"],
        "price": after["price"],
        "platform_id": after["platform_id"],
        "currency": ev_ccy,
        "date": after.get("date"),
        "asset_type": after.get("asset_type"),
    })
    ev.source_account_id = tx.account_id
    ev.transaction_id = tx.id  # both rows flushed by their primitives
    # A sell that leaves exactly zero closes the position; ev is deleted then.
    closed = close_position_if_flat(db, after["ticker"], after["platform_id"])
    return {"transaction": tx, "portfolio_event": ev, "closed_position": closed}


def _account_currency(value) -> str:
    """Trim + upper; null/blank -> IDR; anything outside ACCOUNT_CURRENCIES is refused (D-01)."""
    currency = (value or "").strip().upper() or "IDR"
    if currency not in ACCOUNT_CURRENCIES:
        raise ValueError("Account currency must be one of " + ", ".join(ACCOUNT_CURRENCIES))
    return currency


def _refuse_taken_account_name(db: Session, name: str, acc_id: int | None = None) -> None:
    """A name another account holds -> ValueError (422), not the unique index's 500."""
    taken = db.query(Account).filter(Account.name == name, Account.id != acc_id).first()
    if taken is not None:
        raise ValueError(f"An account named '{name}' already exists")


def apply_add_account(db: Session, after: dict) -> Account:
    """Insert a new account (currency IDR or USD; blank -> IDR)."""
    currency = _account_currency(after.get("currency"))
    _refuse_taken_account_name(db, after["name"])
    acc = Account(
        name=after["name"],
        type=after.get("type"),
        currency=currency,
    )
    db.add(acc)
    db.flush()  # LOAD-BEARING: populates acc.id before the AuditLog row below
    db.add(AuditLog(entity="account", entity_id=acc.id, operation="add",
                    before=None, after={**after, "currency": currency}))
    return acc


def apply_edit_account(db: Session, acc_id: int, after: dict, before: dict | None) -> Account:
    """Partial-update an existing account. None fields in `after` are left unchanged."""
    acc = db.get(Account, acc_id)
    if acc is None:
        raise ValueError(f"Account {acc_id} not found during confirm")
    # Blank means "unchanged" on edit, not IDR (that default is for create only).
    new_currency = _account_currency(after["currency"]) if (after.get("currency") or "").strip() else None
    # Compare against the stored currency, not `before`: chat edits always carry the
    # current currency. Migration 020's composite FK is only the race backstop.
    if new_currency is not None and new_currency != acc.currency:
        n = int(db.execute(text("SELECT COUNT(*) FROM transactions WHERE account_id = :id"), {"id": acc_id}).scalar() or 0)
        if n:
            raise ValueError(f"Account '{acc.name}' has {n} record(s); its currency can't change")
    if after.get("name") is not None:
        _refuse_taken_account_name(db, after["name"], acc_id)
        acc.name = after["name"]
    if after.get("type") is not None:
        acc.type = after["type"]
    if new_currency is not None:
        acc.currency = new_currency
    # A blank currency means "unchanged", so it stays out of the audit.
    audit_after = {k: v for k, v in after.items() if k != "currency"}
    if new_currency is not None:
        audit_after["currency"] = new_currency
    db.add(AuditLog(entity="account", entity_id=acc_id, operation="edit",
                    before=before, after=audit_after))
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

    Portfolio events pointing at the account as their funding source follow the
    reassignment. Without one the account has no transactions left, so those
    links lead to no cash and are cleared; either way the foreign key can't
    block the delete with a 500.
    """
    reassigned_count = 0
    audit_after: dict | None = None

    if reassign_to is not None:
        if reassign_to == acc_id:
            raise ValueError("Can't reassign an account's records to itself")
        dst = db.get(Account, reassign_to)
        if dst is None:
            raise ValueError(f"Reassign target account {reassign_to} not found")
        src = db.get(Account, acc_id)
        if src is not None and src.currency != dst.currency:
            raise ValueError(f"Can't move {src.currency} records into {dst.currency} account '{dst.name}'")
        result = db.execute(
            text("UPDATE transactions SET account_id = :reassign_to WHERE account_id = :acc_id"),
            {"reassign_to": reassign_to, "acc_id": acc_id},
        )
        reassigned_count = result.rowcount
        audit_after = {"reassign_to": reassign_to, "reassigned_count": reassigned_count}

    event_links = db.execute(
        text("UPDATE portfolio_events SET source_account_id = :reassign_to WHERE source_account_id = :acc_id"),
        {"reassign_to": reassign_to, "acc_id": acc_id},
    ).rowcount
    if event_links:
        audit_after = {**(audit_after or {}), "event_links_moved_or_cleared": event_links}

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


def _check_position_target(db: Session, ticker: str, platform_id: int, currency: str | None) -> str:
    """Guards for putting an event on position (ticker, platform_id); returns the resolved currency.

    GUARD (recompute-clobbers-holdings): recompute_holding_from_events rebuilds
    a position purely from its (ticker, platform_id) event slice. A non-zero
    LEGACY holding with ZERO backing events would therefore be silently
    overwritten by just this new event, destroying the opening balance (live
    loss in Phase 18 UAT #3). Refuse loudly instead — run migration 012
    (opening-balance backfill) so the position has a backing event first, after
    which a funded buy correctly SUMS. Once any event exists this never fires.

    T-07-02-CUR: one currency per position. A mismatch with the existing
    holding's currency raises ValueError (422 at the API boundary); an omitted
    currency defaults to the holding's (or "IDR" for a brand-new position).
    """
    existing_holding = db.query(Holding).filter(
        Holding.ticker == ticker, Holding.platform_id == platform_id
    ).one_or_none()

    if existing_holding is not None and existing_holding.quantity != 0:
        prior_events = db.query(PortfolioEvent).filter(
            PortfolioEvent.ticker == ticker,
            PortfolioEvent.platform_id == platform_id,
        ).count()
        if prior_events == 0:
            raise ValueError(
                f"holding {ticker} on platform {platform_id} has "
                f"{existing_holding.quantity} units but no backing portfolio_events — "
                "recording an event now would overwrite that opening balance. Run the "
                "opening-balance backfill (migration 012) first."
            )

    if currency is None:
        return existing_holding.currency if existing_holding is not None else "IDR"
    if existing_holding is not None and currency != existing_holding.currency:
        raise ValueError(
            f"event currency {currency} does not match holding currency "
            f"{existing_holding.currency} (one currency per position)"
        )
    return currency


def _recompute_or_refuse(db: Session, ticker: str, platform_id: int) -> dict:
    """Rebuild a position, refusing the write when a rate is missing (ValueError -> 422).

    recompute leaves the holding untouched without a rate, so saving anyway would
    move cash while the position's quantity stayed wrong. Returns recompute's dict,
    so a close can store the exact realized_pnl the summary already showed.
    """
    result = recompute_holding_from_events(db, ticker, platform_id)
    if result["quantity"] is None:
        raise ValueError(f"No FX rate to IDR for one of {ticker}'s event dates; nothing was saved. Try again later")
    return result


def close_position_if_flat(db: Session, ticker: str, platform_id: int) -> ClosedPosition | None:
    """Close a position whose ledger quantity is exactly zero. Does NOT commit.

    Saves one ClosedPosition (realized P&L in IDR as recompute returned it, close
    date = the latest sell), then deletes the holding and ALL its events with plain
    db.delete. It never touches a Transaction: the sell's cash leg already sits in
    the liquid balance, so the record can never be a cash row. Dust (a non-zero
    stored quantity) and positions with no sell stay open. Audited row by row, with
    strings only in the JSON (no Decimal).
    """
    db.flush()
    result = _recompute_or_refuse(db, ticker, platform_id)
    db.flush()
    holding = db.query(Holding).filter(Holding.ticker == ticker, Holding.platform_id == platform_id).one_or_none()
    if holding is None:
        return None
    db.refresh(holding)  # judge exactly-zero on the stored Numeric(28,8) value
    if holding.quantity != 0:
        return None
    events = db.query(PortfolioEvent).filter(
        PortfolioEvent.ticker == ticker, PortfolioEvent.platform_id == platform_id
    ).order_by(PortfolioEvent.date, PortfolioEvent.id).all()
    sells = [e for e in events if e.event_type == "sell"]
    if not sells:
        return None
    rec = ClosedPosition(
        ticker=ticker, platform_id=platform_id,
        realized_pnl=result["realized_pnl"], close_date=max(e.date for e in sells),
    )
    db.add(rec)
    db.flush()
    db.refresh(rec)  # the stored (rounded) value is what the audit row quotes
    db.add(AuditLog(entity="closed_position", entity_id=rec.id, operation="add", before=None, after={
        "ticker": ticker, "platform_id": platform_id, "realized_pnl": str(rec.realized_pnl),
        "close_date": rec.close_date.isoformat(), "event_ids": [e.id for e in events],
        "holding_id": holding.id,
    }))
    for ev in events:
        db.add(AuditLog(entity="portfolio_event", entity_id=ev.id, operation="delete",
                        before=_portfolio_event_snapshot(ev), after={"closed_position_id": rec.id}))
        db.delete(ev)
    db.add(AuditLog(entity="holding", entity_id=holding.id, operation="delete", before={
        "id": holding.id, "ticker": holding.ticker, "quantity": str(holding.quantity),
        "avg_cost": str(holding.avg_cost), "platform_id": holding.platform_id,
        "currency": holding.currency, "asset_type": holding.asset_type,
    }, after={"closed_position_id": rec.id}))
    db.delete(holding)
    db.flush()
    return rec


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
    if db.get(Platform, after["platform_id"]) is None:
        raise ValueError(f"platform {after['platform_id']} not found")

    event_currency = _check_position_target(
        db, after["ticker"], after["platform_id"], after.get("currency")
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
    _recompute_or_refuse(db, after["ticker"], after["platform_id"])
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


_EDITABLE_EVENT_TYPES = ("buy", "sell", "dividend")
_DELETABLE_EVENT_TYPES = _EDITABLE_EVENT_TYPES + ("deposit",)  # a deposit is delete-only


def _portfolio_event_snapshot(ev: PortfolioEvent) -> dict:
    """Audit snapshot of a portfolio event — strings only (AuditLog JSON-serializes, no Decimal)."""
    return {
        "id": ev.id,
        "date": ev.date.isoformat() if ev.date else None,
        "ticker": ev.ticker,
        "event_type": ev.event_type,
        "quantity": str(ev.quantity),
        "price": str(ev.price),
        "platform_id": ev.platform_id,
        "currency": ev.currency,
        "source_account_id": ev.source_account_id,
        "transaction_id": ev.transaction_id,
    }


def _load_editable_event(
    db: Session, event_id: int, allowed: tuple[str, ...] = _EDITABLE_EVENT_TYPES
) -> PortfolioEvent:
    ev = db.get(PortfolioEvent, event_id)
    if ev is None:
        raise ValueError(f"portfolio event {event_id} not found")
    if ev.event_type not in allowed:
        raise ValueError(
            f"portfolio event {event_id} is a {ev.event_type}; only "
            f"{'/'.join(allowed)} events can be changed this way"
        )
    return ev


def apply_edit_portfolio_event(
    db: Session, event_id: int, after: dict, before: dict | None
) -> PortfolioEvent:
    """Partial-update a buy/sell/dividend event, keep its cash leg in step, recompute.

    None/absent fields in `after` keep the current value. A funded event
    (transaction_id set) must stay buy or sell; its cash leg takes the new
    date and a signed amount (buy negative, sell positive; magnitude from
    `cash_amount`, else the leg's current magnitude). Does NOT commit.
    """
    ev = _load_editable_event(db, event_id)
    old_ticker = ev.ticker
    new_ticker = after.get("ticker") or old_ticker
    new_type = after.get("event_type") or ev.event_type
    funded = ev.transaction_id is not None
    if funded and new_type == "dividend":
        raise ValueError("a funded event must stay a buy or sell (its cash leg is linked)")
    if after.get("cash_amount") is not None and not funded:
        raise ValueError("cash_amount can only be set on a funded event (no linked cash transaction)")
    if new_ticker != old_ticker:
        _check_position_target(db, new_ticker, ev.platform_id, ev.currency)

    ev.ticker = new_ticker
    ev.event_type = new_type
    if after.get("date"):
        ev.date = date.fromisoformat(after["date"])
    if after.get("quantity") is not None:
        ev.quantity = Decimal(str(after["quantity"]))  # LOAD-BEARING: str() before Decimal()
    if after.get("price") is not None:
        ev.price = Decimal(str(after["price"]))

    tx = db.get(Transaction, ev.transaction_id) if funded else None
    if tx is not None:
        tx_before = _transaction_snapshot(tx)
        magnitude = abs(Decimal(str(after["cash_amount"]))) if after.get("cash_amount") is not None else abs(tx.amount)
        new_amount = -magnitude if new_type == "buy" else magnitude
        new_dt = datetime.combine(ev.date, tx.date.time()) if tx.date else datetime.combine(ev.date, datetime.min.time())
        if new_amount != tx.amount or new_dt != tx.date:
            tx.amount = new_amount
            tx.date = new_dt
            db.add(AuditLog(entity="transaction", entity_id=tx.id, operation="edit",
                            before=tx_before,
                            after={"date": new_dt.isoformat(), "amount": str(new_amount)}))

    db.add(AuditLog(entity="portfolio_event", entity_id=ev.id, operation="edit",
                    before=before, after=_portfolio_event_snapshot(ev)))
    db.flush()  # LOAD-BEARING: autoflush=False, recompute's SELECT must see the edited rows
    _recompute_or_refuse(db, ev.ticker, ev.platform_id)
    if new_ticker != old_ticker:
        _recompute_or_refuse(db, old_ticker, ev.platform_id)
        db.flush()
        new_h = db.query(Holding).filter(
            Holding.ticker == new_ticker, Holding.platform_id == ev.platform_id
        ).one_or_none()
        old_h = db.query(Holding).filter(
            Holding.ticker == old_ticker, Holding.platform_id == ev.platform_id
        ).one_or_none()
        if new_h is not None and new_h.asset_type is None and old_h is not None:
            new_h.asset_type = old_h.asset_type
    return ev


def apply_delete_portfolio_event(db: Session, event_id: int, before: dict | None) -> int | None:
    """Delete a buy/sell/dividend/deposit event (and its linked cash leg), then recompute.

    Returns the deleted cash-leg transaction id, or None. A position left with
    no events becomes a zero-quantity holding row (D-04). Does NOT commit.

    A deposit is deletable but not editable. A historical deposit has no linked
    cash leg, so any source-account debit is left alone (delete it
    separately via DELETE /transactions/{id} if it was also a mistake). A hand-linked
    leg that is transfer-paired is refused by apply_delete_transaction's pair guard
    (ValueError -> 422).
    """
    ev = _load_editable_event(db, event_id, _DELETABLE_EVENT_TYPES)
    ticker, platform_id, tx_id = ev.ticker, ev.platform_id, ev.transaction_id
    deleted_tx_id = None
    if tx_id is not None:
        tx = db.get(Transaction, tx_id)
        if tx is not None:
            # audited delete; funded legs carry no transfer_pair_id so its pair guard never fires
            apply_delete_transaction(db, tx_id, _transaction_snapshot(tx))
            deleted_tx_id = tx_id
    db.delete(ev)
    db.add(AuditLog(entity="portfolio_event", entity_id=event_id, operation="delete",
                    before=before, after=None))
    db.flush()  # LOAD-BEARING: autoflush=False, recompute's SELECT must not see the deleted rows
    _recompute_or_refuse(db, ticker, platform_id)
    return deleted_tx_id


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
    # WRITE-01: an identity change on an event-backed holding would orphan its
    # ledger and let a follow-up delete slip past holding_delete_refusal.
    if (after.get("ticker") not in (None, holding.ticker)
            or after.get("platform_id") not in (None, holding.platform_id)):
        if holding_delete_refusal(db, holding) is not None:
            raise ValueError(
                f"Holding {holding.ticker} has ledger events; its ticker and "
                "platform can't be changed. Record a sell to close it instead."
            )
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


def holding_delete_refusal(db: Session, holding: Holding) -> str | None:
    """Shared by apply_delete_holding, apply_edit_holding's identity-change
    check and tools.propose_delete_holding (WRITE-01,
    D-10). Position identity is (ticker, platform_id) — both columns are NOT
    NULL (D-12), so exact equality is the whole rule."""
    count = db.query(PortfolioEvent).filter(
        PortfolioEvent.ticker == holding.ticker,
        PortfolioEvent.platform_id == holding.platform_id,
    ).count()
    if count == 0:
        return None
    return (
        f"Holding {holding.ticker} has {count} ledger event(s); "
        "record a sell to close it instead of deleting."
    )


def apply_delete_holding(db: Session, holding_id: int, before: dict | None) -> None:
    """D-03 direct override: delete a holding by id (no-op if gone) and audit it.

    Raises ValueError when the position still has ledger events (WRITE-01).
    """
    holding = db.get(Holding, holding_id)
    if holding is not None:
        refusal = holding_delete_refusal(db, holding)
        if refusal is not None:
            raise ValueError(refusal)
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
