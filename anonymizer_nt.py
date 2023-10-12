from math import log
import os, sys
from pathlib import Path
import logging
import pickle
from re import sub
import tkinter as tk
from tkinter import filedialog
import customtkinter as ctk
from CTkMessagebox import CTkMessagebox
from model.project import default_project_filename, default_storage_dir
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

import view.welcome as welcome
import view.help as help


from controller.project import ProjectController, ProjectModel, DICOMNode

logger = logging.getLogger()  # get ROOT logger

APP_TITLE = _("RSNA DICOM Anonymizer Version " + __version__)
APP_MIN_WIDTH = 800
APP_MIN_HEIGHT = 600
LOGO_WIDTH = 75
LOGO_HEIGHT = 20
PAD = 10


class App(ctk.CTk):
    default_local_server = DICOMNode("127.0.0.1", 1045, "ANONYMIZER", True)
    project_open_startup_dwell_time = 500  # milliseconds

    def new_project(self):
        logging.info("New Project")
        self.disable_file_menu()

        dlg = SettingsDialog(
            model=ProjectModel(), new_model=True, title=_("New Project Settings")
        )
        self.model = dlg.get_input()
        if self.model is None:
            logger.info("New Project Cancelled")
        else:
            assert self.model
            logger.info(f"New ProjectModel: {self.model}")
            self.project_controller = ProjectController(self.model)
            assert self.project_controller
            self.project_controller.save_model()
            # self.export_view = export.create_view(
            #     self.main_frame, PAD, self.project_controller
            # )
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
                self.model = pickle.load(pkl_file)
            logger.info(f"Project Model loaded from: {project_pkl_path}")
            self.project_controller = ProjectController(self.model)
            assert self.project_controller
            logger.info(f"{self.project_controller}")
            self._open_project()
        else:
            CTkMessagebox(
                title=_("Open Project Error"),
                message=f"Project file not found in: {path}",
                icon="cancel",
            )

        self.enable_file_menu()

    def _open_project_startup(self):
        project_pkl_path = Path(default_storage_dir(), default_project_filename())
        if os.path.exists(project_pkl_path):
            with open(project_pkl_path, "rb") as pkl_file:
                self.model = pickle.load(pkl_file)
            logger.info(f"Project Model loaded from: {project_pkl_path}")
            self.project_controller = ProjectController(self.model)
            assert self.project_controller
            logger.info(f"{self.project_controller}")
            self._open_project()

    def _open_project(self):
        assert self.model
        assert self.project_controller
        self.title(
            f"{self.model.project_name}[{self.model.site_id}] => {self.model.abridged_storage_dir()}"
        )
        self.main_frame.destroy()
        self.create_main_frame()
        self.dashboard = Dashboard(self.main_frame, self.project_controller)
        # self.dashboard.pack(expand=True, fill="both")
        self.set_menu_project_open()
        self.dashboard.focus_force()
        self.protocol("WM_DELETE_WINDOW", self.close_project)

    def close_project(self, event=None):
        logging.info("Close Project")
        if self.project_controller:
            self.project_controller.shutdown()
            self.project_controller.save_model()
            self.project_controller.anonymizer.save_model()
            del self.project_controller.anonymizer
            del self.project_controller
            if self._query_view:
                self._query_view.destroy()
                self._query_view = None
            if self.export_window:
                self.export_window.destroy()
                self.export_window = None
            self.main_frame.destroy()
            self.create_main_frame()
            self.welcome_view = welcome.create_view(self.main_frame)
            self.title(APP_TITLE)
            self.protocol("WM_DELETE_WINDOW", self.quit)
        self.project_controller = None
        self.set_menu_project_closed()

    # File Menu when project is open:
    def import_files(self, event=None):
        assert self.project_controller

        logging.info("Import Files")
        file_extension_filters = [
            ("dcm Files", "*.dcm"),
            ("dicom Files", "*.dicom"),
            ("All Files", "*.*"),
        ]
        paths = filedialog.askopenfilenames(filetypes=file_extension_filters)
        if paths:
            for path in paths:
                self.project_controller.anonymizer.anonymize_dataset_and_store(
                    path, None, self.project_controller.storage_dir
                )
        if len(paths) > 30:
            dlg = ProgressDialog(
                self.project_controller.anonymizer._anon_Q,
                title=_("Import Files Progress"),
                sub_title=_(f"Import {len(paths)} files"),
            )
            dlg.get_input()

    def import_directory(self, event=None):
        assert self.project_controller
        logging.info("Import Directory")
        root_dir = filedialog.askdirectory(title=_("Select DICOM Directory"))
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
                self.project_controller.anonymizer.anonymize_dataset_and_store(
                    path, None, self.project_controller.storage_dir
                )
        dlg = ProgressDialog(
            self.project_controller.anonymizer._anon_Q,
            title=_("Import Directory Progress"),
            sub_title=_(f"Import files from {root_dir}"),
        )
        dlg.get_input()

    def query_retrieve(self):
        assert self.project_controller
        if self._query_view and self._query_view.winfo_exists():
            logger.info(f"QueryView already OPEN")
            self._query_view.deiconify()
            self._query_view.focus_force()
            return

        logging.info("OPEN QueryView")
        self._query_view = QueryView(self, self.project_controller)
        # self._query_view.display()  # blocks until window is closed
        # logger.info(f"QueryView CLOSED")
        # self._query_view = None

    def export(self):
        assert self.project_controller
        if self._export_view and self._export_view.winfo_exists():
            logger.info(f"ExportView already OPEN")
            self._export_view.deiconify()
            self._export_view.focus_force()
            return

        logging.info("OPEN ExportView")
        self._export_view = ExportView(self, self.project_controller)

    # View Menu:
    def settings(self):
        assert self.model
        assert self.project_controller
        logging.info("Settings")
        dlg = SettingsDialog(self.model, title=_("Project Settings"))
        edited_model = dlg.get_input()
        if edited_model is None:
            logger.info("Settings Cancelled")
            return
        logger.info(f"Edited ProjectModel: {self.model}")
        # TODO: model equality check
        # if edited_model == self.model:
        #     return
        self.model = edited_model
        self.project_controller.model = self.model
        self.project_controller.save_model()
        self.project_controller.stop_scp()
        self.project_controller.start_scp()

    # Help Menu:
    def instructions(self):
        logging.info("Instructions")

        class ToplevelWindow(ctk.CTkToplevel):
            def __init__(self, parent):
                super().__init__(parent)
                self.geometry(f"{1000}x{800}")
                self.title(_(f"{APP_TITLE} Instructions"))
                self.rowconfigure(0, weight=1)
                self.columnconfigure(0, weight=1)
                self.help_frame = ctk.CTkFrame(self)
                self.help_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nswe")
                self.help_view = help.create_view(self.help_frame)

        if self.help_window is None or not self.help_window.winfo_exists():
            self.help_window = ToplevelWindow(self)

        self.help_window.focus_force()

    def view_license(self):
        logging.info("View License")

    def get_help_menu(self):
        help_menu = tk.Menu(self.menu_bar, tearoff=0)
        help_menu.add_command(label=_("Instructions"), command=self.instructions)
        help_menu.add_command(label=_("View License"), command=self.view_license)
        return help_menu

    def set_menu_project_closed(self):
        # Setup menu bar:
        if hasattr(self, "menu_bar"):
            self.menu_bar.destroy()
        self.menu_bar = tk.Menu(self)

        # File Menu:
        file_menu = tk.Menu(self, tearoff=0)
        file_menu.add_command(
            label=_("New Project"),
            command=self.new_project,  # accelerator="Command+N"
        )
        file_menu.add_command(
            label=_("Open Project"),
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
            command=self.import_files,  # accelerator="Command+F"
        )
        file_menu.add_command(
            label=_("Import Directory"),
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
            command=self.close_project,
            # accelerator="Command+P",
        )
        self.menu_bar.add_cascade(label=_("File"), menu=file_menu)

        # View Menu:
        view_menu = tk.Menu(self, tearoff=0)
        view_menu.add_command(
            label=_("Project"),
            command=self.settings,
            # accelerator="Command+S",
        )
        self.menu_bar.add_cascade(label=_("Settings"), menu=view_menu)

        # Window Menu:
        # window_menu = tk.Menu(self, tearoff=0)
        # window_menu.add_command(label=_("Main Window"))
        # self.menu_bar.add_cascade(label=_("Window"), menu=window_menu)

        # Help Menu:
        self.menu_bar.add_cascade(label=_("Help"), menu=self.get_help_menu())
        self.config(menu=self.menu_bar)

    def disable_file_menu(self):
        self.menu_bar.entryconfig(_("File"), state="disabled")

    def enable_file_menu(self):
        self.menu_bar.entryconfig(_("File"), state="normal")

    def create_main_frame(self):
        self.main_frame = ctk.CTkFrame(self)
        self.main_frame.grid(row=0, column=0, padx=PAD, pady=PAD)

    def __init__(
        self,
        color_theme,
        title,
        logo_file,
        logo_width,
        logo_height,
        pad,
    ):
        super().__init__()
        ctk.set_appearance_mode("System")  # Modes: "System" (standard), "Dark", "Light"
        ctk.set_default_color_theme(color_theme)  # sets all colors and default font:
        self.iconbitmap("assets\\images\\rsna_icon.ico")

        # self.protocol("WM_DELETE_WINDOW", self.close_project)
        self.project_controller = None
        self.model = None
        self._query_view = None
        self._export_view = None
        self.help_window = None

        # self.minsize(APP_MIN_WIDTH, APP_MIN_HEIGHT)  # width, height
        # self.geometry(f"{APP_MIN_WIDTH}x{APP_MIN_HEIGHT}")
        self.resizable(False, False)
        self.font = ctk.CTkFont()  # get default font as defined in json file
        self.title(title)
        self.title_height = self.font.metrics("linespace")

        self.set_menu_project_closed()  # creates self.menu_bar

        # Bind keyboard shortcuts:
        # self.bind_all("<Command-n>", self.new_project)
        # self.bind_all("<Command-o>", self.open_project)
        # self.bind_all("<Command-p>", self.close_project)
        # self.bind_all("<Command-f>", self.import_files)
        # self.bind_all("<Command-d>", self.import_directory)
        # self.bind_all("<Command-r>", self.query_retrieve)
        # self.bind_all("<Command-s>", self.settings)
        # self.bind_all("<Command-l>", self.logs)

        # Logo:
        # self.logo = ctk.CTkImage(
        #     light_image=Image.open(logo_file),
        #     size=(logo_width, logo_height),
        # )
        # self.logo = ctk.CTkLabel(self, image=self.logo, text="")
        # self.logo.grid(
        #     row=0,
        #     column=0,
        #     padx=pad,
        #     pady=(pad, 0),
        #     sticky="nw",
        # )
        # self.bind("<Unmap>", self.OnUnmap)
        # self.bind("<Map>", self.OnMap)

        self.create_main_frame()
        self.welcome_view = welcome.create_view(self.main_frame)
        self.after(self.project_open_startup_dwell_time, self._open_project_startup)


def main():
    # TODO: handle command line arguments, implement command line interface
    install_dir = os.path.dirname(os.path.realpath(__file__))
    init_logging(install_dir)
    os.chdir(install_dir)

    startup_msg = f"Starting ANONYMIZER GUI Version {__version__}"
    logger = logging.getLogger()  # get root logger
    logger.info(startup_msg)
    logger.info(f"Running from {os.getcwd()}")
    logger.info(
        f"pydicom Version: {pydicom_version}, pynetdicom Version: {pynetdicom_version}"
    )

    # GUI
    app = App(
        color_theme=install_dir + "/assets/themes/rsna_color_scheme_font.json",
        title=APP_TITLE,
        logo_file=install_dir + "/assets/images/rsna_logo_alpha.png",
        logo_width=LOGO_WIDTH,
        logo_height=LOGO_HEIGHT,
        pad=PAD,
    )

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
