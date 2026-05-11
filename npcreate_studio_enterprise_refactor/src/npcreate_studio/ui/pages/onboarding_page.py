"""Onboarding wizard — first-run setup walk-through.

5 steps: License → Activate → Pick device → Bridge → Ready. Each step
shows its own content frame. The state machine in
``services/onboarding.py`` decides which step is "current"; this page
just renders + wires actions.
"""
from __future__ import annotations

import logging
import threading
from tkinter import StringVar
from typing import Any

from ...services.device_view import device_display_label
from ...services.onboarding import (
    TOTAL_STEPS,
    OnboardingState,
    authorized_devices,
    best_device_to_recommend,
    current_step,
    step_label,
    step_status,
)
from .. import theme
from ..components import card, info_row, primary_button, section_title, status_pill, subtle_button

log = logging.getLogger(__name__)

CHIP_COLORS = {
    "done": theme.SUCCESS,
    "current": theme.PRIMARY,
    "upcoming": theme.SURFACE_SOFT,
}


def build(ctk, parent, settings, services: dict[str, Any] | None = None):
    services = services or {}
    lifecycle = services.get("lifecycle")
    adb = services.get("adb_service")
    toast = services.get("toast")

    state = OnboardingState()

    # Pre-fill from current services — if user has already activated, skip ahead.
    if lifecycle is not None:
        current = lifecycle.current_state()
        if current is not None:
            state.has_activation = True
            state.selected_serial = current.device_id  # placeholder; real adb serial set on step 3
    if adb is not None and state.has_activation:
        try:
            lines = adb.reverse_list()
        except Exception:
            lines = []
        if any(f"tcp:{settings.stream_port}" in line for line in lines):
            state.reverse_active = True

    page = ctk.CTkScrollableFrame(parent, fg_color="transparent")
    page.grid_columnconfigure(0, weight=1)
    section_title(
        ctk, page, "เริ่มต้นใช้งาน",
        "ขั้นตอนแนะนำ 5 ขั้น — License → Activate → เลือกอุปกรณ์ → Bridge → ไลฟ์",
    ).grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 14))

    # ── chip row (1 → 2 → 3 → 4 → 5) ──────────────────────────────────
    chip_row = ctk.CTkFrame(page, fg_color="transparent")
    chip_row.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 14))

    # ── step content holder ───────────────────────────────────────────
    content_holder = ctk.CTkFrame(page, fg_color="transparent")
    content_holder.grid(row=2, column=0, sticky="nsew", padx=8)

    def _notify(msg: str, kind: str = "info") -> None:
        if toast is not None:
            toast.show(msg, kind=kind)
        else:
            log.info("toast: %s", msg)

    def _render_chips() -> None:
        for child in list(chip_row.winfo_children()):
            child.destroy()
        statuses = step_status(state)
        for step in range(1, TOTAL_STEPS + 1):
            color = CHIP_COLORS.get(statuses[step], theme.TEXT_MUTED)
            chip = ctk.CTkLabel(
                chip_row,
                text=f"  {step}. {step_label(step)}  ",
                fg_color=color,
                text_color="#FFFFFF",
                corner_radius=999,
                font=(theme.FONT_FAMILY, 12, "bold"),
            )
            chip.pack(side="left", padx=4)

    def _clear_content() -> None:
        for child in list(content_holder.winfo_children()):
            child.destroy()

    # ── step 1: license key ───────────────────────────────────────────
    def _render_step_1() -> None:
        _clear_content()
        c = card(ctk, content_holder, f"ขั้นที่ 1 — {step_label(1)}")
        c.pack(fill="x", padx=0, pady=(0, 14))
        key_var = StringVar(value=state.license_key_input)
        ctk.CTkLabel(c, text="License Key", text_color=theme.TEXT_MUTED).pack(anchor="w", padx=18, pady=(8, 4))
        ctk.CTkEntry(c, textvariable=key_var, height=44, corner_radius=12, placeholder_text="NP-XXXX-XXXX-XXXX-XXXX-XXXX").pack(fill="x", padx=18, pady=(0, 14))

        def _on_next() -> None:
            key = key_var.get().strip()
            if not key:
                _notify("กรอก License Key ก่อน", "warning")
                return
            state.license_key_input = key
            _render_step_2(activate=True)

        primary_button(ctk, c, "Continue → Activate", command=_on_next).pack(anchor="w", padx=18, pady=(0, 18))

    # ── step 2: activating ────────────────────────────────────────────
    def _render_step_2(*, activate: bool = False) -> None:
        _clear_content()
        c = card(ctk, content_holder, f"ขั้นที่ 2 — {step_label(2)}")
        c.pack(fill="x", padx=0, pady=(0, 14))
        msg = ctk.CTkLabel(c, text="กำลัง activate กับ license server…", text_color=theme.TEXT_MUTED, wraplength=900, justify="left")
        msg.pack(anchor="w", padx=18, pady=(12, 14))

        def _on_back() -> None:
            _render_step_1()

        back = subtle_button(ctk, c, "← Back", command=_on_back)
        back.pack(anchor="w", padx=18, pady=(0, 18))

        if not activate:
            return
        if lifecycle is None:
            msg.configure(text="LicenseLifecycleService ยังไม่ initialized", text_color=theme.DANGER)
            return

        def _worker() -> None:
            try:
                lifecycle.activate(state.license_key_input)
            except Exception as exc:
                log.exception("activate failed")
                err_text = f"Activate ไม่สำเร็จ: {exc}"
                page.after(0, lambda err=err_text: msg.configure(text=err, text_color=theme.DANGER))
                page.after(0, lambda err=err_text: _notify(err, "error"))
                return
            state.has_activation = True
            page.after(0, lambda: _notify("Activate สำเร็จ", "success"))
            page.after(0, _refresh)

        threading.Thread(target=_worker, daemon=True, name="np-onboarding-activate").start()

    # ── step 3: pick device ───────────────────────────────────────────
    def _render_step_3() -> None:
        _clear_content()
        c = card(ctk, content_holder, f"ขั้นที่ 3 — {step_label(3)}")
        c.pack(fill="x", padx=0, pady=(0, 14))
        ctk.CTkLabel(c, text="เชื่อม Android ผ่าน USB + เปิด USB Debugging", text_color=theme.TEXT_MUTED, wraplength=900, justify="left").pack(anchor="w", padx=18, pady=(8, 6))
        list_box = ctk.CTkFrame(c, fg_color="transparent")
        list_box.pack(fill="x", padx=18, pady=(0, 8))

        def _refresh_list() -> None:
            for child in list(list_box.winfo_children()):
                child.destroy()
            if adb is None or not adb.is_available():
                ctk.CTkLabel(list_box, text="ADB ไม่พร้อม — ตรวจ vendor/adb หรือ PATH", text_color=theme.DANGER).pack(anchor="w")
                return
            try:
                devices = adb.list_devices()
            except Exception as exc:
                ctk.CTkLabel(list_box, text=f"ตรวจอุปกรณ์ไม่สำเร็จ: {exc}", text_color=theme.DANGER, wraplength=900).pack(anchor="w")
                return
            auth = authorized_devices(devices)
            if not auth:
                ctk.CTkLabel(
                    list_box,
                    text="ยังไม่มีอุปกรณ์ที่ผ่าน — เชื่อม USB แล้วกด Allow บนเครื่อง แล้วกด Refresh",
                    text_color=theme.WARNING,
                    wraplength=900,
                    justify="left",
                ).pack(anchor="w", pady=4)
                return
            # Recommend the first authorized device.
            best = best_device_to_recommend(devices)
            for d in auth:
                row = ctk.CTkFrame(list_box, fg_color=theme.SURFACE_SOFT, corner_radius=14)
                row.pack(fill="x", pady=4)
                status_pill(ctk, row, "Authorized", theme.SUCCESS).pack(side="left", padx=12, pady=10)
                ctk.CTkLabel(row, text=device_display_label(d), text_color=theme.TEXT, font=(theme.FONT_FAMILY, 13, "bold")).pack(side="left")
                pick_btn = primary_button(ctk, row, "เลือก" if d != best else "เลือก ★")

                def _on_pick(serial: str = d.serial) -> None:
                    state.selected_serial = serial
                    _notify(f"เลือกอุปกรณ์ {serial}", "success")
                    _refresh()

                pick_btn.configure(command=_on_pick)
                pick_btn.pack(side="right", padx=12, pady=10)

        actions = ctk.CTkFrame(c, fg_color="transparent")
        actions.pack(fill="x", padx=18, pady=(8, 18))
        subtle_button(ctk, actions, "🔄 Refresh devices", command=_refresh_list).pack(side="left", padx=(0, 8))
        subtle_button(ctk, actions, "← Back", command=lambda: _render_step_2()).pack(side="left")
        _refresh_list()

    # ── step 4: adb reverse ───────────────────────────────────────────
    def _render_step_4() -> None:
        _clear_content()
        c = card(ctk, content_holder, f"ขั้นที่ 4 — {step_label(4)}")
        c.pack(fill="x", padx=0, pady=(0, 14))
        info_row(ctk, c, "Selected", state.selected_serial or "—").pack(fill="x", padx=18, pady=(8, 0))
        info_row(ctk, c, "Reverse port", f"tcp:{settings.stream_port}").pack(fill="x", padx=18, pady=(0, 14))

        msg = ctk.CTkLabel(c, text="กด Bridge เพื่อสร้าง adb reverse — เปิดเส้นทาง PC → โทรศัพท์", text_color=theme.TEXT_MUTED, wraplength=900, justify="left")
        msg.pack(anchor="w", padx=18, pady=(0, 12))

        def _on_bridge() -> None:
            if adb is None:
                _notify("AdbService ยังไม่ initialized", "error")
                return
            if adb.reverse(settings.stream_port, serial=state.selected_serial):
                state.reverse_active = True
                _notify(f"adb reverse tcp:{settings.stream_port} ✓", "success")
                _refresh()
            else:
                _notify("Bridge ล้มเหลว — ตรวจสถานะ USB อีกครั้ง", "error")

        actions = ctk.CTkFrame(c, fg_color="transparent")
        actions.pack(fill="x", padx=18, pady=(0, 18))
        primary_button(ctk, actions, "📱 Bridge now", command=_on_bridge).pack(side="left", padx=(0, 8))
        subtle_button(ctk, actions, "← Back", command=_render_step_3).pack(side="left")

    # ── step 5: ready ─────────────────────────────────────────────────
    def _render_step_5(*, page_switcher) -> None:
        _clear_content()
        c = card(ctk, content_holder, f"ขั้นที่ 5 — {step_label(5)}")
        c.pack(fill="x", padx=0, pady=(0, 14))
        ctk.CTkLabel(
            c,
            text="ตั้งค่าครบแล้ว ✓\nไปที่หน้า Live Streaming เพื่อเลือก video และกด Start — แล้วเปิด receiver บนโทรศัพท์",
            text_color=theme.TEXT,
            wraplength=900,
            justify="left",
            font=(theme.FONT_FAMILY, 14),
        ).pack(anchor="w", padx=18, pady=(12, 12))

        def _go_live() -> None:
            if page_switcher is not None:
                page_switcher("live")

        primary_button(ctk, c, "→ Open Live Streaming", command=_go_live).pack(anchor="w", padx=18, pady=(0, 18))

    # ── orchestration ─────────────────────────────────────────────────
    page_switcher = services.get("_page_switcher")  # injected by main_window (optional)

    def _refresh() -> None:
        _render_chips()
        step = current_step(state)
        if step == 1:
            _render_step_1()
        elif step == 2:
            _render_step_2()
        elif step == 3:
            _render_step_3()
        elif step == 4:
            _render_step_4()
        else:
            _render_step_5(page_switcher=page_switcher)

    _refresh()
    return page
