from typing import List, Union
import tkinter as tk
import customtkinter as ctk
import logging
from utils.translate import _
from controller.project import ProjectController, MoveStudiesRequest, StudyUIDHierarchy

logger = logging.getLogger(__name__)


class ImportStudiesDialog(tk.Toplevel):
    # class ImportStudiesDialog(ctk.CTkToplevel):
    update_interval = 300  # milliseconds

    def __init__(
        self,
        parent,
        controller: ProjectController,
        study_uids: List[str],
        scp_name: str = "QUERY",
        title: str = _("Importing Studies"),
    ):
        super().__init__(master=parent)

        self.title(f"{title} from {controller.model.remote_scps[scp_name].aet}")
        self.attributes("-topmost", True)  # stay on top
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.grab_set()  # make dialog modal
        self.resizable(False, False)
        self._controller = controller
        # Create StudyUIDHierarchy List from study_uids:
        self._studies = [StudyUIDHierarchy(uid) for uid in study_uids]
        self._instances_to_import = 0
        self.imported = 0
        self._scp_name = scp_name
        self.width = 400
        self.height = 400
        self.rowconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
        self._create_widgets()
        self.bind("<Escape>", self._escape_keypress)
        # Phase 1: Start background task to get StudyUIDHierarchies:
        self._controller.get_study_uid_hierarchies_ex(scp_name, self._studies)
        self._update_progress_get_hierarchies()

    def _create_widgets(self):
        logger.info(f"_create_widgets")
        PAD = 10

        self._metadata_status_label = ctk.CTkLabel(self, text=_("Retrieving Study Metadata..."))
        self._metadata_status_label.grid(row=0, column=0, padx=PAD, pady=PAD, sticky="w")

        self._metadata_progress_bar = ctk.CTkProgressBar(self)
        self._metadata_progress_bar.grid(
            row=1,
            column=0,
            padx=(PAD, 2 * PAD),
            pady=(PAD, 0),
            sticky="ew",
        )

        self._metadata_progress_bar.set(0)
        self._metadata_progress_label = ctk.CTkLabel(self, text="")
        self._metadata_progress_label.grid(row=2, column=0, padx=PAD, pady=(0, PAD), sticky="w")

        self._import_status_label = ctk.CTkLabel(self, text=_(""))
        self._import_status_label.grid(row=3, column=0, padx=PAD, pady=PAD, sticky="w")

        self._import_progress_bar = ctk.CTkProgressBar(self)
        self._import_progress_bar.grid(
            row=4,
            column=0,
            padx=(PAD, 2 * PAD),
            pady=(PAD, 0),
            sticky="ew",
        )

        self._import_progress_bar.set(0)
        self._import_progress_label = ctk.CTkLabel(self, text="")
        self._import_progress_label.grid(row=5, column=0, padx=PAD, pady=(0, PAD), sticky="w")

        self._cancel_button = ctk.CTkButton(self, width=100, text=_("Cancel"), command=self._on_cancel)
        self._cancel_button.grid(
            row=6,
            column=0,
            padx=PAD,
            pady=(0, PAD),
            sticky="e",
        )

    def _update_progress_get_hierarchies(self):

        if len(self._studies) == 0:
            self._metadata_progress_label.configure(text=_("No studies to retrieve"))
            self._cancel_button.configure(text=_("Close"))
            return

        errors = sum(1 for study in self._studies if study.last_error_msg)
        meta_retrieved = sum(1 for study in self._studies if study.series)
        pending_studies = len(self._studies) - errors - meta_retrieved

        self._metadata_progress_bar.set(meta_retrieved + errors / len(self._studies))
        self._metadata_progress_label.configure(text=f"{meta_retrieved+errors} of {len(self._studies)}")

        if pending_studies > 0:
            self.after(self.update_interval, self._update_progress_get_hierarchies)
        else:
            if meta_retrieved == 0:  # All studies have errors
                self._metadata_status_label.configure(text=_("Error retrieving ANY Study Metadata"))
                self._cancel_button.configure(text=_("Close"))
            else:
                # Start Phase 2: Move studies:
                self._metadata_status_label.configure(text=_("Finished retrieving Study Metadata"))
                self._instances_to_import = sum([study.get_number_of_instances() for study in self._studies])
                self._import_status_label.configure(text=_(f"Importing {meta_retrieved} Studies..."))
                self._import_progress_label.configure(text=f"0 of {self._instances_to_import} Images")
                mr: MoveStudiesRequest = MoveStudiesRequest(
                    self._scp_name, self._controller.model.scu.aet, "SERIES", self._studies
                )
                self._controller.move_studies(mr)
                self.after(self.update_interval, self._update_progress_move_studies)

    def _update_progress_move_studies(self):
        pending_instances = sum([study.get_number_of_pending_instances() for study in self._studies])
        self.imported = self._instances_to_import - pending_instances
        self._import_progress_bar.set(self.imported / self._instances_to_import)
        self._import_progress_label.configure(text=f"{self.imported} of {self._instances_to_import}")
        if self._controller.bulk_move_active():
            self.after(self.update_interval, self._update_progress_move_studies)
        else:
            self._import_status_label.configure(text=_("Import Finished"))
            self._cancel_button.configure(text=_("Close"))

    def _escape_keypress(self, event):
        logger.info(f"_escape_pressed")
        self._on_cancel()

    def _on_cancel(self):
        logger.info(f"_on_cancel")
        if self._controller.bulk_move_active():
            self._controller.abort_move()

        self.grab_release()
        self.destroy()

    def get_imported(self):
        self.focus()
        self.master.wait_window(self)
        return self.imported
