"""Shared Tk navigation helpers for returning focus to PHI Index."""

from __future__ import annotations

import contextlib
import tkinter as tk


def find_phi_index_parent(window: tk.Misc) -> tk.Misc | None:
    """Return the nearest IndexView ancestor, or None if not in that hierarchy."""
    from anonymizer.view.index import IndexView

    widget: tk.Misc | None = window
    while widget is not None:
        if isinstance(widget, IndexView):
            return widget
        widget = getattr(widget, "master", None)
    return None


def return_to_phi_index(window: tk.Misc) -> None:
    """Refresh the PHI tree and focus IndexView when present in the widget hierarchy."""
    index = find_phi_index_parent(window)
    if index is None:
        return
    index._update_tree_from_phi_index()
    with contextlib.suppress(tk.TclError):
        index.lift()
        index.focus_force()
