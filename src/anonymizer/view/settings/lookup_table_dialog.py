"""Dialog for loading a CTP properties lookup table."""

from __future__ import annotations

import contextlib
import logging
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import TYPE_CHECKING, Callable

import customtkinter as ctk

from anonymizer.controller.process_ctp_lookup import (
    CtpLookupPreview,
    LookupPropertiesError,
    commit_ctp_lookup,
    preview_ctp_lookup,
)
from anonymizer.controller.project import ProjectController
from anonymizer.utils.translate import _
from anonymizer.view.common.app_window import AppToplevel, install_modal_dismiss, place_toplevel_centered_on_parent
from anonymizer.view.common.ctk_safe import teardown_ctk_toplevel

if TYPE_CHECKING:
    from anonymizer.controller.anonymizer_script import ScriptDocument

logger = logging.getLogger(__name__)

# Match AnonymizerScriptDialog / settings dialogs (NetworkTimeouts, DICOM node, etc.).
_DIALOG_PAD = 10
_MIN_WIDTH = 560
_MIN_HEIGHT_COMPACT = 280
_CHANGES_BOX_HEIGHT = 220

_INTRO_TEXT = (
    "A Patient Lookup Table is a CTP/TCIA .properties file that maps each PHI "
    "Patient ID to an anonymized ID, and optionally a per-patient date offset in days.\n\n"
    "Example lines:\n"
    "  ptid/MRN-1001=527408-000101\n"
    "  dateoffset/MRN-1001=42\n\n"
    "Accept stores a private copy in the project and enables @lookup operands in "
    "the anonymizer script (and rewrites matching Patient ID / date rules)."
)

# Shown when loading/replacing a table on a live project (not create-project staging).
_EXISTING_PROJECT_NOTE = (
    "If this project already has anonymized data: files already in the dataset "
    "stay unchanged — they are not re-anonymized. Patients already imported keep "
    "working without a lookup-table row. New files whose Patient ID is not in the "
    "table are sent to quarantine as Lookup_Miss and are not stored."
)


class LookupTableDialog(AppToplevel):
    def __init__(
        self,
        parent,
        project_controller: ProjectController | None = None,
        on_script_path_changed: Callable[[Path], None] | None = None,
        on_pending_preview: Callable[[CtpLookupPreview], None] | None = None,
        script_document: ScriptDocument | None = None,
        on_document_patched: Callable[[CtpLookupPreview], None] | None = None,
    ):
        super().__init__(master=parent)
        # Build while withdrawn so the first paint is already centered (no +0+0 flash).
        self.withdraw()
        self._parent = parent
        self.project_controller = project_controller
        self._on_script_path_changed = on_script_path_changed
        self._on_pending_preview = on_pending_preview
        self._script_document = script_document
        self._on_document_patched = on_document_patched
        self._preview: CtpLookupPreview | None = None
        self._committed = False
        self._changes_visible = False

        self.title(_("Load Patient Lookup Table"))
        self.resizable(True, True)
        self.minsize(_MIN_WIDTH, _MIN_HEIGHT_COMPACT)

        self._create_widgets()
        self._fit_to_content()
        self.deiconify()
        self.wait_visibility()
        self.lift()
        install_modal_dismiss(self, self._on_cancel)
        self.grab_set()
        self.bind("<Escape>", self._on_cancel)

    def _create_widgets(self) -> None:
        pad = _DIALOG_PAD
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._frame = ctk.CTkFrame(self)
        self._frame.grid(row=0, column=0, sticky="nsew", padx=pad, pady=pad)
        self._frame.grid_columnconfigure(1, weight=1)

        intro_block = ctk.CTkFrame(self._frame, fg_color="transparent")
        intro_block.grid(row=0, column=0, columnspan=2, sticky="ew", padx=pad, pady=(pad, 0))
        ctk.CTkLabel(
            intro_block, text=_(_INTRO_TEXT), justify="left", wraplength=520, anchor="w"
        ).pack(fill="x")
        if self.project_controller is not None:
            ctk.CTkLabel(
                intro_block,
                text=_(_EXISTING_PROJECT_NOTE),
                justify="left",
                wraplength=520,
                anchor="w",
                font=ctk.CTkFont(weight="bold"),
            ).pack(fill="x", pady=(pad, 0))

        self._path_var = tk.StringVar(value="")
        ctk.CTkLabel(self._frame, text=_("Properties file") + ":").grid(
            row=1, column=0, sticky="nw", padx=pad, pady=pad
        )
        path_row = ctk.CTkFrame(self._frame, fg_color="transparent")
        path_row.grid(row=1, column=1, sticky="ew", padx=pad, pady=pad)

        self._path_entry = ctk.CTkEntry(path_row, textvariable=self._path_var, width=320)
        self._path_entry.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(path_row, text=_("Browse…"), width=90, command=self._on_browse).pack(
            side="left", padx=(pad, 0)
        )

        self._summary_label = ctk.CTkLabel(
            self._frame, text=_("Select a .properties file to preview."), justify="left"
        )
        self._summary_label.grid(row=2, column=0, columnspan=2, sticky="w", padx=pad, pady=(0, pad))

        self._changes_label = ctk.CTkLabel(self._frame, text=_("Script changes") + ":", anchor="w")
        self._changes_box = ctk.CTkTextbox(self._frame, height=_CHANGES_BOX_HEIGHT, wrap="word")
        self._changes_box.configure(state="disabled")
        # Hidden until a properties file is loaded (preview success or validation error).

        button_row = ctk.CTkFrame(self._frame, fg_color="transparent")
        button_row.grid(row=5, column=0, columnspan=2, sticky="e", padx=pad, pady=pad)
        self._accept_button = ctk.CTkButton(
            button_row, text=_("Accept"), command=self._on_accept, state="disabled"
        )
        self._accept_button.pack(side="right", padx=(pad, 0))
        ctk.CTkButton(button_row, text=_("Cancel"), command=self._on_cancel).pack(side="right")

    def _show_changes_section(self) -> None:
        if self._changes_visible:
            return
        pad = _DIALOG_PAD
        self._frame.grid_rowconfigure(4, weight=1)
        self._changes_label.grid(row=3, column=0, columnspan=2, sticky="w", padx=pad, pady=(0, 0))
        self._changes_box.grid(row=4, column=0, columnspan=2, sticky="nsew", padx=pad, pady=(0, 0))
        self._changes_visible = True

    def _fit_to_content(self) -> None:
        """Size to content and re-center; clamp height to the parent window."""
        self.update_idletasks()
        width = max(_MIN_WIDTH, int(self.winfo_reqwidth()))
        height = max(_MIN_HEIGHT_COMPACT, int(self.winfo_reqheight()))
        parent = self._parent
        with contextlib.suppress(tk.TclError):
            parent.update_idletasks()
            parent_h = int(parent.winfo_height())
            parent_w = int(parent.winfo_width())
            if parent_h > 1:
                height = min(height, max(_MIN_HEIGHT_COMPACT, parent_h - 20))
            if parent_w > 1:
                width = min(width, max(_MIN_WIDTH, parent_w - 20))
        place_toplevel_centered_on_parent(self, parent, width=width, height=height)

    def _on_browse(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title=_("Select CTP Lookup Properties"),
            filetypes=[
                (_("Properties Files"), "*.properties"),
                (_("All Files"), "*.*"),
            ],
        )
        if not path:
            return
        self._path_var.set(path)
        self._run_preview(Path(path), show_errors=True)

    def _run_preview(self, path: Path, *, show_errors: bool) -> bool:
        self._show_changes_section()
        try:
            self._preview = preview_ctp_lookup(path, document=self._script_document)
        except LookupPropertiesError as exc:
            self._preview = None
            self._accept_button.configure(state="disabled")
            self._summary_label.configure(text=_("Validation failed."))
            self._set_changes_text(str(exc))
            self._fit_to_content()
            if show_errors:
                messagebox.showerror(_("Patient Lookup Table Error"), str(exc), parent=self)
            return False
        except Exception as exc:
            logger.exception("Lookup preview failed")
            self._preview = None
            self._accept_button.configure(state="disabled")
            self._summary_label.configure(text=_("Validation failed."))
            self._set_changes_text(str(exc))
            self._fit_to_content()
            if show_errors:
                messagebox.showerror(_("Patient Lookup Table Error"), str(exc), parent=self)
            return False

        patient_count = len(self._preview.rows)
        offset_count = sum(1 for row in self._preview.rows if row.date_offset is not None)
        basedate_count = sum(1 for row in self._preview.rows if row.basedate is not None)
        self._summary_label.configure(
            text=_(
                "Patients: {patients}  |  With date offset: {offsets}  |  With basedate: {basedates}"
            ).format(
                patients=patient_count,
                offsets=offset_count,
                basedates=basedate_count,
            )
        )
        lines = [
            f"{change.name} ({change.tag}): {change.before or '@keep'} → {change.after}"
            for change in self._preview.script_patch.changes
        ]
        if not lines:
            lines = [_("No script tag changes required.")]
        self._set_changes_text("\n".join(lines))
        self._accept_button.configure(state="normal")
        self._fit_to_content()
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
                script_path = commit_ctp_lookup(
                    self.project_controller,
                    self._preview,
                    document=self._script_document,
                )
                if self._on_script_path_changed is not None:
                    self._on_script_path_changed(script_path)
                if self._on_document_patched is not None:
                    self._on_document_patched(self._preview)
                success_message = _("Lookup table and project script were updated successfully.")
            else:
                # Create-project staging: apply to in-memory document; defer SQL/files.
                if self._script_document is not None:
                    from anonymizer.controller.process_ctp_lookup import apply_lookup_operands

                    apply_lookup_operands(self._script_document, has_dateoffset=self._preview.has_dateoffset)
                if self._on_pending_preview is not None:
                    self._on_pending_preview(self._preview)
                if self._on_document_patched is not None:
                    self._on_document_patched(self._preview)
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
