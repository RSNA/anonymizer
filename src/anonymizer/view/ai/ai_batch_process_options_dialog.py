"""Algorithm selection dialog for PHI Index AI batch processing."""

import re
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
    modalities_with_whitelist_terms,
    normalize_selected_algorithms,
)
from anonymizer.controller.ai.blur_face import FaceBlurMode
from anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline import PhiMatchMode
from anonymizer.controller.ai.embedded_phi.pixel.remove_pixel_phi import PixelPhiRemovalMode
from anonymizer.controller.ai.embedded_phi.pixel.remove_scope import OcrRemoveMode
from anonymizer.controller.ai.feature_availability import (
    brain_structures_allowed,
    embedded_phi_allowed,
    face_blur_allowed,
    harmonize_allowed,
)
from anonymizer.controller.ai.feature_ids import AiFeatureId
from anonymizer.controller.ai.harmonize.description_mapping_store import (
    load_series_overrides,
    load_study_loinc_overrides,
)
from anonymizer.utils.translate import _
from anonymizer.view.ai.blur_face_results import face_blur_mode_from_menu_label, face_blur_mode_menu_values
from anonymizer.view.ai.features.catalog import feature_capability_description, feature_title
from anonymizer.view.ai.features.look import (
    FEATURE_ACTION_BUTTON_WIDTH,
    FEATURE_DETAIL_PADX,
    FEATURE_DETAIL_WRAP,
    FEATURE_DIALOG_PAD,
    FEATURE_INTRO_WRAP,
    feature_title_control_kwargs,
    theme_label_text_color,
)
from anonymizer.view.ai.modality_whitelist_preview_dialog import show_modality_whitelist_preview_dialog
from anonymizer.view.common.app_window import (
    AppToplevel,
    fit_toplevel_to_content,
    present_toplevel_centered_on_parent,
)
from anonymizer.view.common.ctk_safe import teardown_ctk_toplevel
from anonymizer.view.common.phi_action_labels import replace_mode_labels
from anonymizer.view.common.ux_fields import button_width_for_label, option_menu_width_for_labels
from anonymizer.view.ocr_ui import (
    match_mode_menu_label,
    match_mode_menu_labels,
    normalize_ocr_remove_mode,
    normalize_pixel_phi_removal_mode,
    ocr_remove_mode_display_label,
    ocr_remove_mode_menu_labels,
    ocr_remove_mode_tooltip,
    pixel_phi_removal_mode_menu_labels,
    pixel_phi_removal_mode_option_label,
)

_GEOMETRY_ORIGIN = re.compile(r"([+-]\d+)([+-]\d+)$")


def _toplevel_origin(window: tk.Misc) -> tuple[int, int]:
    """
    Screen origin currently stored in the toplevel geometry string.

    Args:
        window: Mapped toplevel.

    Returns:
        (x, y) from the geometry string. Falls back to root coordinates.
    """
    match = _GEOMETRY_ORIGIN.search(str(window.geometry()))
    if match is not None:
        return int(match.group(1)), int(match.group(2))
    return int(window.winfo_rootx()), int(window.winfo_rooty())


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
        self._option_grids: list[ctk.CTkFrame] = []
        self._detail_labels: list[ctk.CTkLabel] = []

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
        label = ctk.CTkLabel(
            parent,
            text=text,
            anchor="w",
            justify="left",
            wraplength=wrap if wrap is not None else FEATURE_DETAIL_WRAP,
        )
        self._detail_labels.append(label)
        return label

    def _build_pixel_phi_options(self, parent: ctk.CTkFrame) -> None:
        """
        Embedded PHI controls in decision order.

        The description stays full width. Everything under it is one two-column
        grid: labels and the modality list in column 0, controls in column 1.
        Column 0 grows with the longer of those labels so the list does not
        run into the controls.

        Args:
            parent: Frame under the Embedded PHI description.
        """
        parent.grid_columnconfigure(1, weight=1)
        row = 0
        modalities = modalities_in_selected_studies(self._images_dir, self._studies)

        self._match_mode_labels = match_mode_menu_labels()
        match_labels = list(self._match_mode_labels.keys())
        self._phi_match_mode_var = tk.StringVar(value=match_mode_menu_label(PhiMatchMode.STANDARD))
        row = self._option_label(parent, row, _("Match strictness") + ":")
        self._phi_match_mode_menu = ctk.CTkOptionMenu(
            parent,
            variable=self._phi_match_mode_var,
            values=match_labels,
            dynamic_resizing=False,
            width=option_menu_width_for_labels(match_labels),
        )
        self._phi_match_mode_menu.grid(row=row - 1, column=1, pady=(self.SECTION_PAD, 0), sticky="nw")
        self._detail_label(
            parent,
            _("Applies to whitelist and detected PHI entities for this batch"),
        ).grid(row=row, column=1, sticky="nw", pady=(4, 0))
        row += 1

        listed = modalities_with_whitelist_terms(self._project_dir, modalities)
        listed_text = ", ".join(listed)
        whitelist_label = _("Whitelists") if len(listed) > 1 else _("Whitelist")
        listed_width = ctk.CTkFont().measure(listed_text) + 4 if listed_text else 0
        self._batch_modalities_label = ctk.CTkLabel(
            parent,
            text=listed_text,
            width=listed_width,
            anchor="w",
            justify="left",
        )
        self._batch_modalities_label.grid(
            row=row,
            column=0,
            padx=(0, self.PAD),
            pady=(self.SECTION_PAD, 0),
            sticky="nw",
        )
        self._view_whitelist_button = ctk.CTkButton(
            parent,
            text=whitelist_label,
            width=button_width_for_label(whitelist_label, minimum=1),
            command=self._view_whitelist_button_clicked,
        )
        self._view_whitelist_button.grid(row=row, column=1, pady=(self.SECTION_PAD, 0), sticky="nw")
        row += 1

        remove_labels = list(ocr_remove_mode_menu_labels())
        self._ocr_remove_mode_var = tk.StringVar(
            value=ocr_remove_mode_display_label(OcrRemoveMode.NON_WHITELISTED)
        )
        row = self._option_label(parent, row, _("Pixel PHI Remove Scope") + ":")
        self._ocr_remove_mode_menu = ctk.CTkOptionMenu(
            parent,
            variable=self._ocr_remove_mode_var,
            values=remove_labels,
            command=self._on_ocr_remove_mode_changed,
            dynamic_resizing=False,
            width=option_menu_width_for_labels(remove_labels),
        )
        self._ocr_remove_mode_menu.grid(row=row - 1, column=1, pady=(self.SECTION_PAD, 0), sticky="nw")
        self._pixel_phi_whitelist_disabled_label = self._detail_label(
            parent,
            _("All detected OCR text will be removed; whitelist is ignored."),
        )
        self._pixel_phi_ner_hint_label = self._detail_label(
            parent,
            ocr_remove_mode_tooltip(OcrRemoveMode.PHI_ONLY),
        )
        self._pixel_phi_whitelist_disabled_label.grid(row=row, column=1, sticky="nw", pady=(4, 0))
        self._pixel_phi_ner_hint_label.grid(row=row, column=1, sticky="nw", pady=(4, 0))
        self._pixel_phi_whitelist_disabled_label.grid_remove()
        self._pixel_phi_ner_hint_label.grid_remove()
        row += 1

        removal_labels = list(pixel_phi_removal_mode_menu_labels())
        self._pixel_phi_mode_var = tk.StringVar(
            value=pixel_phi_removal_mode_option_label(PixelPhiRemovalMode.BLACKOUT)
        )
        row = self._option_label(parent, row, _("Pixel PHI removal") + ":")
        self._pixel_phi_mode_menu = ctk.CTkOptionMenu(
            parent,
            variable=self._pixel_phi_mode_var,
            values=removal_labels,
            dynamic_resizing=False,
            width=option_menu_width_for_labels(removal_labels),
        )
        self._pixel_phi_mode_menu.grid(row=row - 1, column=1, pady=(self.SECTION_PAD, 0), sticky="nw")
        self._detail_label(
            parent,
            _("Black out is recommended for de-identification, but can influence ML training."),
        ).grid(row=row, column=1, sticky="nw", pady=(4, 0))
        row += 1

        self._phi_entity_removal_labels = replace_mode_labels()
        entity_labels = list(self._phi_entity_removal_labels)
        self._phi_entity_removal_var = tk.StringVar(value=entity_labels[0])
        row = self._option_label(parent, row, _("Metadata & Report PHI entity removal") + ":")
        self._phi_entity_removal_menu = ctk.CTkOptionMenu(
            parent,
            variable=self._phi_entity_removal_var,
            values=entity_labels,
            dynamic_resizing=False,
            width=option_menu_width_for_labels(entity_labels),
        )
        self._phi_entity_removal_menu.grid(row=row - 1, column=1, pady=(self.SECTION_PAD, 0), sticky="nw")
        self._detail_label(
            parent,
            _("Blank removes the text. Synthetic replaces it with a realistic fake of the same type."),
        ).grid(row=row, column=1, sticky="nw", pady=(4, 0))
        row += 1

        self._ocr_use_exclude_areas_var = tk.IntVar(value=0)
        exclude_count = sum(
            len(rects) for rects in collect_exclude_areas_by_modality(self._project_dir, modalities).values()
        )
        if exclude_count:
            exclude_row = ctk.CTkFrame(parent, fg_color="transparent")
            exclude_row.grid(row=row, column=1, sticky="nw", pady=(self.SECTION_PAD, 0))
            self._ocr_use_exclude_areas_checkbox = ctk.CTkCheckBox(
                exclude_row,
                text=_("Enable Exclude Areas"),
                variable=self._ocr_use_exclude_areas_var,
                **feature_title_control_kwargs(),
            )
            self._ocr_use_exclude_areas_checkbox.pack(side="left")
            self._detail_label(exclude_row, _("{} defined").format(exclude_count)).pack(side="left", padx=(8, 0))
            row += 1
            self._detail_label(
                parent,
                _("Uses exclude areas saved in Series View."),
            ).grid(row=row, column=1, sticky="nw", pady=(4, 0))

    def _option_label(self, parent: ctk.CTkFrame, row: int, text: str) -> int:
        """
        Place a settings-style label in column 0.

        Args:
            parent: Options frame.
            row: Grid row for the label.
            text: Label text, including the trailing colon.

        Returns:
            The next grid row.
        """
        ctk.CTkLabel(parent, text=text, anchor="w").grid(
            row=row,
            column=0,
            padx=(0, self.PAD),
            pady=(self.SECTION_PAD, 0),
            sticky="nw",
        )
        return row + 1

    def _align_option_columns(self) -> None:
        """
        Give every feature the same label-column width.

        Column 1 then starts at the same x for Embedded PHI, Harmonize, and
        Face De-identify.
        """
        self.update_idletasks()
        widest = 0
        for parent in self._option_grids:
            for child in parent.winfo_children():
                info = child.grid_info()
                if str(info.get("column", "")) == "0":
                    widest = max(widest, child.winfo_reqwidth())
        if widest <= 0:
            return
        # Right padding on the label sits inside the column, so the shared
        # minimum has to include it or a long label pushes its controls over.
        column_width = widest + self.PAD
        for parent in self._option_grids:
            parent.grid_columnconfigure(0, minsize=column_width, weight=0)

    def _pad_wrapped_detail_labels(self) -> None:
        """
        Keep the space above a wrapped sentence the same as above a one-line sentence.

        A one-line label is taller than its text, and that spare space sits above
        the words. A sentence that wraps grows past the label and loses that space,
        so its first line sits closer to the feature checkbox.
        """
        self.update_idletasks()
        for label in self._detail_labels:
            text_widgets = [child for child in label.winfo_children() if isinstance(child, tk.Label)]
            if not text_widgets:
                continue
            text_h = int(text_widgets[0].winfo_reqheight())
            configured = int(label.cget("height"))
            if text_h <= configured:
                continue
            probe = tk.Label(self, text="Ag", font=text_widgets[0].cget("font"), bd=0, padx=0, pady=0)
            probe.update_idletasks()
            line_h = int(probe.winfo_reqheight())
            probe.destroy()
            spare = max(configured - line_h, 0)
            label.configure(height=text_h + spare)

    def _build_face_blur_options(self, parent: ctk.CTkFrame) -> None:
        """
        Face De-identify controls in the same two-column grid as Embedded PHI.

        Args:
            parent: Frame under the Face De-identify description.
        """
        parent.grid_columnconfigure(1, weight=1)
        self._blur_mode_var = tk.StringVar(value=face_blur_mode_menu_values()[0])
        blur_labels = list(face_blur_mode_menu_values())
        row = self._option_label(parent, 0, _("Face blur mode") + ":")
        self._blur_mode_menu = ctk.CTkOptionMenu(
            parent,
            variable=self._blur_mode_var,
            values=blur_labels,
            dynamic_resizing=False,
            width=option_menu_width_for_labels(blur_labels),
        )
        self._blur_mode_menu.grid(row=row - 1, column=1, pady=(self.SECTION_PAD, 0), sticky="nw")
        self._detail_label(
            parent,
            _("How face pixels are replaced on head CT and MR."),
        ).grid(row=row, column=1, sticky="nw", pady=(4, 0))

    def _build_harmonize_options(self, parent: ctk.CTkFrame) -> None:
        """
        Harmonize controls in the same two-column grid as Embedded PHI.

        Args:
            parent: Frame under the Harmonize description.
        """
        parent.grid_columnconfigure(1, weight=1)
        offer_brain = brain_structures_allowed()
        self._include_brain_structures_var = tk.IntVar(value=1 if offer_brain else 0)
        brain_text = (
            _("CT Head detail when a head series is present. Academic license.")
            if offer_brain
            else _("Download Brain structures models in AI Features to use this option.")
        )
        row = self._option_label(parent, 0, _("Brain structures") + ":")
        self._include_brain_structures_checkbox = ctk.CTkCheckBox(
            parent,
            text=brain_text,
            variable=self._include_brain_structures_var,
            state="normal" if offer_brain else "disabled",
            text_color=theme_label_text_color(),
        )
        self._include_brain_structures_checkbox.grid(
            row=row - 1, column=1, pady=(self.SECTION_PAD, 0), sticky="nw"
        )
        row += 1

        self._prefer_description_mappings_var = tk.IntVar(value=1)
        row = self._option_label(parent, row, _("Description mappings") + ":")
        ctk.CTkCheckBox(
            parent,
            text=_("Apply a saved mapping and skip the anatomy model."),
            variable=self._prefer_description_mappings_var,
            text_color=theme_label_text_color(),
        ).grid(row=row - 1, column=1, pady=(self.SECTION_PAD, 0), sticky="nw")

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
            options_parent.grid_columnconfigure(0, weight=0)
            options_parent.grid_columnconfigure(1, weight=0)
            self._option_grids.append(options_parent)
            if algorithm is AiBatchAlgorithm.REMOVE_PIXEL_PHI:
                self._build_pixel_phi_options(options_parent)
            elif algorithm is AiBatchAlgorithm.HARMONIZE:
                self._build_harmonize_options(options_parent)
            elif algorithm is AiBatchAlgorithm.FACE_BLUR:
                self._build_face_blur_options(options_parent)

        self._align_option_columns()
        self._pad_wrapped_detail_labels()

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
        self._resize_to_content_in_place()

    def _resize_to_content_in_place(self) -> None:
        """
        Grow or shrink the dialog to its content without moving its top-left corner.

        One geometry write. Recentering on each checkbox click jumps the window.
        """
        try:
            if not self.winfo_viewable():
                return
            origin_x, origin_y = _toplevel_origin(self)
        except tk.TclError:
            return
        width, height = fit_toplevel_to_content(
            self,
            min_width=FEATURE_INTRO_WRAP + FEATURE_DIALOG_PAD * 4,
            pad=FEATURE_DIALOG_PAD * 4,
            apply=False,
        )
        if width < 1 or height < 1:
            return
        try:
            screen_w = int(self.winfo_screenwidth())
            screen_h = int(self.winfo_screenheight())
        except tk.TclError:
            screen_w, screen_h = width, height
        width = min(width, max(1, screen_w))
        height = min(height, max(1, screen_h))
        pos_x = max(0, min(origin_x, screen_w - width))
        pos_y = max(0, min(origin_y, screen_h - height))
        try:
            self.geometry(f"{width}x{height}+{pos_x}+{pos_y}")
        except tk.TclError:
            return

    def _selected_ocr_remove_mode(self) -> OcrRemoveMode:
        if not hasattr(self, "_ocr_remove_mode_var"):
            return OcrRemoveMode.NON_WHITELISTED
        return normalize_ocr_remove_mode(self._ocr_remove_mode_var.get())

    def _selected_phi_match_mode(self) -> PhiMatchMode | None:
        if not hasattr(self, "_phi_match_mode_var"):
            return None
        labels = getattr(self, "_match_mode_labels", None) or match_mode_menu_labels()
        return labels.get(self._phi_match_mode_var.get(), PhiMatchMode.STANDARD)

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
        # Whitelist is a veto in every scope except All text.
        self._view_whitelist_button.configure(
            state="disabled" if mode is OcrRemoveMode.ALL_TEXT else "normal"
        )
        if hasattr(self, "_pixel_phi_whitelist_disabled_label"):
            if mode is OcrRemoveMode.ALL_TEXT:
                self._pixel_phi_whitelist_disabled_label.grid()
            else:
                self._pixel_phi_whitelist_disabled_label.grid_remove()
        if hasattr(self, "_pixel_phi_ner_hint_label"):
            if mode is OcrRemoveMode.PHI_ONLY:
                self._pixel_phi_ner_hint_label.grid()
            else:
                self._pixel_phi_ner_hint_label.grid_remove()

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
        phi_match_mode = self._selected_phi_match_mode()
        ocr_use_exclude_areas = bool(
            hasattr(self, "_ocr_use_exclude_areas_var") and self._ocr_use_exclude_areas_var.get() == 1
        )
        entity_removal = "blank"
        if hasattr(self, "_phi_entity_removal_labels"):
            entity_removal = self._phi_entity_removal_labels.get(self._phi_entity_removal_var.get(), "blank")
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
                phi_match_mode=phi_match_mode,
                ocr_use_exclude_areas=ocr_use_exclude_areas,
                include_brain_structures=include_brain,
                prefer_description_mappings=prefer_mappings,
                series_description_overrides=series_overrides,
                study_loinc_overrides=study_overrides,
                metadata_replace_mode=entity_removal,
                reports_replace_mode=entity_removal,
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
