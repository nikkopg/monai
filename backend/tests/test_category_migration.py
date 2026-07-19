"""
Unit tests for alembic/versions/009_category_hierarchy.py's pure helper
functions — CAT-03's "parity verified, not assumed" safety net.

No database required: load_mapping/find_unmapped/assert_parity/kind_for_group
are pure functions exercised against tmp_path CSV fixtures and in-memory
dicts. The migration module is loaded via importlib (it lives under
alembic/versions/, not an importable package) so these tests double as the
RED half of the TDD gate: they fail with a clear import error until the
migration file exists (Task 2).
"""

import importlib.util
from pathlib import Path

import pytest

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2] / "alembic" / "versions" / "009_category_hierarchy.py"
)


@pytest.fixture(scope="module")
def migration():
    """Load 009_category_hierarchy.py as a standalone module via importlib.

    Fails with FileNotFoundError/ImportError until the migration file exists —
    that is the intended RED-phase failure (module missing, not a bug).
    """
    spec = importlib.util.spec_from_file_location("migration_009", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load migration spec from {MIGRATION_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_csv(tmp_path: Path, rows: list[dict]) -> Path:
    import csv

    path = tmp_path / "category_mapping.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["raw_category", "group", "subcategory", "emoji", "color"]
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


# ---------------------------------------------------------------------------
# load_mapping
# ---------------------------------------------------------------------------


def test_load_mapping_keys_by_exact_raw_string_whitespace_variant_stays_distinct(
    migration, tmp_path
):
    """Pitfall 1 / D-07: a leading-space variant of a raw string is a DISTINCT
    key even though both map to the same (group, subcategory) target."""
    csv_path = _write_csv(
        tmp_path,
        [
            {
                "raw_category": "Active sport, fitness",
                "group": "Life & Entertainment",
                "subcategory": "Active sport, fitness",
                "emoji": "",
                "color": "",
            },
            {
                "raw_category": " Active sport, fitness",
                "group": "Life & Entertainment",
                "subcategory": "Active sport, fitness",
                "emoji": "",
                "color": "",
            },
        ],
    )
    mapping = migration.load_mapping(csv_path)
    assert len(mapping) == 2
    assert "Active sport, fitness" in mapping
    assert " Active sport, fitness" in mapping
    assert mapping["Active sport, fitness"]["group"] == "Life & Entertainment"
    assert mapping[" Active sport, fitness"]["group"] == "Life & Entertainment"


def test_load_mapping_rejects_empty_raw_category(migration, tmp_path):
    """Mapping-file injection guard (RESEARCH Security Domain): an empty key
    must never reach an UPDATE ... WHERE category = '' clause."""
    csv_path = _write_csv(
        tmp_path,
        [{"raw_category": "", "group": "Others", "subcategory": "", "emoji": "", "color": ""}],
    )
    with pytest.raises(ValueError):
        migration.load_mapping(csv_path)


def test_load_mapping_rejects_unknown_group(migration, tmp_path):
    csv_path = _write_csv(
        tmp_path,
        [
            {
                "raw_category": "Some Thing",
                "group": "Not A Real Group",
                "subcategory": "",
                "emoji": "",
                "color": "",
            }
        ],
    )
    with pytest.raises(ValueError, match="Not A Real Group"):
        migration.load_mapping(csv_path)


# ---------------------------------------------------------------------------
# find_unmapped
# ---------------------------------------------------------------------------


def test_find_unmapped_returns_sorted_absent_strings(migration, tmp_path):
    csv_path = _write_csv(
        tmp_path,
        [
            {"raw_category": "A", "group": "Others", "subcategory": "", "emoji": "", "color": ""},
        ],
    )
    mapping = migration.load_mapping(csv_path)
    unmapped = migration.find_unmapped(["A", "C", "B"], mapping)
    assert unmapped == ["B", "C"]


def test_find_unmapped_empty_when_all_covered(migration, tmp_path):
    csv_path = _write_csv(
        tmp_path,
        [
            {"raw_category": "A", "group": "Others", "subcategory": "", "emoji": "", "color": ""},
        ],
    )
    mapping = migration.load_mapping(csv_path)
    assert migration.find_unmapped(["A"], mapping) == []


def test_find_unmapped_no_normalization_trimmed_variant_still_unmapped(migration, tmp_path):
    """D-07: a trimmed variant of a mapped key is still reported unmapped —
    no whitespace normalization anywhere in the abort check."""
    csv_path = _write_csv(
        tmp_path,
        [
            {
                "raw_category": " Active sport, fitness",
                "group": "Others",
                "subcategory": "",
                "emoji": "",
                "color": "",
            },
        ],
    )
    mapping = migration.load_mapping(csv_path)
    unmapped = migration.find_unmapped(["Active sport, fitness"], mapping)
    assert unmapped == ["Active sport, fitness"]


# ---------------------------------------------------------------------------
# assert_parity
# ---------------------------------------------------------------------------


def test_assert_parity_passes_when_equal(migration):
    pre = {"Groceries": (10, 100000)}
    post = {"Groceries": (10, 100000)}
    migration.assert_parity(pre, post)  # must not raise


def test_assert_parity_raises_on_mismatch_naming_string_and_both_pairs(migration):
    pre = {"Groceries": (10, 100000)}
    post = {"Groceries": (9, 90000)}
    with pytest.raises(RuntimeError) as exc_info:
        migration.assert_parity(pre, post)
    msg = str(exc_info.value)
    assert "Groceries" in msg
    assert "10" in msg and "100000" in msg
    assert "9" in msg and "90000" in msg


# ---------------------------------------------------------------------------
# kind_for_group
# ---------------------------------------------------------------------------


def test_kind_for_group_income(migration):
    assert migration.kind_for_group("Income") == "income"


def test_kind_for_group_expense(migration):
    assert migration.kind_for_group("Food & Drinks") == "expense"


def test_kind_for_group_transfer(migration):
    assert migration.kind_for_group("Transfer") == "transfer"
