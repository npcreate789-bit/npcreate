from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

DEVICE_FINGERPRINT_RE = re.compile(r"^[A-Za-z0-9_.:\-]{16,256}$")
MAX_METADATA_JSON_BYTES = 16_384


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def constant_time_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def hash_license_key(license_key: str, pepper: str) -> str:
    normalized = license_key.strip().upper().encode("utf-8")
    return hmac.new(pepper.encode("utf-8"), normalized, hashlib.sha256).hexdigest()


def hash_device_fingerprint(device_fingerprint: str, pepper: str) -> str:
    """Server-side HMAC for device fingerprints.

    Client fingerprints are treated as identifiers, not trusted secrets. Never
    store the client-supplied value directly because it may contain serials or
    other device-specific data.
    """
    normalized = device_fingerprint.strip().lower()
    if not DEVICE_FINGERPRINT_RE.match(normalized):
        raise ValueError("invalid device fingerprint format")
    return hmac.new(pepper.encode("utf-8"), normalized.encode("utf-8"), hashlib.sha256).hexdigest()


def sanitize_metadata(metadata: dict[str, Any], *, max_bytes: int = MAX_METADATA_JSON_BYTES) -> dict[str, Any]:
    """Keep user/device metadata small and JSON-safe before storing it."""
    encoded = json.dumps(metadata or {}, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > max_bytes:
        raise ValueError("metadata payload too large")
    safe: dict[str, Any] = {}
    for key, value in (metadata or {}).items():
        k = str(key)[:80]
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[k] = str(value)[:500] if isinstance(value, str) else value
        elif isinstance(value, list):
            safe[k] = value[:50]
        elif isinstance(value, dict):
            safe[k] = sanitize_metadata(value, max_bytes=max_bytes)
        else:
            safe[k] = str(value)[:500]
    return safe


def new_license_key(prefix: str = "NP") -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    token = "".join(secrets.choice(alphabet) for _ in range(20))
    return prefix + "-" + "-".join(token[i : i + 4] for i in range(0, 20, 4))


def sign_update_manifest(private_key_hex: str, *, version: str, channel: str, mandatory: bool, download_url: str, sha256: str) -> str:
    private_key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_key_hex))
    payload = f"{version}|{channel}|{mandatory}|{download_url}|{sha256}".encode("utf-8")
    return private_key.sign(payload).hex()


def create_token(secret: str, subject: str, claims: dict[str, Any], ttl: timedelta) -> str:
    header = {"alg": "HS256", "typ": "NPCreateToken"}
    body = {"sub": subject, "iat": int(utcnow().timestamp()), "exp": int((utcnow() + ttl).timestamp()), **claims}
    header_b64 = _b64(json.dumps(header, separators=(",", ":")).encode())
    body_b64 = _b64(json.dumps(body, separators=(",", ":")).encode())
    sig = hmac.new(secret.encode("utf-8"), f"{header_b64}.{body_b64}".encode("utf-8"), hashlib.sha256).digest()
    return f"{header_b64}.{body_b64}.{_b64(sig)}"


def verify_token(secret: str, token: str) -> dict[str, Any]:
    try:
        header_b64, body_b64, sig_b64 = token.split(".", 2)
    except ValueError as exc:
        raise ValueError("invalid token format") from exc
    expected = hmac.new(secret.encode("utf-8"), f"{header_b64}.{body_b64}".encode("utf-8"), hashlib.sha256).digest()
    if not hmac.compare_digest(_unb64(sig_b64), expected):
        raise ValueError("invalid token signature")
    body = json.loads(_unb64(body_b64))
    if int(body.get("exp", 0)) < int(utcnow().timestamp()):
        raise ValueError("token expired")
    return body


def payload_hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def verify_webhook_signature(
    secret: str,
    payload: bytes,
    signature_header: str | None,
    *,
    timestamp_header: str | None = None,
    max_age_seconds: int = 300,
    require_timestamp: bool = False,
) -> bool:
    """Verify generic HMAC-SHA256 webhook signature.

    Supported modes:
    - Legacy/dev: HMAC(secret, payload) with header `sha256=<hex>`.
    - Preferred production: HMAC(secret, f"{timestamp}.{payload}") with
      a timestamp header and max replay window.

    Real payment providers should still use provider-specific verification when
    available. This generic verifier is for controlled/internal providers.
    """
    if not secret or not signature_header:
        return False
    provided = signature_header.strip()
    if provided.startswith("sha256="):
        provided = provided.split("=", 1)[1]
    if len(provided) != 64:
        return False

    signed_payload = payload
    if timestamp_header:
        try:
            ts = int(timestamp_header)
        except ValueError:
            return False
        if abs(int(time.time()) - ts) > max_age_seconds:
            return False
        signed_payload = f"{ts}.".encode("utf-8") + payload
    elif require_timestamp:
        return False

    expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    if hmac.compare_digest(provided, expected):
        return True

    if timestamp_header and not require_timestamp:
        legacy_expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(provided, legacy_expected)
    return False


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
