from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .db import connect, migrate
from .jobs import billing_job_loop
from .observability import configure_logging
from .routes_admin import router as admin_router
from .routes_auth import router as auth_router
from .routes_dashboard import router as dashboard_router
from .routes_public import router as public_router
from .settings import BackendSettings


def create_app() -> FastAPI:
    settings = BackendSettings()
    configure_logging(settings.env)
    if settings.env == "production":
        weak = [
            name for name, value in {
                "NPCREATE_BACKEND_ADMIN_TOKEN": settings.admin_token,
                "NPCREATE_BACKEND_APP_API_KEY": settings.app_api_key,
                "NPCREATE_BACKEND_KEY_PEPPER": settings.key_pepper,
                "NPCREATE_BACKEND_PAYMENT_WEBHOOK_SECRET": settings.payment_webhook_secret,
            }.items()
            if value.startswith("CHANGE_ME") or len(value) < 24
        ]
        if weak:
            raise RuntimeError(f"weak production backend secret(s): {', '.join(weak)}")
    with connect(settings.db_target) as conn:
        migrate(conn)
    app = FastAPI(title="NP Create License Backend", version="2.4.0", docs_url=None if settings.env == "production" else "/docs")
    app.include_router(public_router)
    app.include_router(auth_router)
    app.include_router(dashboard_router)
    app.include_router(admin_router)

    @app.on_event("startup")
    async def _start_background_jobs() -> None:
        if settings.billing_job_enabled:
            import asyncio
            asyncio.create_task(billing_job_loop(settings))

    @app.get("/healthz")
    def healthz() -> JSONResponse:
        """Readiness probe — succeeds only when the DB is reachable."""
        try:
            conn = connect(settings.db_target)
            try:
                conn.execute("SELECT 1").fetchone()
            finally:
                conn.close()
        except Exception as exc:
            return JSONResponse(
                status_code=503,
                content={"ok": False, "service": "npcreate-backend", "db": "down", "error": str(exc)[:200]},
            )
        return JSONResponse(content={"ok": True, "service": "npcreate-backend", "db": "ok"})

    return app
