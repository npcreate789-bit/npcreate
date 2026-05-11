"""Backup / Restore page — create or apply a customer-portable ZIP.

The work itself runs on a worker thread so the UI never blocks; results
come back via ``page.after(0, …)`` to keep all Tk widget writes on the
main thread. Restore previews the manifest first so the customer can
sanity-check before committing.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from tkinter import filedialog
from typing import Any

from .. import theme
from ..components import card, info_row, primary_button, section_title, subtle_button

log = logging.getLogger(__name__)


def build(ctk, parent, settings, services: dict[str, Any] | None = None):
    services = services or {}
    backup = services.get("backup_service")
    toast = services.get("toast")

    page = ctk.CTkScrollableFrame(parent, fg_color="transparent")
    section_title(
        ctk, page, "Backup / Restore",
        "บันทึก device_profiles + client_state ลง ZIP — กู้กลับบนเครื่องใหม่ได้",
    ).pack(fill="x", padx=8, pady=(6, 14))

    def _notify(msg: str, kind: str = "info") -> None:
        if toast is not None:
            toast.show(msg, kind=kind)
        else:
            log.info("backup toast: %s", msg)

    # ── create ────────────────────────────────────────────────────────
    create_card = card(ctk, page, "สร้าง Backup")
    create_card.pack(fill="x", padx=8, pady=(0, 14))
    info_row(ctk, create_card, "App data", str(settings.app_data_path)).pack(fill="x", padx=18, pady=(8, 0))
    create_status = ctk.CTkLabel(create_card, text="", text_color=theme.TEXT_MUTED, wraplength=900, justify="left")
    create_status.pack(anchor="w", padx=18, pady=(6, 6))

    def _on_create() -> None:
        if backup is None:
            _notify("BackupService ยังไม่ initialized", "error")
            return
        default_name = backup.suggest_filename()
        chosen = filedialog.asksaveasfilename(
            title="บันทึก Backup เป็น…",
            defaultextension=".zip",
            initialfile=default_name,
            filetypes=[("Backup ZIP", "*.zip"), ("All", "*.*")],
        )
        if not chosen:
            return
        create_btn.configure(state="disabled", text="กำลังสร้าง…")

        def _worker() -> None:
            try:
                result = backup.create_backup(Path(chosen))
            except Exception as exc:
                log.exception("create backup failed")
                err = str(exc)
                page.after(0, lambda e=err: _back_create(False, e, None))
                return
            page.after(0, lambda r=result: _back_create(True, None, r))

        def _back_create(ok: bool, err: str | None, result) -> None:
            create_btn.configure(state="normal", text="📦 บันทึก Backup เป็น ZIP")
            if not ok:
                create_status.configure(text=f"ล้มเหลว: {err}", text_color=theme.DANGER)
                _notify(f"สร้าง Backup ล้มเหลว: {err}", "error")
                return
            create_status.configure(
                text=f"สำเร็จ — {len(result.files)} ไฟล์ → {result.path}",
                text_color=theme.SUCCESS,
            )
            _notify(f"Backup สำเร็จ ({len(result.files)} ไฟล์)", "success")

        threading.Thread(target=_worker, daemon=True, name="np-backup-create").start()

    create_btn = primary_button(ctk, create_card, "📦 บันทึก Backup เป็น ZIP", command=_on_create)
    create_btn.pack(anchor="w", padx=18, pady=(0, 18))

    # ── restore ───────────────────────────────────────────────────────
    restore_card = card(ctk, page, "Restore จาก ZIP")
    restore_card.pack(fill="x", padx=8, pady=(0, 14))
    ctk.CTkLabel(
        restore_card,
        text="เลือกไฟล์ Backup → ดูรายการที่จะกู้คืน → กดยืนยัน",
        text_color=theme.TEXT_MUTED,
        wraplength=900,
        justify="left",
    ).pack(anchor="w", padx=18, pady=(8, 6))

    preview = ctk.CTkLabel(
        restore_card, text="ยังไม่ได้เลือกไฟล์", text_color=theme.TEXT_MUTED,
        wraplength=900, justify="left",
    )
    preview.pack(anchor="w", padx=18, pady=(0, 8))

    selected: dict[str, Path | None] = {"path": None}

    def _on_pick() -> None:
        if backup is None:
            _notify("BackupService ยังไม่ initialized", "error")
            return
        chosen = filedialog.askopenfilename(
            title="เลือก Backup ZIP",
            filetypes=[("Backup ZIP", "*.zip"), ("All", "*.*")],
        )
        if not chosen:
            return
        path = Path(chosen)
        manifest = backup.read_manifest(path)
        if manifest is None:
            preview.configure(text=f"ไฟล์ {path} ไม่ใช่ Backup ของ NP Create", text_color=theme.DANGER)
            restore_btn.configure(state="disabled")
            selected["path"] = None
            return
        selected["path"] = path
        lines = [
            f"📁 {path}",
            f"สร้างจาก {manifest.app_name} v{manifest.app_version} เมื่อ {manifest.created_at}",
            f"จะกู้คืน {len(manifest.files)} ไฟล์: {', '.join(manifest.files) or '—'}",
        ]
        preview.configure(text="\n".join(lines), text_color=theme.TEXT)
        restore_btn.configure(state="normal")

    def _on_restore() -> None:
        path = selected["path"]
        if path is None or backup is None:
            return
        restore_btn.configure(state="disabled", text="กำลังกู้คืน…")

        def _worker() -> None:
            try:
                restored = backup.restore_backup(path)
            except Exception as exc:
                log.exception("restore failed")
                err = str(exc)
                page.after(0, lambda e=err: _back_restore(False, e, []))
                return
            page.after(0, lambda r=restored: _back_restore(True, None, r))

        def _back_restore(ok: bool, err: str | None, restored: list[str]) -> None:
            restore_btn.configure(state="normal", text="✅ ยืนยัน Restore")
            if not ok:
                preview.configure(text=f"Restore ล้มเหลว: {err}", text_color=theme.DANGER)
                _notify(f"Restore ล้มเหลว: {err}", "error")
                return
            preview.configure(
                text=f"กู้คืนเรียบร้อย — {len(restored)} ไฟล์: {', '.join(restored)}",
                text_color=theme.SUCCESS,
            )
            _notify(
                "Restore สำเร็จ — เปิดโปรแกรมใหม่เพื่อให้ค่าโหลดครบ",
                "success",
            )

        threading.Thread(target=_worker, daemon=True, name="np-backup-restore").start()

    btn_row = ctk.CTkFrame(restore_card, fg_color="transparent")
    btn_row.pack(fill="x", padx=18, pady=(0, 18))
    subtle_button(ctk, btn_row, "📂 เลือกไฟล์ Backup", command=_on_pick).pack(side="left", padx=(0, 8))
    restore_btn = primary_button(ctk, btn_row, "✅ ยืนยัน Restore", command=_on_restore)
    restore_btn.configure(state="disabled")
    restore_btn.pack(side="left")

    return page
