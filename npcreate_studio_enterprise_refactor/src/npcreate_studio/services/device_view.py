"""Pure presentation helpers for the Devices page.

Split out of ``ui/pages/devices_page.py`` so the formatters can be unit-tested
without a Tk display. The Tk page only owns the widget layout; mapping from
``Device`` and ``adb reverse --list`` output to user-visible strings lives here.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping

from ..domain.devices import Device, DeviceConnection, DeviceState

COLOR_AUTHORIZED = "success"
COLOR_UNAUTHORIZED = "warning"
COLOR_OFFLINE = "muted"
COLOR_BOOT = "info"
COLOR_UNKNOWN = "muted"


def device_state_pill(device: Device) -> tuple[str, str]:
    """Return (label, color_role) for the per-row state pill."""
    if device.state == DeviceState.DEVICE:
        return ("Authorized", COLOR_AUTHORIZED)
    if device.state == DeviceState.UNAUTHORIZED:
        return ("ต้องกด Allow บนเครื่อง", COLOR_UNAUTHORIZED)
    if device.state == DeviceState.OFFLINE:
        return ("Offline", COLOR_OFFLINE)
    if device.state in (DeviceState.BOOTLOADER, DeviceState.RECOVERY, DeviceState.SIDELOAD):
        return (device.state.value, COLOR_BOOT)
    return ("ไม่ทราบ", COLOR_UNKNOWN)


def device_display_label(device: Device) -> str:
    """Human-readable summary line for a device row.

    Prefers ``nickname`` if set, otherwise falls back to model + serial.
    """
    if device.nickname:
        return device.nickname
    if device.model:
        return f"{device.model} ({device.serial})"
    return device.serial


def device_meta_line(device: Device) -> str:
    """Secondary line under the display label."""
    parts: list[str] = []
    if device.product:
        parts.append(device.product)
    if device.connection == DeviceConnection.WIFI:
        parts.append("WiFi")
    elif device.connection == DeviceConnection.USB:
        parts.append("USB")
    parts.append(device.serial)
    return " · ".join(parts)


def adb_environment_summary(*, is_available: bool, devices: Iterable[Device]) -> Mapping[str, str]:
    """Top-of-page status summary."""
    devices_list = list(devices)
    authorized = sum(1 for d in devices_list if d.authorized)
    return {
        "ADB binary": "✓ พร้อมใช้งาน" if is_available else "✗ ไม่พบ adb (ตรวจ vendor/ หรือ PATH)",
        "Devices detected": str(len(devices_list)),
        "Authorized": str(authorized),
    }


def reverse_tunnel_summary(lines: Iterable[str], *, port: int) -> str:
    """Look at the output of `adb reverse --list` and tell the user whether
    our streaming port is currently tunneled."""
    target = f"tcp:{port}"
    matched = [line for line in lines if target in line]
    if matched:
        return f"✓ มี reverse tunnel ที่ {target} ({len(matched)} session)"
    return f"— ยังไม่มี reverse tunnel ที่ {target}; กด Bridge ในหน้า Live"


def props_quick_view(props: Mapping[str, str]) -> Mapping[str, str]:
    """Render the props dict returned by ``AdbService.get_props`` as a UI-ready
    dict, dropping empty values and renaming a couple of keys for readability."""
    rename = {
        "ro.product.model": "Model",
        "ro.product.device": "Device codename",
        "ro.product.cpu.abi": "CPU ABI",
        "ro.build.version.release": "Android version",
        "ro.build.version.sdk": "SDK level",
        "ro.boot.flash.locked": "Bootloader locked",
        "ro.boot.verifiedbootstate": "Verified boot",
        "ro.soc.model": "SoC",
        "ro.miui.ui.version.name": "MIUI version",
    }
    out: dict[str, str] = {}
    for key, label in rename.items():
        value = (props.get(key) or "").strip()
        if value:
            out[label] = value
    return out
