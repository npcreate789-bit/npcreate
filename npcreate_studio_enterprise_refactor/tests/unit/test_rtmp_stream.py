"""Phase C3 — RtmpStreamService + rtmp_view tests.

Real FFmpeg isn't reachable in CI; we stub the subprocess starter with a
fake Popen that exposes ``poll``/``stderr``/``terminate``/``wait``/``kill``.
Time-sensitive behaviour (monitor loop) is driven by a fake clock and
short poll interval.
"""
from __future__ import annotations

import io
import time
from pathlib import Path
from typing import Any

from npcreate_studio.domain.streams import StreamerStats, StreamProfile, StreamStatus
from npcreate_studio.services.rtmp_stream_service import RtmpStreamService
from npcreate_studio.services.rtmp_view import (
    mask_rtmp_url,
    rtmp_status_pill,
    stream_summary,
)

# ---------- fakes -------------------------------------------------------


class _FakePopen:
    def __init__(self, *, pid: int = 4242, stderr_lines: list[str] | None = None) -> None:
        self.pid = pid
        self._exit: int | None = None
        self._terminated = False
        self._killed = False
        self.returncode: int | None = None
        # Build a stderr stream that yields the configured lines once, then EOF.
        encoded = "\n".join(stderr_lines or []) + ("\n" if stderr_lines else "")
        self.stderr = io.BytesIO(encoded.encode("utf-8")) if stderr_lines else io.BytesIO(b"")

    def set_exit(self, rc: int) -> None:
        self._exit = rc
        self.returncode = rc

    def poll(self) -> int | None:
        if self._exit is not None:
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
        return self.poll() or 0


class _FakeSub:
    def __init__(self, popen: _FakePopen | None = None) -> None:
        self.starts: list[tuple[Any, dict]] = []
        self._popen = popen or _FakePopen()
        self.error: Exception | None = None

    def start(self, args, **kwargs):
        self.starts.append((list(args), kwargs))
        if self.error is not None:
            raise self.error
        return self._popen


class _FakeMedia:
    def build_ffmpeg_args(self, playlist: Path, profile: StreamProfile, output_url: str) -> list[str]:
        return ["ffmpeg", "-re", "-i", str(playlist), "-f", "flv", output_url]


def _service(*, popen: _FakePopen | None = None, ffmpeg_path: str | None = None, poll_interval_s: float = 0.01) -> tuple[RtmpStreamService, _FakeSub]:
    sub = _FakeSub(popen=popen)
    svc = RtmpStreamService(
        media=_FakeMedia(),  # type: ignore[arg-type]
        subprocess=sub,  # type: ignore[arg-type]
        ffmpeg_path=ffmpeg_path,
        clock=time.monotonic,
        sleep_fn=lambda _s: None,
        poll_interval_s=poll_interval_s,
    )
    return svc, sub


# ---------- service lifecycle ------------------------------------------


def test_start_spawns_ffmpeg_with_built_args(tmp_path):
    svc, sub = _service()
    playlist = tmp_path / "p.txt"
    playlist.write_text("file 'a.mp4'\n")
    svc.start(playlist, StreamProfile(), "rtmp://x.example.com/app/sk")
    args, _ = sub.starts[0]
    assert args[0] == "ffmpeg"
    assert args[-1] == "rtmp://x.example.com/app/sk"
    assert svc.is_running() is True
    assert svc.stats.status == StreamStatus.STREAMING
    assert svc.stats.client_addr == "rtmp://x.example.com/app/sk"
    svc.stop()


def test_start_overrides_ffmpeg_path_when_provided(tmp_path):
    svc, sub = _service(ffmpeg_path="/opt/special/ffmpeg")
    svc.start(tmp_path / "p.txt", StreamProfile(), "rtmp://x")
    args, _ = sub.starts[0]
    assert args[0] == "/opt/special/ffmpeg"
    svc.stop()


def test_start_rejects_empty_rtmp_url(tmp_path):
    svc, _ = _service()
    import pytest

    with pytest.raises(ValueError, match="rtmp_url"):
        svc.start(tmp_path / "p.txt", StreamProfile(), "")


def test_start_rejects_double_start(tmp_path):
    svc, _ = _service()
    svc.start(tmp_path / "p.txt", StreamProfile(), "rtmp://x")
    import pytest

    with pytest.raises(RuntimeError, match="already running"):
        svc.start(tmp_path / "p.txt", StreamProfile(), "rtmp://x")
    svc.stop()


def test_start_failure_sets_error_status_and_propagates(tmp_path):
    svc, sub = _service()
    sub.error = FileNotFoundError("ffmpeg missing")
    import pytest

    with pytest.raises(FileNotFoundError):
        svc.start(tmp_path / "p.txt", StreamProfile(), "rtmp://x")
    assert svc.stats.status == StreamStatus.ERROR
    assert "ffmpeg missing" in svc.stats.last_error


def test_stop_terminates_process_and_resets_status(tmp_path):
    popen = _FakePopen()
    svc, _ = _service(popen=popen)
    svc.start(tmp_path / "p.txt", StreamProfile(), "rtmp://x")
    svc.stop()
    assert popen._terminated is True
    assert svc.is_running() is False
    assert svc.stats.status == StreamStatus.IDLE
    assert svc.stats.pid is None
    assert svc.stats.client_addr == ""


def test_stop_when_not_running_is_a_noop():
    svc, _ = _service()
    svc.stop()  # must not raise
    assert svc.stats.status == StreamStatus.IDLE


def test_monitor_detects_external_exit_and_marks_error(tmp_path):
    popen = _FakePopen(stderr_lines=["[error] connection refused"])
    svc, _ = _service(popen=popen, poll_interval_s=0.01)
    svc.start(tmp_path / "p.txt", StreamProfile(), "rtmp://x")
    # External exit before user calls stop.
    popen.set_exit(1)
    # Give the monitor thread a moment to observe the exit.
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and svc.stats.status != StreamStatus.ERROR:
        time.sleep(0.02)
    assert svc.stats.status == StreamStatus.ERROR
    assert "connection refused" in svc.stats.last_error or "rc=1" in svc.stats.last_error
    svc.stop()


def test_recent_stderr_drains_lines_from_process(tmp_path):
    lines = ["frame=  10", "frame=  20", "bitrate=2000kbits/s"]
    popen = _FakePopen(stderr_lines=lines)
    svc, _ = _service(popen=popen)
    svc.start(tmp_path / "p.txt", StreamProfile(), "rtmp://x")
    # Drain runs in a thread; wait briefly for it to consume the buffer.
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and len(svc.recent_stderr()) < 3:
        time.sleep(0.02)
    captured = svc.recent_stderr()
    for expected in lines:
        assert expected in captured
    svc.stop()


# ---------- rtmp_view ---------------------------------------------------


def test_status_pill_streaming():
    label, role = rtmp_status_pill(StreamerStats(status=StreamStatus.STREAMING))
    assert label == "Pushing RTMP"
    assert role == "success"


def test_status_pill_error():
    label, role = rtmp_status_pill(StreamerStats(status=StreamStatus.ERROR))
    assert label == "Error"
    assert role == "danger"


def test_status_pill_stopping_uses_muted():
    label, role = rtmp_status_pill(StreamerStats(status=StreamStatus.STOPPING))
    assert label == "Stopping"
    assert role == "muted"


def test_status_pill_idle_default():
    label, role = rtmp_status_pill(StreamerStats(status=StreamStatus.IDLE))
    assert label == "Idle"
    assert role == "muted"


def test_mask_rtmp_url_redacts_stream_key():
    masked = mask_rtmp_url("rtmp://live.x.com/app/sk-abcdef-1234")
    assert "sk-abcdef-1234" not in masked
    assert "sk-a" in masked
    assert masked.startswith("rtmp://live.x.com/app/")


def test_mask_rtmp_url_handles_short_segments():
    masked = mask_rtmp_url("rtmp://x.com/app/sk")  # 2-char key — too short to truncate cleanly
    assert "rtmp://x.com" in masked


def test_mask_rtmp_url_empty():
    assert mask_rtmp_url("") == "—"


def test_stream_summary_shape():
    out = stream_summary(StreamerStats(
        status=StreamStatus.STREAMING,
        uptime_s=125.0,
        client_addr="rtmp://live.x.com/app/sk-secret",
        pid=4242,
    ))
    assert out["Status"] == "streaming"
    assert out["Uptime"] == "2m 05s"
    assert "sk-secret" not in out["RTMP target"]
    assert out["PID"] == "4242"
    assert out["Last error"] == "—"


def test_stream_summary_uses_dash_for_missing_pid_and_target():
    out = stream_summary(StreamerStats(status=StreamStatus.IDLE))
    assert out["PID"] == "—"
    assert out["RTMP target"] == "—"
    assert out["Last error"] == "—"
