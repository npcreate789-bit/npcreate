from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class StreamStatus(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    CLIENT_CONNECTED = "client_connected"
    STREAMING = "streaming"
    STOPPING = "stopping"
    ERROR = "error"


@dataclass(frozen=True)
class StreamProfile:
    """Encoding settings the FFmpeg streamer hands to libx264.

    Mirrors the legacy StreamConfig fields that actually shape the wire
    format (size + bitrate + keyint), plus an optional rotation filter for
    devices whose native sensor orientation differs from playback.
    """

    width: int = 720
    height: int = 1280
    fps: int = 30
    video_bitrate: str = "2000k"
    video_maxrate: str = "2500k"
    video_bufsize: str = "4000k"
    keyint_seconds: int = 2
    loop_playlist: bool = True
    rotation_filter: str = ""  # "transpose=1", "hflip,vflip", etc. — "" means none


@dataclass
class StreamerStats:
    """Snapshot of the streaming pipeline state. Mutable on purpose so the
    server thread can update counters without re-allocating."""

    status: StreamStatus = StreamStatus.IDLE
    pid: int | None = None
    bytes_sent: int = 0
    frames_sent: int = 0  # approximate — counts Annex-B start codes
    uptime_s: float = 0.0
    client_addr: str = ""
    last_error: str = ""
