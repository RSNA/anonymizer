"""Algorithm selection dialog for PHI Index AI batch processing."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import customtkinter as ctk

from anonymizer.controller.ai.remove_pixel_phi import (
    pixel_phi_removal_mode_from_menu_label,
    pixel_phi_removal_mode_menu_values,
)
from anonymizer.controller.ai.tseg.runtime_status import (
    ai_feature_description_face_blur,
    ai_feature_description_harmonize,
    ai_feature_description_remove_pixel_phi,
    ai_feature_title_face_blur,
    ai_feature_title_harmonize,
    ai_feature_title_remove_pixel_phi,
    face_blur_allowed,
    harmonize_allowed,
    pixel_phi_allowed,
)
from anonymizer.controller.ai_batch_process import (
    AiBatchAlgorithm,
    AiBatchProcessOptions,
    normalize_selected_algorithms,
)
from anonymizer.utils.translate import _
from anonymizer.view.ai.blur_face_results import (
    face_blur_mode_from_menu_label,
    face_blur_mode_menu_values,
)
from anonymizer.view.ai.modality_whitelist_preview_dialog import show_modality_whitelist_preview_dialog
from anonymizer.view.common.app_window import AppToplevel
from anonymizer.view.common.ctk_safe import teardown_ctk_toplevel


@dataclass(frozen=True)
class AiBatchProcessOptionsResult:
    confirmed: bool
    options: AiBatchProcessOptions | None = None


class AiBatchProcessOptionsDialog(AppToplevel):
    PAD = 10
    SECTION_PAD = 8
    SECTION_GAP = 10
    BUTTON_WIDTH = 100
    BUTTON_TOP_PAD = 20
    INTRO_WRAP = 480

    _ALGORITHM_ROWS: tuple[tuple[AiBatchAlgorithm, str, str, callable], ...] = (
        (
            AiBatchAlgorithm.REMOVE_PIXEL_PHI,
            ai_feature_title_remove_pixel_phi(),
            ai_feature_description_remove_pixel_phi(),
            pixel_phi_allowed,
        ),
        (
            AiBatchAlgorithm.HARMONIZE,
            ai_feature_title_harmonize(),
            ai_feature_description_harmonize(),
            harmonize_allowed,
        ),
        (
            AiBatchAlgorithm.FACE_BLUR,
            ai_feature_title_face_blur(),
            ai_feature_description_face_blur(),
            face_blur_allowed,
        ),
    )

    def __init__(
        self,
        parent,
        *,
        project_dir: Path,
        images_dir: Path,
        studies: Sequence[tuple[str, str]],
    ) -> None:
        super().__init__(master=parent)
        self._project_dir = project_dir
        self._images_dir = images_dir
        self._studies = list(studies)
        self._result = AiBatchProcessOptionsResult(confirmed=False)
        self._vars: dict[AiBatchAlgorithm, tk.IntVar] = {}
        self._available: list[AiBatchAlgorithm] = []
        self._section_bodies: dict[AiBatchAlgorithm, ctk.CTkFrame] = {}

        self.title(_("AI Batch Process"))
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.bind("<Return>", self._enter_keypress)
        self.bind("<Escape>", self._escape_keypress)

        self._create_widgets()
        self.wait_visibility()
        self.grab_set()
        self._validate_selection()

    def _create_algorithm_section(self, parent: ctk.CTkFrame, row: int) -> ctk.CTkFrame:
        section = ctk.CTkFrame(parent, border_width=1, corner_radius=8)
        section.grid(
            row=row,
            column=0,
            columnspan=2,
            padx=self.PAD,
            pady=(0, self.SECTION_GAP),
            sticky="ew",
        )
        section.grid_columnconfigure(0, weight=1)
        return section

    def _build_pixel_phi_options(self, parent: ctk.CTkFrame, pad: int) -> None:
        self._pixel_phi_mode_var = tk.StringVar(value=pixel_phi_removal_mode_menu_values()[0])
        mode_frame = ctk.CTkFrame(parent, fg_color="transparent")
        mode_frame.grid(row=0, column=0, pady=(self.SECTION_PAD, 0), sticky="w")
        mode_row = ctk.CTkFrame(mode_frame, fg_color="transparent")
        mode_row.pack(anchor="w")
        ctk.CTkLabel(mode_row, text=_("Removal method") + ":").pack(side="left", padx=(0, pad))
        self._pixel_phi_mode_menu = ctk.CTkOptionMenu(
            mode_row,
            variable=self._pixel_phi_mode_var,
            values=list(pixel_phi_removal_mode_menu_values()),
            dynamic_resizing=False,
        )
        self._pixel_phi_mode_menu.pack(side="left")
        ctk.CTkLabel(
            mode_frame,
            text=_("Black out is recommended for de-identification, but can influence ML training."),
            anchor="w",
            justify="left",
            wraplength=self.INTRO_WRAP - pad * 4,
            text_color="gray60",
        ).pack(anchor="w", pady=(4, 0))

        self._use_modality_whitelist_var = tk.IntVar(value=1)
        whitelist_frame = ctk.CTkFrame(parent, fg_color="transparent")
        whitelist_frame.grid(row=1, column=0, pady=(self.SECTION_PAD, 0), sticky="w")
        controls_row = ctk.CTkFrame(whitelist_frame, fg_color="transparent")
        controls_row.pack(anchor="w")
        self._use_modality_whitelist_checkbox = ctk.CTkCheckBox(
            controls_row,
            text=_("Use modality whitelist"),
            variable=self._use_modality_whitelist_var,
            command=self._update_pixel_phi_whitelist_controls,
        )
        self._use_modality_whitelist_checkbox.pack(side="left")
        self._view_whitelist_button = ctk.CTkButton(
            controls_row,
            text=_("View whitelist") + "…",
            command=self._view_whitelist_button_clicked,
        )
        self._view_whitelist_button.pack(side="left", padx=(pad, 0))
        ctk.CTkLabel(
            whitelist_frame,
            text=_(
                "Whitelist terms combine packaged defaults with project overrides saved in Series View."
            ),
            anchor="w",
            justify="left",
            wraplength=self.INTRO_WRAP - pad * 4,
            text_color="gray60",
        ).pack(anchor="w", pady=(4, 0))
        self._pixel_phi_whitelist_disabled_label = ctk.CTkLabel(
            whitelist_frame,
            text=_("All detected OCR text will be removed when the whitelist is disabled."),
            anchor="w",
            justify="left",
            wraplength=self.INTRO_WRAP - pad * 4,
            text_color="gray60",
        )

    def _build_face_blur_options(self, parent: ctk.CTkFrame, pad: int) -> None:
        self._blur_mode_var = tk.StringVar(value=face_blur_mode_menu_values()[0])
        mode_frame = ctk.CTkFrame(parent, fg_color="transparent")
        mode_frame.grid(row=0, column=0, pady=(self.SECTION_PAD, 0), sticky="w")
        mode_row = ctk.CTkFrame(mode_frame, fg_color="transparent")
        mode_row.pack(anchor="w")
        ctk.CTkLabel(mode_row, text=_("Face blur mode") + ":").pack(side="left", padx=(0, pad))
        self._blur_mode_menu = ctk.CTkOptionMenu(
            mode_row,
            variable=self._blur_mode_var,
            values=list(face_blur_mode_menu_values()),
            dynamic_resizing=False,
        )
        self._blur_mode_menu.pack(side="left")

    def _create_widgets(self) -> None:
        pad = self.PAD
        section_pad = self.SECTION_PAD

        self._frame = ctk.CTkFrame(self)
        self._frame.grid(row=0, column=0, padx=pad, pady=pad, sticky="nw")
        self._frame.grid_columnconfigure(0, weight=1)

        row = 0

        ctk.CTkLabel(
            self._frame,
            text=_("Select AI algorithms to run on the selected studies."),
            anchor="w",
            justify="left",
            wraplength=self.INTRO_WRAP,
        ).grid(row=row, column=0, columnspan=2, padx=pad, pady=(pad, pad + self.SECTION_GAP), sticky="nw")

        row += 1

        for algorithm, label, limitation, allowed_fn in self._ALGORITHM_ROWS:
            if not allowed_fn():
                continue
            self._available.append(algorithm)

            section = self._create_algorithm_section(self._frame, row)
            row += 1

            var = tk.IntVar(value=1)
            self._vars[algorithm] = var
            ctk.CTkCheckBox(
                section,
                text=label,
                variable=var,
                command=self._validate_selection,
            ).grid(row=0, column=0, padx=section_pad, pady=(section_pad, 4), sticky="w")

            body = ctk.CTkFrame(section, fg_color="transparent")
            body.grid(row=1, column=0, padx=section_pad, pady=(0, section_pad), sticky="nw")
            body.grid_columnconfigure(0, weight=1)
            self._section_bodies[algorithm] = body

            ctk.CTkLabel(
                body,
                text=limitation,
                anchor="w",
                justify="left",
                wraplength=self.INTRO_WRAP - pad * 4,
                text_color="gray60",
            ).grid(row=0, column=0, sticky="nw")

            if algorithm is AiBatchAlgorithm.REMOVE_PIXEL_PHI:
                options_parent = ctk.CTkFrame(body, fg_color="transparent")
                options_parent.grid(row=1, column=0, sticky="nw")
                self._build_pixel_phi_options(options_parent, pad)
            elif algorithm is AiBatchAlgorithm.FACE_BLUR:
                options_parent = ctk.CTkFrame(body, fg_color="transparent")
                options_parent.grid(row=1, column=0, sticky="nw")
                self._build_face_blur_options(options_parent, pad)

        button_frame = ctk.CTkFrame(self._frame, fg_color="transparent")
        button_frame.grid(
            row=row,
            column=0,
            columnspan=2,
            padx=pad,
            pady=(self.BUTTON_TOP_PAD, pad),
            sticky="e",
        )

        self._cancel_button = ctk.CTkButton(
            button_frame,
            width=self.BUTTON_WIDTH,
            text=_("Cancel"),
            command=self._on_cancel,
        )
        self._cancel_button.grid(row=0, column=0, padx=(0, pad))

        self._ok_button = ctk.CTkButton(
            button_frame,
            width=self.BUTTON_WIDTH,
            text=_("OK"),
            command=self._on_ok,
        )
        self._ok_button.grid(row=0, column=1)

        if AiBatchAlgorithm.FACE_BLUR in self._vars:
            self._vars[AiBatchAlgorithm.FACE_BLUR].trace_add("write", self._update_option_visibility)
        if AiBatchAlgorithm.REMOVE_PIXEL_PHI in self._vars:
            self._vars[AiBatchAlgorithm.REMOVE_PIXEL_PHI].trace_add("write", self._update_option_visibility)
            self._use_modality_whitelist_var.trace_add("write", self._update_pixel_phi_whitelist_controls)
        if AiBatchAlgorithm.HARMONIZE in self._vars:
            self._vars[AiBatchAlgorithm.HARMONIZE].trace_add("write", self._update_option_visibility)
        self._update_option_visibility()

    def _set_section_body_visible(self, algorithm: AiBatchAlgorithm, *, visible: bool) -> None:
        body = self._section_bodies.get(algorithm)
        if body is None:
            return
        if visible:
            body.grid()
        else:
            body.grid_remove()

    def _update_option_visibility(self, *_args) -> None:
        for algorithm, var in self._vars.items():
            self._set_section_body_visible(algorithm, visible=var.get() == 1)
        self._update_pixel_phi_whitelist_controls()

    def _update_pixel_phi_whitelist_controls(self, *_args) -> None:
        pixel_phi_selected = (
            AiBatchAlgorithm.REMOVE_PIXEL_PHI in self._vars
            and self._vars[AiBatchAlgorithm.REMOVE_PIXEL_PHI].get() == 1
        )
        if not pixel_phi_selected or not hasattr(self, "_view_whitelist_button"):
            return
        use_whitelist = self._use_modality_whitelist_var.get() == 1
        self._view_whitelist_button.configure(state="normal" if use_whitelist else "disabled")
        if use_whitelist:
            self._pixel_phi_whitelist_disabled_label.grid_remove()
        else:
            self._pixel_phi_whitelist_disabled_label.pack(anchor="w", pady=(4, 0))

    def _view_whitelist_button_clicked(self) -> None:
        show_modality_whitelist_preview_dialog(
            self,
            project_dir=self._project_dir,
            images_dir=self._images_dir,
            studies=self._studies,
        )

    def _selected_algorithms(self) -> tuple[AiBatchAlgorithm, ...]:
        selected = [algo for algo, var in self._vars.items() if var.get() == 1]
        return normalize_selected_algorithms(selected)

    def _validate_selection(self) -> None:
        if hasattr(self, "_ok_button"):
            self._ok_button.configure(state="normal" if self._selected_algorithms() else "disabled")
        self._update_option_visibility()

    def _enter_keypress(self, _event) -> None:
        if self._selected_algorithms():
            self._on_ok()

    def _on_ok(self) -> None:
        algorithms = self._selected_algorithms()
        if not algorithms:
            return
        blur_mode = face_blur_mode_from_menu_label(self._blur_mode_var.get())
        pixel_phi_removal_mode = pixel_phi_removal_mode_from_menu_label(self._pixel_phi_mode_var.get())
        self._result = AiBatchProcessOptionsResult(
            confirmed=True,
            options=AiBatchProcessOptions(
                algorithms=algorithms,
                blur_mode=blur_mode,
                pixel_phi_removal_mode=pixel_phi_removal_mode,
                use_modality_whitelist=self._use_modality_whitelist_var.get() == 1,
            ),
        )
        self._close()

    def _escape_keypress(self, _event) -> None:
        self._on_cancel()

    def _on_cancel(self) -> None:
        self._result = AiBatchProcessOptionsResult(confirmed=False)
        self._close()

    def _close(self) -> None:
        parent = self.master
        teardown_ctk_toplevel(self, parent=parent)

    def get_input(self) -> AiBatchProcessOptionsResult:
        self.focus()
        self.master.wait_window(self)
        return self._result


def show_ai_batch_process_options_dialog(
    parent,
    *,
    project_dir: Path,
    images_dir: Path,
    studies: Sequence[tuple[str, str]],
) -> AiBatchProcessOptionsResult:
    if not any(allowed() for _, _, _, allowed in AiBatchProcessOptionsDialog._ALGORITHM_ROWS):
        return AiBatchProcessOptionsResult(confirmed=False)
    dialog = AiBatchProcessOptionsDialog(
        parent,
        project_dir=project_dir,
        images_dir=images_dir,
        studies=studies,
    )
    return dialog.get_input()
