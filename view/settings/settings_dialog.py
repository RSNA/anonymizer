from pathlib import Path
from typing import Union
import tkinter as tk
import customtkinter as ctk
from tkinter import filedialog
import string
import logging
from model.project import ProjectModel
from controller.project import DICOMNode
from utils.translate import _
from utils.ux_fields import str_entry
from utils.logging import set_logging_levels
from view.settings.dicom_node_dialog import DICOMNodeDialog
from view.settings.aws_cognito_dialog import AWSCognitoDialog
from view.settings.network_timeouts_dialog import NetworkTimeoutsDialog
from view.settings.modalites_dialog import ModalitiesDialog
from view.settings.sop_classes_dialog import SOPClassesDialog
from view.settings.transfer_syntaxes_dialog import TransferSyntaxesDialog
from view.settings.logging_levels_dialog import LoggingLevelsDialog

logger = logging.getLogger(__name__)


class SettingsDialog(tk.Toplevel):
    # class SettingsDialog(ctk.CTkToplevel):
    def __init__(
        self,
        parent,
        model: ProjectModel,
        new_model: bool = False,
        title: str = _("Project Settings"),
    ):
        super().__init__(master=parent)
        self.model = model
        self.new_model = new_model
        self.title(title)
        self.resizable(False, False)
        self.grab_set()  # make dialog modal
        self._user_input: Union[ProjectModel, None] = None
        self._create_widgets()
        self.bind("<Return>", self._enter_keypress)
        self.bind("<Escape>", self._escape_keypress)
        # if sys.platform.startswith("win"):
        #     # override CTkTopLevel which sets icon after 200ms
        #     self.after(300, self._win_post_init)

    def _win_post_init(self):
        self.iconbitmap("assets\\images\\rsna_icon.ico")
        self.lift()
        self.focus()

    def _create_widgets(self):
        logger.debug(f"_create_widgets")
        PAD = 10
        min_chars = 3
        max_chars = 20
        uid_max_chars = 30

        char_width_px = ctk.CTkFont().measure("A")
        logger.debug(f"Font Character Width in pixels: {char_width_px}")

        self._frame = ctk.CTkFrame(self)
        self._frame.grid(row=0, column=0, padx=PAD, pady=PAD, sticky="nswe")

        row = 0

        self.site_id__var = str_entry(
            view=self._frame,
            label=_("Site ID:"),
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
        row += 1

        self.project_name_var = str_entry(
            view=self._frame,
            label=_("Project Name:"),
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
        row += 1

        self.uidroot_var = str_entry(
            view=self._frame,
            label=_("UID Root:"),
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

        servers_label = ctk.CTkLabel(self._frame, text=_("DICOM Servers:"))
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

        servers_label = ctk.CTkLabel(self._frame, text=_("AWS S3 Server:"))
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
        network_timeouts_label = ctk.CTkLabel(self._frame, text=_("Network Timeouts:"))
        network_timeouts_label.grid(row=row, column=0, padx=PAD, pady=(PAD, 0), sticky="nw")
        self.network_timeout_button = ctk.CTkButton(
            self._frame,
            width=100,
            text=_("Network Timeouts"),
            command=self._network_timeouts_click,
        )
        self.network_timeout_button.grid(row=row, column=1, padx=PAD, pady=(PAD, 0), sticky="w")

        row += 1

        self._storage_directory_label = ctk.CTkLabel(self._frame, text=_("Storage Directory:"))
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

        self._modalities_label = ctk.CTkLabel(self._frame, text=_("Modalities:"))
        self._modalities_label.grid(row=row, column=0, pady=(PAD, 0), padx=PAD, sticky="nw")

        self._modalities_button = ctk.CTkButton(
            self._frame,
            width=100,
            text=_("Select Modalities"),
            command=self._open_modalities_dialog,
        )
        self._modalities_button.grid(row=row, column=1, pady=(PAD, 0), padx=PAD, sticky="nw")

        row += 1

        self._storage_classes_label = ctk.CTkLabel(self._frame, text=_("Storage Classes:"))
        self._storage_classes_label.grid(row=row, column=0, pady=(PAD, 0), padx=PAD, sticky="nw")

        self._storage_classes_button = ctk.CTkButton(
            self._frame,
            text=_("Select Storage Classes"),
            command=self._open_storage_classes_dialog,
        )
        self._storage_classes_button.grid(row=row, column=1, pady=(PAD, 0), padx=PAD, sticky="nw")

        row += 1

        self._transfer_syntaxes_label = ctk.CTkLabel(self._frame, text=_("Transfer Syntaxes:"))
        self._transfer_syntaxes_label.grid(row=row, column=0, pady=(PAD, 0), padx=PAD, sticky="nw")

        self._transfer_syntaxes_button = ctk.CTkButton(
            self._frame,
            text=_("Select Transfer Syntaxes"),
            command=self._open_transfer_syntaxes_dialog,
        )
        self._transfer_syntaxes_button.grid(row=row, column=1, pady=(PAD, 0), padx=PAD, sticky="nw")

        row += 1

        # Script File is selectable ONLY for NEW projects
        # On project creation the script file is parsed and saved to the Anonymizer model
        if self.new_model:
            self._script_file_label = ctk.CTkLabel(self._frame, text=str("Script File:"))
            self._script_file_label.grid(row=row, column=0, pady=(PAD, 0), padx=PAD, sticky="nw")

            self._script_file_button = ctk.CTkButton(
                self._frame,
                text=str(self.model.anonymizer_script_path),
                command=self._script_file_dialog,
            )
            self._script_file_button.grid(row=row, column=1, padx=PAD, pady=(PAD, 0), sticky="nw")

            row += 1

        # Logging Levels:
        self._logging_levels_label = ctk.CTkLabel(self._frame, text=_("Logging Levels:"))
        self._logging_levels_label.grid(row=row, column=0, pady=(PAD, 0), padx=PAD, sticky="nw")
        self._logging_levels_button = ctk.CTkButton(
            self._frame,
            text=_("Set Logging Levels"),
            command=self._set_logging_levels_dialog,
        )
        self._logging_levels_button.grid(row=row, column=1, pady=(PAD, 0), padx=PAD, sticky="nw")

        row += 1

        if self.new_model:
            btn_text = _("Create Project")
        else:
            btn_text = _("Update Project")
        self._create_project_button = ctk.CTkButton(self._frame, width=100, text=btn_text, command=self._create_project)
        self._create_project_button.grid(
            row=row,
            column=1,
            padx=PAD,
            pady=(PAD * 2, PAD),
            sticky="e",
        )

    def _local_server_click(self, event=None):
        dlg = DICOMNodeDialog(self, self.model.scp, title=_("Local Server"))
        scp = dlg.get_input()
        if scp is None:
            logger.info(f"Local Server cancelled")
            return
        self.model.scp = scp
        self.model.scu = scp  # TODO: remove scu from model?
        logger.info(f"Local Server update: {self.model.scp}")
        # TODO: prevent local server from being a remote server / same address/port

    def _query_server_click(self, event=None):
        if "QUERY" in self.model.remote_scps:
            scp = self.model.remote_scps["QUERY"]
        else:
            scp = DICOMNode("127.0.0.1", 104, "", False)
        dlg = DICOMNodeDialog(self, scp, title=_("Query Server"))
        scp = dlg.get_input()
        if scp is None:
            logger.info(f"Query Server cancelled")
            return
        self.model.remote_scps["QUERY"] = scp
        logger.info(f"Remote Servers: {self.model.remote_scps}")

    def _export_server_click(self, event=None):
        if "EXPORT" in self.model.remote_scps:
            scp = self.model.remote_scps["EXPORT"]
        else:
            scp = DICOMNode("127.0.0.1", 104, "", False)
        dlg = DICOMNodeDialog(self, scp, title=_("Export Server"))
        scp = dlg.get_input()
        if scp is None:
            logger.info(f"Export Server cancelled")
            return
        self.model.remote_scps["EXPORT"] = scp
        logger.info(f"Remote Servers: {self.model.remote_scps}")

    def _aws_cognito_click(self, event=None):
        dlg = AWSCognitoDialog(self, self.model.export_to_AWS, self.model.aws_cognito)
        input = dlg.get_input()
        if input is None:
            logger.info(f"AWS Cognito cancelled")
            return
        self.model.export_to_AWS, self.model.aws_cognito = input
        logger.info(f"Export to AWS: {self.model.export_to_AWS}, Cognito: {self.model.aws_cognito}")

    def _network_timeouts_click(self, event=None):
        dlg = NetworkTimeoutsDialog(self, self.model.network_timeouts)
        timeouts = dlg.get_input()
        if timeouts is None:
            logger.info(f"Network Timeouts cancelled")
            return
        self.model.network_timeouts = timeouts
        logger.info(f"Network Timeouts updated: {self.model.network_timeouts}")

    def _open_storage_directory_dialog(self):
        msg = _("Select Storage Directory")
        path = filedialog.askdirectory(
            message=msg,
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
            logger.info(f"Modalities Dialog cancelled")
            return
        self.model.modalities = edited_modalities
        self.model.set_storage_classes_from_modalities()
        logger.info(f"Modalities updated: {self.model.modalities}")
        logger.info(f"Storage Classes set according to Modalities selected: {self.model.storage_classes}")

    def _open_storage_classes_dialog(self):
        dlg = SOPClassesDialog(self, self.model.storage_classes, self.model.modalities)
        edited_classes = dlg.get_input()
        if edited_classes is None:
            logger.info(f"Storage Classes cancelled")
            return
        self.model.storage_classes = edited_classes
        logger.info(f"Storage Classes updated: {self.model.storage_classes}")

    def _open_transfer_syntaxes_dialog(self):
        dlg = TransferSyntaxesDialog(self, self.model.transfer_syntaxes)
        edited_syntaxes = dlg.get_input()
        if edited_syntaxes is None:
            logger.info(f"Transfer Syntaxes cancelled")
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
            logger.info(f"Logging Levels cancelled")
            return
        self.model.logging_levels = levels
        logger.info(f"Logging Levels updated: {self.model.logging_levels}")
        set_logging_levels(levels)

    def _enter_keypress(self, event):
        logger.info(f"_enter_pressed")
        self._create_project()

    def _create_project(self):
        self._user_input = ProjectModel(
            site_id=self.site_id__var.get(),
            project_name=self.project_name_var.get(),
            uid_root=self.uidroot_var.get(),
            storage_dir=self.model.storage_dir,
            modalities=self.model.modalities,
            storage_classes=self.model.storage_classes,
            transfer_syntaxes=self.model.transfer_syntaxes,
            logging_levels=self.model.logging_levels,
            scu=self.model.scu,
            scp=self.model.scp,
            remote_scps=self.model.remote_scps,
            export_to_AWS=self.model.export_to_AWS,
            aws_cognito=self.model.aws_cognito,
            network_timeouts=self.model.network_timeouts,
            anonymizer_script_path=self.model.anonymizer_script_path,
        )
        self.grab_release()
        self.destroy()

    def _escape_keypress(self, event):
        logger.info(f"_escape_pressed")
        self._on_cancel()

    def _on_cancel(self):
        self.grab_release()
        self.destroy()

    def get_input(self):
        self.focus()
        self.master.wait_window(self)
        return self._user_input
