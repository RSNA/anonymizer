import os
from datetime import datetime
import logging
from queue import Queue, Empty, Full
import customtkinter as ctk
from tkinter import ttk
from CTkMessagebox import CTkMessagebox
from model.project import ProjectModel
from controller.project import ProjectController, ExportRequest, ExportResponse
from utils.translate import _
from utils.storage import count_studies_series_images


logger = logging.getLogger(__name__)


class ExportView(ctk.CTkToplevel):
    ux_poll_export_response_interval = 500  # milli-seconds

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
        self.width = 1200
        self.height = 400
        # Try to move export window to right of the dashboard:
        self.geometry(f"{self.width}x{self.height}+{self.master.winfo_width()}+0")
        self.resizable(True, True)
        self.lift()
        self._create_widgets()
        self.bind("<Return>", self._enter_keypress)
        self.bind("<Escape>", self._escape_keypress)

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
        fixed_width_font = ("Courier", 12, "bold")  # Specify the font family and size
        # TODO: see if theme manager can do this and stor in rsna_color_scheme_font.json
        style = ttk.Style()
        style.configure("Treeview", font=fixed_width_font)

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
        scrollbar = ttk.Scrollbar(
            self._export_frame, orient="vertical", command=self._tree.yview
        )
        scrollbar.grid(row=0, column=11, pady=(PAD, 0), sticky="ns")
        self._tree.configure(yscrollcommand=scrollbar.set)

        # Disable Keyboard selection bindings:
        self._tree.bind("<Left>", lambda e: "break")
        self._tree.bind("<Right>", lambda e: "break")
        self._tree.bind("<Up>", lambda e: "break")
        self._tree.bind("<Down>", lambda e: "break")

        # Progress bar and status:
        self._status = ctk.CTkLabel(
            self._export_frame, text=f"Processing 0 of 0 Patients"
        )
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
        self._clear_selection_button.grid(
            row=1, column=9, padx=PAD, pady=PAD, sticky="w"
        )

        self._export_button = ctk.CTkButton(
            self._export_frame,
            width=ButtonWidth,
            text=_("Export"),
            # state=ctk.DISABLED,
            command=self._export_button_pressed,
        )
        self._export_button.grid(row=1, column=10, padx=PAD, pady=PAD, sticky="e")
        self._export_button.focus_set()

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
            logger.error(f"Selection disabled, export is active")
            return
        logger.info(f"Refresh button pressed, uodate tree from storage directory...")
        # Clear tree to ensure all items are removed before re-populating:
        self._tree.delete(*self._tree.get_children())
        self._update_tree_from_storage_direcctory()

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
            CTkMessagebox(
                master=self,
                title=_("Error Creating PHI CSV File"),
                message=csv_path,
                icon="cancel",
                sound=True,
            )
            return
        else:
            logger.info(f"PHI CSV file created: {csv_path}")
            CTkMessagebox(
                master=self,
                title=_("PHI CSV File Created"),
                message=f"PHI Lookup Data saved to: {csv_path}",
                icon="info",
                sound=True,
            )

    def _update_export_progress(self):
        self._progressbar.set(self._patients_processed / self._patients_to_process)
        if self._patients_processed == self._patients_to_process:
            self._status.configure(
                text=f"Processed {self._patients_to_process} Patients"
            )
        else:
            self._status.configure(
                text=f"Processing {self._patients_processed} of {self._patients_to_process} Patients"
            )

    def _cancel_export_button_pressed(self):
        logger.info(f"Cancel Export button pressed")
        if not self._export_active:
            logger.error(f"Export is not active")
            return
        self._controller.abort_export()

    def _monitor_export_queue(self, ux_Q: Queue):
        while not ux_Q.empty():
            try:
                resp: ExportResponse = ux_Q.get_nowait()
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
                    logger.debug(f"Patient {resp.patient_id} export complete")
                    # remove selection highlight to indicate export of this item/patient is finished
                    self._tree.selection_remove(resp.patient_id)
                    if resp.files_sent == int(current_values[4]):
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

        # Unselect
        # Check for completion of full export:
        if self._patients_processed >= self._patients_to_process:
            logger.info("All patients exported")
            self._export_active = False
            # self._export_button.configure(state=ctk.NORMAL)
            # self._select_all_button.configure(state=ctk.NORMAL)
            # re-enable tree interaction now export is complete
            self._tree.configure(selectmode="extended")
            return

        self._tree.after(
            self.ux_poll_export_response_interval,
            self._monitor_export_queue,
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

        sel_patient_ids = list(self._tree.selection())

        self._patients_to_process = len(sel_patient_ids)
        if self._patients_to_process == 0:
            logger.error(f"No patients selected for export")
            return

        if self._controller.echo("EXPORT"):
            self._export_button.configure(text_color="light green")
        else:
            self._export_button.configure(text_color="red")
            return

        self._export_active = True

        # Create 1 UX queue to handle the full export operation
        ux_Q = Queue()

        # Export all selected patients using a background thread pool
        self._controller.export_patients(
            ExportRequest(
                "AWS" if self._export_to_AWS else "EXPORT",
                sel_patient_ids,
                ux_Q,
            )
        )

        logger.info(f"Export of {self._patients_to_process} patients initiated")
        self._patients_processed = 0
        self._progressbar.set(0)
        # disable tree interaction during export
        self._tree.configure(selectmode="none")
        # disable select_all and export buttons while export is in progress
        # self._export_button.configure(state=ctk.DISABLED)
        # self._select_all_button.configure(state=ctk.DISABLED)

        # Trigger the queue monitor
        self._tree.after(
            self.ux_poll_export_response_interval,
            self._monitor_export_queue,
            ux_Q,
        )

    def _escape_keypress(self, event):
        logger.info(f"_escape_pressed")
        self._on_cancel()

    def _on_cancel(self):
        logger.info(f"_on_cancel")
        if self._export_active:
            logger.info(f"Cancel disabled, export active")
            return

        self.grab_release()
        self.destroy()
