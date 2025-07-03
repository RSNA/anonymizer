"""
This module contains the SettingsDialog class, which is a dialog window for managing project settings.
"""

import logging
import string
import tkinter as tk
from copy import copy
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import List, Tuple

import customtkinter as ctk

from anonymizer.controller.project import DICOMNode
from anonymizer.model.project import AWSCognito, ProjectModel
from anonymizer.utils.logging import set_logging_levels
from anonymizer.utils.storage import (
    JavaAnonymizerExportedStudy,
    read_java_anonymizer_index_xlsx,
)
from anonymizer.utils.translate import _, get_current_language_code
from anonymizer.view.settings.aws_cognito_dialog import AWSCognitoDialog
from anonymizer.view.settings.dicom_node_dialog import DICOMNodeDialog
from anonymizer.view.settings.logging_levels_dialog import LoggingLevelsDialog
from anonymizer.view.settings.modalites_dialog import ModalitiesDialog
from anonymizer.view.settings.network_timeouts_dialog import NetworkTimeoutsDialog
from anonymizer.view.settings.sop_classes_dialog import SOPClassesDialog
from anonymizer.view.settings.transfer_syntaxes_dialog import TransferSyntaxesDialog
from anonymizer.view.ux_fields import str_entry

logger = logging.getLogger(__name__)


# TODO: ctk.CTkToplevel does not handle window icon on Windows
class SettingsDialog(tk.Toplevel):
    """
    A dialog window for managing project settings.

    Args:
        parent (tk.Tk): The parent window.
        model (ProjectModel): The project model.
        new_model (bool, optional): Indicates whether it is a new project model. Defaults to False.
        title (str | None, optional): The title of the dialog window. Defaults to None.
    """

    def __init__(
        self,
        parent,
        model: ProjectModel,
        new_model: bool = False,
        title: str | None = None,
    ):
        super().__init__(master=parent)
        self.model: ProjectModel = copy(model)
        self.java_phi_studies: List[JavaAnonymizerExportedStudy] = []
        self.new_model = new_model  # to restrict editing for existing projects, eg. SITE_ID & storage directory changes
        if title is None:
            title = _("Project Settings")
        self.title(title)
        self.resizable(False, False)
        self._user_input: Tuple[ProjectModel | None, List[JavaAnonymizerExportedStudy] | None] = (None, None)
        self._create_widgets()
        self.wait_visibility()
        self.lift()
        self.grab_set()  # make dialog modal
        self.bind("<Return>", self._enter_keypress)
        self.bind("<Escape>", self._escape_keypress)

    def _create_widgets(self):
        logger.debug("_create_widgets")
        PAD = 10
        min_chars = 3
        max_chars = 20
        uid_max_chars = 30

        char_width_px = ctk.CTkFont().measure("A")
        logger.debug(f"Font Character Width in pixels: {char_width_px}")

        self._frame = ctk.CTkFrame(self)
        self._frame.grid(row=0, column=0, padx=PAD, pady=PAD, sticky="nswe")

        row = 0

        self.site_id_var: ctk.StringVar = str_entry(
            view=self._frame,
            label=_("Site ID") + ":",
            initial_value=self.model.site_id,
            min_chars=min_chars,
            max_chars=max_chars,
            charset=string.digits + "-.",
            tooltipmsg=None,
            row=row,
            col=0,
            pad=PAD,
            sticky="nw",
            enabled=False,  # Site ID is auto generated and cannot be changed
        )

        if self.new_model:
            self._load_java_index_button = ctk.CTkButton(
                self._frame,
                text=_("Load JAVA Index File"),
                command=self._initialise_project_from_java_index,
            )
            self._load_java_index_button.grid(row=row, column=1, padx=PAD, pady=(PAD, 0), sticky="ne")

        row += 1

        self.project_name_var: ctk.StringVar = str_entry(
            view=self._frame,
            label=_("Project Name") + ":",
            initial_value=self.model.project_name,
            min_chars=min_chars,
            max_chars=max_chars,
            charset=string.digits + string.ascii_uppercase + " -.",
            tooltipmsg=None,
            row=row,
            col=0,
            pad=PAD,
            sticky="nw",
            enabled=self.new_model,
        )
        self.project_name_var.trace_add("write", self._project_name_change)

        row += 1

        self.uidroot_var: ctk.StringVar = str_entry(
            view=self._frame,
            label=_("UID Root") + ":",
            initial_value=self.model.uid_root,
            min_chars=min_chars,
            max_chars=uid_max_chars,
            charset=string.digits + ".",
            tooltipmsg=None,
            row=row,
            col=0,
            pad=PAD,
            sticky="nw",
            enabled=self.new_model,
        )
        row += 1

        remove_pixel_phi_label = ctk.CTkLabel(self._frame, text=_("Remove Pixel PHI") + ":")
        remove_pixel_phi_label.grid(row=row, column=0, padx=PAD, pady=(PAD, 0), sticky="nw")

        self._remove_pixel_phi_checkbox = ctk.CTkCheckBox(self._frame, text="")
        if self.model.remove_pixel_phi:
            self._remove_pixel_phi_checkbox.select()

        self._remove_pixel_phi_checkbox.grid(
            row=row,
            column=1,
            padx=PAD,
            pady=PAD,
            sticky="nw",
        )

        row += 1

        servers_label = ctk.CTkLabel(self._frame, text=_("DICOM Servers") + ":")
        servers_label.grid(row=row, column=0, padx=PAD, pady=(PAD, 0), sticky="nw")

        self._local_server_button = ctk.CTkButton(
            self._frame,
            width=100,
            text=_("Local Server"),
            command=self._local_server_click,
        )
        self._local_server_button.grid(row=row, column=1, padx=PAD, pady=(PAD, 0), sticky="w")

        row += 1

        self._query_server_button = ctk.CTkButton(
            self._frame,
            width=100,
            text=_("Query Server"),
            command=self._query_server_click,
        )
        self._query_server_button.grid(row=row, column=1, padx=PAD, pady=(PAD, 0), sticky="w")

        row += 1

        self._export_server_button = ctk.CTkButton(
            self._frame,
            width=100,
            text=_("Export Server"),
            command=self._export_server_click,
        )
        self._export_server_button.grid(row=row, column=1, padx=PAD, pady=(PAD, 0), sticky="w")

        row += 1

        servers_label = ctk.CTkLabel(self._frame, text=_("AWS S3 Server") + ":")
        servers_label.grid(row=row, column=0, padx=PAD, pady=(PAD, 0), sticky="nw")

        self._export_server_button = ctk.CTkButton(
            self._frame,
            width=100,
            text=_("AWS Cognito Credentials"),
            command=self._aws_cognito_click,
        )
        self._export_server_button.grid(row=row, column=1, padx=PAD, pady=(PAD, 0), sticky="w")

        row += 1

        # TODO: None for timeout means no timeout, implement checkbox for enable/disable timeout
        network_timeouts_label = ctk.CTkLabel(self._frame, text=_("Network Timeouts") + ":")
        network_timeouts_label.grid(row=row, column=0, padx=PAD, pady=(PAD, 0), sticky="nw")
        self.network_timeout_button = ctk.CTkButton(
            self._frame,
            width=100,
            text=_("Network Timeouts"),
            command=self._network_timeouts_click,
        )
        self.network_timeout_button.grid(row=row, column=1, padx=PAD, pady=(PAD, 0), sticky="w")

        row += 1

        self._storage_directory_label = ctk.CTkLabel(self._frame, text=_("Storage Directory") + ":")
        self._storage_directory_label.grid(row=row, column=0, pady=(PAD, 0), padx=PAD, sticky="nw")

        # Only allow setting of storage directory for NEW project:
        if self.new_model:
            self._storage_dir_button = ctk.CTkButton(
                self._frame,
                text=self.model.abridged_storage_dir(),
                command=self._open_storage_directory_dialog,
                state=ctk.NORMAL if self.new_model else ctk.DISABLED,
            )
            self._storage_dir_button.grid(row=row, column=1, padx=PAD, pady=(PAD, 0), sticky="nw")
        else:
            self._storage_dir_label = ctk.CTkLabel(self._frame, text=self.model.abridged_storage_dir())
            self._storage_dir_label.grid(row=row, column=1, padx=PAD, pady=(PAD, 0), sticky="nw")

        row += 1

        # TODO: provide user access to DB DIALECT and then infer either file location or URL
        # TODO: test with MySQL & PostgreSQL - see SQLAlchemy documentation for connection strings
        # self.db_url_var: ctk.StringVar = str_entry(
        #     view=self._frame,
        #     label=_("Database URL") + ":",
        #     initial_value=self.model.db_url,
        #     min_chars=min_chars,
        #     max_chars=uid_max_chars,
        #     charset=string.digits + string.ascii_letters + " -./:",
        #     tooltipmsg=None,
        #     row=row,
        #     col=0,
        #     pad=PAD,
        #     sticky="nw",
        #     enabled=True,
        # )

        # row += 1

        self._modalities_label = ctk.CTkLabel(self._frame, text=_("Modalities") + ":")
        self._modalities_label.grid(row=row, column=0, pady=(PAD, 0), padx=PAD, sticky="nw")

        self._modalities_button = ctk.CTkButton(
            self._frame,
            width=100,
            text=_("Select Modalities"),
            command=self._open_modalities_dialog,
        )
        self._modalities_button.grid(row=row, column=1, pady=(PAD, 0), padx=PAD, sticky="nw")

        row += 1

        self._storage_classes_label = ctk.CTkLabel(self._frame, text=_("Storage Classes") + ":")
        self._storage_classes_label.grid(row=row, column=0, pady=(PAD, 0), padx=PAD, sticky="nw")

        self._storage_classes_button = ctk.CTkButton(
            self._frame,
            text=_("Select Storage Classes"),
            command=self._open_storage_classes_dialog,
        )
        self._storage_classes_button.grid(row=row, column=1, pady=(PAD, 0), padx=PAD, sticky="nw")

        row += 1

        self._transfer_syntaxes_label = ctk.CTkLabel(self._frame, text=_("Transfer Syntaxes") + ":")
        self._transfer_syntaxes_label.grid(row=row, column=0, pady=(PAD, 0), padx=PAD, sticky="nw")

        self._transfer_syntaxes_button = ctk.CTkButton(
            self._frame,
            text=_("Select Transfer Syntaxes"),
            command=self._open_transfer_syntaxes_dialog,
        )
        self._transfer_syntaxes_button.grid(row=row, column=1, pady=(PAD, 0), padx=PAD, sticky="nw")

        row += 1

        self._script_file_label = ctk.CTkLabel(self._frame, text=_("Script File") + ":")
        self._script_file_label.grid(row=row, column=0, pady=(PAD, 0), padx=PAD, sticky="nw")

        # Script File is selectable ONLY for NEW projects
        # On project creation the script file is parsed and saved to the Anonymizer model
        if self.new_model:
            self._script_file_button = ctk.CTkButton(
                self._frame,
                text=str(self.model.abridged_script_path()),
                command=self._script_file_dialog,
                state=ctk.NORMAL if self.new_model else ctk.DISABLED,
            )
            self._script_file_button.grid(row=row, column=1, padx=PAD, pady=(PAD, 0), sticky="nw")
        else:
            self._storage_dir_label = ctk.CTkLabel(self._frame, text=self.model.abridged_script_path())
            self._storage_dir_label.grid(row=row, column=1, padx=PAD, pady=(PAD, 0), sticky="nw")

        row += 1

        # Logging Levels:
        self._logging_levels_label = ctk.CTkLabel(self._frame, text=_("Logging Levels") + ":")
        self._logging_levels_label.grid(row=row, column=0, pady=(PAD, 0), padx=PAD, sticky="nw")
        self._logging_levels_button = ctk.CTkButton(
            self._frame,
            text=_("Set Logging Levels"),
            command=self._set_logging_levels_dialog,
        )
        self._logging_levels_button.grid(row=row, column=1, pady=(PAD, 0), padx=PAD, sticky="nw")

        row += 1

        btn_text = _("Create Project") if self.new_model else _("Update Project")
        self._create_project_button = ctk.CTkButton(self._frame, width=100, text=btn_text, command=self._create_project)
        self._create_project_button.grid(
            row=row,
            column=1,
            padx=PAD,
            pady=(PAD * 2, PAD),
            sticky="e",
        )

    def _project_name_change(self, name, index, mode):
        logger.debug("_project_name_change")
        new_project_name = self.project_name_var.get()
        if not new_project_name:
            return
        self.model.project_name = new_project_name
        logger.debug(f"Project Name updated: {self.model.project_name}")
        self.model.storage_dir = self.model.storage_dir.parent / self.model.project_name
        self._storage_dir_button.configure(text=self.model.abridged_storage_dir())
        logger.debug(f"Storage Directory updated: {self.model.storage_dir}")

    def _local_server_click(self, event=None):
        dlg = DICOMNodeDialog(self, self.model.scp, title=_("Local Server"))
        scp: DICOMNode | None = dlg.get_input()
        if scp is None:
            logger.info("Local Server cancelled")
            return
        self.model.scp = scp
        self.model.scu = scp  # TODO: remove scu from model?
        logger.info(f"Local Server update: {self.model.scp}")
        # TODO: prevent local server from being a remote server / same address/port

    def _query_server_click(self, event=None):
        if _("QUERY") in self.model.remote_scps:
            scp = self.model.remote_scps[_("QUERY")]
        else:
            scp = DICOMNode("127.0.0.1", 104, "", False)
        dlg = DICOMNodeDialog(self, scp, title=_("Query Server"))
        scp = dlg.get_input()
        if scp is None:
            logger.info("Query Server cancelled")
            return
        self.model.remote_scps[_("QUERY")] = scp
        logger.info(f"Remote Servers: {self.model.remote_scps}")

    def _export_server_click(self, event=None):
        if _("EXPORT") in self.model.remote_scps:
            scp = self.model.remote_scps[_("EXPORT")]
        else:
            scp = DICOMNode("127.0.0.1", 104, "", False)
        dlg = DICOMNodeDialog(self, scp, title=_("Export Server"))
        scp = dlg.get_input()
        if scp is None:
            logger.info("Export Server cancelled")
            return
        self.model.remote_scps[_("EXPORT")] = scp
        logger.info(f"Remote Servers: {self.model.remote_scps}")

    def _aws_cognito_click(self, event=None):
        dlg = AWSCognitoDialog(self, self.model.export_to_AWS, self.model.aws_cognito)
        input: tuple[bool, AWSCognito] | None = dlg.get_input()
        if input is None:
            logger.info("AWS Cognito cancelled")
            return
        self.model.export_to_AWS, self.model.aws_cognito = input
        logger.info(f"Export to AWS: {self.model.export_to_AWS}, Cognito: {self.model.aws_cognito}")

    def _network_timeouts_click(self, event=None):
        dlg = NetworkTimeoutsDialog(self, self.model.network_timeouts)
        timeouts = dlg.get_input()
        if timeouts is None:
            logger.info("Network Timeouts cancelled")
            return
        self.model.network_timeouts = timeouts
        logger.info(f"Network Timeouts updated: {self.model.network_timeouts}")

    def _open_storage_directory_dialog(self):
        path = filedialog.askdirectory(
            title=_("Select Storage Directory"),
            initialdir=str(self.model.storage_dir),
            parent=self,
            mustexist=False,
        )
        if path:
            self.model.storage_dir = Path(path)
            self._storage_dir_button.configure(text=self.model.abridged_storage_dir())
            logger.info(f"Storage Directory updated: {self.model.storage_dir}")

    def _open_modalities_dialog(self):
        dlg = ModalitiesDialog(self, self.model.modalities)
        edited_modalities = dlg.get_input()
        if edited_modalities is None:
            logger.info("Modalities Dialog cancelled")
            return
        self.model.modalities = edited_modalities
        self.model.set_storage_classes_from_modalities()
        logger.info(f"Modalities updated: {self.model.modalities}")
        logger.info(f"Storage Classes set according to Modalities selected: {self.model.storage_classes}")

    def _open_storage_classes_dialog(self):
        dlg = SOPClassesDialog(self, self.model.storage_classes, self.model.modalities)
        edited_classes = dlg.get_input()
        if edited_classes is None:
            logger.info("Storage Classes cancelled")
            return
        self.model.storage_classes = edited_classes
        logger.info(f"Storage Classes updated: {self.model.storage_classes}")

    def _open_transfer_syntaxes_dialog(self):
        dlg = TransferSyntaxesDialog(self, self.model.transfer_syntaxes)
        edited_syntaxes = dlg.get_input()
        if edited_syntaxes is None:
            logger.info("Transfer Syntaxes cancelled")
            return
        self.model.transfer_syntaxes = edited_syntaxes
        logger.info(f"Transfer Syntaxes updated: {self.model.transfer_syntaxes}")

    def _script_file_dialog(self):
        path = filedialog.askopenfilename(
            parent=self,
            initialfile=str(self.model.anonymizer_script_path),
            defaultextension=".script",
            filetypes=[
                (_("Anonymizer Script Files"), "*.script"),
                (_("All Files"), "*.*"),
            ],
        )
        if path:
            self.model.anonymizer_script_path = Path(path)
            self._script_file_button.configure(text=path)
            logger.info(f"Anonymizer Script File updated: {self.model.anonymizer_script_path}")

    def _set_logging_levels_dialog(self):
        dlg = LoggingLevelsDialog(self, self.model.logging_levels)
        levels = dlg.get_input()
        if levels is None:
            logger.info("Logging Levels cancelled")
            return
        self.model.logging_levels = levels
        logger.info(f"Logging Levels updated: {self.model.logging_levels}")
        set_logging_levels(levels)

    def _initialise_project_from_java_index(self):
        path: str = filedialog.askopenfilename(
            parent=self,
            initialdir="~",
            title=_("Select Java Anonymizer Index File"),
            filetypes=[(_("Excel Files"), "*.xlsx")],
        )
        if path:
            logger.info(f"Java Index File: {path}")
            # Read phi data records from the Java Anonymizer Exported Study Index File:
            try:
                self.java_phi_studies: List[JavaAnonymizerExportedStudy] = read_java_anonymizer_index_xlsx(path)
            except Exception as e:
                msg = _("Error reading Java Anonymizer Index File") + f":\n\n{path}\n\n{e}"
                messagebox.showerror(
                    title=_("Load Java Anonymizer Index File Error"),
                    message=msg,
                    parent=self,
                )
                return
            if len(self.java_phi_studies) == 0:
                msg = _("No PHI data records found in:") + f"\n\n{path}"
                messagebox.showerror(
                    title=_("Load Java Anonymizer Index File Error"),
                    message=msg,
                    parent=self,
                )
                return
            else:
                messagebox.showinfo(
                    title=_("Java Index File Loaded"),
                    message=f"{len(self.java_phi_studies)} "
                    + _("Studies from Java Index loaded.")
                    + "\n\n"
                    + _("Site ID, UID Root will be inferred from the first PHI record.")
                    + "\n\n"
                    + _("Please enter your Project Name and configure all other settings below.")
                    + "\n\n"
                    + _(
                        "The Java Index data will be processed into the Python Anonymizer database when the project is created."
                    ),
                    parent=self,
                )

            # Infer Site ID from the first record's ANON_PatientID:
            self.model.site_id = self.java_phi_studies[0].ANON_PatientID.split("-")[0]
            self.site_id_var.set(self.model.site_id)
            logger.info(f"Site ID {self.model.site_id} initialised from Java Index File")
            # Infer UID Root from the first record's ANON_StudyInstanceUID:
            if self.model.site_id in self.java_phi_studies[0].ANON_StudyInstanceUID:
                self.model.uid_root = self.java_phi_studies[0].ANON_StudyInstanceUID.split(f".{self.model.site_id}")[0]
                self.uidroot_var.set(self.model.uid_root)
                logger.info(f"UID Root {self.model.uid_root} initialised from Java Index File")

    def _enter_keypress(self, event):
        logger.info("_enter_pressed")
        self._create_project()

    def _create_project(self):
        self.model.site_id = self.site_id_var.get()
        self.model.language_code = get_current_language_code()
        self.model.project_name = self.project_name_var.get()
        self.model.uid_root = self.uidroot_var.get()
        self.model.remove_pixel_phi = self._remove_pixel_phi_checkbox.get() == 1
        self._user_input = self.model, self.java_phi_studies

        self.grab_release()
        self.destroy()

    def _escape_keypress(self, event):
        logger.info("_escape_pressed")
        self._on_cancel()

    def _on_cancel(self):
        self.grab_release()
        self.destroy()

    def get_input(self):
        self.focus()
        self.master.wait_window(self)
        return self._user_input
