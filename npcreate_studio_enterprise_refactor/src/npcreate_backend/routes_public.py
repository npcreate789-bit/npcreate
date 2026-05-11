from __future__ import annotations

import json
import secrets
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from .auth import get_activation_claims, get_settings, rate_limit_activation, rate_limit_refresh, require_app_api_key
from .billing import count_bound_devices, get_policy_for_device, process_payment_webhook
from .db import all_rows, connect, migrate, one
from .models import (
    ActivateLicenseRequest,
    ActivateLicenseResponse,
    HeartbeatRequest,
    RefreshTokenRequest,
    RefreshTokenResponse,
    ReleaseRequestCreate,
)
from .payment_providers import get_adapter
from .refresh_tokens import issue_refresh_token, rotate_refresh_token
from .security import (
    create_token,
    hash_device_fingerprint,
    hash_license_key,
    iso,
    parse_dt,
    sanitize_metadata,
    utcnow,
)
from .settings import BackendSettings

router = APIRouter(prefix="/api/v1")


@router.post("/licenses/activate", response_model=ActivateLicenseResponse)
def activate_license(
    req: ActivateLicenseRequest,
    settings: Annotated[BackendSettings, Depends(get_settings)],
    _: Annotated[None, Depends(rate_limit_activation)],
):
    conn = connect(settings.db_target)
    migrate(conn)
    key_hash = hash_license_key(req.license_key, settings.key_pepper)
    lic = one(conn, "SELECT * FROM licenses WHERE key_hash=?", (key_hash,))
    if not lic:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="license key not found")
    if lic["status"] != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"license is {lic['status']}")
    expires_at = parse_dt(lic["expires_at"])
    if expires_at is None or expires_at < utcnow():
        conn.execute("UPDATE licenses SET status='expired', updated_at=? WHERE license_id=?", (iso(utcnow()), lic["license_id"]))
        conn.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="license expired")

    policy = get_policy_for_device(conn, lic["license_id"], req.device_type)
    if int(policy["fingerprint_required"]) and not req.device_fingerprint:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="device fingerprint required")
    try:
        fingerprint_hash = hash_device_fingerprint(req.device_fingerprint, settings.key_pepper)
        device_metadata = sanitize_metadata(req.device_metadata)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    existing = one(
        conn,
        """
        SELECT * FROM devices
        WHERE license_id=? AND device_type=? AND fingerprint_hash=? AND status='bound'
        """,
        (lic["license_id"], req.device_type, fingerprint_hash),
    )
    if existing:
        device_id = existing["device_id"]
        conn.execute("UPDATE devices SET last_seen_at=?, label=?, metadata_json=? WHERE device_id=?", (
            iso(utcnow()), req.device_label, json.dumps(device_metadata, ensure_ascii=False), device_id
        ))
    else:
        bound_count = count_bound_devices(conn, lic["license_id"], req.device_type)
        if bound_count >= int(policy["max_devices"]):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="device limit reached; ask admin to release an old device first",
            )
        device_id = "dev_" + secrets.token_urlsafe(18)
        conn.execute(
            """
            INSERT INTO devices(device_id, license_id, device_type, fingerprint_hash, label, metadata_json, status, bound_at, last_seen_at)
            VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                device_id,
                lic["license_id"],
                req.device_type,
                fingerprint_hash,
                req.device_label,
                json.dumps(device_metadata, ensure_ascii=False),
                "bound",
                iso(utcnow()),
                iso(utcnow()),
            ),
        )
    access_token = create_token(
        settings.key_pepper,
        subject=lic["license_id"],
        claims={"license_id": lic["license_id"], "device_id": device_id, "device_type": req.device_type},
        ttl=timedelta(minutes=settings.activation_access_ttl_minutes),
    )
    _, refresh_raw = issue_refresh_token(
        conn,
        license_id=lic["license_id"],
        device_id=device_id,
        ttl_days=settings.activation_token_ttl_days,
    )
    conn.commit()
    return ActivateLicenseResponse(
        license_id=lic["license_id"],
        status=lic["status"],
        expires_at=expires_at,
        device_id=device_id,
        activation_token=access_token,
        refresh_token=refresh_raw,
        features=json.loads(lic["features_json"]),
        message="activated",
    )


@router.post("/auth/refresh", response_model=RefreshTokenResponse, dependencies=[Depends(rate_limit_refresh)])
def refresh_activation_token(req: RefreshTokenRequest, settings: Annotated[BackendSettings, Depends(get_settings)]):
    conn = connect(settings.db_target)
    migrate(conn)
    rotated = rotate_refresh_token(conn, presented_token=req.refresh_token, ttl_days=settings.activation_token_ttl_days)
    # Determine new access token expiry from settings.
    access_expires = utcnow() + timedelta(minutes=settings.activation_access_ttl_minutes)
    access_token = create_token(
        settings.key_pepper,
        subject=rotated["license_id"],
        claims={"license_id": rotated["license_id"], "device_id": rotated["device_id"]},
        ttl=timedelta(minutes=settings.activation_access_ttl_minutes),
    )
    conn.commit()
    return RefreshTokenResponse(
        access_token=access_token,
        refresh_token=rotated["refresh_token"],
        expires_at=access_expires,
    )


@router.post("/licenses/heartbeat")
def heartbeat(
    req: HeartbeatRequest,
    settings: Annotated[BackendSettings, Depends(get_settings)],
    claims: Annotated[dict, Depends(get_activation_claims)],
):
    conn = connect(settings.db_target)
    migrate(conn)
    lic = one(conn, "SELECT * FROM licenses WHERE license_id=?", (claims["license_id"],))
    dev = one(conn, "SELECT * FROM devices WHERE device_id=? AND status='bound'", (claims["device_id"],))
    expires_at = parse_dt(lic["expires_at"]) if lic else None
    if not lic or not dev or lic["status"] != "active" or expires_at is None or expires_at < utcnow():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="activation not valid")
    conn.execute("UPDATE devices SET last_seen_at=? WHERE device_id=?", (iso(utcnow()), claims["device_id"]))
    conn.commit()
    return {"ok": True, "license_id": lic["license_id"], "expires_at": lic["expires_at"], "server_time": iso(utcnow())}


@router.get("/news")
def list_news(claims: Annotated[dict, Depends(get_activation_claims)], settings: Annotated[BackendSettings, Depends(get_settings)]):
    conn = connect(settings.db_target)
    migrate(conn)
    rows = all_rows(
        conn,
        """
        SELECT news_id, title, body, severity, published_at
        FROM news
        WHERE is_active=1 AND (expires_at IS NULL OR expires_at > ?)
        ORDER BY published_at DESC
        LIMIT 20
        """,
        (iso(utcnow()),),
    )
    return {"items": [dict(r) for r in rows]}


@router.post("/devices/release-request")
def request_release(
    req: ReleaseRequestCreate,
    settings: Annotated[BackendSettings, Depends(get_settings)],
    claims: Annotated[dict, Depends(get_activation_claims)],
):
    conn = connect(settings.db_target)
    migrate(conn)
    request_id = "rel_" + secrets.token_urlsafe(18)
    conn.execute(
        """
        INSERT INTO release_requests(request_id, license_id, device_id, reason, status, requested_at)
        VALUES(?,?,?,?,?,?)
        """,
        (request_id, claims["license_id"], claims["device_id"], req.reason, "pending", iso(utcnow())),
    )
    conn.commit()
    return {"ok": True, "request_id": request_id, "message": "admin will review release request"}


@router.get("/updates/latest")
def latest_update(channel: str = "stable", settings: BackendSettings = Depends(get_settings)):
    conn = connect(settings.db_target)
    migrate(conn)
    row = one(
        conn,
        """
        SELECT version, channel, mandatory, download_url, sha256, signature, release_notes
        FROM update_manifests
        WHERE channel=? AND is_active=1
        ORDER BY published_at DESC
        LIMIT 1
        """,
        (channel,),
    )
    if not row:
        return Response(status_code=204)
    return {
        "version": row["version"],
        "channel": row["channel"],
        "mandatory": bool(row["mandatory"]),
        "download_url": row["download_url"],
        "sha256": row["sha256"],
        "signature": row["signature"],
        "release_notes": row["release_notes"],
    }


@router.post("/webhooks/payments/{provider}")
async def payment_webhook(provider: str, request: Request, settings: BackendSettings = Depends(get_settings)):
    """Receive real payment gateway webhooks via provider adapters.

    Each adapter verifies the provider signature and normalizes the event into
    the existing billing engine format. Failed signature events are recorded but
    never renew a license.
    """
    payload = await request.body()
    if len(payload) > 512 * 1024:
        raise HTTPException(status_code=413, detail="payload too large")
    adapter = get_adapter(provider)
    signature_valid = await adapter.verify(request, payload, settings)
    normalized = adapter.normalize(payload)
    normalized_payload = json.dumps(normalized, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    conn = connect(settings.db_target)
    migrate(conn)
    result = process_payment_webhook(
        conn,
        settings=settings,
        provider=adapter.provider,
        payload=normalized_payload,
        signature_valid=signature_valid,
        ip_address=request.client.host if request.client else "",
    )
    conn.commit()
    return result



@router.post("/error-reports", dependencies=[Depends(require_app_api_key)])
async def submit_error_report(request: Request, settings: BackendSettings = Depends(get_settings)):
    body = await request.json()
    title = str(body.get("title") or "Client error")[:180]
    message = str(body.get("message") or "")[:5000]
    traceback_text = str(body.get("traceback") or "")[:12000]
    metadata = sanitize_metadata(body.get("metadata") if isinstance(body.get("metadata"), dict) else {})
    report_id = "err_" + secrets.token_urlsafe(18)
    conn = connect(settings.db_target)
    migrate(conn)
    conn.execute(
        """
        INSERT INTO error_reports(report_id, license_id, device_id, severity, title, message, traceback, metadata_json, app_version, created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?)
        """,
        (
            report_id,
            str(body.get("license_id") or "")[:80],
            str(body.get("device_id") or "")[:80],
            str(body.get("severity") or "error")[:20],
            title,
            message,
            traceback_text,
            json.dumps(metadata, ensure_ascii=False),
            str(body.get("app_version") or "")[:40],
            iso(utcnow()),
        ),
    )
    conn.commit()
    return {"ok": True, "report_id": report_id}
