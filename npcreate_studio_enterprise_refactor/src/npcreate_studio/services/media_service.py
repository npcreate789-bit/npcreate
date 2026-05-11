"""FFmpeg command-builder + light wrappers.

Two output shapes are supported:

- `build_pipe_args` — H.264 Annex-B written to stdout, intended for the
  TCP stream server to forward to the phone receiver app.
- `build_ffmpeg_args` — FLV-over-RTMP to an external server (legacy use
  case for traditional Live broadcasts).

The probe helper uses `SubprocessRunner` (one-shot). Streaming subprocesses
must use `StreamingSubprocess` instead so stdout can be consumed live.
"""
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

    def build_pipe_args(self, playlist: Path, profile: StreamProfile, *, ffmpeg_path: str | Path | None = None) -> list[str]:
        """Build the FFmpeg command line for phone streaming (H.264 Annex-B → pipe:1).

        Tuned for low-latency real-time streaming over TCP to the receiver app:
        baseline profile + zerolatency + a fixed keyframe interval so MediaCodec
        can recover quickly on the phone side.
        """
        ffmpeg = str(ffmpeg_path) if ffmpeg_path else str(self.tools.resolve("ffmpeg"))
        keyint = max(1, int(profile.fps * profile.keyint_seconds))
        vf: list[str] = []
        if profile.rotation_filter:
            vf.append(profile.rotation_filter)
        vf.append(f"scale={profile.width}:{profile.height}:flags=bicubic")
        vf.append(f"fps={profile.fps}")
        vf.append(f"pad={profile.width}:{profile.height}:(ow-iw)/2:(oh-ih)/2:color=black")
        args: list[str] = [
            ffmpeg,
            "-hide_banner",
            "-loglevel", "warning",
            "-nostdin",
            "-re",
        ]
        if profile.loop_playlist:
            args += ["-stream_loop", "-1"]
        args += [
            "-f", "concat",
            "-safe", "0",
            "-i", str(playlist),
            "-an",
            "-vf", ",".join(vf),
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-tune", "zerolatency",
            "-profile:v", "baseline",
            "-level", "4.0",
            "-pix_fmt", "yuv420p",
            "-r", str(profile.fps),
            "-g", str(keyint),
            "-keyint_min", str(keyint),
            "-sc_threshold", "0",
            "-b:v", profile.video_bitrate,
            "-maxrate", profile.video_maxrate,
            "-bufsize", profile.video_bufsize,
            "-f", "h264",
            "pipe:1",
        ]
        return args

    def build_ffmpeg_args(self, playlist: Path, profile: StreamProfile, output_url: str) -> list[str]:
        """Legacy FLV-over-RTMP output (e.g., direct push to an RTMP relay)."""
        ffmpeg = self.tools.resolve("ffmpeg")
        return [
            str(ffmpeg), "-re", "-stream_loop", "-1" if profile.loop_playlist else "0",
            "-f", "concat", "-safe", "0", "-i", str(playlist),
            "-r", str(profile.fps),
            "-s", f"{profile.width}x{profile.height}",
            "-b:v", profile.video_bitrate, "-maxrate", profile.video_maxrate, "-bufsize", profile.video_bufsize,
            "-f", "flv", output_url,
        ]
