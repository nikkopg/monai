"""
Category hierarchy write-layer + CRUD guard tests — CAT-01 (depth cap) and
CAT-02 (block-or-reassign delete, extended for child categories).

Pins the direct REST write path for the self-referential category hierarchy:
  - POST /categories creates a root (kind+color required) or a child
    (kind inherited from the root, CAT-01/D-03)
  - Depth cap (3 levels) enforced on both create and re-parent (PUT)
  - Uniqueness: (name, parent_id) and a separate root-name uniqueness
  - DELETE mirrors /accounts' 3-way branch, extended so a category WITH
    subcategories is always blocked (child_count) — reassign_to only ever
    moves TRANSACTIONS, never subcategories (Pitfall 3)
  - POST /categories/rename and /merge are reworked as single-row edits
    (D-11): transactions follow via FK, the legacy `category` string column
    is never touched
  - System rows (Transfer/Uncategorized, is_system) are protected from
    delete/rename but allow color/icon edits (D-04)
  - GET /categories returns the tree with tx_count + effective (inherited)
    color, filterable by kind (D-03/D-14)

Requires a live Postgres (the migrated dev DB — Transfer/Uncategorized system
rows already exist, seeded by migration 009 / plan 11-02). Tests seed + clean
up their own category/transaction rows.
"""

import datetime
import uuid

import pytest

from sqlalchemy import text


@pytest.fixture(scope="module")
def db_available():
    from backend.db import engine
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception as e:
        pytest.skip(f"Postgres not available: {e}")
    return True


@pytest.fixture()
def db_session(db_available):
    from backend.db import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _unique_cat(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _make_category(db, name, parent_id=None, kind="expense", color=None, icon=None):
    from backend.models import Category
    cat = Category(name=name, parent_id=parent_id, kind=kind, color=color, icon=icon, is_system=False)
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


def _make_transaction(db, category_id, is_transfer=False):
    from backend.models import Transaction
    tx = Transaction(
        date=datetime.datetime(2024, 1, 15, 12, 0, 0),
        amount=-50000,
        currency="IDR",
        category=None,
        raw_category=None,
        merchant="CatHier Test",
        is_transfer=is_transfer,
        category_id=category_id,
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)
    return tx.id


def _category_exists(db, cat_id: int) -> bool:
    """Raw-SQL existence check (NOT db.get()) — a strongly-referenced ORM
    object deleted by another session raises ObjectDeletedError on
    db.get(..) after expire_all() rather than returning None; a plain SELECT
    sidesteps the identity-map refresh entirely."""
    return db.execute(text("SELECT 1 FROM categories WHERE id = :id"), {"id": cat_id}).first() is not None


def _audit_rows(db, entity_id: int, operation: str) -> int:
    return int(
        db.execute(
            text(
                "SELECT COUNT(*) FROM audit_log "
                "WHERE entity = 'category' AND entity_id = :eid AND operation = :op"
            ),
            {"eid": entity_id, "op": operation},
        ).scalar()
        or 0
    )


def _cleanup(db, *, category_ids=(), tx_ids=()):
    """Delete transactions first, then categories one at a time in reverse
    creation order (children before parents — FK RESTRICT on parent_id).

    Commits after EACH category delete individually: Category has no ORM
    `relationship()` for its self-reference (only a plain parent_id column),
    so SQLAlchemy's unit-of-work can't see the parent/child dependency and
    will batch multiple pending Category deletes into one executemany in
    arbitrary (non-creation) order — a child-before-parent ordering silently
    becomes parent-before-child and trips the FK. One delete+commit per row
    forces DB-level sequencing instead."""
    from backend.models import Category, Transaction
    for tx_id in tx_ids:
        tx = db.get(Transaction, tx_id)
        if tx:
            db.delete(tx)
    db.commit()
    for cat_id in reversed([c for c in category_ids if c is not None]):
        cat = db.get(Category, cat_id)
        if cat:
            db.delete(cat)
            db.commit()


# ---------------------------------------------------------------------------
# POST /categories — create (CAT-01)
# ---------------------------------------------------------------------------

def test_create_root_category_201(client, api_key, db_session):
    name = _unique_cat("RootCreate")
    resp = client.post(
        "/categories",
        json={"name": name, "kind": "expense", "color": "#112233"},
        headers={"MONAI_API_KEY": api_key},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    cat_id = body["id"]
    try:
        assert body["name"] == name
        assert body["parent_id"] is None
        assert body["kind"] == "expense"
        assert body["color"] == "#112233"
        assert _audit_rows(db_session, cat_id, "add") == 1
    finally:
        _cleanup(db_session, category_ids=[cat_id])


def test_create_child_inherits_kind(client, api_key, db_session):
    """A child created without `kind` inherits its root's kind (D-03),
    even though CategoryCreate.kind is Optional."""
    root = _make_category(db_session, _unique_cat("RootIncome"), kind="income", color="#445566")
    child_id = None
    try:
        resp = client.post(
            "/categories",
            json={"name": _unique_cat("ChildNoKind"), "parent_id": root.id},
            headers={"MONAI_API_KEY": api_key},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        child_id = body["id"]
        assert body["kind"] == "income"
        assert body["parent_id"] == root.id
    finally:
        _cleanup(db_session, category_ids=[root.id, child_id])


def test_create_child_depth4_rejected(client, api_key, db_session):
    """root(1) -> child(2) -> grandchild(3); one more level (4) -> 422 (CAT-01)."""
    root = _make_category(db_session, _unique_cat("DepthRoot"), color="#112233")
    child = _make_category(db_session, _unique_cat("DepthChild"), parent_id=root.id)
    grandchild = _make_category(db_session, _unique_cat("DepthGrandchild"), parent_id=child.id)
    try:
        resp = client.post(
            "/categories",
            json={"name": _unique_cat("DepthGreatGrandchild"), "parent_id": grandchild.id},
            headers={"MONAI_API_KEY": api_key},
        )
        assert resp.status_code == 422, resp.text
    finally:
        _cleanup(db_session, category_ids=[root.id, child.id, grandchild.id])


def test_create_duplicate_name_same_parent_rejected(client, api_key, db_session):
    root = _make_category(db_session, _unique_cat("DupParent"), color="#112233")
    dup_name = _unique_cat("DupChild")
    child = _make_category(db_session, dup_name, parent_id=root.id)
    try:
        resp = client.post(
            "/categories",
            json={"name": dup_name, "parent_id": root.id},
            headers={"MONAI_API_KEY": api_key},
        )
        assert resp.status_code == 422, resp.text
    finally:
        _cleanup(db_session, category_ids=[root.id, child.id])


def test_create_duplicate_root_name_rejected(client, api_key, db_session):
    """Root-level name uniqueness via the partial unique index (Postgres
    treats NULL parent_id as pairwise distinct in a plain composite unique)."""
    name = _unique_cat("DupRoot")
    root = _make_category(db_session, name, color="#112233")
    try:
        resp = client.post(
            "/categories",
            json={"name": name, "kind": "expense", "color": "#654321"},
            headers={"MONAI_API_KEY": api_key},
        )
        assert resp.status_code == 422, resp.text
    finally:
        _cleanup(db_session, category_ids=[root.id])


# ---------------------------------------------------------------------------
# PUT /categories/{id} — re-parent depth cap
# ---------------------------------------------------------------------------

def test_put_reparent_exceeds_depth_rejected(client, api_key, db_session):
    """Re-parenting a childless root under a depth-3 node would push it to
    depth 4 -> 422."""
    root_a = _make_category(db_session, _unique_cat("ReparentRootA"), color="#112233")
    child_a = _make_category(db_session, _unique_cat("ReparentChildA"), parent_id=root_a.id)
    grandchild_a = _make_category(db_session, _unique_cat("ReparentGrandA"), parent_id=child_a.id)
    root_b = _make_category(db_session, _unique_cat("ReparentRootB"), color="#445566")
    try:
        resp = client.put(
            f"/categories/{root_b.id}",
            json={"parent_id": grandchild_a.id},
            headers={"MONAI_API_KEY": api_key},
        )
        assert resp.status_code == 422, resp.text
    finally:
        _cleanup(db_session, category_ids=[root_a.id, child_a.id, grandchild_a.id, root_b.id])


# ---------------------------------------------------------------------------
# DELETE /categories/{id} — block-or-reassign (CAT-02), extended for children
# ---------------------------------------------------------------------------

def test_delete_leaf_no_tx_no_children_succeeds_and_audits(client, api_key, db_session):
    cat = _make_category(db_session, _unique_cat("DeleteLeaf"), color="#112233")
    cat_id = cat.id  # capture BEFORE expire_all — cat.id after would re-trigger a refresh of a deleted row
    resp = client.delete(f"/categories/{cat_id}", headers={"MONAI_API_KEY": api_key})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "deleted"
    db_session.expire_all()
    assert not _category_exists(db_session, cat_id)
    assert _audit_rows(db_session, cat_id, "delete") == 1


def test_delete_with_transactions_no_reassign_blocked(client, api_key, db_session):
    cat = _make_category(db_session, _unique_cat("DeleteBlockedTx"), color="#112233")
    tx_ids = [_make_transaction(db_session, cat.id) for _ in range(2)]
    try:
        resp = client.delete(f"/categories/{cat.id}", headers={"MONAI_API_KEY": api_key})
        assert resp.status_code == 422, resp.text
        detail = resp.json()["detail"]
        assert detail["affected_count"] == 2
        assert "child_count" not in detail
    finally:
        _cleanup(db_session, category_ids=[cat.id], tx_ids=tx_ids)


def test_delete_parent_with_subcategories_blocked(client, api_key, db_session):
    """A category with subcategories is always blocked — reassign_to only
    moves transactions, never subcategories (Pitfall 3)."""
    root = _make_category(db_session, _unique_cat("DeleteParent"), color="#112233")
    child = _make_category(db_session, _unique_cat("DeleteParentChild"), parent_id=root.id)
    tx_ids = [_make_transaction(db_session, root.id)]
    try:
        resp = client.delete(f"/categories/{root.id}", headers={"MONAI_API_KEY": api_key})
        assert resp.status_code == 422, resp.text
        detail = resp.json()["detail"]
        assert detail["affected_count"] == 1
        assert detail["child_count"] == 1
    finally:
        _cleanup(db_session, category_ids=[root.id, child.id], tx_ids=tx_ids)


def test_delete_reassign_to_self_rejected(client, api_key, db_session):
    """reassign_to pointing at the deleted node's own descendant -> 422.

    A node with real subcategories is already blocked outright above (any
    child_count > 0 short-circuits before reassign_to is even considered,
    since reassign_to only ever moves transactions). For a childless leaf,
    "its own descendant" collapses to the degenerate case of itself — the
    guard must still reject that self-reference rather than silently
    reassigning a category's transactions to itself and deleting it anyway.
    """
    cat = _make_category(db_session, _unique_cat("DeleteSelfReassign"), color="#112233")
    tx_ids = [_make_transaction(db_session, cat.id)]
    try:
        resp = client.delete(
            f"/categories/{cat.id}?reassign_to={cat.id}",
            headers={"MONAI_API_KEY": api_key},
        )
        assert resp.status_code == 422, resp.text
    finally:
        _cleanup(db_session, category_ids=[cat.id], tx_ids=tx_ids)


def test_delete_with_valid_reassign_moves_transactions(client, api_key, db_session):
    from backend.models import Transaction

    src = _make_category(db_session, _unique_cat("DeleteReassignSrc"), color="#112233")
    dst = _make_category(db_session, _unique_cat("DeleteReassignDst"), color="#445566")
    src_id = src.id  # capture BEFORE expire_all — src.id after would re-trigger a refresh of a deleted row
    tx_ids = [_make_transaction(db_session, src_id) for _ in range(3)]
    try:
        resp = client.delete(
            f"/categories/{src_id}?reassign_to={dst.id}",
            headers={"MONAI_API_KEY": api_key},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["reassigned"] == 3

        db_session.expire_all()
        assert not _category_exists(db_session, src_id)
        for tx_id in tx_ids:
            assert db_session.get(Transaction, tx_id).category_id == dst.id
    finally:
        _cleanup(db_session, category_ids=[dst.id], tx_ids=tx_ids)


# ---------------------------------------------------------------------------
# POST /categories/rename, /merge — reworked as single-row edits (D-11)
# ---------------------------------------------------------------------------

def test_rename_updates_name_only_transactions_follow_via_fk(client, api_key, db_session):
    """Rename edits categories.name (single row); a fixture transaction keeps
    its category_id AND its legacy `category` string is unchanged (D-11)."""
    from backend.models import Category, Transaction

    old_name = _unique_cat("HierRenameOld")
    new_name = _unique_cat("HierRenameNew")
    cat = _make_category(db_session, old_name, color="#112233")
    legacy = "legacy-string-untouched"
    tx = Transaction(
        date=datetime.datetime(2024, 1, 15, 12, 0, 0), amount=-1000, currency="IDR",
        category=legacy, raw_category=legacy, merchant="HierRename", is_transfer=False,
        category_id=cat.id,
    )
    db_session.add(tx)
    db_session.commit()
    db_session.refresh(tx)
    try:
        resp = client.post(
            "/categories/rename",
            json={"old_name": old_name, "new_name": new_name},
            headers={"MONAI_API_KEY": api_key},
        )
        assert resp.status_code == 200, resp.text

        db_session.expire_all()
        assert db_session.get(Category, cat.id).name == new_name
        refreshed_tx = db_session.get(Transaction, tx.id)
        assert refreshed_tx.category_id == cat.id
        assert refreshed_tx.category == legacy  # D-11: legacy string untouched
    finally:
        _cleanup(db_session, category_ids=[cat.id], tx_ids=[tx.id])


def test_rename_collision_under_same_parent_rejected(client, api_key, db_session):
    root = _make_category(db_session, _unique_cat("RenameCollisionRoot"), color="#112233")
    a_name = _unique_cat("RenameCollisionA")
    b_name = _unique_cat("RenameCollisionB")
    cat_a = _make_category(db_session, a_name, parent_id=root.id)
    cat_b = _make_category(db_session, b_name, parent_id=root.id)
    try:
        resp = client.post(
            "/categories/rename",
            json={"old_name": a_name, "new_name": b_name},
            headers={"MONAI_API_KEY": api_key},
        )
        assert resp.status_code == 422, resp.text
    finally:
        _cleanup(db_session, category_ids=[root.id, cat_a.id, cat_b.id])


def test_merge_moves_transactions_and_deletes_source(client, api_key, db_session):
    from backend.models import Transaction

    from_name = _unique_cat("HierMergeFrom")
    into_name = _unique_cat("HierMergeInto")
    from_cat = _make_category(db_session, from_name, color="#112233")
    into_cat = _make_category(db_session, into_name, color="#445566")
    from_cat_id = from_cat.id  # capture BEFORE expire_all — a deleted row can't be refreshed
    tx_ids = [_make_transaction(db_session, from_cat_id) for _ in range(2)]
    try:
        resp = client.post(
            "/categories/merge",
            json={"from_name": from_name, "into_name": into_name},
            headers={"MONAI_API_KEY": api_key},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["affected_count"] == 2

        db_session.expire_all()
        assert not _category_exists(db_session, from_cat_id)
        for tx_id in tx_ids:
            assert db_session.get(Transaction, tx_id).category_id == into_cat.id
    finally:
        _cleanup(db_session, category_ids=[into_cat.id], tx_ids=tx_ids)


def test_merge_source_with_children_rejected(client, api_key, db_session):
    """Merge a source that has child categories -> 422 (merge subcategories
    first — discretion call keeping the depth-cap invariant simple)."""
    from_root = _make_category(db_session, _unique_cat("MergeParentFrom"), color="#112233")
    child = _make_category(db_session, _unique_cat("MergeParentChild"), parent_id=from_root.id)
    into_root = _make_category(db_session, _unique_cat("MergeParentInto"), color="#445566")
    try:
        resp = client.post(
            "/categories/merge",
            json={"from_name": from_root.name, "into_name": into_root.name},
            headers={"MONAI_API_KEY": api_key},
        )
        assert resp.status_code == 422, resp.text
    finally:
        _cleanup(db_session, category_ids=[from_root.id, child.id, into_root.id])


# ---------------------------------------------------------------------------
# System rows (Transfer/Uncategorized, is_system) — D-04
# ---------------------------------------------------------------------------

def _a_system_category(db):
    row = db.execute(
        text("SELECT id, name, color, icon FROM categories WHERE is_system = true LIMIT 1")
    ).first()
    assert row is not None, "expected a system category (migration 009 seeds Transfer/Uncategorized)"
    return row


def test_system_row_delete_rejected(client, api_key, db_session):
    cat_id, _name, _color, _icon = _a_system_category(db_session)
    resp = client.delete(f"/categories/{cat_id}", headers={"MONAI_API_KEY": api_key})
    assert resp.status_code == 422, resp.text


def test_system_row_rename_rejected(client, api_key, db_session):
    _cat_id, name, _color, _icon = _a_system_category(db_session)
    resp = client.post(
        "/categories/rename",
        json={"old_name": name, "new_name": _unique_cat("ShouldNotRename")},
        headers={"MONAI_API_KEY": api_key},
    )
    assert resp.status_code == 422, resp.text


def test_system_row_color_icon_edit_succeeds(client, api_key, db_session):
    cat_id, _name, orig_color, orig_icon = _a_system_category(db_session)
    try:
        resp = client.put(
            f"/categories/{cat_id}",
            json={"color": "#abcdef", "icon": "\U0001F527"},
            headers={"MONAI_API_KEY": api_key},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["color"] == "#abcdef"
        assert body["icon"] == "\U0001F527"
    finally:
        db_session.execute(
            text("UPDATE categories SET color = :c, icon = :i WHERE id = :id"),
            {"c": orig_color, "i": orig_icon, "id": cat_id},
        )
        db_session.commit()


# ---------------------------------------------------------------------------
# GET /categories — tree shape, effective color, kind filter
# ---------------------------------------------------------------------------

def test_get_categories_tree_shape_and_effective_color(client, db_session):
    root = _make_category(db_session, _unique_cat("TreeRoot"), kind="expense", color="#abcdef")
    child = _make_category(db_session, _unique_cat("TreeChild"), parent_id=root.id, color=None)
    tx_ids = [_make_transaction(db_session, child.id)]
    try:
        resp = client.get("/categories")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert isinstance(body, list)
        root_node = next((n for n in body if n["id"] == root.id), None)
        assert root_node is not None
        assert root_node["color"] == "#abcdef"
        assert root_node["effective_color"] == "#abcdef"
        child_node = next((n for n in root_node["children"] if n["id"] == child.id), None)
        assert child_node is not None
        assert child_node["color"] is None
        assert child_node["effective_color"] == "#abcdef"  # inherited (D-14)
        assert child_node["tx_count"] == 1
    finally:
        _cleanup(db_session, category_ids=[root.id, child.id], tx_ids=tx_ids)


def test_get_categories_kind_filter(client, db_session):
    income_root = _make_category(db_session, _unique_cat("FilterIncome"), kind="income", color="#111111")
    expense_root = _make_category(db_session, _unique_cat("FilterExpense"), kind="expense", color="#222222")
    try:
        resp = client.get("/categories", params={"kind": "income"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        ids = [n["id"] for n in body]
        assert income_root.id in ids
        assert expense_root.id not in ids
    finally:
        _cleanup(db_session, category_ids=[income_root.id, expense_root.id])
