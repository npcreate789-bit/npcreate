from __future__ import annotations

import json
import logging
import secrets
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException, status

from .db import all_rows, one
from .observability import log_event
from .security import iso, parse_dt, payload_hash, sanitize_metadata, utcnow
from .settings import BackendSettings

SUCCESS_EVENTS = {"payment.succeeded", "charge.succeeded", "invoice.paid", "subscription.payment_succeeded"}
FAILED_EVENTS = {"payment.failed", "charge.failed", "invoice.payment_failed", "subscription.cancelled"}


def audit_log(
    conn: sqlite3.Connection,
    *,
    actor_type: str,
    actor_id: str,
    action: str,
    target_type: str,
    target_id: str,
    ip_address: str = "",
    metadata: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO audit_logs(audit_id, actor_type, actor_id, action, target_type, target_id, ip_address, metadata_json, created_at)
        VALUES(?,?,?,?,?,?,?,?,?)
        """,
        (
            "aud_" + secrets.token_urlsafe(18),
            actor_type,
            actor_id,
            action,
            target_type,
            target_id,
            ip_address,
            json.dumps(sanitize_metadata(metadata or {}), ensure_ascii=False),
            iso(utcnow()),
        ),
    )


def default_device_policies(max_pc: int, max_phone: int) -> list[dict[str, Any]]:
    return [
        {
            "device_type": "pc",
            "max_devices": max_pc,
            "binding_mode": "admin_release_only",
            "fingerprint_required": True,
            "metadata": {},
        },
        {
            "device_type": "phone",
            "max_devices": max_phone,
            "binding_mode": "admin_release_only",
            "fingerprint_required": True,
            "metadata": {},
        },
    ]


def upsert_device_policies(conn: sqlite3.Connection, license_id: str, policies: list[dict[str, Any]], *, actor: str) -> None:
    lic = one(conn, "SELECT license_id FROM licenses WHERE license_id=?", (license_id,))
    if not lic:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="license not found")
    now = iso(utcnow())
    for p in policies:
        metadata = sanitize_metadata(p.get("metadata", {}))
        existing = one(conn, "SELECT policy_id FROM device_policies WHERE license_id=? AND device_type=?", (license_id, p["device_type"]))
        if existing:
            conn.execute(
                """
                UPDATE device_policies
                SET max_devices=?, binding_mode=?, fingerprint_required=?, metadata_json=?, updated_at=?
                WHERE policy_id=?
                """,
                (
                    int(p["max_devices"]),
                    p.get("binding_mode", "admin_release_only"),
                    1 if p.get("fingerprint_required", True) else 0,
                    json.dumps(metadata, ensure_ascii=False),
                    now,
                    existing["policy_id"],
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO device_policies(policy_id, license_id, device_type, max_devices, binding_mode, fingerprint_required, metadata_json, created_at, updated_at)
                VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (
                    "pol_" + secrets.token_urlsafe(18),
                    license_id,
                    p["device_type"],
                    int(p["max_devices"]),
                    p.get("binding_mode", "admin_release_only"),
                    1 if p.get("fingerprint_required", True) else 0,
                    json.dumps(metadata, ensure_ascii=False),
                    now,
                    now,
                ),
            )
    audit_log(conn, actor_type="admin", actor_id=actor, action="device_policy.upsert", target_type="license", target_id=license_id, metadata={"policies": policies})


def get_policy_for_device(conn: sqlite3.Connection, license_id: str, device_type: str) -> sqlite3.Row:
    policy = one(conn, "SELECT * FROM device_policies WHERE license_id=? AND device_type=?", (license_id, device_type))
    if not policy:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"device type '{device_type}' is not allowed by this license policy")
    return policy


def count_bound_devices(conn: sqlite3.Connection, license_id: str, device_type: str) -> int:
    row = one(conn, "SELECT COUNT(*) AS c FROM devices WHERE license_id=? AND device_type=? AND status='bound'", (license_id, device_type))
    return int(row["c"] if row else 0)


def create_subscription(
    conn: sqlite3.Connection,
    *,
    license_id: str,
    provider: str,
    provider_customer_id: str,
    provider_subscription_id: str,
    amount_satangs: int,
    currency: str,
    next_renewal_at: datetime | None,
    actor_id: str = "admin",
) -> str:
    if not one(conn, "SELECT license_id FROM licenses WHERE license_id=?", (license_id,)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="license not found")
    subscription_id = "sub_" + secrets.token_urlsafe(18)
    now = iso(utcnow())
    conn.execute(
        """
        INSERT INTO subscriptions(subscription_id, license_id, provider, provider_customer_id, provider_subscription_id, status,
                                  billing_cycle, amount_satangs, currency, next_renewal_at, created_at, updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            subscription_id,
            license_id,
            provider,
            provider_customer_id,
            provider_subscription_id,
            "active",
            "monthly",
            int(amount_satangs),
            currency.upper(),
            iso(next_renewal_at) if next_renewal_at else None,
            now,
            now,
        ),
    )
    audit_log(conn, actor_type="admin", actor_id=actor_id, action="subscription.create", target_type="license", target_id=license_id, metadata={"provider": provider, "provider_subscription_id": provider_subscription_id})
    return subscription_id


def _reject_event(conn: sqlite3.Connection, event_id: str, message: str) -> None:
    conn.execute("UPDATE payment_events SET processing_status='rejected', error=?, processed_at=? WHERE event_id=?", (message, iso(utcnow()), event_id))


def _normalize_payment_payload(body: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    external_event_id = str(body.get("id") or body.get("event_id") or "").strip()
    event_type = str(body.get("type") or body.get("event_type") or "").strip()
    data = body.get("data") or {}
    if not external_event_id or not event_type or not isinstance(data, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="missing event id/type/data")
    return external_event_id, event_type, data


def _validate_amount_and_currency(sub: sqlite3.Row | None, amount_satangs: int, currency: str) -> None:
    if not sub:
        return
    expected_amount = int(sub["amount_satangs"] or 0)
    expected_currency = str(sub["currency"] or "THB").upper()
    if expected_amount > 0 and amount_satangs > 0 and amount_satangs != expected_amount:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="payment amount does not match subscription")
    if currency.upper() != expected_currency:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="payment currency does not match subscription")


def process_payment_webhook(
    conn: sqlite3.Connection,
    *,
    settings: BackendSettings,
    provider: str,
    payload: bytes,
    signature_valid: bool,
    ip_address: str = "",
) -> dict[str, Any]:
    """Process a normalized payment webhook safely.

    Hardened behavior:
    - invalid signatures are recorded but never renew a license
    - success payments must map through a known subscription by default
    - provider payment IDs and provider event IDs are idempotent
    - amount/currency must match subscription when configured
    - client-provided license_id is ignored unless explicitly enabled for dev
    """
    payload_sha = payload_hash(payload)
    try:
        body = json.loads(payload.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid json payload") from exc

    external_event_id, event_type, data = _normalize_payment_payload(body)
    event_id = "evt_" + secrets.token_urlsafe(18)
    try:
        conn.execute(
            """
            INSERT INTO payment_events(event_id, provider, external_event_id, event_type, signature_valid, payload_hash, processing_status, received_at)
            VALUES(?,?,?,?,?,?,?,?)
            """,
            (event_id, provider, external_event_id, event_type, 1 if signature_valid else 0, payload_sha, "received", iso(utcnow())),
        )
    except sqlite3.IntegrityError:
        existing = one(conn, "SELECT event_id, processing_status FROM payment_events WHERE provider=? AND external_event_id=?", (provider, external_event_id))
        return {"ok": True, "duplicate": True, "event_id": existing["event_id"], "status": existing["processing_status"]}

    if not signature_valid:
        _reject_event(conn, event_id, "invalid signature")
        audit_log(conn, actor_type="webhook", actor_id=provider, action="payment.rejected_signature", target_type="payment_event", target_id=event_id, ip_address=ip_address)
        log_event(
            "payment.signature_rejected",
            level=logging.ERROR,
            provider=provider,
            event_id=event_id,
            external_event_id=external_event_id,
            ip=ip_address,
        )
        return {"ok": False, "event_id": event_id, "status": "rejected", "reason": "invalid signature"}

    provider_subscription_id = str(data.get("provider_subscription_id") or data.get("subscription_id") or "").strip()

    if event_type in FAILED_EVENTS:
        if provider_subscription_id:
            conn.execute(
                "UPDATE subscriptions SET status='past_due', updated_at=? WHERE provider=? AND provider_subscription_id=?",
                (iso(utcnow()), provider, provider_subscription_id),
            )
        conn.execute("UPDATE payment_events SET processing_status='processed', processed_at=? WHERE event_id=?", (iso(utcnow()), event_id))
        audit_log(conn, actor_type="webhook", actor_id=provider, action="payment.failed", target_type="payment_event", target_id=event_id, ip_address=ip_address)
        log_event(
            "payment.failed",
            level=logging.WARNING,
            provider=provider,
            event_id=event_id,
            external_event_id=external_event_id,
            provider_subscription_id=provider_subscription_id,
            ip=ip_address,
        )
        return {"ok": True, "event_id": event_id, "status": "processed_failed_payment"}

    if event_type not in SUCCESS_EVENTS:
        conn.execute("UPDATE payment_events SET processing_status='ignored', processed_at=? WHERE event_id=?", (iso(utcnow()), event_id))
        return {"ok": True, "event_id": event_id, "status": "ignored"}

    provider_payment_id = str(data.get("provider_payment_id") or data.get("payment_id") or data.get("charge_id") or "").strip()
    if not provider_payment_id:
        _reject_event(conn, event_id, "missing payment id")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="missing provider payment id")

    sub = None
    if provider_subscription_id:
        sub = one(conn, "SELECT * FROM subscriptions WHERE provider=? AND provider_subscription_id=?", (provider, provider_subscription_id))
    if not sub and not settings.allow_direct_license_payment_mapping:
        _reject_event(conn, event_id, "payment not mapped to a known subscription")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="payment not mapped to a known subscription")

    license_id = sub["license_id"] if sub else str(data.get("license_id") or "").strip()
    if not license_id:
        _reject_event(conn, event_id, "cannot map payment to license")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="cannot map payment to license")

    lic = one(conn, "SELECT * FROM licenses WHERE license_id=?", (license_id,))
    if not lic:
        _reject_event(conn, event_id, "license not found")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="license not found")

    amount_satangs = int(data.get("amount_satangs") or data.get("amount") or (sub["amount_satangs"] if sub else 0) or 0)
    currency = str(data.get("currency") or (sub["currency"] if sub else "THB")).upper()[:3]
    _validate_amount_and_currency(sub, amount_satangs, currency)
    paid_at = parse_dt(data.get("paid_at")) or utcnow()
    payment_id = "pay_" + secrets.token_urlsafe(18)

    try:
        conn.execute(
            """
            INSERT INTO payments(payment_id, license_id, subscription_id, provider, provider_payment_id, provider_subscription_id,
                                 status, amount_satangs, currency, paid_at, raw_payload_hash, created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                payment_id,
                license_id,
                sub["subscription_id"] if sub else None,
                provider,
                provider_payment_id,
                provider_subscription_id,
                "paid",
                amount_satangs,
                currency,
                iso(paid_at),
                payload_sha,
                iso(utcnow()),
            ),
        )
    except sqlite3.IntegrityError:
        conn.execute("UPDATE payment_events SET processing_status='duplicate_payment', processed_at=? WHERE event_id=?", (iso(utcnow()), event_id))
        return {"ok": True, "event_id": event_id, "status": "duplicate_payment"}

    current_expiry = parse_dt(lic["expires_at"]) or utcnow()
    base = max(current_expiry, utcnow())
    new_expiry = base + timedelta(days=settings.payment_renewal_days)
    conn.execute(
        "UPDATE licenses SET expires_at=?, status='active', updated_at=? WHERE license_id=?",
        (iso(new_expiry), iso(utcnow()), license_id),
    )
    if sub:
        conn.execute(
            "UPDATE subscriptions SET status='active', last_payment_at=?, next_renewal_at=?, updated_at=? WHERE subscription_id=?",
            (iso(paid_at), iso(new_expiry), iso(utcnow()), sub["subscription_id"]),
        )
    conn.execute("UPDATE payment_events SET processing_status='processed', processed_at=? WHERE event_id=?", (iso(utcnow()), event_id))
    audit_log(
        conn,
        actor_type="webhook",
        actor_id=provider,
        action="license.auto_renew",
        target_type="license",
        target_id=license_id,
        ip_address=ip_address,
        metadata={"payment_id": payment_id, "new_expiry": iso(new_expiry), "event_id": external_event_id},
    )
    log_event(
        "license.auto_renew",
        provider=provider,
        license_id=license_id,
        payment_id=payment_id,
        amount_satangs=amount_satangs,
        currency=currency,
        new_expiry=iso(new_expiry),
    )
    return {"ok": True, "event_id": event_id, "license_id": license_id, "payment_id": payment_id, "expires_at": iso(new_expiry)}


def list_device_policies(conn: sqlite3.Connection, license_id: str) -> list[dict[str, Any]]:
    rows = all_rows(conn, "SELECT * FROM device_policies WHERE license_id=? ORDER BY device_type", (license_id,))
    return [dict(r) | {"metadata": json.loads(r["metadata_json"] or "{}")} for r in rows]
