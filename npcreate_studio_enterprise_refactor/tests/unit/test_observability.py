from __future__ import annotations

import json
import logging
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
from npcreate_backend.jobs import run_billing_maintenance
from npcreate_backend.observability import EVENT_LOGGER_NAME, JsonFormatter, log_event
from npcreate_backend.security import iso, utcnow
from npcreate_backend.settings import BackendSettings


def test_log_event_emits_record_with_event_field(caplog):
    with caplog.at_level(logging.INFO, logger=EVENT_LOGGER_NAME):
        log_event("admin.login_failed", admin_id="ad_1", email="a@b.com", ip="127.0.0.1", failed_count=3)
    matched = [r for r in caplog.records if getattr(r, "event", None) == "admin.login_failed"]
    assert len(matched) == 1
    assert matched[0].admin_id == "ad_1"
    assert matched[0].failed_count == 3


def test_log_event_unregistered_name_still_emits_at_debug(caplog):
    with caplog.at_level(logging.DEBUG, logger=EVENT_LOGGER_NAME):
        log_event("totally.unknown_event", x=1)
    events = [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]
    assert any("unregistered event name" in m for m in events)


def test_json_formatter_serializes_extras_and_drops_non_json():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="npcreate.events",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="admin.login_failed",
        args=(),
        exc_info=None,
    )
    record.event = "admin.login_failed"
    record.admin_id = "ad_test"
    record.complex_obj = object()
    out = json.loads(formatter.format(record))
    assert out["event"] == "admin.login_failed"
    assert out["admin_id"] == "ad_test"
    assert out["level"] == "WARNING"
    assert "complex_obj" in out


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
    monkeypatch.setenv("NPCREATE_BACKEND_PAYMENT_GRACE_DAYS", "0")
    return db_path


def _make_owner(db_path):
    conn = connect(db_path)
    migrate(conn)
    now = utcnow()
    conn.execute(
        """
        INSERT INTO admin_users(admin_id, email, display_name, password_hash, mfa_secret,
                                mfa_enabled, role, status, created_at, updated_at)
        VALUES(?,?,?,?,?,0,'owner','active',?,?)
        """,
        ("ad_owner", "owner@example.com", "Owner", hash_password("x"), new_mfa_secret(), iso(now), iso(now)),
    )
    raw = new_session_token()
    csrf = new_csrf()
    conn.execute(
        """
        INSERT INTO admin_sessions(session_id, admin_id, session_hash, csrf_token, ip_address,
                                   user_agent, created_at, expires_at)
        VALUES(?,?,?,?,?,?,?,?)
        """,
        ("as_owner", "ad_owner", hash_session_token(raw), csrf, "127.0.0.1", "pytest", iso(now), iso(now + timedelta(hours=8))),
    )
    conn.commit()
    conn.close()
    return {"session_token": raw, "csrf_token": csrf}


def test_create_license_emits_event(backend_env, caplog):
    owner = _make_owner(backend_env)
    client = TestClient(create_app())
    with caplog.at_level(logging.INFO, logger=EVENT_LOGGER_NAME):
        response = client.post(
            "/api/v1/admin/licenses",
            json={"customer_name": "ObsTest", "months": 1, "max_pc_devices": 1, "max_phone_devices": 1, "features": []},
            headers={"X-CSRF-Token": owner["csrf_token"]},
            cookies={"npc_admin_session": owner["session_token"]},
        )
    assert response.status_code == 200
    events = [getattr(r, "event", None) for r in caplog.records]
    assert "device_policy.upserted" in events


def test_billing_maintenance_emits_past_due_and_suspended(backend_env, caplog):
    settings = BackendSettings()
    conn = connect(backend_env)
    migrate(conn)
    now = utcnow()
    conn.execute(
        "INSERT INTO licenses(license_id,key_hash,customer_name,status,plan,starts_at,expires_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
        ("lic_obs", "obs_hash_unique", "Customer", "active", "monthly", iso(now), iso(now), iso(now), iso(now)),
    )
    conn.execute(
        "INSERT INTO subscriptions(subscription_id,license_id,provider,provider_subscription_id,status,billing_cycle,amount_satangs,currency,next_renewal_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        ("sub_obs", "lic_obs", "manual", "sub_obs_ext", "active", "monthly", 100, "THB", iso(now.replace(year=now.year - 1)), iso(now), iso(now)),
    )
    conn.commit()
    conn.close()

    with caplog.at_level(logging.WARNING, logger=EVENT_LOGGER_NAME):
        run_billing_maintenance(settings)
        run_billing_maintenance(settings)

    events = [getattr(r, "event", None) for r in caplog.records]
    assert "license.past_due" in events
    assert "license.suspend_overdue" in events
