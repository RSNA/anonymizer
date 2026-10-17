"""Algorithm selection dialog for PHI Index AI batch processing."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import customtkinter as ctk

from anonymizer.controller.ai.batch_process import (
    AiBatchAlgorithm,
    AiBatchProcessOptions,
    collect_exclude_areas_by_modality,
    modalities_in_selected_studies,
    normalize_selected_algorithms,
)
from anonymizer.controller.ai.blur_face import FaceBlurMode
from anonymizer.controller.ai.embedded_phi.pixel.detect_text import (
    PixelPhiRemovalMode,
    normalize_pixel_phi_removal_mode,
    pixel_phi_removal_mode_menu_labels,
    pixel_phi_removal_mode_option_label,
)
from anonymizer.controller.ai.feature_availability import (
    brain_structures_allowed,
    embedded_phi_allowed,
    face_blur_allowed,
    harmonize_allowed,
)
from anonymizer.controller.jobs.runner import (
    OcrRemoveMode,
    normalize_ocr_remove_mode,
    ocr_remove_mode_display_label,
    ocr_remove_mode_menu_labels,
    ocr_remove_mode_tooltip,
)
from anonymizer.utils.translate import _
from anonymizer.view.ai.blur_face_results import face_blur_mode_from_menu_label, face_blur_mode_menu_values
from anonymizer.view.ai.features.catalog import AiFeatureId, feature_capability_description, feature_title
from anonymizer.view.ai.features.look import (
    FEATURE_ACTION_BUTTON_WIDTH,
    FEATURE_DETAIL_PADX,
    FEATURE_DETAIL_WRAP,
    FEATURE_DIALOG_PAD,
    FEATURE_INTRO_WRAP,
    feature_title_control_kwargs,
)
from anonymizer.view.ai.modality_whitelist_preview_dialog import show_modality_whitelist_preview_dialog
from anonymizer.view.common.app_window import (
    AppToplevel,
    fit_toplevel_to_content,
    place_toplevel_centered_on_parent,
    present_toplevel_centered_on_parent,
)
from anonymizer.view.common.ctk_safe import teardown_ctk_toplevel
from anonymizer.view.common.tooltip import bind_hover_tooltip
from anonymizer.view.common.ux_fields import option_menu_width_for_labels
from anonymizer.view.project.description_mapping_store import (
    load_series_overrides,
    load_study_loinc_overrides,
)


@dataclass(frozen=True)
class AiBatchProcessOptionsResult:
    confirmed: bool
    options: AiBatchProcessOptions | None = None


class AiBatchProcessOptionsDialog(AppToplevel):
    PAD = FEATURE_DIALOG_PAD
    SECTION_PAD = 8
    FEATURE_GAP = (0, 14)
    BUTTON_WIDTH = FEATURE_ACTION_BUTTON_WIDTH
    BUTTON_TOP_PAD = 20
    INTRO_WRAP = FEATURE_INTRO_WRAP

    _ALGORITHM_ROWS: tuple[tuple[AiBatchAlgorithm, str, str, Callable[[], bool]], ...] = (
        (
            AiBatchAlgorithm.REMOVE_PIXEL_PHI,
            feature_title(AiFeatureId.EMBEDDED_PHI.value),
            feature_capability_description(AiFeatureId.EMBEDDED_PHI.value),
            embedded_phi_allowed,
        ),
        (
            AiBatchAlgorithm.HARMONIZE,
            feature_title(AiFeatureId.HARMONIZE.value),
            feature_capability_description(AiFeatureId.HARMONIZE.value),
            harmonize_allowed,
        ),
        (
            AiBatchAlgorithm.FACE_BLUR,
            feature_title(AiFeatureId.FACE_BLUR.value),
            feature_capability_description(AiFeatureId.FACE_BLUR.value),
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
        # Build while withdrawn so the first paint is already centered (no +0+0 flash).
        self.withdraw()
        self._parent = parent
        self._project_dir = project_dir
        self._images_dir = images_dir
        self._studies = list(studies)
        self._result = AiBatchProcessOptionsResult(confirmed=False)
        self._vars: dict[AiBatchAlgorithm, tk.IntVar] = {}
        self._available: list[AiBatchAlgorithm] = []
        self._section_bodies: dict[AiBatchAlgorithm, ctk.CTkFrame] = {}

        self.title(_("AI Batch Process"))
        self.resizable(False, False)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.bind("<Return>", self._enter_keypress)
        self.bind("<Escape>", self._escape_keypress)

        self._create_widgets()
        self._validate_selection()
        width, height = fit_toplevel_to_content(
            self,
            min_width=FEATURE_INTRO_WRAP + FEATURE_DIALOG_PAD * 4,
            pad=FEATURE_DIALOG_PAD * 4,
        )
        present_toplevel_centered_on_parent(self, parent, width=width, height=height)
        self.grab_set()

    def _detail_label(self, parent: ctk.CTkFrame, text: str, *, wrap: int | None = None) -> ctk.CTkLabel:
        return ctk.CTkLabel(
            parent,
            text=text,
            anchor="w",
            justify="left",
            wraplength=wrap if wrap is not None else FEATURE_DETAIL_WRAP,
        )

    def _build_pixel_phi_options(self, parent: ctk.CTkFrame) -> None:
        pad = self.PAD
        removal_labels = list(pixel_phi_removal_mode_menu_labels())
        self._pixel_phi_mode_var = tk.StringVar(
            value=pixel_phi_removal_mode_option_label(PixelPhiRemovalMode.BLACKOUT)
        )
        mode_frame = ctk.CTkFrame(parent, fg_color="transparent")
        mode_frame.grid(row=0, column=0, pady=(self.SECTION_PAD, 0), sticky="w")
        mode_row = ctk.CTkFrame(mode_frame, fg_color="transparent")
        mode_row.pack(anchor="w")
        ctk.CTkLabel(mode_row, text=_("Removal method") + ":").pack(side="left", padx=(0, pad))
        self._pixel_phi_mode_menu = ctk.CTkOptionMenu(
            mode_row,
            variable=self._pixel_phi_mode_var,
            values=removal_labels,
            dynamic_resizing=False,
            width=option_menu_width_for_labels(removal_labels),
        )
        self._pixel_phi_mode_menu.pack(side="left")
        self._detail_label(
            mode_frame,
            _("Black out is recommended for de-identification, but can influence ML training."),
        ).pack(anchor="w", pady=(4, 0))

        remove_labels = list(ocr_remove_mode_menu_labels())
        self._ocr_remove_mode_var = tk.StringVar(
            value=ocr_remove_mode_display_label(OcrRemoveMode.NON_WHITELISTED)
        )
        whitelist_frame = ctk.CTkFrame(parent, fg_color="transparent")
        whitelist_frame.grid(row=1, column=0, pady=(self.SECTION_PAD, 0), sticky="w")
        controls_row = ctk.CTkFrame(whitelist_frame, fg_color="transparent")
        controls_row.pack(anchor="w")
        ctk.CTkLabel(controls_row, text=_("Remove") + ":").pack(side="left", padx=(0, pad))
        self._ocr_remove_mode_menu = ctk.CTkOptionMenu(
            controls_row,
            variable=self._ocr_remove_mode_var,
            values=remove_labels,
            command=self._on_ocr_remove_mode_changed,
            dynamic_resizing=False,
            width=option_menu_width_for_labels(remove_labels),
        )
        self._ocr_remove_mode_menu.pack(side="left")
        bind_hover_tooltip(self._ocr_remove_mode_menu, lambda: ocr_remove_mode_tooltip(self._selected_ocr_remove_mode()))
        self._view_whitelist_button = ctk.CTkButton(
            controls_row,
            text=_("View whitelist"),
            command=self._view_whitelist_button_clicked,
        )
        self._view_whitelist_button.pack(side="left", padx=(pad, 0))
        self._pixel_phi_whitelist_disabled_label = self._detail_label(
            whitelist_frame,
            _("All detected OCR text will be removed; whitelist is ignored."),
        )
        self._pixel_phi_ner_hint_label = self._detail_label(
            whitelist_frame,
            ocr_remove_mode_tooltip(OcrRemoveMode.PHI_ONLY),
        )

        self._ocr_use_exclude_areas_var = tk.IntVar(value=0)
        modalities = modalities_in_selected_studies(self._images_dir, self._studies)
        exclude_count = sum(
            len(rects) for rects in collect_exclude_areas_by_modality(self._project_dir, modalities).values()
        )
        if exclude_count:
            exclude_frame = ctk.CTkFrame(parent, fg_color="transparent")
            exclude_frame.grid(row=2, column=0, pady=(self.SECTION_PAD, 0), sticky="w")
            exclude_row = ctk.CTkFrame(exclude_frame, fg_color="transparent")
            exclude_row.pack(anchor="w")
            self._ocr_use_exclude_areas_checkbox = ctk.CTkCheckBox(
                exclude_row,
                text=_("Enable Exclude Areas"),
                variable=self._ocr_use_exclude_areas_var,
                **feature_title_control_kwargs(),
            )
            self._ocr_use_exclude_areas_checkbox.pack(side="left")
            self._detail_label(exclude_row, _("{} defined").format(exclude_count)).pack(
                side="left", padx=(8, 0)
            )
            self._detail_label(
                exclude_frame,
                _("Uses exclude areas saved in Series View."),
            ).pack(anchor="w", pady=(4, 0))

    def _build_face_blur_options(self, parent: ctk.CTkFrame) -> None:
        self._blur_mode_var = tk.StringVar(value=face_blur_mode_menu_values()[0])
        mode_frame = ctk.CTkFrame(parent, fg_color="transparent")
        mode_frame.grid(row=0, column=0, pady=(self.SECTION_PAD, 0), sticky="w")
        mode_row = ctk.CTkFrame(mode_frame, fg_color="transparent")
        mode_row.pack(anchor="w")
        ctk.CTkLabel(mode_row, text=_("Face blur mode") + ":").pack(side="left", padx=(0, self.PAD))
        blur_labels = list(face_blur_mode_menu_values())
        self._blur_mode_menu = ctk.CTkOptionMenu(
            mode_row,
            variable=self._blur_mode_var,
            values=blur_labels,
            dynamic_resizing=False,
            width=option_menu_width_for_labels(blur_labels),
        )
        self._blur_mode_menu.pack(side="left")

    def _build_harmonize_options(self, parent: ctk.CTkFrame) -> None:
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=0, column=0, pady=(self.SECTION_PAD, 0), sticky="w")

        offer_brain = brain_structures_allowed()
        self._include_brain_structures_var = tk.IntVar(value=1 if offer_brain else 0)
        self._include_brain_structures_checkbox = ctk.CTkCheckBox(
            frame,
            text=_("Brain structures (CT Head when present)"),
            variable=self._include_brain_structures_var,
            state="normal" if offer_brain else "disabled",
            **feature_title_control_kwargs(),
        )
        self._include_brain_structures_checkbox.pack(anchor="w")
        self._detail_label(
            frame,
            feature_capability_description(AiFeatureId.BRAIN_STRUCTURES.value)
            if offer_brain
            else _("Download Brain structures models in AI Features to use this option."),
        ).pack(anchor="w", pady=(4, 0))

        self._prefer_description_mappings_var = tk.IntVar(value=1)
        ctk.CTkCheckBox(
            frame,
            text=_("Prefer description mappings (skip AI when matched)"),
            variable=self._prefer_description_mappings_var,
            **feature_title_control_kwargs(),
        ).pack(anchor="w", pady=(8, 0))
        self._detail_label(
            frame,
            _("When a saved original→harmonized mapping matches a series, apply it and skip the anatomy model."),
        ).pack(anchor="w", pady=(4, 0))

    def _create_widgets(self) -> None:
        pad = self.PAD

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._frame = ctk.CTkFrame(self)
        self._frame.grid(row=0, column=0, padx=pad, pady=pad, sticky="nsew")
        self._frame.grid_columnconfigure(0, weight=1)

        self._intro_label = ctk.CTkLabel(
            self._frame,
            text=_("Select AI algorithms to run on the selected studies."),
            anchor="w",
            justify="left",
            wraplength=self.INTRO_WRAP,
        )
        self._intro_label.grid(row=0, column=0, padx=pad, pady=(pad, pad), sticky="nw")

        self._body = ctk.CTkFrame(self._frame, fg_color="transparent")
        self._body.grid(row=1, column=0, sticky="ew", padx=pad)
        self._body.grid_columnconfigure(0, weight=1)

        row = 0
        for algorithm, label, limitation, allowed_fn in self._ALGORITHM_ROWS:
            if not allowed_fn():
                continue
            self._available.append(algorithm)

            section = ctk.CTkFrame(self._body, fg_color="transparent")
            section.grid(row=row, column=0, pady=self.FEATURE_GAP, sticky="ew")
            section.grid_columnconfigure(0, weight=1)
            row += 1

            var = tk.IntVar(value=0)
            self._vars[algorithm] = var
            ctk.CTkCheckBox(
                section,
                text=label,
                variable=var,
                command=self._validate_selection,
                **feature_title_control_kwargs(),
            ).grid(row=0, column=0, sticky="w")

            body = ctk.CTkFrame(section, fg_color="transparent")
            body.grid(row=1, column=0, padx=FEATURE_DETAIL_PADX, pady=(2, 0), sticky="nw")
            body.grid_columnconfigure(0, weight=1)
            self._section_bodies[algorithm] = body

            self._detail_label(body, limitation, wrap=FEATURE_INTRO_WRAP).grid(row=0, column=0, sticky="nw")

            options_parent = ctk.CTkFrame(body, fg_color="transparent")
            options_parent.grid(row=1, column=0, sticky="nw")
            options_parent.grid_columnconfigure(0, weight=1)
            if algorithm is AiBatchAlgorithm.REMOVE_PIXEL_PHI:
                self._build_pixel_phi_options(options_parent)
            elif algorithm is AiBatchAlgorithm.HARMONIZE:
                self._build_harmonize_options(options_parent)
            elif algorithm is AiBatchAlgorithm.FACE_BLUR:
                self._build_face_blur_options(options_parent)

        self._button_frame = ctk.CTkFrame(self._frame, fg_color="transparent")
        self._button_frame.grid(
            row=2,
            column=0,
            padx=pad,
            pady=(self.BUTTON_TOP_PAD, pad),
            sticky="e",
        )

        self._cancel_button = ctk.CTkButton(
            self._button_frame,
            width=self.BUTTON_WIDTH,
            text=_("Cancel"),
            command=self._on_cancel,
        )
        self._cancel_button.grid(row=0, column=0, padx=(0, pad))

        self._ok_button = ctk.CTkButton(
            self._button_frame,
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
        self._recenter_if_mapped()

    def _recenter_if_mapped(self) -> None:
        try:
            if not self.winfo_viewable():
                return
        except tk.TclError:
            return
        width, height = fit_toplevel_to_content(
            self,
            min_width=FEATURE_INTRO_WRAP + FEATURE_DIALOG_PAD * 4,
            pad=FEATURE_DIALOG_PAD * 4,
        )
        place_toplevel_centered_on_parent(self, self._parent, width=width, height=height)

    def _selected_ocr_remove_mode(self) -> OcrRemoveMode:
        if not hasattr(self, "_ocr_remove_mode_var"):
            return OcrRemoveMode.NON_WHITELISTED
        return normalize_ocr_remove_mode(self._ocr_remove_mode_var.get())

    def _on_ocr_remove_mode_changed(self, _choice: str | None = None) -> None:
        self._update_pixel_phi_whitelist_controls()

    def _update_pixel_phi_whitelist_controls(self, *_args) -> None:
        pixel_phi_selected = (
            AiBatchAlgorithm.REMOVE_PIXEL_PHI in self._vars
            and self._vars[AiBatchAlgorithm.REMOVE_PIXEL_PHI].get() == 1
        )
        if not pixel_phi_selected or not hasattr(self, "_view_whitelist_button"):
            return
        mode = self._selected_ocr_remove_mode()
        self._view_whitelist_button.configure(
            state="normal" if mode is OcrRemoveMode.NON_WHITELISTED else "disabled"
        )
        if hasattr(self, "_pixel_phi_whitelist_disabled_label"):
            if mode is OcrRemoveMode.ALL_TEXT:
                self._pixel_phi_whitelist_disabled_label.pack(anchor="w", pady=(4, 0))
            else:
                self._pixel_phi_whitelist_disabled_label.pack_forget()
        if hasattr(self, "_pixel_phi_ner_hint_label"):
            if mode is OcrRemoveMode.PHI_ONLY:
                self._pixel_phi_ner_hint_label.pack(anchor="w", pady=(4, 0))
            else:
                self._pixel_phi_ner_hint_label.pack_forget()

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
        blur_mode = FaceBlurMode.GAUSSIAN
        if hasattr(self, "_blur_mode_var"):
            blur_mode = face_blur_mode_from_menu_label(self._blur_mode_var.get())
        pixel_phi_removal_mode = PixelPhiRemovalMode.BLACKOUT
        if hasattr(self, "_pixel_phi_mode_var"):
            pixel_phi_removal_mode = normalize_pixel_phi_removal_mode(self._pixel_phi_mode_var.get())
        ocr_remove_mode = self._selected_ocr_remove_mode()
        ocr_use_exclude_areas = bool(
            hasattr(self, "_ocr_use_exclude_areas_var") and self._ocr_use_exclude_areas_var.get() == 1
        )
        include_brain = bool(
            hasattr(self, "_include_brain_structures_var") and self._include_brain_structures_var.get() == 1
        )
        prefer_mappings = bool(
            hasattr(self, "_prefer_description_mappings_var") and self._prefer_description_mappings_var.get() == 1
        )
        mappings_dir = Path(self._project_dir) / "mappings"
        series_overrides = load_series_overrides(mappings_dir) if prefer_mappings else {}
        study_overrides = load_study_loinc_overrides(mappings_dir) if prefer_mappings else {}
        self._result = AiBatchProcessOptionsResult(
            confirmed=True,
            options=AiBatchProcessOptions(
                algorithms=algorithms,
                blur_mode=blur_mode,
                pixel_phi_removal_mode=pixel_phi_removal_mode,
                ocr_remove_mode=ocr_remove_mode,
                ocr_use_exclude_areas=ocr_use_exclude_areas,
                include_brain_structures=include_brain,
                prefer_description_mappings=prefer_mappings,
                series_description_overrides=series_overrides,
                study_loinc_overrides=study_overrides,
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
