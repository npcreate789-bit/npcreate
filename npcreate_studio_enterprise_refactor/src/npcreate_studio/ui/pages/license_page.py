from __future__ import annotations

import logging
from tkinter import StringVar
from typing import Any

from .. import theme
from ..components import card, info_row, primary_button, section_title, status_pill, subtle_button

log = logging.getLogger(__name__)


def build(ctk, parent, settings, services: dict[str, Any] | None = None):
    services = services or {}
    lifecycle = services.get("lifecycle")
    toast = services.get("toast")

    page = ctk.CTkFrame(parent, fg_color="transparent")
    page.grid_columnconfigure(0, weight=1)
    section_title(ctk, page, "License & Activation", "ลงทะเบียนเครื่องนี้ด้วย License Key และตรวจวันหมดอายุ").grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 22))

    body = ctk.CTkFrame(page, fg_color="transparent")
    body.grid(row=1, column=0, sticky="nsew", padx=8)
    body.grid_columnconfigure(0, weight=2)
    body.grid_columnconfigure(1, weight=1)

    form = card(ctk, body, "ลงทะเบียน License")
    form.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
    key_var = StringVar()
    ctk.CTkLabel(form, text="License Key", text_color=theme.TEXT_MUTED).pack(anchor="w", padx=18, pady=(12, 4))
    ctk.CTkEntry(form, textvariable=key_var, placeholder_text="NP-XXXX-XXXX-XXXX-XXXX-XXXX", height=44, corner_radius=12).pack(fill="x", padx=18, pady=(0, 12))
    ctk.CTkLabel(form, text="หมายเหตุ: 1 License จะผูกตาม Policy ที่ Admin กำหนด เช่น 1 คอม + 1 โทรศัพท์", text_color=theme.TEXT_MUTED, wraplength=620, justify="left").pack(anchor="w", padx=18, pady=(0, 14))
    actions = ctk.CTkFrame(form, fg_color="transparent")
    actions.pack(fill="x", padx=18, pady=(0, 18))

    status = card(ctk, body, "สถานะปัจจุบัน")
    status.grid(row=0, column=1, sticky="nsew", padx=(12, 0))

    def _render_status() -> None:
        # Re-render after activate/clear: destroy everything below the title.
        for child in list(status.winfo_children())[1:]:
            child.destroy()
        current = lifecycle.current_state() if lifecycle else None
        if current:
            status_pill(ctk, status, "Activated", theme.SUCCESS).pack(anchor="w", padx=18, pady=(14, 10))
            info_row(ctk, status, "License ID", current.license_id[:24] + "…").pack(fill="x", padx=18)
            info_row(ctk, status, "Device ID", current.device_id[:24] + "…").pack(fill="x", padx=18)
            info_row(ctk, status, "หมดอายุ", current.expires_at.strftime("%Y-%m-%d %H:%M UTC")).pack(fill="x", padx=18)
        else:
            status_pill(ctk, status, "ยังไม่ Activate", theme.WARNING).pack(anchor="w", padx=18, pady=(14, 10))
            info_row(ctk, status, "เวอร์ชัน", settings.app_version).pack(fill="x", padx=18)
            info_row(ctk, status, "Server", settings.license_server_url or "ยังไม่ได้ตั้งค่า").pack(fill="x", padx=18)
            info_row(ctk, status, "Channel", settings.update_channel).pack(fill="x", padx=18, pady=(0, 16))

    def _on_activate() -> None:
        key = key_var.get().strip()
        if not key:
            if toast:
                toast.show("กรอก License Key ก่อน", kind="warning")
            return
        if not lifecycle:
            if toast:
                toast.show("ยังไม่ได้ตั้งค่า license_server_url", kind="error")
            return
        try:
            result = lifecycle.activate(key)
        except Exception as exc:
            log.exception("activation failed")
            if toast:
                toast.show(f"Activate ไม่สำเร็จ: {exc}", kind="error")
            return
        if toast:
            toast.show(f"Activate สำเร็จ — license {result.license_id[:12]}…", kind="success")
        _render_status()

    primary_button(ctk, actions, "Activate เครื่องนี้", command=_on_activate).pack(side="left")
    subtle_button(ctk, actions, "ขอปลดเครื่องเดิม").pack(side="left", padx=10)

    _render_status()
    return page
