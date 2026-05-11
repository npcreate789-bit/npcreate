"""Phase A3 — HealthMonitor tests.

Uses fake stats provider + fake adb wrapper so we can drive ticks
deterministically with a controllable clock, without spinning up the
real background thread.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import pytest

from npcreate_studio.domain.streams import StreamerStats, StreamStatus
from npcreate_studio.services.health_monitor import (
    DEFAULT_PHONE_YUV_PATHS,
    HealthMonitor,
)


class _FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def __call__(self) -> float:
        return self.now


@dataclass
class _FakeAdb:
    """Stand-in for AdbService. Records shell calls and returns canned output."""

    available: bool = True
    shell_responses: dict[str, str] = field(default_factory=dict)
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def is_available(self) -> bool:
        return self.available

    def shell(self, command: str, *, serial: str | None = None, timeout: float = 10.0) -> str:
        self.calls.append((command, {"serial": serial, "timeout": timeout}))
        for key, value in self.shell_responses.items():
            if key in command:
                return value
        return ""


def _make_monitor(
    *,
    stats: StreamerStats | None = None,
    adb: _FakeAdb | None = None,
    clock: _FakeClock | None = None,
    interval_s: float = 5.0,
    stall_warn_after_s: float = 8.0,
    on_snapshot=None,
) -> tuple[HealthMonitor, _FakeAdb, _FakeClock, list[StreamerStats]]:
    """Returns (monitor, fake_adb, clock, stats_box). Mutating stats_box[-1]
    in place lets a test step the streamer counters between ticks."""
    stats_box: list[StreamerStats] = [stats or StreamerStats()]
    fake_adb = adb or _FakeAdb()
    fake_clock = clock or _FakeClock()
    monitor = HealthMonitor(
        stats_provider=lambda: stats_box[-1],
        adb=fake_adb,  # type: ignore[arg-type]
        interval_s=interval_s,
        stall_warn_after_s=stall_warn_after_s,
        clock=fake_clock,
        on_snapshot=on_snapshot,
    )
    return monitor, fake_adb, fake_clock, stats_box


# -- bytes/sec calculation -----------------------------------------------


def test_tick_computes_bytes_per_second_from_delta():
    monitor, _, _, stats = _make_monitor(interval_s=5.0)
    stats[-1] = StreamerStats(bytes_sent=0, uptime_s=0.0)
    monitor.tick()
    stats[-1] = StreamerStats(bytes_sent=50_000, uptime_s=5.0)
    snap = monitor.tick()
    # (50_000 - 0) / 5.0 = 10_000 B/s
    assert snap.pc_bytes_per_sec == pytest.approx(10_000.0)


def test_tick_copies_streamer_stats_into_snapshot():
    monitor, _, _, stats = _make_monitor()
    stats[-1] = StreamerStats(
        status=StreamStatus.STREAMING,
        bytes_sent=12345,
        frames_sent=42,
        uptime_s=7.5,
        client_addr="10.0.0.5:51234",
    )
    snap = monitor.tick()
    assert snap.pc_bytes_sent == 12345
    assert snap.pc_frames_sent == 42
    assert snap.pc_uptime_s == 7.5
    assert snap.pc_client_addr == "10.0.0.5:51234"


# -- stall detection -----------------------------------------------------


def test_tick_marks_stalled_when_no_progress_for_threshold():
    monitor, _, clock, stats = _make_monitor(interval_s=1.0, stall_warn_after_s=3.0)
    # client_addr must be set on every tick — Phase K treats no client as
    # "listening, not stalled" so a stall test without a client never fires.
    CLIENT = "127.0.0.1:12345"

    # First two ticks: progressing (bytes increasing fast).
    stats[-1] = StreamerStats(bytes_sent=0, client_addr=CLIENT)
    monitor.tick()
    clock.advance(1.0)
    stats[-1] = StreamerStats(bytes_sent=100_000, client_addr=CLIENT)
    snap = monitor.tick()
    assert snap.is_progressing is True
    assert snap.stalled_for_s == 0.0
    assert snap.is_stalled is False

    # Now freeze bytes (client still connected); stall counter must accumulate.
    stats[-1] = StreamerStats(bytes_sent=100_000, client_addr=CLIENT)
    for _ in range(4):
        clock.advance(1.0)
        snap = monitor.tick()
    assert snap.is_progressing is False
    assert snap.stalled_for_s >= 3.0
    assert snap.is_stalled is True


def test_pre_connection_idle_is_not_stalled():
    """Server listening with no client yet → not a fault, must not WARN-spam.

    Repro from the live debug session: HealthMonitor would tick once per 2s
    and emit WARNING `stall=NNNs` forever before the first phone connection,
    even though nothing was wrong. After Phase J the pre-connection state
    keeps the stall clock pinned at 0 and is_stalled stays False.
    """
    monitor, _, clock, stats = _make_monitor(interval_s=1.0, stall_warn_after_s=2.0)
    # Server is listening but no client yet: bytes_sent=0, client_addr="".
    stats[-1] = StreamerStats(bytes_sent=0, client_addr="")
    for _ in range(10):
        clock.advance(1.0)
        snap = monitor.tick()
    assert snap.stalled_for_s == 0.0
    assert snap.is_stalled is False


def test_stall_resumes_once_client_connects_then_freezes():
    """First a client connects + bytes flow; then bytes freeze → stall fires."""
    monitor, _, clock, stats = _make_monitor(interval_s=1.0, stall_warn_after_s=3.0)
    # Pre-connection: 5 idle ticks.
    stats[-1] = StreamerStats(bytes_sent=0, client_addr="")
    for _ in range(5):
        clock.advance(1.0)
        snap = monitor.tick()
    assert snap.is_stalled is False

    # Client connects, bytes flow.
    stats[-1] = StreamerStats(bytes_sent=100_000, client_addr="127.0.0.1:51234")
    clock.advance(1.0)
    snap = monitor.tick()
    assert snap.is_progressing is True

    # Now bytes freeze (client still connected) → real stall.
    stats[-1] = StreamerStats(bytes_sent=100_000, client_addr="127.0.0.1:51234")
    for _ in range(4):
        clock.advance(1.0)
        snap = monitor.tick()
    assert snap.is_stalled is True
    assert snap.stalled_for_s >= 3.0


def test_post_disconnect_is_listening_not_stalled():
    """Phase K: after client disconnects, server is just listening again.

    Repro: in the live debug session, the WARN spam continued for 100+
    seconds after the test phone disconnected. The cumulative bytes_sent
    stays positive but no current consumer exists — same UX state as
    pre-connection. is_stalled must be False.
    """
    monitor, _, clock, stats = _make_monitor(interval_s=1.0, stall_warn_after_s=2.0)
    # Active stream: bytes flowing.
    stats[-1] = StreamerStats(bytes_sent=100_000, client_addr="127.0.0.1:51234")
    monitor.tick()
    clock.advance(1.0)
    stats[-1] = StreamerStats(bytes_sent=200_000, client_addr="127.0.0.1:51234")
    monitor.tick()

    # Client disconnects: bytes_sent stays (cumulative), client_addr cleared.
    stats[-1] = StreamerStats(bytes_sent=200_000, client_addr="")
    for _ in range(10):
        clock.advance(1.0)
        snap = monitor.tick()
    assert snap.stalled_for_s == 0.0
    assert snap.is_stalled is False


def test_progressing_when_phone_yuv_mtime_advances_even_without_bytes():
    fake_adb = _FakeAdb(shell_responses={
        "stat -c": "12345 1700000100",
        "date +%s": "1700000101",
    })
    monitor, _, clock, stats = _make_monitor(adb=fake_adb, interval_s=1.0)
    stats[-1] = StreamerStats(bytes_sent=100)  # below threshold
    monitor.tick()

    # Second tick: same byte count but newer phone YUV mtime.
    fake_adb.shell_responses["stat -c"] = "12345 1700000105"
    fake_adb.shell_responses["date +%s"] = "1700000106"
    clock.advance(1.0)
    snap = monitor.tick()
    assert snap.is_progressing is True
    assert snap.stalled_for_s == 0.0


def test_stall_logs_warning_when_threshold_crossed(caplog):
    monitor, _, clock, stats = _make_monitor(interval_s=1.0, stall_warn_after_s=2.0)
    # Phase K: stall only fires while a client is connected. Set client_addr
    # so the post-connection stall path is actually exercised.
    stats[-1] = StreamerStats(bytes_sent=10, client_addr="127.0.0.1:51234")
    monitor.tick()
    clock.advance(5.0)
    with caplog.at_level(logging.WARNING, logger="npcreate_studio.services.health_monitor"):
        snap = monitor.tick()
    assert snap.is_stalled is True
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and "[stat]" in r.getMessage()]
    assert warnings, "expected a warning log line on stall"


# -- phone YUV probe -----------------------------------------------------


def test_resolves_first_existing_phone_yuv_path():
    fake_adb = _FakeAdb()
    # First candidate (app-private path) misses; second (/data/local/tmp) hits.
    private_path = DEFAULT_PHONE_YUV_PATHS[0]
    tmp_path = DEFAULT_PHONE_YUV_PATHS[1]

    def fake_shell(command: str, *, serial=None, timeout=10.0) -> str:
        fake_adb.calls.append((command, {"serial": serial, "timeout": timeout}))
        if "run-as" in command:
            return ""  # private path empty → resolver moves on
        if tmp_path in command:
            return "98765 1700000200"
        if "date +%s" in command:
            return "1700000201"
        return ""

    fake_adb.shell = fake_shell  # type: ignore[method-assign]
    monitor, _, _, stats = _make_monitor(adb=fake_adb)
    stats[-1] = StreamerStats(bytes_sent=100)
    snap = monitor.tick()
    assert snap.phone_yuv_size == 98765
    assert snap.phone_yuv_mtime == 1700000200
    assert snap.phone_yuv_path == tmp_path
    assert snap.phone_yuv_fresh_s == 1.0
    # And once resolved, subsequent ticks query the resolved path directly (no `run-as`).
    snap = monitor.tick()
    assert all("run-as" not in c[0] for c in fake_adb.calls[-2:])
    # We refer to private_path via constants so the linter doesn't think it's unused.
    assert private_path.startswith("/data/data/")


def test_skips_phone_probe_when_adb_unavailable():
    fake_adb = _FakeAdb(available=False, shell_responses={"stat -c": "1234 999"})
    monitor, _, _, stats = _make_monitor(adb=fake_adb)
    stats[-1] = StreamerStats(bytes_sent=10)
    snap = monitor.tick()
    assert snap.phone_yuv_size is None
    assert snap.phone_yuv_path is None
    # is_available was checked, but shell was never called
    assert fake_adb.calls == []


def test_gives_up_phone_probe_after_repeated_adb_failures():
    fake_adb = _FakeAdb(shell_responses={})  # shell returns "" → failure
    monitor, _, _, stats = _make_monitor(adb=fake_adb)
    stats[-1] = StreamerStats(bytes_sent=10)
    # Drive enough ticks to exceed the failure budget (>6).
    for _ in range(10):
        monitor.tick()
    early_call_count = len(fake_adb.calls)
    # Next tick should be a no-op for the phone side.
    monitor.tick()
    assert len(fake_adb.calls) == early_call_count


# -- snapshot callback + thread lifecycle --------------------------------


def test_on_snapshot_callback_receives_every_tick():
    received: list = []
    monitor, _, _, stats = _make_monitor(on_snapshot=received.append)
    stats[-1] = StreamerStats(bytes_sent=1)
    monitor.tick()
    monitor.tick()
    assert len(received) == 2
    assert received[0] is received[1] is monitor.snapshot  # same instance, mutated


def test_callback_exception_does_not_crash_tick(caplog):
    def boom(snap):
        raise RuntimeError("callback error")

    monitor, _, _, stats = _make_monitor(on_snapshot=boom)
    stats[-1] = StreamerStats(bytes_sent=1)
    with caplog.at_level(logging.ERROR, logger="npcreate_studio.services.health_monitor"):
        snap = monitor.tick()  # must not raise
    assert snap is monitor.snapshot
    assert any("callback failed" in r.getMessage() for r in caplog.records)


def test_start_and_stop_lifecycle(monkeypatch):
    # interval=0 → tick on every wait return (we'll cap manually)
    fake_adb = _FakeAdb()
    monitor, _, _, stats = _make_monitor(adb=fake_adb, interval_s=0.05)
    stats[-1] = StreamerStats(bytes_sent=100)
    monitor.start()
    assert monitor.is_running()
    import time as _t
    _t.sleep(0.15)
    monitor.stop()
    assert not monitor.is_running()


def test_snapshot_is_persistent_object():
    monitor, _, _, stats = _make_monitor()
    stats[-1] = StreamerStats(bytes_sent=10)
    s1 = monitor.tick()
    s2 = monitor.tick()
    # Snapshot is mutated in place (consistent with legacy semantics).
    assert s1 is s2 is monitor.snapshot
