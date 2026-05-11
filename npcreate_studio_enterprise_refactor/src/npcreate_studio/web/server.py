from __future__ import annotations

import threading

import uvicorn

from ..core.settings import Settings
from .api import create_app


class DashboardServer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.config = uvicorn.Config(
            create_app(settings),
            host=settings.dashboard_host,
            port=settings.dashboard_port,
            log_level="warning",
        )
        self.server = uvicorn.Server(self.config)
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self.server.run, daemon=True, name="npcreate-dashboard")
        self.thread.start()

    def stop(self) -> None:
        self.server.should_exit = True
