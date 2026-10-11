"""
Thread service tests (Phase 36 plan 05): title rule and thread data helpers.

All values are synthetic. The DB is the isolated monai_test database.
"""

from backend import chat_service


def test_title_from():
    assert chat_service.title_from("  How much   did I\nspend this month?  ") == "How much did I spend this month?"
    assert chat_service.title_from("") == ""
    long_q = "ZZTest " + " ".join(["spending"] * 11)  # 90 chars
    assert len(long_q) > 60
    t = chat_service.title_from(long_q)
    assert t.endswith("…") and len(t) <= 61
    assert long_q.startswith(t[:-1]) and long_q[len(t) - 1] == " "  # word boundary
    one = "Z" * 80
    assert chat_service.title_from(one) == "Z" * 60 + "…"
