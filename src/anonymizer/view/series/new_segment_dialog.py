"""New Segment dialog: name + normative organ match for analytics volumes."""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass

import customtkinter as ctk

from anonymizer.controller.ai.tseg.config import PRIMARY_SEGMENT_ORDER
from anonymizer.controller.analytics import organ_display_name
from anonymizer.controller.annotations.store import (
    AnnotateSession,
    label_name_taken,
    resolve_normative_organ,
)
from anonymizer.utils.translate import _
from anonymizer.view.common.app_window import AppToplevel
from anonymizer.view.common.ctk_safe import teardown_ctk_toplevel


@dataclass(frozen=True)
class NewSegmentDialogResult:
    applied: bool = False
    name: str = ""
    normative_organ: str | None = None


class NewSegmentDialog(AppToplevel):
    """Create a user ROI label with optional normative organ mapping."""

    PAD = 12

    def __init__(self, parent: tk.Misc, session: AnnotateSession):
        super().__init__(master=parent)
        self.title(_("New Segment"))
        self._session = session
        self._result = NewSegmentDialogResult()
        self._closing = False
        self.resizable(False, False)

        self._organ_keys = list(PRIMARY_SEGMENT_ORDER)
        self._display_to_key = {organ_display_name(k): k for k in self._organ_keys}
        self._custom_label = _("Custom (no normative band)")
        menu_values = [self._custom_label, *[organ_display_name(k) for k in self._organ_keys]]

        pad = self.PAD
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=0, column=0, sticky="nsew", padx=pad, pady=pad)
        body.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(body, text=_("Segment name"), anchor="w").grid(row=0, column=0, sticky="ew")
        self._name_var = tk.StringVar(value="")
        self._name_entry = ctk.CTkEntry(body, textvariable=self._name_var, width=360)
        self._name_entry.grid(row=1, column=0, sticky="ew", pady=(4, 8))
        self._name_var.trace_add("write", lambda *_a: self._on_name_changed())

        ctk.CTkLabel(body, text=_("Normative organ (analytics)"), anchor="w").grid(
            row=2, column=0, sticky="ew"
        )
        self._organ_var = tk.StringVar(value=self._custom_label)
        self._organ_menu = ctk.CTkOptionMenu(
            body,
            variable=self._organ_var,
            values=menu_values,
            width=360,
            command=lambda _v: self._update_hint(),
        )
        self._organ_menu.grid(row=3, column=0, sticky="ew", pady=(4, 4))

        self._hint_var = tk.StringVar(value="")
        ctk.CTkLabel(
            body,
            textvariable=self._hint_var,
            anchor="w",
            justify="left",
            wraplength=360,
            text_color=("gray40", "gray60"),
        ).grid(row=4, column=0, sticky="ew", pady=(0, 4))

        self._error_var = tk.StringVar(value="")
        ctk.CTkLabel(
            body,
            textvariable=self._error_var,
            anchor="w",
            text_color=("#B00020", "#FF8A80"),
        ).grid(row=5, column=0, sticky="ew", pady=(0, 8))

        buttons = ctk.CTkFrame(body, fg_color="transparent")
        buttons.grid(row=6, column=0, sticky="e")
        ctk.CTkButton(buttons, width=100, text=_("Cancel"), command=self._on_cancel).pack(
            side="left", padx=(0, 8)
        )
        ctk.CTkButton(buttons, width=100, text=_("Create"), command=self._on_ok).pack(side="left")

        self.bind("<Return>", lambda _e: self._on_ok())
        self.bind("<Escape>", lambda _e: self._on_cancel())
        self._update_hint()
        self.wait_visibility()
        self.lift()
        self.grab_set()
        self._name_entry.focus()

    def _selected_normative_organ(self) -> str | None:
        label = self._organ_var.get()
        if label == self._custom_label:
            return None
        return self._display_to_key.get(label)

    def _on_name_changed(self) -> None:
        self._error_var.set("")
        matched = resolve_normative_organ(self._name_var.get())
        if matched is not None:
            self._organ_var.set(organ_display_name(matched))
        self._update_hint()

    def _update_hint(self) -> None:
        key = self._selected_normative_organ()
        if key is None:
            self._hint_var.set(_("No normative band; shown from measured volumes"))
        else:
            self._hint_var.set(
                _("Uses healthy range for {organ}").format(organ=organ_display_name(key))
            )

    def _on_ok(self) -> None:
        if self._closing:
            return
        name = self._name_var.get().strip()
        if not name:
            self._error_var.set(_("Enter a segment name"))
            return
        if label_name_taken(self._session, name):
            self._error_var.set(_("A segment with this name already exists"))
            return
        self._result = NewSegmentDialogResult(
            applied=True,
            name=name,
            normative_organ=self._selected_normative_organ(),
        )
        self._closing = True
        teardown_ctk_toplevel(self, parent=self.master)

    def _on_cancel(self) -> None:
        if self._closing:
            return
        self._closing = True
        teardown_ctk_toplevel(self, parent=self.master)

    def get_input(self) -> NewSegmentDialogResult:
        self.focus()
        self.master.wait_window(self)
        return self._result


def show_new_segment_dialog(parent: tk.Misc, session: AnnotateSession) -> NewSegmentDialogResult:
    dialog = NewSegmentDialog(parent, session)
    return dialog.get_input()
