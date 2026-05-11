from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DeviceConnection(str, Enum):
    USB = "usb"
    WIFI = "wifi"
    OFFLINE = "offline"


class DeviceState(str, Enum):
    """Mirrors the second column of ``adb devices -l`` output."""

    DEVICE = "device"  # online and authorized
    UNAUTHORIZED = "unauthorized"
    OFFLINE = "offline"
    BOOTLOADER = "bootloader"
    RECOVERY = "recovery"
    SIDELOAD = "sideload"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Device:
    serial: str
    state: DeviceState = DeviceState.UNKNOWN
    model: str = ""
    product: str = ""
    nickname: str = ""
    connection: DeviceConnection = DeviceConnection.OFFLINE

    @property
    def authorized(self) -> bool:
        return self.state == DeviceState.DEVICE

    @property
    def online(self) -> bool:
        return self.state == DeviceState.DEVICE
