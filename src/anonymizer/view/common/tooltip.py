"""Shared hover tooltip helpers for tkinter / customtkinter widgets.

Colors and spacing come from ``ThemeManager.theme["Tooltip"]`` (rsna_theme.json)
so Dataset, Analytics, Series View, and settings dialogs share one look.
"""

from __future__ import annotations

import contextlib
import tkinter as tk
from collections.abc import Callable, Mapping
from typing import Any

import customtkinter as ctk

TooltipText = str | Callable[[], str]

# Fallbacks only if theme JSON is incomplete (keep in sync with rsna_theme Tooltip).
_FALLBACK_FG = ("gray90", "gray20")
_FALLBACK_TEXT = ("#014F8F", "white")
_FALLBACK_BORDER = ("gray70", "gray40")
_FALLBACK_PADX = 8
_FALLBACK_PADY = 5
_FALLBACK_WRAP = 260
TOOLTIP_OFFSET = 12


def _appearance_index() -> int:
    return 1 if ctk.get_appearance_mode() == "Dark" else 0


def _theme_pair(value: Any, fallback: tuple[str, str] | str) -> str:
    """Resolve a theme light/dark pair (or plain string) for the active appearance."""
    raw = value if value is not None else fallback
    if isinstance(raw, (list, tuple)) and len(raw) >= 2:
        return str(raw[_appearance_index()])
    if isinstance(raw, (list, tuple)) and raw:
        return str(raw[0])
    return str(raw)


def _tooltip_theme() -> Mapping[str, Any]:
    section = ctk.ThemeManager.theme.get("Tooltip")
    return section if isinstance(section, Mapping) else {}


def tooltip_style() -> dict[str, Any]:
    """Resolved Tooltip theme tokens for the current appearance mode."""
    theme = _tooltip_theme()
    return {
        "bg": _theme_pair(theme.get("fg_color"), _FALLBACK_FG),
        "fg": _theme_pair(theme.get("text_color"), _FALLBACK_TEXT),
        "border": _theme_pair(theme.get("border_color"), _FALLBACK_BORDER),
        "padx": int(theme.get("padx", _FALLBACK_PADX)),
        "pady": int(theme.get("pady", _FALLBACK_PADY)),
        "wraplength": int(theme.get("wraplength", _FALLBACK_WRAP)),
    }


def _resolve_tooltip_text(text: TooltipText) -> str:
    return text() if callable(text) else text


def show_tooltip(parent: tk.Misc, x_root: int, y_root: int, text: str) -> tk.Toplevel:
    """Show a borderless tooltip window at screen coordinates (theme-styled)."""
    style = tooltip_style()
    tip = tk.Toplevel(parent)
    tip.wm_overrideredirect(True)
    # macOS: use the native help-window style (no heavy shadow / chrome).
    with contextlib.suppress(tk.TclError):
        tip.tk.call(
            "::tk::unsupported::MacWindowStyle",
            "style",
            tip._w,
            "help",
            "noActivates",
        )
    tip.wm_geometry(f"+{x_root + TOOLTIP_OFFSET}+{y_root + TOOLTIP_OFFSET}")
    tip.configure(bg=style["bg"])
    label = tk.Label(
        tip,
        text=text,
        bg=style["bg"],
        fg=style["fg"],
        padx=style["padx"],
        pady=style["pady"],
        wraplength=style["wraplength"],
        justify="left",
        borderwidth=0,
        highlightthickness=0,
    )
    label.pack()
    return tip


class HoverTooltipBinding:
    """Binds Enter/Leave/ButtonPress tooltips to a widget."""

    def __init__(self, widget: tk.Misc, text: TooltipText, *, parent: tk.Misc | None = None) -> None:
        self._widget = widget
        self._text = text
        self._parent = parent
        self._tip: tk.Toplevel | None = None

    def _tooltip_parent(self) -> tk.Misc:
        if self._parent is not None:
            return self._parent
        return self._widget.winfo_toplevel()

    def show(self, event: tk.Event) -> None:
        self.hide()
        resolved = _resolve_tooltip_text(self._text)
        if not resolved:
            return
        self._tip = show_tooltip(self._tooltip_parent(), event.x_root, event.y_root, resolved)

    def hide(self, _event: tk.Event | None = None) -> None:
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None

    def bind(self) -> None:
        self._widget.bind("<Enter>", self.show, add="+")
        self._widget.bind("<Leave>", self.hide, add="+")
        self._widget.bind("<ButtonPress-1>", self.hide, add="+")


def bind_hover_tooltip(
    widget: tk.Misc,
    text: TooltipText,
    *,
    parent: tk.Misc | None = None,
) -> HoverTooltipBinding:
    """Attach a hover tooltip to ``widget``; ``text`` may be a callable for dynamic content."""
    binding = HoverTooltipBinding(widget, text, parent=parent)
    binding.bind()
    return binding


class MotionTooltipController:
    """Debounced tooltip for widgets that report position via motion events (e.g. Treeview)."""

    def __init__(
        self,
        widget: tk.Misc,
        text_for_position: Callable[[tk.Event], str | None],
        *,
        parent: tk.Misc | None = None,
        debounce_ms: int = 300,
    ) -> None:
        self._widget = widget
        self._text_for_position = text_for_position
        self._parent = parent
        self._debounce_ms = debounce_ms
        self._tip: tk.Toplevel | None = None
        self._after_id: str | None = None
        self._pending_event: tk.Event | None = None

    def _tooltip_parent(self) -> tk.Misc:
        if self._parent is not None:
            return self._parent
        return self._widget.winfo_toplevel()

    def hide(self, _event: tk.Event | None = None) -> None:
        if self._after_id is not None:
            self._widget.after_cancel(self._after_id)
            self._after_id = None
        self._pending_event = None
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None

    def _show_pending(self) -> None:
        self._after_id = None
        event = self._pending_event
        if event is None:
            return
        text = self._text_for_position(event)
        if not text:
            self.hide()
            return
        if self._tip is not None:
            self._tip.destroy()
        self._tip = show_tooltip(self._tooltip_parent(), event.x_root, event.y_root, text)

    def on_motion(self, event: tk.Event) -> None:
        self._pending_event = event
        if self._after_id is not None:
            self._widget.after_cancel(self._after_id)
        self._after_id = self._widget.after(self._debounce_ms, self._show_pending)

    def bind(self) -> None:
        self._widget.bind("<Motion>", self.on_motion, add="+")
        self._widget.bind("<Leave>", self.hide, add="+")
        self._widget.bind("<ButtonPress-1>", self.hide, add="+")
