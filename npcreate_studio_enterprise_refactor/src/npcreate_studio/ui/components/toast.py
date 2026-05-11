from __future__ import annotations

from .. import theme


class ToastManager:
    def __init__(self, ctk, root) -> None:
        self.ctk = ctk
        self.root = root
        self._active = None

    def show(self, message: str, *, kind: str = "info", duration_ms: int = 3500) -> None:
        if self._active is not None:
            try:
                self._active.destroy()
            except Exception:
                pass
        colors = {
            "success": theme.SUCCESS,
            "warning": theme.WARNING,
            "error": theme.DANGER,
            "info": theme.INFO,
        }
        frame = self.ctk.CTkFrame(self.root, fg_color=colors.get(kind, theme.INFO), corner_radius=14)
        label = self.ctk.CTkLabel(frame, text=message, text_color="#FFFFFF", font=(theme.FONT_FAMILY, 14, "bold"))
        label.pack(padx=18, pady=12)
        frame.place(relx=0.985, rely=0.035, anchor="ne")
        self._active = frame
        self.root.after(duration_ms, lambda: frame.destroy() if frame.winfo_exists() else None)
