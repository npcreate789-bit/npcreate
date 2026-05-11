"""Devices page — list / inspect / control connected Android devices via ADB.

Reads from ``services["adb_service"]`` to enumerate phones, show their state,
inspect ``getprop`` quick view, set up / tear down reverse tunnels, and
restart the local adb daemon when things look stuck.
"""
from __future__ import annotations

import logging
from typing import Any

from ...domain.devices import Device
from ...services.device_view import (
    adb_environment_summary,
    device_display_label,
    device_meta_line,
    device_state_pill,
    props_quick_view,
    reverse_tunnel_summary,
)
from .. import theme
from ..components import card, info_row, primary_button, section_title, status_pill, subtle_button

log = logging.getLogger(__name__)

COLOR_BY_ROLE = {
    "muted": theme.TEXT_MUTED,
    "info": theme.INFO,
    "success": theme.SUCCESS,
    "danger": theme.DANGER,
    "warning": theme.WARNING,
}


def build(ctk, parent, settings, services: dict[str, Any] | None = None):
    services = services or {}
    adb = services.get("adb_service")
    toast = services.get("toast")

    page = ctk.CTkScrollableFrame(parent, fg_color="transparent")
    section_title(
        ctk, page, "ผูกอุปกรณ์ (ADB)",
        "ตรวจ Android ที่เชื่อมต่อ พร้อมจัดการ reverse tunnel สำหรับ Live Streaming",
    ).pack(fill="x", padx=8, pady=(6, 18))

    # ── ADB environment summary ──────────────────────────────────────
    env_card = card(ctk, page, "สถานะ ADB")
    env_card.pack(fill="x", padx=8, pady=(0, 14))
    env_rows = ctk.CTkFrame(env_card, fg_color="transparent")
    env_rows.pack(fill="x", padx=18, pady=(4, 12))

    actions = ctk.CTkFrame(env_card, fg_color="transparent")
    actions.pack(fill="x", padx=18, pady=(0, 14))
    refresh_btn = primary_button(ctk, actions, "🔄 Refresh devices")
    refresh_btn.pack(side="left", padx=(0, 8))
    restart_btn = subtle_button(ctk, actions, "Restart adb-server")
    restart_btn.pack(side="left", padx=(0, 8))
    reverse_btn = subtle_button(ctk, actions, f"ผูก reverse tcp:{settings.stream_port}")
    reverse_btn.pack(side="left", padx=(0, 8))
    unreverse_btn = subtle_button(ctk, actions, "ยกเลิก reverse")
    unreverse_btn.pack(side="left")

    reverse_status = ctk.CTkLabel(env_card, text="", text_color=theme.TEXT_MUTED, anchor="w", justify="left")
    reverse_status.pack(anchor="w", padx=18, pady=(0, 14))

    # ── devices list ─────────────────────────────────────────────────
    devices_card = card(ctk, page, "อุปกรณ์ที่ตรวจพบ")
    devices_card.pack(fill="x", padx=8, pady=(0, 14))

    # ── selected device props ───────────────────────────────────────
    props_card = card(ctk, page, "Properties (เลือกเครื่องเพื่อดู)")
    props_card.pack(fill="x", padx=8)

    selected_serial: dict[str, str | None] = {"value": None}

    def _notify(msg: str, kind: str = "info") -> None:
        if toast is not None:
            toast.show(msg, kind=kind)
        else:
            log.info("toast: %s", msg)

    def _clear_below_title(container) -> None:
        for child in list(container.winfo_children())[1:]:
            child.destroy()

    def _render_env(devices: list[Device]) -> None:
        for child in list(env_rows.winfo_children()):
            child.destroy()
        is_avail = adb.is_available() if adb is not None else False
        for label, value in adb_environment_summary(is_available=is_avail, devices=devices).items():
            info_row(ctk, env_rows, label, value).pack(fill="x")

    def _render_devices(devices: list[Device]) -> None:
        _clear_below_title(devices_card)
        if not devices:
            ctk.CTkLabel(
                devices_card,
                text="ยังไม่มีอุปกรณ์ — เชื่อม USB, เปิด USB Debugging แล้วกด Refresh",
                text_color=theme.TEXT_MUTED,
                wraplength=900,
                justify="left",
            ).pack(anchor="w", padx=18, pady=(0, 18))
            return
        for device in devices:
            row = ctk.CTkFrame(devices_card, fg_color=theme.SURFACE_SOFT, corner_radius=14)
            row.pack(fill="x", padx=18, pady=6)
            label, role = device_state_pill(device)
            status_pill(ctk, row, label, COLOR_BY_ROLE.get(role, theme.TEXT_MUTED)).pack(side="left", padx=12, pady=12)
            text_wrap = ctk.CTkFrame(row, fg_color="transparent")
            text_wrap.pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(text_wrap, text=device_display_label(device), text_color=theme.TEXT, font=(theme.FONT_FAMILY, 14, "bold"), anchor="w").pack(anchor="w")
            ctk.CTkLabel(text_wrap, text=device_meta_line(device), text_color=theme.TEXT_MUTED, anchor="w", font=(theme.FONT_FAMILY, 12)).pack(anchor="w")

            inspect_btn = subtle_button(ctk, row, "ดู props")

            def _on_inspect(serial: str = device.serial) -> None:
                selected_serial["value"] = serial
                _render_props(serial)

            inspect_btn.configure(command=_on_inspect)
            inspect_btn.pack(side="right", padx=12, pady=12)

    def _render_props(serial: str | None) -> None:
        _clear_below_title(props_card)
        if not serial:
            ctk.CTkLabel(props_card, text="เลือกอุปกรณ์ด้านบนก่อน", text_color=theme.TEXT_MUTED).pack(anchor="w", padx=18, pady=(0, 18))
            return
        if adb is None:
            ctk.CTkLabel(props_card, text="AdbService ยังไม่ initialized", text_color=theme.DANGER).pack(anchor="w", padx=18, pady=(0, 18))
            return
        try:
            props = adb.get_props(serial=serial)
        except Exception as exc:
            log.exception("get_props failed")
            ctk.CTkLabel(props_card, text=f"ดู props ไม่สำเร็จ: {exc}", text_color=theme.DANGER, wraplength=900).pack(anchor="w", padx=18, pady=(0, 18))
            return
        rendered = props_quick_view(props)
        if not rendered:
            ctk.CTkLabel(props_card, text="ไม่ได้รับค่าจาก getprop (เครื่องอาจ unauthorized)", text_color=theme.WARNING).pack(anchor="w", padx=18, pady=(0, 18))
            return
        for k, v in rendered.items():
            info_row(ctk, props_card, k, v).pack(fill="x", padx=18)
        ctk.CTkFrame(props_card, height=8, fg_color="transparent").pack()

    def _render_reverse_status() -> None:
        if adb is None or not adb.is_available():
            reverse_status.configure(text=f"— ยังไม่มี reverse tunnel ที่ tcp:{settings.stream_port}; เชื่อม ADB ก่อน")
            return
        try:
            lines = adb.reverse_list()
        except Exception:
            log.exception("reverse_list failed")
            lines = []
        reverse_status.configure(text=reverse_tunnel_summary(lines, port=settings.stream_port))

    def _do_refresh() -> None:
        if adb is None:
            _notify("AdbService ยังไม่ initialized", "error")
            return
        try:
            devices = adb.list_devices()
        except Exception as exc:
            log.exception("list_devices failed")
            _notify(f"ตรวจอุปกรณ์ไม่สำเร็จ: {exc}", "error")
            devices = []
        _render_env(devices)
        _render_devices(devices)
        _render_reverse_status()
        if selected_serial["value"] and any(d.serial == selected_serial["value"] for d in devices):
            _render_props(selected_serial["value"])
        else:
            selected_serial["value"] = None
            _render_props(None)

    def _on_restart_server() -> None:
        if adb is None:
            _notify("AdbService ยังไม่ initialized", "error")
            return
        if adb.restart_server():
            _notify("Restart adb-server ✓", "success")
            _do_refresh()
        else:
            _notify("Restart adb-server ล้มเหลว", "error")

    def _on_reverse() -> None:
        if adb is None:
            _notify("AdbService ยังไม่ initialized", "error")
            return
        if adb.reverse(settings.stream_port, serial=selected_serial["value"]):
            _notify(f"ผูก reverse tcp:{settings.stream_port} ✓", "success")
        else:
            _notify("ผูก reverse ล้มเหลว — ตรวจ USB Debugging แล้วลองอีกครั้ง", "error")
        _render_reverse_status()

    def _on_unreverse() -> None:
        if adb is None:
            _notify("AdbService ยังไม่ initialized", "error")
            return
        try:
            adb.reverse_remove(settings.stream_port, serial=selected_serial["value"])
            _notify("ยกเลิก reverse แล้ว", "info")
        except Exception as exc:
            _notify(f"ยกเลิก reverse ไม่สำเร็จ: {exc}", "error")
        _render_reverse_status()

    refresh_btn.configure(command=_do_refresh)
    restart_btn.configure(command=_on_restart_server)
    reverse_btn.configure(command=_on_reverse)
    unreverse_btn.configure(command=_on_unreverse)

    _do_refresh()  # initial paint
    return page
