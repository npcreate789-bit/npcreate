from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse

from .admin_security import csrf_token, hash_session_token, new_session_token, session_expiry, verify_password, verify_totp
from .auth import get_admin_session, get_settings, rate_limit_admin_login, verify_admin_csrf
from .billing import audit_log
from .db import connect, migrate, one
from .observability import log_event
from .security import iso, parse_dt, utcnow
from .settings import BackendSettings
from .templates import templates

router = APIRouter()


@router.get("/admin/login", response_class=HTMLResponse)
def login_page(request: Request, session=Depends(get_admin_session)):
    if session:
        return RedirectResponse("/admin", status_code=303)
    return templates.TemplateResponse(request, "admin/login.html", {"error": ""})


@router.post("/admin/login")
def login_submit(
    request: Request,
    response: Response,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
    mfa_code: Annotated[str, Form()],
    settings: Annotated[BackendSettings, Depends(get_settings)],
    _: Annotated[None, Depends(rate_limit_admin_login)],
):
    conn = connect(settings.db_target)
    migrate(conn)
    user = one(conn, "SELECT * FROM admin_users WHERE email=?", (email.strip().lower(),))
    now = utcnow()
    if not user or user["status"] != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid admin credentials")
    if user["locked_until"] and parse_dt(user["locked_until"]) > now:
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail="admin account locked temporarily")
    if not verify_password(user["password_hash"], password) or (user["mfa_enabled"] and not verify_totp(user["mfa_secret"], mfa_code)):
        import logging
        failed = int(user["failed_login_count"] or 0) + 1
        locked_until = iso(now + timedelta(minutes=15)) if failed >= 5 else None
        conn.execute("UPDATE admin_users SET failed_login_count=?, locked_until=?, updated_at=? WHERE admin_id=?", (failed, locked_until, iso(now), user["admin_id"]))
        ip = request.client.host if request.client else ""
        audit_log(conn, actor_type="admin", actor_id=user["admin_id"], action="admin.login_failed", target_type="admin_user", target_id=user["admin_id"], ip_address=ip)
        conn.commit()
        log_event(
            "admin.login_failed",
            level=logging.WARNING,
            admin_id=user["admin_id"],
            email=user["email"],
            ip=ip,
            failed_count=failed,
            locked_until=locked_until,
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid admin credentials")

    raw_session = new_session_token()
    session_id = "as_" + secrets.token_urlsafe(18)
    csrf = csrf_token()
    conn.execute(
        """
        INSERT INTO admin_sessions(session_id, admin_id, session_hash, csrf_token, ip_address, user_agent, created_at, expires_at, last_activity_at)
        VALUES(?,?,?,?,?,?,?,?,?)
        """,
        (
            session_id,
            user["admin_id"],
            hash_session_token(raw_session),
            csrf,
            request.client.host if request.client else "",
            request.headers.get("user-agent", "")[:250],
            iso(now),
            session_expiry(settings.admin_session_ttl_minutes),
            iso(now),
        ),
    )
    conn.execute("UPDATE admin_users SET failed_login_count=0, locked_until=NULL, last_login_at=?, updated_at=? WHERE admin_id=?", (iso(now), iso(now), user["admin_id"]))
    ip = request.client.host if request.client else ""
    audit_log(conn, actor_type="admin", actor_id=user["admin_id"], action="admin.login_success", target_type="admin_user", target_id=user["admin_id"], ip_address=ip)
    conn.commit()
    role = user["role"] if "role" in user.keys() else "admin"
    log_event("admin.login_success", admin_id=user["admin_id"], email=user["email"], ip=ip, role=role)
    resp = RedirectResponse("/admin", status_code=303)
    resp.set_cookie(
        settings.admin_session_cookie_name,
        raw_session,
        max_age=settings.admin_session_ttl_minutes * 60,
        httponly=True,
        secure=settings.env == "production",
        samesite="lax",
    )
    return resp


@router.post("/admin/logout", dependencies=[Depends(verify_admin_csrf)])
def logout(request: Request, settings: Annotated[BackendSettings, Depends(get_settings)]):
    token = request.cookies.get(settings.admin_session_cookie_name)
    admin_id = ""
    if token:
        conn = connect(settings.db_target)
        migrate(conn)
        row = one(conn, "SELECT admin_id FROM admin_sessions WHERE session_hash=?", (hash_session_token(token),))
        admin_id = row["admin_id"] if row else ""
        conn.execute("UPDATE admin_sessions SET revoked_at=? WHERE session_hash=?", (iso(utcnow()), hash_session_token(token)))
        conn.commit()
    resp = RedirectResponse("/admin/login", status_code=303)
    resp.delete_cookie(settings.admin_session_cookie_name)
    log_event("admin.logout", admin_id=admin_id, ip=request.client.host if request.client else "")
    return resp
