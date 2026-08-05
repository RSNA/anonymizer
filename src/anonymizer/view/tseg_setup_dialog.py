"""AI Features Setup dialog (Welcome view)."""

from __future__ import annotations

import tkinter as tk
from typing import Callable

import customtkinter as ctk

from anonymizer.utils.translate import _
from anonymizer.view.settings.ai_features_panel import AiFeaturesPanel


class AiFeaturesSetupDialog(tk.Toplevel):
    """Modal dialog for enabling AI tools and checking setup status."""

    def __init__(
        self,
        parent,
        *,
        on_changed: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master=parent)
        self._closing = False
        self._on_changed = on_changed

        self.title(_("AI Features Setup"))
        self.resizable(False, False)
        self._geometry_set = False
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Escape>", lambda _event: self._on_close())

        pad = 12

        frame = ctk.CTkFrame(self)
        frame.grid(row=0, column=0, padx=pad, pady=pad, sticky="nw")
        frame.columnconfigure(0, weight=1)

        intro = _(
            "Select the AI tools you want to use. When a tool is enabled, its status is shown below. "
            "Download models or apply a license when prompted."
        )
        ctk.CTkLabel(frame, text=intro, wraplength=520, justify="left").grid(
            row=0, column=0, padx=pad, pady=(pad, 8), sticky="nw"
        )

        self._panel = AiFeaturesPanel(
            frame,
            on_layout_changed=self._schedule_fit_to_content,
            on_flags_changed=self._notify_changed,
        )
        self._panel.grid(row=1, column=0, padx=pad, pady=(0, 8), sticky="nw")

        self._close_button = ctk.CTkButton(frame, text=_("Close"), command=self._on_close)
        self._close_button.grid(row=2, column=0, padx=pad, pady=(0, pad), sticky="e")

        self.wait_visibility()
        self._schedule_fit_to_content()
        self.grab_set()

    _MIN_WIDTH = 560

    def _schedule_fit_to_content(self) -> None:
        if self._closing:
            return
        self.after_idle(self._fit_to_content)

    def _fit_to_content(self) -> None:
        if self._closing:
            return
        self.update_idletasks()
        width = max(self.winfo_reqwidth(), self._MIN_WIDTH)
        height = self.winfo_reqheight()
        if not self._geometry_set:
            self._geometry_set = True
            parent = self.master
            parent.update_idletasks()
            x = parent.winfo_rootx() + max(0, (parent.winfo_width() - width) // 2)
            y = parent.winfo_rooty() + max(0, (parent.winfo_height() - height) // 2)
        else:
            x, y = self.winfo_x(), self.winfo_y()
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _notify_changed(self) -> None:
        if self._on_changed is not None:
            self._on_changed()

    def _on_close(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._panel.apply_session()
        if self._on_changed is not None:
            self._on_changed()
        self._panel.destroy()
        self.grab_release()
        self.destroy()


def show_ai_features_setup_dialog(
    parent,
    *,
    on_changed: Callable[[], None] | None = None,
) -> None:
    """Open the AI Features Setup dialog modally."""
    AiFeaturesSetupDialog(parent, on_changed=on_changed)
