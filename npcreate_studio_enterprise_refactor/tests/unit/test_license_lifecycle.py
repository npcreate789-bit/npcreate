"""Tests for client-side activation lifecycle: SecureStore token persistence,
LicenseLifecycleService orchestration including auto-refresh on 401."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import httpx
import pytest

from npcreate_studio.domain.licenses import (
    ActivationResult,
    DeviceIdentity,
    DeviceType,
    LicenseStatus,
)
from npcreate_studio.infrastructure.secure_store import SecureStore
from npcreate_studio.services.license_lifecycle import (
    ACCESS_REFRESH_LEEWAY,
    LicenseLifecycleService,
)

# -- SecureStore token persistence -----------------------------------------


def test_secure_store_save_get_roundtrip(tmp_path):
    store = SecureStore(tmp_path)
    payload = {"license_id": "lic_1", "device_id": "dev_1", "access_token": "a", "refresh_token": "r"}
    store.save_tokens(payload)
    assert store.get_tokens() == payload


def test_secure_store_get_returns_none_when_no_file(tmp_path):
    store = SecureStore(tmp_path)
    assert store.get_tokens() is None


def test_secure_store_tokens_file_is_encrypted_on_disk(tmp_path):
    store = SecureStore(tmp_path)
    store.save_tokens({"refresh_token": "supersecret-token-value"})
    raw = store.tokens_path.read_bytes()
    assert b"supersecret-token-value" not in raw
    assert b"refresh_token" not in raw


def test_secure_store_clear_tokens(tmp_path):
    store = SecureStore(tmp_path)
    store.save_tokens({"x": 1})
    assert store.tokens_path.is_file()
    store.clear_tokens()
    assert not store.tokens_path.is_file()
    store.clear_tokens()  # idempotent


def test_secure_store_save_is_atomic(tmp_path):
    """Atomic write: even if tmp exists, save_tokens does not corrupt the live file."""
    store = SecureStore(tmp_path)
    store.save_tokens({"a": 1})
    # Pre-create a tmp file as if a previous run crashed mid-write.
    store.tokens_path.with_suffix(".tmp").write_bytes(b"garbage")
    store.save_tokens({"a": 2})
    assert store.get_tokens() == {"a": 2}


def test_secure_store_get_tokens_returns_none_on_corruption(tmp_path):
    store = SecureStore(tmp_path)
    store.tokens_path.write_bytes(b"not-real-fernet-ciphertext")
    assert store.get_tokens() is None


# -- LicenseLifecycleService.activate --------------------------------------


def _identity() -> DeviceIdentity:
    return DeviceIdentity(
        device_type=DeviceType.PC,
        fingerprint_hash="f" * 64,
        label="TestPC",
        raw_metadata={"host": "test"},
    )


def _activation_result(expires_in_days: int = 30) -> ActivationResult:
    return ActivationResult(
        license_id="lic_42",
        status=LicenseStatus.ACTIVE,
        expires_at=datetime.now(UTC) + timedelta(days=expires_in_days),
        device_id="dev_42",
        activation_token="access-token-abc",
        refresh_token="refresh-token-xyz",
        features=("studio", "phone_bind"),
        message="ok",
    )


def test_activate_persists_tokens_and_returns_status(tmp_path):
    store = SecureStore(tmp_path)
    client = MagicMock()
    client.activate.return_value = _activation_result()
    service = LicenseLifecycleService(client=client, store=store)

    status = service.activate("NP-AAAA-BBBB", identity=_identity())

    assert status.license_id == "lic_42"
    assert status.device_id == "dev_42"
    persisted = store.get_tokens()
    assert persisted["access_token"] == "access-token-abc"
    assert persisted["refresh_token"] == "refresh-token-xyz"
    assert persisted["license_id"] == "lic_42"


def test_current_state_returns_none_without_activation(tmp_path):
    service = LicenseLifecycleService(client=MagicMock(), store=SecureStore(tmp_path))
    assert service.current_state() is None


def test_current_state_returns_status_after_activate(tmp_path):
    store = SecureStore(tmp_path)
    client = MagicMock()
    client.activate.return_value = _activation_result()
    service = LicenseLifecycleService(client=client, store=store)
    service.activate("NP-AAAA-BBBB", identity=_identity())

    status = service.current_state()
    assert status is not None
    assert status.license_id == "lic_42"


def test_clear_removes_persisted_tokens(tmp_path):
    store = SecureStore(tmp_path)
    client = MagicMock()
    client.activate.return_value = _activation_result()
    service = LicenseLifecycleService(client=client, store=store)
    service.activate("k", identity=_identity())
    service.clear()
    assert service.current_state() is None


# -- LicenseLifecycleService.heartbeat (auto-refresh) ----------------------


def test_heartbeat_uses_stored_access_token(tmp_path):
    store = SecureStore(tmp_path)
    client = MagicMock()
    client.activate.return_value = _activation_result()
    client.heartbeat.return_value = {"ok": True, "server_time": "2026-01-01T00:00:00Z"}

    service = LicenseLifecycleService(client=client, store=store)
    service.activate("k", identity=_identity())

    result = service.heartbeat()
    assert result["ok"] is True
    client.heartbeat.assert_called_once_with("access-token-abc")


def test_heartbeat_without_activation_raises(tmp_path):
    service = LicenseLifecycleService(client=MagicMock(), store=SecureStore(tmp_path))
    with pytest.raises(RuntimeError, match="no stored activation"):
        service.heartbeat()


def test_heartbeat_retries_after_401_via_refresh(tmp_path):
    store = SecureStore(tmp_path)
    # Pre-seed tokens to simulate a previously-activated client.
    store.save_tokens({
        "license_id": "lic_42",
        "device_id": "dev_42",
        "access_token": "stale-access",
        "refresh_token": "good-refresh",
        "license_expires_at": "2026-12-31T00:00:00Z",
        "features": [],
        "saved_at": "2026-01-01T00:00:00Z",
    })

    client = MagicMock()
    # First heartbeat call raises 401; second (after refresh) succeeds.
    response = httpx.Response(status_code=401, request=httpx.Request("POST", "http://x"))
    client.heartbeat.side_effect = [
        httpx.HTTPStatusError("401", request=response.request, response=response),
        {"ok": True, "server_time": "now"},
    ]
    rotated = MagicMock()
    rotated.access_token = "fresh-access"
    rotated.refresh_token = "fresh-refresh"
    rotated.expires_at = datetime.now(UTC) + timedelta(minutes=30)
    client.refresh.return_value = rotated

    service = LicenseLifecycleService(client=client, store=store)
    result = service.heartbeat()
    assert result == {"ok": True, "server_time": "now"}
    assert client.heartbeat.call_count == 2
    client.refresh.assert_called_once_with("good-refresh")
    # New tokens persisted for future requests.
    persisted = store.get_tokens()
    assert persisted["access_token"] == "fresh-access"
    assert persisted["refresh_token"] == "fresh-refresh"


def test_heartbeat_proactive_refresh_when_access_about_to_expire(tmp_path):
    store = SecureStore(tmp_path)
    soon = datetime.now(UTC) + ACCESS_REFRESH_LEEWAY / 2  # within leeway
    store.save_tokens({
        "license_id": "lic",
        "device_id": "dev",
        "access_token": "old",
        "refresh_token": "good",
        "access_expires_at": soon.isoformat().replace("+00:00", "Z"),
        "license_expires_at": "2026-12-31T00:00:00Z",
        "features": [],
        "saved_at": "2026-01-01T00:00:00Z",
    })

    client = MagicMock()
    rotated = MagicMock()
    rotated.access_token = "new"
    rotated.refresh_token = "new-refresh"
    rotated.expires_at = datetime.now(UTC) + timedelta(minutes=30)
    client.refresh.return_value = rotated
    client.heartbeat.return_value = {"ok": True}

    service = LicenseLifecycleService(client=client, store=store)
    service.heartbeat()
    # Heartbeat sent the proactively rotated access token, not the stale one.
    client.heartbeat.assert_called_once_with("new")
    assert store.get_tokens()["access_token"] == "new"
