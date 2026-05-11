"""Phase A1 streaming pipeline tests.

We exercise the real `subprocess` + `socket` stack — using `sys.executable` as
a stand-in for FFmpeg so tests don't need ffmpeg installed. The fake child
prints H.264-shaped bytes (Annex-B start codes + payload) so the pump and
frame-counter logic see realistic input.
"""
from __future__ import annotations

import socket
import sys
import time
from pathlib import Path

import pytest

from npcreate_studio.core.errors import SubprocessBlocked
from npcreate_studio.core.settings import Settings
from npcreate_studio.domain.streams import StreamProfile, StreamStatus
from npcreate_studio.infrastructure.streaming_subprocess import (
    StreamingPolicy,
    StreamingSubprocess,
)
from npcreate_studio.services.media_service import MediaService
from npcreate_studio.services.stream_server import (
    StreamServer,
    StreamServerConfig,
)
from npcreate_studio.services.streaming_orchestrator import StreamingOrchestrator

PYTHON_EXE = Path(sys.executable)
PYTHON_NAME = PYTHON_EXE.name


def _allow_python_policy() -> StreamingPolicy:
    return StreamingPolicy(allowed_names=frozenset({PYTHON_NAME}))


# ---------- StreamingSubprocess ----------


def test_streaming_subprocess_rejects_unknown_executable():
    sub = StreamingSubprocess(StreamingPolicy(allowed_names=frozenset({"ffmpeg"})))
    with pytest.raises(SubprocessBlocked):
        sub.start(["bash", "-c", "echo hi"])


def test_streaming_subprocess_rejects_empty_args():
    sub = StreamingSubprocess(_allow_python_policy())
    with pytest.raises(ValueError):
        sub.start([])


def test_streaming_subprocess_starts_and_streams_stdout():
    sub = StreamingSubprocess(_allow_python_policy())
    proc = sub.start([str(PYTHON_EXE), "-c", "import sys; sys.stdout.buffer.write(b'hello'); sys.stdout.buffer.flush()"])
    try:
        out = proc.stdout.read(5)
        assert out == b"hello"
    finally:
        proc.wait(timeout=5)


def test_streaming_subprocess_sanitizes_env_to_allowlist():
    """Random env vars from os.environ must NOT leak; NPCREATE_* only flows
    through when explicitly passed via the extra_env kwarg (matching the
    SubprocessRunner contract)."""
    import os

    os.environ["DEFINITELY_NOT_ALLOWED_XYZ"] = "bad"
    try:
        sub = StreamingSubprocess(_allow_python_policy())
        proc = sub.start(
            [
                str(PYTHON_EXE), "-c",
                "import os, sys; "
                "sys.stdout.buffer.write(b'leak' if 'DEFINITELY_NOT_ALLOWED_XYZ' in os.environ else b'safe'); "
                "sys.stdout.buffer.write(b'-'); "
                "sys.stdout.buffer.write(b'npc-ok' if os.environ.get('NPCREATE_OPT_IN')=='yes' else b'npc-missing'); "
                "sys.stdout.buffer.flush()",
            ],
            env={"NPCREATE_OPT_IN": "yes"},
        )
        out = proc.stdout.read(64)
        proc.wait(timeout=5)
    finally:
        del os.environ["DEFINITELY_NOT_ALLOWED_XYZ"]
    assert b"safe-" in out  # arbitrary env var filtered out
    assert b"npc-ok" in out  # NPCREATE_* passed via extra_env got through


# ---------- MediaService.build_pipe_args ----------


def test_build_pipe_args_outputs_h264_to_pipe():
    media = MediaService(tools=None, runner=None)  # we pass ffmpeg_path directly
    profile = StreamProfile(width=720, height=1280, fps=30, video_bitrate="2000k",
                            video_maxrate="2500k", video_bufsize="4000k",
                            keyint_seconds=2, loop_playlist=True)
    args = media.build_pipe_args(Path("/tmp/playlist.txt"), profile, ffmpeg_path="/usr/bin/ffmpeg")
    assert args[0] == "/usr/bin/ffmpeg"
    assert args[-1] == "pipe:1"
    assert "-f" in args and args[args.index("-f", args.index("-f") + 1) + 1] == "h264"  # second -f is h264
    # Encoder + tuning
    assert "libx264" in args
    assert "zerolatency" in args
    assert "baseline" in args
    assert "yuv420p" in args
    # Filter chain has scale + fps + pad
    vf_index = args.index("-vf")
    assert "scale=720:1280" in args[vf_index + 1]
    assert "fps=30" in args[vf_index + 1]
    assert "pad=720:1280" in args[vf_index + 1]


def test_build_pipe_args_inserts_rotation_filter_first():
    media = MediaService(tools=None, runner=None)
    profile = StreamProfile(rotation_filter="transpose=1")
    args = media.build_pipe_args(Path("p.txt"), profile, ffmpeg_path="ffmpeg")
    vf = args[args.index("-vf") + 1]
    assert vf.startswith("transpose=1,")


def test_build_pipe_args_keyint_derived_from_fps_times_keyint_seconds():
    media = MediaService(tools=None, runner=None)
    profile = StreamProfile(fps=30, keyint_seconds=4)
    args = media.build_pipe_args(Path("p.txt"), profile, ffmpeg_path="ffmpeg")
    assert "-g" in args and args[args.index("-g") + 1] == "120"
    assert "-keyint_min" in args and args[args.index("-keyint_min") + 1] == "120"


def test_build_pipe_args_omits_loop_when_disabled():
    media = MediaService(tools=None, runner=None)
    profile = StreamProfile(loop_playlist=False)
    args = media.build_pipe_args(Path("p.txt"), profile, ffmpeg_path="ffmpeg")
    assert "-stream_loop" not in args


# ---------- StreamServer (1-client TCP, pump fake child) ----------


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


FAKE_FFMPEG = r"""
import sys, time
for i in range(40):
    sys.stdout.buffer.write(b'\x00\x00\x00\x01' + bytes([i % 256] * 256))
    sys.stdout.buffer.flush()
    time.sleep(0.01)
"""


def _build_server(port: int, fake_script: str = FAKE_FFMPEG) -> StreamServer:
    sub = StreamingSubprocess(_allow_python_policy())
    cmd = [str(PYTHON_EXE), "-c", fake_script]
    return StreamServer(
        StreamServerConfig(host="127.0.0.1", port=port, accept_timeout_s=0.2),
        cmd_factory=lambda: cmd,
        subprocess=sub,
    )


def _wait_for_listen(host: str, port: int, *, timeout_s: float = 3.0) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.1):
                return
        except OSError:
            time.sleep(0.02)
    raise AssertionError(f"server never listened on {host}:{port}")


def test_stream_server_listens_then_pumps_to_client():
    port = _free_port()
    server = _build_server(port)
    server.start()
    try:
        _wait_for_listen("127.0.0.1", port)
        with socket.create_connection(("127.0.0.1", port), timeout=3) as client:
            received = b""
            client.settimeout(2)
            while len(received) < 1024:
                chunk = client.recv(4096)
                if not chunk:
                    break
                received += chunk
        # We should see at least one Annex-B start code in the bytes that came through.
        assert b"\x00\x00\x00\x01" in received
    finally:
        server.stop()
    assert server.stats.bytes_sent >= len(received)
    assert server.stats.frames_sent >= 1


def test_stream_server_resets_after_client_disconnect():
    port = _free_port()
    server = _build_server(port)
    server.start()
    try:
        _wait_for_listen("127.0.0.1", port)
        # First client connects and disconnects.
        with socket.create_connection(("127.0.0.1", port), timeout=2) as c1:
            c1.recv(512)
        # Server should still be running and ready to accept again.
        deadline = time.time() + 2.0
        while time.time() < deadline:
            if server.stats.status.value == "listening":
                break
            time.sleep(0.05)
        assert server.stats.status.value == "listening"
        # Second client succeeds — fresh stream.
        with socket.create_connection(("127.0.0.1", port), timeout=2) as c2:
            c2.recv(256)
        assert server.stats.bytes_sent > 0
    finally:
        server.stop()


def test_stream_server_reports_bind_error_on_busy_port():
    port = _free_port()
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    blocker.bind(("127.0.0.1", port))
    blocker.listen(1)
    try:
        server = _build_server(port)
        server.start()
        deadline = time.time() + 2.0
        while time.time() < deadline:
            if server.stats.status == StreamStatus.ERROR:
                break
            time.sleep(0.05)
        assert server.stats.status == StreamStatus.ERROR
        assert "bind failed" in server.stats.last_error
        server.stop()
    finally:
        blocker.close()


def test_stream_server_stop_kills_child_subprocess():
    port = _free_port()
    # A child that would otherwise run forever; we want to verify stop() reaps it.
    long_script = "import sys, time\nwhile True:\n  sys.stdout.buffer.write(b'\\x00\\x00\\x00\\x01' + b'A'*512); sys.stdout.buffer.flush(); time.sleep(0.01)\n"
    server = _build_server(port, fake_script=long_script)
    server.start()
    try:
        _wait_for_listen("127.0.0.1", port)
        with socket.create_connection(("127.0.0.1", port), timeout=2) as c:
            c.recv(1024)
            time.sleep(0.1)
            child_pid = server.stats.pid
            assert child_pid is not None
            # Stop the server; child should be reaped.
            server.stop(join_timeout_s=4)
            # Confirm the child is gone (raises ProcessLookupError or OSError on second kill).
            time.sleep(0.1)
            with pytest.raises(OSError):
                # Sending signal 0 verifies presence without killing; absence raises.
                import os
                os.kill(child_pid, 0)
    finally:
        # Defensive stop in case the test failed before reaching the stop above.
        if server.is_running():
            server.stop()


# ---------- StreamingOrchestrator (façade) ----------


def test_orchestrator_starts_with_settings_port_and_routes_state(tmp_path, monkeypatch):
    monkeypatch.setenv("NPCREATE_STREAM_HOST", "127.0.0.1")
    monkeypatch.setenv("NPCREATE_STREAM_PORT", str(_free_port()))
    settings = Settings()

    # Use Python as a fake FFmpeg via build_pipe_args bypass: orchestrator calls
    # media.build_pipe_args, but for the test we route through a stubbed cmd_factory.
    states: list[str] = []

    class StubMedia:
        def build_pipe_args(self, playlist, profile, *, ffmpeg_path=None):
            return [str(PYTHON_EXE), "-c", FAKE_FFMPEG]

    orch = StreamingOrchestrator(
        settings=settings,
        media=StubMedia(),  # type: ignore[arg-type]
        subprocess=StreamingSubprocess(_allow_python_policy()),
        on_state=lambda s: states.append(s.status.value),
    )

    playlist = tmp_path / "playlist.txt"
    playlist.write_text("file 'video.mp4'\n")
    orch.start(playlist, StreamProfile())
    try:
        _wait_for_listen(settings.stream_host, settings.stream_port)
        with socket.create_connection((settings.stream_host, settings.stream_port), timeout=2) as c:
            assert c.recv(256)
    finally:
        orch.stop()
    assert "listening" in states
    assert "client_connected" in states
    assert "streaming" in states


def test_orchestrator_rejects_double_start(tmp_path):
    settings = Settings(stream_port=_free_port())

    class StubMedia:
        def build_pipe_args(self, playlist, profile, *, ffmpeg_path=None):
            return [str(PYTHON_EXE), "-c", "import time; time.sleep(2)"]

    orch = StreamingOrchestrator(
        settings=settings,
        media=StubMedia(),  # type: ignore[arg-type]
        subprocess=StreamingSubprocess(_allow_python_policy()),
    )
    playlist = tmp_path / "p.txt"
    playlist.write_text("file 'a.mp4'\n")
    orch.start(playlist, StreamProfile())
    try:
        _wait_for_listen(settings.stream_host, settings.stream_port)
        with pytest.raises(RuntimeError, match="already running"):
            orch.start(playlist, StreamProfile())
    finally:
        orch.stop()


def test_orchestrator_stats_default_idle_before_start():
    settings = Settings(stream_port=_free_port())
    orch = StreamingOrchestrator(
        settings=settings,
        media=None,  # type: ignore[arg-type]
        subprocess=StreamingSubprocess(_allow_python_policy()),
    )
    assert orch.stats.status == StreamStatus.IDLE
    assert orch.is_running() is False
