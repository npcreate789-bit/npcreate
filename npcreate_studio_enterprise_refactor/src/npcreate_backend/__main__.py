from __future__ import annotations

import uvicorn

from .settings import BackendSettings


def main() -> None:
    settings = BackendSettings()
    uvicorn.run("npcreate_backend.app:create_app", factory=True, host=settings.host, port=settings.port, reload=settings.env == "development")


if __name__ == "__main__":
    main()
