from __future__ import annotations

import hashlib
import hmac
import json
import time
from types import SimpleNamespace

from npcreate_backend.admin_security import _totp_at, hash_session_token, new_mfa_secret, verify_totp
from npcreate_backend.db import connect, migrate, one
from npcreate_backend.jobs import run_billing_maintenance
from npcreate_backend.payment_providers import StripeAdapter, get_adapter
from npcreate_backend.security import iso, utcnow
from npcreate_backend.settings import BackendSettings


def test_totp_accepts_current_code() -> None:
    secret = new_mfa_secret()
    step = int(time.time() // 30)
    assert verify_totp(secret, _totp_at(secret, step))
    assert not verify_totp(secret, "000000", window=0) or _totp_at(secret, step) == "000000"


def test_session_hash_is_stable_and_not_plaintext() -> None:
    token = "secret-session-token"
    digest = hash_session_token(token)
    assert digest == hash_session_token(token)
    assert digest != token
    assert len(digest) == 64


def test_postgres_adapter_not_used_for_sqlite_migration(tmp_path) -> None:
    conn = connect(tmp_path / "backend.sqlite3")
    migrate(conn)
    row = one(conn, "SELECT version FROM schema_migrations WHERE version=?", (3,))
    assert row is not None


def test_stripe_signature_verification() -> None:
    adapter = StripeAdapter()
    payload = json.dumps({"id": "evt_1", "type": "invoice.payment_succeeded", "data": {"object": {"id": "in_1", "subscription": "sub_1", "amount_paid": 1590000, "currency": "thb"}}}).encode()
    timestamp = str(int(time.time()))
    secret = "whsec_test_secret"
    signature = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256).hexdigest()
    request = SimpleNamespace(headers={"stripe-signature": f"t={timestamp},v1={signature}"})
    settings = BackendSettings(env="development", stripe_webhook_secret=secret, payment_webhook_secret="fallback_secret_1234567890")
    import asyncio
    assert asyncio.run(adapter.verify(request, payload, settings))
    normalized = adapter.normalize(payload)
    assert normalized["type"] == "payment.succeeded"
    assert normalized["data"]["provider_subscription_id"] == "sub_1"


def test_billing_job_marks_past_due_and_suspended(tmp_path, monkeypatch) -> None:
    db = tmp_path / "backend.sqlite3"
    settings = BackendSettings(env="development", database_path=str(db), payment_grace_days=0)
    conn = connect(db)
    migrate(conn)
    now = utcnow()
    conn.execute("INSERT INTO licenses(license_id,key_hash,customer_name,status,plan,starts_at,expires_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)", ("lic_1", "hash_1", "Customer", "active", "monthly", iso(now), iso(now), iso(now), iso(now)))
    conn.execute("INSERT INTO subscriptions(subscription_id,license_id,provider,provider_subscription_id,status,billing_cycle,amount_satangs,currency,next_renewal_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", ("sub_1", "lic_1", "manual", "sub_ext", "active", "monthly", 100, "THB", iso(now.replace(year=now.year-1)), iso(now), iso(now)))
    conn.commit()
    result = run_billing_maintenance(settings)
    assert result["past_due"] == 1
    result = run_billing_maintenance(settings)
    assert result["suspended"] == 1
