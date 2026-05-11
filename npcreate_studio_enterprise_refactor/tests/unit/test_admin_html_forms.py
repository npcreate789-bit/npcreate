"""Tests for HTML form-based admin CRUD (create license, renew, publish news/update,
approve/reject release request). Form CSRF is enforced via _csrf field; verify here."""
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


def _seed_owner(db_path, role: str = "owner") -> dict[str, str]:
    conn = connect(db_path)
    migrate(conn)
    now = utcnow()
    conn.execute(
        """
        INSERT INTO admin_users(admin_id, email, display_name, password_hash, mfa_secret,
                                mfa_enabled, role, status, created_at, updated_at)
        VALUES(?,?,?,?,?,0,?,'active',?,?)
        """,
        (f"ad_{role}", f"{role}@x.com", role, hash_password("x"), new_mfa_secret(), role, iso(now), iso(now)),
    )
    raw = new_session_token()
    csrf = new_csrf()
    conn.execute(
        """
        INSERT INTO admin_sessions(session_id, admin_id, session_hash, csrf_token, ip_address,
                                   user_agent, created_at, expires_at, last_activity_at)
        VALUES(?,?,?,?,?,?,?,?,?)
        """,
        (f"as_{role}", f"ad_{role}", hash_session_token(raw), csrf, "127.0.0.1", "pytest",
         iso(now), iso(now + timedelta(hours=8)), iso(now)),
    )
    conn.commit()
    conn.close()
    return {"session_token": raw, "csrf_token": csrf, "admin_id": f"ad_{role}"}


@pytest.fixture
def client(backend_env):
    return TestClient(create_app())


def test_create_license_form_redirects_and_inserts(client, backend_env):
    owner = _seed_owner(backend_env)
    r = client.post(
        "/admin/licenses/create",
        data={"_csrf": owner["csrf_token"], "customer_name": "FormTest", "customer_contact": "x@y.com",
              "months": 2, "max_pc_devices": 1, "max_phone_devices": 1},
        cookies={"npc_admin_session": owner["session_token"]},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"].startswith("/admin/licenses?created=")

    # Verify license row was persisted.
    conn = connect(backend_env)
    row = conn.execute("SELECT customer_name, status FROM licenses WHERE customer_name=?", ("FormTest",)).fetchone()
    conn.close()
    assert row is not None
    assert row["status"] == "active"


def test_create_license_form_rejects_missing_csrf(client, backend_env):
    owner = _seed_owner(backend_env)
    r = client.post(
        "/admin/licenses/create",
        data={"customer_name": "X", "months": 1, "max_pc_devices": 1, "max_phone_devices": 1},
        cookies={"npc_admin_session": owner["session_token"]},
        follow_redirects=False,
    )
    assert r.status_code == 403


def test_renew_license_form_extends_expiry(client, backend_env):
    owner = _seed_owner(backend_env)
    # First create a license.
    client.post(
        "/admin/licenses/create",
        data={"_csrf": owner["csrf_token"], "customer_name": "RenewTest", "months": 1,
              "max_pc_devices": 1, "max_phone_devices": 1},
        cookies={"npc_admin_session": owner["session_token"]},
        follow_redirects=False,
    )
    conn = connect(backend_env)
    row = conn.execute("SELECT license_id, expires_at FROM licenses WHERE customer_name='RenewTest'").fetchone()
    license_id = row["license_id"]
    original_expiry = row["expires_at"]
    conn.close()

    r = client.post(
        f"/admin/licenses/{license_id}/renew",
        data={"_csrf": owner["csrf_token"], "months": 3},
        cookies={"npc_admin_session": owner["session_token"]},
        follow_redirects=False,
    )
    assert r.status_code == 303

    conn = connect(backend_env)
    row = conn.execute("SELECT expires_at FROM licenses WHERE license_id=?", (license_id,)).fetchone()
    conn.close()
    assert row["expires_at"] > original_expiry


def test_publish_news_form_creates_news_row(client, backend_env):
    owner = _seed_owner(backend_env)
    r = client.post(
        "/admin/news/publish",
        data={"_csrf": owner["csrf_token"], "title": "Maintenance window",
              "body": "Backend จะ restart พรุ่งนี้ 9:00", "severity": "warning", "audience": "all"},
        cookies={"npc_admin_session": owner["session_token"]},
        follow_redirects=False,
    )
    assert r.status_code == 303

    conn = connect(backend_env)
    row = conn.execute("SELECT severity, title FROM news WHERE title='Maintenance window'").fetchone()
    conn.close()
    assert row is not None
    assert row["severity"] == "warning"


def test_publish_update_form_requires_signing_key(client, backend_env, monkeypatch):
    owner = _seed_owner(backend_env)
    # No ed25519 key configured → expect 400.
    r = client.post(
        "/admin/updates/publish",
        data={
            "_csrf": owner["csrf_token"], "version": "2.5.0",
            "download_url": "https://cdn.example.com/x.zip",
            "sha256": "a" * 64, "channel": "stable",
        },
        cookies={"npc_admin_session": owner["session_token"]},
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert "ed25519" in r.text.lower()


def test_publish_update_form_signs_and_inserts_when_key_present(backend_env, monkeypatch):
    import secrets as _secrets

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    priv_hex = Ed25519PrivateKey.generate().private_bytes_raw().hex() if hasattr(Ed25519PrivateKey.generate(), "private_bytes_raw") else _secrets.token_bytes(32).hex()
    monkeypatch.setenv("NPCREATE_BACKEND_ED25519_PRIVATE_KEY_HEX", priv_hex)
    new_client = TestClient(create_app())
    owner = _seed_owner(backend_env)
    r = new_client.post(
        "/admin/updates/publish",
        data={
            "_csrf": owner["csrf_token"], "version": "2.5.0",
            "download_url": "https://cdn.example.com/x.zip",
            "sha256": "a" * 64, "channel": "stable",
        },
        cookies={"npc_admin_session": owner["session_token"]},
        follow_redirects=False,
    )
    assert r.status_code == 303
    conn = connect(backend_env)
    row = conn.execute("SELECT version, channel, signature FROM update_manifests WHERE version='2.5.0'").fetchone()
    conn.close()
    assert row is not None
    assert len(row["signature"]) == 128  # ed25519 sig hex


def test_release_request_approve_form_rejects_without_csrf(client, backend_env):
    owner = _seed_owner(backend_env)
    # Seed a release_request to approve.
    conn = connect(backend_env)
    migrate(conn)
    now = utcnow()
    conn.execute(
        """INSERT INTO licenses(license_id,key_hash,customer_name,status,plan,starts_at,expires_at,
           max_pc_devices,max_phone_devices,features_json,notes,created_at,updated_at)
           VALUES('lic_f','hash_f','C','active','monthly',?,?,1,1,'[]','',?,?)""",
        (iso(now), iso(now + timedelta(days=30)), iso(now), iso(now)),
    )
    conn.execute(
        "INSERT INTO devices(device_id, license_id, device_type, fingerprint_hash, label, metadata_json, status, bound_at) VALUES(?,?,?,?,?,?,?,?)",
        ("dev_f", "lic_f", "pc", "fp_f", "label", "{}", "bound", iso(now)),
    )
    conn.execute(
        "INSERT INTO release_requests(request_id, license_id, device_id, reason, status, requested_at) VALUES(?,?,?,?,?,?)",
        ("rel_f", "lic_f", "dev_f", "moved devices", "pending", iso(now)),
    )
    conn.commit()
    conn.close()

    r = client.post(
        "/admin/release-requests/rel_f/approve",
        data={},  # no _csrf
        cookies={"npc_admin_session": owner["session_token"]},
        follow_redirects=False,
    )
    assert r.status_code == 403


def test_admin_user_without_role_permission_cannot_publish_news(client, backend_env):
    support = _seed_owner(backend_env, role="support")
    r = client.post(
        "/admin/news/publish",
        data={"_csrf": support["csrf_token"], "title": "x", "body": "y", "severity": "info", "audience": "all"},
        cookies={"npc_admin_session": support["session_token"]},
        follow_redirects=False,
    )
    assert r.status_code == 403
    assert "support" in r.text


def test_admin_news_page_renders(client, backend_env):
    owner = _seed_owner(backend_env)
    r = client.get("/admin/news", cookies={"npc_admin_session": owner["session_token"]})
    assert r.status_code == 200
    assert 'action="/admin/news/publish"' in r.text


def test_admin_updates_page_renders(client, backend_env):
    owner = _seed_owner(backend_env)
    r = client.get("/admin/updates", cookies={"npc_admin_session": owner["session_token"]})
    assert r.status_code == 200
    assert 'action="/admin/updates/publish"' in r.text
