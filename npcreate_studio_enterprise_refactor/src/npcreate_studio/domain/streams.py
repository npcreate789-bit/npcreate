from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class StreamStatus(str, Enum):
    IDLE = "idle"
    PREPARING = "preparing"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


@dataclass(frozen=True)
class StreamProfile:
    resolution: str = "720x1280"
    fps: int = 30
    video_bitrate: str = "2000k"
    maxrate: str = "2500k"
    bufsize: str = "4000k"
    loop_playlist: bool = True
