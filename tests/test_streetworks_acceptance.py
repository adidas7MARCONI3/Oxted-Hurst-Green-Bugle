"""Acceptance test for the Street Manager closure feed — written FIRST.

End-to-end: a sample SNS ``Notification`` for a permit ``work-start`` on an
Oxted street (coordinates EPSG:27700 inside the box) is POSTed to the webhook
with the signature path stubbed, then flows through

    parse → Stage 1 SWA filter → coords converted → Stage 2 bbox filter →
    upserted → returned by ``GET /closures`` as GeoJSON

with the correct status and geometry. The negative case — a Surrey permit
outside the box (Guildford) — is excluded.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

# These imports require the streetworks extra (fastapi, pyproj, httpx, ...).
fastapi_testclient = pytest.importorskip("fastapi.testclient")
pytest.importorskip("pyproj")

from streetworks.api import create_app  # noqa: E402
from streetworks.config import DEFAULT_TOPIC_ARNS, PERMIT_TOPIC_ARN, Settings, load_bbox  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"

# The fixtures and these settings agree on the placeholder SWA code "0000".
SWA_CODE = "0000"


def _settings() -> Settings:
    return Settings(
        surrey_swa_code=SWA_CODE,
        bbox=load_bbox(),  # default Oxted/Hurst Green box
        allowed_topic_arns=DEFAULT_TOPIC_ARNS,
        verify_signatures=False,  # signature path stubbed for this test
        health_max_silence_hours=6.0,
        database_url=None,
    )


def _load_inner(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _envelope(inner: dict, *, topic: str = PERMIT_TOPIC_ARN) -> dict:
    """Wrap a Street Manager event in a realistic SNS Notification envelope."""
    swa = inner["object_data"].get("highway_authority_swa_code", SWA_CODE)
    return {
        "Type": "Notification",
        "MessageId": "11111111-2222-3333-4444-555555555555",
        "TopicArn": topic,
        "Subject": "Street Manager event",
        "Message": json.dumps(inner),
        "Timestamp": "2026-06-08T08:02:12.000Z",
        "SignatureVersion": "1",
        "Signature": "c3R1Yg==",
        "SigningCertURL": "https://sns.eu-west-2.amazonaws.com/SimpleNotificationService-stub.pem",
        "MessageAttributes": {
            "area": {"Type": "String", "Value": "Surrey"},
            "ha_org": {"Type": "String", "Value": swa},
            "activity_type": {"Type": "String", "Value": "Remedial works"},
        },
    }


@pytest.fixture()
def client():
    app = create_app(settings=_settings())
    with fastapi_testclient.TestClient(app) as c:
        yield c


def test_oxted_work_start_flows_end_to_end_to_geojson(client):
    inner = _load_inner("permit_work_start_oxted.json")
    resp = client.post("/sns", json=_envelope(inner))
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"

    # TestClient runs the background task before returning, so state is ready.
    geo = client.get("/closures").json()
    assert geo["type"] == "FeatureCollection"
    assert len(geo["features"]) == 1

    feature = geo["features"][0]
    props = feature["properties"]

    # Status came from the work-start event.
    assert props["status"] == "in_progress"
    assert props["street_name"] == "Station Road East"
    assert props["traffic_management_type"] == "Road closure"
    assert props["reference"] == "TQ0900000-PERM-2026-001"
    # Null proposed_end_time preserved, not coerced to midnight.
    assert props["proposed_end_time"] is None

    # Geometry converted to WGS84 and lands on Oxted.
    assert feature["geometry"]["type"] == "Point"
    lon, lat = feature["geometry"]["coordinates"]
    assert -0.045 <= lon <= 0.025
    assert 51.225 <= lat <= 51.275


def test_guildford_permit_is_excluded_by_bbox(client):
    # Same Surrey authority (passes Stage 1) but outside the box (fails Stage 2).
    inner = _load_inner("permit_work_start_guildford.json")
    resp = client.post("/sns", json=_envelope(inner))
    assert resp.status_code == 200

    geo = client.get("/closures").json()
    assert geo["features"] == []


def test_both_together_keeps_only_oxted(client):
    client.post("/sns", json=_envelope(_load_inner("permit_work_start_oxted.json")))
    client.post("/sns", json=_envelope(_load_inner("permit_work_start_guildford.json")))

    geo = client.get("/closures").json()
    streets = [f["properties"]["street_name"] for f in geo["features"]]
    assert streets == ["Station Road East"]


def test_unknown_topic_is_rejected(client):
    inner = _load_inner("permit_work_start_oxted.json")
    env = _envelope(inner, topic="arn:aws:sns:eu-west-2:287813576808:some-other-topic")
    resp = client.post("/sns", json=env)
    assert resp.status_code == 403
