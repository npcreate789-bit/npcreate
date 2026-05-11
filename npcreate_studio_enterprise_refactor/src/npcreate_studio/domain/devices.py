from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DeviceConnection(str, Enum):
    USB = "usb"
    WIFI = "wifi"
    OFFLINE = "offline"


@dataclass(frozen=True)
class Device:
    serial: str
    model: str = ""
    nickname: str = ""
    connection: DeviceConnection = DeviceConnection.OFFLINE
    authorized: bool = False
