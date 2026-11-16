"""Modal busy dialog with status text and an indeterminate progress bar."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TypeVar

import customtkinter as ctk

from anonymizer.view.common.app_window import AppToplevel, install_modal_dismiss, place_toplevel_centered_on_parent
from anonymizer.view.common.ctk_safe import teardown_ctk_toplevel

T = TypeVar("T")


class BusyStatusDialog(AppToplevel):
    """
    Small modal status dialog for long UI work.

    Shows an indeterminate progress bar and a one-line status so the app stays
    responsive instead of spinning the system wait cursor with no feedback.
    """

    _PAD = 12
    _WIDTH = 420

    def __init__(self, parent, *, title: str, status: str) -> None:
        super().__init__(master=parent)
        self.withdraw()
        self.title(title)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", lambda: None)

        frame = ctk.CTkFrame(self)
        frame.grid(row=0, column=0, sticky="nsew", padx=self._PAD, pady=self._PAD)
        frame.grid_columnconfigure(0, weight=1)

        self._status = ctk.CTkLabel(frame, text=status, justify="left", wraplength=380, anchor="w")
        self._status.grid(row=0, column=0, sticky="ew", padx=self._PAD, pady=(self._PAD, 8))

        self._bar = ctk.CTkProgressBar(frame, mode="indeterminate", width=360)
        self._bar.grid(row=1, column=0, sticky="ew", padx=self._PAD, pady=(0, self._PAD))
        self._bar.start()

        self.update_idletasks()
        place_toplevel_centered_on_parent(self, parent, width=self._WIDTH, height=int(self.winfo_reqheight()))
        self.deiconify()
        self.wait_visibility()
        self.lift()
        install_modal_dismiss(self, lambda: None)
        self.grab_set()
        self.update_idletasks()

    def set_status(self, status: str) -> None:
        """
        Update the status line.

        Args:
            status: Plain-language progress text.
        """
        self._status.configure(text=status)
        self.update_idletasks()

    def close(self) -> None:
        """Dismiss the dialog."""
        self._bar.stop()
        teardown_ctk_toplevel(self, parent=self.master)


def run_with_busy(
    parent,
    *,
    title: str,
    status: str,
    work: Callable[[], T],
) -> T:
    """
    Run work on a background thread while showing BusyStatusDialog.

    Args:
        parent: Parent window.
        title: Dialog title.
        status: Initial status line.
        work: Callable run off the UI thread (must not touch Tk).

    Returns:
        The value returned by work.

    Raises:
        Exception: Re-raises whatever work raised.
    """
    dialog = BusyStatusDialog(parent, title=title, status=status)
    box: dict[str, object] = {}
    done = threading.Event()

    def _worker() -> None:
        try:
            box["value"] = work()
        except Exception as exc:  # noqa: BLE001 — resurfaced to caller
            box["error"] = exc
        finally:
            done.set()

    threading.Thread(target=_worker, daemon=True).start()
    while not done.wait(0.05):
        dialog.update()
        dialog.update_idletasks()
    dialog.close()
    error = box.get("error")
    if isinstance(error, BaseException):
        raise error
    return box["value"]  # type: ignore[return-value]
