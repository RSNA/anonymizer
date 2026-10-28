"""De-identification Options dialog: list on the left, explanation on the right."""

from __future__ import annotations

import contextlib
import logging
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

import customtkinter as ctk

from anonymizer.controller.ai.feature_availability import deid_option_ready
from anonymizer.controller.ai.feature_ids import ai_feature_for_deid_option
from anonymizer.controller.script.option_explanations import (
    apply_date_option_exclusivity,
    deid_option_explanation,
)
from anonymizer.model.project import BASIC_OPTIONS, RETAIN_OPTIONS
from anonymizer.utils.dicom import (
    DICOM_CONFIDENTIALITY_PROFILE_URL,
    DeidMethodCode,
    deid_method_meaning,
)
from anonymizer.utils.translate import _
from anonymizer.view.ai.features.availability import DownloadCompleteEvent, get_download_manager
from anonymizer.view.ai.features.catalog import groups_for
from anonymizer.view.common.app_window import AppToplevel, install_modal_dismiss
from anonymizer.view.common.ctk_safe import teardown_ctk_toplevel
from anonymizer.view.common.tooltip import bind_hover_tooltip
from anonymizer.view.common.ux_fields import button_width_for_label

logger = logging.getLogger(__name__)

_PAD = 12
_HELP_WRAP = 380
_LIST_WIDTH = 440
_DIALOG_MIN_HEIGHT = 560


class DeidentificationOptionsDialog(AppToplevel):
    """
    Choose DICOM confidentiality options with a plain-language detail panel.

    Args:
        parent: Parent window.
        selected: Currently selected option codes.
    """

    def __init__(
        self,
        parent,
        selected: frozenset[DeidMethodCode],
    ) -> None:
        super().__init__(master=parent)
        self.title(_("De-identification Options"))
        self.resizable(True, True)
        self._user_input: frozenset[DeidMethodCode] | None = None
        self._change_guard = False
        self._focused: DeidMethodCode = DeidMethodCode.BASIC
        self._option_vars: dict[DeidMethodCode, tk.BooleanVar] = {}
        self._row_frames: dict[DeidMethodCode, ctk.CTkFrame] = {}

        initial = frozenset(selected) | {DeidMethodCode.BASIC}
        for code in DeidMethodCode:
            self._option_vars[code] = tk.BooleanVar(value=code in initial)

        # Outer padded frame like Project Settings (single tone; no nested toolbar).
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.bind("<Return>", self._enter_keypress)
        self.bind("<Escape>", self._escape_keypress)
        self._create_widgets()
        self._show_explanation(self._focused)
        self.wait_visibility()
        self.lift()
        install_modal_dismiss(self, self._on_cancel)
        self.grab_set()

    @staticmethod
    def _open_url(url: str) -> None:
        try:
            webbrowser.open(url)
        except Exception:
            logger.exception("Failed to open URL %s", url)

    def _link_button(self, master: ctk.CTkFrame, text: str, url: str, *, width: int = 90) -> ctk.CTkButton:
        """Transparent link-styled button (same pattern as Welcome View LOINC/RadLex)."""
        button = ctk.CTkButton(
            master=master,
            text=text,
            width=width,
            height=28,
            fg_color="transparent",
            hover_color=("gray80", "gray30"),
            text_color=("#1a5fb4", "#62a0ea"),
            anchor="w",
            command=lambda: self._open_url(url),
        )
        with contextlib.suppress(Exception):
            button.configure(cursor="hand2")
        return button

    def _open_help_link(self) -> None:
        if self._help_link_url:
            self._open_url(self._help_link_url)

    def _create_widgets(self) -> None:
        pad = _PAD
        self._frame = ctk.CTkFrame(self)
        self._frame.grid(row=0, column=0, padx=pad, pady=pad, sticky="nsew")
        self._frame.grid_rowconfigure(1, weight=1)
        self._frame.grid_columnconfigure(0, weight=1)

        dicom_ref = _("DICOM confidentiality profile options (PS 3.15 Appendix E, Table E.1-1)")
        dicom_link = self._link_button(
            self._frame,
            dicom_ref,
            DICOM_CONFIDENTIALITY_PROFILE_URL,
            width=button_width_for_label(dicom_ref, minimum=100),
        )
        dicom_link.grid(row=0, column=0, sticky="w", padx=pad, pady=(pad, 0))
        bind_hover_tooltip(dicom_link, _("View on dicom.nema.org"))

        body = ctk.CTkFrame(self._frame, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew", padx=pad, pady=pad)
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(2, weight=2)
        body.grid_rowconfigure(0, weight=1)

        list_frame = ctk.CTkFrame(body, fg_color="transparent")
        list_frame.grid(row=0, column=0, sticky="nsew", padx=(0, pad))
        list_frame.grid_columnconfigure(0, weight=1)

        for i, code in enumerate(DeidMethodCode):
            row = ctk.CTkFrame(list_frame, fg_color="transparent", cursor="hand2")
            row.grid(row=i, column=0, sticky="ew", pady=2)
            row.grid_columnconfigure(1, weight=1)
            self._row_frames[code] = row

            var = self._option_vars[code]
            checkbox = ctk.CTkCheckBox(
                row,
                text="",
                width=24,
                variable=var,
                command=lambda c=code: self._on_checkbox(c),
            )
            if code is DeidMethodCode.BASIC:
                checkbox.configure(state="disabled")
            checkbox.grid(row=0, column=0, sticky="nw", padx=(0, 6), pady=2)

            label = ctk.CTkLabel(
                row,
                text=_(deid_method_meaning(code)),
                anchor="w",
                justify="left",
                wraplength=_LIST_WIDTH - 48,
            )
            label.grid(row=0, column=1, sticky="ew")
            for widget in (row, label):
                widget.bind("<Button-1>", lambda _e, c=code: self._focus_option(c))

        ttk.Separator(body, orient="vertical").grid(row=0, column=1, sticky="ns", padx=(pad // 2, pad))

        help_panel = ctk.CTkFrame(body, fg_color="transparent")
        help_panel.grid(row=0, column=2, sticky="nsew")
        help_panel.grid_columnconfigure(0, weight=1)

        self._help_title = ctk.CTkLabel(
            help_panel,
            text="",
            font=ctk.CTkFont(weight="bold", size=14),
            anchor="w",
            justify="left",
            wraplength=_HELP_WRAP,
        )
        self._help_title.grid(row=0, column=0, sticky="ew")

        self._help_summary = ctk.CTkLabel(
            help_panel,
            text="",
            anchor="nw",
            justify="left",
            wraplength=_HELP_WRAP,
        )
        self._help_summary.grid(row=1, column=0, sticky="ew", pady=(pad // 2, 0))

        self._help_source_row = ctk.CTkFrame(help_panel, fg_color="transparent")
        self._help_source_row.grid(row=2, column=0, sticky="ew", pady=(pad // 2, 0))
        self._help_source_row.grid_columnconfigure(0, weight=1)
        self._help_source = ctk.CTkLabel(
            self._help_source_row,
            text="",
            anchor="nw",
            justify="left",
            wraplength=_HELP_WRAP,
        )
        self._help_source.grid(row=0, column=0, sticky="ew")
        self._help_link_url = ""
        self._help_link_tooltip = ""
        self._help_link = self._link_button(
            self._help_source_row,
            "",
            "",
            width=100,
        )
        self._help_link.configure(command=self._open_help_link)
        self._help_link.grid(row=1, column=0, sticky="w", pady=(4, 0))
        bind_hover_tooltip(self._help_link, lambda: self._help_link_tooltip)
        self._help_source_row.grid_remove()

        self._help_notes = ctk.CTkLabel(
            help_panel,
            text="",
            anchor="nw",
            justify="left",
            wraplength=_HELP_WRAP,
        )
        self._help_notes.grid(row=3, column=0, sticky="ew", pady=(pad // 2, 0))

        self._help_when_heading = ctk.CTkLabel(
            help_panel,
            text=_("When it runs"),
            font=ctk.CTkFont(weight="bold"),
            anchor="w",
        )
        self._help_when_heading.grid(row=4, column=0, sticky="w", pady=(pad, 0))

        self._help_when = ctk.CTkLabel(
            help_panel,
            text="",
            anchor="nw",
            justify="left",
            wraplength=_HELP_WRAP,
        )
        self._help_when.grid(row=5, column=0, sticky="ew", pady=(4, 0))

        footer = ctk.CTkFrame(self._frame, fg_color="transparent")
        footer.grid(row=2, column=0, sticky="ew", padx=pad, pady=(0, pad))
        footer.grid_columnconfigure(1, weight=1)

        presets = ctk.CTkFrame(footer, fg_color="transparent")
        presets.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(presets, text=_("Presets") + ":").pack(side="left", padx=(0, 8))
        basic_btn = ctk.CTkButton(
            presets,
            text=_("Basic"),
            width=90,
            command=lambda: self._apply_preset(BASIC_OPTIONS),
        )
        basic_btn.pack(side="left", padx=(0, 8))
        bind_hover_tooltip(
            basic_btn,
            lambda: _("Basic Application Confidentiality Profile only (required baseline)."),
        )
        retain_btn = ctk.CTkButton(
            presets,
            text=_("Retain"),
            width=100,
            command=lambda: self._apply_preset(RETAIN_OPTIONS),
        )
        retain_btn.pack(side="left")
        bind_hover_tooltip(retain_btn, self._retain_preset_tooltip)

        actions = ctk.CTkFrame(footer, fg_color="transparent")
        actions.grid(row=0, column=2, sticky="e")
        ctk.CTkButton(
            actions,
            text=_("Cancel"),
            width=100,
            command=self._on_cancel,
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            actions,
            text=_("OK"),
            width=100,
            command=self._ok_event,
        ).pack(side="left")

        self.minsize(_LIST_WIDTH + _HELP_WRAP + 6 * pad, _DIALOG_MIN_HEIGHT)

    @staticmethod
    def _retain_preset_tooltip() -> str:
        return _(
            "Basic Profile plus modified dates, patient characteristics, "
            "and safe private tags — a common research-sharing start."
        )

    def _selected(self) -> frozenset[DeidMethodCode]:
        return frozenset({code for code, var in self._option_vars.items() if var.get()} | {DeidMethodCode.BASIC})

    def _set_vars(self, options: frozenset[DeidMethodCode]) -> None:
        self._change_guard = True
        try:
            for code, var in self._option_vars.items():
                var.set(code in options)
        finally:
            self._change_guard = False

    def _apply_preset(self, options: frozenset[DeidMethodCode]) -> None:
        self._set_vars(options)
        self._show_explanation(self._focused)

    def _focus_option(self, code: DeidMethodCode) -> None:
        self._focused = code
        self._show_explanation(code)

    def _show_explanation(self, code: DeidMethodCode) -> None:
        expl = deid_option_explanation(code)
        self._help_title.configure(text=expl.title)
        self._help_summary.configure(text=expl.summary)
        self._help_when.configure(text=expl.when_it_runs)
        if expl.source_line and expl.link_label and expl.link_url:
            self._help_source.configure(text=expl.source_line)
            self._help_link_url = expl.link_url
            self._help_link_tooltip = expl.link_tooltip or expl.link_url
            self._help_link.configure(
                text=expl.link_label,
                width=button_width_for_label(expl.link_label, minimum=100),
            )
            self._help_source_row.grid()
        else:
            self._help_link_url = ""
            self._help_link_tooltip = ""
            self._help_source_row.grid_remove()
        if expl.notes:
            self._help_notes.configure(text=_("Note") + ": " + expl.notes)
            self._help_notes.grid()
        else:
            self._help_notes.configure(text="")
            self._help_notes.grid_remove()

    def _on_checkbox(self, code: DeidMethodCode) -> None:
        if self._change_guard:
            return
        self._focused = code
        self._show_explanation(code)
        var = self._option_vars[code]
        if not var.get():
            return
        if code in {DeidMethodCode.FULL_DATES, DeidMethodCode.MODIFIED_DATES}:
            self._set_vars(apply_date_option_exclusivity(self._selected(), enabled=code))
        if not deid_option_ready(code):
            self._option_vars[code].set(False)
            self._offer_option_download(code)

    def _offer_option_download(self, code: DeidMethodCode) -> None:
        feature = ai_feature_for_deid_option(code)
        if feature is None:
            messagebox.showinfo(
                _("De-identification Options"),
                _("This option is not available yet."),
                parent=self,
            )
            return
        groups = [g for g in groups_for(feature) if g.needs_download()]
        if not groups:
            messagebox.showinfo(
                _("De-identification Options"),
                _("This option is not ready (models or license missing)."),
                parent=self,
            )
            return
        if not messagebox.askyesno(
            _("De-identification Options"),
            _("Models for this option are not installed. Download now?"),
            parent=self,
        ):
            return
        manager = get_download_manager()
        group = groups[0]

        def _done(event: DownloadCompleteEvent) -> None:
            self.after(0, lambda: self._after_option_download(code, event))

        if not manager.start(group.download_id, group.download, on_complete=_done):
            messagebox.showinfo(
                _("De-identification Options"),
                _("Another download is already in progress."),
                parent=self,
            )

    def _after_option_download(self, code: DeidMethodCode, event: DownloadCompleteEvent) -> None:
        get_download_manager().clear_pending(event.download_id)
        if event.error is None and deid_option_ready(code):
            if code in {DeidMethodCode.FULL_DATES, DeidMethodCode.MODIFIED_DATES}:
                self._set_vars(apply_date_option_exclusivity(self._selected(), enabled=code))
            else:
                self._change_guard = True
                try:
                    self._option_vars[code].set(True)
                finally:
                    self._change_guard = False
            self._show_explanation(code)
        else:
            messagebox.showinfo(
                _("De-identification Options"),
                _("This option is not ready (models or license missing)."),
                parent=self,
            )

    def _enter_keypress(self, event) -> None:
        self._ok_event()

    def _ok_event(self, event=None) -> None:
        self._user_input = self._selected()
        teardown_ctk_toplevel(self, parent=self.master)

    def _escape_keypress(self, event) -> None:
        self._on_cancel()

    def _on_cancel(self) -> None:
        teardown_ctk_toplevel(self, parent=self.master)

    def get_input(self) -> frozenset[DeidMethodCode] | None:
        """
        Block until the dialog closes.

        Returns:
            Selected options including Basic, or None if cancelled.
        """
        self.focus()
        self.master.wait_window(self)
        return self._user_input
