from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from datetime import timedelta

try:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError
except Exception:  # pragma: no cover
    PasswordHasher = None  # type: ignore[assignment]
    VerifyMismatchError = Exception  # type: ignore[assignment]

from .security import iso, utcnow


def hash_password(password: str) -> str:
    if PasswordHasher is None:  # pragma: no cover
        raise RuntimeError("argon2-cffi is required for admin password hashing")
    return PasswordHasher().hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    if PasswordHasher is None:  # pragma: no cover
        raise RuntimeError("argon2-cffi is required for admin password hashing")
    try:
        return PasswordHasher().verify(password_hash, password)
    except VerifyMismatchError:
        return False


def new_mfa_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _totp_at(secret_b32: str, timestep: int) -> str:
    padded = secret_b32.upper() + "=" * ((8 - len(secret_b32) % 8) % 8)
    key = base64.b32decode(padded)
    msg = struct.pack(">Q", timestep)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return f"{code % 1_000_000:06d}"


def verify_totp(secret_b32: str, code: str, *, now: int | None = None, window: int = 1) -> bool:
    if not code or not code.isdigit() or len(code) != 6:
        return False
    base = int((now or time.time()) // 30)
    for step in range(base - window, base + window + 1):
        if hmac.compare_digest(_totp_at(secret_b32, step), code):
            return True
    return False


def new_session_token() -> str:
    return secrets.token_urlsafe(48)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def session_expiry(minutes: int) -> str:
    return iso(utcnow() + timedelta(minutes=minutes))


def csrf_token() -> str:
    return secrets.token_urlsafe(32)


def otpauth_uri(*, issuer: str, email: str, secret: str) -> str:
    label = f"{issuer}:{email}"
    return f"otpauth://totp/{label}?secret={secret}&issuer={issuer}&algorithm=SHA1&digits=6&period=30"
