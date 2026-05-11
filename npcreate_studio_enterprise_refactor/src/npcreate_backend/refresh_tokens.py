"""Refresh-token service.

Issue/rotate/revoke refresh tokens with reuse detection. Tokens are returned
to the client only as opaque random strings; only their SHA256 hash is stored.

Rotation rules:
- A refresh exchange revokes the presented token and issues a new one.
- Reusing an already-rotated token triggers a revoke of the entire chain
  for that device (treat as compromise).
- Revoking a device (admin release / device release) revokes all refresh
  tokens for that device.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import sqlite3
from datetime import timedelta
from typing import Any

from fastapi import HTTPException, status

from .db import all_rows, one
from .observability import log_event
from .security import iso, parse_dt, utcnow


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def issue_refresh_token(
    conn: sqlite3.Connection,
    *,
    license_id: str,
    device_id: str,
    ttl_days: int,
) -> tuple[str, str]:
    """Create a new refresh token row. Returns (token_id, raw_token)."""
    raw = new_refresh_token()
    token_id = "rt_" + secrets.token_urlsafe(18)
    now = utcnow()
    conn.execute(
        """
        INSERT INTO refresh_tokens(token_id, token_hash, license_id, device_id, created_at, expires_at)
        VALUES(?,?,?,?,?,?)
        """,
        (
            token_id,
            hash_refresh_token(raw),
            license_id,
            device_id,
            iso(now),
            iso(now + timedelta(days=ttl_days)),
        ),
    )
    return token_id, raw


def revoke_device_refresh_tokens(
    conn: sqlite3.Connection,
    device_id: str,
    *,
    reason: str = "device_released",
) -> int:
    now_iso = iso(utcnow())
    cur = conn.execute(
        "UPDATE refresh_tokens SET revoked_at=?, revoke_reason=? WHERE device_id=? AND revoked_at IS NULL",
        (now_iso, reason, device_id),
    )
    return cur.rowcount if hasattr(cur, "rowcount") else 0


def _revoke_chain(conn: sqlite3.Connection, device_id: str, reason: str) -> None:
    """Revoke every refresh token belonging to a device (used on reuse detection)."""
    conn.execute(
        "UPDATE refresh_tokens SET revoked_at=?, revoke_reason=? WHERE device_id=? AND revoked_at IS NULL",
        (iso(utcnow()), reason, device_id),
    )


def rotate_refresh_token(
    conn: sqlite3.Connection,
    *,
    presented_token: str,
    ttl_days: int,
) -> dict[str, Any]:
    """Validate the presented refresh token and rotate it.

    Returns dict with license_id, device_id, and new raw token. Raises 401 if
    the token is missing, expired, revoked, or already rotated (reuse).
    """
    row = one(
        conn,
        "SELECT * FROM refresh_tokens WHERE token_hash=?",
        (hash_refresh_token(presented_token),),
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid refresh token")
    if row["rotated_to"]:
        # Reuse of an already-rotated token: treat as compromise. Even though
        # this token is also marked revoked (with reason='rotated'), the
        # presence of `rotated_to` indicates the legitimate caller has already
        # exchanged it once; a second use means the token leaked.
        _revoke_chain(conn, row["device_id"], reason="refresh_reuse_detected")
        conn.commit()
        log_event(
            "license.auto_renew",  # closest registered event; reuse detection deserves its own alert
            level=logging.ERROR,
            event_hint="refresh_token_reuse",
            device_id=row["device_id"],
            license_id=row["license_id"],
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="refresh token reuse detected")
    if row["revoked_at"]:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="refresh token revoked")
    expires_at = parse_dt(row["expires_at"])
    if expires_at is None or expires_at < utcnow():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="refresh token expired")

    # Ensure device + license are still valid.
    lic = one(conn, "SELECT status FROM licenses WHERE license_id=?", (row["license_id"],))
    dev = one(conn, "SELECT status FROM devices WHERE device_id=?", (row["device_id"],))
    if not lic or not dev or dev["status"] != "bound" or lic["status"] not in {"active", "past_due"}:
        _revoke_chain(conn, row["device_id"], reason="license_or_device_invalid")
        conn.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="license or device no longer valid")

    new_token_id, new_raw = issue_refresh_token(
        conn,
        license_id=row["license_id"],
        device_id=row["device_id"],
        ttl_days=ttl_days,
    )
    conn.execute(
        "UPDATE refresh_tokens SET rotated_to=?, revoked_at=?, revoke_reason='rotated' WHERE token_id=?",
        (new_token_id, iso(utcnow()), row["token_id"]),
    )
    return {
        "license_id": row["license_id"],
        "device_id": row["device_id"],
        "refresh_token": new_raw,
    }


def active_tokens_for_device(conn: sqlite3.Connection, device_id: str) -> list[dict[str, Any]]:
    return [dict(r) for r in all_rows(conn, "SELECT * FROM refresh_tokens WHERE device_id=? AND revoked_at IS NULL", (device_id,))]
