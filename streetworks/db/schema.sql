-- Street Manager closures — Postgres + PostGIS schema / migration.
-- Apply once against an empty database:
--   psql "$DATABASE_URL" -f streetworks/db/schema.sql
--
-- Idempotent: safe to re-run. The DB starts empty and fills as SNS events
-- arrive (there is no anonymous backfill — see the README cold-start note).

CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS closures (
    reference                    TEXT PRIMARY KEY,
    record_type                  TEXT NOT NULL,          -- permit | activity | section_58
    last_event_type              TEXT NOT NULL,
    status                       TEXT NOT NULL,          -- proposed | in_progress | completed | inactive

    -- Ordering keys for idempotent, order-tolerant upserts.
    version                      INTEGER,
    event_time                   TEXT,

    -- References.
    permit_reference_number      TEXT,
    work_reference_number        TEXT,
    activity_reference_number    TEXT,
    section_58_reference_number  TEXT,

    -- Who / where.
    promoter_organisation        TEXT,
    highway_authority            TEXT,
    highway_authority_swa_code   TEXT,
    street_name                  TEXT,
    usrn                         TEXT,
    area_name                    TEXT,
    town                         TEXT,

    -- What.
    work_category                TEXT,
    traffic_management_type      TEXT,
    traffic_management_type_ref  TEXT,
    work_status                  TEXT,

    -- When (date and time kept separate; NULL time = unspecified).
    proposed_start_date          TEXT,
    proposed_start_time          TEXT,
    proposed_end_date            TEXT,
    proposed_end_time            TEXT,
    actual_start_date_time       TEXT,
    actual_end_date_time         TEXT,

    -- Geometry in both CRSs.
    geom_27700                   geometry(Geometry, 27700),
    geom_4326                    geometry(Geometry, 4326),

    -- Full raw payload for audit / future backfill.
    raw                          JSONB NOT NULL DEFAULT '{}'::jsonb,

    updated_at                   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS closures_status_idx ON closures (status);
CREATE INDEX IF NOT EXISTS closures_tmt_idx ON closures (traffic_management_type);
CREATE INDEX IF NOT EXISTS closures_start_idx ON closures (proposed_start_date);
CREATE INDEX IF NOT EXISTS closures_geom_4326_idx ON closures USING GIST (geom_4326);

-- Single-row table tracking the last time any SNS message arrived, for the
-- health check / "no traffic in N hours" alert.
CREATE TABLE IF NOT EXISTS feed_health (
    id               INTEGER PRIMARY KEY DEFAULT 1,
    last_message_at  TEXT,
    CONSTRAINT feed_health_singleton CHECK (id = 1)
);
