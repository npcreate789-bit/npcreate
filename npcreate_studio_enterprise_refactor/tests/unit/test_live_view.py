"""Pure-logic tests for live_view helpers (no CustomTkinter, no display)."""
from __future__ import annotations

from npcreate_studio.domain.streams import StreamerStats, StreamStatus
from npcreate_studio.services.health_monitor import HealthSnapshot
from npcreate_studio.services.live_view import (
    bytes_human,
    format_uptime,
    health_warning,
    pc_summary,
    phone_summary,
    stream_status_pill,
)

# -- stream_status_pill ----------------------------------------------------


def test_status_pill_idle():
    assert stream_status_pill(StreamerStats(status=StreamStatus.IDLE)) == ("Idle", "muted")


def test_status_pill_listening_translates_to_waiting():
    assert stream_status_pill(StreamerStats(status=StreamStatus.LISTENING)) == ("Waiting for phone", "info")


def test_status_pill_streaming_shows_live():
    assert stream_status_pill(StreamerStats(status=StreamStatus.STREAMING)) == ("Live", "success")


def test_status_pill_error_uses_danger_color():
    label, role = stream_status_pill(StreamerStats(status=StreamStatus.ERROR))
    assert role == "danger"
    assert label == "Error"


def test_status_pill_overrides_with_stalled_warning_when_pipeline_stuck():
    """Even if server thinks status is STREAMING, a stalled snapshot must win
    so the user sees the actionable state."""
    stats = StreamerStats(status=StreamStatus.STREAMING)
    snap = HealthSnapshot(is_stalled=True, stalled_for_s=12.3)
    label, role = stream_status_pill(stats, snap)
    assert label == "Stalled"
    assert role == "warning"


def test_status_pill_unknown_status_falls_back_gracefully():
    # Construct a stats object whose status enum value is not in any branch
    # (the helper should return (status.value, "muted") as a safety net).
    stats = StreamerStats(status=StreamStatus.STOPPING)
    label, role = stream_status_pill(stats)
    assert label == "Stopping"
    assert role == "muted"


# -- bytes_human ----------------------------------------------------------


def test_bytes_human_zero_returns_bytes_unit():
    assert bytes_human(0) == "0 B"


def test_bytes_human_small_values_stay_in_bytes():
    assert bytes_human(512) == "512 B"


def test_bytes_human_kib_threshold():
    assert bytes_human(1024) == "1.0 KiB"
    assert bytes_human(2048) == "2.0 KiB"


def test_bytes_human_mib_and_gib():
    assert bytes_human(1024 * 1024).startswith("1.0 MiB")
    assert bytes_human(5 * 1024 * 1024 * 1024).startswith("5.0 GiB")


# -- format_uptime --------------------------------------------------------


def test_format_uptime_seconds():
    assert format_uptime(0) == "0s"
    assert format_uptime(7.4) == "7s"


def test_format_uptime_minutes_and_seconds():
    assert format_uptime(125) == "2m 05s"


def test_format_uptime_hours():
    assert format_uptime(3661) == "1h 01m"


# -- pc_summary -----------------------------------------------------------


def test_pc_summary_includes_all_expected_keys():
    stats = StreamerStats(
        status=StreamStatus.STREAMING,
        bytes_sent=1024 * 1024,  # 1 MiB
        frames_sent=180,
        uptime_s=65.0,
        client_addr="10.0.0.5:51234",
        pid=99999,
    )
    out = pc_summary(stats, bytes_per_sec=2048.0)
    assert out["Status"] == "streaming"
    assert out["Client"] == "10.0.0.5:51234"
    assert out["Uptime"] == "1m 05s"
    assert out["Total sent"].startswith("1.0 MiB")
    assert "KiB/s" in out["Rate"]
    assert out["Frames~"] == "180"
    assert out["PID"] == "99999"


def test_pc_summary_uses_dash_for_no_pid_and_no_client():
    out = pc_summary(StreamerStats(status=StreamStatus.IDLE))
    assert out["PID"] == "—"
    assert out["Client"] == "—"


# -- phone_summary --------------------------------------------------------


def test_phone_summary_no_snapshot_returns_unknown_card():
    out = phone_summary(None)
    assert out["YUV path"] == "—"
    assert out["Size"] == "—"
    assert out["ADB"].startswith("ไม่ทราบ")


def test_phone_summary_resolved_snapshot():
    snap = HealthSnapshot(
        phone_yuv_path="/data/data/com.npcreate.studio.receiver/files/vcam.yuv",
        phone_yuv_size=1024 * 50,
        phone_yuv_fresh_s=1.2,
    )
    out = phone_summary(snap)
    assert out["YUV path"].endswith("/vcam.yuv")
    assert out["Size"] == "50.0 KiB"
    assert out["Age"] == "1.2s"
    assert out["ADB"] == "OK"


def test_phone_summary_marks_adb_failure_when_size_missing():
    snap = HealthSnapshot(phone_yuv_path="/x", phone_yuv_size=None)
    out = phone_summary(snap)
    assert out["ADB"] == "ไม่พบไฟล์"


# -- health_warning -------------------------------------------------------


def test_health_warning_none_when_no_snapshot():
    assert health_warning(None) is None


def test_health_warning_returns_stalled_string_when_is_stalled():
    snap = HealthSnapshot(is_stalled=True, stalled_for_s=12.0)
    msg = health_warning(snap)
    assert msg is not None
    assert "Stalled" in msg
    assert "12" in msg


def test_health_warning_returns_idle_when_below_threshold_but_not_progressing():
    snap = HealthSnapshot(is_stalled=False, stalled_for_s=2.0, is_progressing=False)
    msg = health_warning(snap)
    assert msg is not None
    assert "Idle" in msg


def test_health_warning_none_when_progressing():
    snap = HealthSnapshot(is_stalled=False, stalled_for_s=0.0, is_progressing=True)
    assert health_warning(snap) is None
