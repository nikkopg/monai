"""retro-pair historical transfer transactions (XFER-05, D-11)

Revision ID: a7c3e9f2b4d1
Revises: f1a2b3c4d5e6
Create Date: 2026-07-30

One-time backfill of `transactions.transfer_pair_id` for historical
imported transfer rows created before Phase 13's writes.py started setting
the column on new transfers. Adds no schema (the column/index already exist
from migration 010) — pure data backfill, guarded and idempotent (D-11).

Match predicate (strict, D-11): same calendar date + exactly opposite amount
+ two DISTINCT accounts, both already `is_transfer = true`. A row is only
paired when BOTH it and its sole candidate counterpart have EXACTLY ONE
candidate match each (`retro_pair_transfers`'s mutual count-guard) — this
keeps pairing symmetric and prevents a half-pair when one side's only
candidate is itself ambiguous (e.g. two valid opposite matches for a third
row). Zero or multiple candidates on either side -> both rows are left
`transfer_pair_id IS NULL` and their ids are printed (report-only, mirrors
009's `assert_parity` loud-reporting style) — never guessed, never raised
(unlike 009's hard-abort on unmapped categories, an unmatched/ambiguous
transfer row is an expected, non-fatal D-11 outcome).

Pairing convention: both legs of a pair share `transfer_pair_id = min(id)`
of the two rows (shared-group-id), matching the runtime convention writes.py
uses for newly created transfers (Phase 13 plan 03).

Idempotent: the candidate query only considers rows where
`transfer_pair_id IS NULL`, and every UPDATE re-guards on
`transfer_pair_id IS NULL` — a second `upgrade()` run touches zero
already-paired rows and reports zero new pairs.

No hard-coded account ids anywhere (Finding 1 / Pitfall 2) — the match is
purely relational (`a.account_id <> b.account_id`), unlike migration 010's
now-stale `ACCOUNT_TYPE` map.

downgrade(): documented no-op. This revision makes no structural schema
change (the column/index/FK already exist from 010) and, per 009/010's
downgrade posture, backfilled data values are left in place on downgrade —
only schema objects are reverted. There is nothing structural to revert
here.
"""
from collections import Counter
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7c3e9f2b4d1"
down_revision: Union[str, None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Candidate-match query (verified live this session, RESEARCH.md Code
# Examples): same calendar date, exactly opposite amount, distinct accounts,
# both legs still unpaired. `a.id < b.id` yields each unordered pair once.
_CANDIDATE_QUERY = """
    SELECT a.id AS leg_a_id, b.id AS leg_b_id
    FROM transactions a
    JOIN transactions b
      ON a.date::date = b.date::date
     AND a.amount = -b.amount
     AND a.account_id <> b.account_id
     AND a.id < b.id
    WHERE a.is_transfer = true AND b.is_transfer = true
      AND a.transfer_pair_id IS NULL AND b.transfer_pair_id IS NULL
"""

_UNPAIRED_IDS_QUERY = (
    "SELECT id FROM transactions WHERE is_transfer = true AND transfer_pair_id IS NULL"
)

_UPDATE_QUERY = (
    "UPDATE transactions SET transfer_pair_id = :gid "
    "WHERE id = :id AND transfer_pair_id IS NULL"
)


def compute_pairing(
    candidate_pairs: list[tuple[int, int]], all_ids: set[int]
) -> tuple[dict[int, int], list[int]]:
    """Pure function (Pitfall 4 guard): decide which candidate pairs are
    unambiguous and which ids must be left flagged.

    A candidate pair (a, b) is only committed when BOTH a and b individually
    touch exactly one candidate pair in the input — no blind `LIMIT 1`. This
    mutual check also correctly leaves BOTH would-be partners of an
    ambiguous row unpaired (rather than arbitrarily latching one of them
    onto the ambiguous row), since the pair itself is invalid if either side
    is touched more than once.

    Returns (updates, flagged_ids) where `updates` maps every paired
    transaction id -> its shared group id (min(a, b)), and `flagged_ids` is
    the sorted list of `all_ids` that end up with no valid pairing (zero
    candidates, or every candidate pair touching them was ambiguous).
    """
    touch_count: Counter[int] = Counter()
    for a, b in candidate_pairs:
        touch_count[a] += 1
        touch_count[b] += 1

    updates: dict[int, int] = {}
    for a, b in candidate_pairs:
        if touch_count[a] == 1 and touch_count[b] == 1:
            group_id = min(a, b)
            updates[a] = group_id
            updates[b] = group_id

    flagged = sorted(all_ids - set(updates))
    return updates, flagged


def retro_pair_transfers(conn) -> dict:
    """Backfill `transfer_pair_id` on historical unpaired `is_transfer=true`
    rows (D-11). Accepts anything with a SQLAlchemy `.execute()` (a raw
    Connection from `op.get_bind()`, or an ORM Session in tests).

    Idempotent — safe to call repeatedly; a call after all matchable rows
    are paired reports `pairs_backfilled == 0`.
    """
    all_ids = {r[0] for r in conn.execute(sa.text(_UNPAIRED_IDS_QUERY))}
    candidate_pairs = [(r[0], r[1]) for r in conn.execute(sa.text(_CANDIDATE_QUERY))]
    updates, flagged = compute_pairing(candidate_pairs, all_ids)

    for tx_id, group_id in updates.items():
        conn.execute(sa.text(_UPDATE_QUERY), {"gid": group_id, "id": tx_id})

    pair_count = len(updates) // 2
    print(
        f"Retro-pair transfers: {pair_count} pairs backfilled; "
        f"{len(flagged)} rows left unpaired (flagged, never guessed)"
        + (f": {flagged}" if flagged else "")
    )
    return {"pairs_backfilled": pair_count, "flagged_ids": flagged}


def upgrade() -> None:
    conn = op.get_bind()
    retro_pair_transfers(conn)


def downgrade() -> None:
    # No-op by design — see module docstring. No structural schema object
    # was created by this revision (transfer_pair_id/its index came from
    # 010), and 009/010's downgrade posture leaves backfilled data values in
    # place, reverting only schema objects.
    pass
