"""
This module contains the DatasetView class, which is a tkinter Toplevel window for viewing the study index.
The DatasetView class provides a user interface for viewing the study index, deleting studies and exporting the patient lookup table to file.
"""

from __future__ import annotations

import logging
from pathlib import Path
from tkinter import messagebox, ttk

import customtkinter as ctk

from anonymizer.controller.phi_io import PHI_IndexRecord, PHI_SeriesIndexRecord
from anonymizer.controller.project import ProjectController
from anonymizer.utils.translate import _
from anonymizer.view.ai.ai_batch_process_dialog import AiBatchProcessDialog
from anonymizer.view.ai.ai_batch_process_options_dialog import show_ai_batch_process_options_dialog
from anonymizer.view.ai.features.availability import any_ai_batch_feature_allowed
from anonymizer.view.common.app_window import AppToplevel
from anonymizer.view.common.ctk_safe import teardown_ctk_toplevel
from anonymizer.view.common.fonts import AppFonts, char_width_px
from anonymizer.view.project.delete_studies_dialog import DeleteStudiesDialog
from anonymizer.view.series.projection import ProjectionView
from anonymizer.view.series.series import show_series_view
from anonymizer.view.shell.dashboard import Dashboard

logger = logging.getLogger(__name__)

STUDY_IID_PREFIX = "study:"
SERIES_IID_PREFIX = "series:"


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
        self._projection_view: ProjectionView | None = None

        self.title("View Dataset")
        self.resizable(True, True)
        self.lift()
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.bind("<Return>", self._enter_keypress)
        self.bind("<Escape>", self._escape_keypress)
        self._create_widgets()
        self._update_tree_from_phi_index()

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
        self._tree.bind("<Double-1>", self._on_tree_double_click)
        self._tree.bind("<ButtonPress-3>", self._on_tree_right_click)
        self._tree.bind("<<TreeviewOpen>>", self._on_tree_open)
        self._tree.bind("<<TreeviewClose>>", self._on_tree_close)

        self._tree.heading("#0", text=_("Study / Series"))
        self._tree.column("#0", width=20 * self._char_width_px, stretch=False, anchor="w")

        col_names = PHI_IndexRecord.get_tree_display_titles()
        col_fields = PHI_IndexRecord.get_tree_display_fields()
        stretch_fields = {"pixel_phi_removed"}
        for col_idx, title in enumerate(col_names):
            field_name = col_fields[col_idx]
            self._tree.heading(field_name, text=_(title))
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

    def _close_projection_view(self) -> None:
        if self._projection_view is None:
            return
        try:
            if self._projection_view.winfo_exists():
                self._projection_view.destroy()
        except Exception:
            logger.debug("ProjectionView already closed", exc_info=True)
        self._projection_view = None

    def _open_projection_view(self, phi_records: list[PHI_IndexRecord]) -> None:
        """Open Projection View for ``phi_records``, replacing any existing instance."""
        if not phi_records:
            logger.error("No Studies selected")
            return
        self._close_projection_view()
        try:
            self._projection_view = ProjectionView(
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
            self._projection_view = None
            return
        self._projection_view.focus()

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

    def _on_tree_double_click(self, event) -> None:
        iid = self._tree.identify_row(event.y)
        if not iid:
            return
        series_uid = parse_series_tree_iid(iid)
        if series_uid is not None:
            self._open_series_by_uid(series_uid)
            return
        # Study row: toggle expand/collapse
        study_uid = parse_study_tree_iid(iid)
        if study_uid is None:
            return
        if self._tree.item(iid, "open"):
            self._tree.item(iid, open=False)
            self._expanded_study_uids.discard(study_uid)
        else:
            self._tree.item(iid, open=True)
            self._expanded_study_uids.add(study_uid)

    def _on_tree_right_click(self, event) -> None:
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
        # Prefer Projection View for multi-series studies (single shared instance).
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
        self._close_projection_view()

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
