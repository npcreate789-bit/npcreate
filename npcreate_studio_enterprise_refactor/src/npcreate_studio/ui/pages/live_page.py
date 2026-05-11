"""Live page — start/stop the FFmpeg → TCP → phone pipeline.

Visual face of Phases A1–A3:

- ``StreamingOrchestrator`` runs the FFmpeg subprocess and serves bytes on
  the configured TCP port (default 8888).
- "Bridge to phone" calls ``AdbService.reverse(port)`` so the receiver app
  on the phone (legacy: vcam-app) can reach localhost:8888.
- ``HealthMonitor`` polls both sides every few seconds; the panel below
  reflects the latest snapshot.

Services consumed from the bundle assembled by ``MainWindow``:
``orchestrator``, ``health_monitor``, ``adb_service``, ``toast``, ``settings``.
"""
from __future__ import annotations

import logging
from pathlib import Path
from tkinter import StringVar, filedialog
from typing import Any

from ...domain.streams import StreamerStats, StreamProfile
from ...services.live_view import (
    health_warning,
    pc_summary,
    phone_summary,
    stream_status_pill,
)
from .. import theme
from ..components import card, info_row, primary_button, section_title, status_pill, subtle_button

log = logging.getLogger(__name__)

REFRESH_MS = 1000
COLOR_BY_ROLE = {
    "muted": theme.TEXT_MUTED,
    "info": theme.INFO,
    "success": theme.SUCCESS,
    "danger": theme.DANGER,
    "warning": theme.WARNING,
}


def build(ctk, parent, settings, services: dict[str, Any] | None = None):
    services = services or {}
    orchestrator = services.get("orchestrator")
    health = services.get("health_monitor")
    adb = services.get("adb_service")
    toast = services.get("toast")

    page = ctk.CTkScrollableFrame(parent, fg_color="transparent")
    page.grid_columnconfigure(0, weight=1)
    section_title(
        ctk, page, "Live Streaming",
        "เริ่มสตรีม FFmpeg → TCP → โทรศัพท์ พร้อมตรวจ Health เรียลไทม์",
    ).grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 18))

    # ── inputs ─────────────────────────────────────────────────────────
    inputs = card(ctk, page, "Source + Profile")
    inputs.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 14))

    playlist_var = StringVar()
    ctk.CTkLabel(inputs, text="Playlist / Video", text_color=theme.TEXT_MUTED).pack(anchor="w", padx=18, pady=(8, 4))
    pl_inner = ctk.CTkFrame(inputs, fg_color="transparent")
    pl_inner.pack(fill="x", padx=18)
    ctk.CTkEntry(pl_inner, textvariable=playlist_var, height=42, corner_radius=12, placeholder_text="/path/to/playlist.txt").pack(side="left", expand=True, fill="x", padx=(0, 8))

    def _on_browse() -> None:
        path = filedialog.askopenfilename(filetypes=[("Playlist or media", "*.txt *.mp4 *.mov *.mkv"), ("All", "*.*")])
        if path:
            playlist_var.set(path)

    subtle_button(ctk, pl_inner, "Browse…", command=_on_browse).pack(side="left")

    profile_var = StringVar(value="720x1280 30fps · 2 Mbps")
    ctk.CTkLabel(inputs, text="Profile", text_color=theme.TEXT_MUTED).pack(anchor="w", padx=18, pady=(8, 4))
    ctk.CTkOptionMenu(
        inputs,
        values=[
            "720x1280 30fps · 2 Mbps",
            "540x960 30fps · 1.5 Mbps",
            "1080x1920 30fps · 4 Mbps",
        ],
        variable=profile_var,
        corner_radius=10,
    ).pack(anchor="w", padx=18, pady=(0, 14))

    # ── action row ─────────────────────────────────────────────────────
    actions = ctk.CTkFrame(page, fg_color="transparent")
    actions.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 12))
    start_btn = primary_button(ctk, actions, "▶ Start streaming")
    start_btn.pack(side="left", padx=(0, 8))
    stop_btn = subtle_button(ctk, actions, "⏹ Stop")
    stop_btn.pack(side="left", padx=(0, 8))
    bridge_btn = subtle_button(ctk, actions, "📱 Bridge to phone (adb reverse)")
    bridge_btn.pack(side="left")

    # ── status pill + warning row ─────────────────────────────────────
    pill_row = ctk.CTkFrame(page, fg_color="transparent")
    pill_row.grid(row=3, column=0, sticky="ew", padx=8, pady=(0, 12))
    pill_container = ctk.CTkFrame(pill_row, fg_color="transparent")
    pill_container.pack(side="left")
    warning_label = ctk.CTkLabel(pill_row, text="", text_color=theme.WARNING, font=(theme.FONT_FAMILY, 13, "bold"))
    warning_label.pack(side="left", padx=18)

    # ── stat cards ─────────────────────────────────────────────────────
    cards_row = ctk.CTkFrame(page, fg_color="transparent")
    cards_row.grid(row=4, column=0, sticky="nsew", padx=8)
    cards_row.grid_columnconfigure(0, weight=1)
    cards_row.grid_columnconfigure(1, weight=1)

    pc_card = card(ctk, cards_row, "PC (FFmpeg + TCP server)")
    pc_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
    phone_card = card(ctk, cards_row, "Phone (receiver app)")
    phone_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

    # ── render helpers ────────────────────────────────────────────────
    def _clear_below_title(container) -> None:
        for child in list(container.winfo_children())[1:]:
            child.destroy()

    def _redraw_pill(stats: StreamerStats, snap) -> None:
        for w in pill_container.winfo_children():
            w.destroy()
        label, role = stream_status_pill(stats, snap)
        status_pill(ctk, pill_container, label, COLOR_BY_ROLE.get(role, theme.TEXT_MUTED)).pack()

    def _redraw_cards(stats: StreamerStats, snap) -> None:
        _clear_below_title(pc_card)
        rate = snap.pc_bytes_per_sec if snap is not None else 0.0
        for k, v in pc_summary(stats, bytes_per_sec=rate).items():
            info_row(ctk, pc_card, k, v).pack(fill="x", padx=18)
        ctk.CTkFrame(pc_card, height=8, fg_color="transparent").pack()

        _clear_below_title(phone_card)
        for k, v in phone_summary(snap).items():
            info_row(ctk, phone_card, k, v).pack(fill="x", padx=18)
        ctk.CTkFrame(phone_card, height=8, fg_color="transparent").pack()

    def _refresh() -> None:
        if not page.winfo_exists():
            return
        stats = orchestrator.stats if orchestrator is not None else StreamerStats()
        snap = health.snapshot if health is not None else None
        _redraw_pill(stats, snap)
        _redraw_cards(stats, snap)
        warning_label.configure(text=health_warning(snap) or "")
        try:
            page.after(REFRESH_MS, _refresh)
        except Exception:
            pass

    # ── action handlers ───────────────────────────────────────────────
    def _resolved_profile() -> StreamProfile:
        pick = profile_var.get()
        if "540x960" in pick:
            return StreamProfile(width=540, height=960, fps=30, video_bitrate="1500k", video_maxrate="1800k", video_bufsize="3000k")
        if "1080x1920" in pick:
            return StreamProfile(width=1080, height=1920, fps=30, video_bitrate="4000k", video_maxrate="5000k", video_bufsize="8000k")
        return StreamProfile()

    def _notify(msg: str, kind: str) -> None:
        if toast is not None:
            toast.show(msg, kind=kind)
        else:
            log.info("toast: %s", msg)

    def _on_start() -> None:
        if orchestrator is None:
            _notify("Streaming service ยังไม่ initialized", "error")
            return
        playlist_text = playlist_var.get().strip()
        if not playlist_text:
            _notify("เลือก playlist หรือ video file ก่อน", "warning")
            return
        playlist = Path(playlist_text).expanduser()
        if not playlist.exists():
            _notify(f"ไม่พบไฟล์: {playlist}", "error")
            return
        try:
            orchestrator.start(playlist, _resolved_profile())
        except Exception as exc:
            log.exception("orchestrator.start failed")
            _notify(f"Start ไม่สำเร็จ: {exc}", "error")
            return
        if health is not None and not health.is_running():
            health.start()
        _notify(
            f"Listening on {settings.stream_host}:{settings.stream_port} — กด Bridge แล้วเปิด receiver บนโทรศัพท์",
            "success",
        )

    def _on_stop() -> None:
        if orchestrator is not None:
            try:
                orchestrator.stop()
            except Exception as exc:
                log.exception("orchestrator.stop failed")
                _notify(f"Stop เจอ error: {exc}", "warning")
        if health is not None and health.is_running():
            health.stop()
        _notify("หยุดสตรีม", "info")

    def _on_bridge() -> None:
        if adb is None:
            _notify("AdbService ยังไม่ initialized", "error")
            return
        if not adb.is_available():
            _notify("ADB ไม่พร้อม — ตรวจ vendor/adb หรือ PATH", "error")
            return
        if adb.reverse(settings.stream_port):
            _notify(f"adb reverse tcp:{settings.stream_port} ✓ พร้อมรับการเชื่อมต่อจากโทรศัพท์", "success")
        else:
            _notify("adb reverse ล้มเหลว — เชื่อม USB + USB Debugging แล้วลองอีกครั้ง", "error")

    start_btn.configure(command=_on_start)
    stop_btn.configure(command=_on_stop)
    bridge_btn.configure(command=_on_bridge)

    _refresh()
    return page
