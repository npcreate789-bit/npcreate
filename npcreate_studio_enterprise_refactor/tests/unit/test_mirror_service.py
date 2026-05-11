"""Phase B3 — MirrorService tests.

We never spawn real scrcpy — instead we inject a stub subprocess starter
that returns a fake Popen whose ``poll`` / ``terminate`` / ``wait`` /
``kill`` mirror the surface MirrorService uses. Clock and sleep are also
injected so timing is fully deterministic.
"""
from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

from npcreate_studio.services.mirror_service import (
    MirrorService,
    install_url_for_platform,
)

# ---------- fakes --------------------------------------------------------


class _FakePopen:
    """Mimics the subset of ``subprocess.Popen`` MirrorService touches."""

    def __init__(self, *, pid: int = 1234, exit_immediately: int | None = None) -> None:
        self.pid = pid
        self._exit = exit_immediately  # if set, poll() returns this rc right away
        self._terminated = False
        self._killed = False
        self.returncode: int | None = exit_immediately
        # If True, .wait() will raise TimeoutExpired the first time.
        self.simulate_terminate_timeout = False

    def poll(self) -> int | None:
        if self._exit is not None:
            self.returncode = self._exit
            return self._exit
        if self._terminated or self._killed:
            self.returncode = 0
            return 0
        return None

    def terminate(self) -> None:
        self._terminated = True

    def kill(self) -> None:
        self._killed = True

    def wait(self, timeout: float | None = None) -> int:
        if self.simulate_terminate_timeout and not self._killed:
            self.simulate_terminate_timeout = False
            raise subprocess.TimeoutExpired(cmd="scrcpy", timeout=timeout or 0)
        return self.poll() or 0


class _FakeSub:
    """Stub for StreamingSubprocess. Records every start() and returns a
    queued FakePopen (or a configured default)."""

    def __init__(self) -> None:
        self.starts: list[tuple[Sequence[str], dict]] = []
        self._queue: list[_FakePopen] = []
        self.spawn_error: Exception | None = None
        self.default_popen: _FakePopen | None = None

    def queue(self, popen: _FakePopen) -> None:
        self._queue.append(popen)

    def start(self, args, *, env=None, cwd=None, capture_output=True, detached=False):
        self.starts.append((tuple(args), {
            "env": dict(env) if env else None,
            "cwd": cwd,
            "capture_output": capture_output,
            "detached": detached,
        }))
        if self.spawn_error is not None:
            raise self.spawn_error
        if self._queue:
            return self._queue.pop(0)
        return self.default_popen or _FakePopen()


def _service(
    *,
    sub: _FakeSub | None = None,
    scrcpy_path: Path | None = Path("/usr/local/bin/scrcpy"),
    adb_path: str | None = "/usr/local/bin/adb",
    startup_grace_s: float = 0.0,
) -> tuple[MirrorService, _FakeSub]:
    sub = sub or _FakeSub()
    svc = MirrorService(
        subprocess_helper=sub,
        scrcpy_path=lambda: scrcpy_path,
        adb_path=lambda: adb_path,
        clock=lambda: 1700000000.0,
        sleep_fn=lambda _s: None,
        reaper_interval_s=0.05,
        startup_grace_s=startup_grace_s,
    )
    return svc, sub


# ---------- is_available + sanity ---------------------------------------


def test_is_available_true_when_scrcpy_path_resolves():
    svc, _ = _service(scrcpy_path=Path("/usr/local/bin/scrcpy"))
    assert svc.is_available() is True


def test_is_available_false_when_scrcpy_missing():
    svc, _ = _service(scrcpy_path=None)
    assert svc.is_available() is False


def test_install_url_is_platform_specific():
    url = install_url_for_platform()
    assert url.startswith("https://")


# ---------- start_mirror argv shape -------------------------------------


def test_start_mirror_builds_canonical_argv():
    svc, sub = _service()
    sub.queue(_FakePopen())
    result = svc.start_mirror("ABC123", label="My phone")
    assert result.ok is True
    assert result.pid == 1234
    args, kwargs = sub.starts[0]
    # First arg = scrcpy binary; then flags.
    assert args[0] == "/usr/local/bin/scrcpy"
    assert "--serial=ABC123" in args
    assert "--window-title=My phone" in args
    assert "--max-size=1080" in args
    assert "--max-fps=30" in args
    assert "--video-bit-rate=6M" in args
    # Tuned defaults
    assert "--no-audio" in args
    assert "--turn-screen-off" in args
    assert "--stay-awake" in args
    # Optional always-on-top stays off by default
    assert "--always-on-top" not in args
    # Detached + capture off → scrcpy GUI doesn't share stdio with us
    assert kwargs["capture_output"] is False
    assert kwargs["detached"] is True


def test_start_mirror_uses_default_label_when_blank():
    svc, sub = _service()
    sub.queue(_FakePopen())
    svc.start_mirror("ABC123")
    args, _ = sub.starts[0]
    assert "--window-title=NP Create — ABC123" in args


def test_start_mirror_extra_args_appended_after_built_in_flags():
    svc, sub = _service()
    sub.queue(_FakePopen())
    svc.start_mirror("ABC", extra_args=["--no-clipboard-autosync"])
    args, _ = sub.starts[0]
    assert "--no-clipboard-autosync" in args
    assert args.index("--no-clipboard-autosync") > args.index("--turn-screen-off")


def test_start_mirror_passes_adb_path_as_env_var():
    svc, sub = _service(adb_path="/opt/special/adb")
    sub.queue(_FakePopen())
    svc.start_mirror("ABC")
    _, kw = sub.starts[0]
    assert kw["env"] == {"ADB": "/opt/special/adb"}


def test_start_mirror_omits_env_when_no_adb_path_provided():
    svc, sub = _service(adb_path=None)
    sub.queue(_FakePopen())
    svc.start_mirror("ABC")
    _, kw = sub.starts[0]
    assert kw["env"] is None


# ---------- failure paths -----------------------------------------------


def test_start_mirror_rejects_empty_adb_id():
    svc, _ = _service()
    result = svc.start_mirror("")
    assert result.ok is False
    assert result.error == "missing_device"


def test_start_mirror_reports_missing_scrcpy_with_install_url():
    svc, _ = _service(scrcpy_path=None)
    result = svc.start_mirror("ABC")
    assert result.ok is False
    assert result.error == "scrcpy_not_installed"
    assert result.install_url.startswith("https://")


def test_start_mirror_reports_spawn_error():
    svc, sub = _service()
    sub.spawn_error = FileNotFoundError("no such file")
    result = svc.start_mirror("ABC")
    assert result.ok is False
    assert "spawn_failed" in result.error
    assert result.install_url.startswith("https://")


def test_start_mirror_reports_immediate_exit():
    svc, sub = _service()
    sub.queue(_FakePopen(exit_immediately=2))
    result = svc.start_mirror("ABC")
    assert result.ok is False
    assert result.error == "scrcpy_exited_rc2"


# ---------- idempotency + session tracking ------------------------------


def test_start_mirror_second_call_returns_existing_session():
    svc, sub = _service()
    sub.queue(_FakePopen(pid=111))
    sub.queue(_FakePopen(pid=222))
    first = svc.start_mirror("ABC")
    second = svc.start_mirror("ABC")
    assert first.ok is second.ok is True
    assert first.pid == 111
    assert second.pid == 111  # same session
    assert len(sub.starts) == 1  # second call did NOT spawn


def test_get_session_returns_active_session():
    svc, sub = _service()
    sub.queue(_FakePopen(pid=999))
    svc.start_mirror("ABC")
    sess = svc.get_session("ABC")
    assert sess is not None
    assert sess.adb_id == "ABC"
    assert sess.pid == 999


def test_get_session_returns_none_for_unknown_device():
    svc, _ = _service()
    assert svc.get_session("UNKNOWN") is None


def test_is_mirroring_reflects_session_state():
    svc, sub = _service()
    sub.queue(_FakePopen())
    assert svc.is_mirroring("ABC") is False
    svc.start_mirror("ABC")
    assert svc.is_mirroring("ABC") is True


def test_active_serials_lists_running_sessions():
    svc, sub = _service()
    sub.queue(_FakePopen(pid=1))
    sub.queue(_FakePopen(pid=2))
    svc.start_mirror("A")
    svc.start_mirror("B")
    assert set(svc.active_serials()) == {"A", "B"}


# ---------- stop_mirror + stop_all --------------------------------------


def test_stop_mirror_terminates_and_returns_true():
    svc, sub = _service()
    popen = _FakePopen()
    sub.queue(popen)
    svc.start_mirror("ABC")
    assert svc.stop_mirror("ABC") is True
    assert popen._terminated is True
    assert svc.is_mirroring("ABC") is False


def test_stop_mirror_unknown_serial_returns_true():
    svc, _ = _service()
    assert svc.stop_mirror("nope") is True


def test_stop_mirror_falls_back_to_kill_after_terminate_timeout():
    svc, sub = _service()
    popen = _FakePopen()
    popen.simulate_terminate_timeout = True
    sub.queue(popen)
    svc.start_mirror("ABC")
    assert svc.stop_mirror("ABC", timeout=0.01) is True
    assert popen._killed is True


def test_stop_all_terminates_every_session():
    svc, sub = _service()
    a, b = _FakePopen(pid=1), _FakePopen(pid=2)
    sub.queue(a)
    sub.queue(b)
    svc.start_mirror("A")
    svc.start_mirror("B")
    svc.stop_all()
    assert a._terminated and b._terminated
    assert svc.active_serials() == []


# ---------- reaper -------------------------------------------------------


def test_reap_once_prunes_externally_closed_sessions():
    svc, sub = _service()
    alive = _FakePopen(pid=1)
    dead = _FakePopen(pid=2)
    sub.queue(alive)
    sub.queue(dead)
    svc.start_mirror("alive-dev")
    svc.start_mirror("dead-dev")
    # Now the user closes the scrcpy window for dead-dev externally —
    # its proc exits.
    dead._exit = 0
    pruned = svc.reap_once()
    assert "dead-dev" in pruned
    assert svc.is_mirroring("alive-dev") is True
    assert svc.is_mirroring("dead-dev") is False


# ---------- subscribe callbacks -----------------------------------------


def test_subscribe_invoked_on_start_and_stop():
    events: list[str] = []
    svc, sub = _service()
    svc.subscribe(events.append)
    sub.queue(_FakePopen())
    svc.start_mirror("ABC")
    svc.stop_mirror("ABC")
    assert events == ["ABC", "ABC"]


def test_subscribe_invoked_on_external_close_via_reaper():
    events: list[str] = []
    svc, sub = _service()
    svc.subscribe(events.append)
    popen = _FakePopen()
    sub.queue(popen)
    svc.start_mirror("ABC")
    # External close
    popen._exit = 0
    svc.reap_once()
    assert events.count("ABC") == 2  # start + reaper


def test_subscribe_idempotent():
    svc, _ = _service()
    cb = lambda _id: None  # noqa: E731
    svc.subscribe(cb)
    svc.subscribe(cb)  # no-op
    # Internal state shouldn't double-invoke. We assert by counting:
    received: list[str] = []
    counter = lambda _id: received.append(_id)  # noqa: E731
    svc.subscribe(counter)
    svc._emit_change("X")
    assert received.count("X") == 1


def test_unsubscribe_stops_callbacks():
    received: list[str] = []
    svc, _ = _service()
    svc.subscribe(received.append)
    svc.unsubscribe(received.append)
    svc._emit_change("X")
    assert received == []


def test_callback_exception_does_not_break_emit():
    received: list[str] = []
    svc, _ = _service()
    svc.subscribe(lambda _id: (_ for _ in ()).throw(RuntimeError("boom")))
    svc.subscribe(received.append)
    svc._emit_change("X")
    assert received == ["X"]
