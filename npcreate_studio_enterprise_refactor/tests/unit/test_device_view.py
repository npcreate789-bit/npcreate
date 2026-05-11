"""Pure-logic tests for device_view formatters (no Tk display required)."""
from __future__ import annotations

from npcreate_studio.domain.devices import Device, DeviceConnection, DeviceState
from npcreate_studio.services.device_view import (
    adb_environment_summary,
    device_display_label,
    device_meta_line,
    device_state_pill,
    props_quick_view,
    reverse_tunnel_summary,
)

# -- device_state_pill ----------------------------------------------------


def test_state_pill_device_is_authorized_success():
    label, role = device_state_pill(Device(serial="X", state=DeviceState.DEVICE))
    assert label == "Authorized"
    assert role == "success"


def test_state_pill_unauthorized_directs_user_to_allow():
    label, role = device_state_pill(Device(serial="X", state=DeviceState.UNAUTHORIZED))
    assert "Allow" in label
    assert role == "warning"


def test_state_pill_offline_uses_muted_color():
    _, role = device_state_pill(Device(serial="X", state=DeviceState.OFFLINE))
    assert role == "muted"


def test_state_pill_bootloader_recovery_sideload_use_info_color():
    for state in (DeviceState.BOOTLOADER, DeviceState.RECOVERY, DeviceState.SIDELOAD):
        label, role = device_state_pill(Device(serial="X", state=state))
        assert label == state.value
        assert role == "info"


def test_state_pill_unknown_state_falls_back():
    label, role = device_state_pill(Device(serial="X", state=DeviceState.UNKNOWN))
    assert label == "ไม่ทราบ"
    assert role == "muted"


# -- display label + meta line --------------------------------------------


def test_display_label_prefers_nickname():
    d = Device(serial="ABC", state=DeviceState.DEVICE, model="Pixel_2", nickname="My main phone")
    assert device_display_label(d) == "My main phone"


def test_display_label_falls_back_to_model_plus_serial():
    d = Device(serial="ABC", state=DeviceState.DEVICE, model="Pixel_2")
    assert device_display_label(d) == "Pixel_2 (ABC)"


def test_display_label_uses_serial_only_when_model_empty():
    d = Device(serial="ABC", state=DeviceState.DEVICE)
    assert device_display_label(d) == "ABC"


def test_meta_line_shows_product_connection_serial():
    d = Device(
        serial="192.168.1.5:5555",
        state=DeviceState.DEVICE,
        product="taimen",
        connection=DeviceConnection.WIFI,
    )
    assert device_meta_line(d) == "taimen · WiFi · 192.168.1.5:5555"


def test_meta_line_usb_path():
    d = Device(serial="R5CR", state=DeviceState.DEVICE, product="walleye", connection=DeviceConnection.USB)
    assert device_meta_line(d) == "walleye · USB · R5CR"


def test_meta_line_skips_connection_when_offline():
    d = Device(serial="X", state=DeviceState.OFFLINE, connection=DeviceConnection.OFFLINE)
    line = device_meta_line(d)
    assert "USB" not in line
    assert "WiFi" not in line
    assert line == "X"


# -- adb_environment_summary ----------------------------------------------


def test_env_summary_counts_authorized_devices():
    devices = [
        Device(serial="A", state=DeviceState.DEVICE),
        Device(serial="B", state=DeviceState.UNAUTHORIZED),
        Device(serial="C", state=DeviceState.DEVICE),
    ]
    out = adb_environment_summary(is_available=True, devices=devices)
    assert out["Devices detected"] == "3"
    assert out["Authorized"] == "2"
    assert out["ADB binary"].startswith("✓")


def test_env_summary_marks_adb_missing_when_unavailable():
    out = adb_environment_summary(is_available=False, devices=[])
    assert out["ADB binary"].startswith("✗")
    assert out["Devices detected"] == "0"


# -- reverse tunnel summary ----------------------------------------------


def test_reverse_tunnel_summary_matches_port():
    lines = ["(reverse) tcp:8888 tcp:8888", "(reverse) tcp:1234 tcp:1234"]
    out = reverse_tunnel_summary(lines, port=8888)
    assert "✓" in out
    assert "tcp:8888" in out


def test_reverse_tunnel_summary_says_missing_when_port_not_listed():
    out = reverse_tunnel_summary(["(reverse) tcp:1234 tcp:1234"], port=8888)
    assert "ยังไม่มี" in out
    assert "tcp:8888" in out


def test_reverse_tunnel_summary_empty_input():
    out = reverse_tunnel_summary([], port=8888)
    assert "ยังไม่มี" in out


# -- props_quick_view -----------------------------------------------------


def test_props_quick_view_renames_known_keys_and_drops_empty():
    props = {
        "ro.product.model": "Pixel 7",
        "ro.product.cpu.abi": "arm64-v8a",
        "ro.build.version.release": "14",
        "ro.boot.flash.locked": "1",
        "ro.miui.ui.version.name": "",  # empty should be dropped
        "irrelevant.key": "ignored",
    }
    out = props_quick_view(props)
    assert out["Model"] == "Pixel 7"
    assert out["CPU ABI"] == "arm64-v8a"
    assert out["Android version"] == "14"
    assert out["Bootloader locked"] == "1"
    # Renamed labels only — raw keys never leak.
    assert "ro.product.model" not in out
    # Empty values filtered out.
    assert "MIUI version" not in out
    # Unmapped key never appears.
    assert "irrelevant.key" not in out
    assert "ignored" not in out.values()


def test_props_quick_view_empty_input_returns_empty():
    assert props_quick_view({}) == {}
