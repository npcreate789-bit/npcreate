from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException

from .. import __app_name__, __version__
from ..core.settings import Settings
from ..infrastructure import db
from .auth import LocalTokenAuthMiddleware


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title=f"{__app_name__} Dashboard", version=__version__, docs_url=None, redoc_url=None)
    app.add_middleware(LocalTokenAuthMiddleware)
    app.state.db = db.connect(settings.database_path)

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "name": __app_name__, "version": __version__}

    @app.get("/api/summary")
    def summary() -> dict:
        row = app.state.db.execute("SELECT COUNT(*) AS n FROM shops").fetchone()
        return {"shops": int(row["n"])}

    if settings.enable_demo_routes:
        @app.post("/api/demo/clear")
        def demo_clear() -> dict:
            if settings.env == "production":
                raise HTTPException(403, "demo routes disabled in production")
            return {"cleared": 0}

    return app
