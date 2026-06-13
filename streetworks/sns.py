"""AWS SNS envelope handling: parsing, signature verification, subscription.

Every HTTP call from SNS is an envelope whose ``Type`` is one of
``SubscriptionConfirmation``, ``Notification`` or ``UnsubscribeConfirmation``.
For a ``Notification`` the ``Message`` field is itself a JSON string (the Street
Manager event), which we parse a second time downstream.

Signature verification follows the documented SNS scheme: rebuild the canonical
string from a fixed set of fields, fetch the signing certificate from
``SigningCertURL`` (only ever from an ``amazonaws.com`` host), and verify the
RSA signature (SHA1 for SignatureVersion 1, SHA256 for version 2).
"""
from __future__ import annotations

import base64
import json
from typing import Callable
from urllib.parse import urlparse

# Fields that go into the canonical string, in order, per message type.
_SIGNED_KEYS = {
    "Notification": ["Message", "MessageId", "Subject", "Timestamp", "TopicArn", "Type"],
    "SubscriptionConfirmation": [
        "Message", "MessageId", "SubscribeURL", "Timestamp", "Token", "TopicArn", "Type",
    ],
    "UnsubscribeConfirmation": [
        "Message", "MessageId", "SubscribeURL", "Timestamp", "Token", "TopicArn", "Type",
    ],
}


class SignatureError(Exception):
    """Raised when an SNS message fails signature verification."""


def parse_envelope(raw: bytes | str) -> dict:
    """Parse the outer SNS envelope JSON."""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw)


def parse_inner_message(envelope: dict) -> dict:
    """Parse the inner ``Message`` string of a Notification into a dict."""
    message = envelope.get("Message")
    if isinstance(message, dict):
        return message
    if not isinstance(message, str):
        raise ValueError("Notification has no string Message to parse")
    return json.loads(message)


def message_attributes(envelope: dict) -> dict[str, str]:
    """Flatten SNS ``MessageAttributes`` to a plain ``{name: value}`` dict.

    These cheap pre-filter attributes include ``area``, ``ha_org``,
    ``activity_type``, ``promoter_org`` and ``usrn``.
    """
    attrs = envelope.get("MessageAttributes") or {}
    flat: dict[str, str] = {}
    for name, spec in attrs.items():
        if isinstance(spec, dict) and "Value" in spec:
            flat[name] = spec["Value"]
        else:
            flat[name] = spec  # already flat
    return flat


def canonical_string(envelope: dict) -> str:
    """Build the string-to-sign for an SNS envelope."""
    msg_type = envelope.get("Type")
    keys = _SIGNED_KEYS.get(msg_type)
    if keys is None:
        raise SignatureError(f"cannot sign unknown SNS type {msg_type!r}")
    lines: list[str] = []
    for key in keys:
        value = envelope.get(key)
        if value is None:
            continue
        lines.append(key)
        lines.append(str(value))
    return "\n".join(lines) + "\n"


def _cert_host_is_aws(cert_url: str) -> bool:
    parsed = urlparse(cert_url)
    if parsed.scheme != "https":
        return False
    host = (parsed.hostname or "").lower()
    return host == "amazonaws.com" or host.endswith(".amazonaws.com")


def _default_cert_fetcher(cert_url: str) -> bytes:
    import httpx

    resp = httpx.get(cert_url, timeout=10.0)
    resp.raise_for_status()
    return resp.content


def verify_signature(
    envelope: dict,
    *,
    cert_fetcher: Callable[[str], bytes] = _default_cert_fetcher,
) -> None:
    """Verify the SNS message signature. Raises :class:`SignatureError` on failure.

    ``cert_fetcher`` is injectable so tests can supply a certificate without a
    network call.
    """
    cert_url = envelope.get("SigningCertURL") or envelope.get("SigningCertUrl")
    if not cert_url:
        raise SignatureError("message has no SigningCertURL")
    if not _cert_host_is_aws(cert_url):
        raise SignatureError(f"signing cert host is not under amazonaws.com: {cert_url}")

    signature_b64 = envelope.get("Signature")
    if not signature_b64:
        raise SignatureError("message has no Signature")

    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.x509 import load_pem_x509_certificate
    except ImportError as exc:  # pragma: no cover - depends on env
        raise SignatureError("cryptography is required for signature verification") from exc

    pem = cert_fetcher(cert_url)
    cert = load_pem_x509_certificate(pem)
    public_key = cert.public_key()

    version = str(envelope.get("SignatureVersion", "1"))
    hash_alg = hashes.SHA256() if version == "2" else hashes.SHA1()

    try:
        public_key.verify(
            base64.b64decode(signature_b64),
            canonical_string(envelope).encode("utf-8"),
            padding.PKCS1v15(),
            hash_alg,
        )
    except Exception as exc:  # cryptography raises InvalidSignature et al.
        raise SignatureError("SNS signature verification failed") from exc


def confirm_subscription(
    envelope: dict,
    *,
    getter: Callable[[str], None] | None = None,
) -> str:
    """Confirm an SNS subscription by GETting the ``SubscribeURL``.

    Returns the URL that was confirmed. ``getter`` is injectable for tests.
    """
    subscribe_url = envelope.get("SubscribeURL")
    if not subscribe_url:
        raise ValueError("SubscriptionConfirmation has no SubscribeURL")

    if getter is None:
        import httpx

        def getter(url: str) -> None:  # type: ignore[misc]
            httpx.get(url, timeout=10.0).raise_for_status()

    getter(subscribe_url)
    return subscribe_url
