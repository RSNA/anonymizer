import os, sys
from pathlib import Path
import logging
import pickle
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk
from model.project import (
    DICOMRuntimeError,
    default_project_filename,
    default_storage_dir,
)
from utils.translate import _
from utils.logging import init_logging
from __version__ import __version__
from pydicom._version import __version__ as pydicom_version
from pynetdicom._version import __version__ as pynetdicom_version

# The following unused imports are for pyinstaller
# TODO: pyinstaller cmd line special import doesn't work
from pydicom.encoders import (
    pylibjpeg,
    gdcm,
)

from view.settings_dialog import SettingsDialog
from view.dashboard import Dashboard
from view.progress_dialog import ProgressDialog
from view.query_retrieve_import import QueryView
from view.export import ExportView
from view.html_view import HTMLView
from view.welcome import WelcomeView

from controller.project import ProjectController, ProjectModel

logger = logging.getLogger()  # ROOT logger

APP_TITLE = _("RSNA DICOM Anonymizer BETA Version " + __version__)

class App(ctk.CTk):
    project_open_startup_dwell_time = 500  # milliseconds
    menu_font=("", 13) 

    def new_project(self):
        logging.info("New Project")
        self.disable_file_menu()

        dlg = SettingsDialog(
            parent=self, model=ProjectModel(), new_model=True, title=_("New Project Settings")
        )
        self._model = dlg.get_input()
        if self._model is None:
            logger.info("New Project Cancelled")
        else:
            assert self._model
            logger.info(f"New ProjectModel: {self._model}")
            self._project_controller = ProjectController(self._model)
            assert self._project_controller
            self._project_controller.save_model()
            self._open_project()

        self.enable_file_menu()

    def open_project(self):
        self.disable_file_menu()

        logging.info("Open Project")
        path = filedialog.askdirectory(
            initialdir=default_storage_dir(),
            title=_("Select Anonymizer Storage Directory"),
        )
        if not path:
            logger.info(f"Open Project Cancelled")
            self.enable_file_menu()
            return

        project_pkl_path = Path(path, default_project_filename())
        if os.path.exists(project_pkl_path):
            with open(project_pkl_path, "rb") as pkl_file:
                self._model = pickle.load(pkl_file)
            logger.info(f"Project Model loaded from: {project_pkl_path}")
            self._project_controller = ProjectController(self._model)
            assert self._project_controller
            logger.info(f"{self._project_controller}")
            self._open_project()
        else:
            messagebox.showerror(
                title=_("Open Project Error"),
                message=f"Project file not found in: {path}",
                parent=self
            )
    

        self.enable_file_menu()

    def _open_project_startup(self):
        logger.info(f"Default font: {ctk.CTkFont().actual()}")
        if sys.platform.startswith("win"):
            self.iconbitmap(default="assets\\images\\rsna_icon.ico") 
        project_pkl_path = Path(default_storage_dir(), default_project_filename())
        if os.path.exists(project_pkl_path):
            with open(project_pkl_path, "rb") as pkl_file:
                self._model = pickle.load(pkl_file)
            logger.info(f"Project Model loaded from: {project_pkl_path}")
            self._project_controller = ProjectController(self._model)
            assert self._project_controller
            logger.info(f"{self._project_controller}")
            self._open_project()

    def _open_project(self):
        assert self._model
        assert self._project_controller
        try:
            self._project_controller.start_scp()
        except DICOMRuntimeError as e:
            messagebox.showerror(
                title=_("Local DICOM Server Error"),
                message=str(e),
                parent=self
            )
            return

        self.title(
            f"{self._model.project_name}[{self._model.site_id}] => {self._model.abridged_storage_dir()}"
        )
        
        self._welcome_view.destroy()
        self.dashboard = Dashboard(self, self._project_controller)
        self.protocol("WM_DELETE_WINDOW", self.close_project)
        self.set_menu_project_open()

    def close_project(self, event=None):
        logging.info("Close Project")
        if self._query_view and self._query_view.busy():
            logger.info(f"QueryView busy, cannot close project")
            messagebox.showerror(
                title=_("Query Busy"),
                message=_(
                    f"Query is busy, please wait for query to complete before closing project."
                ),
                parent=self
            )
            return
        if self._export_view and self._export_view.busy():
            logger.info(f"ExportView busy, cannot close project")
            messagebox.showerror(
                title=_("Export Busy"),
                message=_(
                    f"Export is busy, please wait for export to complete before closing project."
                ),
                parent=self
            )
            return
        if self._project_controller:
            self._project_controller.shutdown()
            self._project_controller.save_model()
            self._project_controller.anonymizer.save_model()
            self._project_controller.anonymizer.stop()
            del self._project_controller.anonymizer
            del self._project_controller
            if self._query_view:
                self._query_view.destroy()
                self._query_view = None
            if self._export_view:
                self._export_view.destroy()
                self._export_view = None
            
            self._welcome_view = WelcomeView(self)
            self.protocol("WM_DELETE_WINDOW", self.quit)
            self.focus_force()
            
        self._project_controller = None
        self.set_menu_project_closed()

    def import_files(self, event=None):
        assert self._project_controller

        logging.info("Import Files")
        file_extension_filters = [
            ("dcm Files", "*.dcm"),
            ("dicom Files", "*.dicom"),
            ("All Files", "*.*"),
        ]
        paths = filedialog.askopenfilenames(
            title=_("Select DICOM Files to Import & Anonymize"),
            defaultextension=".dcm",
            filetypes=file_extension_filters,
        )
        if paths:
            for path in paths:
                self._project_controller.anonymizer.anonymize_dataset_and_store(
                    path, None, self._project_controller.storage_dir
                )
        if len(paths) > 30:
            dlg = ProgressDialog(
                self._project_controller.anonymizer._anon_Q,
                title=_("Import Files Progress"),
                sub_title=_(f"Import {len(paths)} files"),
            )
            dlg.get_input()

    def import_directory(self, event=None):
        assert self._project_controller
        logging.info("Import Directory")
        root_dir = filedialog.askdirectory(
            title=_("Select DICOM Directory to Impport & Anonymize")
        )
        logger.info(root_dir)

        if root_dir:
            file_paths = [
                os.path.join(root, file)
                for root, _, files in os.walk(root_dir)
                for file in files
                if not file.startswith(".")  # and is_dicom(os.path.join(root, file))
            ]
            logger.info(f"Importing {len(file_paths)} files, adding to anonymizer Q")
            for path in file_paths:
                self._project_controller.anonymizer.anonymize_dataset_and_store(
                    path, None, self._project_controller.storage_dir
                )
        dlg = ProgressDialog(
            self,
            self._project_controller.anonymizer._anon_Q,
            title=_("Import Directory Progress"),
            sub_title=_(f"Import files from {root_dir}"),
        )
        dlg.get_input()

    def query_retrieve(self):
        assert self._project_controller
        if self._query_view and self._query_view.winfo_exists():
            logger.info(f"QueryView already OPEN")
            self._query_view.deiconify()
            self._query_view.focus_force()
            return

        logging.info("OPEN QueryView")
        self._query_view = QueryView(self, self._project_controller)
        self._query_view.focus()

    def export(self):
        assert self._project_controller
        if self._export_view and self._export_view.winfo_exists():
            logger.info(f"ExportView already OPEN")
            self._export_view.deiconify()
            self._export_view.focus_force()
            return

        logging.info("OPEN ExportView")
        self._export_view = ExportView(self, self._project_controller)
        self._export_view.focus()

    def settings(self):
        logging.info("Settings")
        assert self._model
        assert self._project_controller
        if self._query_view and self._query_view.busy():
            logger.info(f"QueryView busy, cannot open SettingsDialog")
            messagebox.showerror(
                title=_("Query Busy"),
                message=_(
                    f"Query is busy, please wait for query to complete before changing settings."
                ),
                parent=self
            )
            return
        if self._export_view and self._export_view.busy():
            logger.info(f"ExportView busy, cannot open SettingsDialog")
            messagebox.showerror(
                title=_("Export Busy"),
                message=_(
                    f"Export is busy, please wait for export to complete before changing settings."
                ),
                parent=self
            )
            return
        dlg = SettingsDialog(self, self._model, title=_("Project Settings"))
        edited_model = dlg.get_input()
        if edited_model is None:
            logger.info("Settings Cancelled")
            return
        logger.info(f"Edited ProjectModel")

        # TODO: model equality check
        # if edited_model == self._model:
        #     return
        self._model = edited_model
        self._project_controller.model = self._model
        self._project_controller._post_model_update()
        logger.info(f"{self._project_controller}")

    def instructions(self):
        if self._instructions_view and self._instructions_view.winfo_exists():
            logger.info(f"Instructions HTMLView already OPEN")
            self._instructions_view.deiconify()  
            return 
        
        logging.info("OPEN Instructions HTMLView")
        self._instructions_view = HTMLView(
            self,
            title=_(f"Instructions"),
            html_file_path="assets/html/instructions.html",
        )
        self._instructions_view.focus()
        
    def view_license(self):
        if self._license_view and self._license_view.winfo_exists():
            logger.info(f"License HTMLView already OPEN")
            self._license_view.deiconify()
            self._license_view.focus_force()
            return

        logging.info("OPEN License HTMLView")
        self._license_view = HTMLView(
            self,
            title=_(f"License"),
            html_file_path="assets/html/license.html",
        )
        self._license_view.focus()

    def get_help_menu(self):
        help_menu = tk.Menu(self.menu_bar, tearoff=0)
        help_menu.add_command(label=_("Instructions"), font=self.menu_font, command=self.instructions)
        help_menu.add_command(label=_("View License"), font=self.menu_font, command=self.view_license)
        return help_menu

    def set_menu_project_closed(self):
        
        # Setup menu bar:
        if hasattr(self, "menu_bar"):
            self.menu_bar.destroy()

        # font does not effect main menu items, only sub-menus on windows
        self.menu_bar = tk.Menu(master=self) 

        # File Menu:
        file_menu = tk.Menu(self, tearoff=0)
        file_menu.add_command(
            label=_("New Project"),
            font=self.menu_font,
            command=self.new_project,  # accelerator="Command+N"
        )
        file_menu.add_command(
            label=_("Open Project"),
            font=self.menu_font,
            command=self.open_project,  # accelerator="Command+O"
        )
        self.menu_bar.add_cascade(label=_("File"), menu=file_menu)

        # Help Menu:
        self.menu_bar.add_cascade(label=_("Help"), menu=self.get_help_menu())
        self.config(menu=self.menu_bar)

    def set_menu_project_open(self):
        # Reset menu bar:
        if hasattr(self, "menu_bar"):
            self.menu_bar.delete(0, tk.END)
        self.menu_bar = tk.Menu(self)

        # File Menu:
        file_menu = tk.Menu(self, tearoff=0)
        file_menu.add_command(
            label=_("Import Files"),
            font=self.menu_font,
            command=self.import_files,  # accelerator="Command+F"
        )
        file_menu.add_command(
            label=_("Import Directory"),
            font=self.menu_font,
            command=self.import_directory,
            # accelerator="Command+D",
        )

        # file_menu.add_command(
        #     label=_("Query & Retrieve"),
        #     command=self.query_retrieve,
        #     # accelerator="Command+R",
        # )
        # file_menu.add_command(
        #     label=_("Export"),
        #     command=self.export,
        #     # accelerator="Command+E",
        # )
        file_menu.add_separator()
        file_menu.add_command(
            label=_("Close Project"),
            font=self.menu_font,
            command=self.close_project,
            # accelerator="Command+P",
        )
        self.menu_bar.add_cascade(label=_("File"), font=self.menu_font, menu=file_menu)

        # View Menu:
        view_menu = tk.Menu(self, tearoff=0)
        view_menu.add_command(
            label=_("Project"),
            font=self.menu_font,
            command=self.settings,
            # accelerator="Command+S",
        )
        self.menu_bar.add_cascade(label=_("Settings"), menu=view_menu)

        # Help Menu:
        self.menu_bar.add_cascade(label=_("Help"), menu=self.get_help_menu())
        self.config(menu=self.menu_bar)

    def disable_file_menu(self):
        self.menu_bar.entryconfig(_("File"), state="disabled")

    def enable_file_menu(self):
        self.menu_bar.entryconfig(_("File"), state="normal")

    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("System")  # Modes: "System" (standard), "Dark", "Light"
        ctk.set_default_color_theme("assets/themes/rsna_theme.json") 

        self._project_controller: ProjectController = None
        self._model: ProjectModel = None
        self._query_view: QueryView = None
        self._export_view: ExportView = None
        self._instructions_view: HTMLView = None
        self._license_view: HTMLView = None
        self.resizable(False, False)
        self.title(APP_TITLE)
        self.set_menu_project_closed()  # creates self.menu_bar
        self._welcome_view = WelcomeView(self)
        self.after(self.project_open_startup_dwell_time, self._open_project_startup)


def main():
    args = str(sys.argv)

    install_dir = os.path.dirname(os.path.realpath(__file__))
    init_logging(install_dir)
    os.chdir(install_dir)

    logger = logging.getLogger()  # get root logger
    logger.info(f"cmd line args={args}")

    if "debug" in args:
        logger.info("DEBUG MODE")
        logger.setLevel(logging.DEBUG)

    logger.info(f"Starting ANONYMIZER GUI Version {__version__}")
    logger.info(f"Running from {os.getcwd()}")
    logger.info(f"Python Version: {sys.version_info.major}.{sys.version_info.minor}")
    logger.info(
        f"pydicom Version: {pydicom_version}, pynetdicom Version: {pynetdicom_version}"
    )

    # GUI
    app = App()

    # Pyinstaller splash page close
    if sys.platform.startswith("win"):
        try:
            import pyi_splash

            pyi_splash.close()  # type: ignore
        except Exception:
            pass

    app.mainloop()

    logger.info("ANONYMIZER GUI Stop.")


if __name__ == "__main__":
    main()
