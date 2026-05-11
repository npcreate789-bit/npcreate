"""Device Profile CRUD — list / add / edit / remove the rotation filter
profiles that the Live page uses.

Builtin profiles ship inside the package (read-only). User-source profiles
persist to ``<app_data>/device_profiles.json`` via
``device_profile_repository.save_user``.
"""
from __future__ import annotations

import logging
from tkinter import StringVar
from typing import Any

from ...domain.device_profiles import DeviceProfile, ProfileSource
from ...services.device_profile_repository import save_user
from ...services.profile_view import (
    is_editable,
    library_counts,
    make_profile_from_form,
    profile_row_summary,
    validate_profile_form,
)
from .. import theme
from ..components import card, info_row, primary_button, section_title, status_pill, subtle_button

log = logging.getLogger(__name__)


def build(ctk, parent, settings, services: dict[str, Any] | None = None):
    services = services or {}
    library = services.get("device_profile_lib")
    toast = services.get("toast")
    user_path = settings.app_data_path / "device_profiles.json"

    page = ctk.CTkScrollableFrame(parent, fg_color="transparent")
    page.grid_columnconfigure(0, weight=1)
    section_title(
        ctk, page, "Device Profiles",
        "จัดการ rotation filter ต่อรุ่นโทรศัพท์ — builtin (ship กับโปรแกรม) แก้ไม่ได้, user เพิ่ม/ลบเองได้",
    ).grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 14))

    summary_card = card(ctk, page, "สรุป Library")
    summary_card.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 14))

    form_card = card(ctk, page, "เพิ่ม Profile ใหม่")
    form_card.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 14))

    list_card = card(ctk, page, "Profiles ทั้งหมด")
    list_card.grid(row=3, column=0, sticky="ew", padx=8)

    # editing-state holder. None = create-new form; otherwise = editing existing profile name.
    editing_target: dict[str, str | None] = {"name": None}

    def _notify(msg: str, kind: str = "info") -> None:
        if toast is not None:
            toast.show(msg, kind=kind)
        else:
            log.info("toast: %s", msg)

    def _persist() -> None:
        """Write current library state to user_path. Best-effort — toast on error."""
        if library is None:
            return
        try:
            save_user(library, user_path)
        except Exception as exc:
            log.exception("device profile save_user failed")
            _notify(f"บันทึกไฟล์ profile ไม่สำเร็จ: {exc}", "error")

    # ── render helpers ─────────────────────────────────────────────────
    def _clear_below_title(container) -> None:
        for child in list(container.winfo_children())[1:]:
            child.destroy()

    def _render_summary() -> None:
        _clear_below_title(summary_card)
        if library is None:
            ctk.CTkLabel(summary_card, text="DeviceProfileLibrary ยังไม่ initialized", text_color=theme.DANGER).pack(anchor="w", padx=18, pady=(0, 18))
            return
        counts = library_counts(library)
        info_row(ctk, summary_card, "ทั้งหมด", str(counts["total"])).pack(fill="x", padx=18)
        info_row(ctk, summary_card, "Builtin (ship)", str(counts["builtin"])).pack(fill="x", padx=18)
        info_row(ctk, summary_card, "User (แก้ไขได้)", str(counts["user"])).pack(fill="x", padx=18)
        info_row(ctk, summary_card, "ไฟล์ user JSON", str(user_path)).pack(fill="x", padx=18, pady=(0, 12))

    # Form widgets — declared at module level so edit-mode can pre-fill.
    name_var = StringVar()
    model_var = StringVar()
    rotation_var = StringVar()
    soc_var = StringVar()
    notes_var = StringVar()
    form_title_label = None

    def _render_form() -> None:
        nonlocal form_title_label
        _clear_below_title(form_card)
        target = editing_target["name"]
        header_text = "แก้ไข profile" if target else "เพิ่ม profile ใหม่"
        form_title_label = ctk.CTkLabel(form_card, text=header_text, text_color=theme.TEXT_MUTED, font=(theme.FONT_FAMILY, 13))
        form_title_label.pack(anchor="w", padx=18, pady=(0, 6))

        def _label_and_entry(label_text: str, var: StringVar, placeholder: str = "") -> None:
            ctk.CTkLabel(form_card, text=label_text, text_color=theme.TEXT_MUTED).pack(anchor="w", padx=18, pady=(6, 2))
            ctk.CTkEntry(form_card, textvariable=var, height=38, corner_radius=10, placeholder_text=placeholder).pack(fill="x", padx=18, pady=(0, 4))

        _label_and_entry("ชื่อ *", name_var, placeholder="เช่น Pixel 7")
        _label_and_entry("Model (ro.product.model)", model_var, placeholder="เช่น Pixel_7")
        _label_and_entry("Rotation filter (FFmpeg)", rotation_var, placeholder='เช่น transpose=2,vflip หรือเว้นว่างเพื่อไม่หมุน')
        _label_and_entry("SoC hint", soc_var, placeholder="เช่น Tensor G2 (optional)")
        _label_and_entry("Notes", notes_var, placeholder="หมายเหตุภายใน (optional)")

        actions = ctk.CTkFrame(form_card, fg_color="transparent")
        actions.pack(fill="x", padx=18, pady=(10, 18))

        primary_label = "บันทึกการแก้ไข" if target else "เพิ่ม profile"
        primary_button(ctk, actions, primary_label, command=_on_save).pack(side="left", padx=(0, 8))
        if target:
            subtle_button(ctk, actions, "ยกเลิก", command=_on_cancel_edit).pack(side="left")

    def _on_save() -> None:
        if library is None:
            _notify("DeviceProfileLibrary ยังไม่ initialized", "error")
            return
        target = editing_target["name"]
        err = validate_profile_form(name=name_var.get(), library=library, allow_replace=target or "")
        if err:
            _notify(err, "warning")
            return
        new_profile = make_profile_from_form(
            name=name_var.get(),
            model=model_var.get(),
            rotation_filter=rotation_var.get(),
            soc_hint=soc_var.get(),
            notes=notes_var.get(),
        )
        # If editing and the name changed, remove the old entry first.
        if target and target != new_profile.name:
            library.remove(target)
        library.add(new_profile)
        _persist()
        editing_target["name"] = None
        _reset_form()
        _refresh()
        _notify(f"บันทึก '{new_profile.name}' แล้ว", "success")

    def _on_cancel_edit() -> None:
        editing_target["name"] = None
        _reset_form()
        _render_form()

    def _reset_form() -> None:
        name_var.set("")
        model_var.set("")
        rotation_var.set("")
        soc_var.set("")
        notes_var.set("")

    def _on_edit(profile: DeviceProfile) -> None:
        editing_target["name"] = profile.name
        name_var.set(profile.name)
        model_var.set(profile.model)
        rotation_var.set(profile.rotation_filter)
        soc_var.set(profile.soc_hint)
        notes_var.set(profile.notes)
        _render_form()

    def _on_delete(profile: DeviceProfile) -> None:
        if library is None:
            return
        if not library.remove(profile.name):
            _notify(f"ลบไม่ได้ — '{profile.name}' เป็น builtin", "warning")
            return
        _persist()
        _refresh()
        _notify(f"ลบ '{profile.name}' แล้ว", "info")

    def _render_list() -> None:
        _clear_below_title(list_card)
        if library is None:
            ctk.CTkLabel(list_card, text="DeviceProfileLibrary ยังไม่ initialized", text_color=theme.DANGER).pack(anchor="w", padx=18, pady=(0, 18))
            return
        for profile in library.profiles:
            row = ctk.CTkFrame(list_card, fg_color=theme.SURFACE_SOFT, corner_radius=14)
            row.pack(fill="x", padx=18, pady=6)
            head = ctk.CTkFrame(row, fg_color="transparent")
            head.pack(fill="x", padx=14, pady=(10, 4))
            pill_color = theme.SUCCESS if profile.source == ProfileSource.USER else theme.INFO
            pill_text = "USER" if profile.source == ProfileSource.USER else "BUILTIN"
            status_pill(ctk, head, pill_text, pill_color).pack(side="left", padx=(0, 12))
            ctk.CTkLabel(head, text=profile.name, text_color=theme.TEXT, font=(theme.FONT_FAMILY, 14, "bold")).pack(side="left")
            if is_editable(profile):
                subtle_button(ctk, head, "ลบ", command=lambda p=profile: _on_delete(p)).pack(side="right", padx=(8, 0))
                subtle_button(ctk, head, "แก้ไข", command=lambda p=profile: _on_edit(p)).pack(side="right")
            # body summary
            body = ctk.CTkFrame(row, fg_color="transparent")
            body.pack(fill="x", padx=14, pady=(0, 10))
            for label, value in profile_row_summary(profile).items():
                info_row(ctk, body, label, value).pack(fill="x")

    def _refresh() -> None:
        _render_summary()
        _render_form()
        _render_list()

    _refresh()
    return page
