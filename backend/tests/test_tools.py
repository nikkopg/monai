"""
Tool correctness tests.

Two groups:
  - resolve_period: pure date logic, no DB.
  - tool SQL: integration against the live Postgres (requires `docker compose up db`
    and a loaded database). Skipped automatically if the DB is unreachable.
"""

import datetime

import pytest

from backend.tools import resolve_period


# --------------------------------------------------------------------------
# Pure date-logic tests (no DB)
# --------------------------------------------------------------------------

class TestResolvePeriod:
    def test_all_time_is_unbounded(self):
        assert resolve_period("all_time") == (None, None)

    def test_this_month_starts_on_first(self):
        s, e = resolve_period("this_month")
        assert s.day == 1
        # end is the first of the following month
        assert e.day == 1
        assert (e.year, e.month) != (s.year, s.month)

    def test_last_month_precedes_this_month(self):
        last_s, last_e = resolve_period("last_month")
        this_s, _ = resolve_period("this_month")
        assert last_e == this_s
        assert last_s.day == 1

    def test_this_year_spans_jan_to_jan(self):
        s, e = resolve_period("this_year")
        assert (s.month, s.day) == (1, 1)
        assert (e.month, e.day) == (1, 1)
        assert e.year == s.year + 1

    def test_last_year(self):
        s, e = resolve_period("last_year")
        this_s, _ = resolve_period("this_year")
        assert e == this_s
        assert s.year == this_s.year - 1

    def test_last_30_days_span(self):
        s, e = resolve_period("last_30_days")
        assert (e - s).days == 31  # 30 days back + today inclusive

    def test_custom_makes_end_exclusive(self):
        s, e = resolve_period("custom", "2024-01-01", "2024-12-31")
        assert s == datetime.date(2024, 1, 1)
        assert e == datetime.date(2025, 1, 1)  # exclusive day after

    def test_december_rolls_over(self):
        # last_month from a December date is exercised indirectly; just ensure no crash
        s, e = resolve_period("last_month")
        assert s < e

    def test_unknown_period_raises(self):
        with pytest.raises(ValueError):
            resolve_period("fortnight")


# --------------------------------------------------------------------------
# Integration tests against live Postgres
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def db_available():
    from sqlalchemy import text
    from backend.db import engine
    try:
        with engine.connect() as c:
            n = c.execute(text("SELECT COUNT(*) FROM transactions")).scalar()
        if not n:
            pytest.skip("transactions table is empty")
    except Exception as e:
        pytest.skip(f"Postgres not available: {e}")
    return True


class TestToolSQL:
    def test_spending_total_non_negative(self, db_available):
        from backend.tools import spending_total
        assert spending_total("all_time")["total"] >= 0

    def test_income_total_non_negative(self, db_available):
        from backend.tools import income_total
        assert income_total("all_time")["total"] >= 0

    def test_net_equals_income_minus_spending(self, db_available):
        from backend.tools import spending_total, income_total, net_total
        spend = spending_total("all_time")["total"]
        inc = income_total("all_time")["total"]
        net = net_total("all_time")["net"]
        assert abs(net - (inc - spend)) < 1.0  # float tolerance

    def test_categories_all_positive_and_descending(self, db_available):
        from backend.tools import spending_by_category
        rows = spending_by_category("all_time", limit=10)["rows"]
        totals = [t for _, t in rows]
        assert all(t > 0 for t in totals)
        assert totals == sorted(totals, reverse=True)

    def test_count_all_ge_expense(self, db_available):
        from backend.tools import transaction_count
        all_n = transaction_count("all_time", kind="all")["count"]
        exp_n = transaction_count("all_time", kind="expense")["count"]
        inc_n = transaction_count("all_time", kind="income")["count"]
        assert all_n >= exp_n
        assert all_n >= inc_n

    def test_largest_expenses_descending_magnitude(self, db_available):
        from backend.tools import largest_transactions
        rows = largest_transactions("all_time", limit=5, kind="expense")["rows"]
        mags = [r["amount"] for r in rows]
        assert mags == sorted(mags, reverse=True)
        assert all(m > 0 for m in mags)  # reported as positive magnitude

    def test_find_transactions_rows_include_id(self, db_available):
        from backend.tools import find_transactions
        rows = find_transactions(limit=5)["rows"]
        for row in rows:
            assert "id" in row and isinstance(row["id"], int)
            assert "date" in row
            assert "amount" in row
            assert "category" in row
            assert "merchant" in row
            assert "account_id" in row

    def test_find_transactions_most_recent_first(self, db_available):
        from backend.tools import find_transactions
        rows = find_transactions(limit=20)["rows"]
        dates = [r["date"] for r in rows]
        assert dates == sorted(dates, reverse=True)

    def test_find_transactions_limit_clamping(self, db_available):
        from backend.tools import find_transactions
        rows = find_transactions(limit=999)["rows"]
        assert len(rows) <= 50
        rows_zero = find_transactions(limit=0)["rows"]
        assert len(rows_zero) >= 0  # clamp floor is 1, call must not raise

    def test_find_transactions_kind_filter(self, db_available):
        from backend.tools import find_transactions
        expense_rows = find_transactions(kind="expense", limit=20)["rows"]
        assert all(r["amount"] < 0 for r in expense_rows)
        income_rows = find_transactions(kind="income", limit=20)["rows"]
        assert all(r["amount"] > 0 for r in income_rows)

    def test_find_transactions_category_exact_match(self, db_available):
        # find_transactions still filters on the legacy category string, so
        # seed the filter value straight from transactions (list_categories
        # now returns the hierarchy tree, not legacy strings).
        from sqlalchemy import text
        from backend.db import engine
        from backend.tools import find_transactions

        with engine.connect() as c:
            row = c.execute(text(
                "SELECT category FROM transactions "
                "WHERE category IS NOT NULL AND is_transfer = false LIMIT 1"
            )).fetchone()
        if not row:
            return
        category_name = row[0]
        rows = find_transactions(category=category_name, limit=20)["rows"]
        for r in rows:
            assert r["category"] == category_name

    def test_find_transactions_merchant_partial_match(self, db_available):
        from backend.tools import find_transactions
        seed_rows = find_transactions(limit=1)["rows"]
        if not seed_rows or not seed_rows[0]["merchant"]:
            return
        merchant = seed_rows[0]["merchant"]
        substring = merchant.lower()[: max(1, len(merchant) // 2)]
        rows = find_transactions(merchant=substring, limit=20)["rows"]
        assert any(substring in (r["merchant"] or "").lower() for r in rows)

    def test_find_platforms_rows_include_id(self, db_available):
        from backend.tools import find_platforms
        rows = find_platforms(limit=5)["rows"]
        for row in rows:
            assert "id" in row and isinstance(row["id"], int)
            assert "name" in row
            assert "kind" in row

    def test_find_platforms_name_filter_ilike(self, db_available):
        from sqlalchemy import text
        from backend.db import engine
        from backend.tools import find_platforms

        with engine.connect() as c:
            c.execute(text(
                "INSERT INTO platforms (name, kind) VALUES ('ZZ Test Bitplatform', 'exchange') "
                "ON CONFLICT (name) DO NOTHING"
            ))
            c.commit()
        rows = find_platforms(name="zz test bit", limit=10)["rows"]
        assert any(r["name"] == "ZZ Test Bitplatform" for r in rows)

    def test_find_platforms_limit_clamping(self, db_available):
        from backend.tools import find_platforms
        rows = find_platforms(limit=999)["rows"]
        assert len(rows) <= 50
        rows_zero = find_platforms(limit=0)["rows"]
        assert len(rows_zero) >= 0  # clamp floor is 1, call must not raise

    def test_find_accounts_rows_include_id(self, db_available):
        from backend.tools import find_accounts
        rows = find_accounts(limit=5)["rows"]
        for row in rows:
            assert "id" in row and isinstance(row["id"], int)
            assert "name" in row
            assert "type" in row
            assert "currency" in row

    def test_find_accounts_name_filter_ilike(self, db_available):
        from sqlalchemy import text
        from backend.db import engine
        from backend.tools import find_accounts

        with engine.connect() as c:
            c.execute(text(
                "INSERT INTO accounts (name, type, currency) VALUES ('ZZ Test BCA', 'liquid', 'IDR') "
                "ON CONFLICT (name) DO NOTHING"
            ))
            c.commit()
        rows = find_accounts(name="zz test bca", limit=10)["rows"]
        assert any(r["name"] == "ZZ Test BCA" for r in rows)

    def test_find_accounts_limit_clamping(self, db_available):
        from backend.tools import find_accounts
        rows = find_accounts(limit=999)["rows"]
        assert len(rows) <= 50
        rows_zero = find_accounts(limit=0)["rows"]
        assert len(rows_zero) >= 0  # clamp floor is 1, call must not raise

    def test_tools_registry_includes_find_platforms_and_find_accounts(self):
        from backend.tools import TOOLS
        assert "find_platforms" in TOOLS
        assert "find_accounts" in TOOLS

    def test_propose_add_holding_includes_platform_id(self, db_available):
        from backend.tools import propose_add_holding
        proposal = propose_add_holding(
            ticker="ZZTEST", quantity=1, avg_cost=100, platform_id=42
        )
        assert proposal["after"]["platform_id"] == 42


def test_spending_before_after_purchase(db_available):
    """CHAT-03 / D-15: before/after correlation around the earliest buy event.

    Seeds a portfolio_events buy row (pivot) plus one expense in the before
    window and two in the after window for a unique category, then asserts the
    equal-length windows, totals, delta, and the no-buy-event error path.
    """
    from sqlalchemy import text
    from backend.db import engine
    from backend.tools import spending_before_after_purchase

    TICKER = "ZZTEST"
    CATEGORY = "zz-correlation-test"
    pivot = datetime.date.today() - datetime.timedelta(days=10)  # n_days = 10
    before_day = pivot - datetime.timedelta(days=5)   # inside [pivot-10, pivot-1]
    after_day = pivot + datetime.timedelta(days=3)    # inside [pivot, today]

    with engine.begin() as c:
        # portfolio_events.platform_id is NOT NULL + FK since quick 260711-rb2 —
        # get-or-create a throwaway platform for the pivot event.
        plat_id = c.execute(
            text("INSERT INTO platforms (name, kind) VALUES ('zz-corr-plat', 'test') "
                 "ON CONFLICT (name) DO UPDATE SET kind = 'test' RETURNING id")
        ).scalar()
        c.execute(
            text("INSERT INTO portfolio_events (date, ticker, event_type, quantity, price, platform_id) "
                 "VALUES (:d, :t, 'buy', 1, 100, :pid)"),
            {"d": pivot, "t": TICKER, "pid": plat_id},
        )
        # spending_in_category is hierarchy-backed (11-04): the category must
        # exist as a categories node and transactions must carry category_id.
        cat_id = c.execute(
            text("INSERT INTO categories (name, parent_id, kind, is_system) "
                 "VALUES (:n, NULL, 'expense', false) RETURNING id"),
            {"n": CATEGORY},
        ).scalar()
        c.execute(
            text("INSERT INTO transactions (date, amount, currency, category, category_id, is_transfer) "
                 "VALUES (:d, -100, 'IDR', :cat, :cid, false)"),
            {"d": before_day, "cat": CATEGORY, "cid": cat_id},
        )
        c.execute(
            text("INSERT INTO transactions (date, amount, currency, category, category_id, is_transfer) "
                 "VALUES (:d, -300, 'IDR', :cat, :cid, false)"),
            {"d": after_day, "cat": CATEGORY, "cid": cat_id},
        )
        c.execute(
            text("INSERT INTO transactions (date, amount, currency, category, category_id, is_transfer) "
                 "VALUES (:d, -50, 'IDR', :cat, :cid, false)"),
            {"d": pivot, "cat": CATEGORY, "cid": cat_id},  # boundary: pivot day counts as "after"
        )

    try:
        res = spending_before_after_purchase(TICKER, CATEGORY)
        assert res["tool"] == "spending_before_after_purchase"
        assert res["pivot_date"] == pivot.isoformat()
        assert res["window_days"] == 10
        assert res["before_total"] == 100.0
        assert res["after_total"] == 350.0  # 300 + 50 (pivot day is "after")
        assert res["delta"] == 250.0
        assert abs(res["delta_pct"] - 250.0) < 1e-6

        # Honesty: unknown ticker → structured error, never a fabricated number.
        err = spending_before_after_purchase("NOSUCHTICKER", CATEGORY)
        assert err["tool"] == "spending_before_after_purchase"
        assert "error" in err
        assert "before_total" not in err
    finally:
        with engine.begin() as c:
            c.execute(text("DELETE FROM portfolio_events WHERE ticker = :t"), {"t": TICKER})
            c.execute(text("DELETE FROM transactions WHERE category = :cat"), {"cat": CATEGORY})
            c.execute(text("DELETE FROM categories WHERE name = :cat"), {"cat": CATEGORY})


# --------------------------------------------------------------------------
# Category hierarchy tests (CAT-04, D-09/D-10/D-11/D-12) — Phase 11 Plan 04
# --------------------------------------------------------------------------

@pytest.fixture
def category_tree(db_available):
    """Root group (expense, own color) -> child -> grandchild, each with one
    directly-attached transaction, plus a sibling system category and a
    Transfer-flagged transaction on the root — enough to exercise 3-level
    rollup (D-09), descendant-inclusive sums (D-10), and D-12 exclusion
    (system category + is_transfer) in one fixture.

    Deliberately leaves the legacy `transactions.category` string column NULL
    on every seeded row — these tests exist to prove the tools have moved onto
    `category_id`, not the legacy string (D-11); against the pre-hierarchy
    implementation none of these rows would ever be found by string matching.
    """
    from sqlalchemy import text
    from backend.db import engine

    ROOT, CHILD, GRANDCHILD, SYSTEM = (
        "ZZ Test Root Group", "ZZ Test Child", "ZZ Test Grandchild", "ZZ Test System",
    )
    today = datetime.date.today()
    ids: dict[str, int] = {}
    with engine.begin() as c:
        ids["root"] = c.execute(
            text("INSERT INTO categories (name, parent_id, kind, color, is_system) "
                 "VALUES (:n, NULL, 'expense', :col, false) RETURNING id"),
            {"n": ROOT, "col": "#123456"},
        ).scalar()
        ids["child"] = c.execute(
            text("INSERT INTO categories (name, parent_id, kind, is_system) "
                 "VALUES (:n, :p, 'expense', false) RETURNING id"),
            {"n": CHILD, "p": ids["root"]},
        ).scalar()
        ids["grandchild"] = c.execute(
            text("INSERT INTO categories (name, parent_id, kind, is_system) "
                 "VALUES (:n, :p, 'expense', false) RETURNING id"),
            {"n": GRANDCHILD, "p": ids["child"]},
        ).scalar()
        ids["system"] = c.execute(
            text("INSERT INTO categories (name, parent_id, kind, is_system) "
                 "VALUES (:n, NULL, 'expense', true) RETURNING id"),
            {"n": SYSTEM},
        ).scalar()

        for key, amount in (("root", -100), ("child", -200), ("grandchild", -300), ("system", -50)):
            c.execute(text(
                "INSERT INTO transactions (date, amount, currency, category_id, is_transfer) "
                "VALUES (:d, :amt, 'IDR', :cid, false)"
            ), {"d": today, "amt": amount, "cid": ids[key]})
        # Transfer-flagged transaction attached to the root — must not inflate
        # the root's spending total regardless of its category (D-12).
        c.execute(text(
            "INSERT INTO transactions (date, amount, currency, category_id, is_transfer) "
            "VALUES (:d, -999, 'IDR', :cid, true)"
        ), {"d": today, "cid": ids["root"]})

    yield {"root": ROOT, "child": CHILD, "grandchild": GRANDCHILD, "system": SYSTEM, "ids": ids}

    with engine.begin() as c:
        c.execute(text("DELETE FROM transactions WHERE category_id = ANY(:ids)"), {"ids": list(ids.values())})
        for key in ("grandchild", "child", "root", "system"):
            c.execute(text("DELETE FROM categories WHERE id = :id"), {"id": ids[key]})


class TestCategoryHierarchyTools:
    def test_spending_by_category_rolls_up_three_levels(self, category_tree):
        from backend.tools import spending_by_category
        result = spending_by_category(limit=50)
        assert result["tool"] == "spending_by_category"
        totals = dict(result["rows"])
        assert totals[category_tree["root"]] == 600.0  # 100 (root) + 200 (child) + 300 (grandchild)
        assert "children" in result
        children = dict(result["children"][category_tree["root"]])
        assert children == {
            category_tree["root"]: 100.0,
            category_tree["child"]: 200.0,
            category_tree["grandchild"]: 300.0,
        }

    def test_spending_by_category_excludes_system_and_transfer(self, category_tree):
        from backend.tools import spending_by_category
        result = spending_by_category(limit=50)
        names = [name for name, _ in result["rows"]]
        assert category_tree["system"] not in names
        # the transfer-flagged root transaction (-999) must not inflate the root total
        assert dict(result["rows"])[category_tree["root"]] == 600.0

    def test_spending_in_category_parent_includes_descendants(self, category_tree):
        from backend.tools import spending_in_category
        root_total = spending_in_category(category_tree["root"])["total"]
        assert root_total == 600.0

    def test_spending_in_category_child_excludes_parent_own_rows(self, category_tree):
        from backend.tools import spending_in_category
        child_total = spending_in_category(category_tree["child"])["total"]
        assert child_total == 500.0  # child (200) + grandchild (300), not root's own 100

    def test_list_categories_returns_tree_with_effective_color(self, category_tree):
        from backend.tools import list_categories
        result = list_categories()
        assert result["tool"] == "list_categories"
        assert "categories" in result

        def _find(nodes, name):
            for n in nodes:
                if n["name"] == name:
                    return n
                found = _find(n["children"], name)
                if found:
                    return found
            return None

        root_node = _find(result["categories"], category_tree["root"])
        assert root_node is not None
        assert root_node["color"] == "#123456"
        child_node = _find(root_node["children"], category_tree["child"])
        assert child_node is not None
        assert child_node["color"] == "#123456"  # inherited from root (D-14)

        top_names = [n["name"] for n in result["categories"]]
        assert "Transfer" in top_names
        assert "Uncategorized" in top_names

    def test_propose_rename_category_unknown_name_returns_error(self, db_available):
        from backend.tools import propose_rename_category
        result = propose_rename_category("ZZ Definitely Not A Real Category", "New Name")
        assert result["tool"] == "propose_rename_category"
        assert "error" in result
        assert "proposal_id" not in result

    def test_propose_merge_category_counts_via_category_id(self, category_tree):
        from backend.tools import propose_merge_category
        result = propose_merge_category(category_tree["grandchild"], category_tree["child"])
        assert result["tool"] == "propose_merge_category"
        assert result["before"]["affected_count"] == 1


def test_net_worth_trend_shape_and_current_month():
    """net_worth_trend: >=6 monthly rows; net_worth is None or float per month,
    and the current (last) month equals the LIVE net_worth() total so the chart
    line's endpoint matches the /net-worth hero (non-tautological, live DB)."""
    from backend.tools import net_worth_trend, net_worth

    rows = net_worth_trend(6)["rows"]
    assert len(rows) >= 6
    for r in rows:
        assert set(r.keys()) == {"month", "net_worth"}
        assert r["net_worth"] is None or isinstance(r["net_worth"], float)

    current = rows[-1]["net_worth"]
    assert current is not None
    assert abs(current - net_worth()["total"]) < 1.0
