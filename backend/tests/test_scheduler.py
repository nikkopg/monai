"""
Scheduler tests (Wave 0 RED target) — filled in by Plan 06.

  - test_snapshot_job_partial_failure_tolerant — the daily APScheduler snapshot
    job records what it can and tolerates a per-ticker fetch failure (does not
    abort the whole run) when writing portfolio_value_history rows.

The body calls pytest.fail(...) so the downstream RED->GREEN transition is visible
(real failing target, NOT a skip). No production scheduler module is imported here —
that name is referenced lazily inside the real assertion Plan 06 will add.
"""

import pytest


def test_snapshot_job_partial_failure_tolerant():
    pytest.fail("not yet implemented — Plan 06 fills this")
