from __future__ import annotations

import json
import secrets
from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .auth import get_settings, require_admin, require_role
from .billing import audit_log, create_subscription, default_device_policies, upsert_device_policies
from .db import all_rows, connect, migrate, one
from .observability import log_event
from .pagination import clamp_limit, clamp_offset, like_escape
from .security import (
    hash_license_key,
    iso,
    new_license_key,
    parse_dt,
    sign_update_manifest,
    utcnow,
)
from .settings import BackendSettings
from .templates import templates

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])


def _common_context(session: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {"csrf_token": session.get("csrf_token", ""), **extra}


def _page_meta(*, total: int, limit: int, offset: int, query: dict[str, str]) -> dict[str, Any]:
    page = offset // limit + 1 if limit else 1
    pages = max(1, (total + limit - 1) // limit) if limit else 1
    return {
        "total": int(total),
        "limit": int(limit),
        "offset": int(offset),
        "page": page,
        "pages": pages,
        "has_prev": offset > 0,
        "has_next": offset + limit < total,
        "prev_offset": max(0, offset - limit),
        "next_offset": offset + limit,
        "query": query,
    }


def _counts(conn):
    tables = ["licenses", "devices", "subscriptions", "payments", "release_requests", "error_reports"]
    out = {}
    for table in tables:
        row = one(conn, f"SELECT COUNT(*) AS c FROM {table}")
        out[table] = int(row["c"] if row else 0)
    return out


@router.get("", response_class=HTMLResponse)
def dashboard(request: Request, settings: Annotated[BackendSettings, Depends(get_settings)], session: Annotated[dict[str, Any], Depends(require_admin)]):
    conn = connect(settings.db_target)
    migrate(conn)
    recent_licenses = all_rows(conn, "SELECT license_id, customer_name, status, expires_at, created_at FROM licenses ORDER BY created_at DESC LIMIT 8")
    recent_events = all_rows(conn, "SELECT event_id, provider, event_type, processing_status, received_at FROM payment_events ORDER BY received_at DESC LIMIT 8")
    return templates.TemplateResponse(request, "admin/dashboard.html", _common_context(session, counts=_counts(conn), licenses=[dict(r) for r in recent_licenses], events=[dict(r) for r in recent_events], page="dashboard"))


@router.get("/licenses", response_class=HTMLResponse)
def licenses_page(
    request: Request,
    settings: Annotated[BackendSettings, Depends(get_settings)],
    session: Annotated[dict[str, Any], Depends(require_admin)],
    status_filter: str = "",
    q: str = "",
    limit: int = 50,
    offset: int = 0,
):
    conn = connect(settings.db_target)
    migrate(conn)
    limit = clamp_limit(limit)
    offset = clamp_offset(offset)
    where: list[str] = []
    params: list[object] = []
    if status_filter:
        where.append("status=?")
        params.append(status_filter)
    if q:
        where.append("(customer_name LIKE ? ESCAPE '\\' OR customer_contact LIKE ? ESCAPE '\\' OR license_id LIKE ? ESCAPE '\\')")
        like = f"%{like_escape(q)}%"
        params.extend([like, like, like])
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    total_row = one(conn, f"SELECT COUNT(*) AS c FROM licenses{where_sql}", tuple(params))
    total = int(total_row["c"]) if total_row else 0
    items = all_rows(
        conn,
        f"SELECT license_id, customer_name, customer_contact, status, expires_at, plan, created_at FROM licenses{where_sql} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        tuple(params) + (limit, offset),
    )
    meta = _page_meta(total=total, limit=limit, offset=offset, query={"status_filter": status_filter, "q": q})
    return templates.TemplateResponse(request, "admin/licenses.html", _common_context(session, items=[dict(r) for r in items], meta=meta, filters={"status_filter": status_filter, "q": q}, page="licenses"))


@router.get("/payments", response_class=HTMLResponse)
def payments_page(
    request: Request,
    settings: Annotated[BackendSettings, Depends(get_settings)],
    session: Annotated[dict[str, Any], Depends(require_admin)],
    provider: str = "",
    status_filter: str = "",
    limit: int = 50,
    offset: int = 0,
):
    conn = connect(settings.db_target)
    migrate(conn)
    limit = clamp_limit(limit)
    offset = clamp_offset(offset)
    where: list[str] = []
    params: list[object] = []
    if provider:
        where.append("provider=?")
        params.append(provider)
    if status_filter:
        where.append("status=?")
        params.append(status_filter)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    total_row = one(conn, f"SELECT COUNT(*) AS c FROM payments{where_sql}", tuple(params))
    total = int(total_row["c"]) if total_row else 0
    items = all_rows(
        conn,
        f"SELECT payment_id, license_id, provider, provider_payment_id, status, amount_satangs, currency, paid_at, created_at FROM payments{where_sql} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        tuple(params) + (limit, offset),
    )
    meta = _page_meta(total=total, limit=limit, offset=offset, query={"provider": provider, "status_filter": status_filter})
    return templates.TemplateResponse(request, "admin/payments.html", _common_context(session, items=[dict(r) for r in items], meta=meta, filters={"provider": provider, "status_filter": status_filter}, page="payments"))


@router.get("/devices", response_class=HTMLResponse)
def devices_page(
    request: Request,
    settings: Annotated[BackendSettings, Depends(get_settings)],
    session: Annotated[dict[str, Any], Depends(require_admin)],
    status_filter: str = "",
    device_type: str = "",
    q: str = "",
    limit: int = 50,
    offset: int = 0,
):
    conn = connect(settings.db_target)
    migrate(conn)
    limit = clamp_limit(limit)
    offset = clamp_offset(offset)
    where: list[str] = []
    params: list[object] = []
    if status_filter:
        where.append("d.status=?")
        params.append(status_filter)
    if device_type:
        where.append("d.device_type=?")
        params.append(device_type)
    if q:
        where.append("(d.label LIKE ? ESCAPE '\\' OR l.customer_name LIKE ? ESCAPE '\\' OR d.device_id LIKE ? ESCAPE '\\')")
        like = f"%{like_escape(q)}%"
        params.extend([like, like, like])
    base_join = " FROM devices d JOIN licenses l ON l.license_id=d.license_id"
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    total_row = one(conn, f"SELECT COUNT(*) AS c {base_join}{where_sql}", tuple(params))
    total = int(total_row["c"]) if total_row else 0
    items = all_rows(
        conn,
        f"SELECT d.device_id, d.license_id, l.customer_name, d.device_type, d.label, d.status, d.bound_at, d.last_seen_at {base_join}{where_sql} ORDER BY d.bound_at DESC LIMIT ? OFFSET ?",
        tuple(params) + (limit, offset),
    )
    release_requests = all_rows(conn, """
        SELECT rr.request_id, rr.license_id, l.customer_name, d.label, d.device_type, rr.reason, rr.status, rr.requested_at
        FROM release_requests rr
        JOIN licenses l ON l.license_id=rr.license_id
        JOIN devices d ON d.device_id=rr.device_id
        WHERE rr.status='pending'
        ORDER BY rr.requested_at DESC LIMIT 100
    """)
    meta = _page_meta(total=total, limit=limit, offset=offset, query={"status_filter": status_filter, "device_type": device_type, "q": q})
    return templates.TemplateResponse(request, "admin/devices.html", _common_context(session, items=[dict(r) for r in items], release_requests=[dict(r) for r in release_requests], meta=meta, filters={"status_filter": status_filter, "device_type": device_type, "q": q}, page="devices"))


@router.get("/logs", response_class=HTMLResponse)
def logs_page(
    request: Request,
    settings: Annotated[BackendSettings, Depends(get_settings)],
    session: Annotated[dict[str, Any], Depends(require_admin)],
    action: str = "",
    actor_id: str = "",
    limit: int = 50,
    offset: int = 0,
):
    conn = connect(settings.db_target)
    migrate(conn)
    limit = clamp_limit(limit)
    offset = clamp_offset(offset)
    where: list[str] = []
    params: list[object] = []
    if action:
        where.append("action=?")
        params.append(action)
    if actor_id:
        where.append("actor_id=?")
        params.append(actor_id)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    total_row = one(conn, f"SELECT COUNT(*) AS c FROM audit_logs{where_sql}", tuple(params))
    total = int(total_row["c"]) if total_row else 0
    audits = all_rows(
        conn,
        f"SELECT * FROM audit_logs{where_sql} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        tuple(params) + (limit, offset),
    )
    errors = all_rows(conn, "SELECT * FROM error_reports ORDER BY created_at DESC LIMIT 100")
    meta = _page_meta(total=total, limit=limit, offset=offset, query={"action": action, "actor_id": actor_id})
    return templates.TemplateResponse(request, "admin/logs.html", _common_context(session, audits=[dict(r) for r in audits], errors=[dict(r) for r in errors], meta=meta, filters={"action": action, "actor_id": actor_id}, page="logs"))


@router.post("/licenses/create")
def create_license_form(
    request: Request,
    settings: Annotated[BackendSettings, Depends(get_settings)],
    session: Annotated[dict[str, Any], Depends(require_role("owner", "admin"))],
    customer_name: Annotated[str, Form(min_length=1, max_length=160)],
    customer_contact: Annotated[str, Form(max_length=160)] = "",
    months: Annotated[int, Form(ge=1, le=36)] = 1,
    max_pc_devices: Annotated[int, Form(ge=0, le=10)] = 1,
    max_phone_devices: Annotated[int, Form(ge=0, le=50)] = 1,
):
    conn = connect(settings.db_target)
    migrate(conn)
    raw_key = new_license_key()
    now = utcnow()
    expires_at = now + timedelta(days=31 * months)
    license_id = "lic_" + secrets.token_urlsafe(18)
    conn.execute(
        """
        INSERT INTO licenses(
            license_id, key_hash, customer_name, customer_contact, status, plan,
            starts_at, expires_at, max_pc_devices, max_phone_devices,
            features_json, notes, created_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (license_id, hash_license_key(raw_key, settings.key_pepper), customer_name,
         customer_contact, "active", "monthly", iso(now), iso(expires_at),
         max_pc_devices, max_phone_devices, json.dumps([]), "", iso(now), iso(now)),
    )
    upsert_device_policies(conn, license_id, default_device_policies(max_pc_devices, max_phone_devices), actor=session["admin_id"])
    conn.commit()
    log_event("device_policy.upserted", admin_id=session["admin_id"], license_id=license_id, customer_name=customer_name, months=months)
    return RedirectResponse(
        f"/admin/licenses?created={license_id}&key={raw_key}",
        status_code=303,
    )


@router.post("/licenses/{license_id}/renew")
def renew_license_form(
    license_id: str,
    request: Request,
    settings: Annotated[BackendSettings, Depends(get_settings)],
    session: Annotated[dict[str, Any], Depends(require_role("owner", "admin", "billing"))],
    months: Annotated[int, Form(ge=1, le=36)] = 1,
):
    conn = connect(settings.db_target)
    migrate(conn)
    lic = one(conn, "SELECT * FROM licenses WHERE license_id=?", (license_id,))
    if not lic:
        raise HTTPException(status_code=404, detail="license not found")
    base = max(parse_dt(lic["expires_at"]), utcnow())
    expires_at = base + timedelta(days=31 * months)
    conn.execute(
        "UPDATE licenses SET expires_at=?, status='active', updated_at=? WHERE license_id=?",
        (iso(expires_at), iso(utcnow()), license_id),
    )
    audit_log(conn, actor_type="admin", actor_id=session["admin_id"], action="license.renew", target_type="license", target_id=license_id, metadata={"months": months})
    conn.commit()
    log_event("license.renew", admin_id=session["admin_id"], license_id=license_id, months=months)
    return RedirectResponse("/admin/licenses", status_code=303)


@router.post("/release-requests/{request_id}/approve")
def approve_release_form(
    request_id: str,
    request: Request,
    settings: Annotated[BackendSettings, Depends(get_settings)],
    session: Annotated[dict[str, Any], Depends(require_role("owner", "admin", "support"))],
    reason: Annotated[str, Form(max_length=1000)] = "",
):
    conn = connect(settings.db_target)
    migrate(conn)
    row = one(conn, "SELECT * FROM release_requests WHERE request_id=?", (request_id,))
    if not row:
        raise HTTPException(status_code=404, detail="release request not found")
    if row["status"] != "pending":
        raise HTTPException(status_code=409, detail="release request already resolved")
    now = iso(utcnow())
    actor = session["admin_id"]
    conn.execute(
        "UPDATE devices SET status='released', released_at=?, released_by=?, release_reason=? WHERE device_id=?",
        (now, actor, reason or "approved_release_request", row["device_id"]),
    )
    conn.execute(
        "UPDATE release_requests SET status='approved', resolved_at=?, resolved_by=? WHERE request_id=?",
        (now, actor, request_id),
    )
    # Revoke any active refresh tokens for this device — moved off device implies new activation.
    from .refresh_tokens import revoke_device_refresh_tokens

    revoked = revoke_device_refresh_tokens(conn, row["device_id"], reason="release_request_approved")
    audit_log(conn, actor_type="admin", actor_id=actor, action="device.release.approve", target_type="device", target_id=row["device_id"], metadata={"request_id": request_id, "refresh_tokens_revoked": revoked})
    conn.commit()
    log_event("release_request.approved", admin_id=actor, request_id=request_id, device_id=row["device_id"], license_id=row["license_id"])
    return RedirectResponse("/admin/devices", status_code=303)


@router.post("/release-requests/{request_id}/reject")
def reject_release_form(
    request_id: str,
    request: Request,
    settings: Annotated[BackendSettings, Depends(get_settings)],
    session: Annotated[dict[str, Any], Depends(require_role("owner", "admin", "support"))],
    reason: Annotated[str, Form(max_length=1000)] = "",
):
    conn = connect(settings.db_target)
    migrate(conn)
    row = one(conn, "SELECT * FROM release_requests WHERE request_id=?", (request_id,))
    if not row:
        raise HTTPException(status_code=404, detail="release request not found")
    if row["status"] != "pending":
        raise HTTPException(status_code=409, detail="release request already resolved")
    actor = session["admin_id"]
    conn.execute(
        "UPDATE release_requests SET status='rejected', resolved_at=?, resolved_by=? WHERE request_id=?",
        (iso(utcnow()), actor, request_id),
    )
    audit_log(conn, actor_type="admin", actor_id=actor, action="device.release.reject", target_type="device", target_id=row["device_id"], metadata={"request_id": request_id, "reason": reason})
    conn.commit()
    log_event("release_request.rejected", admin_id=actor, request_id=request_id, device_id=row["device_id"], reason=reason)
    return RedirectResponse("/admin/devices", status_code=303)


@router.post("/news/publish")
def publish_news_form(
    request: Request,
    settings: Annotated[BackendSettings, Depends(get_settings)],
    session: Annotated[dict[str, Any], Depends(require_role("owner", "admin"))],
    title: Annotated[str, Form(min_length=1, max_length=160)],
    body: Annotated[str, Form(min_length=1, max_length=5000)],
    severity: Annotated[str, Form(pattern="^(info|success|warning|critical)$")] = "info",
    audience: Annotated[str, Form(max_length=80)] = "all",
):
    conn = connect(settings.db_target)
    migrate(conn)
    news_id = "news_" + secrets.token_urlsafe(18)
    conn.execute(
        """
        INSERT INTO news(news_id, title, body, severity, audience, published_at, expires_at, is_active)
        VALUES(?,?,?,?,?,?,?,1)
        """,
        (news_id, title, body, severity, audience, iso(utcnow()), None),
    )
    audit_log(conn, actor_type="admin", actor_id=session["admin_id"], action="news.publish", target_type="news", target_id=news_id, metadata={"severity": severity, "audience": audience})
    conn.commit()
    log_event("news.published", admin_id=session["admin_id"], news_id=news_id, severity=severity, audience=audience, title=title)
    return RedirectResponse("/admin/news", status_code=303)


@router.get("/news", response_class=HTMLResponse)
def news_page(
    request: Request,
    settings: Annotated[BackendSettings, Depends(get_settings)],
    session: Annotated[dict[str, Any], Depends(require_admin)],
    limit: int = 50,
    offset: int = 0,
):
    conn = connect(settings.db_target)
    migrate(conn)
    limit = clamp_limit(limit)
    offset = clamp_offset(offset)
    total_row = one(conn, "SELECT COUNT(*) AS c FROM news")
    total = int(total_row["c"]) if total_row else 0
    items = all_rows(
        conn,
        "SELECT news_id, title, body, severity, audience, published_at, expires_at, is_active FROM news ORDER BY published_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    )
    meta = _page_meta(total=total, limit=limit, offset=offset, query={})
    return templates.TemplateResponse(request, "admin/news.html", _common_context(session, items=[dict(r) for r in items], meta=meta, page="news"))


@router.post("/updates/publish")
def publish_update_form(
    request: Request,
    settings: Annotated[BackendSettings, Depends(get_settings)],
    session: Annotated[dict[str, Any], Depends(require_role("owner", "admin"))],
    version: Annotated[str, Form(min_length=1, max_length=40)],
    download_url: Annotated[str, Form(min_length=8, max_length=2000)],
    sha256: Annotated[str, Form(min_length=64, max_length=64)],
    channel: Annotated[str, Form(pattern="^(stable|beta|dev)$")] = "stable",
    mandatory: Annotated[bool, Form()] = False,
    release_notes: Annotated[str, Form(max_length=5000)] = "",
):
    if not settings.ed25519_private_key_hex:
        raise HTTPException(status_code=400, detail="NPCREATE_BACKEND_ED25519_PRIVATE_KEY_HEX must be configured to publish updates")
    signature = sign_update_manifest(
        settings.ed25519_private_key_hex,
        version=version,
        channel=channel,
        mandatory=mandatory,
        download_url=download_url,
        sha256=sha256,
    )
    conn = connect(settings.db_target)
    migrate(conn)
    update_id = "upd_" + secrets.token_urlsafe(18)
    conn.execute(
        """
        INSERT INTO update_manifests(update_id, version, channel, mandatory, download_url, sha256, signature, release_notes, is_active, published_at)
        VALUES(?,?,?,?,?,?,?,?,1,?)
        """,
        (update_id, version, channel, int(mandatory), download_url, sha256, signature, release_notes, iso(utcnow())),
    )
    audit_log(conn, actor_type="admin", actor_id=session["admin_id"], action="update.publish", target_type="update_manifest", target_id=update_id, metadata={"version": version, "channel": channel, "mandatory": mandatory})
    conn.commit()
    log_event("update.published", admin_id=session["admin_id"], update_id=update_id, version=version, channel=channel, mandatory=mandatory)
    return RedirectResponse("/admin/updates", status_code=303)


@router.get("/updates", response_class=HTMLResponse)
def updates_page(
    request: Request,
    settings: Annotated[BackendSettings, Depends(get_settings)],
    session: Annotated[dict[str, Any], Depends(require_admin)],
    channel: str = "",
    limit: int = 50,
    offset: int = 0,
):
    conn = connect(settings.db_target)
    migrate(conn)
    limit = clamp_limit(limit)
    offset = clamp_offset(offset)
    where: list[str] = []
    params: list[object] = []
    if channel:
        where.append("channel=?")
        params.append(channel)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    total_row = one(conn, f"SELECT COUNT(*) AS c FROM update_manifests{where_sql}", tuple(params))
    total = int(total_row["c"]) if total_row else 0
    items = all_rows(
        conn,
        f"SELECT update_id, version, channel, mandatory, download_url, sha256, is_active, published_at FROM update_manifests{where_sql} ORDER BY published_at DESC LIMIT ? OFFSET ?",
        tuple(params) + (limit, offset),
    )
    meta = _page_meta(total=total, limit=limit, offset=offset, query={"channel": channel})
    return templates.TemplateResponse(request, "admin/updates.html", _common_context(session, items=[dict(r) for r in items], meta=meta, filters={"channel": channel}, has_signing_key=bool(settings.ed25519_private_key_hex), page="updates"))


@router.post("/subscriptions/create")
def create_subscription_form(
    request: Request,
    settings: Annotated[BackendSettings, Depends(get_settings)],
    session: Annotated[dict[str, Any], Depends(require_role("owner", "admin", "billing"))],
    license_id: Annotated[str, Form(min_length=8, max_length=80)],
    provider_subscription_id: Annotated[str, Form(min_length=3, max_length=160)],
    provider: Annotated[str, Form(pattern=r"^[a-z0-9_\-]+$")] = "manual",
    provider_customer_id: Annotated[str, Form(max_length=160)] = "",
    amount_satangs: Annotated[int, Form(ge=0, le=50_000_000)] = 0,
    currency: Annotated[str, Form(min_length=3, max_length=3)] = "THB",
):
    conn = connect(settings.db_target)
    migrate(conn)
    sub_id = create_subscription(
        conn,
        license_id=license_id,
        provider=provider,
        provider_customer_id=provider_customer_id,
        provider_subscription_id=provider_subscription_id,
        amount_satangs=amount_satangs,
        currency=currency,
        next_renewal_at=None,
        actor_id=session["admin_id"],
    )
    conn.commit()
    log_event("subscription.created", admin_id=session["admin_id"], license_id=license_id, provider=provider, subscription_id=sub_id)
    return RedirectResponse("/admin/licenses", status_code=303)


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, settings: Annotated[BackendSettings, Depends(get_settings)], session: Annotated[dict[str, Any], Depends(require_admin)]):
    safe_settings = {
        "env": settings.env,
        "database": "PostgreSQL" if settings.is_postgres else "SQLite/dev",
        "payment_provider_mode": settings.payment_provider_mode,
        "billing_job_enabled": settings.billing_job_enabled,
        "billing_job_interval_minutes": settings.billing_job_interval_minutes,
        "code_signing_required": settings.code_signing_required,
        "allow_legacy_admin_token": settings.allow_legacy_admin_token,
    }
    return templates.TemplateResponse(request, "admin/settings.html", _common_context(session, settings=safe_settings, page="settings"))
