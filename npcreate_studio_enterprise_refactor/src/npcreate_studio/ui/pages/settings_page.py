from __future__ import annotations

from .. import theme
from ..components import card, info_row, section_title


def build(ctk, parent, settings):
    page = ctk.CTkScrollableFrame(parent, fg_color="transparent")
    section_title(ctk, page, "ตั้งค่าระบบ", "ตรวจ path, backend URL และค่าความปลอดภัยที่สำคัญ").pack(fill="x", padx=8, pady=(6, 22))
    cfg = card(ctk, page, "Application Settings")
    cfg.pack(fill="x", padx=8)
    rows = [
        ("App data", str(settings.app_data_path)),
        ("Tool root", str(settings.tool_root_path)),
        ("Tools manifest", str(settings.tools_manifest_path)),
        ("Dashboard", f"{settings.dashboard_host}:{settings.dashboard_port}"),
        ("License server", settings.license_server_url or "ยังไม่ได้ตั้งค่า"),
    ]
    for label, value in rows:
        info_row(ctk, cfg, label, value).pack(fill="x", padx=18)
    ctk.CTkLabel(cfg, text="Production note: Dashboard ต้องเปิดเฉพาะ localhost และทุก tool ต้องผ่าน SHA256 manifest ก่อนเรียกใช้งาน", text_color=theme.TEXT_MUTED, wraplength=900, justify="left").pack(anchor="w", padx=18, pady=(12, 18))
    return page
