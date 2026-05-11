from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from .auth import require_admin, get_settings
from .db import all_rows, connect, migrate, one
from .pagination import clamp_limit, clamp_offset, like_escape
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
