from __future__ import annotations

from typing import Callable

from .. import theme


def section_title(ctk, parent, title: str, subtitle: str = ""):
    wrap = ctk.CTkFrame(parent, fg_color="transparent")
    ctk.CTkLabel(wrap, text=title, font=(theme.FONT_FAMILY, 24, "bold"), text_color=theme.TEXT).pack(anchor="w")
    if subtitle:
        ctk.CTkLabel(wrap, text=subtitle, font=(theme.FONT_FAMILY, 13), text_color=theme.TEXT_MUTED).pack(anchor="w", pady=(4, 0))
    return wrap


def card(ctk, parent, title: str = ""):
    frame = ctk.CTkFrame(parent, fg_color=theme.SURFACE, corner_radius=theme.CARD_RADIUS, border_width=1, border_color=theme.BORDER)
    if title:
        ctk.CTkLabel(frame, text=title, font=(theme.FONT_FAMILY, 16, "bold"), text_color=theme.TEXT).pack(anchor="w", padx=18, pady=(16, 6))
    return frame


def metric_card(ctk, parent, label: str, value: str, hint: str, accent: str = theme.PRIMARY):
    frame = card(ctk, parent)
    ctk.CTkLabel(frame, text=label, font=(theme.FONT_FAMILY, 13), text_color=theme.TEXT_MUTED).pack(anchor="w", padx=18, pady=(16, 2))
    ctk.CTkLabel(frame, text=value, font=(theme.FONT_FAMILY, 26, "bold"), text_color=theme.TEXT).pack(anchor="w", padx=18)
    ctk.CTkLabel(frame, text=hint, font=(theme.FONT_FAMILY, 12), text_color=theme.TEXT_MUTED).pack(anchor="w", padx=18, pady=(4, 16))
    bar = ctk.CTkFrame(frame, height=4, fg_color=accent, corner_radius=4)
    bar.pack(fill="x", padx=18, pady=(0, 16))
    return frame


def primary_button(ctk, parent, text: str, command: Callable[[], None] | None = None):
    return ctk.CTkButton(parent, text=text, command=command, fg_color=theme.PRIMARY, hover_color=theme.PRIMARY_HOVER, corner_radius=12, height=40)


def subtle_button(ctk, parent, text: str, command: Callable[[], None] | None = None):
    return ctk.CTkButton(parent, text=text, command=command, fg_color=theme.SURFACE_SOFT, hover_color=theme.BORDER, corner_radius=12, height=40)


def status_pill(ctk, parent, text: str, color: str = theme.SUCCESS):
    pill = ctk.CTkLabel(parent, text=f"  {text}  ", fg_color=color, text_color="#FFFFFF", corner_radius=999, font=(theme.FONT_FAMILY, 12, "bold"))
    return pill


def info_row(ctk, parent, label: str, value: str):
    row = ctk.CTkFrame(parent, fg_color="transparent")
    row.grid_columnconfigure(1, weight=1)
    ctk.CTkLabel(row, text=label, text_color=theme.TEXT_MUTED, font=(theme.FONT_FAMILY, 13)).grid(row=0, column=0, sticky="w", padx=(0, 12), pady=6)
    ctk.CTkLabel(row, text=value, text_color=theme.TEXT, font=(theme.FONT_FAMILY, 13, "bold"), wraplength=520, justify="left").grid(row=0, column=1, sticky="w", pady=6)
    return row
