"""Dialog for loading a CTP properties lookup table."""

from __future__ import annotations

import logging
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Callable

import customtkinter as ctk

from anonymizer.controller.process_ctp_lookup import (
    CtpLookupPreview,
    LookupPropertiesError,
    commit_ctp_lookup,
    preview_ctp_lookup,
)
from anonymizer.controller.project import ProjectController
from anonymizer.utils.translate import _
from anonymizer.view.common.app_window import AppToplevel
from anonymizer.view.common.ctk_safe import teardown_ctk_toplevel

logger = logging.getLogger(__name__)


class LookupTableDialog(AppToplevel):
    def __init__(
        self,
        parent,
        project_controller: ProjectController | None = None,
        on_script_path_changed: Callable[[Path], None] | None = None,
        on_pending_preview: Callable[[CtpLookupPreview], None] | None = None,
    ):
        super().__init__(master=parent)
        self.project_controller = project_controller
        self._on_script_path_changed = on_script_path_changed
        self._on_pending_preview = on_pending_preview
        self._preview: CtpLookupPreview | None = None
        self._committed = False

        self.title(_("Load Patient Lookup Table"))
        self.resizable(True, True)
        self.minsize(520, 400)

        self._create_widgets()
        self.wait_visibility()
        self.lift()
        self.grab_set()
        self.bind("<Escape>", self._on_cancel)

    def _create_widgets(self) -> None:
        pad = 10
        frame = ctk.CTkFrame(self)
        frame.pack(fill="both", expand=True, padx=pad, pady=pad)

        self._path_var = tk.StringVar(value="")
        ctk.CTkLabel(frame, text=_("Properties file") + ":").grid(row=0, column=0, sticky="nw", padx=pad, pady=pad)
        path_row = ctk.CTkFrame(frame, fg_color="transparent")
        path_row.grid(row=0, column=1, sticky="ew", padx=pad, pady=pad)
        frame.grid_columnconfigure(1, weight=1)

        self._path_entry = ctk.CTkEntry(path_row, textvariable=self._path_var, width=320)
        self._path_entry.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(path_row, text=_("Browse…"), width=90, command=self._on_browse).pack(side="left", padx=(pad, 0))

        self._summary_label = ctk.CTkLabel(frame, text=_("Select a .properties file to preview."), justify="left")
        self._summary_label.grid(row=1, column=0, columnspan=2, sticky="w", padx=pad, pady=(0, pad))

        ctk.CTkLabel(frame, text=_("Script changes") + ":").grid(row=2, column=0, columnspan=2, sticky="w", padx=pad)
        self._changes_box = ctk.CTkTextbox(frame, height=220, wrap="word")
        self._changes_box.grid(row=3, column=0, columnspan=2, sticky="nsew", padx=pad, pady=(0, pad))
        frame.grid_rowconfigure(3, weight=1)
        self._changes_box.configure(state="disabled")

        button_row = ctk.CTkFrame(frame, fg_color="transparent")
        button_row.grid(row=4, column=0, columnspan=2, sticky="e", padx=pad, pady=pad)
        self._accept_button = ctk.CTkButton(button_row, text=_("Accept"), command=self._on_accept, state="disabled")
        self._accept_button.pack(side="right", padx=(pad, 0))
        ctk.CTkButton(button_row, text=_("Cancel"), command=self._on_cancel).pack(side="right")

    def _on_browse(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title=_("Select CTP Lookup Properties File"),
            filetypes=[(_("Properties Files"), "*.properties"), (_("All Files"), "*.*")],
        )
        if not path:
            return
        self.load_properties_path(Path(path))

    def load_properties_path(self, path: Path, *, show_errors: bool = True) -> bool:
        """Load and preview a CTP ``.properties`` file (used by Browse and automation)."""
        self._path_var.set(str(path))
        try:
            self._preview = preview_ctp_lookup(path)
        except LookupPropertiesError as exc:
            self._preview = None
            self._accept_button.configure(state="disabled")
            self._summary_label.configure(text=_("Validation failed."))
            self._set_changes_text(str(exc))
            if show_errors:
                messagebox.showerror(_("Patient Lookup Table Error"), str(exc), parent=self)
            return False

        patient_count = len(self._preview.rows)
        offset_count = sum(1 for row in self._preview.rows if row.date_offset is not None)
        self._summary_label.configure(
            text=_("Patients: {patients}  |  With date offset: {offsets}").format(
                patients=patient_count, offsets=offset_count
            )
        )
        lines = [
            f"{change.name} ({change.tag}): {change.before} → {change.after}"
            for change in self._preview.script_patch.changes
        ]
        if not lines:
            lines = [_("No script tag changes required.")]
        self._set_changes_text("\n".join(lines))
        self._accept_button.configure(state="normal")
        return True

    def _set_changes_text(self, text: str) -> None:
        self._changes_box.configure(state="normal")
        self._changes_box.delete("1.0", "end")
        self._changes_box.insert("1.0", text)
        self._changes_box.configure(state="disabled")

    def _on_accept(self) -> None:
        if self._preview is None:
            return
        try:
            if self.project_controller is not None:
                script_path = commit_ctp_lookup(self.project_controller, self._preview)
                if self._on_script_path_changed is not None:
                    self._on_script_path_changed(script_path)
                success_message = _("Lookup table and project script were updated successfully.")
            else:
                if self._on_pending_preview is not None:
                    self._on_pending_preview(self._preview)
                success_message = _("Lookup table will be loaded when the project is created.")
        except Exception as exc:
            logger.exception("CTP lookup commit failed")
            messagebox.showerror(_("Patient Lookup Table Error"), str(exc), parent=self)
            return
        self._committed = True
        messagebox.showinfo(_("Load Patient Lookup Table"), success_message, parent=self)
        teardown_ctk_toplevel(self, parent=self.master)

    def _on_cancel(self, _event=None) -> None:
        teardown_ctk_toplevel(self, parent=self.master)

    def committed(self) -> bool:
        return self._committed
