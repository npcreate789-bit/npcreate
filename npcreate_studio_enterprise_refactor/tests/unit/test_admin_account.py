"""Tests for MFA backup codes + admin self-service password change (work H)."""
from __future__ import annotations

import time
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from npcreate_backend.admin_security import (
    BACKUP_CODE_GROUPS,
    _totp_at,
    generate_backup_codes,
    hash_backup_code,
    hash_password,
    hash_session_token,
    new_mfa_secret,
    new_session_token,
    normalize_backup_code,
)
from npcreate_backend.admin_security import (
    csrf_token as new_csrf,
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
def client(backend_env):
    return TestClient(create_app())


# --- helpers: pure functions ----------------------------------------------


def test_generate_backup_codes_produces_unique_human_readable():
    codes = generate_backup_codes(8)
    assert len(codes) == 8
    assert len(set(codes)) == 8
    for c in codes:
        groups = c.split("-")
        assert len(groups) == len(BACKUP_CODE_GROUPS)
        for grp, expected_len in zip(groups, BACKUP_CODE_GROUPS, strict=True):
            assert len(grp) == expected_len
            assert grp.isalnum()


def test_normalize_backup_code_strips_dashes_and_uppercases():
    assert normalize_backup_code("abcd-1234-wxyz") == "ABCD1234WXYZ"
    assert normalize_backup_code(" ABCD 1234 WXYZ ") == "ABCD1234WXYZ"


def test_hash_backup_code_is_dash_insensitive():
    a = hash_backup_code("ABCD-1234-WXYZ")
    b = hash_backup_code("abcd1234wxyz")
    assert a == b


# --- login with backup code -----------------------------------------------


def _seed_admin_with_mfa(db_path) -> tuple[str, str, list[str]]:
    """Seed admin user + backup codes. Returns (email, mfa_secret, codes)."""
    conn = connect(db_path)
    migrate(conn)
    now = utcnow()
    secret = new_mfa_secret()
    conn.execute(
        """
        INSERT INTO admin_users(admin_id, email, display_name, password_hash, mfa_secret,
                                mfa_enabled, role, status, created_at, updated_at)
        VALUES(?,?,?,?,?,1,'owner','active',?,?)
        """,
        ("ad_h", "h@example.com", "H", hash_password("VeryStrongPwd2026!"), secret, iso(now), iso(now)),
    )
    codes = generate_backup_codes(8)
    for i, code in enumerate(codes):
        conn.execute(
            "INSERT INTO admin_backup_codes(code_id, admin_id, code_hash, created_at) VALUES(?,?,?,?)",
            (f"bc_{i}", "ad_h", hash_backup_code(code), iso(now)),
        )
    conn.commit()
    conn.close()
    return "h@example.com", secret, codes


def test_login_with_totp_still_works(client, backend_env):
    email, secret, _ = _seed_admin_with_mfa(backend_env)
    totp = _totp_at(secret, int(time.time() // 30))
    r = client.post(
        "/admin/login",
        data={"email": email, "password": "VeryStrongPwd2026!", "mfa_code": totp},
        follow_redirects=False,
    )
    assert r.status_code == 303


def test_login_with_backup_code_succeeds_and_consumes_it(client, backend_env):
    email, _, codes = _seed_admin_with_mfa(backend_env)
    code = codes[0]
    r = client.post(
        "/admin/login",
        data={"email": email, "password": "VeryStrongPwd2026!", "mfa_code": code},
        follow_redirects=False,
    )
    assert r.status_code == 303

    # The same backup code must not work a second time.
    r2 = client.post(
        "/admin/login",
        data={"email": email, "password": "VeryStrongPwd2026!", "mfa_code": code},
        follow_redirects=False,
    )
    assert r2.status_code == 401

    # Another (unused) backup code still works.
    r3 = client.post(
        "/admin/login",
        data={"email": email, "password": "VeryStrongPwd2026!", "mfa_code": codes[1]},
        follow_redirects=False,
    )
    assert r3.status_code == 303


def test_login_with_invalid_backup_code_fails(client, backend_env):
    email, _, _ = _seed_admin_with_mfa(backend_env)
    r = client.post(
        "/admin/login",
        data={"email": email, "password": "VeryStrongPwd2026!", "mfa_code": "ZZZZ-9999-XXXX"},
        follow_redirects=False,
    )
    assert r.status_code == 401


def test_backup_code_accepts_dashless_input(client, backend_env):
    email, _, codes = _seed_admin_with_mfa(backend_env)
    code = codes[0].replace("-", "").lower()
    r = client.post(
        "/admin/login",
        data={"email": email, "password": "VeryStrongPwd2026!", "mfa_code": code},
        follow_redirects=False,
    )
    assert r.status_code == 303


# --- account page + change password + regenerate -------------------------


def _login_session(db_path) -> dict[str, str]:
    """Insert an active session row to skip the full TOTP login dance."""
    conn = connect(db_path)
    migrate(conn)
    now = utcnow()
    conn.execute(
        """
        INSERT INTO admin_users(admin_id, email, display_name, password_hash, mfa_secret,
                                mfa_enabled, role, status, created_at, updated_at)
        VALUES(?,?,?,?,?,0,'owner','active',?,?)
        """,
        ("ad_acc", "acc@example.com", "Acc", hash_password("CurrentPassword2026!"), new_mfa_secret(), iso(now), iso(now)),
    )
    raw = new_session_token()
    csrf = new_csrf()
    conn.execute(
        """
        INSERT INTO admin_sessions(session_id, admin_id, session_hash, csrf_token, ip_address,
                                   user_agent, created_at, expires_at, last_activity_at)
        VALUES(?,?,?,?,?,?,?,?,?)
        """,
        ("as_acc", "ad_acc", hash_session_token(raw), csrf, "127.0.0.1", "pytest",
         iso(now), iso(now + timedelta(hours=8)), iso(now)),
    )
    conn.commit()
    conn.close()
    return {"session_token": raw, "csrf_token": csrf, "admin_id": "ad_acc"}


def test_account_page_renders_for_logged_in_admin(client, backend_env):
    s = _login_session(backend_env)
    r = client.get("/admin/account", cookies={"npc_admin_session": s["session_token"]})
    assert r.status_code == 200
    assert "acc@example.com" in r.text
    assert 'action="/admin/account/change-password"' in r.text
    assert 'action="/admin/account/regenerate-backup-codes"' in r.text


def test_change_password_with_correct_current_password(client, backend_env):
    s = _login_session(backend_env)
    r = client.post(
        "/admin/account/change-password",
        data={"_csrf": s["csrf_token"], "current_password": "CurrentPassword2026!", "new_password": "NewBetter2026Password!"},
        cookies={"npc_admin_session": s["session_token"]},
        follow_redirects=False,
    )
    assert r.status_code == 303
    # Verify new password actually works for login.
    r2 = client.post(
        "/admin/login",
        data={"email": "acc@example.com", "password": "NewBetter2026Password!", "mfa_code": "unused"},
        follow_redirects=False,
    )
    assert r2.status_code == 303  # mfa disabled for this test account


def test_change_password_rejects_wrong_current_password(client, backend_env):
    s = _login_session(backend_env)
    r = client.post(
        "/admin/account/change-password",
        data={"_csrf": s["csrf_token"], "current_password": "WRONG", "new_password": "DoesntMatterPwd!"},
        cookies={"npc_admin_session": s["session_token"]},
        follow_redirects=False,
    )
    assert r.status_code == 403


def test_change_password_requires_csrf(client, backend_env):
    s = _login_session(backend_env)
    r = client.post(
        "/admin/account/change-password",
        data={"current_password": "CurrentPassword2026!", "new_password": "AnotherStrongPwd2026!"},
        cookies={"npc_admin_session": s["session_token"]},
        follow_redirects=False,
    )
    assert r.status_code == 403


def test_regenerate_backup_codes_creates_new_set_and_invalidates_old(client, backend_env):
    s = _login_session(backend_env)
    # Seed one usable backup code first.
    conn = connect(backend_env)
    conn.execute(
        "INSERT INTO admin_backup_codes(code_id, admin_id, code_hash, created_at) VALUES('bc_old', ?, ?, ?)",
        (s["admin_id"], hash_backup_code("OLD1-OLD2-OLD3"), iso(utcnow())),
    )
    conn.commit()
    conn.close()

    r = client.post(
        "/admin/account/regenerate-backup-codes",
        data={"_csrf": s["csrf_token"]},
        cookies={"npc_admin_session": s["session_token"]},
        follow_redirects=False,
    )
    assert r.status_code == 303
    # The redirect URL must include exactly 8 new codes in query params.
    new_codes = [v for k, v in [tuple(part.split("=", 1)) for part in r.headers["location"].split("?", 1)[1].split("&")] if k == "new"]
    assert len(new_codes) == 8

    # Old code must no longer be usable.
    conn = connect(backend_env)
    row = conn.execute("SELECT COUNT(*) AS c FROM admin_backup_codes WHERE code_hash=?", (hash_backup_code("OLD1-OLD2-OLD3"),)).fetchone()
    assert row["c"] == 0
    # Exactly 8 fresh ones exist.
    row = conn.execute("SELECT COUNT(*) AS c FROM admin_backup_codes WHERE admin_id=? AND used_at IS NULL", (s["admin_id"],)).fetchone()
    assert row["c"] == 8
    conn.close()
