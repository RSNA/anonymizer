"""Shared chrome for AI Features Setup and AI Batch Process dialogs.

Spacing is shared. Colors, borders, and fonts come from ``rsna_theme.json``.
"""

from __future__ import annotations

import customtkinter as ctk

FEATURE_DIALOG_PAD = 12
FEATURE_INTRO_WRAP = 480
FEATURE_DETAIL_WRAP = 460
FEATURE_BLOCK_PADY = (0, 6)
FEATURE_DETAIL_PADX = (16, 0)
FEATURE_ACTION_BUTTON_WIDTH = 80


def theme_label_text_color():
    """RSNA CTkLabel color pair. Pass with a custom font so Tk does not fall back to black."""
    return ctk.ThemeManager.theme["CTkLabel"]["text_color"]


def feature_title_label_kwargs() -> dict:
    """Bold feature titles as in AI Features Setup."""
    return {
        "anchor": "w",
        "font": ctk.CTkFont(weight="bold"),
        "text_color": theme_label_text_color(),
    }


def feature_title_control_kwargs() -> dict:
    """Bold RSNA-blue text for CTkCheckBox feature titles."""
    return {
        "font": ctk.CTkFont(weight="bold"),
        "text_color": theme_label_text_color(),
    }
