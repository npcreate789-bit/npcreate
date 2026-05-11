import hashlib
import hmac
import json
from datetime import timedelta

from npcreate_backend.billing import create_subscription, default_device_policies, get_policy_for_device, process_payment_webhook, upsert_device_policies
from npcreate_backend.db import connect, migrate, one
from npcreate_backend.security import hash_license_key, iso, utcnow, verify_webhook_signature
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


def _insert_license(conn, settings, license_id="lic_test"):
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


def test_device_policy_allows_admin_defined_device_type(tmp_path):
    settings = _settings(tmp_path)
    conn = connect(settings.db_path)
    migrate(conn)
    license_id = _insert_license(conn, settings)
    upsert_device_policies(conn, license_id, [{"device_type": "tablet", "max_devices": 3, "binding_mode": "admin_release_only", "fingerprint_required": True, "metadata": {}}], actor="test")
    conn.commit()

    policy = get_policy_for_device(conn, license_id, "tablet")
    assert policy["max_devices"] == 3


def test_payment_webhook_signature():
    payload = b'{"id":"evt_1"}'
    secret = "webhook-secret-webhook-secret"
    sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    assert verify_webhook_signature(secret, payload, "sha256=" + sig)
    assert not verify_webhook_signature(secret, payload, "sha256=bad")


def test_success_payment_webhook_auto_renews_license(tmp_path):
    settings = _settings(tmp_path)
    conn = connect(settings.db_path)
    migrate(conn)
    license_id = _insert_license(conn, settings)
    create_subscription(
        conn,
        license_id=license_id,
        provider="manual",
        provider_customer_id="cus_1",
        provider_subscription_id="sub_1",
        amount_satangs=1590000,
        currency="THB",
        next_renewal_at=None,
    )
    before = one(conn, "SELECT expires_at FROM licenses WHERE license_id=?", (license_id,))["expires_at"]
    payload = json.dumps({
        "id": "evt_paid_1",
        "type": "payment.succeeded",
        "data": {"provider_payment_id": "pay_1", "provider_subscription_id": "sub_1", "amount_satangs": 1590000, "currency": "THB"},
    }, separators=(",", ":")).encode()
    result = process_payment_webhook(conn, settings=settings, provider="manual", payload=payload, signature_valid=True)
    conn.commit()

    after = one(conn, "SELECT expires_at FROM licenses WHERE license_id=?", (license_id,))["expires_at"]
    assert result["ok"] is True
    assert after > before


def test_payment_webhook_is_idempotent(tmp_path):
    settings = _settings(tmp_path)
    conn = connect(settings.db_path)
    migrate(conn)
    license_id = _insert_license(conn, settings)
    create_subscription(conn, license_id=license_id, provider="manual", provider_customer_id="", provider_subscription_id="sub_2", amount_satangs=100, currency="THB", next_renewal_at=None)
    payload = json.dumps({"id": "evt_same", "type": "payment.succeeded", "data": {"provider_payment_id": "pay_same", "provider_subscription_id": "sub_2"}}, separators=(",", ":")).encode()

    first = process_payment_webhook(conn, settings=settings, provider="manual", payload=payload, signature_valid=True)
    second = process_payment_webhook(conn, settings=settings, provider="manual", payload=payload, signature_valid=True)

    assert first["ok"] is True
    assert second["duplicate"] is True
