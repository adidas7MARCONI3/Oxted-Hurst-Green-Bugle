"""Postgres + PostGIS implementation of the closure store.

Mirrors :class:`streetworks.store.InMemoryStore` so the API is identical. The
schema and migration live in ``streetworks/db/schema.sql``; apply it once before
first use (see the README). SQLAlchemy + psycopg are imported lazily so the
in-memory path never needs them.

The same idempotent, order-tolerant upsert rule applies: an event only updates
state when its ``(version, event_time)`` is at least the stored one. We let the
database enforce this with an ``ON CONFLICT`` guard.
"""
from __future__ import annotations

import json
from dataclasses import asdict

from .events import ClosureStatus, EventType, apply_event
from .models import Closure

_UPSERT_SQL = """
INSERT INTO closures (
    reference, record_type, last_event_type, status, version, event_time,
    permit_reference_number, work_reference_number, activity_reference_number,
    section_58_reference_number, promoter_organisation, highway_authority,
    highway_authority_swa_code, street_name, usrn, area_name, town,
    work_category, traffic_management_type, traffic_management_type_ref,
    work_status, proposed_start_date, proposed_start_time, proposed_end_date,
    proposed_end_time, actual_start_date_time, actual_end_date_time,
    geom_27700, geom_4326, raw, updated_at
) VALUES (
    :reference, :record_type, :last_event_type, :status, :version, :event_time,
    :permit_reference_number, :work_reference_number, :activity_reference_number,
    :section_58_reference_number, :promoter_organisation, :highway_authority,
    :highway_authority_swa_code, :street_name, :usrn, :area_name, :town,
    :work_category, :traffic_management_type, :traffic_management_type_ref,
    :work_status, :proposed_start_date, :proposed_start_time, :proposed_end_date,
    :proposed_end_time, :actual_start_date_time, :actual_end_date_time,
    ST_GeomFromGeoJSON(:geom_27700_json), ST_GeomFromGeoJSON(:geom_4326_json),
    CAST(:raw_json AS JSONB), NOW()
)
ON CONFLICT (reference) DO UPDATE SET
    last_event_type = EXCLUDED.last_event_type,
    status = EXCLUDED.status,
    version = EXCLUDED.version,
    event_time = EXCLUDED.event_time,
    street_name = COALESCE(EXCLUDED.street_name, closures.street_name),
    traffic_management_type = COALESCE(EXCLUDED.traffic_management_type, closures.traffic_management_type),
    work_category = COALESCE(EXCLUDED.work_category, closures.work_category),
    promoter_organisation = COALESCE(EXCLUDED.promoter_organisation, closures.promoter_organisation),
    proposed_start_date = COALESCE(EXCLUDED.proposed_start_date, closures.proposed_start_date),
    proposed_end_date = COALESCE(EXCLUDED.proposed_end_date, closures.proposed_end_date),
    actual_start_date_time = COALESCE(EXCLUDED.actual_start_date_time, closures.actual_start_date_time),
    actual_end_date_time = COALESCE(EXCLUDED.actual_end_date_time, closures.actual_end_date_time),
    geom_27700 = EXCLUDED.geom_27700,
    geom_4326 = EXCLUDED.geom_4326,
    raw = EXCLUDED.raw,
    updated_at = NOW()
WHERE
    -- order-tolerant: only overwrite with an event that is newer-or-equal
    COALESCE(EXCLUDED.version, -1) > COALESCE(closures.version, -1)
    OR (
        COALESCE(EXCLUDED.version, -1) = COALESCE(closures.version, -1)
        AND COALESCE(EXCLUDED.event_time, '') >= COALESCE(closures.event_time, '')
    )
"""


class PostgresStore:
    def __init__(self, database_url: str) -> None:
        from sqlalchemy import create_engine

        self._engine = create_engine(database_url, future=True)

    def _params(self, c: Closure) -> dict:
        # Compute the status the same way the in-memory store does so behaviour
        # matches: the new status is the event applied to whatever is stored.
        existing = self.get(c.reference)
        prior = existing.status if existing else None
        new_status = apply_event(prior, c.last_event_type)
        p = asdict(c)
        p.pop("geometry_27700", None)
        p.pop("geometry_4326", None)
        p.pop("representative_lon", None)
        p.pop("representative_lat", None)
        p.pop("raw", None)
        p["status"] = new_status.value
        p["last_event_type"] = c.last_event_type.value
        p["geom_27700_json"] = json.dumps(c.geometry_27700) if c.geometry_27700 else None
        p["geom_4326_json"] = json.dumps(c.geometry_4326) if c.geometry_4326 else None
        p["raw_json"] = json.dumps(c.raw or {})
        return p

    def upsert(self, closure: Closure) -> Closure:
        from sqlalchemy import text

        with self._engine.begin() as conn:
            conn.execute(text(_UPSERT_SQL), self._params(closure))
        return self.get(closure.reference) or closure

    def get(self, reference: str) -> Closure | None:
        from sqlalchemy import text

        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT *, ST_AsGeoJSON(geom_27700) AS gj27700, "
                    "ST_AsGeoJSON(geom_4326) AS gj4326 FROM closures WHERE reference = :ref"
                ),
                {"ref": reference},
            ).mappings().first()
        return _row_to_closure(row) if row else None

    def list_closures(self) -> list[Closure]:
        from sqlalchemy import text

        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT *, ST_AsGeoJSON(geom_27700) AS gj27700, "
                    "ST_AsGeoJSON(geom_4326) AS gj4326 FROM closures"
                )
            ).mappings().all()
        return [_row_to_closure(r) for r in rows]

    def record_message(self, when_iso: str) -> None:
        from sqlalchemy import text

        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO feed_health (id, last_message_at) VALUES (1, :ts) "
                    "ON CONFLICT (id) DO UPDATE SET last_message_at = :ts"
                ),
                {"ts": when_iso},
            )

    def last_message_at(self) -> str | None:
        from sqlalchemy import text

        with self._engine.connect() as conn:
            row = conn.execute(
                text("SELECT last_message_at FROM feed_health WHERE id = 1")
            ).first()
        return row[0] if row else None


def _row_to_closure(row) -> Closure:
    data = dict(row)
    geom_27700 = json.loads(data["gj27700"]) if data.get("gj27700") else None
    geom_4326 = json.loads(data["gj4326"]) if data.get("gj4326") else None
    raw = data.get("raw") or {}
    if isinstance(raw, str):
        raw = json.loads(raw)
    return Closure(
        reference=data["reference"],
        record_type=data["record_type"],
        last_event_type=EventType(data["last_event_type"]),
        status=ClosureStatus(data["status"]),
        version=data.get("version"),
        event_time=data.get("event_time"),
        permit_reference_number=data.get("permit_reference_number"),
        work_reference_number=data.get("work_reference_number"),
        activity_reference_number=data.get("activity_reference_number"),
        section_58_reference_number=data.get("section_58_reference_number"),
        promoter_organisation=data.get("promoter_organisation"),
        highway_authority=data.get("highway_authority"),
        highway_authority_swa_code=data.get("highway_authority_swa_code"),
        street_name=data.get("street_name"),
        usrn=data.get("usrn"),
        area_name=data.get("area_name"),
        town=data.get("town"),
        work_category=data.get("work_category"),
        traffic_management_type=data.get("traffic_management_type"),
        traffic_management_type_ref=data.get("traffic_management_type_ref"),
        work_status=data.get("work_status"),
        proposed_start_date=data.get("proposed_start_date"),
        proposed_start_time=data.get("proposed_start_time"),
        proposed_end_date=data.get("proposed_end_date"),
        proposed_end_time=data.get("proposed_end_time"),
        actual_start_date_time=data.get("actual_start_date_time"),
        actual_end_date_time=data.get("actual_end_date_time"),
        geometry_27700=geom_27700,
        geometry_4326=geom_4326,
        raw=raw,
    )
