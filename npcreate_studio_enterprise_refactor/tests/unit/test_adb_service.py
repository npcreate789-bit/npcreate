"""Phase A2 — AdbService tests.

The real ``adb`` binary isn't on most dev machines and definitely not in CI;
instead we stub ``SubprocessRunner.run`` so we can assert both the parsing
logic and the argv shape (`-s SERIAL`, `reverse tcp:<port> tcp:<port>`, etc.)
that downstream tools depend on.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from npcreate_studio.domain.devices import DeviceConnection, DeviceState
from npcreate_studio.infrastructure.subprocess_runner import CommandResult
from npcreate_studio.services.adb_service import AdbService


@dataclass
class _FakeTools:
    adb_path: str = "/fake/adb"

    def resolve(self, name: str) -> str:
        return f"{self.adb_path}-{name}" if name != "adb" else self.adb_path

    def resolve_or_path(self, name: str, *, path_name: str | None = None) -> str:
        return self.resolve(name)


class _FakeRunner:
    """Stub that records argv lists and returns canned CommandResult per match."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self._matchers: list[tuple[Sequence[str], CommandResult]] = []
        self.default: CommandResult = CommandResult(0, "", "")

    def register(self, suffix: Sequence[str], result: CommandResult) -> None:
        self._matchers.append((tuple(suffix), result))

    def run(self, args, *, timeout=None, cwd=None, env=None, input_text=None):  # noqa: ANN001
        argv = [str(a) for a in args]
        self.calls.append(argv)
        for suffix, result in self._matchers:
            if tuple(argv[-len(suffix):]) == suffix:
                return result
        return self.default


def _service() -> tuple[AdbService, _FakeRunner]:
    runner = _FakeRunner()
    return AdbService(tools=_FakeTools(), runner=runner), runner  # type: ignore[arg-type]


# -- argv shape ---------------------------------------------------------------


def test_run_uses_resolved_adb_path_and_no_serial_by_default():
    svc, runner = _service()
    svc.shell("getprop ro.product.model")
    assert runner.calls[-1][0] == "/fake/adb"
    assert "-s" not in runner.calls[-1]


def test_run_injects_serial_before_subcommand():
    svc, runner = _service()
    svc.shell("getprop ro.product.model", serial="ABC123")
    argv = runner.calls[-1]
    assert argv[:4] == ["/fake/adb", "-s", "ABC123", "shell"]


# -- list_devices parsing -----------------------------------------------------


_DEVICES_OUTPUT = """List of devices attached
R5CR70ABCDE   device  product:taimen model:Pixel_2_XL device:taimen transport_id:1
192.168.1.5:5555 unauthorized usb:1-2 device:walleye transport_id:2
EMULATOR1     offline
* daemon not running; starting now at tcp:5037 *
"""


def test_list_devices_parses_state_model_product():
    svc, runner = _service()
    runner.register(("devices", "-l"), CommandResult(0, _DEVICES_OUTPUT, ""))
    devices = svc.list_devices()
    assert len(devices) == 3
    by_serial = {d.serial: d for d in devices}
    pixel = by_serial["R5CR70ABCDE"]
    assert pixel.state == DeviceState.DEVICE
    assert pixel.model == "Pixel_2_XL"
    assert pixel.product == "taimen"
    assert pixel.authorized is True
    assert pixel.connection == DeviceConnection.USB

    wifi = by_serial["192.168.1.5:5555"]
    assert wifi.state == DeviceState.UNAUTHORIZED
    assert wifi.authorized is False
    # serial contains ":" but state is unauthorized → connection is OFFLINE
    assert wifi.connection == DeviceConnection.OFFLINE

    emu = by_serial["EMULATOR1"]
    assert emu.state == DeviceState.OFFLINE


def test_list_devices_marks_wifi_when_authorized_and_serial_has_colon():
    svc, runner = _service()
    runner.register(
        ("devices", "-l"),
        CommandResult(0, "List of devices attached\n192.168.1.5:5555 device\n", ""),
    )
    [device] = svc.list_devices()
    assert device.state == DeviceState.DEVICE
    assert device.connection == DeviceConnection.WIFI


def test_list_devices_returns_empty_on_failure():
    svc, runner = _service()
    runner.register(("devices", "-l"), CommandResult(1, "", "error: device offline"))
    assert svc.list_devices() == []


def test_list_devices_skips_blank_and_daemon_marker_lines():
    svc, runner = _service()
    runner.register(
        ("devices", "-l"),
        CommandResult(0, "List of devices attached\n\n* daemon not running *\nABC device model:X product:y\n", ""),
    )
    [device] = svc.list_devices()
    assert device.serial == "ABC"


# -- shell + props ------------------------------------------------------------


def test_shell_returns_trimmed_stdout():
    svc, runner = _service()
    runner.register(("shell", "echo hi"), CommandResult(0, "  hi  \n", ""))
    assert svc.shell("echo hi") == "hi"


def test_shell_returns_empty_string_on_nonzero_exit():
    svc, runner = _service()
    runner.register(("shell", "false"), CommandResult(1, "", "ouch"))
    assert svc.shell("false") == ""


def test_get_props_returns_dict_with_all_requested_keys():
    svc, runner = _service()

    def handler(args, **kwargs):
        argv = [str(a) for a in args]
        runner.calls.append(argv)
        prop = argv[-1].split(" ", 1)[1]  # "getprop ro.product.model" → "ro.product.model"
        return CommandResult(0, f"value-of-{prop}", "")

    runner.run = handler  # type: ignore[method-assign]
    props = svc.get_props(keys=("ro.product.model", "ro.boot.flash.locked"))
    assert props == {"ro.product.model": "value-of-ro.product.model", "ro.boot.flash.locked": "value-of-ro.boot.flash.locked"}


def test_get_props_default_keys_include_critical_security_props():
    svc, runner = _service()
    runner.default = CommandResult(0, "x", "")
    props = svc.get_props()
    # The legacy-critical security/boot props must always be queried.
    assert "ro.boot.flash.locked" in props
    assert "ro.boot.verifiedbootstate" in props


# -- reverse tunnel -----------------------------------------------------------


def test_reverse_constructs_correct_argv_and_returns_true_on_success():
    svc, runner = _service()
    runner.register(("reverse", "tcp:8888", "tcp:8888"), CommandResult(0, "", ""))
    assert svc.reverse(8888) is True
    argv = runner.calls[-1]
    assert argv == ["/fake/adb", "reverse", "tcp:8888", "tcp:8888"]


def test_reverse_with_serial_inserts_dash_s():
    svc, runner = _service()
    runner.register(("reverse", "tcp:8888", "tcp:8888"), CommandResult(0, "", ""))
    svc.reverse(8888, serial="ABC")
    argv = runner.calls[-1]
    assert argv[:3] == ["/fake/adb", "-s", "ABC"]
    assert argv[-3:] == ["reverse", "tcp:8888", "tcp:8888"]


def test_reverse_returns_false_on_failure():
    svc, runner = _service()
    runner.register(("reverse", "tcp:8888", "tcp:8888"), CommandResult(1, "", "device offline"))
    assert svc.reverse(8888) is False


def test_reverse_remove_uses_remove_flag():
    svc, runner = _service()
    svc.reverse_remove(8888)
    argv = runner.calls[-1]
    assert argv[-3:] == ["reverse", "--remove", "tcp:8888"]


def test_reverse_list_returns_non_empty_lines():
    svc, runner = _service()
    runner.register(
        ("reverse", "--list"),
        CommandResult(0, "host-rev\ntcp:8888 tcp:8888\n\n", ""),
    )
    assert svc.reverse_list() == ["host-rev", "tcp:8888 tcp:8888"]


# -- restart_server + is_available -------------------------------------------


def test_restart_server_returns_true_when_start_succeeds_even_if_kill_failed():
    svc, runner = _service()
    runner.register(("kill-server",), CommandResult(1, "", "no daemon"))
    runner.register(("start-server",), CommandResult(0, "", ""))
    assert svc.restart_server() is True


def test_restart_server_returns_false_when_start_fails():
    svc, runner = _service()
    runner.register(("kill-server",), CommandResult(0, "", ""))
    runner.register(("start-server",), CommandResult(1, "", "port in use"))
    assert svc.restart_server() is False


def test_is_available_returns_true_when_version_ok():
    svc, runner = _service()
    runner.register(("version",), CommandResult(0, "Android Debug Bridge version 1.0.41", ""))
    assert svc.is_available() is True


def test_is_available_returns_false_on_nonzero_exit():
    svc, runner = _service()
    runner.register(("version",), CommandResult(127, "", "adb: command not found"))
    assert svc.is_available() is False
