"""Read-only preview of effective modality whitelists for AI batch OCR."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Sequence
from pathlib import Path

import customtkinter as ctk

from anonymizer.controller.ai.remove_pixel_phi import OcrWhitelistMatchSettings, describe_match_settings
from anonymizer.controller.ai_batch_process import (
    effective_modality_whitelist_match_settings,
    effective_modality_whitelists,
    format_modality_whitelist_heading,
    modalities_in_selected_studies,
)
from anonymizer.utils.translate import _
from anonymizer.view.common.app_window import AppToplevel
from anonymizer.view.common.ctk_safe import teardown_ctk_toplevel


def populate_modality_whitelist_preview_textbox(
    text_box: ctk.CTkTextbox,
    whitelists_by_modality: dict[str, list[str]],
    *,
    no_modalities_message: str,
    no_terms_label: str,
    match_settings_by_modality: dict[str, OcrWhitelistMatchSettings] | None = None,
) -> None:
    """Fill a text box with whitelist preview content and bold modality headings."""
    inner = text_box._textbox
    base_font = inner.cget("font")
    if isinstance(base_font, str):
        family = base_font
        size = 13
    else:
        family = base_font.actual("family")
        size = int(float(base_font.actual("size")))
    inner.tag_configure("modality_heading", font=(family, size, "bold"))

    text_box.configure(state="normal")
    inner.delete("1.0", "end")

    if not whitelists_by_modality:
        inner.insert("end", no_modalities_message)
        text_box.configure(state="disabled")
        return

    for index, modality in enumerate(sorted(whitelists_by_modality)):
        if index > 0:
            inner.insert("end", "\n\n")
        terms = whitelists_by_modality[modality]
        inner.insert("end", format_modality_whitelist_heading(modality, len(terms)) + "\n", "modality_heading")
        if match_settings_by_modality and modality in match_settings_by_modality:
            inner.insert(
                "end",
                f"  {_('Match strictness')}: {describe_match_settings(match_settings_by_modality[modality])}\n",
            )
        if terms:
            inner.insert("end", "\n".join(f"  {term}" for term in terms))
        else:
            inner.insert("end", f"  {no_terms_label}")

    text_box.configure(state="disabled")


class ModalityWhitelistPreviewDialog(AppToplevel):
    PAD = 10
    TEXT_HEIGHT = 320
    TEXT_WIDTH = 480

    def __init__(
        self,
        parent: tk.Misc,
        *,
        project_dir: Path | None,
        images_dir: Path,
        studies: Sequence[tuple[str, str]],
    ) -> None:
        super().__init__(master=parent)
        self.title(_("Modality Whitelist"))
        self.resizable(True, True)
        self.minsize(400, 280)

        modalities = modalities_in_selected_studies(images_dir, studies)
        whitelists = effective_modality_whitelists(project_dir, modalities)
        match_settings = effective_modality_whitelist_match_settings(project_dir, modalities)
        no_modalities_message = _(
            "No modalities found in the selected studies."
            + "\n\n"
            + "Verify your study selection includes series with readable DICOM files."
        )
        no_terms_label = _("(no whitelist terms)")

        frame = ctk.CTkFrame(self)
        frame.pack(fill="both", expand=True, padx=self.PAD, pady=self.PAD)
        frame.grid_rowconfigure(1, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            frame,
            text=_(
                "Effective OCR whitelist terms and match strictness for selected studies "
                + "(project settings when saved, otherwise modality defaults)."
            ),
            anchor="w",
            justify="left",
            wraplength=self.TEXT_WIDTH,
        ).grid(row=0, column=0, sticky="ew", pady=(0, self.PAD))

        text_box = ctk.CTkTextbox(frame, width=self.TEXT_WIDTH, height=self.TEXT_HEIGHT, wrap="word")
        text_box.grid(row=1, column=0, sticky="nsew")
        populate_modality_whitelist_preview_textbox(
            text_box,
            whitelists,
            no_modalities_message=no_modalities_message,
            no_terms_label=no_terms_label,
            match_settings_by_modality=match_settings,
        )

        ctk.CTkLabel(
            frame,
            text=_("Read-only. Edit whitelist terms in Series View before running batch."),
            anchor="w",
            justify="left",
            wraplength=self.TEXT_WIDTH,
            text_color="gray60",
        ).grid(row=2, column=0, sticky="ew", pady=(self.PAD, 0))

        button_frame = ctk.CTkFrame(frame, fg_color="transparent")
        button_frame.grid(row=3, column=0, sticky="e", pady=(self.PAD, 0))
        ctk.CTkButton(button_frame, text=_("Close"), width=100, command=self._close).grid(row=0, column=0)

        self.protocol("WM_DELETE_WINDOW", self._close)
        self.bind("<Escape>", lambda _event: self._close())

        self.wait_visibility()
        self.lift()
        self.grab_set()

    def _close(self) -> None:
        teardown_ctk_toplevel(self, parent=self.master)

    def get_input(self) -> None:
        self.focus()
        self.master.wait_window(self)


def show_modality_whitelist_preview_dialog(
    parent: tk.Misc,
    *,
    project_dir: Path | None,
    images_dir: Path,
    studies: Sequence[tuple[str, str]],
) -> None:
    dialog = ModalityWhitelistPreviewDialog(
        parent,
        project_dir=project_dir,
        images_dir=images_dir,
        studies=studies,
    )
    dialog.get_input()
