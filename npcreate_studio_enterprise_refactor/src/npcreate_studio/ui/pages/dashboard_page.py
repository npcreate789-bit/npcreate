from __future__ import annotations

from .. import theme
from ..components import card, metric_card, section_title, status_pill


def build(ctk, parent, settings):
    page = ctk.CTkScrollableFrame(parent, fg_color="transparent")
    section_title(ctk, page, "ภาพรวมระบบ", "ตรวจสถานะ License, เครื่องที่ผูก, ข่าวสาร และอัปเดตล่าสุดในหน้าเดียว").pack(fill="x", padx=8, pady=(6, 22))

    grid = ctk.CTkFrame(page, fg_color="transparent")
    grid.pack(fill="x", padx=8)
    for i in range(4):
        grid.grid_columnconfigure(i, weight=1)

    metric_card(ctk, grid, "License", "รอตรวจสอบ", "กดหน้า License เพื่อ Activate", theme.WARNING).grid(row=0, column=0, sticky="nsew", padx=(0, 10))
    metric_card(ctk, grid, "อุปกรณ์", "0 เครื่อง", "ยังไม่ผูกเครื่องกับระบบ", theme.INFO).grid(row=0, column=1, sticky="nsew", padx=10)
    metric_card(ctk, grid, "อัปเดต", settings.app_version, "เวอร์ชันโปรแกรมปัจจุบัน", theme.SUCCESS).grid(row=0, column=2, sticky="nsew", padx=10)
    metric_card(ctk, grid, "ความปลอดภัย", "เปิดใช้งาน", "ตรวจ hash / token / update", theme.PRIMARY).grid(row=0, column=3, sticky="nsew", padx=(10, 0))

    lower = ctk.CTkFrame(page, fg_color="transparent")
    lower.pack(fill="both", expand=True, padx=8, pady=22)
    lower.grid_columnconfigure(0, weight=1)
    lower.grid_columnconfigure(1, weight=1)

    checklist = card(ctk, lower, "ขั้นตอนแนะนำก่อนใช้งาน")
    checklist.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
    steps = [
        "1. กรอก License Key และ Activate เครื่องนี้",
        "2. ต่อโทรศัพท์ Android แล้วตรวจสถานะอุปกรณ์",
        "3. ตรวจอัปเดตโปรแกรมก่อนเริ่มงาน",
        "4. อ่านประกาศจากทีม NP Create",
    ]
    for step in steps:
        ctk.CTkLabel(checklist, text=step, text_color=theme.TEXT, font=(theme.FONT_FAMILY, 14), anchor="w").pack(fill="x", padx=18, pady=6)

    health = card(ctk, lower, "Production Guard")
    health.grid(row=0, column=1, sticky="nsew", padx=(12, 0))
    for label, color in [("Local dashboard only", theme.SUCCESS), ("Signed update required", theme.SUCCESS), ("Device binding enabled", theme.SUCCESS), ("Admin release required", theme.SUCCESS)]:
        row = ctk.CTkFrame(health, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=7)
        status_pill(ctk, row, "ON", color).pack(side="left")
        ctk.CTkLabel(row, text=label, text_color=theme.TEXT, font=(theme.FONT_FAMILY, 14)).pack(side="left", padx=10)

    return page
