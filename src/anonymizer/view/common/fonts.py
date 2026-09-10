"""Centralized app-lifetime font registry for the view layer.

All CTkFont objects are created once at startup via ``create_app_fonts()`` and
live for the process — no per-view allocation or teardown required.  Widgets
that use the theme default font (San Francisco 13 / Tahoma 13) need no
``font=`` parameter at all; CustomTkinter applies it automatically.

For ``tk.Canvas.create_text`` use ``canvas_label_font()`` which returns a plain
tuple — no Tcl Font object is allocated.
"""

from __future__ import annotations

import logging
import platform
from dataclasses import dataclass

import customtkinter as ctk
from customtkinter import ThemeManager

logger = logging.getLogger(__name__)

_default_ui_font: ctk.CTkFont | None = None


# ---------------------------------------------------------------------------
# Theme helpers
# ---------------------------------------------------------------------------

def theme_font_family() -> str:
    """Return the theme UI font family without allocating a Font object."""
    return ThemeManager.theme["CTkFont"]["family"]


def theme_font_size(default: int = 13) -> int:
    """Return the theme UI font size."""
    size = ThemeManager.theme["CTkFont"].get("size")
    return int(size) if size is not None else default


def _mono_font_family() -> str:
    """Read the mono font family from the Treeview theme section (OS-aware)."""
    family = "Courier New"
    os_map = {"Darwin": "macOS", "Windows": "Windows", "Linux": "Linux"}
    os_key = os_map.get(platform.system())
    if os_key is None:
        logger.error("Unsupported OS: %s - using fallback mono font", platform.system())
        return family
    tv_theme = ThemeManager.theme.get("Treeview", {})
    font_section = tv_theme.get("font", {}).get(os_key, {})
    return font_section.get("family", family)


# ---------------------------------------------------------------------------
# AppFonts — app-lifetime font variants
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AppFonts:
    """App-lifetime font variants created once at startup from the loaded theme.

    Most CTk widgets need no ``font=`` parameter — the theme default applies
    automatically.  Use these named variants only where a non-default size or
    weight is required.
    """

    # Mono family (from Treeview.font in theme)
    mono: ctk.CTkFont          # Menlo 12 — data tables, Treeview
    mono_large: ctk.CTkFont    # Menlo 48 — dashboard counters

    # UI family variants (from CTkFont in theme)
    small: ctk.CTkFont         # 11 — help text, captions
    bold: ctk.CTkFont          # 14 bold — section headers
    heading: ctk.CTkFont       # 20 bold — large headings / radlex values
    title: ctk.CTkFont         # 28 — welcome screen title
    body: ctk.CTkFont          # 20 normal — welcome body (same weight as title)
    label_large: ctk.CTkFont   # 32 — dashboard heading labels


def create_app_fonts() -> AppFonts:
    """Create the app-lifetime font registry (call once on the main thread)."""
    ui = theme_font_family()
    mono = _mono_font_family()
    logger.info("AppFonts: ui=%s  mono=%s", ui, mono)
    return AppFonts(
        mono=ctk.CTkFont(family=mono, size=12),
        mono_large=ctk.CTkFont(family=mono, size=48),
        small=ctk.CTkFont(family=ui, size=11),
        bold=ctk.CTkFont(family=ui, size=14, weight="bold"),
        heading=ctk.CTkFont(family=ui, size=20, weight="bold"),
        title=ctk.CTkFont(family=ui, size=28),
        body=ctk.CTkFont(family=ui, size=20),
        label_large=ctk.CTkFont(family=ui, size=32),
    )


# ---------------------------------------------------------------------------
# Layout / Canvas helpers (kept — no Tcl Font allocated)
# ---------------------------------------------------------------------------

def _default_ui_font_instance() -> ctk.CTkFont:
    """Lazy cached default UI font for measurement (process lifetime)."""
    global _default_ui_font
    if _default_ui_font is None:
        _default_ui_font = ctk.CTkFont(
            family=theme_font_family(),
            size=theme_font_size(),
            weight=ThemeManager.theme["CTkFont"].get("weight", "normal"),
        )
    return _default_ui_font


def char_width_px(font: ctk.CTkFont) -> int:
    """Return pixel width of a typical character for layout sizing."""
    return int(font.measure("A"))


def default_char_width_px() -> int:
    """Return pixel width using the cached default UI font (no ephemeral allocation)."""
    return char_width_px(_default_ui_font_instance())


def canvas_label_font(size: int = 10) -> tuple[str, int]:
    """Return a tuple font for ``tk.Canvas.create_text`` (no Tcl Font object)."""
    return (theme_font_family(), size)
