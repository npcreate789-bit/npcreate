"""Per-device scrcpy mirror sessions — ported from legacy
``vcam-pc/src/scrcpy_mirror.py``.

User story (legacy): the phone is laid flat on the desk so the camera
points at the lightbox/turntable. The customer doesn't want to pick it up
to drive TikTok comments / "Go Live"; they want mouse + keyboard from PC.
scrcpy (Genymobile) streams the phone display over the existing ADB
transport and accepts input events back.

Legacy used module-level globals (sessions dict, reaper thread, change-
callbacks). We port to a ``MirrorService`` class so:

- two app instances or tests don't share global state,
- dependencies (subprocess starter, scrcpy/adb path resolution, clock,
  sleep) are all injectable for deterministic unit tests, and
- the GUI shutdown hook can call ``stop_all`` on a single instance.

scrcpy runs as a separate OS-level window — customer can drag it to a
second monitor, full-screen it, etc. We don't try to embed inside Tk.
"""
from __future__ import annotations

import logging
import shlex
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class StartMirrorResult:
    """Returned by :meth:`MirrorService.start_mirror`. Mirrors the shape
    of other lifecycle-result records so UI handlers can use one try/except
    pattern."""

    ok: bool
    error: str = ""
    install_url: str = ""
    pid: int | None = None
    cmd: tuple[str, ...] = ()


@dataclass
class MirrorSession:
    adb_id: str
    label: str
    pid: int
    started_at: float
    proc: subprocess.Popen
    cmd: tuple[str, ...]

    def is_running(self) -> bool:
        return self.proc.poll() is None


class _SubprocessStarter(Protocol):
    def start(
        self,
        args,
        *,
        env: Mapping[str, str] | None = ...,
        cwd: Path | None = ...,
        capture_output: bool = ...,
        detached: bool = ...,
    ) -> subprocess.Popen: ...


ChangeCallback = Callable[[str], None]


def install_url_for_platform() -> str:
    """Deep-link to the most appropriate scrcpy install instructions for
    THIS OS — used in the "scrcpy not found" UI so customers go straight
    to the right place."""
    if sys.platform == "darwin":
        return "https://formulae.brew.sh/formula/scrcpy"
    if sys.platform.startswith("win"):
        return "https://github.com/Genymobile/scrcpy/releases"
    return "https://github.com/Genymobile/scrcpy#linux"


class MirrorService:
    """Track + control scrcpy sessions per ADB serial."""

    def __init__(
        self,
        *,
        subprocess_helper: _SubprocessStarter,
        scrcpy_path: Callable[[], Path | None],
        adb_path: Callable[[], str | None] = lambda: None,
        clock: Callable[[], float] = time.time,
        sleep_fn: Callable[[float], None] = time.sleep,
        reaper_interval_s: float = 1.0,
        startup_grace_s: float = 0.25,
    ) -> None:
        self._sub = subprocess_helper
        self._scrcpy_path = scrcpy_path
        self._adb_path = adb_path
        self._clock = clock
        self._sleep = sleep_fn
        self._reaper_interval_s = reaper_interval_s
        self._startup_grace_s = startup_grace_s

        self._sessions: dict[str, MirrorSession] = {}
        self._sessions_lock = threading.RLock()
        self._reaper_thread: threading.Thread | None = None
        self._reaper_stop = threading.Event()
        self._on_change_callbacks: list[ChangeCallback] = []

    # -- introspection ----------------------------------------------------

    def is_available(self) -> bool:
        return self._scrcpy_path() is not None

    def get_session(self, adb_id: str) -> MirrorSession | None:
        with self._sessions_lock:
            sess = self._sessions.get(adb_id)
            if sess is None or not sess.is_running():
                return None
            return sess

    def is_mirroring(self, adb_id: str) -> bool:
        return self.get_session(adb_id) is not None

    def active_serials(self) -> list[str]:
        with self._sessions_lock:
            return [s for s, sess in self._sessions.items() if sess.is_running()]

    # -- callbacks --------------------------------------------------------

    def subscribe(self, cb: ChangeCallback) -> None:
        if cb not in self._on_change_callbacks:
            self._on_change_callbacks.append(cb)

    def unsubscribe(self, cb: ChangeCallback) -> None:
        if cb in self._on_change_callbacks:
            self._on_change_callbacks.remove(cb)

    def _emit_change(self, adb_id: str) -> None:
        for cb in list(self._on_change_callbacks):
            try:
                cb(adb_id)
            except Exception:
                log.exception("mirror change callback raised")

    # -- start / stop -----------------------------------------------------

    def start_mirror(
        self,
        adb_id: str,
        *,
        label: str = "",
        max_size: int = 1080,
        max_fps: int = 30,
        bit_rate_mbps: int = 6,
        turn_screen_off: bool = True,
        stay_awake: bool = True,
        no_audio: bool = True,
        always_on_top: bool = False,
        extra_args: list[str] | None = None,
    ) -> StartMirrorResult:
        """Spawn scrcpy for ``adb_id``. Idempotent — calling twice on the
        same device returns the existing session.

        Defaults are tuned for "phone face-down on the desk":
        - ``turn_screen_off`` keeps the OLED dark (battery + heat),
        - ``stay_awake`` overrides "screen-off → suspend" timers,
        - ``no_audio`` avoids double-routing audio (TikTok already has its),
        - ``max_size=1080`` keeps bandwidth sane vs 4 K.
        """
        if not adb_id:
            return StartMirrorResult(ok=False, error="missing_device")

        existing = self.get_session(adb_id)
        if existing is not None:
            return StartMirrorResult(ok=True, pid=existing.pid, cmd=existing.cmd)

        binary = self._scrcpy_path()
        if binary is None:
            return StartMirrorResult(
                ok=False,
                error="scrcpy_not_installed",
                install_url=install_url_for_platform(),
            )

        title = label.strip() or f"NP Create — {adb_id}"
        cmd: list[str] = [
            str(binary),
            f"--serial={adb_id}",
            f"--window-title={title}",
            f"--max-size={int(max_size)}",
            f"--max-fps={int(max_fps)}",
            f"--video-bit-rate={int(bit_rate_mbps)}M",
        ]
        if no_audio:
            cmd.append("--no-audio")
        if turn_screen_off:
            cmd.append("--turn-screen-off")
        if stay_awake:
            cmd.append("--stay-awake")
        if always_on_top:
            cmd.append("--always-on-top")
        if extra_args:
            cmd.extend(extra_args)

        env: dict[str, str] | None = None
        adb_path = self._adb_path()
        if adb_path:
            # scrcpy honours $ADB to find a specific adb binary across
            # major versions where the flag name differed.
            env = {"ADB": str(adb_path)}

        log.info("scrcpy launch: %s", " ".join(shlex.quote(c) for c in cmd))
        try:
            proc = self._sub.start(
                cmd,
                env=env,
                capture_output=False,
                detached=True,
            )
        except (FileNotFoundError, OSError) as exc:
            log.warning("scrcpy spawn failed: %s", exc)
            return StartMirrorResult(
                ok=False,
                error=f"spawn_failed: {exc}",
                install_url=install_url_for_platform(),
            )

        # Brief grace period to catch "device not found" type failures
        # that exit immediately.
        self._sleep(self._startup_grace_s)
        if proc.poll() is not None:
            log.warning("scrcpy exited immediately for %s rc=%s", adb_id, proc.returncode)
            return StartMirrorResult(
                ok=False,
                error=f"scrcpy_exited_rc{proc.returncode}",
            )

        sess = MirrorSession(
            adb_id=adb_id,
            label=title,
            pid=proc.pid,
            started_at=self._clock(),
            proc=proc,
            cmd=tuple(cmd),
        )
        with self._sessions_lock:
            self._sessions[adb_id] = sess
        self._ensure_reaper_running()
        self._emit_change(adb_id)
        return StartMirrorResult(ok=True, pid=proc.pid, cmd=tuple(cmd))

    def stop_mirror(self, adb_id: str, *, timeout: float = 3.0) -> bool:
        """Politely terminate the session. Returns True if a session was
        stopped (or none was running). Falls back to ``kill()`` after
        ``timeout`` if scrcpy refuses to exit on SIGTERM (rare)."""
        with self._sessions_lock:
            sess = self._sessions.pop(adb_id, None)
        if sess is None:
            return True
        try:
            sess.proc.terminate()
            try:
                sess.proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                log.warning("scrcpy %s ignored TERM, killing", adb_id)
                sess.proc.kill()
        except Exception:
            log.exception("error stopping scrcpy mirror for %s", adb_id)
            return False
        finally:
            self._emit_change(adb_id)
        return True

    def stop_all(self) -> None:
        with self._sessions_lock:
            ids = list(self._sessions.keys())
        for adb_id in ids:
            self.stop_mirror(adb_id, timeout=1.0)
        self._reaper_stop.set()

    # -- reaper (prune externally-closed scrcpy windows) -----------------

    def _ensure_reaper_running(self) -> None:
        if self._reaper_thread is not None and self._reaper_thread.is_alive():
            return
        self._reaper_stop.clear()
        self._reaper_thread = threading.Thread(
            target=self._reap_loop, name="np-mirror-reaper", daemon=True,
        )
        self._reaper_thread.start()

    def _reap_loop(self) -> None:
        while not self._reaper_stop.wait(self._reaper_interval_s):
            try:
                self.reap_once()
            except Exception:
                log.exception("mirror reaper crashed (will retry)")

    def reap_once(self) -> list[str]:
        """One iteration of the reaper — public so tests can drive it.

        Returns the list of adb_ids that were pruned this tick.
        """
        stale: list[str] = []
        with self._sessions_lock:
            for adb_id, sess in self._sessions.items():
                if not sess.is_running():
                    stale.append(adb_id)
            for adb_id in stale:
                log.info(
                    "scrcpy mirror exited externally for %s (pid=%s)",
                    adb_id, self._sessions[adb_id].pid,
                )
                del self._sessions[adb_id]
        for adb_id in stale:
            self._emit_change(adb_id)
        return stale
