"""
This module contains the DatasetView class, which is a tkinter Toplevel window for viewing the study index.
The DatasetView class provides a user interface for viewing the study index, deleting studies and exporting the patient lookup table to file.
"""

from __future__ import annotations

import contextlib
import logging
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

# Treeview multi-select modifiers (Shift | Control | Mod1/Command).
_TREE_MULTISELECT_STATE = 0x0001 | 0x0004 | 0x0008


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
        mono_font (ctk.CTkFont): The mono font used for layout sizing.
        title (str | None): The title of the view.

    Attributes:
        _data_font (ctk.CTkFont): The mono font. (used only for calculating character width)
        _parent (Dashboard): The parent dashboard.
        _controller (ProjectController): The project controller.
        _project_model (ProjectModel): The project model.
    """

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
        # Ignore FocusOut dismissals briefly after place/post (popdown steals focus).
        self._description_combo_suppress_focus_out_until: float = 0.0

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
        self._tree.bind("<ButtonRelease-1>", self._on_tree_description_activate)
        self._tree.bind("<ButtonPress-3>", self._on_tree_right_click)
        self._tree.bind("<<TreeviewOpen>>", self._on_tree_open)
        self._tree.bind("<<TreeviewClose>>", self._on_tree_close)
        MotionTooltipController(self._tree, self._tree_row_tooltip_text, parent=self).bind()

        self._tree.heading("#0", text=_("Study / Series"))
        self._tree.column("#0", width=20 * self._char_width_px, stretch=False, anchor="w")

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
        self._view_projections_button.grid(row=0, column=2, padx=PAD, pady=PAD, sticky="e")
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
        self._create_phi_button.grid(row=0, column=3, padx=PAD, pady=PAD, sticky="e")

        self._refresh_button = ctk.CTkButton(
            self._button_frame,
            width=ButtonWidth,
            text=_("Refresh"),
            command=self._refresh_button_pressed,
        )
        self._refresh_button.grid(row=0, column=4, padx=PAD, pady=PAD, sticky="e")
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

    @staticmethod
    def _any_ai_batch_feature_enabled() -> bool:
        return any_ai_batch_feature_allowed()

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

    def _clear_selection_button_pressed(self):
        logger.info("Clear Selection button pressed")
        self._tree.selection_set([])

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
        series_uid = parse_series_tree_iid(iid)
        if series_uid is not None:
            pair = self._series_by_uid.get(series_uid)
            if pair is None or not pair[1].is_harmonized():
                return None
            return _("Click description to choose RadLex alternative · Right-click to open Series View")
        study_uid = parse_study_tree_iid(iid)
        if study_uid is not None:
            record = self._studies_by_uid.get(study_uid)
            if record is None or not record.harmonize:
                return None
            return _("Click description to choose LOINC alternative · Right-click to view study projections")
        return None

    def _cancel_description_combo_dismiss(self) -> None:
        after_id = self._description_combo_dismiss_after_id
        if after_id is not None:
            with contextlib.suppress(tk.TclError):
                self.after_cancel(after_id)
            self._description_combo_dismiss_after_id = None

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
        combo.focus_set()

        def open_dropdown() -> None:
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
        self.after(10, open_dropdown)

    def _on_tree_description_activate(self, event) -> None:
        # Preserve multi-select: modifier clicks are selection gestures, not description edit.
        state = int(getattr(event, "state", 0) or 0)
        if state & _TREE_MULTISELECT_STATE:
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
                # Same row: ensure the list is posted (first click may have lost the race).
                combo = self._description_combo
                if combo is not None and not self._description_combo_popdown_mapped(combo):
                    self._suppress_description_combo_focus_out(600)
                    with contextlib.suppress(tk.TclError):
                        combo.tk.call("ttk::combobox::Post", combo)
                return
            self._dismiss_description_combo(apply=False)

        series_uid = parse_series_tree_iid(iid)
        if series_uid is not None:
            self._edit_series_description(iid, series_uid)
            return
        study_uid = parse_study_tree_iid(iid)
        if study_uid is not None:
            self._edit_study_description(iid, study_uid)

    def _edit_study_description(self, iid: str, anon_study_uid: str) -> None:
        from anonymizer.controller.ai.harmonize import (
            apply_harmonized_study_description,
            study_description_edit_choices,
        )

        record = self._studies_by_uid.get(anon_study_uid)
        if record is None or not record.harmonize:
            return

        anon_model = self._controller.anonymizer.model
        current = (anon_model.get_study_harmonized_description(anon_study_uid) or "").strip()
        if not current:
            return

        pairs = study_description_edit_choices(anon_model, anon_study_uid)
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

        # Ensure current harmonized value is first.
        current_label = None
        for label in labels:
            name = label.rsplit("  (", 1)[0].strip() if "  (" in label else label
            if name == current:
                current_label = label
                break
        if current_label is None:
            labels.insert(0, current)
            choice_meta[current] = None
            current_label = current
        else:
            labels = [current_label] + [label for label in labels if label != current_label]

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
            series_description_edit_choices,
        )

        pair = self._series_by_uid.get(anon_series_uid)
        if pair is None:
            return
        study, series = pair
        if not series.is_harmonized():
            return
        current = (series.harmonized_description or "").strip()
        if not current:
            return

        choices = series_description_edit_choices(
            modality=series.modality,
            current_description=current,
        )
        if not choices:
            return
        series_path = series_path_for_record(self._controller.model.images_dir(), study, series)
        if not series_path.is_dir():
            messagebox.showerror(
                title=_("Edit Series Description"),
                message=_("Series folder not found on disk."),
                parent=self,
            )
            return

        anon_model = self._controller.anonymizer.model

        def apply_fn(description: str, _loinc_number: str | None) -> bool:
            return apply_harmonized_description(series_path, description, anon_model)

        self._place_description_combo(
            iid,
            choices=choices,
            choice_meta={label: None for label in choices},
            initial=current if current in choices else choices[0],
            apply_callback=apply_fn,
        )

    def _on_tree_right_click(self, event) -> None:
        self._dismiss_description_combo(apply=False)
        iid = self._tree.identify_row(event.y)
        if not iid:
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
