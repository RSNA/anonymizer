"""Shared Embedded PHI entity legend widget (Report Text Review / Series View chrome)."""

from __future__ import annotations

from tkinter import Misc

import customtkinter as ctk

from anonymizer.controller.ai.embedded_phi.ner.phi_entity import SCORED_LABELS
from anonymizer.utils.translate import _
from anonymizer.view.reports.entity_colors import entity_color_hex, entity_label_display


class EntityLegend(ctk.CTkFrame):
    """Colored swatch + name per scored label. Vertical by default (right-hand chrome)."""

    def __init__(self, master: Misc, *, orientation: str = "vertical", **kwargs) -> None:
        kwargs.setdefault("fg_color", "transparent")
        super().__init__(master, **kwargs)
        title = ctk.CTkLabel(self, text=_("PHI TYPES"), anchor="w")
        title.grid(row=0, column=0, columnspan=2, sticky="w", padx=6, pady=(4, 8))
        vertical = orientation != "horizontal"
        for i, label in enumerate(SCORED_LABELS):
            row = i + 1 if vertical else 0
            col_swatch = 0 if vertical else i * 2
            col_text = 1 if vertical else i * 2 + 1
            swatch = ctk.CTkLabel(
                self, text="  ", width=14, height=14, corner_radius=3, fg_color=entity_color_hex(label)
            )
            swatch.grid(row=row, column=col_swatch, padx=(6, 2), pady=3, sticky="w")
            text = ctk.CTkLabel(self, text=entity_label_display(label), anchor="w")
            text.grid(row=row, column=col_text, padx=(0, 6), pady=3, sticky="w")
