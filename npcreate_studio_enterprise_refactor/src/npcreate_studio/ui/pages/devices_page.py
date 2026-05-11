from __future__ import annotations

from .. import theme
from ..components import card, primary_button, section_title, status_pill, subtle_button


def build(ctk, parent, settings):
    page = ctk.CTkScrollableFrame(parent, fg_color="transparent")
    section_title(ctk, page, "อุปกรณ์ที่ผูกกับ License", "ระบบรองรับ Device Policy ที่ Admin กำหนดได้อิสระ เช่น PC, Phone, Tablet").pack(fill="x", padx=8, pady=(6, 22))

    tools = card(ctk, page, "ตรวจอุปกรณ์")
    tools.pack(fill="x", padx=8, pady=(0, 18))
    ctk.CTkLabel(tools, text="หลัง Activate แล้ว โปรแกรมจะแสดงรายการเครื่องที่ผูก และปุ่มขอปลดเครื่องถ้าต้องย้ายอุปกรณ์", text_color=theme.TEXT_MUTED, wraplength=900, justify="left").pack(anchor="w", padx=18, pady=(12, 14))
    row = ctk.CTkFrame(tools, fg_color="transparent")
    row.pack(fill="x", padx=18, pady=(0, 18))
    primary_button(ctk, row, "ตรวจโทรศัพท์ Android").pack(side="left")
    subtle_button(ctk, row, "Refresh สถานะ").pack(side="left", padx=10)

    policy = card(ctk, page, "ตัวอย่าง Policy ที่ Backend รองรับ")
    policy.pack(fill="x", padx=8)
    for dtype, maxd, desc in [("pc", "1", "เครื่องคอมพิวเตอร์หลัก"), ("phone", "1", "โทรศัพท์ Android สำหรับใช้งาน"), ("tablet", "0-200", "เพิ่มได้ในอนาคตโดย Admin")]:
        item = ctk.CTkFrame(policy, fg_color=theme.SURFACE_SOFT, corner_radius=14)
        item.pack(fill="x", padx=18, pady=7)
        status_pill(ctk, item, dtype.upper(), theme.INFO).pack(side="left", padx=12, pady=12)
        ctk.CTkLabel(item, text=f"สูงสุด {maxd} เครื่อง — {desc}", text_color=theme.TEXT).pack(side="left")
    return page
