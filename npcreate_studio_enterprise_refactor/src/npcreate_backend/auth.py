from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Annotated, Any

from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .admin_security import hash_session_token
from .db import connect, migrate, one
from .security import constant_time_equal, parse_dt, utcnow, verify_token
from .settings import BackendSettings

CSRF_HEADER = "X-CSRF-Token"
CSRF_FORM_FIELD = "_csrf"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

VALID_ROLES = ("owner", "admin", "support", "billing", "viewer")
LEGACY_ROLE = "owner"  # legacy admin token gets full access for CLI-only flows

bearer = HTTPBearer(auto_error=False)
_RATE_BUCKETS: dict[str, deque[float]] = defaultdict(deque)


def get_settings() -> BackendSettings:
    return BackendSettings()


def _client_ip(request: Request, settings: BackendSettings) -> str:
    if settings.trusted_proxy_header:
        forwarded = request.headers.get(settings.trusted_proxy_header)
        if forwarded:
            return forwarded.split(",", 1)[0].strip()[:80]
    return request.client.host if request.client else "unknown"


def _rate_limit(key: str, limit: int) -> None:
    now = time.time()
    bucket = _RATE_BUCKETS[key]
    while bucket and bucket[0] < now - 60:
        bucket.popleft()
    if len(bucket) >= limit:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="too many attempts")
    bucket.append(now)


def rate_limit_activation(request: Request, settings: Annotated[BackendSettings, Depends(get_settings)]) -> None:
    _rate_limit(f"activation:{_client_ip(request, settings)}", settings.activation_rate_limit_per_minute)


def rate_limit_admin_login(request: Request, settings: Annotated[BackendSettings, Depends(get_settings)]) -> None:
    _rate_limit(f"admin_login:{_client_ip(request, settings)}", settings.admin_login_rate_limit_per_minute)


def get_admin_session(
    request: Request,
    settings: Annotated[BackendSettings, Depends(get_settings)],
    session_cookie: Annotated[str | None, Cookie(alias="npc_admin_session")] = None,
) -> dict[str, Any] | None:
    cookie_name = settings.admin_session_cookie_name
    token = request.cookies.get(cookie_name) or session_cookie
    if not token:
        return None
    conn = connect(settings.db_target)
    migrate(conn)
    row = one(
        conn,
        """
        SELECT s.*, u.email, u.display_name, u.role, u.status AS user_status
        FROM admin_sessions s
        JOIN admin_users u ON u.admin_id=s.admin_id
        WHERE s.session_hash=? AND s.revoked_at IS NULL
        """,
        (hash_session_token(token),),
    )
    if not row:
        return None
    if parse_dt(row["expires_at"]) < utcnow() or row["user_status"] != "active":
        return None
    return dict(row)


def require_admin_session(session: Annotated[dict[str, Any] | None, Depends(get_admin_session)]) -> dict[str, Any]:
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="admin login required")
    return session


def require_admin(
    request: Request,
    settings: Annotated[BackendSettings, Depends(get_settings)],
    x_admin_token: Annotated[str | None, Header(alias="X-Admin-Token")] = None,
) -> dict[str, Any]:
    # New production path: secure cookie session created after password + MFA.
    session = get_admin_session(request, settings)
    if session:
        return session
    # Legacy token remains optional only for CLI/backfill in controlled environments.
    if settings.allow_legacy_admin_token and x_admin_token and constant_time_equal(x_admin_token, settings.admin_token):
        return {"admin_id": "legacy-token", "email": "legacy-token", "csrf_token": "", "role": LEGACY_ROLE}
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="admin login required")


async def _extract_csrf_from_form(request: Request) -> str | None:
    content_type = request.headers.get("content-type", "")
    if not content_type.startswith(("application/x-www-form-urlencoded", "multipart/form-data")):
        return None
    try:
        form = await request.form()
    except Exception:
        return None
    value = form.get(CSRF_FORM_FIELD)
    return str(value) if value else None


async def verify_admin_csrf(
    request: Request,
    session: Annotated[dict[str, Any], Depends(require_admin)],
    x_csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict[str, Any]:
    """Verify CSRF for state-changing admin requests.

    Skipped for safe HTTP methods. Legacy admin token (CLI) bypasses CSRF since
    it is not vulnerable to browser-based CSRF (no cookie auth path).
    """
    if request.method in SAFE_METHODS:
        return session
    if session.get("admin_id") == "legacy-token":
        return session
    expected = session.get("csrf_token") or ""
    if not expected:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="csrf token missing on session")
    provided = x_csrf_token or await _extract_csrf_from_form(request)
    if not provided or not constant_time_equal(provided, expected):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid csrf token")
    return session


def require_app_api_key(
    settings: Annotated[BackendSettings, Depends(get_settings)],
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> None:
    if settings.app_api_key.startswith("CHANGE_ME"):
        return
    if not x_api_key or not constant_time_equal(x_api_key, settings.app_api_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid api key")


def require_role(*allowed: str):
    """Return a dependency that allows only the listed admin roles.

    Used after verify_admin_csrf so CSRF + auth are already enforced.
    """
    if not allowed:
        raise ValueError("require_role requires at least one allowed role")
    for role in allowed:
        if role not in VALID_ROLES:
            raise ValueError(f"unknown role: {role}")

    async def _dep(
        session: Annotated[dict[str, Any], Depends(verify_admin_csrf)],
    ) -> dict[str, Any]:
        role = session.get("role") or "admin"
        if role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"role '{role}' not permitted for this action",
            )
        return session

    return _dep


def get_activation_claims(
    settings: Annotated[BackendSettings, Depends(get_settings)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> dict:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="bearer token required")
    try:
        return verify_token(settings.key_pepper, credentials.credentials)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
