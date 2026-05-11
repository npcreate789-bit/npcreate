from __future__ import annotations

from .. import theme
from ..components import card, section_title, status_pill


def build(ctk, parent, settings):
    page = ctk.CTkScrollableFrame(parent, fg_color="transparent")
    section_title(ctk, page, "ข่าวสารจากทีม NP Create", "ประกาศสำคัญ เทคนิคการใช้งาน และแจ้งเตือนระบบจะแสดงที่นี่").pack(fill="x", padx=8, pady=(6, 22))
    sample = card(ctk, page, "ตัวอย่างประกาศ")
    sample.pack(fill="x", padx=8)
    status_pill(ctk, sample, "INFO", theme.INFO).pack(anchor="w", padx=18, pady=(16, 8))
    ctk.CTkLabel(sample, text="เมื่อเชื่อม License Server แล้ว ข่าวสารจะถูกดึงจาก Backend เฉพาะ License ที่ยังใช้งานได้", text_color=theme.TEXT, wraplength=900, justify="left").pack(anchor="w", padx=18, pady=(0, 18))
    return page
