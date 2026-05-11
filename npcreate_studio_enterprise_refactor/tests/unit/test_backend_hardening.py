import hashlib
import hmac
import json
import time
from datetime import timedelta

import pytest
from fastapi import HTTPException

from npcreate_backend.billing import create_subscription, default_device_policies, process_payment_webhook, upsert_device_policies
from npcreate_backend.db import connect, migrate
from npcreate_backend.security import hash_device_fingerprint, hash_license_key, iso, utcnow, verify_webhook_signature
from npcreate_backend.settings import BackendSettings


def _settings(tmp_path):
    return BackendSettings(
        env="development",
        database_path=str(tmp_path / "backend.sqlite3"),
        admin_token="admin-token-admin-token-admin-token",
        app_api_key="app-key-app-key-app-key-app-key",
        key_pepper="pepper-pepper-pepper-pepper",
        payment_webhook_secret="webhook-secret-webhook-secret",
    )


def _insert_license(conn, settings, license_id="lic_test_hardened"):
    now = utcnow()
    conn.execute(
        """
        INSERT INTO licenses(license_id, key_hash, customer_name, status, plan, starts_at, expires_at,
                             max_pc_devices, max_phone_devices, features_json, created_at, updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            license_id,
            hash_license_key("NP-TEST", settings.key_pepper),
            "Customer",
            "active",
            "monthly",
            iso(now),
            iso(now + timedelta(days=1)),
            1,
            1,
            "[]",
            iso(now),
            iso(now),
        ),
    )
    upsert_device_policies(conn, license_id, default_device_policies(1, 1), actor="test")
    conn.commit()
    return license_id


def test_device_fingerprint_is_server_hmac_and_peppered():
    raw = "abc123abc123abc123abc123abc12312"
    hashed = hash_device_fingerprint(raw, "pepper-one")
    assert hashed != raw
    assert hashed == hash_device_fingerprint(raw.upper(), "pepper-one")
    assert hashed != hash_device_fingerprint(raw, "pepper-two")


def test_timestamped_webhook_signature():
    payload = b'{"id":"evt_1"}'
    secret = "webhook-secret-webhook-secret"
    ts = str(int(time.time()))
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    assert verify_webhook_signature(secret, payload, "sha256=" + sig, timestamp_header=ts, require_timestamp=True)
    assert not verify_webhook_signature(secret, payload, "sha256=" + sig, timestamp_header="1", require_timestamp=True)


def test_payment_without_known_subscription_is_rejected(tmp_path):
    settings = _settings(tmp_path)
    conn = connect(settings.db_path)
    migrate(conn)
    license_id = _insert_license(conn, settings)
    payload = json.dumps({
        "id": "evt_direct_license",
        "type": "payment.succeeded",
        "data": {"provider_payment_id": "pay_direct", "license_id": license_id, "amount_satangs": 1590000, "currency": "THB"},
    }, separators=(",", ":")).encode()
    with pytest.raises(HTTPException):
        process_payment_webhook(conn, settings=settings, provider="manual", payload=payload, signature_valid=True)


def test_payment_amount_mismatch_is_rejected(tmp_path):
    settings = _settings(tmp_path)
    conn = connect(settings.db_path)
    migrate(conn)
    license_id = _insert_license(conn, settings)
    create_subscription(conn, license_id=license_id, provider="manual", provider_customer_id="", provider_subscription_id="sub_amount", amount_satangs=1590000, currency="THB", next_renewal_at=None)
    payload = json.dumps({
        "id": "evt_bad_amount",
        "type": "payment.succeeded",
        "data": {"provider_payment_id": "pay_bad_amount", "provider_subscription_id": "sub_amount", "amount_satangs": 100, "currency": "THB"},
    }, separators=(",", ":")).encode()
    with pytest.raises(HTTPException):
        process_payment_webhook(conn, settings=settings, provider="manual", payload=payload, signature_valid=True)
