"""Algorithm selection dialog for PHI Index AI batch processing."""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass

import customtkinter as ctk

from anonymizer.controller.ai_batch_process import (
    AiBatchAlgorithm,
    AiBatchProcessOptions,
    normalize_selected_algorithms,
)
from anonymizer.controller.remove_pixel_phi import (
    pixel_phi_removal_mode_from_menu_label,
    pixel_phi_removal_mode_menu_values,
)
from anonymizer.controller.tseg.runtime_status import (
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
from anonymizer.utils.translate import _
from anonymizer.view.blur_face_results import (
    face_blur_mode_from_menu_label,
    face_blur_mode_menu_values,
)


@dataclass(frozen=True)
class AiBatchProcessOptionsResult:
    confirmed: bool
    options: AiBatchProcessOptions | None = None


class AiBatchProcessOptionsDialog(tk.Toplevel):
    PAD = 10
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

    def __init__(self, parent) -> None:
        super().__init__(master=parent)
        self._result = AiBatchProcessOptionsResult(confirmed=False)
        self._vars: dict[AiBatchAlgorithm, tk.IntVar] = {}
        self._available: list[AiBatchAlgorithm] = []
        self._hint_frames: dict[AiBatchAlgorithm, ctk.CTkFrame] = {}

        self.title(_("AI Batch Process"))
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.bind("<Return>", self._enter_keypress)
        self.bind("<Escape>", self._escape_keypress)

        self._create_widgets()
        self.wait_visibility()
        self.grab_set()
        self._validate_selection()

    def _create_widgets(self) -> None:
        pad = self.PAD

        self._frame = ctk.CTkFrame(self)
        self._frame.grid(row=0, column=0, padx=pad, pady=pad, sticky="nw")

        row = 0

        ctk.CTkLabel(
            self._frame,
            text=_("Select AI algorithms to run on the selected studies."),
            anchor="w",
            justify="left",
            wraplength=self.INTRO_WRAP,
        ).grid(row=row, column=0, columnspan=2, padx=pad, pady=(pad, pad), sticky="nw")

        row += 1

        self._pixel_phi_mode_frame = ctk.CTkFrame(self._frame, fg_color="transparent")
        self._pixel_phi_mode_var = tk.StringVar(value=pixel_phi_removal_mode_menu_values()[0])
        ctk.CTkLabel(self._pixel_phi_mode_frame, text=_("Removal method") + ":").grid(
            row=0,
            column=0,
            padx=(0, pad),
            sticky="w",
        )
        self._pixel_phi_mode_menu = ctk.CTkOptionMenu(
            self._pixel_phi_mode_frame,
            variable=self._pixel_phi_mode_var,
            values=list(pixel_phi_removal_mode_menu_values()),
            dynamic_resizing=False,
        )
        self._pixel_phi_mode_menu.grid(row=0, column=1, sticky="w")

        ctk.CTkLabel(
            self._pixel_phi_mode_frame,
            text=_("Black out is recommended for de-identification, but can influence ML training."),
            anchor="w",
            justify="left",
            wraplength=self.INTRO_WRAP - pad * 2,
            text_color="gray60",
        ).grid(row=1, column=0, columnspan=2, padx=(0, pad), pady=(4, 0), sticky="nw")

        self._blur_mode_frame = ctk.CTkFrame(self._frame, fg_color="transparent")
        self._blur_mode_var = tk.StringVar(value=face_blur_mode_menu_values()[0])
        ctk.CTkLabel(self._blur_mode_frame, text=_("Face blur mode") + ":").grid(
            row=0,
            column=0,
            padx=(0, pad),
            sticky="w",
        )
        self._blur_mode_menu = ctk.CTkOptionMenu(
            self._blur_mode_frame,
            variable=self._blur_mode_var,
            values=list(face_blur_mode_menu_values()),
            dynamic_resizing=False,
        )
        self._blur_mode_menu.grid(row=0, column=1, sticky="w")

        sub_option_indent = pad * 2

        for algorithm, label, limitation, allowed_fn in self._ALGORITHM_ROWS:
            if not allowed_fn():
                continue
            self._available.append(algorithm)
            var = tk.IntVar(value=1)
            self._vars[algorithm] = var
            checkbox = ctk.CTkCheckBox(
                self._frame,
                text=label,
                variable=var,
                command=self._validate_selection,
            )
            checkbox.grid(row=row, column=0, columnspan=2, padx=pad, pady=(0, 4), sticky="w")
            row += 1

            hint_frame = ctk.CTkFrame(self._frame, fg_color="transparent")
            ctk.CTkLabel(
                hint_frame,
                text=limitation,
                anchor="w",
                justify="left",
                wraplength=self.INTRO_WRAP - sub_option_indent,
                text_color="gray60",
            ).grid(row=0, column=0, sticky="nw")
            hint_frame.grid(
                row=row,
                column=0,
                columnspan=2,
                padx=(sub_option_indent, pad),
                pady=(0, 6),
                sticky="nw",
            )
            self._hint_frames[algorithm] = hint_frame
            row += 1

            if algorithm is AiBatchAlgorithm.REMOVE_PIXEL_PHI:
                self._pixel_phi_mode_frame.grid(
                    row=row,
                    column=0,
                    columnspan=2,
                    padx=(sub_option_indent, pad),
                    pady=(0, pad),
                    sticky="nw",
                )
                row += 1
            elif algorithm is AiBatchAlgorithm.FACE_BLUR:
                self._blur_mode_frame.grid(
                    row=row,
                    column=0,
                    columnspan=2,
                    padx=(sub_option_indent, pad),
                    pady=(0, pad),
                    sticky="nw",
                )
                row += 1

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
        if AiBatchAlgorithm.HARMONIZE in self._vars:
            self._vars[AiBatchAlgorithm.HARMONIZE].trace_add("write", self._update_option_visibility)
        self._update_option_visibility()

    def _update_option_visibility(self, *_args) -> None:
        for algorithm, var in self._vars.items():
            show = var.get() == 1
            hint_frame = self._hint_frames.get(algorithm)
            if hint_frame is not None:
                if show:
                    hint_frame.grid()
                else:
                    hint_frame.grid_remove()
        self._update_blur_mode_visibility()
        self._update_pixel_phi_mode_visibility()

    def _update_blur_mode_visibility(self, *_args) -> None:
        show = AiBatchAlgorithm.FACE_BLUR in self._vars and self._vars[AiBatchAlgorithm.FACE_BLUR].get() == 1
        if show:
            self._blur_mode_frame.grid()
        else:
            self._blur_mode_frame.grid_remove()

    def _update_pixel_phi_mode_visibility(self, *_args) -> None:
        show = (
            AiBatchAlgorithm.REMOVE_PIXEL_PHI in self._vars and self._vars[AiBatchAlgorithm.REMOVE_PIXEL_PHI].get() == 1
        )
        if show:
            self._pixel_phi_mode_frame.grid()
        else:
            self._pixel_phi_mode_frame.grid_remove()

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
            ),
        )
        self._close()

    def _escape_keypress(self, _event) -> None:
        self._on_cancel()

    def _on_cancel(self) -> None:
        self._result = AiBatchProcessOptionsResult(confirmed=False)
        self._close()

    def _close(self) -> None:
        self.grab_release()
        self.destroy()

    def get_input(self) -> AiBatchProcessOptionsResult:
        self.focus()
        self.master.wait_window(self)
        return self._result


def show_ai_batch_process_options_dialog(parent) -> AiBatchProcessOptionsResult:
    if not any(allowed() for _, _, _, allowed in AiBatchProcessOptionsDialog._ALGORITHM_ROWS):
        return AiBatchProcessOptionsResult(confirmed=False)
    dialog = AiBatchProcessOptionsDialog(parent)
    return dialog.get_input()
