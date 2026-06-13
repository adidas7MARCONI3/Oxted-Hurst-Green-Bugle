"""Turn an SNS Notification into a normalised :class:`Closure` (or a rejection).

The pipeline: parse inner Message → normalise event type → Stage 1 authority
filter → convert coordinates → Stage 2 bounding-box filter → build the record.
Unparseable or unfilterable payloads are reported (for dead-lettering), never
silently dropped.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import sns
from .config import Settings
from .events import EventType, apply_event, normalise_event_type
from .filtering import passes_authority, passes_geography
from .geo import convert_wkt
from .models import Closure

# Which WKT field carries the geometry, by record type.
_COORD_FIELDS = (
    "works_location_coordinates",
    "activity_coordinates",
    "section_58_coordinates",
)

_RECORD_TYPE_BY_COORD_FIELD = {
    "works_location_coordinates": "permit",
    "activity_coordinates": "activity",
    "section_58_coordinates": "section_58",
}


@dataclass
class ProcessResult:
    """Outcome of processing one Notification."""

    closure: Closure | None
    accepted: bool
    reason: str

    @classmethod
    def reject(cls, reason: str) -> "ProcessResult":
        return cls(closure=None, accepted=False, reason=reason)

    @classmethod
    def accept(cls, closure: Closure) -> "ProcessResult":
        return cls(closure=closure, accepted=True, reason="accepted")


def _first_present(data: dict, *keys: str) -> str | None:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return None


def _natural_reference(object_data: dict, record_type: str) -> str | None:
    if record_type == "permit":
        return _first_present(
            object_data, "permit_reference_number", "work_reference_number"
        )
    if record_type == "activity":
        return _first_present(
            object_data, "activity_reference_number", "activity_reference"
        )
    if record_type == "section_58":
        return _first_present(
            object_data, "section_58_reference_number", "section_58_reference"
        )
    return None


def _coord_field(object_data: dict) -> str | None:
    for field_name in _COORD_FIELDS:
        if object_data.get(field_name):
            return field_name
    return None


def build_closure(object_data: dict, event_type: EventType, record_type: str) -> Closure:
    """Map a raw ``object_data`` payload onto a :class:`Closure` (no filtering)."""
    reference = _natural_reference(object_data, record_type) or ""
    closure = Closure(
        reference=reference,
        record_type=record_type,
        last_event_type=event_type,
        status=apply_event(None, event_type),
        version=_coerce_int(object_data.get("version")),
        event_time=_first_present(
            object_data, "event_time", "event_reference_datetime", "datetime"
        ),
        permit_reference_number=object_data.get("permit_reference_number"),
        work_reference_number=object_data.get("work_reference_number"),
        activity_reference_number=_first_present(
            object_data, "activity_reference_number", "activity_reference"
        ),
        section_58_reference_number=_first_present(
            object_data, "section_58_reference_number", "section_58_reference"
        ),
        promoter_organisation=object_data.get("promoter_organisation"),
        highway_authority=object_data.get("highway_authority"),
        highway_authority_swa_code=object_data.get("highway_authority_swa_code"),
        street_name=object_data.get("street_name"),
        usrn=_as_str(object_data.get("usrn")),
        area_name=object_data.get("area_name"),
        town=object_data.get("town"),
        work_category=object_data.get("work_category"),
        traffic_management_type=object_data.get("traffic_management_type"),
        traffic_management_type_ref=object_data.get("traffic_management_type_ref"),
        work_status=object_data.get("work_status"),
        proposed_start_date=object_data.get("proposed_start_date"),
        proposed_start_time=object_data.get("proposed_start_time"),
        proposed_end_date=object_data.get("proposed_end_date"),
        proposed_end_time=object_data.get("proposed_end_time"),
        actual_start_date_time=object_data.get("actual_start_date_time"),
        actual_end_date_time=object_data.get("actual_end_date_time"),
        raw=object_data,
    )
    return closure


def _coerce_int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_str(value) -> str | None:
    return None if value is None else str(value)


def process_notification(envelope: dict, settings: Settings) -> ProcessResult:
    """Run a parsed SNS ``Notification`` envelope through the full pipeline."""
    try:
        inner = sns.parse_inner_message(envelope)
    except Exception as exc:  # malformed inner JSON → dead-letter
        return ProcessResult.reject(f"unparseable inner message: {exc}")

    object_data = inner.get("object_data")
    if not isinstance(object_data, dict):
        return ProcessResult.reject("notification has no object_data object")

    event_type = normalise_event_type(inner.get("event_type"))
    attributes = sns.message_attributes(envelope)

    # ── Stage 1: authority ────────────────────────────────────────────────
    if not passes_authority(object_data, attributes, settings):
        return ProcessResult.reject("stage-1 authority filter: not Surrey CC")

    coord_field = _coord_field(object_data)
    if coord_field is None:
        return ProcessResult.reject("no coordinates to place this record")
    record_type = _RECORD_TYPE_BY_COORD_FIELD[coord_field]

    # ── coordinate conversion ─────────────────────────────────────────────
    try:
        geom_27700, geom_4326, (lon, lat) = convert_wkt(object_data[coord_field])
    except Exception as exc:
        return ProcessResult.reject(f"coordinate conversion failed: {exc}")

    # ── Stage 2: geography ────────────────────────────────────────────────
    if not passes_geography(lon, lat, settings.bbox, usrn=_as_str(object_data.get("usrn"))):
        return ProcessResult.reject("stage-2 bbox filter: outside Oxted/Hurst Green")

    closure = build_closure(object_data, event_type, record_type)
    closure.geometry_27700 = geom_27700
    closure.geometry_4326 = geom_4326
    closure.representative_lon = lon
    closure.representative_lat = lat
    return ProcessResult.accept(closure)
