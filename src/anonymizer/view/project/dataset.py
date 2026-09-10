"""
This module contains the DatasetView class, which is a tkinter Toplevel window for viewing the study index.
The DatasetView class provides a user interface for viewing the study index, deleting studies and exporting the patient lookup table to file.
"""

from __future__ import annotations

import contextlib
import logging
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

import customtkinter as ctk

from anonymizer.controller.ai.feature_availability import any_ai_batch_feature_allowed
from anonymizer.controller.phi_io import PHI_IndexRecord, PHI_SeriesIndexRecord
from anonymizer.controller.project import ProjectController
from anonymizer.utils.translate import _
from anonymizer.view.ai.ai_batch_process_dialog import AiBatchProcessDialog
from anonymizer.view.ai.ai_batch_process_options_dialog import show_ai_batch_process_options_dialog
from anonymizer.view.common.app_window import AppToplevel, focus_app_window
from anonymizer.view.common.ctk_safe import teardown_ctk_toplevel
from anonymizer.view.common.fonts import AppFonts, char_width_px
from anonymizer.view.common.tooltip import MotionTooltipController, bind_hover_tooltip
from anonymizer.view.project.delete_studies_dialog import DeleteStudiesDialog
from anonymizer.view.series.projection import ProjectionView, projection_study_uids
from anonymizer.view.series.series import show_series_view
from anonymizer.view.shell.dashboard import Dashboard

logger = logging.getLogger(__name__)

STUDY_IID_PREFIX = "study:"
SERIES_IID_PREFIX = "series:"

# Multi-select modifiers for description-edit vs selection gestures.
# Windows maps Num Lock to Mod1 (0x0008) — do NOT treat Mod1/Mod2 as multi-select there
# or every click with Num Lock on is ignored (no Set description).
if sys.platform == "darwin":
    _TREE_MULTISELECT_STATE = (
        0x0001  # Shift
        | 0x0004  # Control
        | 0x00080000  # Option
        | 0x00100000  # Command
    )
else:
    _TREE_MULTISELECT_STATE = (
        0x0001  # Shift
        | 0x0004  # Control
    )


def study_tree_iid(anon_study_uid: str) -> str:
    return f"{STUDY_IID_PREFIX}{anon_study_uid}"


def series_tree_iid(anon_series_uid: str) -> str:
    return f"{SERIES_IID_PREFIX}{anon_series_uid}"


def parse_study_tree_iid(iid: str) -> str | None:
    if not iid.startswith(STUDY_IID_PREFIX):
        return None
    return iid[len(STUDY_IID_PREFIX) :]


def parse_series_tree_iid(iid: str) -> str | None:
    if not iid.startswith(SERIES_IID_PREFIX):
        return None
    return iid[len(SERIES_IID_PREFIX) :]


def resolve_selected_study_records(
    selected_iids: list[str],
    studies_by_uid: dict[str, PHI_IndexRecord],
    series_parent_by_uid: dict[str, str],
) -> list[PHI_IndexRecord]:
    """Map mixed study/series tree selection to unique study records (study actions)."""
    seen: set[str] = set()
    records: list[PHI_IndexRecord] = []
    for iid in selected_iids:
        study_uid = parse_study_tree_iid(iid)
        if study_uid is None:
            series_uid = parse_series_tree_iid(iid)
            if series_uid is None:
                continue
            study_uid = series_parent_by_uid.get(series_uid)
        if study_uid is None or study_uid in seen:
            continue
        record = studies_by_uid.get(study_uid)
        if record is None:
            continue
        seen.add(study_uid)
        records.append(record)
    return records


def series_path_for_record(
    images_dir: Path,
    study: PHI_IndexRecord,
    series: PHI_SeriesIndexRecord,
) -> Path:
    return images_dir / study.anon_patient_id / study.anon_study_uid / series.anon_series_uid


class DatasetView(AppToplevel):
    """
    Represents a view of the project's study index.

    Args:
        parent (Dashboard): The parent dashboard.
        project_controller (ProjectController): The project controller.
        fonts (AppFonts): Application fonts (mono used for column sizing).

    Attributes:
        _data_font (ctk.CTkFont): The mono font. (used only for calculating character width)
        _parent (Dashboard): The parent dashboard.
        _controller (ProjectController): The project controller.
        _project_model (ProjectModel): The project model.
    """

    # Tree #0 (study/series description): keep enough width for LOINC/RadLex text.
    _MIN_DESCRIPTION_CHARS = 30
    # Child series rows are indented under the expander; reserve space so ~30 chars stay visible.
    _SERIES_TREE_INDENT_CHARS = 6

    def __init__(
        self,
        parent: Dashboard,
        project_controller: ProjectController,
        fonts: AppFonts,
    ):
        super().__init__(master=parent)
        self._fonts = fonts
        self._char_width_px = char_width_px(fonts.mono)
        self._parent = parent
        self._controller = project_controller
        self._phi_index: list[PHI_IndexRecord] | None = None
        self._studies_by_uid: dict[str, PHI_IndexRecord] = {}
        self._series_by_uid: dict[str, tuple[PHI_IndexRecord, PHI_SeriesIndexRecord]] = {}
        self._series_parent_by_uid: dict[str, str] = {}
        self._expanded_study_uids: set[str] = set()
        self._projection_views: dict[tuple[str, ...], ProjectionView] = {}
        self._projection_open_in_progress = False
        self._description_combo: ttk.Combobox | None = None
        self._description_combo_meta: dict[str, str | None] = {}
        self._description_combo_apply = None
        self._description_combo_initial: str | None = None
        self._description_combo_iid: str | None = None
        self._description_combo_dismiss_after_id: str | None = None
        self._description_combo_open_after_id: str | None = None
        # Ignore FocusOut dismissals briefly after place/post (popdown steals focus).
        self._description_combo_suppress_focus_out_until: float = 0.0
        # True when the latest tree ButtonPress used a multi-select modifier.
        self._tree_press_was_multiselect: bool = False

        self.title(_("View Dataset"))
        self.resizable(True, True)
        self.lift()
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.bind("<Return>", self._enter_keypress)
        self.bind("<Escape>", self._escape_keypress)
        self._create_widgets()
        self._update_tree_from_phi_index()
        self._enable_filesystem_drops()

    def _enable_filesystem_drops(self) -> None:
        """Optional OS file/folder drop → same ImportFilesDialog path as File menu."""
        from anonymizer.view.common.filesystem_drop import enable_filesystem_drops

        app = self._parent.master  # Anonymizer (Dashboard's master)
        on_paths = getattr(app, "import_paths", None)
        if not callable(on_paths):
            return
        # Register on the window and the index frame so drops land on usable chrome.
        enable_filesystem_drops(self, on_paths)
        enable_filesystem_drops(self._index_frame, on_paths)

    def _create_widgets(self):
        logger.info("_create_widgets")
        PAD = 10
        ButtonWidth = 120
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # 1. INDEX Frame for file treeview:
        self._index_frame = ctk.CTkFrame(self)
        self._index_frame.grid(row=0, column=0, padx=PAD, pady=(0, PAD), sticky="nswe")
        self._index_frame.grid_rowconfigure(0, weight=1)
        self._index_frame.grid_columnconfigure(3, weight=1)

        # Treeview: study parents + series children
        self._tree = ttk.Treeview(
            self._index_frame,
            show="tree headings",
            style="Treeview",
            columns=list(PHI_IndexRecord.get_tree_display_fields()),
            height=30,
        )
        self._tree.grid(row=0, column=0, columnspan=11, sticky="nswe")
        # Single-click only: Double-1 also fires ButtonRelease and caused awkward re-entry.
        self._tree.bind("<ButtonPress-1>", self._on_tree_button_press, add="+")
        self._tree.bind("<ButtonRelease-1>", self._on_tree_description_activate)
        self._tree.bind("<ButtonPress-3>", self._on_tree_right_click)
        self._tree.bind("<<TreeviewOpen>>", self._on_tree_open)
        self._tree.bind("<<TreeviewClose>>", self._on_tree_close)
        self._tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        MotionTooltipController(self._tree, self._tree_row_tooltip_text, parent=self).bind()

        self._tree.heading("#0", text=_("Study / Series"))
        self._tree.column(
            "#0",
            width=self._MIN_DESCRIPTION_CHARS * self._char_width_px,
            stretch=False,
            anchor="w",
        )

        col_names = PHI_IndexRecord.get_tree_display_titles()
        col_fields = PHI_IndexRecord.get_tree_display_fields()
        stretch_fields = {"pixel_phi_removed"}
        for col_idx, title in enumerate(col_names):
            field_name = col_fields[col_idx]
            self._tree.heading(field_name, text=title)
            width_chars = max(len(title), 8) + 2
            if field_name == "modality":
                width_chars = max(width_chars, 12)
            self._tree.column(
                field_name,
                width=width_chars * self._char_width_px,
                stretch=field_name in stretch_fields,
                anchor="center",
            )

        self._tree.tag_configure("green", background="limegreen", foreground="white")
        self._tree.tag_configure("red", background="red")
        self._tree.tag_configure("series", foreground="#555555")

        self._update_tree_from_phi_index()

        scrollbar = ttk.Scrollbar(self._index_frame, orient="vertical", command=self._tree.yview)
        scrollbar.grid(row=0, column=11, sticky="ns")
        self._tree.configure(yscrollcommand=scrollbar.set)

        # 2. Button Frame:
        self._button_frame = ctk.CTkFrame(self)
        self._button_frame.grid(row=1, column=0, padx=PAD, pady=(0, PAD), sticky="nswe")
        self._button_frame.grid_columnconfigure(1, weight=1)

        self._ai_batch_process_button = ctk.CTkButton(
            self._button_frame,
            width=ButtonWidth,
            text=_("AI Batch Process"),
            command=self._ai_batch_process_button_pressed,
        )
        self._ai_batch_process_button.grid(row=0, column=0, padx=PAD, pady=PAD, sticky="w")
        if not self._any_ai_batch_feature_enabled():
            self._ai_batch_process_button.grid_remove()

        self._view_projections_button = ctk.CTkButton(
            self._button_frame,
            width=ButtonWidth,
            text=_("View Projections"),
            command=self._view_projections_button_pressed,
        )
        self._view_projections_button.grid(row=0, column=1, padx=PAD, pady=PAD, sticky="e")
        bind_hover_tooltip(
            self._view_projections_button,
            _("Open projections for the selected studies."),
            parent=self,
        )

        self._create_phi_button = ctk.CTkButton(
            self._button_frame,
            width=ButtonWidth,
            text=_("Create Patient Lookup"),
            command=self._create_phi_button_pressed,
        )
        self._create_phi_button.grid(row=0, column=2, padx=PAD, pady=PAD, sticky="e")

        self._refresh_button = ctk.CTkButton(
            self._button_frame,
            width=ButtonWidth,
            text=_("Refresh"),
            command=self._refresh_button_pressed,
        )
        self._refresh_button.grid(row=0, column=3, padx=PAD, pady=PAD, sticky="e")

        self._select_similar_button = ctk.CTkButton(
            self._button_frame,
            width=max(ButtonWidth, 140),
            text=_("Select Similar"),
            command=self._select_similar_button_pressed,
        )
        self._select_similar_button.grid(row=0, column=4, padx=PAD, pady=PAD, sticky="e")
        bind_hover_tooltip(self._select_similar_button, self._select_similar_tooltip_text, parent=self)

        self._select_all_button = ctk.CTkButton(
            self._button_frame,
            width=ButtonWidth,
            text=_("Select All"),
            command=self._select_all_button_pressed,
        )
        self._select_all_button.grid(row=0, column=5, padx=PAD, pady=PAD, sticky="e")

        self._clear_selection_button = ctk.CTkButton(
            self._button_frame,
            width=ButtonWidth,
            text=_("Clear Selection"),
            command=self._clear_selection_button_pressed,
        )
        self._clear_selection_button.grid(row=0, column=6, padx=PAD, pady=PAD, sticky="e")

        self._delete_button = ctk.CTkButton(
            self._button_frame,
            width=ButtonWidth,
            text=_("Delete"),
            command=self._delete_button_pressed,
        )
        self._delete_button.grid(row=0, column=7, padx=PAD, pady=PAD, sticky="e")
        self._delete_button.focus_set()
        self._refresh_description_action_buttons()

    @staticmethod
    def _any_ai_batch_feature_enabled() -> bool:
        return any_ai_batch_feature_allowed()

    def _on_tree_select(self, _event=None) -> None:
        self._refresh_description_action_buttons()

    def _selected_description_targets(
        self,
    ) -> tuple[str, list[str], object | None]:
        """
        Return ``(kind, uids, selection_info)`` where kind is ``series``, ``study``, or ``invalid``.
        """
        from anonymizer.controller.ai.harmonize import (
            classify_description_edit_selection,
            series_description_cohort_key,
            study_loinc_prefix_for_edit,
        )

        selected = list(self._tree.selection())
        series_uids: list[str] = []
        study_uids: list[str] = []
        for iid in selected:
            series_uid = parse_series_tree_iid(str(iid))
            if series_uid is not None:
                series_uids.append(series_uid)
                continue
            study_uid = parse_study_tree_iid(str(iid))
            if study_uid is not None:
                study_uids.append(study_uid)

        if series_uids and study_uids:
            info = classify_description_edit_selection(
                series_cohort_keys=["mixed"],
                study_loinc_prefixes=["mixed"],
            )
            return "invalid", [], info
        if series_uids:
            keys = []
            for uid in series_uids:
                pair = self._series_by_uid.get(uid)
                keys.append(series_description_cohort_key(pair[1].modality) if pair else None)
            info = classify_description_edit_selection(series_cohort_keys=keys)
            return info.kind, series_uids if info.kind == "series" else [], info
        if study_uids:
            anon_model = self._controller.anonymizer.model
            prefixes = [study_loinc_prefix_for_edit(anon_model, uid) for uid in study_uids]
            info = classify_description_edit_selection(study_loinc_prefixes=prefixes)
            return info.kind, study_uids if info.kind == "study" else [], info
        info = classify_description_edit_selection()
        return "invalid", [], info

    def _refresh_description_action_buttons(self) -> None:
        if not hasattr(self, "_select_similar_button"):
            return
        similar_ok = False
        selected = list(self._tree.selection())
        if len(selected) == 1:
            peers = self._similar_peer_uids_for_selection()
            similar_ok = True  # enabled so tooltip can explain zero peers
            if peers is None:
                similar_ok = False
        self._select_similar_button.configure(state="normal" if similar_ok else "disabled")

    def _similar_peer_uids_for_selection(self) -> list[str] | None:
        """Return peer UIDs for the single selected row, or None if Select similar is N/A."""
        from anonymizer.controller.ai.harmonize import (
            find_similar_series_uids,
            find_similar_study_uids,
            study_loinc_prefix_for_edit,
        )

        selected = list(self._tree.selection())
        if len(selected) != 1:
            return None
        iid = str(selected[0])
        series_uid = parse_series_tree_iid(iid)
        if series_uid is not None:
            pair = self._series_by_uid.get(series_uid)
            if pair is None:
                return None
            _study, series = pair
            desc = (series.harmonized_description or series.description or "").strip()
            candidates = [
                (
                    uid,
                    s.modality,
                    (s.harmonized_description or s.description or "").strip(),
                )
                for uid, (_st, s) in self._series_by_uid.items()
            ]
            return find_similar_series_uids(
                candidates,
                seed_uid=series_uid,
                seed_modality=series.modality,
                seed_description=desc,
            )
        study_uid = parse_study_tree_iid(iid)
        if study_uid is None:
            return None
        anon_model = self._controller.anonymizer.model

        def _prefix_from_record(record: PHI_IndexRecord) -> str | None:
            mod = str(record.modality or "").strip().upper()
            if mod in {"CT", "MR", "US", "MG"}:
                return f"{mod} "
            if mod in {"CR", "DX"}:
                return "XR "
            return None

        # In-memory Dataset labels only — one DB call for the seed prefix accuracy.
        seed_prefix = study_loinc_prefix_for_edit(anon_model, study_uid)
        study_candidates: list[tuple[str, str, str | None]] = []
        for uid, record in self._studies_by_uid.items():
            desc = (record.study_description or "").strip()
            prefix = seed_prefix if uid == study_uid else _prefix_from_record(record)
            study_candidates.append((uid, desc, prefix))
        return find_similar_study_uids(anon_model, study_uid, candidates=study_candidates)

    def _on_tree_button_press(self, event) -> None:
        state = int(getattr(event, "state", 0) or 0)
        self._tree_press_was_multiselect = bool(state & _TREE_MULTISELECT_STATE)
        if self._tree_press_was_multiselect and self._description_combo is not None:
            self._dismiss_description_combo(apply=False)

    def _on_tree_description_activate(self, event) -> None:
        # Preserve multi-select: modifier clicks are selection gestures, not description edit.
        # Prefer press-time flag — ButtonRelease often drops Shift/Cmd before release.
        state = int(getattr(event, "state", 0) or 0)
        multiselect_click = self._tree_press_was_multiselect or bool(state & _TREE_MULTISELECT_STATE)
        self._tree_press_was_multiselect = False
        if multiselect_click:
            if self._description_combo is not None:
                self._dismiss_description_combo(apply=False)
            return

        # Ignore expander clicks and non-description columns.
        if self._tree.identify_region(event.x, event.y) not in {"tree", "cell"}:
            return
        if self._tree.identify_column(event.x) != "#0":
            return
        # Tree indicator (expand/collapse) shares the #0 column — skip it.
        if self._tree.identify_element(event.x, event.y) in {"Indicator", "Treeitem.indicator"}:
            return
        iid = self._tree.identify_row(event.y)
        if not iid:
            return

        # Treeview already applied selection for this click; do not collapse a multi-select.
        selected = self._tree.selection()
        if len(selected) > 1:
            if self._description_combo is not None:
                self._dismiss_description_combo(apply=False)
            return

        if self._description_combo is not None:
            if self._description_combo_iid == iid:
                # Second click on the active row: close the menu and show the label again.
                self._dismiss_description_combo(apply=False)
                return
            self._dismiss_description_combo(apply=False)

        series_uid = parse_series_tree_iid(iid)
        if series_uid is not None:
            self._edit_series_description(iid, series_uid)
            return
        study_uid = parse_study_tree_iid(iid)
        if study_uid is not None:
            self._edit_study_description(iid, study_uid)

    def _set_description_tooltip_text(self) -> str:
        kind, uids, info = self._selected_description_targets()
        n = info.count or len(uids)
        if kind == "series":
            return _("Right-click to set the same RadLex description on {n} selected series").format(n=n)
        if kind == "study":
            return _("Right-click to set the same LOINC description on {n} selected studies").format(n=n)
        if info.reason == "mixed":
            return _("Select only studies or only series, then right-click to set description")
        if info.reason == "mixed_modality":
            return _("Selection must share the same modality, then right-click to set description")
        return _("Select one or more studies or series, then right-click to set description")

    def _select_similar_tooltip_text(self) -> str:
        selected = list(self._tree.selection())
        if not selected:
            return _("Select one study or series, then add others with the same description")

        series_count = sum(1 for iid in selected if parse_series_tree_iid(str(iid)) is not None)
        study_count = sum(1 for iid in selected if parse_study_tree_iid(str(iid)) is not None)

        # After Select similar (or any multi-select), button is disabled — report selection size.
        if len(selected) > 1:
            if series_count and not study_count:
                return _("{n} series selected").format(n=series_count)
            if study_count and not series_count:
                return _("{n} studies selected").format(n=study_count)
            return _("{n} rows selected").format(n=len(selected))

        peers = self._similar_peer_uids_for_selection()
        if peers is None:
            return _("Select one study or series, then add others with the same description")
        iid = str(selected[0])
        k = len(peers)
        if parse_series_tree_iid(iid) is not None:
            if k == 0:
                return _("No other series share this description")
            return _("Select {k} other series with the same description").format(k=k)
        if k == 0:
            return _("No other studies share this description")
        # Include the current study in the count shown to the user.
        return _("Change {n} studies with the same description").format(n=k + 1)

    def _apply_series_description_dialog(
        self,
        *,
        series_dirs: list[Path],
        choices: list[str],
        initial: str,
        title: str,
        hint: str,
        modality: str,
    ) -> None:
        from anonymizer.controller.ai.harmonize import apply_series_descriptions
        from anonymizer.view.ai.set_description_dialog import show_set_description_dialog

        if not choices or not series_dirs:
            return
        result = show_set_description_dialog(
            self,
            title=title,
            hint=hint,
            choices=choices,
            choice_meta={label: None for label in choices},
            initial=initial if initial in choices else choices[0],
            catalog_kind="radlex",
            modality=modality,
        )
        if not result.applied or not result.description:
            return
        updated = apply_series_descriptions(
            series_dirs=series_dirs,
            description=result.description,
            anon_model=self._controller.anonymizer.model,
        )
        self._update_tree_from_phi_index()
        if len(series_dirs) > 1:
            messagebox.showinfo(
                title=_("Series description"),
                message=_("Updated {ok} of {total} series descriptions").format(
                    ok=len(updated), total=len(series_dirs)
                ),
                parent=self,
            )

    def _apply_study_description_dialog(
        self,
        *,
        anon_study_uids: list[str],
        labels: list[str],
        choice_meta: dict[str, str | None],
        initial: str,
        title: str,
        hint: str,
        modality: str,
    ) -> None:
        from anonymizer.controller.ai.harmonize import apply_study_descriptions
        from anonymizer.view.ai.set_description_dialog import show_set_description_dialog

        if not labels or not anon_study_uids:
            return
        result = show_set_description_dialog(
            self,
            title=title,
            hint=hint,
            choices=labels,
            choice_meta=choice_meta,
            initial=initial,
            catalog_kind="loinc",
            modality=modality,
        )
        if not result.applied or not result.description:
            return
        updated = apply_study_descriptions(
            images_dir=Path(self._controller.model.images_dir()),
            anon_model=self._controller.anonymizer.model,
            anon_study_uids=anon_study_uids,
            description=result.description,
            loinc_number=result.loinc_number,
        )
        self._update_tree_from_phi_index()
        if len(anon_study_uids) > 1:
            messagebox.showinfo(
                title=_("Study description"),
                message=_("Updated {ok} of {total} study descriptions").format(
                    ok=len(updated), total=len(anon_study_uids)
                ),
                parent=self,
            )

    def _select_similar_button_pressed(self) -> None:
        peers = self._similar_peer_uids_for_selection()
        selected = list(self._tree.selection())
        if len(selected) != 1 or peers is None:
            messagebox.showinfo(
                title=_("Select Similar"),
                message=self._select_similar_tooltip_text(),
                parent=self,
            )
            return
        if not peers:
            messagebox.showinfo(
                title=_("Select Similar"),
                message=self._select_similar_tooltip_text(),
                parent=self,
            )
            return
        iid = str(selected[0])
        series_uid = parse_series_tree_iid(iid)
        add_iids: list[str] = []
        if series_uid is not None:
            add_iids = [series_tree_iid(uid) for uid in peers]
        else:
            add_iids = [study_tree_iid(uid) for uid in peers]
            # Expand matching studies so the selection is visible.
            for peer_iid in add_iids:
                with contextlib.suppress(tk.TclError):
                    self._tree.item(peer_iid, open=True)
        self._tree.selection_set(iid, *add_iids)
        self._refresh_description_action_buttons()

    def refresh_ai_feature_ui(self) -> None:
        if not hasattr(self, "_ai_batch_process_button"):
            return
        if self._any_ai_batch_feature_enabled():
            self._ai_batch_process_button.grid()
        else:
            self._ai_batch_process_button.grid_remove()

    def _selected_study_records(self) -> list[PHI_IndexRecord]:
        return resolve_selected_study_records(
            list(self._tree.selection()),
            self._studies_by_uid,
            self._series_parent_by_uid,
        )

    def _ai_batch_process_button_pressed(self) -> None:
        if not self._any_ai_batch_feature_enabled():
            messagebox.showinfo(
                title=_("AI Batch Process"),
                message=_("No AI features are enabled. Click AI Features on the Welcome screen."),
                parent=self,
            )
            return
        if not any_ai_batch_feature_allowed():
            messagebox.showinfo(
                title=_("AI Batch Process"),
                message=_("AI features are not ready yet. Click AI Features on the Welcome screen to download models."),
                parent=self,
            )
            return
        if self._phi_index is None:
            logger.error("self._phi_index is empty")
            return

        selected_records = self._selected_study_records()
        if not selected_records:
            messagebox.showerror(
                title=_("AI Batch Process"),
                message=_("No studies selected for AI batch processing.")
                + "\n\n"
                + _("Use SHIFT+Click and/or CMD/CTRL+Click to select multiple studies."),
                parent=self,
            )
            return

        studies: list[tuple[str, str]] = [
            (record.anon_patient_id, record.anon_study_uid) for record in selected_records
        ]

        options_result = show_ai_batch_process_options_dialog(
            self,
            project_dir=self._controller.model.storage_dir,
            images_dir=self._controller.model.images_dir(),
            studies=studies,
        )
        if not options_result.confirmed or options_result.options is None:
            return

        logger.info(
            "AI Batch Process pressed for %d studies with algorithms %s",
            len(studies),
            options_result.options.algorithms,
        )
        self._ai_batch_process_button.configure(state="disabled")
        try:
            dialog = AiBatchProcessDialog(self, self._controller, studies, options_result.options)
            dialog.get_input()
        finally:
            self._ai_batch_process_button.configure(state="normal")
        self._update_tree_from_phi_index()

    def _create_phi_button_pressed(self):
        logger.info("Create PHI button pressed")
        csv_path = self._controller.create_phi_csv()
        if isinstance(csv_path, str):
            logger.error(f"Failed to create PHI CSV file: {csv_path}")
            messagebox.showerror(
                master=self,
                title=_("Error Creating PHI CSV File"),
                message=csv_path,
                parent=self,
            )
            return
        else:
            logger.info(f"PHI CSV file created: {csv_path}")
            messagebox.showinfo(
                title=_("PHI CSV File Created"),
                message=_("PHI Lookup Data saved to") + f":\n\n{csv_path}",
                parent=self,
            )

    def _remember_expanded_studies(self) -> None:
        expanded: set[str] = set()
        for iid in self._tree.get_children(""):
            study_uid = parse_study_tree_iid(str(iid))
            if study_uid is not None and self._tree.item(iid, "open"):
                expanded.add(study_uid)
        self._expanded_study_uids = expanded

    def _update_tree_from_phi_index(self):
        self._remember_expanded_studies()
        self._tree.delete(*self._tree.get_children())

        self._phi_index = self._controller.get_phi_index_records()
        self._studies_by_uid = {}
        self._series_by_uid = {}
        self._series_parent_by_uid = {}

        if self._phi_index is None:
            logger.warning("No Studies/PHI data in Anonymizer Model for Dataset")
            return _("No Studies in Anonymizer Model for Dataset")

        for record in self._phi_index:
            self._studies_by_uid[record.anon_study_uid] = record
            study_iid = study_tree_iid(record.anon_study_uid)
            study_tags: tuple[str, ...] = ()
            if record.harmonize:
                study_tags = ("green",)
            self._tree.insert(
                "",
                "end",
                iid=study_iid,
                text=record.tree_label(),
                values=record.tree_values(),
                open=record.anon_study_uid in self._expanded_study_uids,
                tags=study_tags,
            )
            for series in record.series:
                self._series_by_uid[series.anon_series_uid] = (record, series)
                self._series_parent_by_uid[series.anon_series_uid] = record.anon_study_uid
                series_tags: list[str] = ["series"]
                if (series.harmonized_description or "").strip():
                    series_tags.append("green")
                self._tree.insert(
                    study_iid,
                    "end",
                    iid=series_tree_iid(series.anon_series_uid),
                    text=series.tree_label(),
                    values=record.series_tree_values(series),
                    tags=tuple(series_tags),
                )

        self._autosize_id_columns()
        self._autosize_description_column()
        self._refresh_description_action_buttons()

    def _autosize_description_column(self) -> None:
        """Widen Study/Series (#0) so at least ~30 description characters stay visible."""
        heading = _("Study / Series")
        max_chars = max(self._MIN_DESCRIPTION_CHARS, len(heading) + 2)
        for study_iid in self._tree.get_children(""):
            max_chars = max(max_chars, len(str(self._tree.item(study_iid, "text") or "")))
            for series_iid in self._tree.get_children(study_iid):
                text_len = len(str(self._tree.item(series_iid, "text") or ""))
                max_chars = max(max_chars, text_len + self._SERIES_TREE_INDENT_CHARS)
        self._tree.column(
            "#0",
            width=max_chars * self._char_width_px,
            stretch=False,
            anchor="w",
        )

    def _autosize_id_columns(self) -> None:
        """Widen PHI ID / Anon ID to fit the widest study value (plus heading)."""
        fields = PHI_IndexRecord.get_tree_display_fields()
        phi_idx = fields.index("phi_patient_id")
        anon_idx = fields.index("anon_patient_id")
        max_phi = len(_("PHI ID"))
        max_anon = len(_("Anon ID"))
        for study_iid in self._tree.get_children(""):
            values = self._tree.item(study_iid, "values")
            if not values:
                continue
            max_phi = max(max_phi, len(str(values[phi_idx])))
            max_anon = max(max_anon, len(str(values[anon_idx])))
        pad = 2
        self._tree.column("phi_patient_id", width=(max_phi + pad) * self._char_width_px)
        self._tree.column("anon_patient_id", width=(max_anon + pad) * self._char_width_px)

    def _projection_view_for(self, study_uids: tuple[str, ...]) -> ProjectionView | None:
        view = self._projection_views.get(study_uids)
        if view is None:
            return None
        try:
            if view.winfo_exists():
                return view
        except Exception:
            pass
        self._projection_views.pop(study_uids, None)
        return None

    def _forget_projection_view(self, study_uids: tuple[str, ...], _event=None) -> None:
        self._projection_views.pop(study_uids, None)

    def _close_projection_views(self) -> None:
        for study_uids in list(self._projection_views):
            view = self._projection_views.pop(study_uids)
            try:
                view.destroy()
            except Exception:
                logger.debug("ProjectionView already closed", exc_info=True)

    def _open_projection_view(self, phi_records: list[PHI_IndexRecord]) -> None:
        """Open or focus a Projection View for ``phi_records`` (one window per study set)."""
        if not phi_records:
            logger.error("No Studies selected")
            return

        study_uids = projection_study_uids(phi_records)
        existing = self._projection_view_for(study_uids)
        if existing is not None:
            focus_app_window(existing)
            return

        if self._projection_open_in_progress:
            return
        self._projection_open_in_progress = True
        try:
            try:
                view = ProjectionView(
                    self,
                    controller=self._controller,
                    base_dir=self._controller.model.images_dir(),
                    phi_records=phi_records,
                    fonts=self._fonts,
                )
            except Exception as e:
                logger.error("Error creating ProjectionView: %s", e)
                messagebox.showerror(
                    title=_("Error Creating Projection View"),
                    message=str(e),
                    parent=self,
                )
                return
            self._projection_views[study_uids] = view
            view.bind(
                "<Destroy>",
                lambda _event, uids=study_uids: self._forget_projection_view(uids),
                add="+",
            )
            focus_app_window(view)
        finally:
            self._projection_open_in_progress = False

    def _view_projections_button_pressed(self):
        if self._phi_index is None:
            return

        selected_phi_records = self._selected_study_records()
        logger.info("View Pixels button pressed, %d studies selected", len(selected_phi_records))
        if not selected_phi_records:
            logger.error("No Studies selected")
            return
        self._open_projection_view(selected_phi_records)

    def _refresh_button_pressed(self):
        logger.info("Refresh button pressed, update tree from Dataset...")
        self._update_tree_from_phi_index()

    def _select_all_button_pressed(self):
        logger.info("Select All button pressed")
        # Study parents only — batch/delete operate at study level.
        self._tree.selection_set(*self._tree.get_children(""))
        self._refresh_description_action_buttons()

    def _clear_selection_button_pressed(self):
        logger.info("Clear Selection button pressed")
        self._tree.selection_set([])
        self._refresh_description_action_buttons()

    def _enter_keypress(self, event):
        logger.info("_enter_pressed")
        self._delete_button_pressed()

    def _delete_button_pressed(self):
        logger.info("Delete button pressed")
        if self._phi_index is None:
            logger.error("self._phi_index is empty")
            return

        selected_records = self._selected_study_records()
        if not selected_records:
            logger.error("No patients selected for deletion")
            messagebox.showerror(
                title=_("Deletion Error"),
                message=_("No studies selected for deletion.")
                + "\n\n"
                + _("Use SHIFT+Click and/or CMD/CTRL+Click to select multiple studies."),
                parent=self,
            )
            return

        if not messagebox.askyesno(
            title=_("Confirm Study Deletion"),
            message=(
                _(
                    "Selected studies will be permanently deleted from Dataset and all associated anonymized files deleted from local storage directory"
                )
                + "\n\n"
                + _("Are you sure?")
            ),
            icon="warning",
            type="yesno",
            default="no",
            parent=self,
        ):
            logger.info("Study deletion aborted by user")
            return

        logger.info("Delete of %d studies initiated", len(selected_records))
        studies: list[tuple[str, str]] = [
            (record.anon_patient_id, record.anon_study_uid) for record in selected_records
        ]
        dlg = DeleteStudiesDialog(self, self._controller, studies)
        dlg.get_input()
        self._update_tree_from_phi_index()
        self._parent.update_totals(self._controller.get_totals())

    def _on_tree_open(self, _event=None) -> None:
        focus = self._tree.focus()
        study_uid = parse_study_tree_iid(focus) if focus else None
        if study_uid is not None:
            self._expanded_study_uids.add(study_uid)

    def _on_tree_close(self, _event=None) -> None:
        focus = self._tree.focus()
        study_uid = parse_study_tree_iid(focus) if focus else None
        if study_uid is not None:
            self._expanded_study_uids.discard(study_uid)

    def _tree_row_tooltip_text(self, event) -> str | None:
        iid = self._tree.identify_row(event.y)
        if not iid:
            return None

        selected = self._tree.selection()
        if len(selected) > 1:
            kind, uids, info = self._selected_description_targets()
            n = info.count or len(uids) or len(selected)
            if kind == "series":
                return _("Right-click to set the same RadLex description on {n} selected series").format(n=n)
            if kind == "study":
                return _("Right-click to set the same LOINC description on {n} selected studies").format(n=n)
            if info.reason == "mixed":
                return _("Select only studies or only series · Then right-click to set description")
            if info.reason == "mixed_modality":
                return _("Selection must share the same modality · Then right-click to set description")
            return _("Right-click a homogeneous selection to set description")

        series_uid = parse_series_tree_iid(iid)
        if series_uid is not None:
            pair = self._series_by_uid.get(series_uid)
            if pair is None:
                return None
            from anonymizer.controller.ai.harmonize import series_description_cohort_key

            if series_description_cohort_key(pair[1].modality) is None:
                return None
            return _("Click description to choose a RadLex name · Right-click opens Series View")

        study_uid = parse_study_tree_iid(iid)
        if study_uid is not None:
            record = self._studies_by_uid.get(study_uid)
            if record is None:
                return None
            from anonymizer.controller.ai.harmonize import study_loinc_prefix_for_edit

            anon_model = self._controller.anonymizer.model
            if study_loinc_prefix_for_edit(anon_model, study_uid) is None and not (
                anon_model.get_study_harmonized_description(study_uid) or ""
            ).strip():
                # Still allow tooltip when study has a display description / eligible modality.
                if not (record.modality or "").strip():
                    return None
            return _("Click description to choose a LOINC name · Right-click opens projections")
        return None

    def _cancel_description_combo_dismiss(self) -> None:
        after_id = self._description_combo_dismiss_after_id
        if after_id is not None:
            with contextlib.suppress(tk.TclError):
                self.after_cancel(after_id)
            self._description_combo_dismiss_after_id = None

    def _cancel_description_combo_open(self) -> None:
        after_id = self._description_combo_open_after_id
        if after_id is not None:
            with contextlib.suppress(tk.TclError):
                self.after_cancel(after_id)
            self._description_combo_open_after_id = None

    def _suppress_description_combo_focus_out(self, ms: int = 500) -> None:
        self._description_combo_suppress_focus_out_until = time.monotonic() + (ms / 1000.0)

    def _description_combo_popdown_mapped(self, combo: ttk.Combobox) -> bool:
        try:
            popdown = combo.tk.call("ttk::combobox::PopdownWindow", combo)
            return bool(combo.tk.getboolean(combo.tk.call("winfo", "ismapped", popdown)))
        except tk.TclError:
            return False

    def _dismiss_description_combo(self, *, apply: bool = False) -> None:
        self._cancel_description_combo_dismiss()
        self._cancel_description_combo_open()
        combo = self._description_combo
        if combo is None:
            return
        apply_fn = self._description_combo_apply
        meta = self._description_combo_meta
        initial = self._description_combo_initial
        try:
            if apply and apply_fn is not None:
                label = combo.get().strip()
                if label and label != (initial or ""):
                    loinc_number = meta.get(label)
                    description = label
                    if "  (" in label and label.endswith(")"):
                        description = label.rsplit("  (", 1)[0].strip()
                    apply_fn(description, loinc_number)
        finally:
            try:
                if self._description_combo_popdown_mapped(combo):
                    combo.tk.call("ttk::combobox::Unpost", combo)
            except tk.TclError:
                pass
            combo.destroy()
            self._description_combo = None
            self._description_combo_meta = {}
            self._description_combo_apply = None
            self._description_combo_initial = None
            self._description_combo_iid = None

    def _maybe_dismiss_description_combo(self) -> None:
        self._description_combo_dismiss_after_id = None
        combo = self._description_combo
        if combo is None:
            return
        if time.monotonic() < self._description_combo_suppress_focus_out_until:
            return
        if self._description_combo_popdown_mapped(combo):
            return
        try:
            focused = combo.focus_get()
            if focused is not None:
                focused_path = str(focused)
                combo_path = str(combo)
                if focused_path == combo_path or focused_path.startswith(combo_path + "."):
                    return
                if "popdown" in focused_path.lower() or focused.winfo_class() in {"Listbox", "TCombobox"}:
                    return
        except tk.TclError:
            pass
        self._dismiss_description_combo(apply=False)

    def _place_description_combo(
        self,
        iid: str,
        *,
        choices: list[str],
        choice_meta: dict[str, str | None],
        initial: str,
        apply_callback,
    ) -> None:
        self._dismiss_description_combo(apply=False)
        if not choices:
            return
        # Do not call selection_set here — that would collapse multi-study selection.
        self._tree.see(iid)
        self._tree.update_idletasks()
        bbox = self._tree.bbox(iid, "#0")
        if not bbox:
            # Row may still be laying out after expand/see; retry once.
            self.after(
                16,
                lambda: self._place_description_combo(
                    iid,
                    choices=choices,
                    choice_meta=choice_meta,
                    initial=initial,
                    apply_callback=apply_callback,
                ),
            )
            return
        x, y, width, height = bbox
        # Place on the tree's parent frame — widgets inside Treeview break popdown geometry
        # on macOS (list appears at top-left).
        parent = self._tree.master
        combo = ttk.Combobox(
            parent,
            values=choices,
            state="readonly",
            font=self._fonts.mono,
        )
        if initial in choices:
            combo.set(initial)
        else:
            combo.current(0)
        place_x = int(self._tree.winfo_x() + x)
        place_y = int(self._tree.winfo_y() + y)
        combo.place(x=place_x, y=place_y, width=max(int(width), 180), height=max(int(height), 22))
        combo.lift()
        self._description_combo = combo
        self._description_combo_iid = iid
        self._description_combo_meta = choice_meta
        self._description_combo_apply = apply_callback
        self._description_combo_initial = combo.get()
        self._suppress_description_combo_focus_out(600)

        def on_selected(_event=None) -> None:
            self._dismiss_description_combo(apply=True)
            self._update_tree_from_phi_index()

        def on_escape(_event=None) -> None:
            self._dismiss_description_combo(apply=False)

        def on_focus_out(_event=None) -> None:
            if time.monotonic() < self._description_combo_suppress_focus_out_until:
                return
            if self._description_combo_popdown_mapped(combo):
                return
            # Delay so a click on the dropdown list can still register as <<ComboboxSelected>>.
            self._cancel_description_combo_dismiss()
            self._description_combo_dismiss_after_id = self.after(250, self._maybe_dismiss_description_combo)

        combo.bind("<<ComboboxSelected>>", on_selected)
        combo.bind("<Return>", on_selected)
        combo.bind("<Escape>", on_escape)
        combo.bind("<FocusOut>", on_focus_out)

        def on_combo_click(_event=None) -> None:
            # Clicking the active field (not a list choice) cancels back to the tree label.
            def _close_to_label() -> None:
                if self._description_combo is not combo:
                    return
                self._dismiss_description_combo(apply=False)

            # Defer so a list selection can still fire <<ComboboxSelected>> first.
            self.after(80, _close_to_label)

        combo.bind("<ButtonRelease-1>", on_combo_click, add="+")
        combo.focus_set()

        def open_dropdown() -> None:
            self._description_combo_open_after_id = None
            if self._description_combo is not combo:
                return
            self._suppress_description_combo_focus_out(600)
            try:
                combo.update_idletasks()
                combo.tk.call("ttk::combobox::Post", combo)
            except tk.TclError:
                with contextlib.suppress(tk.TclError):
                    combo.event_generate("<Down>")

        # Post after geometry is realized; Button-1 synthesize places the list at (0,0).
        # A short delay beats after_idle on macOS where the widget is not yet mapped.
        self._cancel_description_combo_open()
        self._description_combo_open_after_id = self.after(10, open_dropdown)

    def _edit_study_description(self, iid: str, anon_study_uid: str) -> None:
        from anonymizer.controller.ai.harmonize import (
            apply_harmonized_study_description,
            study_description_edit_choices,
            study_description_group_choices,
            study_loinc_prefix_for_edit,
        )

        record = self._studies_by_uid.get(anon_study_uid)
        if record is None:
            return

        anon_model = self._controller.anonymizer.model
        if study_loinc_prefix_for_edit(anon_model, anon_study_uid) is None and not (
            anon_model.get_study_harmonized_description(anon_study_uid) or ""
        ).strip():
            from anonymizer.controller.ai.harmonize import series_description_cohort_key

            # Allow edit when study modality is Harmonize-eligible even without series yet.
            if series_description_cohort_key(record.modality) is None and not any(
                series_description_cohort_key(s.modality) for s in (record.series or [])
            ):
                return

        current = (anon_model.get_study_harmonized_description(anon_study_uid) or "").strip()
        is_harmonized = bool(current)
        if not current:
            current = (record.study_description or "").strip()

        kind, uids, _info = self._selected_description_targets()
        group_uids = uids if kind == "study" and anon_study_uid in uids and len(uids) > 1 else [anon_study_uid]
        full_catalog = not is_harmonized

        if len(group_uids) > 1:
            hints = []
            for uid in group_uids:
                rec = self._studies_by_uid.get(uid)
                text = (anon_model.get_study_harmonized_description(uid) or "").strip()
                if not text and rec is not None:
                    text = (rec.study_description or "").strip()
                hints.append(text)
                if not (anon_model.get_study_harmonized_description(uid) or "").strip():
                    full_catalog = True
            pairs = study_description_group_choices(
                anon_model,
                group_uids,
                hint_descriptions=hints,
            )
        else:
            pairs = study_description_edit_choices(
                anon_model,
                anon_study_uid,
                hint_description=current,
                full_catalog=full_catalog,
            )
        if not pairs:
            return

        choice_meta: dict[str, str | None] = {}
        labels: list[str] = []
        for name, code in pairs:
            label = f"{name}  ({code})" if code else name
            if label in choice_meta:
                continue
            choice_meta[label] = code
            labels.append(label)

        current_label = None
        for label in labels:
            name = label.rsplit("  (", 1)[0].strip() if "  (" in label else label
            if name == current:
                current_label = label
                break
        if current_label is not None:
            labels = [current_label] + [label for label in labels if label != current_label]
        else:
            # Unharmonized PHI is not a selectable option — default to first LOINC choice.
            current_label = labels[0]

        # Full LOINC catalog (or multi-select) uses the scrollable picker.
        if full_catalog or len(group_uids) > 1 or len(labels) > 12:
            n = len(group_uids)
            prefix = study_loinc_prefix_for_edit(anon_model, anon_study_uid) or ""
            modality = prefix.strip() or str(record.modality or "").strip()
            if n > 1:
                title = _("Set {modality} study description ({n})").format(modality=modality, n=n)
                hint = _("Applies to all {n} selected {modality} studies").format(n=n, modality=modality)
            else:
                title = _("Set {modality} study description").format(modality=modality)
                hint = _("Choose a {modality} LOINC study description").format(modality=modality)
            self._apply_study_description_dialog(
                anon_study_uids=group_uids,
                labels=labels,
                choice_meta=choice_meta,
                initial=current_label,
                title=title,
                hint=hint,
                modality=modality,
            )
            return

        patient_id = anon_model.get_anon_patient_id_for_study(anon_study_uid)
        images_dir = self._controller.model.images_dir()
        study_root = Path(images_dir) / patient_id / anon_study_uid if patient_id else None

        def apply_fn(description: str, loinc_number: str | None) -> bool:
            if study_root is None or not study_root.is_dir():
                logger.error("Study root missing for %s", anon_study_uid)
                return False
            return apply_harmonized_study_description(
                study_root,
                description,
                anon_model,
                anon_study_uid,
                loinc_number=loinc_number,
            )

        self._place_description_combo(
            iid,
            choices=labels,
            choice_meta=choice_meta,
            initial=current_label,
            apply_callback=apply_fn,
        )

    def _edit_series_description(self, iid: str, anon_series_uid: str) -> None:
        from anonymizer.controller.ai.harmonize import (
            apply_harmonized_description,
            series_description_cohort_key,
            series_description_edit_choices,
            series_description_group_choices,
        )
        from anonymizer.controller.ai.harmonize.pipeline import _series_description_looks_playbook

        pair = self._series_by_uid.get(anon_series_uid)
        if pair is None:
            return
        study, series = pair
        if series_description_cohort_key(series.modality) is None:
            return
        current = (series.harmonized_description or series.description or "").strip()
        is_harmonized = bool((series.harmonized_description or "").strip()) or _series_description_looks_playbook(
            modality=series.modality,
            description=current,
        )
        study_hint = (study.study_description or "").strip()

        kind, uids, _info = self._selected_description_targets()
        group_uids = (
            uids if kind == "series" and anon_series_uid in uids and len(uids) > 1 else [anon_series_uid]
        )
        full_catalog = not is_harmonized
        images_dir = Path(self._controller.model.images_dir())

        if len(group_uids) > 1:
            modalities = []
            descriptions = []
            series_dirs: list[Path] = []
            for uid in group_uids:
                item = self._series_by_uid.get(uid)
                if item is None:
                    continue
                st, ser = item
                modalities.append(ser.modality)
                desc = (ser.harmonized_description or ser.description or "").strip()
                descriptions.append(desc)
                if not (ser.harmonized_description or "").strip() and not _series_description_looks_playbook(
                    modality=ser.modality, description=desc
                ):
                    full_catalog = True
                series_dirs.append(series_path_for_record(images_dir, st, ser))
            choices = series_description_group_choices(
                modalities=modalities,
                current_descriptions=descriptions,
                anatomy_hint=study_hint,
            )
        else:
            choices = series_description_edit_choices(
                modality=series.modality,
                current_description=current,
                full_catalog=full_catalog,
                anatomy_hint=study_hint,
            )
            series_dirs = [series_path_for_record(images_dir, study, series)]

        if not choices:
            return
        if any(not path.is_dir() for path in series_dirs):
            messagebox.showerror(
                title=_("Edit Series Description"),
                message=_("Series folder not found on disk."),
                parent=self,
            )
            return

        initial = current if current in choices else choices[0]
        if full_catalog or len(group_uids) > 1 or len(choices) > 12:
            n = len(series_dirs)
            modality = str(series.modality or "").strip()
            if n > 1:
                title = _("Set {modality} series description ({n})").format(modality=modality, n=n)
                hint = _("Applies to all {n} selected {modality} series").format(n=n, modality=modality)
            else:
                title = _("Set {modality} series description").format(modality=modality)
                hint = _("Choose a {modality} RadLex Playbook series description").format(modality=modality)
            self._apply_series_description_dialog(
                series_dirs=series_dirs,
                choices=choices,
                initial=initial,
                title=title,
                hint=hint,
                modality=modality,
            )
            return

        anon_model = self._controller.anonymizer.model
        series_path = series_dirs[0]

        def apply_fn(description: str, _loinc_number: str | None) -> bool:
            return apply_harmonized_description(series_path, description, anon_model)

        self._place_description_combo(
            iid,
            choices=choices,
            choice_meta={label: None for label in choices},
            initial=initial,
            apply_callback=apply_fn,
        )

    def _on_tree_right_click(self, event) -> None:
        self._dismiss_description_combo(apply=False)
        iid = self._tree.identify_row(event.y)
        if not iid:
            return

        selected = list(self._tree.selection())
        # Multi-select on a selected row: open Set description for a homogeneous group.
        if len(selected) > 1 and iid in selected:
            kind, _uids, _info = self._selected_description_targets()
            series_uid = parse_series_tree_iid(iid)
            if kind == "series" and series_uid is not None:
                self._edit_series_description(iid, series_uid)
                return
            study_uid = parse_study_tree_iid(iid)
            if kind == "study" and study_uid is not None:
                self._edit_study_description(iid, study_uid)
                return
            # Mixed / mixed-modality selection — keep selection, do not open viewers.
            return

        self._tree.selection_set(iid)
        series_uid = parse_series_tree_iid(iid)
        if series_uid is not None:
            self._open_series_by_uid(series_uid)
            return
        study_uid = parse_study_tree_iid(iid)
        if study_uid is None:
            return
        record = self._studies_by_uid.get(study_uid)
        if record is None:
            return
        # Prefer Projection View for multi-series studies.
        self._open_projection_view([record])

    def _open_series_by_uid(self, anon_series_uid: str) -> None:
        pair = self._series_by_uid.get(anon_series_uid)
        if pair is None:
            logger.error("Series uid not found in Dataset: %s", anon_series_uid)
            return
        study, series = pair
        series_path = series_path_for_record(self._controller.model.images_dir(), study, series)
        if not series_path.exists():
            messagebox.showerror(
                title=_("Series Not Found"),
                message=_("Series directory not found on disk") + f":\n\n{series_path}",
                parent=self,
            )
            return
        show_series_view(
            self,
            controller=self._controller,
            series_path=series_path,
            fonts=self._fonts,
        )

    def _escape_keypress(self, event):
        logger.info("_escape_pressed")
        self._on_cancel()

    def _on_cancel(self):
        logger.info("_on_cancel")
        self._close_projection_views()

        app = self.winfo_toplevel()
        if getattr(app, "dataset_view", None) is self:
            app.dataset_view = None

        self.grab_release()
        teardown_ctk_toplevel(self, parent=self.master)

    def get_input(self):
        """
        Get the user input.

        """
        self.focus()
        self.master.wait_window(self)
        return
