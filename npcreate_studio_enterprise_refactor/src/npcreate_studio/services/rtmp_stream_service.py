"""Spawn FFmpeg to push the playlist directly to an RTMP ingest URL.

Counterpart to ``StreamingOrchestrator`` (which serves bytes over TCP to a
phone receiver). Use ``RtmpStreamService`` when you want to push to a
remote RTMP server — TikTok / Facebook / Twitch / NGINX-RTMP / etc.

Lifecycle:

  start(playlist, profile, rtmp_url) → spawn FFmpeg with --output rtmp://…
  stop() → SIGTERM → wait → kill fallback
  Background monitor thread polls poll() + drains stderr so the pipe
  buffer doesn't fill; the last few stderr lines are surfaced as
  ``stats.last_error`` whenever the child exits non-zero.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path

from ..domain.streams import StreamerStats, StreamProfile, StreamStatus
from ..infrastructure.streaming_subprocess import StreamingSubprocess
from .media_service import MediaService

log = logging.getLogger(__name__)

_STDERR_RING_SIZE = 50


class RtmpStreamService:
    def __init__(
        self,
        *,
        media: MediaService,
        subprocess: StreamingSubprocess,
        ffmpeg_path: str | Path | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep_fn: Callable[[float], None] = time.sleep,
        poll_interval_s: float = 0.5,
    ) -> None:
        self._media = media
        self._subprocess = subprocess
        self._ffmpeg_path = ffmpeg_path
        self._clock = clock
        self._sleep = sleep_fn
        self._poll_interval_s = poll_interval_s
        self.stats = StreamerStats()
        self._proc = None
        self._started_at: float | None = None
        self._monitor_thread: threading.Thread | None = None
        self._stop_evt = threading.Event()
        self._stderr_ring: deque[str] = deque(maxlen=_STDERR_RING_SIZE)
        self._lock = threading.RLock()

    # -- public API -------------------------------------------------------

    def start(self, playlist: Path, profile: StreamProfile, rtmp_url: str) -> None:
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                raise RuntimeError("RTMP stream already running")
            if not rtmp_url:
                raise ValueError("rtmp_url is required")
            # MediaService builds the canonical RTMP argv (flv + scale + bitrate).
            args = self._media.build_ffmpeg_args(playlist, profile, rtmp_url)
            if self._ffmpeg_path:
                args = [str(self._ffmpeg_path), *args[1:]]
            try:
                self._proc = self._subprocess.start(args)
            except Exception as exc:
                log.exception("rtmp ffmpeg spawn failed")
                self.stats.status = StreamStatus.ERROR
                self.stats.last_error = str(exc)[:200]
                raise
            self._started_at = self._clock()
            self._stderr_ring.clear()
            self.stats.pid = self._proc.pid
            self.stats.status = StreamStatus.STREAMING
            self.stats.client_addr = rtmp_url
            self.stats.last_error = ""
            self.stats.bytes_sent = 0
            self.stats.frames_sent = 0
            self.stats.uptime_s = 0.0
            self._stop_evt.clear()
            self._monitor_thread = threading.Thread(target=self._monitor_loop, name="np-rtmp-monitor", daemon=True)
            self._monitor_thread.start()

    def stop(self, *, terminate_timeout_s: float = 3.0) -> None:
        with self._lock:
            proc = self._proc
            if proc is None:
                return
            self.stats.status = StreamStatus.STOPPING
        self._stop_evt.set()
        if proc.poll() is None:
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=terminate_timeout_s)
                except Exception:
                    proc.kill()
                    try:
                        proc.wait(timeout=2.0)
                    except Exception:
                        pass
            except Exception:
                log.exception("rtmp ffmpeg terminate failed")
        if self._monitor_thread is not None:
            self._monitor_thread.join(timeout=2.0)
        with self._lock:
            self._proc = None
            self._started_at = None
            self.stats.status = StreamStatus.IDLE
            self.stats.pid = None
            self.stats.client_addr = ""

    def is_running(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def recent_stderr(self) -> list[str]:
        """Snapshot of the last few stderr lines (newest last). Useful for the
        UI to surface FFmpeg warnings/errors without dumping the whole stream."""
        with self._lock:
            return list(self._stderr_ring)

    # -- internals --------------------------------------------------------

    def _monitor_loop(self) -> None:
        """Drain stderr to keep the pipe buffer from filling, advance uptime,
        and detect child exit (either clean or via crash)."""
        proc = self._proc
        if proc is None:
            return
        # Background stderr drain — keep the buffer empty so FFmpeg never
        # blocks on stderr write.
        def _drain_stderr() -> None:
            assert proc.stderr is not None
            try:
                for raw in proc.stderr:
                    line = (raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw).rstrip()
                    if line:
                        with self._lock:
                            self._stderr_ring.append(line)
            except Exception:
                log.debug("rtmp stderr drain ended", exc_info=True)

        drain_thread = threading.Thread(target=_drain_stderr, name="np-rtmp-stderr", daemon=True)
        drain_thread.start()

        while not self._stop_evt.wait(self._poll_interval_s):
            rc = proc.poll()
            now = self._clock()
            with self._lock:
                if self._started_at is not None:
                    self.stats.uptime_s = max(0.0, now - self._started_at)
                if rc is not None:
                    # Child exited on its own.
                    if rc == 0:
                        self.stats.status = StreamStatus.IDLE
                    else:
                        self.stats.status = StreamStatus.ERROR
                        if self._stderr_ring:
                            self.stats.last_error = self._stderr_ring[-1][:200]
                        else:
                            self.stats.last_error = f"ffmpeg exited rc={rc}"
                    self.stats.pid = None
                    self._proc = None
                    break
        drain_thread.join(timeout=1.0)
