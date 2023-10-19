import logging
import string
from queue import Queue, Empty, Full
from tkinter import Tk, filedialog
from turtle import st
import customtkinter as ctk
from CTkMessagebox import CTkMessagebox
from pydicom import Dataset
import pandas as pd
import tkinter as tk
from tkinter import ttk
from controller.dicom_C_codes import C_PENDING_A, C_PENDING_B, C_SUCCESS, C_FAILURE
from utils.translate import _
from utils.storage import images_stored
from utils.ux_fields import (
    str_entry,
    patient_name_max_chars,
    patient_id_max_chars,
    accession_no_max_chars,
    dicom_date_chars,
    modality_max_chars,
    modality_min_chars,
)

from controller.project import (
    ProjectController,
    FindRequest,
    FindResponse,
    MoveRequest,
)

logger = logging.getLogger(__name__)


class QueryView(ctk.CTkToplevel):
    ux_poll_find_response_interval = 250  # milli-seconds
    ux_poll_move_response_interval = 500  # milli-seconds

    # C-FIND DICOM attributes to display in the results Treeview:
    # Key: DICOM field name, Value: (display name, centre justify)
    _attr_map = {
        "PatientName": (_("Patient Name"), 20, False),
        "PatientID": (_("Patient ID"), 15, True),
        "StudyDate": (_("Date"), 10, True),
        "StudyDescription": (_("Study Description"), 30, False),
        "AccessionNumber": (_("Accession No."), 15, True),
        "ModalitiesInStudy": (_("Modalities"), 9, True),
        "NumberOfStudyRelatedSeries": (_("Series"), 6, True),
        "NumberOfStudyRelatedInstances": (_("Images"), 6, True),
        "NumberOfCompletedSuboperations": (_("Stored"), 10, True),
        "NumberOfFailedSuboperations": (_("Errors"), 10, True),
        # not for display, for find/move:
        "StudyInstanceUID": (_("StudyInstanceUID"), 0, False),
    }

    def __init__(
        self,
        parent,
        project_controller: ProjectController,
        title: str = _(f"Query, Retrieve & Import Studies"),
    ):
        super().__init__(master=parent)
        self._controller = project_controller
        scp_aet = project_controller.model.remote_scps["QUERY"].aet
        self.title(f"{title} from {scp_aet}")
        self._query_active = False
        self._move_active = False
        self._acc_no_list = []
        self._studies_processed = 0
        self._studies_to_process = 0
        self._acc_no_file_path = None
        self.width = 1200
        self.height = 400
        # Try to move query window below the dashboard:
        self.geometry(f"{self.width}x{self.height}+0+{self.master.winfo_height()+60}")
        self.resizable(True, True)
        self.lift()
        self.bind("<Return>", self._enter_keypress)
        self.bind("<Escape>", self._escape_keypress)
        self._create_widgets()

    def _create_widgets(self):
        logger.info(f"_create_widgets")
        PAD = 10
        ButtonWidth = 100

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
        char_width_px = ctk.CTkFont().measure("A")

        # QUERY PARAMETERS:
        # Create frame for Query Input:
        self._query_frame = ctk.CTkFrame(self)
        self._query_frame.grid(row=0, column=0, padx=PAD, pady=PAD, sticky="nswe")
        # self._query_frame.grid_columnconfigure(7, weight=1)
        self._query_frame.focus_set()

        # Patient Name
        self._patient_name_var = str_entry(
            view=self._query_frame,
            label=_("Patient Name:"),
            initial_value="",
            min_chars=0,
            max_chars=patient_name_max_chars,
            charset=string.ascii_letters
            + string.digits
            + "- '^*?"
            + "À-ÖØ-öø-ÿ"
            + string.whitespace,
            tooltipmsg=None,  # "Alphabetic ^ spaces * for wildcard",
            row=0,
            col=0,
            pad=PAD,
            sticky="nw",
        )
        # Patient ID
        self._patient_id_var = ctk.StringVar(self)
        self._patient_id_var = str_entry(
            self._query_frame,
            label=_("Patient ID:"),
            initial_value="",
            min_chars=0,
            max_chars=patient_id_max_chars,
            charset=string.ascii_letters + string.digits + "*?",
            tooltipmsg=None,  # "Alpha-numeric, * or ? for wildcard",
            row=1,
            col=0,
            pad=PAD,
            sticky="nw",
        )
        # Accession No.
        self._accession_no_var = str_entry(
            view=self._query_frame,
            label=_("Accession No.:"),
            initial_value="",
            min_chars=0,
            max_chars=None,
            charset=string.ascii_letters + string.digits + " *?/-_,.",
            tooltipmsg=None,  # "Alpha-numeric, * or ? for wildcard",
            row=0,
            col=4,
            pad=PAD,
            sticky="nw",
        )
        # Study Date:
        self._study_date_var = str_entry(
            view=self._query_frame,
            label=_("Study Date:"),
            initial_value="",
            min_chars=dicom_date_chars,
            max_chars=dicom_date_chars,
            charset=string.digits + "*",
            tooltipmsg=None,  # _("Numeric YYYYMMDD, * or ? for wildcard"),
            row=1,
            col=2,
            pad=PAD,
            sticky="nw",
        )
        # Modality:
        self._modality_var = str_entry(
            view=self._query_frame,
            label=_("Modality:"),
            initial_value="",
            min_chars=modality_min_chars,
            max_chars=modality_max_chars,
            charset=string.ascii_uppercase,
            tooltipmsg=None,  # _("Modality Code"),
            row=0,
            col=2,
            pad=PAD,
            sticky="nw",
        )

        self._load_accession_file_button = ctk.CTkButton(
            self._query_frame,
            width=ButtonWidth,
            text=_("Load Accession Numbers"),
            command=self._load_accession_file_button_pressed,
        )
        self._load_accession_file_button.grid(
            row=0, column=6, padx=PAD, pady=(PAD, 0), sticky="w"
        )

        self._query_button = ctk.CTkButton(
            self._query_frame,
            width=ButtonWidth,
            text=_("Query"),
            command=self._query_button_pressed,
        )
        self._query_button.grid(row=1, column=4, padx=PAD, pady=PAD, sticky="e")

        self._cancel_query_button = ctk.CTkButton(
            self._query_frame,
            width=ButtonWidth,
            text=_("Cancel Query"),
            command=self._cancel_query_button_pressed,
        )
        self._cancel_query_button.grid(row=1, column=5, padx=PAD, pady=PAD, sticky="w")

        self._studies_found_label = ctk.CTkLabel(
            self._query_frame, text=_("Studies Found: 0")
        )
        self._studies_found_label.grid(row=1, column=6, padx=PAD, pady=PAD, sticky="w")

        # Create frame for Query results:
        self._results_frame = ctk.CTkFrame(self)
        self._results_frame.grid(
            row=1, column=0, padx=PAD, pady=(0, PAD), sticky="nswe"
        )
        self._results_frame.grid_rowconfigure(0, weight=1)
        self._results_frame.grid_columnconfigure(7, weight=1)

        # Managing C-FIND results Treeview:
        fixed_width_font = ("Courier", 12, "bold")
        # Create a custom style for the Treeview
        # TODO: see if theme manager can do this and store in rsna_color_scheme_font.json
        # # if bg_color=="default":
        #     self.bg_color = self._apply_appearance_mode(customtkinter.ThemeManager.theme["CTkFrame"]["fg_color"])
        # else:
        #     self.bg_color = bg_color

        style = ttk.Style()
        style.configure("Treeview", font=fixed_width_font)

        self._tree = ttk.Treeview(
            self._results_frame,
            show="headings",
            style="Treeview",
            columns=list(self._attr_map.keys())[:-1],
        )
        self._tree.grid(row=0, column=0, columnspan=10, sticky="nswe")

        # Create a Scrollbar and associate it with the Treeview
        scrollbar = ttk.Scrollbar(
            self._results_frame, orient="vertical", command=self._tree.yview
        )
        scrollbar.grid(row=0, column=10, padx=(0, PAD), sticky="news")
        self._tree.configure(yscrollcommand=scrollbar.set)

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

        # Disable Keyboard selection bindings:
        self._tree.bind("<Left>", lambda e: "break")
        self._tree.bind("<Right>", lambda e: "break")
        self._tree.bind("<Up>", lambda e: "break")
        self._tree.bind("<Down>", lambda e: "break")

        # Progress bar and status:
        self._status = ctk.CTkLabel(
            self._results_frame, text=f"Processing 0 of 0 Studies"
        )
        self._status.grid(row=1, column=0, padx=PAD, pady=0, sticky="w")

        self._progressbar = ctk.CTkProgressBar(self._results_frame)
        self._progressbar.grid(
            row=1,
            column=1,
            padx=PAD,
            pady=0,
            sticky="w",
        )
        self._progressbar.set(0)

        self._cancel_import_button = ctk.CTkButton(
            self._results_frame,
            width=ButtonWidth,
            text=_("Cancel Import"),
            command=self._cancel_import_button_pressed,
        )
        self._cancel_import_button.grid(row=1, column=2, padx=PAD, pady=PAD, sticky="w")

        self._select_all_button = ctk.CTkButton(
            self._results_frame,
            width=ButtonWidth,
            text=_("Select All"),
            command=self._select_all_button_pressed,
        )
        self._select_all_button.grid(row=1, column=5, padx=PAD, pady=PAD, sticky="w")

        self._clear_selection_button = ctk.CTkButton(
            self._results_frame,
            width=ButtonWidth,
            text=_("Clear Selection"),
            command=self._clear_selection_button_pressed,
        )
        self._clear_selection_button.grid(
            row=1, column=6, padx=PAD, pady=PAD, sticky="w"
        )

        self._retrieve_button = ctk.CTkButton(
            self._results_frame,
            width=ButtonWidth,
            text=_("Import & Anonymize"),
            command=self._retrieve_button_pressed,
        )
        self._retrieve_button.grid(row=1, column=7, padx=PAD, pady=PAD, sticky="e")

    def _disable_action_buttons(self):
        logger.info(f"_disable_action_buttons")
        self._load_accession_file_button.configure(state="disabled")
        self._query_button.configure(state="disabled")
        self._select_all_button.configure(state="disabled")
        self._clear_selection_button.configure(state="disabled")
        self._retrieve_button.configure(state="disabled")

        self._cancel_import_button.configure(state="enabled")
        self._cancel_query_button.configure(state="enabled")

        self._tree.configure(selectmode="none")

    def _enable_action_buttons(self):
        logger.info(f"_enable_action_buttons")
        self._load_accession_file_button.configure(state="enabled")
        self._query_button.configure(state="enabled")
        self._select_all_button.configure(state="enabled")
        self._clear_selection_button.configure(state="enabled")
        self._retrieve_button.configure(state="enabled")

        self._cancel_import_button.configure(state="disabled")
        self._cancel_query_button.configure(state="disabled")

        self._tree.configure(selectmode="extended")

    def _load_accession_file_button_pressed(self):
        logger.info(f"Load Accession File button pressed")
        if self._query_active or self._move_active:
            logger.info(f"Load Accession File disabled, query or move active")
            return
        self._acc_no_file_path = filedialog.askopenfilename(
            title=_(
                "Select text or csv file with list of accession numbers to retrieve"
            ),
            defaultextension=".txt",
            filetypes=[
                ("Text Files", "*.txt"),
                ("CSV Files", "*.csv"),
            ],
        )
        if not self._acc_no_file_path:
            logger.info(f"Load Accession File cancelled")
            return

        logger.info(f"Load Accession File")
        # Clear Accession Number entry field:
        self._accession_no_var.set("")
        # Read accession numbers from file:
        with open(self._acc_no_file_path, "r") as file:
            acc_nos_str = file.read().replace("\n", ",")

        self._acc_no_list = sorted(set(acc_nos_str.split(",")))  # remove duplicates

        # Trigger the query:
        # TODO: optimize query using wildcards * and ? to reduce number of queries for blocks/sequences
        self._query_button_pressed()

    def _monitor_query_response(self, ux_Q: Queue):
        results = []
        query_finished = False
        while not ux_Q.empty():
            try:
                resp: FindResponse = ux_Q.get_nowait()
                logger.debug(f"{resp}")
                if resp.status.Status in [C_PENDING_A, C_PENDING_B, C_SUCCESS]:
                    if resp.identifier:
                        results.append(resp.identifier)
                    if resp.status.Status == C_SUCCESS:
                        query_finished = True
                else:
                    assert resp.status.Status == C_FAILURE
                    query_finished = True
                    logger.error(f"Query failed: {resp.status.ErrorComment}")
                    if self._query_active:  # not aborted
                        CTkMessagebox(
                            master=self,
                            message=_(
                                f"Query Remote Server Error: {resp.status.ErrorComment}"
                            ),
                            icon="cancel",
                            header=True,
                        )

                ux_Q.task_done()

            except Empty:
                logger.info("Queue is empty")
            except Full:
                logger.error("Queue is full")

        # Create Pandas DataFrame from results and display in Treeview:
        if results:
            logger.info(f"monitor_query_response: processing {len(results)} results")
            self._studies_processed += len(results)
            # List the DICOM attributes in the desired order using the keys from the mapping
            ordered_attrs = list(self._attr_map.keys())
            data_dicts = [
                {
                    self._attr_map[attr][0]: getattr(ds, attr, None)
                    for attr in ordered_attrs
                    if hasattr(ds, attr)
                }
                for ds in results
            ]
            df = pd.DataFrame(data_dicts)

            # Update the treeview with the new data
            # if processing accno list, this will remove found accession numbers from the list
            self._update_treeview_data(df)

        # Update UX label for studies found:
        self._update_query_progress()
        self._studies_found_label.configure(
            text=f"Studies Found: {self._studies_processed}"
        )

        if query_finished:
            logger.info(f"Query finished, {self._studies_processed} results")
            self._query_active = False
            self._enable_action_buttons()
            if self._acc_no_list:
                logger.info(
                    f"- {len(self._acc_no_list)} NOT found: {self._acc_no_list}"
                )
                # If processing accession numbers from file,
                # write any not found to file based on input file name with "_not_found" appended:
                if self._acc_no_file_path:
                    not_found_file_path = (
                        f"{self._acc_no_file_path.split('.')[0]}_not_found.txt"
                    )
                    with open(not_found_file_path, "w") as file:
                        file.write("\n".join(self._acc_no_list))

                    logger.info(
                        _(
                            f"Accession numbers not found written to: {not_found_file_path}"
                        )
                    )

                    # TODO: investigate errors (hanging and blank box) when using standard form of CTkMessagebox
                    CTkMessagebox(
                        master=self,
                        message=_(
                            f"Accession Numbers not found were written to: {not_found_file_path}"
                        ),
                        icon="info",
                        header=True,
                    )

            self._acc_no_file_path = None
            self._acc_no_list = []  # reset accession number list
        else:
            # Re-trigger monitor_query_response callback:
            self.after(
                self.ux_poll_find_response_interval,
                self._monitor_query_response,
                ux_Q,
            )

    def _enter_keypress(self, event):
        logger.info(f"_enter_pressed")
        self._query_button_pressed()

    def _query_button_pressed(self):
        logger.info(f"Query button pressed")

        if self._query_active:
            logger.error(f"Query disabled, query is active")
            return
        if self._move_active:
            logger.error(f"Query disabled, move is active")
            return

        if self._controller.echo("QUERY"):
            self._query_button.configure(text_color="light green")
        else:
            self._query_button.configure(text_color="red")
            return

        self._query_active = True
        self._disable_action_buttons()
        self._clear_results_tree()

        # Handle multiple comma delimited accession numbers:
        # Entered by user or loaded from file:
        if self._accession_no_var.get() and "," in self._accession_no_var.get():
            self._acc_no_list = self._accession_no_var.get().split(",")

        if self._acc_no_list:
            # Remove null strings and keep unique values
            filtered_acc_nos = list(filter(None, set(self._acc_no_list)))

            # Separate numeric and non-numeric strings
            numeric_acc_nos = [x for x in filtered_acc_nos if x.isdigit()]
            non_numeric_acc_nos = [x for x in filtered_acc_nos if not x.isdigit()]

            # Sort numeric strings in ascending order
            sorted_numeric = sorted(numeric_acc_nos, key=lambda x: int(x))

            # Concatenate numeric and non-numeric sorted lists
            self._acc_no_list = sorted_numeric + non_numeric_acc_nos

            self._studies_to_process = len(self._acc_no_list)
        else:
            self._studies_to_process = -1  # unknown

        self._studies_processed = 0

        ux_Q = Queue()
        req: FindRequest = FindRequest(
            "QUERY",
            self._patient_name_var.get(),
            self._patient_id_var.get(),
            self._accession_no_var.get()
            if not self._acc_no_list
            else self._acc_no_list,
            self._study_date_var.get(),
            self._modality_var.get(),
            ux_Q,
        )
        self._controller.find_ex(req)
        # Start FindResponse monitor:
        self._tree.after(
            self.ux_poll_find_response_interval,
            self._monitor_query_response,
            ux_Q,
        )

    def _cancel_query_button_pressed(self):
        logger.info(f"Cancel Query button pressed")
        self._query_active = False
        self._enable_action_buttons()
        # self._update_query_progress(cancel=True)
        self._controller.abort_query()

    def _update_query_progress(self, cancel=False):
        if self._studies_to_process == -1:
            studies_to_process = "Unknown"
        else:
            studies_to_process = self._studies_to_process
            self._progressbar.set(self._studies_processed / self._studies_to_process)
        if cancel:
            self._status.configure(
                text=f"Query cancelled: Found {self._studies_processed} of {studies_to_process}"
            )
            return
        self._status.configure(
            text=f"Found {self._studies_processed} of {studies_to_process} Studies"
        )

    def _clear_results_tree(self):
        self._tree.delete(*self._tree.get_children())

    def _select_all_button_pressed(self):
        if self._move_active:
            logger.error(f"Selection disabled, move is active")
            return
        # self._tree.selection_set(self._tree.get_children())
        for item in self._tree.get_children():
            if not self._tree.tag_has("green", item):
                self._tree.selection_add(item)

    def _clear_selection_button_pressed(self):
        if self._move_active:
            logger.error(f"Selection disabled, move is active")
            return
        for item in self._tree.selection():
            self._tree.selection_remove(item)

    def _cancel_import_button_pressed(self):
        logger.info(f"Cancel Import button pressed")
        self._move_active = False
        self._update_move_progress(cancel=True)
        self._enable_action_buttons()
        self._controller.abort_move()

    def _update_move_progress(self, cancel=False):
        if cancel:
            self._status.configure(
                text=f"Import cancelled: Processed {self._studies_processed} of {self._studies_to_process} Studies Selected"
            )
            return
        self._progressbar.set(self._studies_processed / self._studies_to_process)
        if self._studies_processed == self._studies_to_process:
            self._status.configure(
                text=f"Processed {self._studies_to_process} of {self._studies_to_process} Studies Selected"
            )
        else:
            self._status.configure(
                text=f"Processing {self._studies_processed} of {self._studies_to_process} Studies Selected"
            )

    def _monitor_move_response(self, ux_Q: Queue):
        while not ux_Q.empty():
            try:
                # TODO: do this in batches
                resp: Dataset = ux_Q.get_nowait()
                logger.debug(f"{resp}")

                # Terminate move operation if an incomplete response is received:
                if not hasattr(resp, "StudyInstanceUID"):
                    logger.error(
                        f"Fatal Move Error detected, exit monitor_move_response"
                    )
                    self._move_active = False
                    CTkMessagebox(
                        master=self,
                        message=f"Terminate move operation, fatal error detected: {resp}",
                        icon="cancel",
                        header=True,
                    )
                    return

                # If one file failed to moved, mark the study as red:
                # TODO: hover over item to see error message
                current_values = list(self._tree.item(resp.StudyInstanceUID, "values"))
                # Ensure there are at least 10 values in the list:
                while len(current_values) < 10:
                    current_values.append("")

                self._tree.see(resp.StudyInstanceUID)

                if resp.Status == C_FAILURE:
                    self._tree.selection_remove(resp.StudyInstanceUID)
                    self._tree.item(resp.StudyInstanceUID, tags="red")
                    self._studies_processed += 1
                    if current_values[9] == "":
                        current_values[9] = "0"
                    current_values[9] = str(int(current_values[9]) + 1)
                    self._tree.item(resp.StudyInstanceUID, values=current_values)
                    self._update_move_progress()
                    # TOOD: add last error message to treeview
                else:
                    current_values[8] = str(resp.NumberOfCompletedSuboperations)
                    current_values[9] = str(resp.NumberOfFailedSuboperations)
                    self._tree.item(resp.StudyInstanceUID, values=current_values)

                    if resp.Status == C_SUCCESS:
                        self._tree.selection_remove(resp.StudyInstanceUID)
                        if resp.NumberOfFailedSuboperations == 0:
                            # TODO: #8 ensure all images of study have been stored by anonymizer worker
                            # StudyInstanceUID in uid_lookup and files in storage_dir
                            # need to wait for anonymizer worker to finish processing this study
                            self._tree.item(resp.StudyInstanceUID, tags="green")

                        self._studies_processed += 1
                        self._update_move_progress()

                if self._studies_processed >= self._studies_to_process:
                    logger.info(f"Full Move operation finished")
                    self._move_active = False
                    self._enable_action_buttons()
                    return

            except Empty:
                logger.info("Queue is empty")
            except Full:
                logger.error("Queue is full")

        # Re-trigger monitor callback:
        self._tree.after(
            self.ux_poll_move_response_interval,
            self._monitor_move_response,
            ux_Q,
        )

    def _retrieve_button_pressed(self):
        logger.debug(f"Retrieve button pressed")

        if self._query_active:
            logger.error(f"Retrieve disabled, query is active")
            return
        if self._move_active:
            logger.error(f"Retrieve disabled, move is active")
            return

        study_uids = list(self._tree.selection())

        if len(study_uids) == 0:
            logger.info(f"No studies selected to import")
            return

        # Create 1 UX queue to handle the full move / retrieve operation
        ux_Q = Queue()

        unstored_study_uids = [
            study_uid
            for study_uid in study_uids
            # if self._controller.anonymizer.model.get_anon_uid(study_uid) is None
            if not self._tree.tag_has("green", study_uid)
        ]

        self._studies_to_process = len(unstored_study_uids)

        if self._studies_to_process == 0:
            logger.info(f"All studies selected are already stored/imported")
            return

        self._move_active = True
        self._disable_action_buttons()

        self._studies_processed = 0
        logger.info(f"Retrieving {self._studies_to_process} Study(s)")
        logger.debug(f"StudyInstanceUIDs: {study_uids}")

        req = MoveRequest(
            "QUERY",
            self._controller.model.scu.aet,
            unstored_study_uids,
            ux_Q,
        )
        self._controller.move_studies(req)

        # Start MoveResponse monitor:
        self.after(
            self.ux_poll_move_response_interval,
            self._monitor_move_response,
            ux_Q,
        )

    def _update_treeview_data(self, data: pd.DataFrame):
        # Insert new data
        logger.info(f"update_treeview_data items: {len(data)}")
        for _, row in data.iterrows():
            # Remove found accession numbers from self._acc_no_list:
            if self._acc_no_list:
                acc_no = row["Accession No."]
                if acc_no in self._acc_no_list:
                    self._acc_no_list.remove(acc_no)

            display_values = [
                val for col, val in row.items() if col != "StudyInstanceUID"
            ]

            # If the StudyInstanceUID is already in the uid_lookup / been stored
            # determine how many images have been stored:
            anon_study_uid = self._controller.anonymizer.model.get_anon_uid(
                row["StudyInstanceUID"]
            )
            images_stored_count = 0
            if anon_study_uid:
                anon_pt_id = self._controller.anonymizer.model.get_anon_patient_id(
                    row["Patient ID"]
                )
                anon_acc_no = self._controller.anonymizer.model.get_anon_acc_no(
                    row["Accession No."]
                )
                if anon_pt_id and anon_acc_no:
                    images_stored_count = images_stored(
                        self._controller.storage_dir,
                        anon_pt_id,
                        anon_study_uid,
                        anon_acc_no,
                    )
                    display_values.append(str(images_stored_count))

            try:
                self._tree.insert(
                    "", "end", iid=row["StudyInstanceUID"], values=display_values
                )
                if images_stored_count == row["Images"]:
                    self._tree.item(row["StudyInstanceUID"], tags="green")
            except Exception as e:
                logger.error(
                    f"Exception: {e}"
                )  # _tkinter.TclError: Item {iid} already exists

    def _escape_keypress(self, event):
        logger.info(f"_escape_pressed")
        self._on_cancel()

    def _on_cancel(self):
        logger.info(f"_on_cancel")
        if self._query_active or self._move_active:
            logger.info(f"Cancel disabled, query or move active")
            return

        self.grab_release()
        self.destroy()
