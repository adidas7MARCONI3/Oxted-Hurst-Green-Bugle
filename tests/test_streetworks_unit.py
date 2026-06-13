"""Unit tests for the Street Manager closure service internals."""
from __future__ import annotations

import base64

import pytest

pytest.importorskip("pyproj")

from streetworks import sns  # noqa: E402
from streetworks.config import BBox, DEFAULT_TOPIC_ARNS, Settings, load_bbox  # noqa: E402
from streetworks.events import (  # noqa: E402
    ClosureStatus,
    EventType,
    apply_event,
    normalise_event_type,
)
from streetworks.filtering import passes_authority, passes_geography  # noqa: E402
from streetworks.geo import convert_wkt, parse_wkt  # noqa: E402
from streetworks.models import Closure  # noqa: E402
from streetworks.processor import process_notification  # noqa: E402
from streetworks.store import InMemoryStore, filter_closures  # noqa: E402


def _settings(swa="0000", **kw):
    base = dict(
        surrey_swa_code=swa,
        bbox=load_bbox(),
        allowed_topic_arns=DEFAULT_TOPIC_ARNS,
        verify_signatures=False,
        health_max_silence_hours=6.0,
        database_url=None,
    )
    base.update(kw)
    return Settings(**base)


# ── event-type normalisation ──────────────────────────────────────────────

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("work-start", EventType.WORK_START),
        ("WORK_START", EventType.WORK_START),
        ("Work Start", EventType.WORK_START),
        ("PERMIT_GRANTED", EventType.PERMIT_GRANTED),
        ("activity-created", EventType.ACTIVITY_CREATED),
        ("section-58-in-force", EventType.SECTION_58_IN_FORCE),
        ("work-stop-reverted", EventType.WORK_STOP_REVERTED),
        ("something_new", EventType.UNKNOWN),
        ("", EventType.UNKNOWN),
        (None, EventType.UNKNOWN),
    ],
)
def test_normalise_event_type(raw, expected):
    assert normalise_event_type(raw) == expected


# ── status lifecycle ────────────────────────────────────────────────────────

def test_lifecycle_forward():
    s = apply_event(None, EventType.PERMIT_GRANTED)
    assert s == ClosureStatus.PROPOSED and s.is_active
    s = apply_event(s, EventType.WORK_START)
    assert s == ClosureStatus.IN_PROGRESS and s.is_active
    s = apply_event(s, EventType.WORK_STOP)
    assert s == ClosureStatus.COMPLETED and not s.is_active


def test_lifecycle_cancel_and_revert():
    assert apply_event(ClosureStatus.PROPOSED, EventType.PERMIT_REVOKED) == ClosureStatus.INACTIVE
    # work-start-reverted rolls back to proposed; work-stop-reverted to in_progress
    assert apply_event(ClosureStatus.IN_PROGRESS, EventType.WORK_START_REVERTED) == ClosureStatus.PROPOSED
    assert apply_event(ClosureStatus.COMPLETED, EventType.WORK_STOP_REVERTED) == ClosureStatus.IN_PROGRESS


def test_apply_event_is_idempotent():
    s = apply_event(ClosureStatus.IN_PROGRESS, EventType.WORK_START)
    assert s == apply_event(s, EventType.WORK_START) == ClosureStatus.IN_PROGRESS


# ── geometry ────────────────────────────────────────────────────────────────

def test_parse_wkt_point_and_linestring():
    assert parse_wkt("POINT(539000 152400)") == ("POINT", [(539000.0, 152400.0)])
    gt, pts = parse_wkt("LINESTRING(539000 152400, 539100 152500)")
    assert gt == "LINESTRING" and len(pts) == 2


def test_parse_wkt_rejects_garbage():
    with pytest.raises(ValueError):
        parse_wkt("POLYGON((0 0,1 1))")
    with pytest.raises(ValueError):
        parse_wkt("not wkt")


def test_convert_wkt_point_lands_on_oxted():
    geom_27700, geom_4326, (lon, lat) = convert_wkt("POINT(539000 152400)")
    assert geom_27700["type"] == "Point"
    assert geom_4326["type"] == "Point"
    # Near Oxted town centre (~51.256 N, -0.005 W).
    assert -0.045 <= lon <= 0.025
    assert 51.225 <= lat <= 51.275


def test_convert_wkt_linestring_preserves_vertices():
    _, geom_4326, _ = convert_wkt("LINESTRING(539000 152400, 539100 152500)")
    assert geom_4326["type"] == "LineString"
    assert len(geom_4326["coordinates"]) == 2


# ── two-stage filter ────────────────────────────────────────────────────────

def test_stage1_authority_by_attribute_or_body():
    s = _settings(swa="1234")
    assert passes_authority({}, {"ha_org": "1234"}, s)
    assert passes_authority({"highway_authority_swa_code": "1234"}, {}, s)
    assert not passes_authority({"highway_authority_swa_code": "9999"}, {"ha_org": "9999"}, s)


def test_stage2_geography_bbox_and_usrn_allow_list():
    box = BBox(min_lat=51.0, max_lat=52.0, min_lon=-1.0, max_lon=1.0)
    assert passes_geography(0.0, 51.5, box)
    assert not passes_geography(5.0, 51.5, box)
    # USRN allow-list overrides the box.
    assert passes_geography(5.0, 51.5, box, usrn="42", usrn_allow_list=frozenset({"42"}))


# ── processor (no HTTP) ─────────────────────────────────────────────────────

def _notification(object_data, event_type="work-start", swa="0000"):
    import json

    return {
        "Type": "Notification",
        "TopicArn": "arn:aws:sns:eu-west-2:287813576808:prod-permit-topic",
        "Message": json.dumps({"event_type": event_type, "object_data": object_data}),
        "MessageAttributes": {"ha_org": {"Value": swa}},
    }


def test_processor_accepts_oxted_record():
    obj = {
        "permit_reference_number": "P-1",
        "highway_authority_swa_code": "0000",
        "street_name": "Station Road East",
        "traffic_management_type": "Road closure",
        "works_location_coordinates": "POINT(539000 152400)",
        "version": 1,
    }
    result = process_notification(_notification(obj), _settings())
    assert result.accepted
    assert result.closure.status == ClosureStatus.IN_PROGRESS
    assert result.closure.record_type == "permit"


def test_processor_rejects_wrong_authority():
    obj = {"permit_reference_number": "P-2", "highway_authority_swa_code": "8888",
           "works_location_coordinates": "POINT(539000 152400)"}
    result = process_notification(_notification(obj, swa="8888"), _settings(swa="0000"))
    assert not result.accepted and "stage-1" in result.reason


def test_processor_rejects_out_of_box():
    obj = {"permit_reference_number": "P-3", "highway_authority_swa_code": "0000",
           "works_location_coordinates": "POINT(499700 149600)"}
    result = process_notification(_notification(obj), _settings())
    assert not result.accepted and "stage-2" in result.reason


def test_processor_dead_letters_bad_inner_json():
    env = {"Type": "Notification", "Message": "{not json",
           "MessageAttributes": {"ha_org": {"Value": "0000"}}}
    result = process_notification(env, _settings())
    assert not result.accepted and "unparseable" in result.reason


# ── store: idempotent, order-tolerant upsert ────────────────────────────────

def _closure(ref="P-1", event=EventType.PERMIT_GRANTED, version=1, **kw):
    c = Closure(reference=ref, record_type="permit", last_event_type=event,
                status=apply_event(None, event), version=version, **kw)
    return c


def test_store_upsert_accumulates_status():
    store = InMemoryStore()
    store.upsert(_closure(event=EventType.PERMIT_GRANTED, version=1, street_name="High St"))
    store.upsert(_closure(event=EventType.WORK_START, version=2))
    c = store.get("P-1")
    assert c.status == ClosureStatus.IN_PROGRESS
    # field from the earlier event is retained
    assert c.street_name == "High St"


def test_store_out_of_order_event_does_not_clobber():
    store = InMemoryStore()
    store.upsert(_closure(event=EventType.WORK_START, version=5))
    # A late-arriving older PERMIT_GRANTED (v2) must not roll status back.
    store.upsert(_closure(event=EventType.PERMIT_GRANTED, version=2, street_name="Late St"))
    c = store.get("P-1")
    assert c.status == ClosureStatus.IN_PROGRESS
    # but it may back-fill a previously-missing field
    assert c.street_name == "Late St"


def test_store_upsert_is_idempotent():
    store = InMemoryStore()
    e = _closure(event=EventType.WORK_START, version=2)
    store.upsert(e)
    store.upsert(_closure(event=EventType.WORK_START, version=2))
    assert store.get("P-1").status == ClosureStatus.IN_PROGRESS
    assert len(store.list_closures()) == 1


def test_filter_closures_active_only_and_filters():
    store = InMemoryStore()
    store.upsert(_closure(ref="A", event=EventType.WORK_START, version=1,
                          traffic_management_type="Road closure", work_category="Major",
                          proposed_start_date="2026-06-08"))
    store.upsert(_closure(ref="B", event=EventType.WORK_STOP, version=1,
                          traffic_management_type="Lane closure",
                          proposed_start_date="2026-06-01"))
    # active_only drops the completed one
    active = filter_closures(store.list_closures(), active_only=True)
    assert [c.reference for c in active] == ["A"]
    # type filter
    assert filter_closures(store.list_closures(), active_only=False,
                           traffic_management_type="Lane closure")[0].reference == "B"
    # explicit status filter
    assert filter_closures(store.list_closures(), status="completed")[0].reference == "B"


# ── SNS signature verification (self-signed cert, no network) ───────────────

def _make_cert_and_sign(canonical: str):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    from cryptography.x509.oid import NameOID
    import datetime as dt

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "sns.amazonaws.com")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc))
        .not_valid_after(dt.datetime(2040, 1, 1, tzinfo=dt.timezone.utc))
        .sign(key, hashes.SHA256())
    )
    pem = cert.public_bytes(serialization.Encoding.PEM)
    signature = key.sign(canonical.encode(), padding.PKCS1v15(), hashes.SHA1())
    return pem, base64.b64encode(signature).decode()


def _signed_envelope():
    env = {
        "Type": "Notification",
        "MessageId": "abc",
        "Subject": "s",
        "Message": "hello",
        "Timestamp": "2026-06-08T00:00:00.000Z",
        "TopicArn": "arn:aws:sns:eu-west-2:287813576808:prod-permit-topic",
        "SignatureVersion": "1",
        "SigningCertURL": "https://sns.eu-west-2.amazonaws.com/cert.pem",
    }
    pem, sig = _make_cert_and_sign(sns.canonical_string(env))
    env["Signature"] = sig
    return env, pem


def test_signature_verifies_with_valid_cert():
    env, pem = _signed_envelope()
    sns.verify_signature(env, cert_fetcher=lambda url: pem)  # no raise


def test_signature_rejects_non_aws_cert_host():
    env, pem = _signed_envelope()
    env["SigningCertURL"] = "https://evil.example.com/cert.pem"
    with pytest.raises(sns.SignatureError):
        sns.verify_signature(env, cert_fetcher=lambda url: pem)


def test_signature_rejects_tampered_message():
    env, pem = _signed_envelope()
    env["Message"] = "tampered"
    with pytest.raises(sns.SignatureError):
        sns.verify_signature(env, cert_fetcher=lambda url: pem)


def test_confirm_subscription_gets_subscribe_url():
    seen = {}
    env = {"Type": "SubscriptionConfirmation", "SubscribeURL": "https://sns.eu-west-2.amazonaws.com/?confirm=1"}
    sns.confirm_subscription(env, getter=lambda url: seen.setdefault("url", url))
    assert seen["url"].endswith("confirm=1")
