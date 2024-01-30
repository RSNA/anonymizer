import os, sys, json
from pathlib import Path
import logging
import pickle
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk
from model.project import DICOMRuntimeError, ProjectModel

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


class App(ctk.CTk):
    TITLE = _("RSNA DICOM Anonymizer BETA Version " + __version__)
    THEME_FILE = "assets/themes/rsna_theme.json"
    CONFIG_FILENAME = "config.json"

    project_open_startup_dwell_time = 500  # milliseconds
    menu_font = ("", 13)

    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("System")  # Modes: "System" (standard), "Dark", "Light"
        theme = self.THEME_FILE
        if not os.path.exists(theme):
            logger.error(f"Theme file not found: {theme}, reverting to dark-blue theme")
            theme = "dark-blue"
        ctk.set_default_color_theme(theme)
        if sys.platform.startswith("win"):
            self.iconbitmap(
                "assets\\images\\rsna_icon.ico", default="assets\\images\\rsna_icon.ico"
            )

        self._project_controller: ProjectController = None
        self._model: ProjectModel = None
        self._query_view: QueryView = None
        self._export_view: ExportView = None
        self._instructions_view: HTMLView = None
        self._license_view: HTMLView = None
        self._dashboard: Dashboard = None
        self.resizable(False, False)
        self.title(self.TITLE)
        self.recent_project_dirs: list[str] = []
        self.current_open_project_dir: str = None
        self.load_config()
        self.set_menu_project_closed()  # creates self.menu_bar, populates Open Recent list
        self._welcome_view = WelcomeView(self)
        self.after(self.project_open_startup_dwell_time, self._open_project_startup)

    def load_config(self):
        try:
            with open(self.CONFIG_FILENAME, "r") as config_file:
                try:
                    config_data = json.load(config_file)
                except Exception as e:
                    logger.error("Config file corrupt, start with no global config set")
                    return

                self.recent_project_dirs = list(
                    set(config_data.get("recent_project_dirs", []))
                )
                for dir in self.recent_project_dirs:
                    if not os.path.exists(dir):
                        self.recent_project_dirs.remove(dir)
                self.current_open_project_dir = config_data.get(
                    "current_open_project_dir"
                )
                if not os.path.exists(self.current_open_project_dir):
                    self.current_open_project_dir = None
        except FileNotFoundError:
            warn_msg = _(
                f"Config file not found: {self.CONFIG_FILENAME}, no recent project list or current project set"
            )
            logger.warning(warn_msg)

    def save_config(self):
        try:
            config_data = {
                "recent_project_dirs": self.recent_project_dirs,
                "current_open_project_dir": self.current_open_project_dir or "",
            }
            with open(self.CONFIG_FILENAME, "w") as config_file:
                json.dump(config_data, config_file, indent=2)
        except Exception as e:
            err_msg = _(
                f"Error writing json config file: {self.CONFIG_FILENAME} {str(e)}"
            )
            logger.error(err_msg)
            messagebox.showerror(
                title=_("Configuration File Write Error"),
                message=err_msg,
                parent=self,
            )

    def new_project(self):
        logging.info("New Project")
        self.disable_file_menu()

        dlg = SettingsDialog(
            parent=self,
            model=ProjectModel(),
            new_model=True,
            title=_("New Project Settings"),
        )
        self._model = dlg.get_input()
        if self._model is None:
            logger.info("New Project Cancelled")
        else:
            assert self._model
            logger.info(f"New ProjectModel: {self._model}")
            self._project_controller = ProjectController(self._model)
            assert self._project_controller

            project_dir = str(self._project_controller.storage_dir)
            if os.path.exists(project_dir):
                confirm = messagebox.askyesno(
                    title=_("Confirm Overwrite"),
                    message=_(
                        "The project directory already exists. Do you want to overwrite the existing project?"
                    ),
                    parent=self,
                )
                if not confirm:
                    logger.info("New Project Cancelled")
                    self.enable_file_menu()
                    return

            self._project_controller.save_model()
            if project_dir not in self.recent_project_dirs:
                self.recent_project_dirs.insert(0, project_dir)
            self.current_open_project_dir = project_dir
            self._open_project()

        self.enable_file_menu()

    def open_project(self, project_dir: str = None):
        self.disable_file_menu()

        logging.info(f"Open Project project_dir={project_dir}")

        if project_dir is None:
            project_dir = filedialog.askdirectory(
                initialdir=ProjectModel.default_storage_dir(),
                title=_("Select Anonymizer Storage Directory"),
            )

        if not project_dir:
            logger.info(f"Open Project Cancelled")
            self.enable_file_menu()
            return

        project_pkl_path = Path(project_dir, ProjectModel.default_project_filename())

        if os.path.exists(project_pkl_path):
            with open(project_pkl_path, "rb") as pkl_file:
                self._model = pickle.load(pkl_file)
            logger.info(f"Project Model loaded from: {project_pkl_path}")
            self._project_controller = ProjectController(self._model)
            assert self._project_controller
            logger.info(f"{self._project_controller}")
            if not project_dir in self.recent_project_dirs:
                self.recent_project_dirs.insert(0, project_dir)
            self.current_open_project_dir = project_dir
            self.save_config()
            self._open_project()
        else:
            messagebox.showerror(
                title=_("Open Project Error"),
                message=_(f"Project file not found in: \n\n{project_dir}"),
                parent=self,
            )
            self.recent_project_dirs.remove(project_dir)
            self.set_menu_project_closed()
            self.save_config()

        self.enable_file_menu()

    def _open_project_startup(self):
        if self.current_open_project_dir:
            self.open_project(self.current_open_project_dir)

    def _open_project(self):
        assert self._model
        assert self._project_controller
        try:
            self._project_controller.start_scp()
        except DICOMRuntimeError as e:
            messagebox.showerror(
                title=_("Local DICOM Server Error"), message=str(e), parent=self
            )

        self.title(
            f"{self._model.project_name}[{self._model.site_id}] => {self._model.abridged_storage_dir()}"
        )

        self._welcome_view.destroy()
        self._dashboard = Dashboard(self, self._project_controller)
        self.protocol("WM_DELETE_WINDOW", self.close_project)
        self.set_menu_project_open()
        self._dashboard.focus_set()

    def close_project(self, event=None):
        logging.info("Close Project")
        if self._query_view and self._query_view.busy():
            logger.info(f"QueryView busy, cannot close project")
            messagebox.showerror(
                title=_("Query Busy"),
                message=_(
                    f"Query is busy, please wait for query to complete before closing project."
                ),
                parent=self,
            )
            return
        if self._export_view and self._export_view.busy():
            logger.info(f"ExportView busy, cannot close project")
            messagebox.showerror(
                title=_("Export Busy"),
                message=_(
                    f"Export is busy, please wait for export to complete before closing project."
                ),
                parent=self,
            )
            return
        if self._dashboard:
            self._dashboard.destroy()
            self._dashboard = None
        if self._project_controller:
            self._project_controller.shutdown()
            self._project_controller.save_model()
            self._project_controller.anonymizer.save_model()
            self._project_controller.anonymizer.stop()
            if self._query_view:
                self._query_view.destroy()
                self._query_view = None
            if self._export_view:
                self._export_view.destroy()
                self._export_view = None

            self._welcome_view = WelcomeView(self)
            self.protocol("WM_DELETE_WINDOW", self.quit)
            self.focus_force()

        self.current_open_project_dir = None
        self._project_controller = None
        self.set_menu_project_closed()
        self.title(self.TITLE)
        self.save_config()

    def clone_project(self, event=None):
        logging.info("Clone Project")

        current_project_dir = self._project_controller.storage_dir

        cloned_project_dir = filedialog.askdirectory(
            initialdir=current_project_dir.parent,
            message=_("Select Directory for Cloned Project"),
            mustexist=False,
            parent=self,
        )

        if not cloned_project_dir:
            logger.info(f"Clone Project Cancelled")
            return

        assert os.path.exists(cloned_project_dir)

        if cloned_project_dir == current_project_dir:
            logger.info(
                f"Clone Project Cancelled, cloned directory same as current project directory"
            )
            messagebox.showerror(
                title=_("Clone Project Error"),
                message=_(
                    f"Cloned directory cannot be the same as the current project directory."
                ),
                parent=self,
            )
            return

        self._project_controller.save_model(cloned_project_dir)
        self.close_project()

        project_pkl_path = Path(
            cloned_project_dir, ProjectModel.default_project_filename()
        )

        with open(project_pkl_path, "rb") as pkl_file:
            self._model = pickle.load(pkl_file)

        logger.info(f"Project Model loaded from: {project_pkl_path}")
        # Change storage directory and site_id of clonded model:
        self._model.storage_dir = Path(cloned_project_dir)
        self._model.regenerate_site_id()
        self._project_controller = ProjectController(self._model)
        assert self._project_controller
        logger.info(f"{self._project_controller}")
        if not cloned_project_dir in self.recent_project_dirs:
            self.recent_project_dirs.insert(0, cloned_project_dir)
        self.current_open_project_dir = cloned_project_dir
        self.save_config()
        self._open_project()

    def import_files(self, event=None):
        assert self._project_controller

        logging.info("Import Files")
        file_extension_filters = [
            ("dcm Files", "*.dcm"),
            ("dicom Files", "*.dicom"),
            ("All Files", "*.*"),
        ]
        msg = _("Select DICOM Files to Import & Anonymize")
        paths = filedialog.askopenfilenames(
            message=msg,
            defaultextension=".dcm",
            filetypes=file_extension_filters,
            parent=self,
        )
        if not paths:
            logger.info(f"Import Files Cancelled")
            return
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
        msg = _("Select DICOM Directory to Impport & Anonymize")
        root_dir = filedialog.askdirectory(
            message=msg,
            mustexist=True,
            parent=self,
        )
        logger.info(root_dir)

        if not root_dir:
            logger.info(f"Import Directory Cancelled")
            return

        file_paths = [
            os.path.join(root, file)
            for root, _, files in os.walk(root_dir)
            for file in files
            if not file.startswith(".")  # and is_dicom(os.path.join(root, file))
        ]
        if len(file_paths) == 0:
            logger.info(f"No DICOM files found in {root_dir}")
            messagebox.showerror(
                title=_("Import Directory Error"),
                message=f"No DICOM files found in {root_dir}",
                parent=self,
            )
            return
        logger.info(f"Importing {len(file_paths)} files, adding to anonymizer Q")
        for path in file_paths:
            self._project_controller.anonymizer.anonymize_dataset_and_store(
                path, None, self._project_controller.storage_dir
            )
        qsize = self._project_controller.anonymizer._anon_Q.qsize()
        logging.info(f"File load complete, monitoring anonymizer Q...{qsize}")
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
                parent=self,
            )
            return
        if self._export_view and self._export_view.busy():
            logger.info(f"ExportView busy, cannot open SettingsDialog")
            messagebox.showerror(
                title=_("Export Busy"),
                message=_(
                    f"Export is busy, please wait for export to complete before changing settings."
                ),
                parent=self,
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
        help_menu.add_command(
            label=_("Instructions"), font=self.menu_font, command=self.instructions
        )
        help_menu.add_command(
            label=_("View License"), font=self.menu_font, command=self.view_license
        )
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

        if self.recent_project_dirs:
            # Open Recent menu (cascaded)
            open_recent_menu = tk.Menu(file_menu, tearoff=0, name="open_recent_menu")
            file_menu.add_cascade(label=_("Open Recent"), menu=open_recent_menu)

            for directory in self.recent_project_dirs:
                open_recent_menu.add_command(
                    label=directory,
                    command=lambda dir=directory: self.open_project(dir),
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
            label=_("Clone Project"),
            font=self.menu_font,
            command=self.clone_project,
            # accelerator="Command+C",
        )
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


def main():
    args = str(sys.argv)
    install_dir = os.path.dirname(os.path.realpath(__file__))
    run_as_exe = getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")
    # TODO: enhance cmd line processing using Click library
    # TODO: run time log level change
    # may need user settable log level for pynetdicom and pydicom separately
    debug_mode = "debug" in args or "DEBUG" in args
    init_logging(install_dir, debug_mode, run_as_exe)
    os.chdir(install_dir)

    logger = logging.getLogger()  # get root logger
    logger.info(f"cmd line args={args}")
    if debug_mode:
        logger.info(f"DEBUG Mode")
    if run_as_exe:
        logger.info(f"Running as executable (PyInstaller)")
    logger.info(f"Python Optimization Level: {sys.flags.optimize}")
    logger.info(f"Starting ANONYMIZER GUI Version {__version__}")
    logger.info(f"Running from {os.getcwd()}")
    logger.info(f"Python Version: {sys.version_info.major}.{sys.version_info.minor}")
    logger.info(f"tkinter TkVersion: {tk.TkVersion} TclVersion: {tk.TclVersion}")
    logger.info(f"Customtkinter Version: {ctk.__version__}")
    logger.info(
        f"pydicom Version: {pydicom_version}, pynetdicom Version: {pynetdicom_version}"
    )

    # GUI
    try:
        app = App()
        logger.info("ANONYMIZER GUI Initialised successfully.")
    except Exception as e:
        logger.exception(f"Error starting ANONYMIZER GUI, exit: {str(e)}")
        sys.exit(1)

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
