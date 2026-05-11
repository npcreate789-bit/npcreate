"""ADB orchestration — ported from legacy ``vcam-pc/src/adb.py``.

Wraps the ``adb`` binary via ``SubprocessRunner`` so executable + env are
validated. Surface:

- ``list_devices`` — parses ``adb devices -l`` with model/product/state
- ``shell`` / ``get_props`` — run shell commands and bulk-fetch ``getprop`` values
- ``reverse`` / ``reverse_remove`` / ``reverse_list`` — TCP port forwarding
  phone → PC (this is what unlocks streaming from PC's :8888 to the receiver
  app — the legacy core trick)
- ``restart_server`` — ``kill-server`` then ``start-server``; clears 95 %% of
  "stuck on Allow USB Debugging" reports per the legacy comments
- ``is_available`` — quick smoke test, used by UI to gate Live page actions
"""
from __future__ import annotations

import logging

from ..domain.devices import Device, DeviceConnection, DeviceState
from ..infrastructure.subprocess_runner import SubprocessRunner
from ..infrastructure.toolchain import ToolchainResolver

log = logging.getLogger(__name__)


def _state_from_string(value: str) -> DeviceState:
    try:
        return DeviceState(value)
    except ValueError:
        return DeviceState.UNKNOWN


def _connection_from_state(state: DeviceState, serial: str) -> DeviceConnection:
    if state != DeviceState.DEVICE:
        return DeviceConnection.OFFLINE
    # Wireless ADB serials look like "192.168.1.5:5555".
    return DeviceConnection.WIFI if ":" in serial else DeviceConnection.USB


class AdbService:
    def __init__(self, tools: ToolchainResolver, runner: SubprocessRunner) -> None:
        self.tools = tools
        self.runner = runner

    # -- plumbing ----------------------------------------------------------

    def _adb_path(self) -> str:
        return str(self.tools.resolve("adb"))

    def _run(self, *args: str, serial: str | None = None, timeout: float = 10.0):
        adb = self._adb_path()
        argv: list[str] = [adb]
        if serial:
            argv += ["-s", serial]
        argv += list(args)
        return self.runner.run(argv, timeout=timeout)

    # -- availability + lifecycle -----------------------------------------

    def is_available(self) -> bool:
        try:
            result = self._run("version", timeout=5)
        except Exception:
            return False
        return result.returncode == 0

    def restart_server(self) -> bool:
        """``kill-server`` then ``start-server`` to recover from stale daemon state.

        Returns True only if start-server succeeded. kill-server failing
        usually just means no daemon was running — that's fine, the goal is
        "no stale daemon."
        """
        kill = self._run("kill-server", timeout=5)
        if kill.returncode != 0:
            log.debug("adb kill-server rc=%s err=%s", kill.returncode, kill.stderr.strip())
        start = self._run("start-server", timeout=10)
        if start.returncode != 0:
            log.error("adb start-server failed rc=%s err=%s", start.returncode, start.stderr.strip())
            return False
        log.info("adb daemon restarted")
        return True

    # -- device enumeration ------------------------------------------------

    def list_devices(self) -> list[Device]:
        """Parse ``adb devices -l``.

        Each non-header line looks like::

            R5CR70ABCDE   device  product:taimen model:Pixel_2_XL device:taimen ...
            192.168.1.5:5555 unauthorized

        We pull serial + state + model + product. ``device:`` we treat as
        the "product code" because vendors sometimes overload `product:` /
        `device:` confusingly — but the legacy code uses `product`, so we
        match that to avoid surprising downstream consumers.
        """
        result = self._run("devices", "-l", timeout=10)
        if result.returncode != 0:
            log.error("adb devices failed: %s", result.stderr.strip())
            return []
        devices: list[Device] = []
        for raw in result.stdout.splitlines()[1:]:
            line = raw.strip()
            if not line or line.startswith("*"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            serial, raw_state = parts[0], parts[1]
            kv = dict(p.split(":", 1) for p in parts[2:] if ":" in p)
            state = _state_from_string(raw_state)
            devices.append(
                Device(
                    serial=serial,
                    state=state,
                    model=kv.get("model", ""),
                    product=kv.get("product", ""),
                    connection=_connection_from_state(state, serial),
                )
            )
        return devices

    # -- shell helpers -----------------------------------------------------

    def shell(self, command: str, *, serial: str | None = None, timeout: float = 10.0) -> str:
        """Run a single shell command and return trimmed stdout (empty on failure)."""
        result = self._run("shell", command, serial=serial, timeout=timeout)
        if result.returncode != 0:
            log.warning("adb shell %r rc=%s err=%s", command, result.returncode, result.stderr.strip())
        return result.stdout.strip()

    DEFAULT_PROPS: tuple[str, ...] = (
        "ro.soc.model",
        "ro.board.platform",
        "ro.product.device",
        "ro.product.model",
        "ro.product.cpu.abi",
        "ro.build.version.release",
        "ro.build.version.sdk",
        "ro.miui.ui.version.name",
        "ro.mi.os.version.name",
        "ro.boot.flash.locked",
        "ro.boot.verifiedbootstate",
    )

    def get_props(self, *, serial: str | None = None, keys: tuple[str, ...] | None = None) -> dict[str, str]:
        """Bulk-fetch ``getprop`` values. Empty string for any key adb doesn't return."""
        wanted = keys or self.DEFAULT_PROPS
        out: dict[str, str] = {}
        for key in wanted:
            out[key] = self.shell(f"getprop {key}", serial=serial)
        return out

    # -- reverse port forwarding ------------------------------------------

    def reverse(self, port: int, *, serial: str | None = None) -> bool:
        """``adb reverse tcp:<port> tcp:<port>`` — tunnel phone → PC.

        This is THE legacy mechanism that lets the phone receiver app open
        a TCP socket to localhost:<port> and have it land on the PC's
        FFmpeg-pumped stream server.
        """
        result = self._run("reverse", f"tcp:{port}", f"tcp:{port}", serial=serial, timeout=5)
        if result.returncode != 0:
            log.error("adb reverse :%d failed: %s", port, result.stderr.strip())
            return False
        return True

    def reverse_remove(self, port: int, *, serial: str | None = None) -> None:
        self._run("reverse", "--remove", f"tcp:{port}", serial=serial, timeout=5)

    def reverse_list(self, *, serial: str | None = None) -> list[str]:
        result = self._run("reverse", "--list", serial=serial, timeout=5)
        return [line for line in result.stdout.splitlines() if line.strip()]
