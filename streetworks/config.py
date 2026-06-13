"""Runtime configuration for the Street Manager closure service.

Everything is driven by environment variables with sensible defaults so the
service runs out of the box. The two settings the owner will care about are
``SURREY_SWA_CODE`` (the Street Works Authority code for Surrey County Council)
and the bounding box that scopes records to Oxted & Hurst Green.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

# ── The three Street Manager production SNS topics (region eu-west-2, account
# 287813576808). These are fixed facts about the feed, not configuration.
PERMIT_TOPIC_ARN = "arn:aws:sns:eu-west-2:287813576808:prod-permit-topic"
ACTIVITY_TOPIC_ARN = "arn:aws:sns:eu-west-2:287813576808:prod-activity-topic"
SECTION_58_TOPIC_ARN = "arn:aws:sns:eu-west-2:287813576808:prod-section-58-topic"

DEFAULT_TOPIC_ARNS = frozenset(
    {PERMIT_TOPIC_ARN, ACTIVITY_TOPIC_ARN, SECTION_58_TOPIC_ARN}
)

# Placeholder SWA code. Surrey County Council is the street authority for
# Oxted/Hurst Green (two-tier England — the county, not the district, holds
# highway-authority permits). The real code is dropped in via the env var.
DEFAULT_SURREY_SWA_CODE = "0000"


@dataclass(frozen=True)
class BBox:
    """A simple lon/lat bounding box (WGS84 / EPSG:4326)."""

    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float

    def contains(self, lon: float, lat: float) -> bool:
        return (
            self.min_lon <= lon <= self.max_lon
            and self.min_lat <= lat <= self.max_lat
        )


@dataclass(frozen=True)
class Settings:
    surrey_swa_code: str
    bbox: BBox
    allowed_topic_arns: frozenset[str]
    # Verify SNS message signatures. Disable ONLY for local testing.
    verify_signatures: bool
    # Health check alerts if no message has arrived in this many hours.
    health_max_silence_hours: float
    # Optional Postgres/PostGIS connection string. When unset the service uses
    # an in-memory store (handy for tests and a quick local spin-up).
    database_url: str | None


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_bbox() -> BBox:
    """Bounding box covering Oxted and Hurst Green (adjacent villages)."""
    return BBox(
        min_lat=_env_float("BBOX_MIN_LAT", 51.225),
        max_lat=_env_float("BBOX_MAX_LAT", 51.275),
        min_lon=_env_float("BBOX_MIN_LON", -0.045),
        max_lon=_env_float("BBOX_MAX_LON", 0.025),
    )


def load_settings() -> Settings:
    return Settings(
        surrey_swa_code=os.getenv("SURREY_SWA_CODE", DEFAULT_SURREY_SWA_CODE),
        bbox=load_bbox(),
        allowed_topic_arns=DEFAULT_TOPIC_ARNS,
        verify_signatures=_env_bool("SNS_VERIFY_SIGNATURES", True),
        health_max_silence_hours=_env_float("HEALTH_MAX_SILENCE_HOURS", 6.0),
        database_url=os.getenv("DATABASE_URL") or None,
    )
