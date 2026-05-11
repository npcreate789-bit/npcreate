"""Pure presentation helpers for the RTMP Stream page.

Split out so the formatters can be unit-tested without instantiating Tk.
"""
from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlparse

from ..domain.streams import StreamerStats, StreamStatus
from .live_view import format_uptime


def rtmp_status_pill(stats: StreamerStats) -> tuple[str, str]:
    """Return (label, color_role) for the status pill on the Stream page."""
    if stats.status == StreamStatus.STREAMING:
        return ("Pushing RTMP", "success")
    if stats.status == StreamStatus.STOPPING:
        return ("Stopping", "muted")
    if stats.status == StreamStatus.ERROR:
        return ("Error", "danger")
    return ("Idle", "muted")


def mask_rtmp_url(url: str) -> str:
    """Hide the stream key portion so screen-shots / logs don't leak it.

    For ``rtmp://live.x.com/app/sk-abcdef`` we want
    ``rtmp://live.x.com/app/sk-ab…``. The path's last segment is the secret.
    """
    if not url:
        return "—"
    try:
        parsed = urlparse(url)
    except ValueError:
        return url
    host = parsed.netloc or "?"
    path = parsed.path.rstrip("/") or ""
    if not path:
        return f"{parsed.scheme}://{host}/"
    segments = path.split("/")
    last = segments[-1]
    if len(last) > 4:
        masked_last = last[:4] + "…"
        segments[-1] = masked_last
    masked_path = "/".join(segments)
    return f"{parsed.scheme}://{host}{masked_path}"


def stream_summary(stats: StreamerStats) -> Mapping[str, str]:
    """Dict ของ label → value สำหรับ Card สรุปสถานะ FFmpeg."""
    return {
        "Status": stats.status.value,
        "Uptime": format_uptime(stats.uptime_s),
        "RTMP target": mask_rtmp_url(stats.client_addr),
        "PID": str(stats.pid) if stats.pid else "—",
        "Last error": stats.last_error or "—",
    }
