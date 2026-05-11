"""Background poller for live streaming sessions — ported from legacy
``vcam-pc/src/health.py``.

Combines two signals per tick:

1. **PC side** — current ``StreamerStats`` (bytes_sent, frames_sent, uptime,
   client_addr) supplied by a caller-provided ``stats_provider`` callable
   so we don't couple the monitor to a specific server implementation.
2. **Phone side** — the YUV frame file written by the receiver app on the
   phone. We use ``adb shell stat`` to read size + mtime; the receiver
   rewrites the file in-place so size stays constant, but mtime advances
   on every decoded frame. If both bytes/sec on PC AND phone YUV mtime
   stall, we treat the pipeline as stuck and emit a warning.

The monitor exposes ``tick()`` publicly so tests can drive iterations
deterministically without spinning up a thread.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from ..domain.streams import StreamerStats
from .adb_service import AdbService

log = logging.getLogger(__name__)

DEFAULT_PHONE_YUV_PATHS: tuple[str, ...] = (
    "/data/data/com.npcreate.studio.receiver/files/vcam.yuv",
    "/data/local/tmp/vcam.yuv",
)
DEFAULT_BYTES_PROGRESS_THRESHOLD = 1024  # bytes/sec below this is "stalled"
DEFAULT_STALL_WARN_AFTER_S = 8.0


@dataclass
class HealthSnapshot:
    pc_bytes_sent: int = 0
    pc_frames_sent: int = 0
    pc_uptime_s: float = 0.0
    pc_client_addr: str = ""
    pc_bytes_per_sec: float = 0.0
    phone_yuv_size: int | None = None
    phone_yuv_mtime: int | None = None
    phone_yuv_path: str | None = None
    phone_yuv_fresh_s: float | None = None
    stalled_for_s: float = 0.0
    is_stalled: bool = False
    is_progressing: bool = False
    last_progress_at: float = field(default_factory=time.monotonic)


StatsProvider = Callable[[], StreamerStats]
SnapshotCallback = Callable[[HealthSnapshot], None]


class HealthMonitor:
    def __init__(
        self,
        *,
        stats_provider: StatsProvider,
        adb: AdbService,
        interval_s: float = 5.0,
        phone_yuv_paths: tuple[str, ...] = DEFAULT_PHONE_YUV_PATHS,
        phone_app_package: str = "com.npcreate.studio.receiver",
        stall_warn_after_s: float = DEFAULT_STALL_WARN_AFTER_S,
        bytes_progress_threshold: int = DEFAULT_BYTES_PROGRESS_THRESHOLD,
        on_snapshot: SnapshotCallback | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._stats_provider = stats_provider
        self._adb = adb
        self._interval_s = interval_s
        self._phone_yuv_paths = phone_yuv_paths
        self._phone_app_package = phone_app_package
        self._stall_warn_after_s = stall_warn_after_s
        self._bytes_progress_threshold = bytes_progress_threshold
        self._on_snapshot = on_snapshot
        self._clock = clock

        self._stop_evt = threading.Event()
        self._thread: threading.Thread | None = None
        self._snapshot = HealthSnapshot(last_progress_at=clock())
        self._last_bytes_sent = 0
        self._resolved_phone_path: str | None = None
        self._adb_failures = 0
        self._max_adb_failures_before_giveup = 6

    # -- lifecycle --------------------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        # Reset the stall clock so we don't immediately fire a false-alarm
        # warning if the monitor was constructed minutes before the user
        # actually pressed Start (e.g. constructed in build_services at app
        # launch). Without this, last_progress_at carries the construction
        # timestamp and the very first tick records `stalled_for_s = T_now -
        # T_app_start` — a phantom stall.
        now = self._clock()
        self._snapshot.last_progress_at = now
        self._snapshot.stalled_for_s = 0.0
        self._snapshot.is_stalled = False
        self._last_bytes_sent = 0
        self._stop_evt.clear()
        self._thread = threading.Thread(target=self._loop, name="np-health", daemon=True)
        self._thread.start()

    def stop(self, *, join_timeout_s: float = 2.0) -> None:
        self._stop_evt.set()
        if self._thread is not None:
            self._thread.join(timeout=join_timeout_s)

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    @property
    def snapshot(self) -> HealthSnapshot:
        return self._snapshot

    # -- per-tick logic (public for tests) --------------------------------

    def tick(self) -> HealthSnapshot:
        snap = self._snapshot
        stats = self._stats_provider()

        bytes_now = stats.bytes_sent
        snap.pc_bytes_per_sec = max(0.0, (bytes_now - self._last_bytes_sent) / max(self._interval_s, 0.001))
        self._last_bytes_sent = bytes_now

        snap.pc_bytes_sent = bytes_now
        snap.pc_frames_sent = stats.frames_sent
        snap.pc_uptime_s = stats.uptime_s
        snap.pc_client_addr = stats.client_addr

        prev_mtime = snap.phone_yuv_mtime
        size, mtime, path, device_now = self._probe_phone_yuv()
        snap.phone_yuv_size = size
        snap.phone_yuv_mtime = mtime
        snap.phone_yuv_path = path
        snap.phone_yuv_fresh_s = max(0.0, device_now - mtime) if (mtime is not None and device_now is not None) else None

        mtime_advanced = prev_mtime is not None and mtime is not None and mtime > prev_mtime
        snap.is_progressing = (snap.pc_bytes_per_sec > self._bytes_progress_threshold) or mtime_advanced

        now = self._clock()
        if snap.is_progressing:
            snap.last_progress_at = now
            snap.stalled_for_s = 0.0
        else:
            snap.stalled_for_s = max(0.0, now - snap.last_progress_at)

        snap.is_stalled = snap.stalled_for_s >= self._stall_warn_after_s

        line = self._format_line(snap)
        if snap.is_stalled:
            log.warning("[stat] %s", line)
        else:
            log.info("[stat] %s", line)

        if self._on_snapshot is not None:
            try:
                self._on_snapshot(snap)
            except Exception:
                log.exception("on_snapshot callback failed")

        return snap

    # -- internals --------------------------------------------------------

    def _loop(self) -> None:
        while not self._stop_evt.wait(self._interval_s):
            try:
                self.tick()
            except Exception:
                log.exception("health tick failed")

    def _probe_phone_yuv(self) -> tuple[int | None, int | None, str | None, int | None]:
        if not self._adb.is_available() or self._adb_failures > self._max_adb_failures_before_giveup:
            return None, None, None, None
        if self._resolved_phone_path is None:
            for candidate in self._phone_yuv_paths:
                size, mtime = self._stat_remote(candidate)
                if size is not None:
                    self._resolved_phone_path = candidate
                    return size, mtime, candidate, self._device_now()
            return None, None, None, None
        size, mtime = self._stat_remote(self._resolved_phone_path)
        return size, mtime, self._resolved_phone_path, self._device_now()

    def _stat_remote(self, path: str) -> tuple[int | None, int | None]:
        pkg_prefix = f"/data/data/{self._phone_app_package}/"
        if path.startswith(pkg_prefix):
            rel = path[len(pkg_prefix):]
            cmd = f"run-as {self._phone_app_package} stat -c '%s %Y' {rel}"
        else:
            cmd = f"stat -c '%s %Y' {path}"
        out = self._adb.shell(cmd, timeout=3).strip()
        if not out:
            self._adb_failures += 1
            return None, None
        parts = out.split()
        if len(parts) < 2 or not parts[0].lstrip("-").isdigit() or not parts[1].lstrip("-").isdigit():
            return None, None
        self._adb_failures = 0
        return int(parts[0]), int(parts[1])

    def _device_now(self) -> int | None:
        out = self._adb.shell("date +%s", timeout=3).strip()
        return int(out) if out.isdigit() else None

    @staticmethod
    def _format_line(snap: HealthSnapshot) -> str:
        mb = snap.pc_bytes_sent / (1024 * 1024)
        rate_kib = snap.pc_bytes_per_sec / 1024
        parts = [
            f"up={snap.pc_uptime_s:5.0f}s",
            f"pc={mb:6.2f}MB",
            f"rate={rate_kib:6.1f}KiB/s",
            f"frames~{snap.pc_frames_sent}",
            f"client={snap.pc_client_addr or '—'}",
        ]
        if snap.phone_yuv_size is not None:
            parts.append(f"phone_yuv={snap.phone_yuv_size // 1024}KiB")
            if snap.phone_yuv_fresh_s is not None:
                parts.append(f"age={snap.phone_yuv_fresh_s:.1f}s")
        else:
            parts.append("phone_yuv=?")
        if snap.stalled_for_s >= 1.0:
            parts.append(f"stall={snap.stalled_for_s:.0f}s")
        return "  ".join(parts)
