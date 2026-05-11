from __future__ import annotations

import logging
import shutil
from collections.abc import Callable
from typing import Any

from ..core.settings import Settings
from ..infrastructure.secure_store import SecureStore
from ..infrastructure.streaming_subprocess import StreamingPolicy, StreamingSubprocess
from ..infrastructure.subprocess_runner import SubprocessRunner
from ..infrastructure.toolchain import ToolchainResolver
from ..services.adb_service import AdbService
from ..services.device_profile_repository import load_combined as load_device_profile_library
from ..services.health_monitor import HealthMonitor
from ..services.license_client import LicenseClient
from ..services.license_lifecycle import LicenseLifecycleService
from ..services.media_service import MediaService
from ..services.mirror_service import MirrorService
from ..services.rtmp_stream_service import RtmpStreamService
from ..services.streaming_orchestrator import StreamingOrchestrator
from ..services.tiktok_automation import TikTokAutomation
from . import theme
from .components.toast import ToastManager

log = logging.getLogger(__name__)


def build_services(settings: Settings, *, toast: Any = None) -> dict[str, Any]:
    """Assemble the service bundle that pages receive.

    Extracted out of ``MainWindow.run`` so the wiring is unit-testable without
    instantiating Tk. ``toast`` can be a stub (or ``None``) when no display is
    available — pages defensively handle missing toast.
    """
    services: dict[str, Any] = {}

    if settings.license_server_url:
        client = LicenseClient(base_url=settings.license_server_url, app_version=settings.app_version)
        store = SecureStore(settings.app_data_path)
        services["lifecycle"] = LicenseLifecycleService(client=client, store=store)

    # Streaming + ADB stack (Phases A1–A3). Falls back to PATH for ffmpeg/adb
    # in dev when vendor/ is empty; production builds rely on tools_manifest.
    runner = SubprocessRunner()
    tools = ToolchainResolver(root=settings.tool_root_path, manifest_path=settings.tools_manifest_path)
    media = MediaService(tools=tools, runner=runner)
    adb = AdbService(tools=tools, runner=runner)
    ffmpeg_path = shutil.which("ffmpeg")
    streaming_policy = StreamingPolicy(allowed_names=frozenset({"ffmpeg", "ffmpeg.exe"}))
    orchestrator = StreamingOrchestrator(
        settings=settings,
        media=media,
        subprocess=StreamingSubprocess(streaming_policy),
        ffmpeg_path=ffmpeg_path,
    )
    health = HealthMonitor(
        stats_provider=lambda: orchestrator.stats,
        adb=adb,
        interval_s=2.0,
    )
    device_profile_lib = load_device_profile_library(
        user_path=settings.app_data_path / "device_profiles.json",
    )

    # Phase B1 + B3 — TikTok automation + scrcpy mirror sessions.
    tiktok = TikTokAutomation(adb=adb)
    scrcpy_path_value = shutil.which("scrcpy")
    from pathlib import Path as _Path
    mirror_policy = StreamingPolicy(allowed_names=frozenset({"scrcpy", "scrcpy.exe"}))
    mirror = MirrorService(
        subprocess_helper=StreamingSubprocess(mirror_policy),
        scrcpy_path=lambda: _Path(scrcpy_path_value) if scrcpy_path_value else None,
        adb_path=lambda: shutil.which("adb"),
    )

    # Phase C3 — separate RTMP push service (FFmpeg → external ingest URL).
    rtmp_service = RtmpStreamService(
        media=media,
        subprocess=StreamingSubprocess(streaming_policy),
        ffmpeg_path=ffmpeg_path,
    )

    services.update({
        "media_service": media,
        "adb_service": adb,
        "orchestrator": orchestrator,
        "health_monitor": health,
        "device_profile_lib": device_profile_lib,
        "tiktok_automation": tiktok,
        "mirror_service": mirror,
        "rtmp_service": rtmp_service,
        "toast": toast,
        "settings": settings,
    })
    return services


class MainWindow:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._content = None
        self._nav_buttons: dict[str, object] = {}
        self._services: dict[str, Any] = {}

    def run(self) -> None:
        """Production-ready CustomTkinter shell.

        Business logic stays in services; UI pages are thin and safe. Import
        customtkinter lazily so CLI/tests can run headless.
        """
        try:
            import customtkinter as ctk
        except ImportError:
            log.warning("customtkinter missing; running headless smoke mode")
            return

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")
        self.ctk = ctk
        root = ctk.CTk()
        root.title("NP Create Studio")
        root.geometry("1240x780")
        root.minsize(1100, 680)
        root.configure(fg_color=theme.BACKGROUND)
        self.toast = ToastManager(ctk, root)
        self._services = build_services(self.settings, toast=self.toast)

        orchestrator = self._services["orchestrator"]
        health = self._services["health_monitor"]
        mirror = self._services["mirror_service"]
        rtmp = self._services["rtmp_service"]

        # Graceful shutdown — stop streaming + health + mirror + RTMP on close.
        def _on_close() -> None:
            try:
                if orchestrator.is_running():
                    orchestrator.stop()
            except Exception:
                log.exception("orchestrator stop on close failed")
            try:
                if health.is_running():
                    health.stop()
            except Exception:
                log.exception("health stop on close failed")
            try:
                mirror.stop_all()
            except Exception:
                log.exception("mirror.stop_all on close failed")
            try:
                if rtmp.is_running():
                    rtmp.stop()
            except Exception:
                log.exception("rtmp stop on close failed")
            root.destroy()

        root.protocol("WM_DELETE_WINDOW", _on_close)

        shell = ctk.CTkFrame(root, fg_color=theme.BACKGROUND)
        shell.pack(fill="both", expand=True)
        shell.grid_columnconfigure(1, weight=1)
        shell.grid_rowconfigure(0, weight=1)

        self._build_sidebar(shell)
        self._content = ctk.CTkFrame(shell, fg_color=theme.BACKGROUND)
        self._content.grid(row=0, column=1, sticky="nsew", padx=22, pady=22)
        self._content.grid_rowconfigure(1, weight=1)
        self._content.grid_columnconfigure(0, weight=1)

        # First-run auto-redirect: if no activation yet, drop the user into the
        # onboarding wizard so they're not staring at an empty dashboard.
        first_page = "dashboard"
        lifecycle = self._services.get("lifecycle")
        if lifecycle is None or lifecycle.current_state() is None:
            first_page = "onboarding"
        self._show_page(first_page)
        root.mainloop()

    def _build_sidebar(self, parent) -> None:
        ctk = self.ctk
        sidebar = ctk.CTkFrame(parent, width=250, fg_color=theme.SIDEBAR, corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="ns")
        sidebar.grid_propagate(False)

        logo = ctk.CTkFrame(sidebar, fg_color="transparent")
        logo.pack(fill="x", padx=20, pady=(24, 16))
        ctk.CTkLabel(logo, text="NP", width=48, height=48, fg_color=theme.PRIMARY, corner_radius=16, font=(theme.FONT_FAMILY, 20, "bold"), text_color="#FFFFFF").pack(side="left")
        ctk.CTkLabel(logo, text="NP Create\nStudio", justify="left", font=(theme.FONT_FAMILY, 18, "bold"), text_color=theme.TEXT).pack(side="left", padx=12)

        ctk.CTkLabel(sidebar, text="เมนูหลัก", text_color=theme.TEXT_MUTED, anchor="w", font=(theme.FONT_FAMILY, 12, "bold")).pack(fill="x", padx=22, pady=(6, 6))
        nav: list[tuple[str, str]] = [
            ("dashboard", "ภาพรวมระบบ"),
            ("onboarding", "เริ่มต้น"),
            ("license", "License"),
            ("live", "Live Streaming"),
            ("stream", "Stream (RTMP)"),
            ("devices", "ผูกอุปกรณ์"),
            ("updates", "อัปเดตโปรแกรม"),
            ("news", "ข่าวสาร"),
            ("logs", "Log / Error Report"),
            ("settings", "ตั้งค่า"),
        ]
        for page_key, label in nav:
            btn = ctk.CTkButton(
                sidebar,
                text=label,
                anchor="w",
                height=42,
                fg_color="transparent",
                hover_color=theme.SURFACE_SOFT,
                corner_radius=12,
                command=lambda k=page_key: self._show_page(k),
            )
            btn.pack(fill="x", padx=16, pady=3)
            self._nav_buttons[page_key] = btn

        footer = ctk.CTkFrame(sidebar, fg_color=theme.SURFACE, corner_radius=18)
        footer.pack(side="bottom", fill="x", padx=16, pady=18)
        ctk.CTkLabel(footer, text="Production Mode", text_color=theme.TEXT, font=(theme.FONT_FAMILY, 14, "bold")).pack(anchor="w", padx=16, pady=(14, 2))
        ctk.CTkLabel(footer, text=f"v{self.settings.app_version}\nSigned update + Device binding", text_color=theme.TEXT_MUTED, justify="left", font=(theme.FONT_FAMILY, 12)).pack(anchor="w", padx=16, pady=(0, 14))

    def _show_page(self, page_key: str) -> None:
        ctk = self.ctk
        assert self._content is not None
        for widget in self._content.winfo_children():
            widget.destroy()
        for key, button in self._nav_buttons.items():
            button.configure(fg_color=theme.PRIMARY if key == page_key else "transparent")

        header = ctk.CTkFrame(self._content, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="ระบบจัดการ NP Create Studio", text_color=theme.TEXT_MUTED, font=(theme.FONT_FAMILY, 13)).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(header, text="● Secure Client", text_color=theme.SUCCESS, font=(theme.FONT_FAMILY, 13, "bold")).grid(row=0, column=1, sticky="e")

        page_builders: dict[str, Callable] = {
            "dashboard": self._load_page("dashboard_page"),
            "onboarding": self._load_page("onboarding_page"),
            "license": self._load_page("license_page"),
            "live": self._load_page("live_page"),
            "stream": self._load_page("stream_page"),
            "devices": self._load_page("devices_page"),
            "updates": self._load_page("updates_page"),
            "news": self._load_page("news_page"),
            "logs": self._load_page("logs_page"),
            "settings": self._load_page("settings_page"),
        }
        builder = page_builders.get(page_key, page_builders["dashboard"])
        # Inject a page-switcher callback so pages can request navigation
        # (e.g. onboarding's "→ Open Live Streaming" button).
        self._services["_page_switcher"] = self._show_page
        try:
            page = builder(ctk, self._content, self.settings, self._services)
        except TypeError:
            # Backward-compat for builders that haven't migrated to (ctk, parent, settings, services).
            page = builder(ctk, self._content, self.settings)
        page.grid(row=1, column=0, sticky="nsew")

    def _load_page(self, module_name: str) -> Callable:
        from importlib import import_module

        module = import_module(f"npcreate_studio.ui.pages.{module_name}")
        return module.build
