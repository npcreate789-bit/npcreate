from __future__ import annotations

import logging

from .core.logging import configure_logging
from .core.settings import Settings
from .infrastructure.toolchain import ToolchainResolver

log = logging.getLogger(__name__)


def bootstrap(settings: Settings | None = None) -> Settings:
    settings = settings or Settings()
    configure_logging(settings.log_level, app_data_dir=settings.app_data_path)

    resolver = ToolchainResolver(
        root=settings.tool_root_path,
        manifest_path=settings.tools_manifest_path,
    )
    report = resolver.verify_all(required=False)
    if report.invalid:
        log.warning("bundled tool verification failed: %s", report.invalid)
    if report.missing:
        log.info("bundled tools not installed yet: %s", report.missing)
    return settings


def run() -> int:
    """Application entrypoint. Keep startup small; UI imports stay lazy."""
    settings = bootstrap()
    try:
        from .ui.main_window import MainWindow

        MainWindow(settings=settings).run()
    except Exception:
        log.exception("application crashed")
        return 1
    return 0
