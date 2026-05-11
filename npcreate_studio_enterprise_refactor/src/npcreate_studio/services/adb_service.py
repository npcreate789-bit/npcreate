from __future__ import annotations

from ..domain.devices import Device, DeviceConnection
from ..infrastructure.subprocess_runner import SubprocessRunner
from ..infrastructure.toolchain import ToolchainResolver


class AdbService:
    def __init__(self, tools: ToolchainResolver, runner: SubprocessRunner) -> None:
        self.tools = tools
        self.runner = runner

    def list_devices(self) -> list[Device]:
        adb = self.tools.resolve("adb")
        result = self.runner.run([adb, "devices", "-l"], timeout=10)
        devices: list[Device] = []
        for line in result.stdout.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2:
                serial, status = parts[0], parts[1]
                devices.append(
                    Device(
                        serial=serial,
                        connection=DeviceConnection.USB,
                        authorized=status == "device",
                    )
                )
        return devices
