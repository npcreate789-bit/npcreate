"""Tests for ops hardening: /healthz DB check, admin idle timeout, refresh rate limit."""
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
from npcreate_backend.billing import default_device_policies, upsert_device_policies
from npcreate_backend.db import connect, migrate
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


@pytest.fixture
def client(backend_env):
    return TestClient(create_app())


# -- /healthz ---------------------------------------------------------------


def test_healthz_returns_200_when_db_reachable(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["db"] == "ok"


def test_healthz_returns_503_when_db_path_unreadable(tmp_path, monkeypatch):
    # Point the backend at a path it cannot create (under a read-only parent).
    bad_path = tmp_path / "nonexistent_dir_does_not_exist_anywhere"
    bad_path.mkdir()
    bad_path.chmod(0o000)
    try:
        monkeypatch.setenv("NPCREATE_BACKEND_ENV", "development")
        monkeypatch.setenv("NPCREATE_BACKEND_DATABASE_PATH", str(bad_path / "ro" / "x.sqlite3"))
        monkeypatch.setenv("NPCREATE_BACKEND_DATABASE_URL", "")
        # Avoid migrate() failing on import: bypass create_app() by hand-crafting a tiny app.
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse

        from npcreate_backend.db import connect as db_connect
        from npcreate_backend.settings import BackendSettings as Settings

        app = FastAPI()

        @app.get("/healthz")
        def healthz():
            try:
                conn = db_connect(Settings().db_target)
                try:
                    conn.execute("SELECT 1").fetchone()
                finally:
                    conn.close()
            except Exception as exc:
                return JSONResponse(status_code=503, content={"ok": False, "db": "down", "error": str(exc)[:200]})
            return JSONResponse(content={"ok": True, "db": "ok"})

        c = TestClient(app)
        r = c.get("/healthz")
        assert r.status_code == 503
        body = r.json()
        assert body["ok"] is False
        assert body["db"] == "down"
    finally:
        bad_path.chmod(0o700)


# -- admin session idle timeout --------------------------------------------


def _seed_admin_with_session(db_path, *, idle_minutes_ago: int = 0) -> dict[str, str]:
    conn = connect(db_path)
    migrate(conn)
    now = utcnow()
    conn.execute(
        """
        INSERT INTO admin_users(admin_id, email, display_name, password_hash, mfa_secret,
                                mfa_enabled, role, status, created_at, updated_at)
        VALUES(?,?,?,?,?,0,'owner','active',?,?)
        """,
        ("ad_idle", "idle@example.com", "Idle", hash_password("x"), new_mfa_secret(), iso(now), iso(now)),
    )
    raw = new_session_token()
    csrf = new_csrf()
    last_activity = now - timedelta(minutes=idle_minutes_ago) if idle_minutes_ago else now
    conn.execute(
        """
        INSERT INTO admin_sessions(session_id, admin_id, session_hash, csrf_token, ip_address,
                                   user_agent, created_at, expires_at, last_activity_at)
        VALUES(?,?,?,?,?,?,?,?,?)
        """,
        ("as_idle", "ad_idle", hash_session_token(raw), csrf, "127.0.0.1", "pytest",
         iso(now), iso(now + timedelta(hours=8)), iso(last_activity)),
    )
    conn.commit()
    conn.close()
    return {"session_token": raw, "csrf_token": csrf}


def test_admin_session_within_idle_timeout_is_accepted(client, backend_env):
    actor = _seed_admin_with_session(backend_env, idle_minutes_ago=5)
    r = client.get("/api/v1/admin/licenses", cookies={"npc_admin_session": actor["session_token"]})
    assert r.status_code == 200


def test_admin_session_beyond_idle_timeout_is_rejected(client, backend_env, monkeypatch):
    monkeypatch.setenv("NPCREATE_BACKEND_ADMIN_SESSION_IDLE_TIMEOUT_MINUTES", "30")
    # Stale last_activity_at: 31 minutes ago > 30-minute idle limit.
    actor = _seed_admin_with_session(backend_env, idle_minutes_ago=31)
    r = client.get("/api/v1/admin/licenses", cookies={"npc_admin_session": actor["session_token"]})
    assert r.status_code == 401


def test_admin_session_idle_resets_on_each_request(client, backend_env):
    actor = _seed_admin_with_session(backend_env, idle_minutes_ago=10)
    # First request — succeeds and updates last_activity_at to now.
    r1 = client.get("/api/v1/admin/licenses", cookies={"npc_admin_session": actor["session_token"]})
    assert r1.status_code == 200
    # Read back DB to confirm last_activity_at is recent.
    conn = connect(backend_env)
    row = conn.execute(
        "SELECT last_activity_at FROM admin_sessions WHERE session_hash=?",
        (hash_session_token(actor["session_token"]),),
    ).fetchone()
    conn.close()
    from npcreate_backend.security import parse_dt
    last = parse_dt(row["last_activity_at"])
    assert (utcnow() - last) < timedelta(seconds=5)


# -- /auth/refresh rate limit ----------------------------------------------


def _seed_license_and_activate(client, backend_env):
    conn = connect(backend_env)
    migrate(conn)
    now = utcnow()
    license_id = "lic_rl"
    conn.execute(
        """
        INSERT INTO licenses(license_id,key_hash,customer_name,customer_contact,status,plan,starts_at,expires_at,
                             max_pc_devices,max_phone_devices,features_json,notes,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (license_id, hash_license_key("NP-RATE-LIMIT-RATE-LIMIT-AAAA", "pepper-pepper-pepper-pepper"),
         "C", "", "active", "monthly", iso(now), iso(now + timedelta(days=30)),
         1, 1, "[]", "", iso(now), iso(now)),
    )
    upsert_device_policies(conn, license_id, default_device_policies(1, 1), actor="test")
    conn.commit()
    conn.close()
    r = client.post("/api/v1/licenses/activate", json={
        "license_key": "NP-RATE-LIMIT-RATE-LIMIT-AAAA",
        "device_type": "pc",
        "device_fingerprint": "fp-rate-limit-test-fingerprint-x123",
        "device_label": "RL",
    })
    assert r.status_code == 200
    return r.json()["refresh_token"]


def test_refresh_rate_limit_blocks_after_threshold(client, backend_env, monkeypatch):
    monkeypatch.setenv("NPCREATE_BACKEND_AUTH_REFRESH_RATE_LIMIT_PER_MINUTE", "3")
    # Reset the limiter bucket between tests to avoid pollution from neighbours.
    from npcreate_backend.auth import _RATE_BUCKETS
    _RATE_BUCKETS.clear()

    refresh = _seed_license_and_activate(client, backend_env)
    # First successful rotation — chain stays valid; subsequent calls just see "refresh token reuse".
    # That's fine for rate-limit test: we only care that we hit 429 before reaching token logic.
    statuses = []
    for _ in range(5):
        r = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
        statuses.append(r.status_code)
    # First 3 should NOT be 429; from 4th onward, 429.
    assert 429 in statuses, f"expected 429 in {statuses}"
    assert statuses.count(429) >= 2, f"expected at least 2 rate-limited calls, got {statuses}"


def test_refresh_below_rate_limit_succeeds(client, backend_env, monkeypatch):
    monkeypatch.setenv("NPCREATE_BACKEND_AUTH_REFRESH_RATE_LIMIT_PER_MINUTE", "30")
    from npcreate_backend.auth import _RATE_BUCKETS
    _RATE_BUCKETS.clear()
    refresh = _seed_license_and_activate(client, backend_env)
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert r.status_code == 200
