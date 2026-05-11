from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from npcreate_backend.app import create_app
from npcreate_backend.billing import default_device_policies, upsert_device_policies
from npcreate_backend.db import connect, migrate, one
from npcreate_backend.refresh_tokens import hash_refresh_token, issue_refresh_token
from npcreate_backend.security import hash_license_key, iso, utcnow


VALID_FINGERPRINT = "fp-test-device-fingerprint-1234567890ab"


@pytest.fixture
def backend_env(tmp_path, monkeypatch):
    db_path = tmp_path / "backend.sqlite3"
    monkeypatch.setenv("NPCREATE_BACKEND_ENV", "development")
    monkeypatch.setenv("NPCREATE_BACKEND_DATABASE_PATH", str(db_path))
    monkeypatch.setenv("NPCREATE_BACKEND_DATABASE_URL", "")
    monkeypatch.setenv("NPCREATE_BACKEND_ADMIN_TOKEN", "admin-token-admin-token-admin-token")
    monkeypatch.setenv("NPCREATE_BACKEND_APP_API_KEY", "app-key-app-key-app-key-app-key")
    monkeypatch.setenv("NPCREATE_BACKEND_KEY_PEPPER", "pepper-pepper-pepper-pepper")
    monkeypatch.setenv("NPCREATE_BACKEND_PAYMENT_WEBHOOK_SECRET", "webhook-secret-webhook-secret")
    monkeypatch.setenv("NPCREATE_BACKEND_BILLING_JOB_ENABLED", "false")
    monkeypatch.setenv("NPCREATE_BACKEND_ALLOW_LEGACY_ADMIN_TOKEN", "false")
    monkeypatch.setenv("NPCREATE_BACKEND_ACTIVATION_ACCESS_TTL_MINUTES", "30")
    monkeypatch.setenv("NPCREATE_BACKEND_ACTIVATION_TOKEN_TTL_DAYS", "35")
    return db_path


def _seed_license(db_path, pepper, license_key="NP-AAAA-BBBB-CCCC-DDDD-EEEE"):
    conn = connect(db_path)
    migrate(conn)
    now = utcnow()
    license_id = "lic_refresh_test"
    conn.execute(
        """
        INSERT INTO licenses(license_id,key_hash,customer_name,customer_contact,status,plan,starts_at,expires_at,
                             max_pc_devices,max_phone_devices,features_json,notes,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            license_id,
            hash_license_key(license_key, pepper),
            "Customer", "", "active", "monthly",
            iso(now), iso(now + timedelta(days=30)),
            1, 1, "[]", "", iso(now), iso(now),
        ),
    )
    upsert_device_policies(conn, license_id, default_device_policies(1, 1), actor="test")
    conn.commit()
    conn.close()
    return license_id, license_key


@pytest.fixture
def client(backend_env):
    return TestClient(create_app())


def _activate(client, license_key) -> dict:
    response = client.post(
        "/api/v1/licenses/activate",
        json={
            "license_key": license_key,
            "device_type": "pc",
            "device_fingerprint": VALID_FINGERPRINT,
            "device_label": "Test PC",
            "device_metadata": {},
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_activate_returns_access_and_refresh_tokens(client, backend_env):
    _, key = _seed_license(backend_env, "pepper-pepper-pepper-pepper")
    body = _activate(client, key)
    assert body["activation_token"]
    assert body["refresh_token"]
    assert body["activation_token"] != body["refresh_token"]


def test_refresh_rotates_token_and_old_is_revoked(client, backend_env):
    _, key = _seed_license(backend_env, "pepper-pepper-pepper-pepper")
    body = _activate(client, key)
    first_refresh = body["refresh_token"]

    response = client.post("/api/v1/auth/refresh", json={"refresh_token": first_refresh})
    assert response.status_code == 200
    rotated = response.json()
    assert rotated["refresh_token"] != first_refresh
    assert rotated["access_token"]

    # Old token must not be accepted again.
    reuse = client.post("/api/v1/auth/refresh", json={"refresh_token": first_refresh})
    assert reuse.status_code == 401
    assert "reuse" in reuse.text.lower()


def test_refresh_reuse_revokes_entire_chain(client, backend_env):
    _, key = _seed_license(backend_env, "pepper-pepper-pepper-pepper")
    body = _activate(client, key)
    first_refresh = body["refresh_token"]

    second = client.post("/api/v1/auth/refresh", json={"refresh_token": first_refresh}).json()
    # Reuse the original (already rotated) token → triggers chain revoke.
    reuse = client.post("/api/v1/auth/refresh", json={"refresh_token": first_refresh})
    assert reuse.status_code == 401

    # Now the rotated token should also be revoked.
    follow_up = client.post("/api/v1/auth/refresh", json={"refresh_token": second["refresh_token"]})
    assert follow_up.status_code == 401
    assert "revoked" in follow_up.text.lower()


def test_refresh_rejects_invalid_token(client, backend_env):
    _seed_license(backend_env, "pepper-pepper-pepper-pepper")
    response = client.post("/api/v1/auth/refresh", json={"refresh_token": "not-a-real-token-not-a-real-token"})
    assert response.status_code == 401


def test_refresh_rejects_expired_token(client, backend_env):
    _, key = _seed_license(backend_env, "pepper-pepper-pepper-pepper")
    body = _activate(client, key)
    raw = body["refresh_token"]
    conn = connect(backend_env)
    past = iso(utcnow() - timedelta(days=1))
    conn.execute("UPDATE refresh_tokens SET expires_at=? WHERE token_hash=?", (past, hash_refresh_token(raw)))
    conn.commit()
    conn.close()
    response = client.post("/api/v1/auth/refresh", json={"refresh_token": raw})
    assert response.status_code == 401
    assert "expired" in response.text.lower()


def test_refresh_rejects_when_device_released(client, backend_env):
    _, key = _seed_license(backend_env, "pepper-pepper-pepper-pepper")
    body = _activate(client, key)
    raw = body["refresh_token"]
    conn = connect(backend_env)
    conn.execute("UPDATE devices SET status='released' WHERE device_id=?", (body["device_id"],))
    conn.commit()
    conn.close()
    response = client.post("/api/v1/auth/refresh", json={"refresh_token": raw})
    assert response.status_code == 403


def test_admin_release_revokes_refresh_tokens(client, backend_env):
    pepper = "pepper-pepper-pepper-pepper"
    _, key = _seed_license(backend_env, pepper)
    body = _activate(client, key)

    # Seed admin owner so we can call release endpoint.
    from datetime import timedelta as _td
    from npcreate_backend.admin_security import (
        csrf_token as new_csrf,
        hash_password,
        hash_session_token,
        new_mfa_secret,
        new_session_token,
    )
    conn = connect(backend_env)
    now = utcnow()
    conn.execute(
        """
        INSERT INTO admin_users(admin_id, email, display_name, password_hash, mfa_secret,
                                mfa_enabled, role, status, created_at, updated_at)
        VALUES(?,?,?,?,?,0,'owner','active',?,?)
        """,
        ("ad_owner_r", "o@x.com", "O", hash_password("x"), new_mfa_secret(), iso(now), iso(now)),
    )
    raw_session = new_session_token()
    csrf = new_csrf()
    conn.execute(
        """
        INSERT INTO admin_sessions(session_id, admin_id, session_hash, csrf_token, ip_address,
                                   user_agent, created_at, expires_at)
        VALUES(?,?,?,?,?,?,?,?)
        """,
        ("as_owner_r", "ad_owner_r", hash_session_token(raw_session), csrf, "127.0.0.1", "pytest", iso(now), iso(now + _td(hours=8))),
    )
    conn.commit()
    conn.close()

    # Admin release device.
    response = client.post(
        f"/api/v1/admin/devices/{body['device_id']}/release",
        headers={"X-CSRF-Token": csrf},
        cookies={"npc_admin_session": raw_session},
    )
    assert response.status_code == 200

    # Refresh should now fail.
    refresh_resp = client.post("/api/v1/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert refresh_resp.status_code in {401, 403}


def test_issue_refresh_token_persists_hash_not_plaintext(backend_env):
    conn = connect(backend_env)
    migrate(conn)
    now = utcnow()
    # Seed minimal license + device.
    conn.execute(
        """
        INSERT INTO licenses(license_id,key_hash,customer_name,status,plan,starts_at,expires_at,
                             max_pc_devices,max_phone_devices,features_json,notes,created_at,updated_at)
        VALUES('lic_h','h','C','active','monthly',?,?,1,1,'[]','',?,?)
        """,
        (iso(now), iso(now + timedelta(days=10)), iso(now), iso(now)),
    )
    conn.execute(
        "INSERT INTO devices(device_id, license_id, device_type, fingerprint_hash, label, metadata_json, status, bound_at) VALUES(?,?,?,?,?,?,?,?)",
        ("dev_h", "lic_h", "pc", "fp_h", "label", "{}", "bound", iso(now)),
    )
    _, raw = issue_refresh_token(conn, license_id="lic_h", device_id="dev_h", ttl_days=10)
    conn.commit()
    row = one(conn, "SELECT token_hash FROM refresh_tokens WHERE device_id='dev_h'")
    conn.close()
    assert row["token_hash"] == hash_refresh_token(raw)
    assert row["token_hash"] != raw
