from __future__ import annotations

from pathlib import Path

from .. import theme
from ..components import card, primary_button, section_title, status_pill, subtle_button


def _read_tail(path: Path, max_lines: int = 120) -> str:
    try:
        if not path.exists():
            return "ยังไม่พบไฟล์ log"
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-max_lines:])
    except Exception as exc:
        return f"อ่าน log ไม่สำเร็จ: {exc}"


def build(ctk, parent, settings):
    page = ctk.CTkFrame(parent, fg_color="transparent")
    page.grid_columnconfigure(0, weight=1)
    page.grid_rowconfigure(2, weight=1)
    section_title(ctk, page, "Log Viewer / Error Report", "ตรวจ log ล่าสุดและส่งรายงานปัญหาให้ทีม Support ได้ง่ายขึ้น").grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 22))

    actions = card(ctk, page, "เครื่องมือ Support")
    actions.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 14))
    status_pill(ctk, actions, "LOCAL", theme.INFO).pack(anchor="w", padx=18, pady=(14, 8))
    row = ctk.CTkFrame(actions, fg_color="transparent")
    row.pack(fill="x", padx=18, pady=(4, 18))
    primary_button(ctk, row, "ส่ง Error Report").pack(side="left")
    subtle_button(ctk, row, "Refresh Log").pack(side="left", padx=10)

    box = card(ctk, page, "Application Log ล่าสุด")
    box.grid(row=2, column=0, sticky="nsew", padx=8)
    log_path = settings.app_data_path / "logs" / "npcreate-studio.log"
    text = ctk.CTkTextbox(box, height=420, fg_color=theme.SURFACE_SOFT, text_color=theme.TEXT, corner_radius=12)
    text.pack(fill="both", expand=True, padx=18, pady=(10, 18))
    text.insert("1.0", _read_tail(log_path))
    text.configure(state="disabled")
    return page
