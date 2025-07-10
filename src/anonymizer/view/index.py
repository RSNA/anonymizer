"""
This module contains the IndexView class, which is a tkinter Toplevel window for viewing the study index.
The IndexView class provides a user interface for viewing the study index, deleting studies and exporting the patient lookup table to file.
"""

import logging
import tkinter as tk
from tkinter import messagebox, ttk

import customtkinter as ctk

from anonymizer.controller.project import ProjectController
from anonymizer.model.anonymizer import AnonymizerModel, PHI_IndexRecord
from anonymizer.utils.translate import _
from anonymizer.view.dashboard import Dashboard
from anonymizer.view.delete_studies_dialog import DeleteStudiesDialog
from anonymizer.view.projection import ProjectionView
from anonymizer.view.series import SeriesView

logger = logging.getLogger(__name__)


class IndexView(tk.Toplevel):
    """
    Represents a view of the project's study index.

    Args:
        parent (Dashboard): The parent dashboard.
        project_controller (ProjectController): The project controller.
        mono_font (ctk.CTkFont): The mono font.
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
        char_width_px: int,
    ):
        super().__init__(master=parent)
        self._char_width_px = char_width_px
        self._parent = parent
        self._controller = project_controller
        self._anon_model: AnonymizerModel = project_controller.anonymizer.model
        self._phi_index: list[PHI_IndexRecord] | None = None
        self._projection_view: ProjectionView | None = None

        self.title("View PHI Index")
        self.resizable(True, True)
        self.lift()
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.bind("<Return>", self._enter_keypress)
        self.bind("<Escape>", self._escape_keypress)
        self.bind("<ButtonPress-3>", self._open_series_view)  # Right-click press
        self._create_widgets()
        self._update_tree_from_phi_index()

    def _create_widgets(self):
        logger.info("_create_widgets")
        PAD = 10
        ButtonWidth = 100
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # 1. INDEX Frame for file treeview:
        self._index_frame = ctk.CTkFrame(self)
        self._index_frame.grid(row=0, column=0, padx=PAD, pady=(0, PAD), sticky="nswe")
        self._index_frame.grid_rowconfigure(0, weight=1)
        self._index_frame.grid_columnconfigure(3, weight=1)

        # Treeview:
        self._tree = ttk.Treeview(
            self._index_frame,
            show="headings",
            style="Treeview",
            columns=list(PHI_IndexRecord.get_field_names()),
            height=30,
        )
        # self._tree.bind("<<TreeviewSelect>>", self._tree_select)
        self._tree.grid(row=0, column=0, columnspan=11, sticky="nswe")

        # Set tree column headers, width and justification
        col_names = PHI_IndexRecord.get_field_titles()
        for col in range(len(col_names)):
            self._tree.heading(col, text=col_names[col])
            self._tree.column(
                column=col,
                width=(len(col_names[col]) + 2) * self._char_width_px,
                stretch=False,
            )

        # Setup display tags:
        self._tree.tag_configure("green", background="limegreen", foreground="white")
        self._tree.tag_configure("red", background="red")

        # Populate treeview with existing patients
        self._update_tree_from_phi_index()

        # Create a Scrollbar and associate it with the Treeview
        scrollbar = ttk.Scrollbar(self._index_frame, orient="vertical", command=self._tree.yview)
        scrollbar.grid(row=0, column=11, sticky="ns")
        self._tree.configure(yscrollcommand=scrollbar.set)

        # 2. Button Frame:
        self._button_frame = ctk.CTkFrame(self)
        self._button_frame.grid(row=1, column=0, padx=PAD, pady=(0, PAD), sticky="nswe")
        self._button_frame.grid_columnconfigure(3, weight=1)

        # Control buttons:
        self._view_projections_button = ctk.CTkButton(
            self._button_frame,
            width=ButtonWidth,
            text=_("View Projections"),
            command=self._view_projections_button_pressed,
        )
        self._view_projections_button.grid(row=0, column=4, padx=PAD, pady=PAD, sticky="w")

        self._create_phi_button = ctk.CTkButton(
            self._button_frame,
            width=ButtonWidth,
            text=_("Create Patient Lookup"),
            command=self._create_phi_button_pressed,
        )
        self._create_phi_button.grid(row=0, column=5, padx=PAD, pady=PAD, sticky="w")

        self._refresh_button = ctk.CTkButton(
            self._button_frame,
            width=ButtonWidth,
            text=_("Refresh"),
            command=self._refresh_button_pressed,
        )
        self._refresh_button.grid(row=0, column=7, padx=PAD, pady=PAD, sticky="we")
        self._select_all_button = ctk.CTkButton(
            self._button_frame,
            width=ButtonWidth,
            text=_("Select All"),
            command=self._select_all_button_pressed,
        )
        self._select_all_button.grid(row=0, column=8, padx=PAD, pady=PAD, sticky="w")

        self._clear_selection_button = ctk.CTkButton(
            self._button_frame,
            width=ButtonWidth,
            text=_("Clear Selection"),
            command=self._clear_selection_button_pressed,
        )
        self._clear_selection_button.grid(row=0, column=9, padx=PAD, pady=PAD, sticky="w")

        self._delete_button = ctk.CTkButton(
            self._button_frame,
            width=ButtonWidth,
            text=_("Delete"),
            command=self._delete_button_pressed,
        )
        self._delete_button.grid(row=0, column=10, padx=PAD, pady=PAD, sticky="e")
        self._delete_button.focus_set()

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

    def _update_tree_from_phi_index(self):
        # Clear tree to ensure all items are removed before re-populating:
        self._tree.delete(*self._tree.get_children())

        self._phi_index = self._anon_model.get_phi_index()

        if self._phi_index is None:
            logger.warning("No Studies/PHI data in Anonymizer Model for PHI Index")
            return _("No Studies in Anonymizer Model for PHI Index")

        for row, record in enumerate(self._phi_index):
            self._tree.insert("", 0, iid=row, values=record.flatten())

    def _view_projections_button_pressed(self):
        if self._phi_index is None:
            return

        if self._projection_view and self._projection_view.winfo_exists():
            logger.info("PixelsView already OPEN")
            self._projection_view.deiconify()
            self._projection_view.focus_force()
            return

        rows_selected = list(self._tree.selection())
        logger.info(f"View Pixels button pressed, {len(rows_selected)} studies selected")
        if len(rows_selected) == 0:
            logger.error("No Studies selected")
            return

        selected_indices = [int(row) for row in rows_selected]  # convert to integers
        selected_phi_records = [self._phi_index[i] for i in selected_indices]

        self._projection_view = ProjectionView(
            self,
            anon_model=self._anon_model,
            base_dir=self._controller.model.images_dir(),
            phi_records=selected_phi_records,
        )
        if self._projection_view is None:
            logger.error("Internal Error creating PixelsView")
            return

        self._projection_view.focus()

    def _refresh_button_pressed(self):
        logger.info("Refresh button pressed, update tree from PHI Index...")
        self._update_tree_from_phi_index()

    def _select_all_button_pressed(self):
        logger.info("Select All button pressed")
        self._tree.selection_set(*self._tree.get_children())

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

        rows_to_delete = self._tree.selection()

        if len(rows_to_delete) == 0:
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
                    "Selected studies will be permanently deleted from PHI Index and all associated anonymized files deleted from local storage directory"
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

        logger.info(f"Delete of {len(rows_to_delete)} studies initiated")
        studies: list[tuple[str, str]] = []
        for row in rows_to_delete:
            studies.append(
                (
                    self._phi_index[int(row)].anon_patient_id,
                    self._phi_index[int(row)].anon_study_uid,
                )
            )
        dlg = DeleteStudiesDialog(self, self._controller, studies)
        dlg.get_input()
        self._update_tree_from_phi_index()
        self._parent.update_totals(self._anon_model.get_totals())

    def _open_series_view(self, event):
        logger.info("Right click")
        if self._phi_index is None:
            return

        rows_selected = list(self._tree.selection())
        if len(rows_selected) == 0:
            return

        ndx = int(rows_selected[0])
        if ndx > len(self._phi_index):
            logger.error("Critical phi_indexing error.")
            return

        phi_record = self._phi_index[ndx]
        # TODO: UX with listbox of series descriptions / uids
        study_path = self._controller.model.images_dir() / phi_record.anon_patient_id / phi_record.anon_study_uid
        if study_path.exists():
            # Filter out hidden files/directories and get first series directory
            first_series_path = next((p for p in study_path.iterdir() if not p.name.startswith(".")), None)
            if first_series_path:
                SeriesView(self, anon_model=self._anon_model, series_path=first_series_path)

    def _escape_keypress(self, event):
        logger.info("_escape_pressed")
        self._on_cancel()

    def _on_cancel(self):
        logger.info("_on_cancel")
        if self._projection_view:
            self._projection_view.destroy()

        self.grab_release()
        self.destroy()

    def get_input(self):
        """
        Get the user input.

        """
        self.focus()
        self.master.wait_window(self)
        return
