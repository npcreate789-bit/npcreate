"""Stream page — push the playlist directly to an external RTMP ingest URL.

Counterpart to Live Streaming (which serves bytes to a phone). This page is
for users who want to push to TikTok/Facebook/Twitch/NGINX-RTMP servers
directly from PC.
"""
from __future__ import annotations

import logging
from pathlib import Path
from tkinter import StringVar, filedialog
from typing import Any

from ...domain.streams import StreamProfile
from ...services.rtmp_view import rtmp_status_pill, stream_summary
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
    rtmp = services.get("rtmp_service")
    toast = services.get("toast")

    page = ctk.CTkScrollableFrame(parent, fg_color="transparent")
    page.grid_columnconfigure(0, weight=1)
    section_title(
        ctk, page, "Stream (RTMP push)",
        "Push playlist ตรงไปยัง RTMP ingest URL (TikTok / Facebook / Twitch / NGINX-RTMP / ฯลฯ)",
    ).grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 18))

    # ── inputs ───────────────────────────────────────────────────────
    inputs = card(ctk, page, "Source + Profile + RTMP")
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
    ctk.CTkLabel(inputs, text="Encode preset", text_color=theme.TEXT_MUTED).pack(anchor="w", padx=18, pady=(8, 4))
    ctk.CTkOptionMenu(
        inputs,
        values=[
            "720x1280 30fps · 2 Mbps",
            "540x960 30fps · 1.5 Mbps",
            "1080x1920 30fps · 4 Mbps",
        ],
        variable=profile_var,
        corner_radius=10,
    ).pack(anchor="w", padx=18, pady=(0, 8))

    rtmp_url_var = StringVar()
    ctk.CTkLabel(inputs, text="RTMP URL (incl. stream key)", text_color=theme.TEXT_MUTED).pack(anchor="w", padx=18, pady=(4, 4))
    ctk.CTkEntry(
        inputs,
        textvariable=rtmp_url_var,
        height=42,
        corner_radius=12,
        placeholder_text="rtmp://live.example.com/app/STREAM_KEY",
    ).pack(fill="x", padx=18, pady=(0, 14))

    # ── action row ────────────────────────────────────────────────────
    actions = ctk.CTkFrame(page, fg_color="transparent")
    actions.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 12))
    start_btn = primary_button(ctk, actions, "📡 Start pushing")
    start_btn.pack(side="left", padx=(0, 8))
    stop_btn = subtle_button(ctk, actions, "⏹ Stop")
    stop_btn.pack(side="left")

    # ── status pill ───────────────────────────────────────────────────
    pill_row = ctk.CTkFrame(page, fg_color="transparent")
    pill_row.grid(row=3, column=0, sticky="ew", padx=8, pady=(0, 12))
    pill_container = ctk.CTkFrame(pill_row, fg_color="transparent")
    pill_container.pack(side="left")

    # ── stat + log ────────────────────────────────────────────────────
    stat_row = ctk.CTkFrame(page, fg_color="transparent")
    stat_row.grid(row=4, column=0, sticky="nsew", padx=8)
    stat_row.grid_columnconfigure(0, weight=1)
    stat_row.grid_columnconfigure(1, weight=2)

    stat_card = card(ctk, stat_row, "FFmpeg status")
    stat_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
    log_card = card(ctk, stat_row, "FFmpeg stderr (ล่าสุด)")
    log_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
    log_text = ctk.CTkTextbox(log_card, height=200, corner_radius=10, font=("Menlo", 11))
    log_text.pack(fill="both", expand=True, padx=14, pady=(0, 12))
    log_text.configure(state="disabled")

    def _clear_below_title(container) -> None:
        for child in list(container.winfo_children())[1:]:
            child.destroy()

    def _redraw_pill() -> None:
        for w in pill_container.winfo_children():
            w.destroy()
        if rtmp is None:
            status_pill(ctk, pill_container, "RTMP service ยังไม่ initialized", theme.DANGER).pack()
            return
        label, role = rtmp_status_pill(rtmp.stats)
        status_pill(ctk, pill_container, label, COLOR_BY_ROLE.get(role, theme.TEXT_MUTED)).pack()

    def _redraw_stats() -> None:
        if rtmp is None:
            return
        _clear_below_title(stat_card)
        for k, v in stream_summary(rtmp.stats).items():
            info_row(ctk, stat_card, k, v).pack(fill="x", padx=18)
        ctk.CTkFrame(stat_card, height=8, fg_color="transparent").pack()

    def _redraw_log() -> None:
        if rtmp is None:
            return
        lines = rtmp.recent_stderr()
        try:
            log_text.configure(state="normal")
            log_text.delete("0.0", "end")
            log_text.insert("0.0", "\n".join(lines[-30:]) or "(ยังไม่มี stderr — เริ่ม push เพื่อเห็น)")
            log_text.configure(state="disabled")
        except Exception:
            pass

    def _refresh() -> None:
        if not page.winfo_exists():
            return
        _redraw_pill()
        _redraw_stats()
        _redraw_log()
        try:
            page.after(REFRESH_MS, _refresh)
        except Exception:
            pass

    def _notify(msg: str, kind: str) -> None:
        if toast is not None:
            toast.show(msg, kind=kind)
        else:
            log.info("toast: %s", msg)

    def _resolved_profile() -> StreamProfile:
        pick = profile_var.get()
        if "540x960" in pick:
            return StreamProfile(width=540, height=960, fps=30, video_bitrate="1500k", video_maxrate="1800k", video_bufsize="3000k")
        if "1080x1920" in pick:
            return StreamProfile(width=1080, height=1920, fps=30, video_bitrate="4000k", video_maxrate="5000k", video_bufsize="8000k")
        return StreamProfile()

    def _on_start() -> None:
        if rtmp is None:
            _notify("RTMP service ยังไม่ initialized", "error")
            return
        playlist_text = playlist_var.get().strip()
        rtmp_url = rtmp_url_var.get().strip()
        if not playlist_text:
            _notify("เลือก playlist หรือ video file ก่อน", "warning")
            return
        if not rtmp_url:
            _notify("ใส่ RTMP URL ก่อน", "warning")
            return
        playlist = Path(playlist_text).expanduser()
        if not playlist.exists():
            _notify(f"ไม่พบไฟล์: {playlist}", "error")
            return
        try:
            rtmp.start(playlist, _resolved_profile(), rtmp_url)
        except Exception as exc:
            log.exception("rtmp start failed")
            _notify(f"Start ไม่สำเร็จ: {exc}", "error")
            return
        _notify("Pushing → RTMP target", "success")

    def _on_stop() -> None:
        if rtmp is None:
            return
        try:
            rtmp.stop()
        except Exception as exc:
            log.exception("rtmp stop failed")
            _notify(f"Stop เจอ error: {exc}", "warning")
            return
        _notify("หยุด RTMP push", "info")

    start_btn.configure(command=_on_start)
    stop_btn.configure(command=_on_stop)
    _refresh()
    return page
