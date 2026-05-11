from __future__ import annotations

from .. import theme
from ..components import card, info_row, primary_button, section_title, status_pill


def build(ctk, parent, settings):
    page = ctk.CTkFrame(parent, fg_color="transparent")
    section_title(ctk, page, "Update Center", "ตรวจแพทช์ใหม่แบบ Signed Manifest + SHA256 ก่อนติดตั้งทุกครั้ง").pack(fill="x", padx=8, pady=(6, 22))
    box = card(ctk, page, "สถานะอัปเดต")
    box.pack(fill="x", padx=8)
    status_pill(ctk, box, "ปลอดภัย", theme.SUCCESS).pack(anchor="w", padx=18, pady=(14, 8))
    info_row(ctk, box, "เวอร์ชันปัจจุบัน", settings.app_version).pack(fill="x", padx=18)
    info_row(ctk, box, "ช่องทางอัปเดต", settings.update_channel).pack(fill="x", padx=18)
    info_row(ctk, box, "Manifest", settings.update_manifest_url or "ใช้ Backend /updates/latest").pack(fill="x", padx=18)
    primary_button(ctk, box, "ตรวจอัปเดตล่าสุด").pack(anchor="w", padx=18, pady=(14, 18))
    return page
