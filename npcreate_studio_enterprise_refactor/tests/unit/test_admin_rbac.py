from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from npcreate_backend.admin_security import (
    csrf_token as new_csrf,
    hash_password,
    hash_session_token,
    new_mfa_secret,
    new_session_token,
)
from npcreate_backend.app import create_app
from npcreate_backend.db import connect, migrate
from npcreate_backend.security import iso, utcnow


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
    return db_path


def _make_admin(db_path, role: str, admin_id: str | None = None) -> dict[str, str]:
    conn = connect(db_path)
    migrate(conn)
    now = utcnow()
    admin_id = admin_id or f"ad_{role}"
    conn.execute(
        """
        INSERT INTO admin_users(admin_id, email, display_name, password_hash, mfa_secret,
                                mfa_enabled, role, status, created_at, updated_at)
        VALUES(?,?,?,?,?,0,?,'active',?,?)
        """,
        (admin_id, f"{role}@example.com", role.title(), hash_password("Strong"), new_mfa_secret(), role, iso(now), iso(now)),
    )
    raw_session = new_session_token()
    csrf = new_csrf()
    conn.execute(
        """
        INSERT INTO admin_sessions(session_id, admin_id, session_hash, csrf_token, ip_address,
                                   user_agent, created_at, expires_at)
        VALUES(?,?,?,?,?,?,?,?)
        """,
        ("as_" + admin_id, admin_id, hash_session_token(raw_session), csrf, "127.0.0.1", "pytest", iso(now), iso(now + timedelta(hours=8))),
    )
    conn.commit()
    conn.close()
    return {"admin_id": admin_id, "session_token": raw_session, "csrf_token": csrf, "role": role}


@pytest.fixture
def client(backend_env):
    return TestClient(create_app())


def _post_license(client, actor):
    return client.post(
        "/api/v1/admin/licenses",
        json={"customer_name": "RBACTest", "months": 1, "max_pc_devices": 1, "max_phone_devices": 1, "features": []},
        headers={"X-CSRF-Token": actor["csrf_token"]},
        cookies={"npc_admin_session": actor["session_token"]},
    )


def test_admin_role_can_create_license(client, backend_env):
    actor = _make_admin(backend_env, "admin")
    assert _post_license(client, actor).status_code == 200


def test_owner_role_can_create_license(client, backend_env):
    actor = _make_admin(backend_env, "owner")
    assert _post_license(client, actor).status_code == 200


def test_support_role_cannot_create_license(client, backend_env):
    actor = _make_admin(backend_env, "support")
    response = _post_license(client, actor)
    assert response.status_code == 403
    assert "support" in response.text


def test_billing_role_cannot_create_license_but_can_create_subscription(client, backend_env):
    owner = _make_admin(backend_env, "owner", admin_id="ad_owner")
    license_response = _post_license(client, owner)
    license_id = license_response.json()["license_id"]

    billing = _make_admin(backend_env, "billing")
    assert _post_license(client, billing).status_code == 403

    response = client.post(
        "/api/v1/admin/subscriptions",
        json={
            "license_id": license_id,
            "provider": "manual",
            "provider_customer_id": "cust_1",
            "provider_subscription_id": "sub_1",
            "amount_satangs": 1590000,
            "currency": "THB",
            "next_renewal_at": None,
        },
        headers={"X-CSRF-Token": billing["csrf_token"]},
        cookies={"npc_admin_session": billing["session_token"]},
    )
    assert response.status_code == 200


def test_viewer_role_cannot_perform_any_mutation(client, backend_env):
    viewer = _make_admin(backend_env, "viewer")
    response = _post_license(client, viewer)
    assert response.status_code == 403


def test_viewer_role_can_read_list_endpoints(client, backend_env):
    viewer = _make_admin(backend_env, "viewer")
    response = client.get(
        "/api/v1/admin/licenses",
        cookies={"npc_admin_session": viewer["session_token"]},
    )
    assert response.status_code == 200


def test_support_role_can_release_device(client, backend_env):
    owner = _make_admin(backend_env, "owner", admin_id="ad_owner2")
    lic_resp = _post_license(client, owner)
    license_id = lic_resp.json()["license_id"]

    conn = connect(backend_env)
    now = utcnow()
    conn.execute(
        "INSERT INTO devices(device_id, license_id, device_type, fingerprint_hash, label, metadata_json, status, bound_at) VALUES(?,?,?,?,?,?,?,?)",
        ("dev_test", license_id, "pc", "hash_dev_test", "TestPC", "{}", "bound", iso(now)),
    )
    conn.commit()
    conn.close()

    support = _make_admin(backend_env, "support")
    response = client.post(
        "/api/v1/admin/devices/dev_test/release",
        headers={"X-CSRF-Token": support["csrf_token"]},
        cookies={"npc_admin_session": support["session_token"]},
    )
    assert response.status_code == 200
