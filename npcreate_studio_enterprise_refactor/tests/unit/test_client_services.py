"""Tests for client-side services: LicenseClient + UpdateClient.

Uses httpx.MockTransport to intercept network calls so tests run without a real
backend. Covers the HTTP contract (paths, headers, params) and key error paths.
"""
from __future__ import annotations

import hashlib

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from npcreate_studio.core.errors import SecurityError
from npcreate_studio.domain.licenses import DeviceIdentity, DeviceType
from npcreate_studio.services.license_client import LicenseClient
from npcreate_studio.services.update_client import UpdateClient, UpdateManifestResponse


def _identity() -> DeviceIdentity:
    return DeviceIdentity(
        device_type=DeviceType.PC,
        fingerprint_hash="f" * 64,
        label="TestPC",
        raw_metadata={"host": "test"},
    )


def _activation_response(**overrides):
    body = {
        "license_id": "lic_test",
        "status": "active",
        "expires_at": "2026-12-31T00:00:00Z",
        "device_id": "dev_test",
        "activation_token": "access-token",
        "refresh_token": "refresh-token",
        "features": ["studio", "phone_bind"],
        "message": "activated",
    }
    body.update(overrides)
    return body


# --- LicenseClient ----------------------------------------------------------


def _patched_client(transport: httpx.MockTransport) -> LicenseClient:
    """Build a LicenseClient that uses MockTransport. Achieved by monkey-patching
    httpx.Client at the call site — simpler than refactoring LicenseClient."""
    return LicenseClient(base_url="http://test", app_version="2.4.0")


def test_license_client_activate_sends_correct_payload(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_activation_response())

    transport = httpx.MockTransport(handler)

    real_client = httpx.Client
    def patched_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)
    monkeypatch.setattr(httpx, "Client", patched_client)

    client = LicenseClient(base_url="http://test", app_version="2.4.0")
    result = client.activate("NP-AAAA-BBBB", _identity())

    assert captured["method"] == "POST"
    assert captured["url"].endswith("/api/v1/licenses/activate")
    assert captured["body"]["license_key"] == "NP-AAAA-BBBB"
    assert captured["body"]["device_type"] == "pc"
    assert captured["body"]["device_fingerprint"] == "f" * 64
    assert captured["body"]["app_version"] == "2.4.0"
    assert result.license_id == "lic_test"
    assert result.activation_token == "access-token"
    assert result.refresh_token == "refresh-token"


def test_license_client_heartbeat_sends_bearer_token(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"ok": True, "server_time": "2026-01-01T00:00:00Z"})

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client
    def patched_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)
    monkeypatch.setattr(httpx, "Client", patched_client)

    client = LicenseClient(base_url="http://test", app_version="2.4.0")
    out = client.heartbeat("access-token-abc")

    assert captured["url"].endswith("/api/v1/licenses/heartbeat")
    assert captured["auth"] == "Bearer access-token-abc"
    assert out["ok"] is True


def test_license_client_refresh_calls_auth_endpoint(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_at": "2026-12-31T00:00:00Z",
        })

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client
    def patched_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)
    monkeypatch.setattr(httpx, "Client", patched_client)

    client = LicenseClient(base_url="http://test", app_version="2.4.0")
    out = client.refresh("old-refresh")

    assert captured["url"].endswith("/api/v1/auth/refresh")
    assert captured["body"]["refresh_token"] == "old-refresh"
    assert out.access_token == "new-access"
    assert out.refresh_token == "new-refresh"


def test_license_client_fetch_news_parses_items(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "items": [
                {"news_id": "n1", "title": "Hello", "body": "world", "severity": "info", "published_at": "2026-01-01T00:00:00Z"},
                {"news_id": "n2", "title": "Maintenance", "body": "tonight", "severity": "warning", "published_at": "2026-01-02T00:00:00Z"},
            ]
        })

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client
    def patched_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)
    monkeypatch.setattr(httpx, "Client", patched_client)

    client = LicenseClient(base_url="http://test", app_version="2.4.0")
    news = client.fetch_news("access-token")
    assert len(news) == 2
    assert news[0].news_id == "n1"
    assert news[1].severity == "warning"


def test_license_client_request_admin_release_posts_reason(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True, "request_id": "rel_x"})

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client
    def patched_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)
    monkeypatch.setattr(httpx, "Client", patched_client)

    client = LicenseClient(base_url="http://test", app_version="2.4.0")
    out = client.request_admin_release("access-token", "บริษัทเปลี่ยนเครื่อง")
    assert captured["url"].endswith("/api/v1/devices/release-request")
    assert captured["body"]["reason"] == "บริษัทเปลี่ยนเครื่อง"
    assert out["request_id"] == "rel_x"


def test_license_client_propagates_4xx_as_http_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"detail": "license expired"})

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client
    def patched_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)
    monkeypatch.setattr(httpx, "Client", patched_client)

    client = LicenseClient(base_url="http://test", app_version="2.4.0")
    with pytest.raises(httpx.HTTPStatusError):
        client.activate("NP-X", _identity())


# --- UpdateClient -----------------------------------------------------------


def _make_signed_manifest():
    priv = Ed25519PrivateKey.generate()
    pub_hex = priv.public_key().public_bytes_raw().hex()
    payload = "2.5.0|stable|False|https://cdn.example.com/x.zip|" + "a" * 64
    sig = priv.sign(payload.encode()).hex()
    manifest = UpdateManifestResponse(
        version="2.5.0",
        channel="stable",
        mandatory=False,
        download_url="https://cdn.example.com/x.zip",
        sha256="a" * 64,
        signature=sig,
        release_notes="",
    )
    return manifest, pub_hex, priv


def test_update_client_check_latest_returns_none_on_204(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(204)

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client
    def patched_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)
    monkeypatch.setattr(httpx, "Client", patched_client)

    client = UpdateClient(base_url="http://test", app_version="2.4.0", channel="stable", public_key_hex="00" * 32)
    assert client.check_latest() is None


def test_update_client_check_latest_returns_manifest(monkeypatch):
    manifest, pub_hex, _ = _make_signed_manifest()

    def handler(request: httpx.Request) -> httpx.Response:
        assert "/api/v1/updates/latest" in str(request.url)
        return httpx.Response(200, json=manifest.model_dump())

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client
    def patched_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)
    monkeypatch.setattr(httpx, "Client", patched_client)

    client = UpdateClient(base_url="http://test", app_version="2.4.0", channel="stable", public_key_hex=pub_hex)
    out = client.check_latest("access-token")
    assert out is not None
    assert out.version == "2.5.0"


def test_update_client_verify_manifest_signature_accepts_valid():
    manifest, pub_hex, _ = _make_signed_manifest()
    client = UpdateClient(base_url="http://test", app_version="2.4.0", channel="stable", public_key_hex=pub_hex)
    client.verify_manifest_signature(manifest)  # must not raise


def test_update_client_verify_manifest_signature_rejects_tampered():
    manifest, pub_hex, _ = _make_signed_manifest()
    tampered = manifest.model_copy(update={"version": "9.9.9"})
    client = UpdateClient(base_url="http://test", app_version="2.4.0", channel="stable", public_key_hex=pub_hex)
    with pytest.raises(SecurityError):
        client.verify_manifest_signature(tampered)


def test_update_client_download_patch_verifies_sha256(tmp_path, monkeypatch):
    # Build a real zip-ish payload + matching sha256.
    body = b"x" * 1024
    real_sha = hashlib.sha256(body).hexdigest()
    priv = Ed25519PrivateKey.generate()
    pub_hex = priv.public_key().public_bytes_raw().hex()
    payload_str = f"2.5.0|stable|False|https://cdn.example.com/x.zip|{real_sha}"
    sig = priv.sign(payload_str.encode()).hex()
    manifest = UpdateManifestResponse(
        version="2.5.0", channel="stable", mandatory=False,
        download_url="https://cdn.example.com/x.zip", sha256=real_sha, signature=sig,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    transport = httpx.MockTransport(handler)
    def patched_stream(method, url, **kwargs):
        kwargs.pop("transport", None)
        return httpx.Client(transport=transport).stream(method, url, **kwargs)
    monkeypatch.setattr(httpx, "stream", patched_stream)

    client = UpdateClient(base_url="http://test", app_version="2.4.0", channel="stable", public_key_hex=pub_hex)
    target = tmp_path / "patch.zip"
    out_path = client.download_patch(manifest, target)
    assert out_path == target
    assert target.read_bytes() == body


def test_update_client_download_patch_rejects_sha256_mismatch(tmp_path, monkeypatch):
    body = b"actual content"
    wrong_sha = "b" * 64
    priv = Ed25519PrivateKey.generate()
    pub_hex = priv.public_key().public_bytes_raw().hex()
    payload_str = f"2.5.0|stable|False|https://cdn.example.com/x.zip|{wrong_sha}"
    sig = priv.sign(payload_str.encode()).hex()
    manifest = UpdateManifestResponse(
        version="2.5.0", channel="stable", mandatory=False,
        download_url="https://cdn.example.com/x.zip", sha256=wrong_sha, signature=sig,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    transport = httpx.MockTransport(handler)
    def patched_stream(method, url, **kwargs):
        kwargs.pop("transport", None)
        return httpx.Client(transport=transport).stream(method, url, **kwargs)
    monkeypatch.setattr(httpx, "stream", patched_stream)

    client = UpdateClient(base_url="http://test", app_version="2.4.0", channel="stable", public_key_hex=pub_hex)
    with pytest.raises(SecurityError, match="sha256"):
        client.download_patch(manifest, tmp_path / "patch.zip")
    # The download should not leave a corrupt file behind.
    assert not (tmp_path / "patch.zip").exists()


def test_update_client_download_patch_rejects_oversized(tmp_path, monkeypatch):
    body = b"x" * 4096
    real_sha = hashlib.sha256(body).hexdigest()
    priv = Ed25519PrivateKey.generate()
    pub_hex = priv.public_key().public_bytes_raw().hex()
    payload_str = f"2.5.0|stable|False|https://cdn.example.com/x.zip|{real_sha}"
    sig = priv.sign(payload_str.encode()).hex()
    manifest = UpdateManifestResponse(
        version="2.5.0", channel="stable", mandatory=False,
        download_url="https://cdn.example.com/x.zip", sha256=real_sha, signature=sig,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    transport = httpx.MockTransport(handler)
    def patched_stream(method, url, **kwargs):
        kwargs.pop("transport", None)
        return httpx.Client(transport=transport).stream(method, url, **kwargs)
    monkeypatch.setattr(httpx, "stream", patched_stream)

    client = UpdateClient(base_url="http://test", app_version="2.4.0", channel="stable", public_key_hex=pub_hex)
    with pytest.raises(SecurityError, match="exceeds max size"):
        client.download_patch(manifest, tmp_path / "patch.zip", max_bytes=1024)
