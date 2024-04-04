import os
from datetime import datetime
import logging
from queue import Queue, Empty, Full
import tkinter as tk
import customtkinter as ctk
from tkinter import ttk, messagebox
from model.project import ProjectModel
from controller.project import (
    ProjectController,
    ExportStudyRequest,
    ExportStudyResponse,
)
from utils.translate import _
from utils.storage import count_studies_series_images


logger = logging.getLogger(__name__)


class ExportView(tk.Toplevel):
    # class ExportView(ctk.CTkToplevel):
    ux_poll_export_response_interval = 500  # milli-seconds

    # TODO: manage fonts using theme manager
    fixed_width_font = ("Courier", 10, "bold")

    # Export attributes to display in the results Treeview:
    # Key: column id: (column name, width, centre justify)
    _attr_map = {
        "Patient_Name": (_("Patient Name"), 10, False),
        "Anon_PatientID": (_("Anonymized ID"), 10, True),
        "Studies": (_("Studies"), 10, True),
        "Series": (_("Series"), 10, True),
        "Files": (_("Images"), 10, True),
        "DateTime": (_("Date Time"), 15, True),
        "FilesSent": (_("Images Sent"), 10, True),
    }

    def __init__(
        self,
        parent,
        project_controller: ProjectController,
        title: str = _(f"Export Studies"),
    ):
        super().__init__(master=parent)
        self._controller = project_controller
        self._project_model: ProjectModel = project_controller.model
        self._export_to_AWS = self._project_model.export_to_AWS
        if not self._export_to_AWS:
            dest = self._project_model.remote_scps["EXPORT"].aet
        else:
            dest = f"{self._project_model.aws_cognito.username}@AWS/{self._project_model.aws_cognito.s3_prefix}"

        self.title(f"{title} to {dest}")
        self._export_active = False
        self._patients_processed = 0
        self._patients_to_process = 0
        self._patient_ids_to_export = []  # dynamically as per export progress
        self.width = 1200
        self.height = 400
        # Try to move export window to right of the dashboard:
        self.geometry(f"{self.width}x{self.height}+{self.master.winfo_width()}+0")
        self.resizable(True, True)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.bind("<Return>", self._enter_keypress)
        self.bind("<Escape>", self._escape_keypress)
        self._create_widgets()
        self._enable_action_buttons()

    def _create_widgets(self):
        logger.info(f"_create_widgets")
        PAD = 10
        ButtonWidth = 100
        char_width_px = ctk.CTkFont().measure("A")
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Create frame for file treeview:
        self._export_frame = ctk.CTkFrame(self)
        self._export_frame.grid(row=1, column=0, padx=PAD, pady=(0, PAD), sticky="nswe")
        self._export_frame.grid_rowconfigure(0, weight=1)
        self._export_frame.grid_columnconfigure(3, weight=1)

        # Treeview:

        # TODO: see if theme manager can do this and stor in rsna_color_scheme_font.json
        style = ttk.Style()
        style.configure("Treeview", font=self.fixed_width_font)

        self._tree = ttk.Treeview(
            self._export_frame,
            show="headings",
            style="Treeview",
            columns=list(self._attr_map.keys()),
        )
        self._tree.grid(row=0, column=0, columnspan=11, sticky="nswe")

        # Set tree column headers, width and justification
        for col in self._tree["columns"]:
            self._tree.heading(col, text=self._attr_map[col][0])
            self._tree.column(
                col,
                width=self._attr_map[col][1] * char_width_px,
                anchor="center" if self._attr_map[col][2] else "w",
            )

        # Setup display tags:
        self._tree.tag_configure("green", background="limegreen")
        self._tree.tag_configure("red", background="red")

        # Populate treeview with existing patients
        self._update_tree_from_storage_direcctory()

        # Create a Scrollbar and associate it with the Treeview
        scrollbar = ttk.Scrollbar(self._export_frame, orient="vertical", command=self._tree.yview)
        scrollbar.grid(row=0, column=11, pady=(PAD, 0), sticky="ns")
        self._tree.configure(yscrollcommand=scrollbar.set)

        # Disable Keyboard selection bindings:
        self._tree.bind("<Left>", lambda e: "break")
        self._tree.bind("<Right>", lambda e: "break")
        self._tree.bind("<Up>", lambda e: "break")
        self._tree.bind("<Down>", lambda e: "break")

        # Progress bar and status:
        self._status = ctk.CTkLabel(self._export_frame, text=f"Processing 0 of 0 Patients")
        self._status.grid(row=1, column=0, padx=PAD, pady=0, sticky="w")

        self._progressbar = ctk.CTkProgressBar(
            self._export_frame,
        )
        self._progressbar.grid(
            row=1,
            column=1,
            padx=PAD,
            pady=0,
            sticky="w",
        )
        self._progressbar.set(0)

        self._cancel_export_button = ctk.CTkButton(
            self._export_frame,
            width=ButtonWidth,
            text=_("Cancel Export"),
            command=self._cancel_export_button_pressed,
        )
        self._cancel_export_button.grid(row=1, column=2, padx=PAD, pady=PAD, sticky="w")

        self._create_phi_button = ctk.CTkButton(
            self._export_frame,
            width=ButtonWidth,
            text=_("Create Patient Lookup"),
            command=self._create_phi_button_pressed,
        )
        self._create_phi_button.grid(row=1, column=5, padx=PAD, pady=PAD, sticky="w")

        self._refresh_button = ctk.CTkButton(
            self._export_frame,
            width=ButtonWidth,
            text=_("Refresh"),
            command=self._refresh_button_pressed,
        )
        self._refresh_button.grid(row=1, column=7, padx=PAD, pady=PAD, sticky="we")
        self._select_all_button = ctk.CTkButton(
            self._export_frame,
            width=ButtonWidth,
            text=_("Select All"),
            command=self._select_all_button_pressed,
        )
        self._select_all_button.grid(row=1, column=8, padx=PAD, pady=PAD, sticky="w")

        self._clear_selection_button = ctk.CTkButton(
            self._export_frame,
            width=ButtonWidth,
            text=_("Clear Selection"),
            command=self._clear_selection_button_pressed,
        )
        self._clear_selection_button.grid(row=1, column=9, padx=PAD, pady=PAD, sticky="w")

        self._export_button = ctk.CTkButton(
            self._export_frame,
            width=ButtonWidth,
            text=_("Export"),
            command=self._export_button_pressed,
        )
        self._export_button.grid(row=1, column=10, padx=PAD, pady=PAD, sticky="e")
        self._export_button.focus_set()

    def busy(self):
        return self._export_active

    def _disable_action_buttons(self):
        logger.info(f"_disable_action_buttons")
        self._refresh_button.configure(state="disabled")
        self._export_button.configure(state="disabled")
        self._select_all_button.configure(state="disabled")
        self._clear_selection_button.configure(state="disabled")
        self._create_phi_button.configure(state="disabled")
        self._cancel_export_button.configure(state="enabled")
        self._tree.configure(selectmode="none")

    def _enable_action_buttons(self):
        logger.info(f"_enable_action_buttons")
        self._refresh_button.configure(state="enabled")
        self._export_button.configure(state="enabled")
        self._select_all_button.configure(state="enabled")
        self._clear_selection_button.configure(state="enabled")
        if not self._tree.get_children():
            self._create_phi_button.configure(state="disabled")
        else:
            self._create_phi_button.configure(state="enabled")
        self._cancel_export_button.configure(state="disabled")
        self._tree.configure(selectmode="extended")

    def _update_tree_from_storage_direcctory(self):
        # Storage Directory Sub-directory Names = Patient IDs
        # Sequentially added
        anon_pt_ids = [
            f
            for f in sorted(os.listdir(self._controller.storage_dir))
            if not f.startswith(".") and not (f.endswith(".pkl") or f.endswith(".csv"))
        ]
        existing_iids = set(self._tree.get_children())
        not_in_treeview = sorted(set(anon_pt_ids) - existing_iids)

        # Insert NEW data
        for anon_pt_id in not_in_treeview:
            study_count, series_count, file_count = count_studies_series_images(
                os.path.join(self._controller.storage_dir, anon_pt_id)
            )
            phi_name = self._controller.anonymizer.model.get_phi_name(anon_pt_id)
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
                os.path.join(self._controller.storage_dir, anon_pt_id)
            )
            current_values = list(self._tree.item(anon_pt_id, "values"))
            current_values[2] = str(study_count)
            current_values[3] = str(series_count)
            current_values[4] = str(file_count)
            self._tree.item(anon_pt_id, values=current_values)

    def _refresh_button_pressed(self):
        if self._export_active:
            logger.error(f"Refresh disabled, export is active")
            return
        logger.info(f"Refresh button pressed, uodate tree from storage directory...")
        # Clear tree to ensure all items are removed before re-populating:
        self._tree.delete(*self._tree.get_children())
        self._update_tree_from_storage_direcctory()
        self._enable_action_buttons()

    def _select_all_button_pressed(self):
        if self._export_active:
            logger.error(f"Selection disabled, export is active")
            return
        logger.info(f"Select All button pressed")
        self._tree.selection_set(self._tree.get_children())

    def _clear_selection_button_pressed(self):
        if self._export_active:
            logger.error(f"Selection disabled, export is active")
            return
        logger.info(f"Clear Selection button pressed")
        for item in self._tree.selection():
            self._tree.selection_remove(item)

    def _create_phi_button_pressed(self):
        logger.info(f"Create PHI button pressed")
        # TODO: error handling
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
                message=f"PHI Lookup Data saved to: {csv_path}",
                parent=self,
            )

    def _update_export_progress(self, cancel: bool = False):
        if cancel:
            self._status.configure(
                text=f"Export cancelled: Processed {self._patients_processed} of {self._patients_to_process} Patients"
            )
            return
        self._progressbar.set(self._patients_processed / self._patients_to_process)
        if self._patients_processed == self._patients_to_process:
            self._status.configure(text=f"Processed {self._patients_to_process} Patients")
        else:
            self._status.configure(
                text=f"Processing {self._patients_processed} of {self._patients_to_process} Patients"
            )

    def _cancel_export_button_pressed(self):
        logger.info(f"Cancel Export button pressed")
        self._export_active = False
        self._update_export_progress(cancel=True)
        self._controller.abort_export()
        self._enable_action_buttons()

    def _monitor_export_response(self, ux_Q: Queue):
        while not ux_Q.empty():
            try:
                resp: ExportStudyResponse = ux_Q.get_nowait()
                logger.debug(f"{resp}")

                # Update treeview item:
                current_values = list(self._tree.item(resp.patient_id, "values"))
                # Ensure there are at least 7 values in the list:
                while len(current_values) < 7:
                    current_values.append("")
                # Format the date and time as "YYYY-MM-DD HH:MM:SS"
                current_values[5] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                current_values[6] = str(resp.files_sent)
                self._tree.item(resp.patient_id, values=current_values)
                self._tree.see(resp.patient_id)

                # Check for completion or critical error of this patient's export
                if resp.complete:
                    if resp.files_sent == int(current_values[4]):
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
                    message=_(f"Failed to export {len(self._patient_ids_to_export)} patient(s)"),
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
        logger.info(f"_enter_pressed")
        self._export_button_pressed()

    def _export_button_pressed(self):
        logger.info(f"Export button pressed")
        if self._export_active:
            logger.error(f"Selection disabled, export is active")
            return

        if self._controller.echo("EXPORT"):
            self._export_button.configure(text_color="light green")
        else:
            self._export_button.configure(text_color="red")
            messagebox.showerror(
                title=_("Connection Error"),
                message=_(f"Export Server Failed DICOM C-ECHO"),
                parent=self,
            )
            return

        self._patient_ids_to_export = list(self._tree.selection())

        self._patients_to_process = len(self._patient_ids_to_export)
        if self._patients_to_process == 0:
            logger.error(f"No patients selected for export")
            messagebox.showerror(
                title=_("Export Error"),
                message=_(
                    f"No patients selected for export."
                    " Use SHIFT+Click and/or CMD/CTRL+Click to select multiple patients."
                ),
                parent=self,
            )
            return

        if self._controller.echo("EXPORT"):
            self._export_button.configure(text_color="light green")
        else:
            self._export_button.configure(text_color="red")
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
            ExportStudyRequest(
                "AWS" if self._export_to_AWS else "EXPORT",
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
        logger.info(f"_escape_pressed")
        self._on_cancel()

    def _on_cancel(self):
        logger.info(f"_on_cancel")
        if self._export_active:
            msg = _("Cancel active export?")
            if not messagebox.askokcancel(title=_("Cancel"), message=msg, parent=self):
                return
            else:
                self._controller.abort_export()

        self.grab_release()
        self.destroy()
