"""The normalised closure record — the unit of current state we store & serve."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .events import ClosureStatus, EventType


@dataclass
class Closure:
    """A single road/street work or closure, assembled from event deltas.

    ``reference`` is the natural key we upsert on (the permit/work reference, the
    activity reference, or the section 58 reference depending on ``record_type``).
    """

    reference: str
    record_type: str  # "permit" | "activity" | "section_58"

    # Latest event applied + the status it implies.
    last_event_type: EventType = EventType.UNKNOWN
    status: ClosureStatus = ClosureStatus.PROPOSED

    # Ordering keys for idempotent, order-tolerant upserts.
    version: int | None = None
    event_time: str | None = None  # ISO 8601 UTC

    # All the references we know about.
    permit_reference_number: str | None = None
    work_reference_number: str | None = None
    activity_reference_number: str | None = None
    section_58_reference_number: str | None = None

    # Who / where.
    promoter_organisation: str | None = None
    highway_authority: str | None = None
    highway_authority_swa_code: str | None = None
    street_name: str | None = None
    usrn: str | None = None
    area_name: str | None = None
    town: str | None = None

    # What.
    work_category: str | None = None
    traffic_management_type: str | None = None
    traffic_management_type_ref: str | None = None
    work_status: str | None = None

    # When (date and time kept separate; a null time means "unspecified").
    proposed_start_date: str | None = None
    proposed_start_time: str | None = None
    proposed_end_date: str | None = None
    proposed_end_time: str | None = None
    actual_start_date_time: str | None = None
    actual_end_date_time: str | None = None

    # Geometry in both CRSs (GeoJSON geometry dicts) + a WGS84 representative
    # point used for the bounding-box test.
    geometry_27700: dict | None = None
    geometry_4326: dict | None = None
    representative_lon: float | None = None
    representative_lat: float | None = None

    # The raw inner ``object_data`` payload, retained for audit/backfill.
    raw: dict[str, Any] = field(default_factory=dict)

    # ── ordering ──────────────────────────────────────────────────────────
    def order_key(self) -> tuple[int, str]:
        """Higher = more recent. Sorts by version, then event_time as tiebreak."""
        return (self.version if self.version is not None else -1, self.event_time or "")

    @property
    def primary_start_date(self) -> str | None:
        return self.proposed_start_date

    # ── serialisation ─────────────────────────────────────────────────────
    def to_feature(self) -> dict:
        """Render as a GeoJSON Feature (geometry in WGS84)."""
        props = asdict(self)
        # Geometry travels in the Feature's ``geometry`` slot, not properties.
        props.pop("geometry_4326", None)
        props.pop("raw", None)
        # Enums → their string values for clean JSON.
        props["status"] = self.status.value
        props["last_event_type"] = self.last_event_type.value
        return {
            "type": "Feature",
            "geometry": self.geometry_4326,
            "properties": props,
        }
