"""
This module contains the ExportView class, which is a tkinter Toplevel window for exporting studies.
The ExportView class provides a user interface for selecting and exporting studies from a project.
"""

import logging
import os
import tkinter as tk
from datetime import datetime
from queue import Empty, Full, Queue
from tkinter import messagebox, ttk

import customtkinter as ctk

from anonymizer.controller.project import (
    ExportPatientsRequest,
    ExportPatientsResponse,
    ProjectController,
)
from anonymizer.model.project import ProjectModel
from anonymizer.utils.storage import count_studies_series_images
from anonymizer.utils.translate import _
from anonymizer.view.dashboard import Dashboard

logger = logging.getLogger(__name__)


class ExportView(tk.Toplevel):
    """
    Represents a view for exporting data.

    Args:
        parent (Dashboard): The parent dashboard.
        project_controller (ProjectController): The project controller.
        mono_font (ctk.CTkFont): The mono font.
        title (str | None): The title of the view.

    Attributes:
        ux_poll_export_response_interval (int): The interval for polling export response in milliseconds.
        _data_font (ctk.CTkFont): The mono font.
        _attr_map (dict): A dictionary mapping column ids to column attributes.
        _parent (Dashboard): The parent dashboard.
        _controller (ProjectController): The project controller.
        _project_model (ProjectModel): The project model.
        _export_to_AWS (bool): Flag indicating whether to export to AWS.
        _export_active (bool): Flag indicating whether an export is active.
        _patients_processed (int): The number of patients processed.
        _patients_to_process (int): The number of patients to process.
        _patient_ids_to_export (list): The list of patient IDs to export.
        _export_frame (ctk.CTkFrame): The export frame.
        _tree (ttk.Treeview): The treeview for displaying export attributes.
        _error_frame (ctk.CTkFrame): The error frame.
        _error_label (ctk.CTkLabel): The label for displaying error messages.
        _status_frame (ctk.CTkFrame): The status frame.
        _status (ctk.CTkLabel): The label for displaying export status.
        _progressbar (ctk.CTkProgressBar): The progress bar for export.
        _cancel_export_button (ctk.CTkButton): The button for canceling export.
        _refresh_button (ctk.CTkButton): The button for refreshing the view.
        _select_all_button (ctk.CTkButton): The button for selecting all patients.
        _clear_selection_button (ctk.CTkButton): The button for clearing the selection.
        _export_button (ctk.CTkButton): The button for initiating export.
    """

    ux_poll_export_response_interval = 500  # milli-seconds

    def __init__(
        self,
        parent: Dashboard,
        project_controller: ProjectController,
        mono_font: ctk.CTkFont,
        title: str | None = None,
    ):
        super().__init__(master=parent)
        self._data_font = mono_font  # get mono font from app
        # Export attributes to display in the results Treeview:
        # Key: column id: (column name, width (in chars), centre justify, stretch column of resize)
        self._attr_map = {
            "Patient_Name": (_("Patient Name"), 20, False, False),
            "Anon_PatientID": (_("Anonymized ID"), 15, True, False),
            "Studies": (_("Studies"), 10, True, False),
            "Series": (_("Series"), 10, True, False),
            "Files": (_("Images"), 10, True, False),
            "DateTime": (_("Date Time"), 20, True, False),
            "FilesSent": (_("Images Sent"), 5, True, False),
            "Error": (_("Last Export Error"), 30, False, True),
        }
        self._parent = parent
        self._controller = project_controller
        self._project_model: ProjectModel = project_controller.model
        self._export_to_AWS = self._project_model.export_to_AWS
        if not self._export_to_AWS:
            dest = self._project_model.remote_scps[_("EXPORT")].aet
        else:
            dest = f"{self._project_model.aws_cognito.username}@AWS/{self._project_model.project_name}"

        if title is None:
            title = _("Export") + " " + _("Studies")

        self.title(f"{title} -> {dest}")
        self._export_active = False
        self._patients_processed = 0
        self._patients_to_process = 0
        self._patient_ids_to_export = []  # dynamically as per export progress
        self.resizable(True, True)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.bind("<Return>", self._enter_keypress)
        self.bind("<Escape>", self._escape_keypress)
        self._create_widgets()
        self._enable_action_buttons()

    def _create_widgets(self):
        logger.info("_create_widgets")
        PAD = 10
        ButtonWidth = 100
        char_width_px = self._data_font.measure("A")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # 1. Export Frame for file treeview:
        self._export_frame = ctk.CTkFrame(self)
        self._export_frame.grid(row=0, column=0, padx=PAD, pady=(0, PAD), sticky="nswe")
        self._export_frame.grid_rowconfigure(0, weight=1)
        self._export_frame.grid_columnconfigure(3, weight=1)

        # Treeview:
        self._tree = ttk.Treeview(
            self._export_frame,
            show="headings",
            style="Treeview",
            columns=list(self._attr_map.keys()),
        )
        self._tree.bind("<<TreeviewSelect>>", self._tree_select)
        self._tree.grid(row=0, column=0, columnspan=11, sticky="nswe")

        # Set tree column headers, width and justification
        for col in self._tree["columns"]:
            col_name = self._attr_map[col][0]
            self._tree.heading(col, text=col_name)
            col_width_chars = self._attr_map[col][1]
            if len(col_name) > col_width_chars:
                col_width_chars = len(col_name) + 2
            self._tree.column(
                col,
                width=col_width_chars * char_width_px,
                anchor="center" if self._attr_map[col][2] else "w",
                stretch=self._attr_map[col][3],
            )

        # Setup display tags:
        self._tree.tag_configure("green", background="limegreen", foreground="white")
        self._tree.tag_configure("red", background="red")

        # Populate treeview with existing patients
        self._update_tree_from_images_directory()

        # Create a Scrollbar and associate it with the Treeview
        scrollbar = ttk.Scrollbar(self._export_frame, orient="vertical", command=self._tree.yview)
        scrollbar.grid(row=0, column=11, sticky="ns")
        self._tree.configure(yscrollcommand=scrollbar.set)

        # Disable Keyboard selection bindings:
        self._tree.bind("<Left>", lambda e: "break")
        self._tree.bind("<Right>", lambda e: "break")
        self._tree.bind("<Up>", lambda e: "break")
        self._tree.bind("<Down>", lambda e: "break")

        # 3. ERROR FRAME:
        self._error_frame = ctk.CTkFrame(self)
        self._error_frame.grid(row=1, column=0, padx=PAD, pady=(0, PAD), sticky="nswe")
        self._error_frame.grid_columnconfigure(0, weight=1)

        self._error_label = ctk.CTkLabel(self._error_frame, anchor="w", justify="left")
        self._error_label.grid(row=0, column=0, padx=PAD, sticky="w")
        self._error_frame.grid_remove()

        # 4. STATUS Frame:
        self._status_frame = ctk.CTkFrame(self)
        self._status_frame.grid(row=2, column=0, padx=PAD, pady=(0, PAD), sticky="nswe")
        self._status_frame.grid_columnconfigure(3, weight=1)

        # Status and progress bar:
        self._status = ctk.CTkLabel(
            self._status_frame,
            font=self._data_font,
            text=_("Processing") + " _ " + _("of") + " _ " + _("Patients"),
        )
        self._status.grid(row=0, column=0, padx=PAD, pady=0, sticky="w")

        self._progressbar = ctk.CTkProgressBar(
            self._status_frame,
        )
        self._progressbar.grid(
            row=0,
            column=1,
            padx=PAD,
            pady=0,
            sticky="w",
        )
        self._progressbar.set(0)

        self._cancel_export_button = ctk.CTkButton(
            self._status_frame,
            width=ButtonWidth,
            text=_("Cancel Export"),
            command=self._cancel_export_button_pressed,
        )
        self._cancel_export_button.grid(row=0, column=2, padx=PAD, pady=PAD, sticky="w")

        self._refresh_button = ctk.CTkButton(
            self._status_frame,
            width=ButtonWidth,
            text=_("Refresh"),
            command=self._refresh_button_pressed,
        )
        self._refresh_button.grid(row=0, column=7, padx=PAD, pady=PAD, sticky="we")
        self._select_all_button = ctk.CTkButton(
            self._status_frame,
            width=ButtonWidth,
            text=_("Select All"),
            command=self._select_all_button_pressed,
        )
        self._select_all_button.grid(row=0, column=8, padx=PAD, pady=PAD, sticky="w")

        self._clear_selection_button = ctk.CTkButton(
            self._status_frame,
            width=ButtonWidth,
            text=_("Clear Selection"),
            command=self._clear_selection_button_pressed,
        )
        self._clear_selection_button.grid(row=0, column=9, padx=PAD, pady=PAD, sticky="w")

        self._export_button = ctk.CTkButton(
            self._status_frame,
            width=ButtonWidth,
            text=_("Export"),
            command=self._export_button_pressed,
        )
        self._export_button.grid(row=0, column=10, padx=PAD, pady=PAD, sticky="e")
        self._export_button.focus_set()

    def busy(self):
        return self._export_active

    def _disable_action_buttons(self):
        logger.info("_disable_action_buttons")
        self._refresh_button.configure(state="disabled")
        self._export_button.configure(state="disabled")
        self._select_all_button.configure(state="disabled")
        self._clear_selection_button.configure(state="disabled")
        self._cancel_export_button.configure(state="enabled")
        self._tree.configure(selectmode="none")

    def _enable_action_buttons(self):
        logger.info("_enable_action_buttons")
        self._refresh_button.configure(state="enabled")
        self._export_button.configure(state="enabled")
        self._select_all_button.configure(state="enabled")
        self._clear_selection_button.configure(state="enabled")
        self._cancel_export_button.configure(state="disabled")
        self._tree.configure(selectmode="extended")

    def _update_tree_from_images_directory(self):
        # Images Directory Sub-directory Names = Patient IDs
        # Sequentially added
        anon_pt_ids = [
            f
            for f in sorted(os.listdir(self._controller.model.images_dir()))
            if not f.startswith(".") and not (f.endswith(".pkl") or f.endswith(".csv"))
        ]
        existing_iids = set(self._tree.get_children())
        not_in_treeview = sorted(set(anon_pt_ids) - existing_iids)

        # Insert NEW data
        for anon_pt_id in not_in_treeview:
            study_count, series_count, file_count = count_studies_series_images(
                os.path.join(self._controller.model.images_dir(), anon_pt_id)
            )
            phi_name = self._controller.anonymizer.model.get_phi_name_by_anon_patient_id(anon_pt_id)
            self._tree.insert(
                "",
                0,
                iid=anon_pt_id,
                values=[
                    phi_name,
                    anon_pt_id,
                    study_count,
                    series_count,
                    file_count,
                ],
            )

        if not_in_treeview:
            logger.info(f"Added {len(not_in_treeview)} new patients to treeview")

        # Update all values (i/o intensive, TODO: could be optimised)
        for anon_pt_id in anon_pt_ids:
            study_count, series_count, file_count = count_studies_series_images(
                os.path.join(self._controller.model.images_dir(), anon_pt_id)
            )
            current_values = list(self._tree.item(anon_pt_id, "values"))
            current_values[2] = str(study_count)
            current_values[3] = str(series_count)
            current_values[4] = str(file_count)
            self._tree.item(anon_pt_id, values=current_values)

    def _tree_select(self, event):
        selected = self._tree.selection()
        # Display Last Import Error in Error Frame if selected item has error:
        if len(selected) == 1:
            item = selected[0]
            values = self._tree.item(item, "values")
            if len(values) > 7:
                error_msg = values[7]
                window_width = self.winfo_width()
                if error_msg:
                    self._error_label.configure(text=error_msg, wraplength=window_width)
                    self._error_frame.grid()
            else:
                self._error_frame.grid_remove()
        else:
            self._error_frame.grid_remove()

    def _refresh_button_pressed(self):
        if self._export_active:
            logger.error("Refresh disabled, export is active")
            return
        logger.info("Refresh button pressed, update tree from images directory...")
        # Clear tree to ensure all items are removed before re-populating:
        self._tree.delete(*self._tree.get_children())
        self._update_tree_from_images_directory()
        self._enable_action_buttons()

    def _select_all_button_pressed(self):
        if self._export_active:
            logger.error("Selection disabled, export is active")
            return
        logger.info("Select All button pressed")
        self._tree.selection_set(*self._tree.get_children())

    def _clear_selection_button_pressed(self):
        if self._export_active:
            logger.error("Selection disabled, export is active")
            return
        logger.info("Clear Selection button pressed")
        self._tree.selection_set([])

    def _update_export_progress(self, cancel: bool = False):
        self._progressbar.set(self._patients_processed / self._patients_to_process)
        state_label = _("Processing")
        entity_label = _("Patients")
        if self._patients_processed == self._patients_to_process:
            state_label = _("Processed") + " "
        msg = state_label + f" {self._patients_processed} " + _("of") + f" {self._patients_to_process} " + entity_label
        self._status.configure(text=msg)

    def _cancel_export_button_pressed(self):
        logger.info("Cancel Export button pressed")
        self._export_active = False
        self._update_export_progress(cancel=True)
        self._controller.abort_export()
        self._enable_action_buttons()

    def _monitor_export_response(self, ux_Q: Queue):
        while not ux_Q.empty():
            try:
                resp: ExportPatientsResponse = ux_Q.get_nowait()
                logger.debug(f"{resp}")

                # Update treeview item:
                current_values = list(self._tree.item(resp.patient_id, "values"))
                # Ensure there are strings in all current_values:
                while len(current_values) < len(self._attr_map):
                    current_values.append("")
                # Format the date and time as "YYYY-MM-DD HH:MM:SS"
                current_values[5] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                current_values[6] = str(resp.files_sent)
                current_values[7] = resp.error if resp.error else ""
                self._tree.item(resp.patient_id, values=current_values)
                self._tree.see(resp.patient_id)

                # Check for completion or critical error of this patient's export
                if resp.complete:
                    # if resp.files_sent == int(current_values[4]):
                    logger.debug(f"Patient {resp.patient_id} export complete")
                    self._patient_ids_to_export.remove(resp.patient_id)
                    self._tree.selection_remove(resp.patient_id)
                    self._tree.item(resp.patient_id, tags="green")
                    self._patients_processed += 1
                    self._update_export_progress()

                if resp.error:
                    self._tree.selection_remove(resp.patient_id)
                    self._tree.item(resp.patient_id, tags="red")

            except Empty:
                logger.info("Queue is empty")
            except Full:
                logger.error("Queue is full")

        # Check for completion of full export processing:
        if self._patients_processed >= self._patients_to_process:
            logger.info("All patients processed")
            self._enable_action_buttons()
            self._export_active = False
            if len(self._patient_ids_to_export) > 0:
                logger.error(f"Failed to export {len(self._patient_ids_to_export)} patients")
                if messagebox.askretrycancel(
                    title=_("Export Error"),
                    message=_("Failed to export") + f" {len(self._patient_ids_to_export)} " + _("patient(s)"),
                    parent=self,
                ):
                    # Select failed patients in treeview to retry export:
                    self._tree.selection_add(self._patient_ids_to_export)
                    self._export_button_pressed()
                    return

        else:
            # Re-trigger the export queue monitor:
            self._tree.after(
                self.ux_poll_export_response_interval,
                self._monitor_export_response,
                ux_Q,
            )

    def _enter_keypress(self, event):
        logger.info("_enter_pressed")
        self._export_button_pressed()

    def _export_button_pressed(self):
        logger.info("Export button pressed")
        if self._export_active:
            logger.error("Selection disabled, export is active")
            return

        self._error_frame.grid_remove()

        if not self._controller.model.export_to_AWS:
            # Verify echo of export DICOM server
            # TODO: remove this echo test? Rely on connection error from c-send?
            if not self._controller.echo(_("EXPORT")):
                self._export_button.configure(text_color="red")
                self._parent._send_button.configure(text_color="red")
                messagebox.showerror(
                    title=_("Connection Error"),
                    message=_("Export Server Failed DICOM C-ECHO"),
                    parent=self,
                )
                return

        self._export_button.configure(text_color="light green")
        self._parent._send_button.configure(text_color="light green")

        self._patient_ids_to_export = list(self._tree.selection())

        self._patients_to_process = len(self._patient_ids_to_export)
        if self._patients_to_process == 0:
            logger.error("No patients selected for export")
            messagebox.showerror(
                title=_("Export Error"),
                message=_("No patients selected for export.")
                + "\n\n"
                + _("Use SHIFT+Click and/or CMD/CTRL+Click to select multiple patients."),
                parent=self,
            )
            return

        self._disable_action_buttons()
        self._export_active = True
        self._patients_processed = 0
        self._progressbar.set(0)
        self._update_export_progress()

        # Create 1 UX queue to handle the full export operation
        ux_Q = Queue()

        # Export all selected patients using a background thread pool
        self._controller.export_patients_ex(
            ExportPatientsRequest(
                "AWS" if self._export_to_AWS else _("EXPORT"),
                self._patient_ids_to_export.copy(),
                ux_Q,
            )
        )

        logger.info(f"Export of {self._patients_to_process} patients initiated")

        # Trigger the queue monitor
        self._tree.after(
            self.ux_poll_export_response_interval,
            self._monitor_export_response,
            ux_Q,
        )

    def _escape_keypress(self, event):
        logger.info("_escape_pressed")
        self._on_cancel()

    def _on_cancel(self):
        logger.info("_on_cancel")
        if self._export_active:
            msg = _("Cancel active export?")
            if not messagebox.askokcancel(title=_("Cancel"), message=msg, parent=self):
                return
            else:
                self._controller.abort_export()

        self.grab_release()
        self.destroy()
