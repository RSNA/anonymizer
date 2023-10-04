from pathlib import Path
from typing import Union
import customtkinter as ctk
from tkinter import filedialog
import string
import logging
from model.project import ProjectModel
from controller.project import DICOMNode
from view.dicom_node_dialog import DICOMNodeDialog
from utils.translate import _
from utils.ux_fields import str_entry, int_entry
from view.sop_classes_dialog import SOPClassesDialog


logger = logging.getLogger(__name__)


class SettingsDialog(ctk.CTkToplevel):
    def __init__(
        self,
        model: ProjectModel,
        new_model: bool = False,
        title: str = _("Project Settings"),
    ):
        super().__init__()
        self.model = model
        self.new_model = new_model
        self.title(title)
        self.lift()  # lift window on top
        self.attributes("-topmost", True)  # stay on top
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.resizable(False, False)
        self.grab_set()  # make dialog modal
        self._user_input: Union[ProjectModel, None] = None
        self._create_widgets()

    def _create_widgets(self):
        logger.info(f"_create_widgets")
        PAD = 10
        min_chars = 3
        max_chars = 20
        uid_max_chars = 30

        char_width_px = ctk.CTkFont().measure("A")
        # validate_entry_cmd = self.register(validate_entry)
        logger.info(f"Font Character Width in pixels: ±{char_width_px}")

        self.columnconfigure(1, weight=1)
        self.rowconfigure(3, weight=1)

        row = 0

        self.site_id__var = str_entry(
            view=self,
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
            enabled=self.new_model,
        )
        row += 1

        self.project_name_var = str_entry(
            view=self,
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

        self.trial_name_var = str_entry(
            view=self,
            label=_("Trial Name:"),
            initial_value=self.model.trial_name,
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
            view=self,
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

        servers_label = ctk.CTkLabel(self, text=_("Servers:"))
        servers_label.grid(row=row, column=0, padx=PAD, pady=(PAD, 0), sticky="nw")

        self._local_server_button = ctk.CTkButton(
            self, width=100, text=_("Local Server"), command=self._local_server_click
        )
        self._local_server_button.grid(
            row=row, column=1, padx=PAD, pady=(PAD, 0), sticky="w"
        )

        row += 1

        self._query_server_button = ctk.CTkButton(
            self, width=100, text=_("Query Server"), command=self._query_server_click
        )
        self._query_server_button.grid(
            row=row, column=1, padx=PAD, pady=(PAD, 0), sticky="w"
        )

        row += 1

        self._export_server_button = ctk.CTkButton(
            self, width=100, text=_("Export Server"), command=self._export_server_click
        )
        self._export_server_button.grid(
            row=row, column=1, padx=PAD, pady=(PAD, 0), sticky="w"
        )

        row += 1

        self.nework_timeout_var = int_entry(
            view=self,
            label=_("Network Timeout:"),
            initial_value=self.model.network_timeout,
            min=0,
            max=30,
            tooltipmsg=None,
            row=row,
            col=0,
            pad=PAD,
            sticky="nw",
        )

        row += 1

        self._storage_directory_label = ctk.CTkLabel(self, text=_("Storage Directory:"))
        self._storage_directory_label.grid(
            row=row, column=0, pady=(PAD, 0), padx=PAD, sticky="nw"
        )

        # Only allow setting of storage directory for NEW project:
        if self.new_model:
            self._storage_dir_button = ctk.CTkButton(
                self,
                text=self.model.abridged_storage_dir(),
                command=self._open_storage_directory_dialog,
                state=ctk.NORMAL if self.new_model else ctk.DISABLED,
            )
            self._storage_dir_button.grid(
                row=row, column=1, padx=PAD, pady=(PAD, 0), sticky="nw"
            )
        else:
            self._storage_dir_label = ctk.CTkLabel(
                self, text=self.model.abridged_storage_dir()
            )
            self._storage_dir_label.grid(
                row=row, column=1, padx=PAD, pady=(PAD, 0), sticky="nw"
            )

        row += 1

        self._storage_classes_label = ctk.CTkLabel(self, text=_("Storage Classes:"))
        self._storage_classes_label.grid(
            row=row, column=0, pady=(PAD, 0), padx=PAD, sticky="nw"
        )

        self._storage_classes_button = ctk.CTkButton(
            self,
            text=_("Select Storage Classes"),
            command=self._open_storage_classes_dialog,
        )
        self._storage_classes_button.grid(
            row=row, column=1, pady=(PAD, 0), padx=PAD, sticky="nw"
        )

        row += 1

        # Script File is selectable ONLY for NEW projects
        # On project creation the script file is parsed and saved to the Anonymizer model
        if self.new_model:
            self._script_file_label = ctk.CTkLabel(self, text=str("Script File:"))
            self._script_file_label.grid(
                row=row, column=0, pady=(PAD, 0), padx=PAD, sticky="nw"
            )

            self._script_file_button = ctk.CTkButton(
                self,
                text=str(self.model.anonymizer_script_path),
                command=self._script_file_dialog,
            )
            self._script_file_button.grid(
                row=row, column=1, padx=PAD, pady=(PAD, 0), sticky="nw"
            )

            row += 1

        if self.new_model:
            btn_text = _("Create Project")
        else:
            btn_text = _("Update Project")
        self._create_project_button = ctk.CTkButton(
            self, width=100, text=btn_text, command=self._create_project
        )
        self._create_project_button.grid(
            row=row,
            column=1,
            padx=PAD,
            pady=(PAD * 2, PAD),
            sticky="e",
        )

    def _local_server_click(self, event=None):
        dlg = DICOMNodeDialog(self.model.scp, title=_("Local Server"))
        scp = dlg.get_input()
        if scp is None:
            logger.info(f"Local Server cancelled")
            return
        self.model.scp = scp
        self.model.scu = scp  # TODO: remove scu from model?
        logger.info(f"Local Server: {self.model.scp}")
        # TODO: prevent local server from being a remote server / same address/port

    def _query_server_click(self, event=None):
        if "QUERY" in self.model.remote_scps:
            scp = self.model.remote_scps["QUERY"]
        else:
            scp = DICOMNode("127.0.0.1", 104, "", False)
        dlg = DICOMNodeDialog(scp, title=_("Query Server"))
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
        dlg = DICOMNodeDialog(scp, title=_("Export Server"))
        scp = dlg.get_input()
        if scp is None:
            logger.info(f"Export Server cancelled")
            return
        self.model.remote_scps["EXPORT"] = scp
        logger.info(f"Remote Servers: {self.model.remote_scps}")

    def _open_storage_directory_dialog(self):
        path = filedialog.askdirectory(
            initialdir=str(self.model.storage_dir), mustexist=False
        )
        if path:
            self.model.storage_dir = Path(path)
            self._storage_dir_button.configure(text=self.model.abridged_storage_dir())
            logger.info(f"Storage Directory: {self.model.storage_dir}")

    def _open_storage_classes_dialog(self):
        dlg = SOPClassesDialog(self.model.storage_classes)
        edited_classes = dlg.get_input()
        if edited_classes is None:
            logger.info(f"Storage Classes cancelled")
            return
        self.model.storage_classes = edited_classes
        logger.info(f"Storage Classes updated: {self.model.storage_classes}")

    def _script_file_dialog(self):
        path = filedialog.askopenfilename(
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
            logger.info(f"Anonymizer Script File: {self.model.anonymizer_script_path}")

    def _create_project(self):
        self._user_input = ProjectModel(
            site_id=self.site_id__var.get(),
            project_name=self.project_name_var.get(),
            trial_name=self.trial_name_var.get(),
            uid_root=self.uidroot_var.get(),
            storage_dir=self.model.storage_dir,
            scu=self.model.scu,
            scp=self.model.scp,
            remote_scps=self.model.remote_scps,
            network_timeout=self.nework_timeout_var.get(),
        )
        self.grab_release()
        self.destroy()

    def _on_cancel(self):
        self.grab_release()
        self.destroy()

    def get_input(self):
        self.master.wait_window(self)
        return self._user_input
