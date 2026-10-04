"""Proposal state machine: per-channel TTL, status transitions, lazy expiry.

`transition()` is the only place application code assigns a proposal's status
(a grep test in test_proposals_approval.py enforces it, D-09). Expiry is lazy
(`expire_stale()`, run at the top of proposal reads); there is no background
job (D-11). Status values are pending, confirmed, rejected, expired, superseded
(superseded = replaced by a newer MCP proposal, Phase 32 D-14); there is
no `locked` status, Phase 32 derives MCP lockout from failed_attempts (D-04).
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

TTL: dict[str, timedelta] = {
    "chat": timedelta(minutes=15),
    "mcp": timedelta(hours=48),
}

_TARGETS = ("confirmed", "rejected", "expired", "superseded")

ALL_SKIPPED_MSG = "Every row is skipped — reject this proposal instead"


def ttl_for(channel: str) -> timedelta:
    """Return the proposal lifetime for a channel; unknown channels raise ValueError."""
    try:
        return TTL[channel]
    except KeyError:
        raise ValueError(f"No proposal TTL for channel {channel!r}") from None


def transition(proposal, new_status: str) -> None:
    """Move a pending proposal to confirmed, rejected, expired or superseded. Caller commits."""
    if new_status not in _TARGETS:
        raise ValueError(f"Invalid proposal status {new_status!r}")
    if proposal.status != "pending":
        raise ValueError(f"Proposal already {proposal.status}")
    now = datetime.now(timezone.utc)
    proposal.status_changed_at = now
    proposal.status = new_status
    if new_status == "confirmed":
        proposal.confirmed_at = now


def expire_stale(db: Session) -> None:
    """Bulk-expire pending proposals past expires_at, then commit."""
    db.execute(
        text(
            "UPDATE proposals SET status = 'expired', status_changed_at = now() "
            "WHERE status = 'pending' AND expires_at < now()"
        )
    )
    db.commit()
