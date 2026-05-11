from __future__ import annotations

import json
import secrets
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from .auth import get_settings, require_role, verify_admin_csrf
from .billing import audit_log, create_subscription, default_device_policies, list_device_policies, upsert_device_policies
from .db import all_rows, connect, migrate, one
from .observability import log_event
from .pagination import clamp_limit, clamp_offset, like_escape, paginated
from .refresh_tokens import revoke_device_refresh_tokens
from .models import (
    AdminCreateLicenseRequest,
    AdminCreateLicenseResponse,
    AdminCreateSubscriptionRequest,
    AdminPublishNewsRequest,
    AdminResolveReleaseRequest,
    AdminPublishUpdateRequest,
    AdminRenewLicenseRequest,
    AdminUpsertDevicePoliciesRequest,
)
from .security import hash_license_key, iso, new_license_key, parse_dt, sign_update_manifest, utcnow
from .settings import BackendSettings

router = APIRouter(prefix="/api/v1/admin", dependencies=[Depends(verify_admin_csrf)])


@router.post("/licenses", response_model=AdminCreateLicenseResponse)
def create_license(
    req: AdminCreateLicenseRequest,
    settings: Annotated[BackendSettings, Depends(get_settings)],
    session: Annotated[dict, Depends(require_role("owner", "admin"))],
):
    conn = connect(settings.db_target)
    migrate(conn)
    raw_key = new_license_key()
    now = utcnow()
    expires_at = now + timedelta(days=31 * req.months)
    license_id = "lic_" + secrets.token_urlsafe(18)
    policies = [p.model_dump() for p in req.device_policies] if req.device_policies else default_device_policies(req.max_pc_devices, req.max_phone_devices)
    conn.execute(
        """
        INSERT INTO licenses(
            license_id, key_hash, customer_name, customer_contact, status, plan,
            starts_at, expires_at, max_pc_devices, max_phone_devices,
            features_json, notes, created_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            license_id,
            hash_license_key(raw_key, settings.key_pepper),
            req.customer_name,
            req.customer_contact,
            "active",
            "monthly",
            iso(now),
            iso(expires_at),
            req.max_pc_devices,
            req.max_phone_devices,
            json.dumps(req.features, ensure_ascii=False),
            req.notes,
            iso(now),
            iso(now),
        ),
    )
    upsert_device_policies(conn, license_id, policies, actor=session["admin_id"])
    conn.commit()
    log_event("device_policy.upserted", admin_id=session["admin_id"], license_id=license_id, customer_name=req.customer_name, months=req.months)
    return AdminCreateLicenseResponse(license_id=license_id, license_key=raw_key, expires_at=expires_at)


@router.post("/licenses/{license_id}/renew")
def renew_license(
    license_id: str,
    req: AdminRenewLicenseRequest,
    settings: Annotated[BackendSettings, Depends(get_settings)],
    session: Annotated[dict, Depends(require_role("owner", "admin", "billing"))],
):
    conn = connect(settings.db_target)
    migrate(conn)
    lic = one(conn, "SELECT * FROM licenses WHERE license_id=?", (license_id,))
    if not lic:
        raise HTTPException(status_code=404, detail="license not found")
    base = max(parse_dt(lic["expires_at"]), utcnow())
    expires_at = base + timedelta(days=31 * req.months)
    conn.execute("UPDATE licenses SET expires_at=?, status='active', updated_at=? WHERE license_id=?", (iso(expires_at), iso(utcnow()), license_id))
    audit_log(conn, actor_type="admin", actor_id=session["admin_id"], action="license.renew", target_type="license", target_id=license_id, metadata={"months": req.months, "new_expires_at": iso(expires_at)})
    conn.commit()
    log_event("license.renew", admin_id=session["admin_id"], license_id=license_id, months=req.months, new_expires_at=iso(expires_at))
    return {"ok": True, "license_id": license_id, "expires_at": iso(expires_at)}


@router.get("/licenses")
def list_licenses(
    settings: Annotated[BackendSettings, Depends(get_settings)],
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
    rows = all_rows(
        conn,
        f"SELECT license_id, customer_name, customer_contact, status, expires_at, max_pc_devices, max_phone_devices, created_at FROM licenses{where_sql} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        tuple(params) + (limit, offset),
    )
    return paginated([dict(r) for r in rows], total=int(total_row["c"]) if total_row else 0, limit=limit, offset=offset)


@router.get("/licenses/{license_id}")
def get_license_detail(license_id: str, settings: Annotated[BackendSettings, Depends(get_settings)]):
    conn = connect(settings.db_target)
    migrate(conn)
    lic = one(conn, "SELECT * FROM licenses WHERE license_id=?", (license_id,))
    if not lic:
        raise HTTPException(status_code=404, detail="license not found")
    device_counts = all_rows(
        conn,
        """
        SELECT device_type, COUNT(*) AS bound_count
        FROM devices
        WHERE license_id=? AND status='bound'
        GROUP BY device_type
        """,
        (license_id,),
    )
    return {
        "license": dict(lic) | {"features": json.loads(lic["features_json"] or "[]")},
        "device_policies": list_device_policies(conn, license_id),
        "device_counts": [dict(r) for r in device_counts],
    }


@router.get("/licenses/{license_id}/device-policies")
def get_device_policies(license_id: str, settings: Annotated[BackendSettings, Depends(get_settings)]):
    conn = connect(settings.db_target)
    migrate(conn)
    if not one(conn, "SELECT license_id FROM licenses WHERE license_id=?", (license_id,)):
        raise HTTPException(status_code=404, detail="license not found")
    return {"items": list_device_policies(conn, license_id)}


@router.post("/licenses/{license_id}/device-policies")
def set_device_policies(
    license_id: str,
    req: AdminUpsertDevicePoliciesRequest,
    settings: Annotated[BackendSettings, Depends(get_settings)],
    session: Annotated[dict, Depends(require_role("owner", "admin"))],
):
    conn = connect(settings.db_target)
    migrate(conn)
    policies = [p.model_dump() for p in req.policies]
    upsert_device_policies(conn, license_id, policies, actor=session["admin_id"])
    conn.commit()
    return {"ok": True, "license_id": license_id, "items": list_device_policies(conn, license_id)}


@router.get("/licenses/{license_id}/devices")
def list_devices(
    license_id: str,
    settings: Annotated[BackendSettings, Depends(get_settings)],
    status_filter: str = "",
    device_type: str = "",
    limit: int = 50,
    offset: int = 0,
):
    conn = connect(settings.db_target)
    migrate(conn)
    limit = clamp_limit(limit)
    offset = clamp_offset(offset)
    where = ["license_id=?"]
    params: list[object] = [license_id]
    if status_filter:
        where.append("status=?")
        params.append(status_filter)
    if device_type:
        where.append("device_type=?")
        params.append(device_type)
    where_sql = " WHERE " + " AND ".join(where)
    total_row = one(conn, f"SELECT COUNT(*) AS c FROM devices{where_sql}", tuple(params))
    rows = all_rows(
        conn,
        f"SELECT device_id, device_type, label, status, bound_at, last_seen_at, released_at, release_reason FROM devices{where_sql} ORDER BY bound_at DESC LIMIT ? OFFSET ?",
        tuple(params) + (limit, offset),
    )
    return paginated([dict(r) for r in rows], total=int(total_row["c"]) if total_row else 0, limit=limit, offset=offset)


@router.post("/devices/{device_id}/release")
def release_device(
    device_id: str,
    settings: Annotated[BackendSettings, Depends(get_settings)],
    session: Annotated[dict, Depends(require_role("owner", "admin", "support"))],
):
    conn = connect(settings.db_target)
    migrate(conn)
    dev = one(conn, "SELECT * FROM devices WHERE device_id=?", (device_id,))
    if not dev:
        raise HTTPException(status_code=404, detail="device not found")
    now = iso(utcnow())
    actor = session["admin_id"]
    conn.execute(
        """
        UPDATE devices
        SET status='released', released_at=?, released_by=?, release_reason='admin_release'
        WHERE device_id=?
        """,
        (now, actor, device_id),
    )
    conn.execute("UPDATE release_requests SET status='approved', resolved_at=?, resolved_by=? WHERE device_id=? AND status='pending'", (now, actor, device_id))
    revoked = revoke_device_refresh_tokens(conn, device_id, reason="admin_release")
    audit_log(conn, actor_type="admin", actor_id=actor, action="device.release", target_type="device", target_id=device_id, metadata={"refresh_tokens_revoked": revoked})
    conn.commit()
    log_event("device.released", admin_id=actor, device_id=device_id, license_id=dev["license_id"], refresh_tokens_revoked=revoked)
    return {"ok": True, "device_id": device_id, "message": "device released; customer can activate another device"}


@router.post("/subscriptions")
def admin_create_subscription(
    req: AdminCreateSubscriptionRequest,
    settings: Annotated[BackendSettings, Depends(get_settings)],
    session: Annotated[dict, Depends(require_role("owner", "admin", "billing"))],
):
    conn = connect(settings.db_target)
    migrate(conn)
    sub_id = create_subscription(
        conn,
        license_id=req.license_id,
        provider=req.provider,
        provider_customer_id=req.provider_customer_id,
        provider_subscription_id=req.provider_subscription_id,
        amount_satangs=req.amount_satangs,
        currency=req.currency,
        next_renewal_at=req.next_renewal_at,
        actor_id=session["admin_id"],
    )
    conn.commit()
    log_event("subscription.created", admin_id=session["admin_id"], license_id=req.license_id, provider=req.provider, subscription_id=sub_id)
    return {"ok": True, "subscription_id": sub_id}


@router.get("/licenses/{license_id}/subscriptions")
def list_subscriptions(
    license_id: str,
    settings: Annotated[BackendSettings, Depends(get_settings)],
    status_filter: str = "",
    limit: int = 50,
    offset: int = 0,
):
    conn = connect(settings.db_target)
    migrate(conn)
    limit = clamp_limit(limit)
    offset = clamp_offset(offset)
    where = ["license_id=?"]
    params: list[object] = [license_id]
    if status_filter:
        where.append("status=?")
        params.append(status_filter)
    where_sql = " WHERE " + " AND ".join(where)
    total_row = one(conn, f"SELECT COUNT(*) AS c FROM subscriptions{where_sql}", tuple(params))
    rows = all_rows(
        conn,
        f"SELECT * FROM subscriptions{where_sql} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        tuple(params) + (limit, offset),
    )
    return paginated([dict(r) for r in rows], total=int(total_row["c"]) if total_row else 0, limit=limit, offset=offset)


@router.get("/licenses/{license_id}/payments")
def list_payments(
    license_id: str,
    settings: Annotated[BackendSettings, Depends(get_settings)],
    provider: str = "",
    status_filter: str = "",
    limit: int = 50,
    offset: int = 0,
):
    conn = connect(settings.db_target)
    migrate(conn)
    limit = clamp_limit(limit)
    offset = clamp_offset(offset)
    where = ["license_id=?"]
    params: list[object] = [license_id]
    if provider:
        where.append("provider=?")
        params.append(provider)
    if status_filter:
        where.append("status=?")
        params.append(status_filter)
    where_sql = " WHERE " + " AND ".join(where)
    total_row = one(conn, f"SELECT COUNT(*) AS c FROM payments{where_sql}", tuple(params))
    rows = all_rows(
        conn,
        f"SELECT payment_id, provider, provider_payment_id, status, amount_satangs, currency, paid_at, created_at FROM payments{where_sql} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        tuple(params) + (limit, offset),
    )
    return paginated([dict(r) for r in rows], total=int(total_row["c"]) if total_row else 0, limit=limit, offset=offset)


@router.get("/payment-events")
def list_payment_events(
    settings: Annotated[BackendSettings, Depends(get_settings)],
    provider: str = "",
    processing_status: str = "",
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
    if provider:
        where.append("provider=?")
        params.append(provider)
    if processing_status:
        where.append("processing_status=?")
        params.append(processing_status)
    if q:
        where.append("(external_event_id LIKE ? ESCAPE '\\' OR event_type LIKE ? ESCAPE '\\')")
        like = f"%{like_escape(q)}%"
        params.extend([like, like])
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    total_row = one(conn, f"SELECT COUNT(*) AS c FROM payment_events{where_sql}", tuple(params))
    rows = all_rows(
        conn,
        f"SELECT event_id, provider, external_event_id, event_type, processing_status, received_at, processed_at, error FROM payment_events{where_sql} ORDER BY received_at DESC LIMIT ? OFFSET ?",
        tuple(params) + (limit, offset),
    )
    return paginated([dict(r) for r in rows], total=int(total_row["c"]) if total_row else 0, limit=limit, offset=offset)


@router.get("/release-requests")
def list_release_requests(
    settings: Annotated[BackendSettings, Depends(get_settings)],
    status_filter: str = "pending",
    q: str = "",
    limit: int = 50,
    offset: int = 0,
):
    conn = connect(settings.db_target)
    migrate(conn)
    if status_filter not in {"pending", "approved", "rejected", "all"}:
        raise HTTPException(status_code=400, detail="invalid status_filter")
    limit = clamp_limit(limit)
    offset = clamp_offset(offset)
    where: list[str] = []
    params: list[object] = []
    if status_filter != "all":
        where.append("rr.status=?")
        params.append(status_filter)
    if q:
        where.append("(l.customer_name LIKE ? ESCAPE '\\' OR d.label LIKE ? ESCAPE '\\')")
        like = f"%{like_escape(q)}%"
        params.extend([like, like])
    base_join = """
        FROM release_requests rr
        JOIN licenses l ON l.license_id = rr.license_id
        JOIN devices d ON d.device_id = rr.device_id
    """
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    total_row = one(conn, f"SELECT COUNT(*) AS c {base_join}{where_sql}", tuple(params))
    rows = all_rows(
        conn,
        f"""SELECT rr.request_id, rr.license_id, rr.device_id, rr.reason, rr.status, rr.requested_at, rr.resolved_at,
                   l.customer_name, d.device_type, d.label
            {base_join}{where_sql}
            ORDER BY rr.requested_at DESC LIMIT ? OFFSET ?""",
        tuple(params) + (limit, offset),
    )
    return paginated([dict(r) for r in rows], total=int(total_row["c"]) if total_row else 0, limit=limit, offset=offset)


@router.post("/release-requests/{request_id}/approve")
def approve_release_request(
    request_id: str,
    req: AdminResolveReleaseRequest,
    settings: Annotated[BackendSettings, Depends(get_settings)],
    session: Annotated[dict, Depends(require_role("owner", "admin", "support"))],
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
        """
        UPDATE devices
        SET status='released', released_at=?, released_by=?, release_reason=?
        WHERE device_id=?
        """,
        (now, actor, req.reason or "approved_release_request", row["device_id"]),
    )
    conn.execute(
        "UPDATE release_requests SET status='approved', resolved_at=?, resolved_by=? WHERE request_id=?",
        (now, actor, request_id),
    )
    revoked = revoke_device_refresh_tokens(conn, row["device_id"], reason="release_request_approved")
    audit_log(conn, actor_type="admin", actor_id=actor, action="device.release.approve", target_type="device", target_id=row["device_id"], metadata={"request_id": request_id, "refresh_tokens_revoked": revoked})
    conn.commit()
    log_event("release_request.approved", admin_id=actor, request_id=request_id, device_id=row["device_id"], license_id=row["license_id"], refresh_tokens_revoked=revoked)
    return {"ok": True, "request_id": request_id, "device_id": row["device_id"], "status": "approved"}


@router.post("/release-requests/{request_id}/reject")
def reject_release_request(
    request_id: str,
    req: AdminResolveReleaseRequest,
    settings: Annotated[BackendSettings, Depends(get_settings)],
    session: Annotated[dict, Depends(require_role("owner", "admin", "support"))],
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
    audit_log(conn, actor_type="admin", actor_id=actor, action="device.release.reject", target_type="device", target_id=row["device_id"], metadata={"request_id": request_id, "reason": req.reason})
    conn.commit()
    log_event("release_request.rejected", admin_id=actor, request_id=request_id, device_id=row["device_id"], reason=req.reason)
    return {"ok": True, "request_id": request_id, "status": "rejected"}


@router.get("/audit-logs")
def list_audit_logs(
    settings: Annotated[BackendSettings, Depends(get_settings)],
    target_type: str = "",
    target_id: str = "",
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
    if target_type:
        where.append("target_type=?")
        params.append(target_type)
    if target_id:
        where.append("target_id=?")
        params.append(target_id)
    if action:
        where.append("action=?")
        params.append(action)
    if actor_id:
        where.append("actor_id=?")
        params.append(actor_id)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    total_row = one(conn, f"SELECT COUNT(*) AS c FROM audit_logs{where_sql}", tuple(params))
    rows = all_rows(
        conn,
        f"SELECT * FROM audit_logs{where_sql} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        tuple(params) + (limit, offset),
    )
    return paginated([dict(r) for r in rows], total=int(total_row["c"]) if total_row else 0, limit=limit, offset=offset)


@router.post("/news")
def publish_news(
    req: AdminPublishNewsRequest,
    settings: Annotated[BackendSettings, Depends(get_settings)],
    session: Annotated[dict, Depends(require_role("owner", "admin"))],
):
    conn = connect(settings.db_target)
    migrate(conn)
    news_id = "news_" + secrets.token_urlsafe(18)
    conn.execute(
        """
        INSERT INTO news(news_id, title, body, severity, audience, published_at, expires_at, is_active)
        VALUES(?,?,?,?,?,?,?,1)
        """,
        (news_id, req.title, req.body, req.severity, req.audience, iso(utcnow()), iso(req.expires_at) if req.expires_at else None),
    )
    audit_log(conn, actor_type="admin", actor_id=session["admin_id"], action="news.publish", target_type="news", target_id=news_id, metadata={"severity": req.severity, "audience": req.audience})
    conn.commit()
    log_event("news.published", admin_id=session["admin_id"], news_id=news_id, severity=req.severity, audience=req.audience, title=req.title)
    return {"ok": True, "news_id": news_id}


@router.post("/updates")
def publish_update(
    req: AdminPublishUpdateRequest,
    settings: Annotated[BackendSettings, Depends(get_settings)],
    session: Annotated[dict, Depends(require_role("owner", "admin"))],
):
    signature = req.signature
    if not signature:
        if not settings.ed25519_private_key_hex:
            raise HTTPException(status_code=400, detail="signature required when private key is not configured")
        signature = sign_update_manifest(
            settings.ed25519_private_key_hex,
            version=req.version,
            channel=req.channel,
            mandatory=req.mandatory,
            download_url=req.download_url,
            sha256=req.sha256,
        )
    conn = connect(settings.db_target)
    migrate(conn)
    update_id = "upd_" + secrets.token_urlsafe(18)
    conn.execute(
        """
        INSERT INTO update_manifests(update_id, version, channel, mandatory, download_url, sha256, signature, release_notes, is_active, published_at)
        VALUES(?,?,?,?,?,?,?,?,1,?)
        """,
        (update_id, req.version, req.channel, int(req.mandatory), req.download_url, req.sha256, signature, req.release_notes, iso(utcnow())),
    )
    audit_log(conn, actor_type="admin", actor_id=session["admin_id"], action="update.publish", target_type="update_manifest", target_id=update_id, metadata={"version": req.version, "channel": req.channel, "mandatory": req.mandatory})
    conn.commit()
    log_event("update.published", admin_id=session["admin_id"], update_id=update_id, version=req.version, channel=req.channel, mandatory=req.mandatory)
    return {"ok": True, "update_id": update_id, "signature": signature}
