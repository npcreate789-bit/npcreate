"""Update Center page — surface the orchestrator's check_now() to the user.

Renders current version, channel, and manifest URL; a "ตรวจอัปเดตล่าสุด"
button runs a synchronous check on a background thread and reports back
via toast + the in-page status pill. The background poller (started by
main_window) already shows a toast on its own when it sees a new version,
so this page is the manual "check right now" affordance.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

from .. import theme
from ..components import card, info_row, primary_button, section_title, status_pill

log = logging.getLogger(__name__)


def build(ctk, parent, settings, services: dict[str, Any] | None = None):
    services = services or {}
    update_orch = services.get("update_orchestrator")
    toast = services.get("toast")

    page = ctk.CTkFrame(parent, fg_color="transparent")
    section_title(
        ctk, page, "Update Center",
        "ตรวจแพทช์ใหม่แบบ Signed Manifest + SHA256 ก่อนติดตั้งทุกครั้ง",
    ).pack(fill="x", padx=8, pady=(6, 22))

    box = card(ctk, page, "สถานะอัปเดต")
    box.pack(fill="x", padx=8)
    pill = status_pill(ctk, box, "พร้อมตรวจ", theme.SUCCESS)
    pill.pack(anchor="w", padx=18, pady=(14, 8))
    info_row(ctk, box, "เวอร์ชันปัจจุบัน", settings.app_version).pack(fill="x", padx=18)
    info_row(ctk, box, "ช่องทางอัปเดต", settings.update_channel).pack(fill="x", padx=18)
    info_row(ctk, box, "Manifest", settings.update_manifest_url or "ใช้ Backend /updates/latest").pack(fill="x", padx=18)

    available = ctk.CTkLabel(box, text="", text_color=theme.TEXT_MUTED, wraplength=900, justify="left")
    available.pack(anchor="w", padx=18, pady=(6, 0))

    def _notify(msg: str, kind: str = "info") -> None:
        if toast is not None:
            toast.show(msg, kind=kind)
        else:
            log.info("update toast: %s", msg)

    def _on_check() -> None:
        if update_orch is None:
            _notify(
                "ยังไม่ได้ตั้งค่า license_server_url / vendor_public_key_hex — "
                "อัปเดตปิดอยู่",
                "warning",
            )
            return
        check_btn.configure(state="disabled", text="กำลังตรวจ…")

        def _worker() -> None:
            manifest = None
            err: str | None = None
            try:
                manifest = update_orch.check_now()
            except Exception as exc:
                log.exception("manual update check failed")
                err = str(exc)

            def _back_on_ui() -> None:
                check_btn.configure(state="normal", text="ตรวจอัปเดตล่าสุด")
                if err is not None:
                    _notify(f"ตรวจอัปเดตล้มเหลว: {err}", "error")
                    return
                if manifest is None:
                    available.configure(
                        text=f"เวอร์ชันล่าสุดคือ {settings.app_version} แล้ว",
                        text_color=theme.TEXT_MUTED,
                    )
                    _notify("ใช้เวอร์ชันล่าสุดอยู่แล้ว", "success")
                    return
                available.configure(
                    text=(
                        f"พบเวอร์ชันใหม่ v{manifest.version} "
                        f"({manifest.channel}) — รอติดตั้งบน Update Center"
                    ),
                    text_color=theme.PRIMARY,
                )
                _notify(f"พบเวอร์ชันใหม่ v{manifest.version}", "info")

            page.after(0, _back_on_ui)

        threading.Thread(target=_worker, daemon=True, name="np-update-check").start()

    check_btn = primary_button(ctk, box, "ตรวจอัปเดตล่าสุด", command=_on_check)
    check_btn.pack(anchor="w", padx=18, pady=(14, 18))
    return page
