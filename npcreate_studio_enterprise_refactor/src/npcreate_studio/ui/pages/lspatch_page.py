"""Patch TikTok page — drive the LSPatch pipeline from the UI.

Surfaces ``LSPatchService`` as four sequential steps the user clicks
through: probe → pull → patch → install. Each long subprocess runs on
a worker thread; results marshal back to the Tk main thread via
``page.after(0, …)``.

The install step is destructive (uninstalls stock TikTok = user logs
out). We disable it until pull + patch both succeeded, and gate it
behind a toast that names the cost.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

from ...services.lspatch_service import (
    InstallResult,
    LSPatchService,
    PatchResult,
    PullResult,
    ToolStatus,
)
from .. import theme
from ..components import card, primary_button, section_title, status_pill, subtle_button

log = logging.getLogger(__name__)


def build(ctk, parent, settings, services: dict[str, Any] | None = None):
    services = services or {}
    adb = services.get("adb_service")
    toast = services.get("toast")

    if adb is None:
        page = ctk.CTkFrame(parent, fg_color="transparent")
        ctk.CTkLabel(
            page, text="AdbService ยังไม่ initialized — ตรวจ build_services",
            text_color=theme.DANGER,
        ).pack(padx=20, pady=20)
        return page

    lspatch = LSPatchService(
        adb=adb,
        cache_dir=settings.app_data_path / "lspatch",
    )

    # Working state shared between step handlers.
    state: dict[str, Any] = {
        "tool_status": None,        # ToolStatus
        "pull_result": None,        # PullResult
        "patch_result": None,       # PatchResult
        "patched_pkg": "",
    }

    page = ctk.CTkScrollableFrame(parent, fg_color="transparent")
    section_title(
        ctk, page, "Patch TikTok (LSPatch, no root)",
        "ฉีด CameraHook เข้า TikTok APK โดยตรง — ไม่ต้อง root เครื่อง",
    ).pack(fill="x", padx=8, pady=(6, 14))

    def _notify(msg: str, kind: str = "info") -> None:
        if toast is not None:
            toast.show(msg, kind=kind)
        else:
            log.info("toast: %s", msg)

    # ── status banner ─────────────────────────────────────────────────
    banner_card = card(ctk, page, "สถานะ TikTok บนโทรศัพท์")
    banner_card.pack(fill="x", padx=8, pady=(0, 12))
    banner_pill_holder = ctk.CTkFrame(banner_card, fg_color="transparent")
    banner_pill_holder.pack(anchor="w", padx=18, pady=(10, 6))
    banner_info = ctk.CTkLabel(
        banner_card, text="กด 'รีเฟรช' เพื่อตรวจสถานะ", text_color=theme.TEXT_MUTED,
        wraplength=900, justify="left",
    )
    banner_info.pack(anchor="w", padx=18, pady=(0, 10))

    def _refresh_status() -> None:
        def _worker() -> None:
            st = lspatch.installed_status()
            page.after(0, lambda s=st: _render_banner(s))
        threading.Thread(target=_worker, daemon=True, name="np-lspatch-status").start()

    def _render_banner(s: LSPatchService.InstalledStatus) -> None:
        for w in banner_pill_holder.winfo_children():
            w.destroy()
        if not s.package:
            status_pill(ctk, banner_pill_holder, "ไม่พบ TikTok", theme.DANGER).pack(side="left")
            banner_info.configure(text="ติดตั้ง TikTok ก่อน")
            return
        label = "Patched ✓" if s.is_patched else "Stock"
        color = theme.SUCCESS if s.is_patched else theme.WARNING
        status_pill(ctk, banner_pill_holder, label, color).pack(side="left")
        banner_info.configure(
            text=(
                f"package={s.package}  v{s.version_name}\n"
                f"signature fingerprint={s.fingerprint or '?'}  "
                + ("(LSPatch debug key)" if s.is_patched else "(Google original)")
            ),
        )

    subtle_button(ctk, banner_card, "🔄 รีเฟรช", command=_refresh_status).pack(
        anchor="w", padx=18, pady=(0, 14),
    )

    # ── step 1: probe ─────────────────────────────────────────────────
    step1 = card(ctk, page, "ขั้น 1 — ตรวจเครื่องมือ (java / lspatch.jar / receiver APK)")
    step1.pack(fill="x", padx=8, pady=(0, 12))
    step1_status = ctk.CTkLabel(
        step1, text="—", text_color=theme.TEXT_MUTED,
        wraplength=900, justify="left",
    )
    step1_status.pack(anchor="w", padx=18, pady=(8, 0))

    def _on_probe() -> None:
        def _worker() -> None:
            st = lspatch.probe_tools()
            page.after(0, lambda x=st: _back_probe(x))
        threading.Thread(target=_worker, daemon=True, name="np-lspatch-probe").start()

    def _back_probe(st: ToolStatus) -> None:
        state["tool_status"] = st
        if st.ok:
            txt = (
                f"✓ java {st.java_version.split(chr(10))[0]}\n"
                f"✓ lspatch.jar: {st.lspatch}\n"
                f"✓ receiver APK: {st.receiver_apk}\n"
                f"✓ adb available"
            )
            step1_status.configure(text=txt, text_color=theme.SUCCESS)
            pull_btn.configure(state="normal")
            _notify("เครื่องมือพร้อม", "success")
        else:
            step1_status.configure(
                text="❌ " + "\n❌ ".join(st.errors), text_color=theme.DANGER,
            )
            _notify("เครื่องมือไม่พร้อม — ดูข้อความขั้น 1", "error")

    primary_button(ctk, step1, "ตรวจเครื่องมือ", command=_on_probe).pack(
        anchor="w", padx=18, pady=(8, 14),
    )

    # ── step 2: pull ──────────────────────────────────────────────────
    step2 = card(ctk, page, "ขั้น 2 — Pull TikTok APKs จากโทรศัพท์")
    step2.pack(fill="x", padx=8, pady=(0, 12))
    step2_status = ctk.CTkLabel(
        step2, text="ยังไม่ได้ pull", text_color=theme.TEXT_MUTED,
        wraplength=900, justify="left",
    )
    step2_status.pack(anchor="w", padx=18, pady=(8, 0))

    def _on_pull() -> None:
        pull_btn.configure(state="disabled", text="กำลัง pull…")

        def _worker() -> None:
            result = lspatch.pull_tiktok()
            page.after(0, lambda r=result: _back_pull(r))
        threading.Thread(target=_worker, daemon=True, name="np-lspatch-pull").start()

    def _back_pull(r: PullResult) -> None:
        pull_btn.configure(state="normal", text="Pull TikTok")
        if not r.ok:
            step2_status.configure(text=f"❌ {r.error}", text_color=theme.DANGER)
            _notify(f"Pull ล้มเหลว: {r.error}", "error")
            return
        state["pull_result"] = r
        step2_status.configure(
            text=(
                f"✓ {r.package} v{r.version_name}\n"
                f"  {len(r.apks)} APKs ({sum(p.stat().st_size for p in r.apks):,} B) "
                f"in {r.elapsed_s:.1f}s"
            ),
            text_color=theme.SUCCESS,
        )
        patch_btn.configure(state="normal")
        _notify(f"Pull สำเร็จ — {len(r.apks)} APKs", "success")

    pull_btn = primary_button(ctk, step2, "Pull TikTok", command=_on_pull)
    pull_btn.configure(state="disabled")
    pull_btn.pack(anchor="w", padx=18, pady=(8, 14))

    # ── step 3: patch ─────────────────────────────────────────────────
    step3 = card(ctk, page, "ขั้น 3 — LSPatch (embed CameraHook into APKs)")
    step3.pack(fill="x", padx=8, pady=(0, 12))
    step3_status = ctk.CTkLabel(
        step3, text="ยังไม่ได้ patch", text_color=theme.TEXT_MUTED,
        wraplength=900, justify="left",
    )
    step3_status.pack(anchor="w", padx=18, pady=(8, 0))

    def _on_patch() -> None:
        pull = state["pull_result"]
        if pull is None:
            _notify("Pull ก่อน", "warning")
            return
        patch_btn.configure(state="disabled", text="กำลัง patch…")

        def _worker() -> None:
            result = lspatch.patch(apks=pull.apks)
            page.after(0, lambda r=result: _back_patch(r))
        threading.Thread(target=_worker, daemon=True, name="np-lspatch-patch").start()

    def _back_patch(r: PatchResult) -> None:
        patch_btn.configure(state="normal", text="Patch")
        if not r.ok:
            step3_status.configure(
                text=f"❌ {r.error}\n{r.log_tail[:300]}",
                text_color=theme.DANGER,
            )
            _notify(f"Patch ล้มเหลว: {r.error}", "error")
            return
        state["patch_result"] = r
        total = sum(p.stat().st_size for p in r.patched_apks)
        step3_status.configure(
            text=(
                f"✓ {len(r.patched_apks)} patched APKs ({total / 1024 / 1024:.1f} MB)\n"
                f"  in {r.elapsed_s:.1f}s — {r.output_dir}"
            ),
            text_color=theme.SUCCESS,
        )
        install_btn.configure(state="normal")
        _notify(f"Patch สำเร็จ — {len(r.patched_apks)} APKs", "success")

    patch_btn = primary_button(ctk, step3, "Patch", command=_on_patch)
    patch_btn.configure(state="disabled")
    patch_btn.pack(anchor="w", padx=18, pady=(8, 14))

    # ── step 4: install ───────────────────────────────────────────────
    step4 = card(ctk, page, "ขั้น 4 — Install Patched TikTok (DESTRUCTIVE)")
    step4.pack(fill="x", padx=8, pady=(0, 12))
    ctk.CTkLabel(
        step4,
        text=(
            "⚠️ จะ uninstall TikTok เดิม + install version ที่ patched. "
            "User จะ logout จาก TikTok และต้อง login ใหม่ครั้งเดียว."
        ),
        text_color=theme.WARNING, wraplength=900, justify="left",
    ).pack(anchor="w", padx=18, pady=(8, 4))
    step4_status = ctk.CTkLabel(
        step4, text="ยังไม่ได้ install", text_color=theme.TEXT_MUTED,
        wraplength=900, justify="left",
    )
    step4_status.pack(anchor="w", padx=18, pady=(8, 0))

    def _on_install() -> None:
        pull = state["pull_result"]
        patch_r = state["patch_result"]
        if pull is None or patch_r is None:
            _notify("Pull + Patch ก่อน", "warning")
            return
        install_btn.configure(state="disabled", text="กำลัง install…")

        def _worker() -> None:
            result = lspatch.install(
                package=pull.package,
                patched_apks=patch_r.patched_apks,
                original_apks=pull.apks,
            )
            page.after(0, lambda r=result: _back_install(r))
        threading.Thread(target=_worker, daemon=True, name="np-lspatch-install").start()

    def _back_install(r: InstallResult) -> None:
        install_btn.configure(state="normal", text="✅ Install Patched")
        if not r.ok:
            extra = ""
            if r.rollback_attempted:
                extra = f"\nrollback: {'✓' if r.rollback_ok else '✗ ' + r.rollback_error}"
            step4_status.configure(
                text=f"❌ {r.error}{extra}", text_color=theme.DANGER,
            )
            _notify(f"Install ล้มเหลว: {r.error[:80]}", "error")
            return
        step4_status.configure(
            text=(
                f"✓ Install สำเร็จใน {r.elapsed_s:.1f}s\n"
                f"  signature fingerprint = {r.fingerprint}  "
                + ("(LSPatch — patched ✓)" if r.fingerprint == lspatch.LSPATCH_FINGERPRINT
                   else "(unexpected fingerprint)")
            ),
            text_color=theme.SUCCESS,
        )
        _notify("Install สำเร็จ — เปิด TikTok + login เพื่อใช้งาน", "success")
        _refresh_status()

    install_btn = primary_button(ctk, step4, "✅ Install Patched", command=_on_install)
    install_btn.configure(state="disabled")
    install_btn.pack(anchor="w", padx=18, pady=(8, 14))

    # ── help ──────────────────────────────────────────────────────────
    help_card = card(ctk, page, "หลังจาก install สำเร็จ")
    help_card.pack(fill="x", padx=8, pady=(0, 16))
    ctk.CTkLabel(
        help_card,
        text=(
            "1. เปิด TikTok ใหม่ (signature เปลี่ยน → ต้อง login ใหม่ครั้งเดียว)\n"
            "2. Copy วิดีโอที่จะใช้ไปที่ /sdcard/vcam_final.mp4 บนโทรศัพท์\n"
            "3. เปิด switch: adb shell touch /data/local/tmp/vcam_enabled\n"
            "4. ใน TikTok กด Live — กล้องจะถูกแทนที่ด้วยวิดีโอจากไฟล์\n"
            "5. ปิด switch: adb shell rm /data/local/tmp/vcam_enabled"
        ),
        text_color=theme.TEXT, wraplength=900, justify="left",
        font=(theme.FONT_FAMILY, 13),
    ).pack(anchor="w", padx=18, pady=(8, 16))

    _refresh_status()
    return page
