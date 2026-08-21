"""Shared Tk navigation helpers for returning focus to Dataset view."""

from __future__ import annotations

import contextlib
import tkinter as tk


def find_dataset_view_parent(window: tk.Misc) -> tk.Misc | None:
    """Return the nearest DatasetView ancestor, or None if not in that hierarchy."""
    from anonymizer.view.project.dataset import DatasetView

    widget: tk.Misc | None = window
    while widget is not None:
        if isinstance(widget, DatasetView):
            return widget
        widget = getattr(widget, "master", None)
    return None


# Short aliases for call sites that still use the old PHI Index names.
find_phi_index_parent = find_dataset_view_parent


def return_to_dataset_view(window: tk.Misc) -> None:
    """Refresh the dataset tree and focus DatasetView when present in the widget hierarchy."""
    dataset = find_dataset_view_parent(window)
    if dataset is None:
        return
    dataset._update_tree_from_phi_index()
    with contextlib.suppress(tk.TclError):
        dataset.lift()
        dataset.focus_force()


return_to_phi_index = return_to_dataset_view
