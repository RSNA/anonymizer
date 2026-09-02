"""Shared hover tooltip helpers for tkinter / customtkinter widgets."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

TooltipText = str | Callable[[], str]

TOOLTIP_BG = "#333333"
TOOLTIP_FG = "white"
TOOLTIP_WRAPLENGTH = 220
TOOLTIP_OFFSET = 12


def _resolve_tooltip_text(text: TooltipText) -> str:
    return text() if callable(text) else text


def show_tooltip(parent: tk.Misc, x_root: int, y_root: int, text: str) -> tk.Toplevel:
    """Show a borderless tooltip window at screen coordinates."""
    tip = tk.Toplevel(parent)
    tip.wm_overrideredirect(True)
    tip.wm_geometry(f"+{x_root + TOOLTIP_OFFSET}+{y_root + TOOLTIP_OFFSET}")
    label = tk.Label(
        tip,
        text=text,
        bg=TOOLTIP_BG,
        fg=TOOLTIP_FG,
        padx=6,
        pady=4,
        wraplength=TOOLTIP_WRAPLENGTH,
        justify="left",
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
