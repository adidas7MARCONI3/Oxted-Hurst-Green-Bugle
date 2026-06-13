"""Current-state store for closures.

Street Manager is a stream of deltas, so the store accumulates events into the
current state of each work. Upserts are keyed on the natural reference and are:

* **idempotent** — replaying the same event is a no-op;
* **order-tolerant** — an event that arrives out of order (lower version /
  earlier ``event_time``) never clobbers newer state; it only back-fills fields
  that are still missing.

The default :class:`InMemoryStore` works everywhere (tests, quick local runs).
A PostGIS-backed store with the same interface lives in ``store_postgres.py``.
"""
from __future__ import annotations

from dataclasses import fields as dataclass_fields
from typing import Iterable, Protocol

from .events import apply_event
from .models import Closure


class Store(Protocol):
    def upsert(self, closure: Closure) -> Closure: ...
    def get(self, reference: str) -> Closure | None: ...
    def list_closures(self) -> list[Closure]: ...
    def record_message(self, when_iso: str) -> None: ...
    def last_message_at(self) -> str | None: ...


# Fields that should never be overwritten by a merge (they are managed by the
# upsert logic itself, not copied across).
_MANAGED_FIELDS = {"reference", "status", "last_event_type", "version", "event_time", "raw"}


def _merge_fields(target: Closure, incoming: Closure, *, overwrite: bool) -> None:
    """Copy non-null fields from ``incoming`` onto ``target``.

    When ``overwrite`` is True (incoming is newer) any present value wins; when
    False (incoming is older) we only fill blanks, preserving newer state.
    """
    for f in dataclass_fields(Closure):
        if f.name in _MANAGED_FIELDS:
            continue
        value = getattr(incoming, f.name)
        if value in (None, ""):
            continue
        if overwrite or getattr(target, f.name) in (None, ""):
            setattr(target, f.name, value)


class InMemoryStore:
    """A dict-backed store, keyed by natural reference."""

    def __init__(self) -> None:
        self._by_ref: dict[str, Closure] = {}
        self._last_message_at: str | None = None

    def upsert(self, closure: Closure) -> Closure:
        existing = self._by_ref.get(closure.reference)
        if existing is None:
            self._by_ref[closure.reference] = closure
            return closure

        incoming_newer = closure.order_key() >= existing.order_key()
        if incoming_newer:
            # Apply the event to the existing status (forward or rollback),
            # then merge in any newer field values.
            existing.status = apply_event(existing.status, closure.last_event_type)
            existing.last_event_type = closure.last_event_type
            existing.version = closure.version
            existing.event_time = closure.event_time
            existing.raw = closure.raw or existing.raw
            _merge_fields(existing, closure, overwrite=True)
        else:
            # Out-of-order/older event: don't touch status; only back-fill gaps.
            _merge_fields(existing, closure, overwrite=False)
        return existing

    def get(self, reference: str) -> Closure | None:
        return self._by_ref.get(reference)

    def list_closures(self) -> list[Closure]:
        return list(self._by_ref.values())

    def record_message(self, when_iso: str) -> None:
        self._last_message_at = when_iso

    def last_message_at(self) -> str | None:
        return self._last_message_at


def filter_closures(
    closures: Iterable[Closure],
    *,
    active_only: bool = True,
    status: str | None = None,
    traffic_management_type: str | None = None,
    work_category: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[Closure]:
    """Apply the read-API filters to a collection of closures.

    Date filtering is an inclusive overlap test on ISO ``YYYY-MM-DD`` strings
    (lexicographic comparison is valid for that format).
    """
    out: list[Closure] = []
    for c in closures:
        if status is not None:
            if c.status.value != status:
                continue
        elif active_only and not c.status.is_active:
            continue
        if traffic_management_type and c.traffic_management_type != traffic_management_type:
            continue
        if work_category and c.work_category != work_category:
            continue
        # Date-range overlap test on the closure's proposed window.
        window_start = c.proposed_start_date
        window_end = c.proposed_end_date or window_start
        if start_date and window_end and window_end < start_date:
            continue  # finished before the window opens
        if end_date and window_start and window_start > end_date:
            continue  # starts after the window closes
        out.append(c)
    # Sorted by start date (None last), as the list view expects.
    out.sort(key=lambda c: (c.proposed_start_date is None, c.proposed_start_date or ""))
    return out
