"""Shared Tk navigation helpers for Dataset View and workspace focus restore.

Public API
----------
find_dataset_view_parent(window) -> tk.Misc | None
    Nearest DatasetView ancestor, or None.

return_to_dataset_view(window) -> None
    Refresh the Dataset tree and focus DatasetView when present.

return_after_workspace(window, opener) -> None
    Refresh Dataset when present; focus opener if it still exists, else DatasetView.
"""

import contextlib
import tkinter as tk


def find_dataset_view_parent(window: tk.Misc) -> tk.Misc | None:
    """Return the nearest DatasetView ancestor, or None if not in that hierarchy."""

    widget: tk.Misc | None = window
    while widget is not None:
        if getattr(widget, "IS_DATASET_VIEW", False) is True:
            return widget
        widget = getattr(widget, "master", None)
    return None


# Short aliases for call sites that still use the old PHI Index names.
find_phi_index_parent = find_dataset_view_parent


def _refresh_dataset_view(dataset: tk.Misc) -> None:
    """
    Reload the Dataset tree from the PHI index.

    Args:
        dataset: DatasetView instance.
    """
    dataset._update_tree_from_phi_index()


def _focus_window(window: tk.Misc) -> bool:
    """
    Lift and focus window when it still exists.

    Args:
        window: Toplevel or widget to focus.

    Returns:
        True when focus was applied.
    """
    with contextlib.suppress(tk.TclError):
        if window.winfo_exists():
            window.lift()
            window.focus_force()
            return True
    return False


def return_to_dataset_view(window: tk.Misc) -> None:
    """Refresh the dataset tree and focus DatasetView when present in the widget hierarchy."""
    dataset = find_dataset_view_parent(window)
    if dataset is None:
        return
    _refresh_dataset_view(dataset)
    _focus_window(dataset)


def return_after_workspace(window: tk.Misc, opener: tk.Misc | None) -> None:
    """
    Restore UI after closing Series View or Report Text Review.

    Always refreshes Dataset View when it is in the hierarchy (Embedded PHI /
    status columns). Focus returns to opener when that window still exists
    (e.g. View Projections); otherwise focuses Dataset View.

    Args:
        window: Closing workspace (used to locate DatasetView via master chain).
        opener: Window that opened the workspace (ProjectionView, DatasetView, …).
    """
    dataset = find_dataset_view_parent(window)
    if dataset is not None:
        _refresh_dataset_view(dataset)

    if opener is not None and _focus_window(opener):
        return
    if dataset is not None:
        _focus_window(dataset)


return_to_phi_index = return_to_dataset_view
