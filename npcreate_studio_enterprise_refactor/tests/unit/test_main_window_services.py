"""Phase C6 — main_window service-bundle assembly tests.

We can't drive the CustomTkinter mainloop headless, but we can verify the
service wiring that `build_services()` returns. Pages depend on exact keys
(``orchestrator``, ``adb_service``, ``mirror_service``, …) and on each
service's runtime type, so a typo here would silently break the GUI.
"""
from __future__ import annotations

from npcreate_studio.core.settings import Settings
from npcreate_studio.services.adb_service import AdbService
from npcreate_studio.services.device_profile_repository import DeviceProfileLibrary
from npcreate_studio.services.health_monitor import HealthMonitor
from npcreate_studio.services.media_service import MediaService
from npcreate_studio.services.mirror_service import MirrorService
from npcreate_studio.services.streaming_orchestrator import StreamingOrchestrator
from npcreate_studio.services.tiktok_automation import TikTokAutomation
from npcreate_studio.ui.main_window import build_services


def _settings(tmp_path) -> Settings:
    """Settings tuned so build_services doesn't try to hit the network."""
    return Settings(
        license_server_url=None,  # skip the license-lifecycle branch
        app_data_dir=str(tmp_path),
        tool_root=str(tmp_path / "vendor"),
        tools_manifest=str(tmp_path / "tools_manifest.json"),
    )


def test_build_services_returns_all_expected_keys(tmp_path):
    services = build_services(_settings(tmp_path))
    assert set(services.keys()) >= {
        "media_service",
        "adb_service",
        "orchestrator",
        "health_monitor",
        "device_profile_lib",
        "tiktok_automation",
        "mirror_service",
        "toast",
        "settings",
    }


def test_build_services_skips_license_lifecycle_when_no_server_url(tmp_path):
    services = build_services(_settings(tmp_path))
    assert "lifecycle" not in services


def test_build_services_wires_lifecycle_when_server_url_present(tmp_path):
    settings = Settings(
        license_server_url="http://127.0.0.1:8088",
        app_data_dir=str(tmp_path),
        tool_root=str(tmp_path / "vendor"),
        tools_manifest=str(tmp_path / "tools_manifest.json"),
    )
    services = build_services(settings)
    assert "lifecycle" in services


def test_build_services_assigns_correct_runtime_types(tmp_path):
    services = build_services(_settings(tmp_path))
    assert isinstance(services["media_service"], MediaService)
    assert isinstance(services["adb_service"], AdbService)
    assert isinstance(services["orchestrator"], StreamingOrchestrator)
    assert isinstance(services["health_monitor"], HealthMonitor)
    assert isinstance(services["device_profile_lib"], DeviceProfileLibrary)
    assert isinstance(services["tiktok_automation"], TikTokAutomation)
    assert isinstance(services["mirror_service"], MirrorService)


def test_build_services_health_monitor_pulls_stats_from_orchestrator(tmp_path):
    """Wiring contract: HealthMonitor.stats_provider must read from the same
    StreamingOrchestrator instance that the page's Start button drives."""
    services = build_services(_settings(tmp_path))
    orchestrator = services["orchestrator"]
    health = services["health_monitor"]
    # Calling tick() with no streaming should produce a snapshot equal to
    # orchestrator.stats — bytes/sec=0, status=IDLE.
    snap = health.tick()
    assert snap.pc_bytes_sent == orchestrator.stats.bytes_sent


def test_build_services_tiktok_automation_shares_adb_service(tmp_path):
    """TikTok automation must talk to the same ADB binary as the rest of
    the UI — sharing a single AdbService instance ensures that."""
    services = build_services(_settings(tmp_path))
    assert services["tiktok_automation"].adb is services["adb_service"]


def test_build_services_toast_passthrough_is_optional(tmp_path):
    """Headless / test mode passes toast=None; pages defensively handle it."""
    services = build_services(_settings(tmp_path), toast=None)
    assert services["toast"] is None


def test_build_services_mirror_service_reports_unavailable_when_scrcpy_missing(tmp_path, monkeypatch):
    """When ``shutil.which('scrcpy')`` returns None, MirrorService.is_available
    should be False and start_mirror returns ``scrcpy_not_installed``."""
    import shutil

    monkeypatch.setattr(shutil, "which", lambda name: None)
    services = build_services(_settings(tmp_path))
    mirror = services["mirror_service"]
    assert mirror.is_available() is False
    result = mirror.start_mirror("ABC123")
    assert result.ok is False
    assert result.error == "scrcpy_not_installed"
