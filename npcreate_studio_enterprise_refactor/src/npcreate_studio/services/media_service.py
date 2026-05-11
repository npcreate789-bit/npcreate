from __future__ import annotations

from pathlib import Path

from ..domain.streams import StreamProfile
from ..infrastructure.subprocess_runner import SubprocessRunner
from ..infrastructure.toolchain import ToolchainResolver


class MediaService:
    def __init__(self, tools: ToolchainResolver, runner: SubprocessRunner) -> None:
        self.tools = tools
        self.runner = runner

    def probe(self, media_path: Path) -> bool:
        ffprobe = self.tools.resolve("ffprobe")
        result = self.runner.run([ffprobe, "-v", "error", "-show_format", media_path], timeout=15)
        return result.returncode == 0

    def build_ffmpeg_args(self, playlist: Path, profile: StreamProfile, output_url: str) -> list[str]:
        ffmpeg = self.tools.resolve("ffmpeg")
        return [
            str(ffmpeg), "-re", "-stream_loop", "-1" if profile.loop_playlist else "0",
            "-f", "concat", "-safe", "0", "-i", str(playlist),
            "-r", str(profile.fps), "-s", profile.resolution,
            "-b:v", profile.video_bitrate, "-maxrate", profile.maxrate, "-bufsize", profile.bufsize,
            "-f", "flv", output_url,
        ]
