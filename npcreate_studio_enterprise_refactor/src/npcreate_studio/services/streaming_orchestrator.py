"""High-level entry point for the streaming pipeline.

Wires `MediaService.build_pipe_args` (FFmpeg command builder) with
`StreamServer` (1-client TCP forwarder) so the UI can just call
``orchestrator.start(playlist, profile)`` and get streaming status updates
without touching subprocess or socket APIs directly.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from ..core.settings import Settings
from ..domain.streams import StreamerStats, StreamProfile
from ..infrastructure.streaming_subprocess import StreamingSubprocess
from .media_service import MediaService
from .stream_server import StreamServer, StreamServerConfig

log = logging.getLogger(__name__)

StateCallback = Callable[[StreamerStats], None]


class StreamingOrchestrator:
    """Single façade for the Streaming pipeline.

    Mirrors the legacy `TcpStreamServer.start(playlist, profile)` shape but
    keeps the FFmpeg cmd-builder, subprocess starter, and TCP server as
    composable services so each piece can be unit-tested in isolation.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        media: MediaService,
        subprocess: StreamingSubprocess,
        ffmpeg_path: str | Path | None = None,
        on_state: StateCallback | None = None,
    ) -> None:
        self.settings = settings
        self._media = media
        self._subprocess = subprocess
        self._ffmpeg_path = ffmpeg_path
        self._on_state = on_state
        self._server: StreamServer | None = None
        self._playlist: Path | None = None
        self._profile: StreamProfile | None = None

    # -- public API ---------------------------------------------------------

    def start(self, playlist: Path, profile: StreamProfile) -> None:
        if self._server and self._server.is_running():
            raise RuntimeError("streaming already running")
        self._playlist = playlist
        self._profile = profile
        config = StreamServerConfig(host=self.settings.stream_host, port=self.settings.stream_port)
        self._server = StreamServer(
            config,
            cmd_factory=self._build_cmd,
            subprocess=self._subprocess,
            on_state=self._on_state,
        )
        self._server.start()

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.stop()
        self._server = None

    def is_running(self) -> bool:
        return bool(self._server and self._server.is_running())

    @property
    def stats(self) -> StreamerStats:
        if self._server is None:
            return StreamerStats()
        return self._server.stats

    # -- internals ----------------------------------------------------------

    def _build_cmd(self) -> list[str]:
        assert self._playlist is not None and self._profile is not None
        return self._media.build_pipe_args(self._playlist, self._profile, ffmpeg_path=self._ffmpeg_path)
