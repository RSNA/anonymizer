import logging
import string
import re
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import customtkinter as ctk
from pydicom import Dataset
from queue import Empty, Full, Queue
from controller.dicom_C_codes import C_FAILURE, C_PENDING_A, C_PENDING_B, C_SUCCESS
from controller.project import (
    FindStudyRequest,
    FindStudyResponse,
    StudyUIDHierarchy,
    ProjectController,
)
from utils.storage import count_study_images
from utils.translate import _
from utils.ux_fields import (
    accession_no_max_chars,
)  # disabled on entry to allow for list of acc nos
from utils.ux_fields import (
    dicom_date_chars,
    modality_max_chars,
    modality_min_chars,
    patient_id_max_chars,
    patient_name_max_chars,
    str_entry,
)
from view.import_studies_dialog import ImportStudiesDialog
from view.dashboard import Dashboard

logger = logging.getLogger(__name__)


# class QueryView(tk.Toplevel):
class QueryView(ctk.CTkToplevel):
    ux_poll_find_response_interval = 250  # milli-seconds

    fixed_width_font = ("Courier", 10, "bold")
    # C-FIND DICOM attributes to display in the results Treeview:
    # Key: DICOM field name, Value: (display name, centre justify)
    _attr_map = {
        "PatientName": (_("Patient Name"), 20, False),
        "PatientID": (_("Patient ID"), 15, True),
        "StudyDate": (_("Date"), 10, True),
        "StudyDescription": (_("Study Description"), 30, False),
        "AccessionNumber": (_("Accession No."), 15, True),
        "ModalitiesInStudy": (_("Modalities"), 12, True),
        "NumberOfStudyRelatedSeries": (_("Series"), 6, True),
        "NumberOfStudyRelatedInstances": (_("Images"), 6, True),
        # not dicom fields, for display only:
        "imported": (_("Imported"), 10, True),
        "error": (_("Last Import Error"), 50, False),
        # not for display, for find/move:
        "StudyInstanceUID": (_("StudyInstanceUID"), 0, False),
    }
    _tree_column_keys = list(_attr_map.keys())[:-1]
    MOVE_LEVELS = ["STUDY", "SERIES", "INSTANCE"]

    def __init__(
        self,
        parent: Dashboard,
        project_controller: ProjectController,
        title: str = _(f"Query, Retrieve & Import Studies"),
    ):
        super().__init__(master=parent)
        self._controller = project_controller
        scp_aet = project_controller.model.remote_scps["QUERY"].aet
        self.title(f"{title} from {scp_aet}")
        self._query_active = False
        self._acc_no_list: list[str] = []
        self._studies_processed = 0
        self._studies_to_process = 0
        self._study_uids_to_import = []
        self._acc_no_file_path = None
        self.width = 1300
        self.height = 400
        self.resizable(True, True)
        self.lift()
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.bind("<Return>", self._enter_keypress)
        self.bind("<Escape>", self._escape_keypress)
        self._create_widgets()
        self._enable_action_buttons()

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
        self._query_frame.grid_columnconfigure(7, weight=1)

        # Patient Name
        self._patient_name_var = str_entry(
            view=self._query_frame,
            label=_("Patient Name:"),
            initial_value="",
            min_chars=0,
            max_chars=patient_name_max_chars,
            charset=string.ascii_letters + string.digits + "- '^*?" + "À-ÖØ-öø-ÿ" + string.whitespace,
            tooltipmsg=None,  # "Alphabetic ^ spaces * ? for wildcard",
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
            label=_("Accession No.(s):"),
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
            max_chars=dicom_date_chars * 2 + 1,  # allow Date Range: YYYYMMDD-YYYYMMDD
            charset=string.digits + "-",
            tooltipmsg=None,  # _("Numeric YYYYMMDD, no wildcards for date"),
            row=1,
            col=2,
            pad=PAD,
            sticky="nw",
        )
        # Modality:
        _modality_label = ctk.CTkLabel(self._query_frame, text=_("Modality:"))
        _modality_label.grid(row=0, column=2, padx=PAD, pady=(PAD, 0), sticky="nw")
        self._modality_var = ctk.StringVar(self._query_frame)

        self._modalities_optionmenu = ctk.CTkOptionMenu(
            self._query_frame,
            width=60,
            dynamic_resizing=True,
            values=[""] + self._controller.model.modalities,
            variable=self._modality_var,
        )
        self._modalities_optionmenu.grid(row=0, column=3, padx=PAD, pady=(PAD, 0), sticky="nw")

        self._load_accession_file_button = ctk.CTkButton(
            self._query_frame,
            width=ButtonWidth,
            text=_("Load Accession Numbers"),
            command=self._load_accession_file_button_pressed,
        )
        self._load_accession_file_button.grid(row=0, column=6, padx=PAD, pady=(PAD, 0), sticky="w")

        self._show_imported_studies_switch = ctk.CTkSwitch(
            self._query_frame, text=_("Show Imported Studies")  # ,command=self._show_imported_studies_switch_pressed
        )
        self._show_imported_studies_switch.grid(row=0, column=7, padx=PAD, pady=(PAD, 0), sticky="e")

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

        # Create frame for Query results:
        self._results_frame = ctk.CTkFrame(self)
        self._results_frame.grid(row=1, column=0, padx=PAD, pady=(0, PAD), sticky="nswe")

        results_row = 0
        self._results_frame.grid_rowconfigure(results_row, weight=1)
        self._results_frame.grid_columnconfigure(7, weight=1)  # @ move_level_label

        # Managing C-FIND results Treeview:

        # Create a custom style for the Treeview
        # TODO: see if theme manager can do this and store in rsna_color_scheme_font.json
        # # if bg_color=="default":
        #     self.bg_color = self._apply_appearance_mode(customtkinter.ThemeManager.theme["CTkFrame"]["fg_color"])
        # else:
        #     self.bg_color = bg_color

        style = ttk.Style()
        style.configure("Treeview", font=self.fixed_width_font)

        self._tree = ttk.Treeview(
            self._results_frame,
            show="headings",
            style="Treeview",
            columns=self._tree_column_keys,
        )

        # Create a Vertical and Horizontal Scrollbar and associate them with the Treeview
        vertical_scrollbar = ttk.Scrollbar(self._results_frame, orient="vertical", command=self._tree.yview)
        vertical_scrollbar.grid(row=results_row, column=10, sticky="ns")
        self._tree.configure(yscrollcommand=vertical_scrollbar.set)

        # Set tree column width and justification
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
        self._tree.bind("<<TreeviewSelect>>", self._tree_select)
        self._tree.grid(row=results_row, column=0, columnspan=10, sticky="nswe")

        results_row += 1

        # TODO: Fix horizontal scrollbar dissappearing after window resize
        # horizontal_scrollbar = ttk.Scrollbar(self._results_frame, orient="horizontal", command=self._tree.xview)
        # horizontal_scrollbar.grid(row=results_row, column=0, columnspan=10, sticky="we")
        # self._tree.configure(xscrollcommand=horizontal_scrollbar.set)
        # results_row += 1

        # Progress bar and status:
        col = 0
        self._status = ctk.CTkLabel(self._results_frame, text=f"Processing 0 of 0 Studies")
        self._status.grid(row=results_row, column=col, padx=PAD, pady=0, sticky="w")

        col += 1
        self._progressbar = ctk.CTkProgressBar(self._results_frame)
        self._progressbar.grid(
            row=results_row,
            column=col,
            padx=PAD,
            pady=0,
            sticky="w",
        )
        self._progressbar.set(0)
        col += 1

        self._select_all_button = ctk.CTkButton(
            self._results_frame,
            width=ButtonWidth,
            text=_("Select All"),
            command=self._select_all_button_pressed,
        )
        self._select_all_button.grid(row=results_row, column=col, padx=PAD, pady=PAD, sticky="w")
        col += 1

        self._clear_selection_button = ctk.CTkButton(
            self._results_frame,
            width=ButtonWidth,
            text=_("Clear Selection"),
            command=self._clear_selection_button_pressed,
        )
        self._clear_selection_button.grid(row=results_row, column=col, padx=PAD, pady=PAD, sticky="w")
        col += 1

        self._studies_selected_label = ctk.CTkLabel(self._results_frame, text=_("Studies Selected: 0"))
        self._studies_selected_label.grid(row=results_row, column=col, padx=PAD, pady=PAD, sticky="w")
        col += 1

        self._move_level_label = ctk.CTkLabel(self._results_frame, text=_("Move Level:"))
        self._move_level_label.grid(row=results_row, column=7, padx=PAD, pady=PAD, sticky="e")

        self._move_level_var = ctk.StringVar(self._results_frame, value=_("STUDY"))
        move_levels_optionmenu = ctk.CTkOptionMenu(
            self._results_frame,
            width=char_width_px * len(max(self.MOVE_LEVELS, key=len)) + 40,
            dynamic_resizing=False,
            values=self.MOVE_LEVELS,
            variable=self._move_level_var,
        )
        move_levels_optionmenu.grid(row=results_row, column=8, padx=PAD, pady=PAD, sticky="e")
        move_levels_optionmenu.focus_set()

        self._import_button = ctk.CTkButton(
            self._results_frame,
            width=ButtonWidth,
            text=_("Import & Anonymize"),
            command=self._import_button_pressed,
        )
        self._import_button.grid(row=results_row, column=9, padx=PAD, pady=PAD, sticky="e")

    def busy(self):
        return self._query_active or self._controller.bulk_move_active()

    def _disable_action_buttons(self):
        logger.info(f"_disable_action_buttons")
        self._load_accession_file_button.configure(state="disabled")
        self._show_imported_studies_switch.configure(state="disabled")
        self._query_button.configure(state="disabled")
        self._select_all_button.configure(state="disabled")
        self._clear_selection_button.configure(state="disabled")
        self._import_button.configure(state="disabled")

        if self._query_active:
            self._cancel_query_button.configure(state="enabled")

        self._tree.configure(selectmode="none")

    def _enable_action_buttons(self):
        logger.info(f"_enable_action_buttons")
        self._load_accession_file_button.configure(state="enabled")
        self._show_imported_studies_switch.configure(state="enabled")
        self._query_button.configure(state="enabled")
        self._select_all_button.configure(state="enabled")
        self._clear_selection_button.configure(state="enabled")
        self._import_button.configure(state="enabled")
        self._cancel_query_button.configure(state="disabled")

        self._tree.configure(selectmode="extended")

    def _load_accession_file_button_pressed(self):
        logger.info(f"Load Accession File button pressed")
        if self._query_active:
            logger.info(f"Load Accession File disabled, query active")
            return
        self._acc_no_file_path = filedialog.askopenfilename(
            title=_("Select text or csv file with list of accession numbers to retrieve"),
            defaultextension=".txt",
            filetypes=[
                ("Text Files", "*.txt"),
                ("CSV Files", "*.csv"),
            ],
        )
        if not self._acc_no_file_path:
            logger.info(f"Load Accession File cancelled")
            return

        logger.info(f"Loading Accession Number File...")

        # Clear Accession Number entry field:
        self._accession_no_var.set("")

        try:
            with open(self._acc_no_file_path, "r") as file:
                # acc_nos_str = file.read().replace("\n", ",")
                file_content = file.read()

                # Extract accession numbers using a regular expression
                accession_numbers = re.findall(r"[\w\-_\.]+", file_content)

                # Remove leading/trailing whitespaces and convert to uppercase for consistency
                # Further processing in _query_button_pressed
                self._acc_no_list = [acc_no.strip().upper() for acc_no in accession_numbers]

        except Exception as e:
            messagebox.showerror(
                _(f"File Read Error [{type(e)}]"), _(f"Error reading Accession Number file: {e}"), parent=self
            )
            return

        self._cancel_query_button.focus_set()

        self._query_button_pressed()

    def _monitor_query_response(self, ux_Q: Queue):
        results = []

        while not ux_Q.empty():
            try:
                resp: FindStudyResponse = ux_Q.get_nowait()
                # logger.debug(f"{resp}")
                if resp.status.Status in [C_PENDING_A, C_PENDING_B, C_SUCCESS]:
                    if resp.study_result:
                        results.append(resp.study_result)
                    if resp.status.Status == C_SUCCESS:
                        self._query_active = False
                else:
                    assert resp.status.Status == C_FAILURE
                    self._query_active = False
                    logger.error(f"Query failed: {resp.status.ErrorComment}")
                    # TODO: reflect error to UX if query not aborted

                ux_Q.task_done()

            except Empty:
                logger.info("Queue is empty")
            except Full:
                logger.error("Queue is full")
            # except Exception as e:
            #     logger.error(f"Exception: {e}")

        # Display results in Treeview:
        if results:
            logger.debug(f"monitor_query_response: processing {len(results)} results")
            self._studies_processed += len(results)
            # Update the treeview with the new data
            # if processing accno list, this will remove found accession numbers from the list
            self._update_treeview_data(results)

        # Update UX label for studies found:
        self._update_query_progress()

        if not self._query_active:
            logger.info(f"Query finished, {self._studies_processed} results")
            self._query_active = False
            self._enable_action_buttons()
            if self._acc_no_list:
                logger.debug(f"- {len(self._acc_no_list)} NOT found: {self._acc_no_list}")
                # If processing accession numbers from file,
                # write any not found to file based on input file name with "_not_found" appended:
                if self._acc_no_file_path:
                    not_found_file_path = f"{self._acc_no_file_path.split('.')[0]}_not_found.txt"
                    with open(not_found_file_path, "w") as file:
                        file.write("\n".join(self._acc_no_list))

                    logger.info(
                        _(f"Accession numbers not found [{len(self._acc_no_list)}] written to: {not_found_file_path}")
                    )
                    messagebox.showwarning(
                        title=_("Accession Numbers not found"),
                        message=_(f"Accession Numbers not found were written to text file:\n {not_found_file_path}"),
                        parent=self,
                    )
            else:
                self._progressbar.stop()
                self._progressbar.configure(mode="determinate")
                self._progressbar.set(1)

            self._acc_no_file_path = None
            self._acc_no_list.clear()  # reset accession number list
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

        # TODO: remove this echo test? Rely on connection error from query?
        # OR implement using background thread to handle connection or long timeout errors
        if self._controller.echo("QUERY"):
            self._query_button.configure(text_color="light green")
        else:
            self._query_button.configure(text_color="red")
            messagebox.showerror(
                title=_("Connection Error"),
                message=_(f"Query Server Failed DICOM C-ECHO"),
                parent=self,
            )
            return

        # Handle multiple comma delimited accession numbers:
        # Entered by user or loaded from file:
        accession_no = self._accession_no_var.get().strip()
        if accession_no and "," in accession_no:
            self._acc_no_list = [x.strip() for x in self._accession_no_var.get().split(",")]
            self._modalities_optionmenu.set("")

        if self._acc_no_list:
            # Remove empty strings and keep unique values
            filtered_acc_nos = list(filter(lambda x: x != "", set(self._acc_no_list)))

            # Separate numeric and non-numeric strings
            numeric_acc_nos = [x for x in filtered_acc_nos if x.isdigit()]
            non_numeric_acc_nos = [x for x in filtered_acc_nos if not x.isdigit()]

            # Sort numeric strings in ascending order
            sorted_numeric = sorted(numeric_acc_nos, key=lambda x: int(x))

            # TODO: OPTIMIZE query using wildcard character: ? to reduce number of queries for Accession Number blocks/sequences

            # Concatenate numeric and non-numeric sorted lists
            self._acc_no_list = sorted_numeric + non_numeric_acc_nos

            self._studies_to_process = len(self._acc_no_list)
            if not messagebox.askyesno(
                _("Query via Accession Numbers"),
                _(f"Loaded {self._studies_to_process} Accession Numbers\n\nProceed with Query?"),
                parent=self,
            ):
                return
        else:
            # Prevent NULL Query:
            if not any(
                [
                    self._patient_name_var.get(),
                    self._patient_id_var.get(),
                    self._accession_no_var.get(),
                    self._study_date_var.get(),
                    self._modality_var.get(),
                ]
            ):
                logger.error(f"Query disabled, no search criteria entered")
                messagebox.showwarning(
                    title=_("Query Criteria"),
                    message=_(f"\nEnter at least one search criterion"),
                    parent=self,
                )
                return
            self._studies_to_process = -1  # unknown
            self._progressbar.configure(mode="indeterminate")
            self._progressbar.start()

        self._studies_processed = 0
        self._studies_selected_label.configure(text=f"Studies Selected: 0")

        self._query_active = True
        self._disable_action_buttons()
        self._clear_results_tree()

        ux_Q = Queue()
        req: FindStudyRequest = FindStudyRequest(
            "QUERY",
            self._patient_name_var.get(),
            self._patient_id_var.get(),
            (accession_no if self._acc_no_list == [] else self._acc_no_list),
            self._study_date_var.get(),
            self._modality_var.get(),
            ux_Q,
        )
        self._controller.find_ex(req)
        # Start FindStudyResponse monitor:
        self._tree.after(
            self.ux_poll_find_response_interval,
            self._monitor_query_response,
            ux_Q,
        )

    def _cancel_query_button_pressed(self):
        logger.info(f"Cancel Query button pressed")
        self._controller.abort_query()

    def _update_query_progress(self):
        if self._studies_to_process == -1:
            self._status.configure(text=f"Found {self._studies_processed} Studies")
        else:
            studies_to_process = self._studies_to_process
            self._progressbar.set(self._studies_processed / self._studies_to_process)
            self._status.configure(text=f"Found {self._studies_processed} of {studies_to_process} Studies")

    def _tree_select(self, event):
        # Ensure no Imported Studies are selected:
        for item in self._tree.selection():
            if self._tree.tag_has("green", item):
                self._tree.selection_remove(item)
        # Update selection count:
        self._studies_selected_label.configure(text=f"Studies Selected: {len(list(self._tree.selection()))}")

    def _clear_results_tree(self):
        self._tree.delete(*self._tree.get_children())

    def _select_all_button_pressed(self):
        self._tree.selection_set(*self._tree.get_children())
        self._studies_selected_label.configure(text=f"Studies Selected: {len(list(self._tree.selection()))}")

    def _clear_selection_button_pressed(self):
        self._tree.selection_set([])
        self._studies_selected_label.configure(text=f"Studies Selected: 0")

    def _display_import_result(self, studies: list[StudyUIDHierarchy]):
        logger.debug("_display_import_result")

        for study in studies:
            current_values = list(self._tree.item(study.uid, "values"))
            instances_to_import = study.get_number_of_instances()
            patient_id = current_values[self._tree_column_keys.index("PatientID")]

            files_imported = self._images_stored_phi_lookup(patient_id, study.uid)  # reads file system FAT
            # TODO: optimize, compare to using AnonymizerModel.get_stored_instance_count which uses in memory PHI lookup
            #       or trust study.pending_instances
            current_values[self._tree_column_keys.index("imported")] = str(files_imported)
            if study.last_error_msg:
                current_values[self._tree_column_keys.index("error")] = study.last_error_msg
            self._tree.item(study.uid, values=current_values)
            if instances_to_import > 0 and files_imported >= instances_to_import:
                self._tree.selection_remove(study.uid)
                self._tree.item(study.uid, tags="green")

    def _import_button_pressed(self):
        logger.info(f"Import button pressed")

        if self._query_active:
            logger.error(f"Import disabled, query is active")
            return

        study_uids = list(self._tree.selection())

        if len(study_uids) == 0:
            logger.info(f"No studies selected to import")
            return

        # Double check if any selected studies are already stored/imported:
        unstored_study_uids = [study_uid for study_uid in study_uids if not self._tree.tag_has("green", study_uid)]

        if len(unstored_study_uids) == 0:
            logger.info(f"All studies selected are already stored/imported")
            return

        studies: list[StudyUIDHierarchy] = []
        for study_uid in unstored_study_uids:
            patient_id = self._tree.item(study_uid, "values")[self._tree_column_keys.index("PatientID")]
            studies.append(StudyUIDHierarchy(study_uid, patient_id))

        self._studies_to_process = len(unstored_study_uids)
        self._study_uids_to_import = unstored_study_uids.copy()

        if self._studies_to_process == 0:
            logger.info(f"All studies selected are already stored/imported")
            return

        self._disable_action_buttons()

        dlg = ImportStudiesDialog(self, self._controller, studies, self._move_level_var.get())
        imported_study_hierarchies = dlg.get_input()

        self._enable_action_buttons()

        self._display_import_result(imported_study_hierarchies)

    def _images_stored_phi_lookup(self, phi_patient_id: str, phi_study_uid: str) -> int:
        anon_study_uid = self._controller.anonymizer.model.get_anon_uid(phi_study_uid)
        if not anon_study_uid:
            return 0

        anon_pt_id = self._controller.anonymizer.model.get_anon_patient_id(phi_patient_id)
        if anon_pt_id is None:
            logger.error(f"Fatal Lookup Error for anon_patient_id where phi_patient_id={phi_patient_id}")
            return 0

        # Actual file count from file system:
        return count_study_images(
            self._controller.model.images_dir(),
            anon_pt_id,
            anon_study_uid,
        )

    def _update_treeview_data(self, dicom_datasets: list[Dataset]):
        logger.debug(f"update_treeview_data items: {len(dicom_datasets)}")

        for dataset in dicom_datasets:
            # Remove found accession numbers from self._acc_no_list:
            if self._acc_no_list:
                acc_no = dataset.get("AccessionNumber", "")
                if acc_no in self._acc_no_list:
                    self._acc_no_list.remove(acc_no)

            display_values = []

            study_uid = dataset.get("StudyInstanceUID", None)
            if study_uid is None:
                logger.critical(f"Critical Internal error: Query result dataset does not have StudyInstanceUID")
                continue

            patient_id = dataset.get("PatientID", "")
            images_stored_count = self._controller.anonymizer.model.get_stored_instance_count(patient_id, study_uid)
            # Actual file count from file system:
            # self._images_stored_phi_lookup(
            #     patient_id,
            #     study_uid,
            # )

            # Note: dataset.NumberOfStudyRelatedInstances includes image counts for all modalties in study
            # not just those modalities requested & imported
            imported = False
            study_instances_from_scp = int(dataset.get("NumberOfStudyRelatedInstances", 0))
            if study_instances_from_scp and images_stored_count and images_stored_count >= study_instances_from_scp:
                imported = True
            else:
                # For multi-modality studies query the AnonymizerModel:
                imported = self._controller.anonymizer.model.study_imported(patient_id, study_uid)

            # Do not show Imported Studies if UX switch is on
            if imported and not self._show_imported_studies_switch.get():
                continue

            attr_name = self._tree_column_keys[-2]
            setattr(dataset, attr_name, images_stored_count)

            for field, (display_name, _, _) in self._attr_map.items():
                value = getattr(dataset, field, "")
                display_values.append(str(value))

            try:
                self._tree.insert(
                    "",
                    "end",
                    iid=dataset.get("StudyInstanceUID", ""),
                    values=display_values,
                )
                if imported:
                    self._tree.item(dataset.get("StudyInstanceUID", ""), tags="green")

            except Exception as e:
                logger.error(f"Exception: {e}")

        self.update_idletasks()

    def _escape_keypress(self, event):
        logger.info(f"_escape_pressed")
        self._on_cancel()

    def _on_cancel(self):
        logger.info(f"_on_cancel")

        if self._query_active and not messagebox.askokcancel(
            title=_("Cancel"), message=_("Cancel active Query?"), parent=self
        ):
            return
        else:
            self._controller.abort_query()

        self.grab_release()
        self.destroy()