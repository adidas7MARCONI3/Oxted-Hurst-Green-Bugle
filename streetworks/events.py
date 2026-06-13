"""Event-type normalisation and the closure status lifecycle.

Street Manager emits event-driven *deltas*, not snapshots. The same logical
event arrives in different cosmetic spellings across topics and versions
(``WORK_START`` vs ``work-start`` vs ``Work Start``). We normalise everything to
a clean :class:`EventType` enum and derive the current closure status by
applying events to the previous status — idempotently and order-tolerantly.
"""
from __future__ import annotations

from enum import Enum


class EventType(str, Enum):
    # Permit lifecycle
    PERMIT_SUBMITTED = "permit_submitted"
    PERMIT_GRANTED = "permit_granted"
    PERMIT_REFUSED = "permit_refused"
    PERMIT_MODIFICATION_REQUEST = "permit_modification_request"
    PERMIT_CANCELLED = "permit_cancelled"
    PERMIT_REVOKED = "permit_revoked"
    # Work progress
    WORK_START = "work_start"
    WORK_STOP = "work_stop"
    WORK_START_REVERTED = "work_start_reverted"
    WORK_STOP_REVERTED = "work_stop_reverted"
    # Activities (planned events not requiring a permit)
    ACTIVITY_CREATED = "activity_created"
    ACTIVITY_UPDATED = "activity_updated"
    ACTIVITY_CANCELLED = "activity_cancelled"
    # Section 58 (restrictions on works following resurfacing)
    SECTION_58_IN_FORCE = "section_58_in_force"
    SECTION_58_ENDED = "section_58_ended"
    SECTION_58_CANCELLED = "section_58_cancelled"

    UNKNOWN = "unknown"


# Canonicalised spelling (UPPER_SNAKE, no punctuation) → EventType.
_ALIASES: dict[str, EventType] = {
    "PERMIT_SUBMITTED": EventType.PERMIT_SUBMITTED,
    "PERMIT_GRANTED": EventType.PERMIT_GRANTED,
    "PERMIT_REFUSED": EventType.PERMIT_REFUSED,
    "PERMIT_MODIFICATION_REQUEST": EventType.PERMIT_MODIFICATION_REQUEST,
    "PERMIT_MODIFICATION_REQUESTED": EventType.PERMIT_MODIFICATION_REQUEST,
    "PERMIT_CANCELLED": EventType.PERMIT_CANCELLED,
    "PERMIT_REVOKED": EventType.PERMIT_REVOKED,
    "WORK_START": EventType.WORK_START,
    "WORK_STARTED": EventType.WORK_START,
    "WORK_STOP": EventType.WORK_STOP,
    "WORK_STOPPED": EventType.WORK_STOP,
    "WORK_START_REVERTED": EventType.WORK_START_REVERTED,
    "WORK_STOP_REVERTED": EventType.WORK_STOP_REVERTED,
    "ACTIVITY_CREATED": EventType.ACTIVITY_CREATED,
    "ACTIVITY_UPDATED": EventType.ACTIVITY_UPDATED,
    "ACTIVITY_CANCELLED": EventType.ACTIVITY_CANCELLED,
    "SECTION_58_IN_FORCE": EventType.SECTION_58_IN_FORCE,
    "SECTION_58_ENDED": EventType.SECTION_58_ENDED,
    "SECTION_58_CANCELLED": EventType.SECTION_58_CANCELLED,
}


def normalise_event_type(raw: str | None) -> EventType:
    """Map any cosmetic spelling of an event type to the canonical enum."""
    if not raw:
        return EventType.UNKNOWN
    key = raw.strip().upper().replace("-", "_").replace(" ", "_")
    while "__" in key:
        key = key.replace("__", "_")
    return _ALIASES.get(key, EventType.UNKNOWN)


class ClosureStatus(str, Enum):
    PROPOSED = "proposed"        # submitted / granted / planned — not yet started
    IN_PROGRESS = "in_progress"  # work-start seen; physically happening now
    COMPLETED = "completed"      # work-stop seen
    INACTIVE = "inactive"        # cancelled / revoked / refused

    @property
    def is_active(self) -> bool:
        """Active = something a resident would see on the map right now."""
        return self in (ClosureStatus.PROPOSED, ClosureStatus.IN_PROGRESS)


# Events that move *forward* through the lifecycle.
_FORWARD: dict[EventType, ClosureStatus] = {
    EventType.PERMIT_SUBMITTED: ClosureStatus.PROPOSED,
    EventType.PERMIT_GRANTED: ClosureStatus.PROPOSED,
    EventType.PERMIT_MODIFICATION_REQUEST: ClosureStatus.PROPOSED,
    EventType.ACTIVITY_CREATED: ClosureStatus.PROPOSED,
    EventType.ACTIVITY_UPDATED: ClosureStatus.PROPOSED,
    EventType.WORK_START: ClosureStatus.IN_PROGRESS,
    EventType.SECTION_58_IN_FORCE: ClosureStatus.IN_PROGRESS,
    EventType.WORK_STOP: ClosureStatus.COMPLETED,
    EventType.SECTION_58_ENDED: ClosureStatus.COMPLETED,
    EventType.PERMIT_REFUSED: ClosureStatus.INACTIVE,
    EventType.PERMIT_CANCELLED: ClosureStatus.INACTIVE,
    EventType.PERMIT_REVOKED: ClosureStatus.INACTIVE,
    EventType.ACTIVITY_CANCELLED: ClosureStatus.INACTIVE,
    EventType.SECTION_58_CANCELLED: ClosureStatus.INACTIVE,
}

# Reverting events roll the status *back* to where it was before the thing they
# undo. work-start-reverted ⇒ back to proposed; work-stop-reverted ⇒ back to
# in-progress (the work resumed).
_REVERT: dict[EventType, ClosureStatus] = {
    EventType.WORK_START_REVERTED: ClosureStatus.PROPOSED,
    EventType.WORK_STOP_REVERTED: ClosureStatus.IN_PROGRESS,
}


def apply_event(current: ClosureStatus | None, event: EventType) -> ClosureStatus:
    """Return the new status after applying ``event`` to ``current``.

    Pure function — no side effects, deterministic, so applying the same event
    twice is idempotent and a replayed stream converges to the same answer.
    """
    if event in _REVERT:
        return _REVERT[event]
    if event in _FORWARD:
        return _FORWARD[event]
    # Unknown / no-op event: keep the prior status (or PROPOSED if brand new).
    return current if current is not None else ClosureStatus.PROPOSED
