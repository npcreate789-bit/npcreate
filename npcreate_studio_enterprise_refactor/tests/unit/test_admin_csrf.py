from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from npcreate_backend.admin_security import (
    csrf_token as new_csrf,
)
from npcreate_backend.admin_security import (
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


@pytest.fixture
def admin_with_session(backend_env):
    conn = connect(backend_env)
    migrate(conn)
    now = utcnow()
    admin_id = "ad_test"
    conn.execute(
        """
        INSERT INTO admin_users(admin_id, email, display_name, password_hash, mfa_secret,
                                mfa_enabled, status, created_at, updated_at)
        VALUES(?,?,?,?,?,0,'active',?,?)
        """,
        (admin_id, "test@example.com", "Test Admin", hash_password("StrongPasswordHere"), new_mfa_secret(), iso(now), iso(now)),
    )
    raw_session = new_session_token()
    csrf = new_csrf()
    conn.execute(
        """
        INSERT INTO admin_sessions(session_id, admin_id, session_hash, csrf_token, ip_address,
                                   user_agent, created_at, expires_at)
        VALUES(?,?,?,?,?,?,?,?)
        """,
        (
            "as_test",
            admin_id,
            hash_session_token(raw_session),
            csrf,
            "127.0.0.1",
            "pytest",
            iso(now),
            iso(now + timedelta(hours=8)),
        ),
    )
    conn.commit()
    conn.close()
    return {"admin_id": admin_id, "session_token": raw_session, "csrf_token": csrf}


@pytest.fixture
def client(backend_env):
    return TestClient(create_app())


def _auth_cookies(session_token: str) -> dict[str, str]:
    return {"npc_admin_session": session_token}


def test_get_admin_route_does_not_require_csrf(client, admin_with_session):
    response = client.get(
        "/api/v1/admin/licenses",
        cookies=_auth_cookies(admin_with_session["session_token"]),
    )
    assert response.status_code == 200


def test_post_admin_route_rejects_request_without_csrf(client, admin_with_session):
    response = client.post(
        "/api/v1/admin/licenses",
        json={"customer_name": "X", "months": 1, "max_pc_devices": 1, "max_phone_devices": 1, "features": []},
        cookies=_auth_cookies(admin_with_session["session_token"]),
    )
    assert response.status_code == 403
    assert "csrf" in response.text.lower()


def test_post_admin_route_rejects_request_with_wrong_csrf(client, admin_with_session):
    response = client.post(
        "/api/v1/admin/licenses",
        json={"customer_name": "X", "months": 1, "max_pc_devices": 1, "max_phone_devices": 1, "features": []},
        headers={"X-CSRF-Token": "wrong-token-value"},
        cookies=_auth_cookies(admin_with_session["session_token"]),
    )
    assert response.status_code == 403


def test_post_admin_route_accepts_valid_csrf(client, admin_with_session):
    response = client.post(
        "/api/v1/admin/licenses",
        json={"customer_name": "X", "months": 1, "max_pc_devices": 1, "max_phone_devices": 1, "features": []},
        headers={"X-CSRF-Token": admin_with_session["csrf_token"]},
        cookies=_auth_cookies(admin_with_session["session_token"]),
    )
    assert response.status_code == 200
    assert response.json()["license_id"]


def test_post_admin_route_without_session_returns_401(client):
    response = client.post(
        "/api/v1/admin/licenses",
        json={"customer_name": "X", "months": 1, "max_pc_devices": 1, "max_phone_devices": 1, "features": []},
    )
    assert response.status_code == 401


def test_logout_form_rejects_missing_csrf(client, admin_with_session):
    response = client.post(
        "/admin/logout",
        cookies=_auth_cookies(admin_with_session["session_token"]),
        follow_redirects=False,
    )
    assert response.status_code == 403


def test_logout_form_accepts_csrf_in_form_field(client, admin_with_session):
    response = client.post(
        "/admin/logout",
        data={"_csrf": admin_with_session["csrf_token"]},
        cookies=_auth_cookies(admin_with_session["session_token"]),
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"


def test_dashboard_html_embeds_csrf_token(client, admin_with_session):
    response = client.get(
        "/admin",
        cookies=_auth_cookies(admin_with_session["session_token"]),
    )
    assert response.status_code == 200
    assert admin_with_session["csrf_token"] in response.text
    assert 'name="_csrf"' in response.text


def test_audit_log_records_real_admin_id(client, admin_with_session, backend_env):
    response = client.post(
        "/api/v1/admin/licenses",
        json={"customer_name": "AuditTest", "months": 1, "max_pc_devices": 1, "max_phone_devices": 1, "features": []},
        headers={"X-CSRF-Token": admin_with_session["csrf_token"]},
        cookies=_auth_cookies(admin_with_session["session_token"]),
    )
    assert response.status_code == 200

    conn = connect(backend_env)
    cur = conn.execute(
        "SELECT actor_id, action FROM audit_logs WHERE action=? ORDER BY created_at DESC LIMIT 1",
        ("device_policy.upsert",),
    ).fetchone()
    conn.close()
    assert cur is not None, "expected audit row for device_policy.upsert"
    assert cur["actor_id"] == admin_with_session["admin_id"]
    assert cur["actor_id"] != "admin"


def test_legacy_admin_token_bypasses_csrf_when_enabled(backend_env, monkeypatch):
    monkeypatch.setenv("NPCREATE_BACKEND_ALLOW_LEGACY_ADMIN_TOKEN", "true")
    monkeypatch.setenv("NPCREATE_BACKEND_ADMIN_TOKEN", "legacy-admin-token-legacy-admin-token")
    client = TestClient(create_app())
    response = client.post(
        "/api/v1/admin/licenses",
        json={"customer_name": "X", "months": 1, "max_pc_devices": 1, "max_phone_devices": 1, "features": []},
        headers={"X-Admin-Token": "legacy-admin-token-legacy-admin-token"},
    )
    assert response.status_code == 200
