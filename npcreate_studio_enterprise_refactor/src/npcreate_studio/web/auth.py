from __future__ import annotations

from collections.abc import Callable
from ipaddress import ip_address

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from ..core.security import constant_time_equal, generate_token

SAFE_PATHS = {"/", "/api/health"}


def is_loopback_host(host: str | None) -> bool:
    if not host:
        return False
    host = host.split(":", 1)[0]
    if host in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


class LocalTokenAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, token: str | None = None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.token = token or generate_token()

    async def dispatch(self, request: Request, call_next: Callable):  # type: ignore[no-untyped-def]
        client_host = request.client.host if request.client else None
        if not is_loopback_host(client_host):
            return Response("forbidden", status_code=403)
        if request.url.path in SAFE_PATHS or request.url.path.startswith("/static/"):
            return await call_next(request)
        supplied = request.headers.get("x-npcreate-token") or request.query_params.get("token")
        if not supplied or not constant_time_equal(supplied, self.token):
            return Response("unauthorized", status_code=401)
        return await call_next(request)
