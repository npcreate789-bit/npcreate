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
from npcreate_backend.pagination import clamp_limit, clamp_offset, like_escape, paginated
from npcreate_backend.security import hash_license_key, iso, utcnow


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


def _make_admin(db_path):
    conn = connect(db_path)
    migrate(conn)
    now = utcnow()
    conn.execute(
        """
        INSERT INTO admin_users(admin_id, email, display_name, password_hash, mfa_secret,
                                mfa_enabled, role, status, created_at, updated_at)
        VALUES(?,?,?,?,?,0,'admin','active',?,?)
        """,
        ("ad_pag", "pag@example.com", "Pag", hash_password("x"), new_mfa_secret(), iso(now), iso(now)),
    )
    raw = new_session_token()
    csrf = new_csrf()
    conn.execute(
        """
        INSERT INTO admin_sessions(session_id, admin_id, session_hash, csrf_token, ip_address,
                                   user_agent, created_at, expires_at)
        VALUES(?,?,?,?,?,?,?,?)
        """,
        ("as_pag", "ad_pag", hash_session_token(raw), csrf, "127.0.0.1", "pytest", iso(now), iso(now + timedelta(hours=8))),
    )
    conn.commit()
    conn.close()
    return {"session_token": raw, "csrf_token": csrf}


def _seed_licenses(db_path, customers):
    settings_pepper = "pepper-pepper-pepper-pepper"
    conn = connect(db_path)
    migrate(conn)
    now = utcnow()
    for i, name in enumerate(customers):
        conn.execute(
            """
            INSERT INTO licenses(license_id,key_hash,customer_name,customer_contact,status,plan,starts_at,expires_at,
                                 max_pc_devices,max_phone_devices,features_json,notes,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                f"lic_seed_{i}",
                hash_license_key(f"SEED-{i}", settings_pepper),
                name,
                f"{name.lower()}@x.com",
                "active" if i % 2 == 0 else "suspended",
                "monthly",
                iso(now),
                iso(now + timedelta(days=30)),
                1, 1, "[]", "",
                iso(now - timedelta(seconds=i)),
                iso(now),
            ),
        )
    conn.commit()
    conn.close()


@pytest.fixture
def client(backend_env):
    return TestClient(create_app())


def test_pagination_helpers_clamp_values():
    assert clamp_limit(None) == 50
    assert clamp_limit(0) == 1
    assert clamp_limit(5000) == 200
    assert clamp_limit(75) == 75
    assert clamp_offset(None) == 0
    assert clamp_offset(-10) == 0
    assert clamp_offset(20) == 20


def test_paginated_helper_shape():
    out = paginated([{"id": 1}], total=10, limit=5, offset=0)
    assert out == {"items": [{"id": 1}], "total": 10, "limit": 5, "offset": 0, "has_more": True}
    out2 = paginated([{"id": 1}], total=1, limit=5, offset=0)
    assert out2["has_more"] is False


def test_like_escape_prevents_wildcard_injection():
    assert like_escape("foo") == "foo"
    assert like_escape("100%") == "100\\%"
    assert like_escape("a_b") == "a\\_b"
    assert like_escape("\\back") == "\\\\back"


def test_list_licenses_paginates_with_total_and_has_more(client, backend_env):
    actor = _make_admin(backend_env)
    _seed_licenses(backend_env, [f"Customer {i:02d}" for i in range(7)])
    response = client.get(
        "/api/v1/admin/licenses?limit=3&offset=0",
        cookies={"npc_admin_session": actor["session_token"]},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 3
    assert data["total"] == 7
    assert data["limit"] == 3
    assert data["offset"] == 0
    assert data["has_more"] is True


def test_list_licenses_offset_returns_next_slice(client, backend_env):
    actor = _make_admin(backend_env)
    _seed_licenses(backend_env, [f"Customer {i:02d}" for i in range(7)])
    page1 = client.get("/api/v1/admin/licenses?limit=3&offset=0", cookies={"npc_admin_session": actor["session_token"]}).json()
    page2 = client.get("/api/v1/admin/licenses?limit=3&offset=3", cookies={"npc_admin_session": actor["session_token"]}).json()
    page3 = client.get("/api/v1/admin/licenses?limit=3&offset=6", cookies={"npc_admin_session": actor["session_token"]}).json()
    ids1 = {x["license_id"] for x in page1["items"]}
    ids2 = {x["license_id"] for x in page2["items"]}
    assert not ids1 & ids2
    assert len(page3["items"]) == 1
    assert page3["has_more"] is False


def test_list_licenses_status_filter(client, backend_env):
    actor = _make_admin(backend_env)
    _seed_licenses(backend_env, [f"Customer {i:02d}" for i in range(8)])
    response = client.get(
        "/api/v1/admin/licenses?status_filter=suspended&limit=100",
        cookies={"npc_admin_session": actor["session_token"]},
    )
    data = response.json()
    assert all(x["status"] == "suspended" for x in data["items"])
    assert data["total"] == 4


def test_list_licenses_keyword_search(client, backend_env):
    actor = _make_admin(backend_env)
    _seed_licenses(backend_env, ["Alpha Co", "Beta Co", "Alpha Bravo"])
    response = client.get(
        "/api/v1/admin/licenses?q=Alpha&limit=100",
        cookies={"npc_admin_session": actor["session_token"]},
    )
    data = response.json()
    assert {x["customer_name"] for x in data["items"]} == {"Alpha Co", "Alpha Bravo"}
    assert data["total"] == 2


def test_list_licenses_keyword_does_not_use_wildcard_injection(client, backend_env):
    actor = _make_admin(backend_env)
    _seed_licenses(backend_env, ["Alpha", "100% match", "Beta"])
    response = client.get(
        "/api/v1/admin/licenses?q=%25&limit=100",
        cookies={"npc_admin_session": actor["session_token"]},
    )
    data = response.json()
    assert {x["customer_name"] for x in data["items"]} == {"100% match"}


def test_list_licenses_limit_capped_to_maximum(client, backend_env):
    actor = _make_admin(backend_env)
    _seed_licenses(backend_env, [f"Customer {i}" for i in range(5)])
    response = client.get(
        "/api/v1/admin/licenses?limit=5000",
        cookies={"npc_admin_session": actor["session_token"]},
    )
    assert response.json()["limit"] == 200


def test_dashboard_licenses_html_renders_pagination_controls(client, backend_env):
    actor = _make_admin(backend_env)
    _seed_licenses(backend_env, [f"Customer {i:02d}" for i in range(7)])
    response = client.get(
        "/admin/licenses?limit=3&offset=0",
        cookies={"npc_admin_session": actor["session_token"]},
    )
    assert response.status_code == 200
    body = response.text
    assert "ทั้งหมด 7 รายการ" in body
    assert "หน้า 1 / 3" in body
    assert 'href="?q=&status_filter=&limit=3&offset=3"' in body
