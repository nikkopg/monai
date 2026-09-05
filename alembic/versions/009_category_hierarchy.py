"""category hierarchy: categories table + transactions.category_id backfill

Revision ID: e5f6a7b8c9d0
Revises: d3e4f5a6b7c8
Create Date: 2026-07-19

CAT-01 (self-referential Category table) + CAT-03 (data migration of the 74
distinct `transactions.category` strings onto it). This revision writes and
tests the migration machinery only — the human-reviewed mapping file
(`alembic/data/category_mapping.csv`) is drafted by a later plan (11-02),
which also runs `alembic upgrade head` against the live 5,728-row table.

Order (idempotent — every step is guarded so `upgrade()` is safely re-runnable,
D-07):
  1. create `categories` if missing (self-referential FK, D-01; no `ondelete`
     clause on `parent_id` — Postgres RESTRICT default, matches Pitfall 3).
  2. load `category_mapping.csv` (path resolved relative to this file, NOT
     cwd) — raises FileNotFoundError naming plan 11-02 if the CSV is absent.
  3. seed top-level group rows (every group referenced by the CSV, plus the
     two system rows "Transfer" and "Uncategorized" unconditionally, D-04)
     and subcategory rows under them; a blank `subcategory` cell resolves
     the raw string to the group node itself (any-level assignment, D-01).
  4. add `transactions.category_id` (nullable — D-04/Pitfall 2, tightened to
     NOT NULL by a later destructive migration once every insert path
     resolves a category first) + FK + index, if missing.
  5. SELECT DISTINCT category FROM transactions; abort loudly (RuntimeError)
     if any string is not a mapping key — nothing partial, env.py's single-
     transaction online-migration model makes this a clean rollback (D-07).
  6. snapshot pre-backfill (count, sum(amount)) per raw string, backfill via
     one bound-parameter UPDATE per mapping row (exact string match — no
     TRIM/ILIKE, Pitfall 1), snapshot post-backfill, assert_parity.
  7. assert zero `category_id IS NULL` rows and that the distinct-string
     count seen equals the CSV key count present in the DB (drift here means
     normalization crept in somewhere, Pitfall 1); print a per-group summary.

`raw_category` is never read or written (D-08). All SQL uses bound
parameters — never string interpolation, even though the CSV is trusted,
reviewed input (RESEARCH Security Domain).

downgrade(): strict reverse of steps 4 and 1 (drop index, FK, column, then
the categories table) — the CSV-driven seed/backfill data is not
"un-inserted" explicitly; dropping the table/column removes it.
"""
import csv
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d3e4f5a6b7c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Migration-adjacent data file, resolved relative to this file (not cwd) so
# `alembic upgrade head` works regardless of the invoking shell's cwd.
_CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "category_mapping.csv"

# D-02 top-level BudgetBakers groups + the 2 system rows, each mapped to
# (kind, color_hex, default_emoji) — hex values are the UI-SPEC 13-swatch
# palette (D-14), verbatim.
GROUP_META: dict[str, tuple[str, str, str]] = {
    "Food & Drinks": ("expense", "#d8b26a", "\U0001F354"),
    "Shopping": ("expense", "#b5503f", "\U0001F6CD"),
    "Housing": ("expense", "#5a8f73", "\U0001F3E0"),
    "Transportation": ("expense", "#8fae9c", "\U0001F68C"),
    "Vehicle": ("expense", "#a8674a", "\U0001F697"),
    "Life & Entertainment": ("expense", "#8a6a8f", "\U0001F3AD"),
    "Communication / PC": ("expense", "#6b7f8f", "\U0001F4BB"),
    "Financial Expenses": ("expense", "#6f6857", "\U0001F4B0"),
    "Investments": ("expense", "#c9973f", "\U0001F4C8"),
    "Income": ("income", "#23543c", "\U0001F4B5"),
    "Others": ("expense", "#c8c1b5", "\U0001F4E6"),
    "Transfer": ("transfer", "#a49c8c", "\U0001F501"),
    "Uncategorized": ("expense", "#8b8474", "❓"),
}


def kind_for_group(group: str) -> str:
    """D-03: typing (expense/income/transfer) is carried at the top-level group."""
    return GROUP_META[group][0]


def load_mapping(csv_path) -> dict[str, dict]:
    """Load category_mapping.csv into a dict keyed by the EXACT raw string.

    No trimming/normalization (Pitfall 1) — two whitespace variants of a raw
    string are two distinct keys, even if they map to the same target.

    Raises ValueError (loudly, before any SQL runs) on:
      - a row with empty raw_category (mapping-file injection guard — an
        empty key must never reach an `UPDATE ... WHERE category = ''`)
      - a row whose group is not a known GROUP_META key
    """
    mapping: dict[str, dict] = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            raw = row.get("raw_category") or ""
            if not raw:
                raise ValueError(
                    f"category_mapping.csv row has empty raw_category: {row!r}"
                )
            group = row.get("group") or ""
            if group not in GROUP_META:
                raise ValueError(
                    f"category_mapping.csv row for {raw!r} has unknown group: {group!r}"
                )
            mapping[raw] = {
                "group": group,
                "subcategory": row.get("subcategory") or "",
                "emoji": row.get("emoji") or None,
                "color": row.get("color") or None,
            }
    return mapping


def find_unmapped(distinct_strings, mapping: dict) -> list[str]:
    """Sorted list of strings from `distinct_strings` absent from mapping
    keys — exact match only, no normalization (D-07)."""
    return sorted(s for s in distinct_strings if s not in mapping)


def assert_parity(pre: dict, post: dict) -> None:
    """Raise RuntimeError naming the exact raw string and both (count, sum)
    pairs on any mismatch between pre- and post-backfill snapshots."""
    mismatches = []
    for raw, pre_vals in pre.items():
        post_vals = post.get(raw)
        if post_vals != pre_vals:
            mismatches.append(f"{raw!r}: pre={pre_vals} post={post_vals}")
    if mismatches:
        raise RuntimeError(
            "Category migration parity check failed for: " + "; ".join(mismatches)
        )


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    # 1. Create categories table if missing.
    if "categories" not in inspector.get_table_names():
        op.create_table(
            "categories",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column(
                "parent_id", sa.Integer(),
                sa.ForeignKey("categories.id"), nullable=True,
            ),
            sa.Column("kind", sa.String(length=16), nullable=False),
            sa.Column("color", sa.String(length=16), nullable=True),
            sa.Column("icon", sa.String(length=16), nullable=True),
            sa.Column(
                "is_system", sa.Boolean(), nullable=False, server_default=sa.false(),
            ),
            sa.UniqueConstraint("name", "parent_id", name="uq_categories_name_parent"),
        )
        op.create_index("ix_categories_parent_id", "categories", ["parent_id"])
        op.create_index(
            "uq_categories_name_root", "categories", ["name"],
            unique=True, postgresql_where=sa.text("parent_id IS NULL"),
        )
        inspector = sa.inspect(op.get_bind())

    conn = op.get_bind()

    # 2. Load the human-reviewed mapping (plan 11-02's artifact).
    if not _CSV_PATH.exists():
        raise FileNotFoundError(
            f"category_mapping.csv not found at {_CSV_PATH} — run plan 11-02 "
            "(draft + human-review the mapping) before this migration."
        )
    mapping = load_mapping(_CSV_PATH)

    # 3. Seed group + subcategory rows (idempotent: SELECT-before-INSERT).
    groups_needed = {row["group"] for row in mapping.values()} | {"Transfer", "Uncategorized"}
    group_row_id: dict[str, int] = {}
    for group in groups_needed:
        kind, color, emoji = GROUP_META[group]
        is_system = group in ("Transfer", "Uncategorized")
        existing = conn.execute(
            sa.text(
                "SELECT id FROM categories WHERE name = :name AND parent_id IS NULL"
            ),
            {"name": group},
        ).scalar()
        if existing is not None:
            group_row_id[group] = existing
            continue
        result = conn.execute(
            sa.text(
                "INSERT INTO categories (name, parent_id, kind, color, icon, is_system) "
                "VALUES (:name, NULL, :kind, :color, :icon, :is_system) RETURNING id"
            ),
            {"name": group, "kind": kind, "color": color, "icon": emoji, "is_system": is_system},
        )
        group_row_id[group] = result.scalar()

    # Subcategory rows: name = subcategory value, parent = group row. Blank
    # subcategory means the raw string resolves to the group node itself.
    subcat_row_id: dict[tuple[str, str], int] = {}
    for row in mapping.values():
        sub = row["subcategory"]
        if not sub:
            continue
        group = row["group"]
        key = (group, sub)
        if key in subcat_row_id:
            continue
        parent_id = group_row_id[group]
        existing = conn.execute(
            sa.text(
                "SELECT id FROM categories WHERE name = :name AND parent_id = :pid"
            ),
            {"name": sub, "pid": parent_id},
        ).scalar()
        if existing is not None:
            subcat_row_id[key] = existing
            continue
        kind = kind_for_group(group)
        color = row["color"]  # NULL = inherit parent's swatch (D-14)
        icon = row["emoji"]
        result = conn.execute(
            sa.text(
                "INSERT INTO categories (name, parent_id, kind, color, icon, is_system) "
                "VALUES (:name, :pid, :kind, :color, :icon, FALSE) RETURNING id"
            ),
            {"name": sub, "pid": parent_id, "kind": kind, "color": color, "icon": icon},
        )
        subcat_row_id[key] = result.scalar()

    # Resolve each mapping key (raw string) to its target category id.
    raw_to_category_id: dict[str, int] = {}
    for raw, row in mapping.items():
        sub = row["subcategory"]
        if sub:
            raw_to_category_id[raw] = subcat_row_id[(row["group"], sub)]
        else:
            raw_to_category_id[raw] = group_row_id[row["group"]]

    # 4. Add transactions.category_id (nullable, D-04/Pitfall 2) + FK + index.
    tx_columns = {c["name"] for c in inspector.get_columns("transactions")}
    if "category_id" not in tx_columns:
        op.add_column(
            "transactions", sa.Column("category_id", sa.Integer(), nullable=True)
        )
    tx_fks = {fk["name"] for fk in inspector.get_foreign_keys("transactions")}
    if "fk_transactions_category" not in tx_fks:
        op.create_foreign_key(
            "fk_transactions_category", "transactions", "categories",
            ["category_id"], ["id"],
        )
    tx_indexes = {ix["name"] for ix in inspector.get_indexes("transactions")}
    if "ix_transactions_category_id" not in tx_indexes:
        op.create_index(
            "ix_transactions_category_id", "transactions", ["category_id"]
        )

    # 5. Abort loudly if any live category string isn't in the mapping (D-07).
    distinct_strings = [
        r[0] for r in conn.execute(
            sa.text("SELECT DISTINCT category FROM transactions WHERE category IS NOT NULL")
        )
    ]
    unmapped = find_unmapped(distinct_strings, mapping)
    if unmapped:
        raise RuntimeError(
            "Category migration abort — unmapped category strings found "
            f"(not in category_mapping.csv): {unmapped}"
        )

    # 6. Pre-backfill parity snapshot, then bound-parameter backfill per raw
    #    string (exact match only — no TRIM/ILIKE, Pitfall 1).
    def _snapshot() -> dict[str, tuple[int, object]]:
        snap: dict[str, tuple[int, object]] = {}
        for raw in mapping:
            row = conn.execute(
                sa.text(
                    "SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM transactions "
                    "WHERE category = :raw"
                ),
                {"raw": raw},
            ).one()
            snap[raw] = (row[0], row[1])
        return snap

    pre = _snapshot()
    for raw, cid in raw_to_category_id.items():
        conn.execute(
            sa.text(
                "UPDATE transactions SET category_id = :cid "
                "WHERE category = :raw AND category_id IS NULL"
            ),
            {"cid": cid, "raw": raw},
        )
    post = _snapshot()
    assert_parity(pre, post)

    # 7. Zero-NULL and drift assertions.
    null_count = conn.execute(
        sa.text("SELECT COUNT(*) FROM transactions WHERE category_id IS NULL")
    ).scalar()
    if null_count:
        raise RuntimeError(
            f"Category migration left {null_count} transactions with NULL category_id"
        )

    seen_count = len(distinct_strings)
    if seen_count != len(mapping):
        raise RuntimeError(
            f"Category migration drift: {seen_count} distinct categories seen in DB, "
            f"{len(mapping)} keys in category_mapping.csv — expected exact match "
            "(Pitfall 1: whitespace/casing normalization crept in somewhere)"
        )

    print(f"Category migration: {len(mapping)} raw strings backfilled, parity OK.")
    for group, gid in sorted(group_row_id.items()):
        count = conn.execute(
            sa.text(
                "SELECT COUNT(*) FROM transactions t JOIN categories c "
                "ON c.id = t.category_id WHERE c.id = :gid OR c.parent_id = :gid"
            ),
            {"gid": gid},
        ).scalar()
        print(f"  {group}: {count} transactions")


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    tx_indexes = {ix["name"] for ix in inspector.get_indexes("transactions")}
    if "ix_transactions_category_id" in tx_indexes:
        op.drop_index("ix_transactions_category_id", table_name="transactions")

    tx_fks = {fk["name"] for fk in inspector.get_foreign_keys("transactions")}
    if "fk_transactions_category" in tx_fks:
        op.drop_constraint(
            "fk_transactions_category", "transactions", type_="foreignkey"
        )

    tx_columns = {c["name"] for c in inspector.get_columns("transactions")}
    if "category_id" in tx_columns:
        op.drop_column("transactions", "category_id")

    if "categories" in inspector.get_table_names():
        op.drop_table("categories")
