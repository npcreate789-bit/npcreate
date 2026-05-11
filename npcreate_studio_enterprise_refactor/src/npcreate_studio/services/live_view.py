"""Pure presentation helpers for the Live page.

We split these out of ``ui/pages/live_page.py`` so they can be unit-tested
without instantiating CustomTkinter (which requires a Tk display).

The helpers convert raw service state (``StreamerStats``, ``HealthSnapshot``)
into human-readable strings + a status pill ``(text, color_role)`` tuple.
"""
from __future__ import annotations

from collections.abc import Mapping

from ..domain.streams import StreamerStats, StreamStatus
from .health_monitor import HealthSnapshot

# Color roles mapped to theme constants by the GUI layer (live_page).
COLOR_IDLE = "muted"
COLOR_LISTENING = "info"
COLOR_STREAMING = "success"
COLOR_ERROR = "danger"
COLOR_WARNING = "warning"


def stream_status_pill(stats: StreamerStats, snap: HealthSnapshot | None = None) -> tuple[str, str]:
    """Return (label, color_role) for the big status pill at the top of the page.

    `snap` overrides the headline label when the pipeline is stalled even
    while the server thinks it's still streaming — the user wants to see the
    most actionable state first.
    """
    if snap is not None and snap.is_stalled:
        return ("Stalled", COLOR_WARNING)
    if stats.status == StreamStatus.IDLE:
        return ("Idle", COLOR_IDLE)
    if stats.status == StreamStatus.LISTENING:
        return ("Waiting for phone", COLOR_LISTENING)
    if stats.status == StreamStatus.CLIENT_CONNECTED:
        return ("Phone connected", COLOR_STREAMING)
    if stats.status == StreamStatus.STREAMING:
        return ("Live", COLOR_STREAMING)
    if stats.status == StreamStatus.STOPPING:
        return ("Stopping", COLOR_IDLE)
    if stats.status == StreamStatus.ERROR:
        return ("Error", COLOR_ERROR)
    return (stats.status.value, COLOR_IDLE)


def bytes_human(n: float) -> str:
    """Format a byte count using binary (KiB/MiB/GiB) units. Always 1 decimal."""
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    value = float(n)
    for unit in units:
        if abs(value) < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} TiB"


def format_uptime(seconds: float) -> str:
    s = int(max(0.0, seconds))
    if s < 60:
        return f"{s}s"
    minutes, sec = divmod(s, 60)
    if minutes < 60:
        return f"{minutes}m {sec:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def pc_summary(stats: StreamerStats, *, bytes_per_sec: float = 0.0) -> Mapping[str, str]:
    """Dict ของ label → value สำหรับ Card "PC" ใน Live page."""
    return {
        "Status": stats.status.value,
        "Client": stats.client_addr or "—",
        "Uptime": format_uptime(stats.uptime_s),
        "Total sent": bytes_human(stats.bytes_sent),
        "Rate": f"{bytes_human(bytes_per_sec)}/s",
        "Frames~": str(stats.frames_sent),
        "PID": str(stats.pid) if stats.pid else "—",
    }


def phone_summary(snap: HealthSnapshot | None) -> Mapping[str, str]:
    """Dict ของ label → value สำหรับ Card "Phone" ใน Live page."""
    if snap is None or snap.phone_yuv_path is None:
        return {
            "YUV path": "—",
            "Size": "—",
            "Age": "—",
            "ADB": "ไม่ทราบ (กด Bridge to phone)",
        }
    return {
        "YUV path": snap.phone_yuv_path,
        "Size": bytes_human(snap.phone_yuv_size or 0),
        "Age": f"{snap.phone_yuv_fresh_s:.1f}s" if snap.phone_yuv_fresh_s is not None else "—",
        "ADB": "OK" if snap.phone_yuv_size is not None else "ไม่พบไฟล์",
    }


def health_warning(snap: HealthSnapshot | None) -> str | None:
    """One-line warning string when the pipeline looks stuck."""
    if snap is None:
        return None
    if snap.is_stalled:
        return f"⚠ Stalled {int(snap.stalled_for_s)}s — ตรวจ phone receiver และ adb reverse"
    if snap.stalled_for_s >= 1.0 and not snap.is_progressing:
        return f"Idle {int(snap.stalled_for_s)}s (ยังไม่ส่งข้อมูล)"
    return None
