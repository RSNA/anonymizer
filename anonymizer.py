import os, sys, json
from pathlib import Path
from copy import copy
import logging
import pickle
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk
from model.project import DICOMRuntimeError, ProjectModel

from utils.translate import _
from utils.logging import init_logging
from utils.storage import get_latest_pkl_file
from __version__ import __version__
from pydicom._version import __version__ as pydicom_version
from pydicom import dcmread
from pynetdicom._version import __version__ as pynetdicom_version

# The following unused imports are for pyinstaller
# TODO: pyinstaller cmd line special import doesn't work
from pydicom.encoders import (
    pylibjpeg,
    gdcm,
)

from view.settings.settings_dialog import SettingsDialog
from view.dashboard import Dashboard
from view.import_files_dialog import ImportFilesDialog
from view.query_retrieve_import import QueryView
from view.export import ExportView
from view.html_view import HTMLView
from view.welcome import WelcomeView

from controller.project import ProjectController, ProjectModel

logger = logging.getLogger()  # ROOT logger


class App(ctk.CTk):
    TITLE = _("RSNA DICOM Anonymizer Version " + __version__)
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
            self.iconbitmap("assets\\images\\rsna_icon.ico", default="assets\\images\\rsna_icon.ico")

        self.controller: ProjectController | None = None
        self.query_view: QueryView | None = None
        self.export_view: ExportView | None = None
        self.instructions_view: HTMLView | None = None
        self.license_view: HTMLView | None = None
        self.dashboard: Dashboard | None = None
        self.welcome_view = WelcomeView(self)
        self.resizable(False, False)
        self.title(self.TITLE)
        self.recent_project_dirs: list[Path] = []
        self.current_open_project_dir: Path | None = None
        self.load_config()
        self.set_menu_project_closed()  # creates self.menu_bar, populates Open Recent list
        self.after(self.project_open_startup_dwell_time, self._open_project_startup)

    def load_config(self):
        try:
            with open(self.CONFIG_FILENAME, "r") as config_file:
                try:
                    config_data = json.load(config_file)
                except Exception as e:
                    logger.error("Config file corrupt, start with no global config set")
                    return

                self.recent_project_dirs = list(set(config_data.get("recent_project_dirs", [])))
                for dir in self.recent_project_dirs:
                    if not os.path.exists(dir):
                        self.recent_project_dirs.remove(dir)
                self.current_open_project_dir = config_data.get("current_open_project_dir")
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
                "recent_project_dirs": [str(path) for path in self.recent_project_dirs],
                "current_open_project_dir": str(self.current_open_project_dir) or "",
            }
            with open(self.CONFIG_FILENAME, "w") as config_file:
                json.dump(config_data, config_file, indent=2)
        except Exception as e:
            err_msg = _(f"Error writing json config file: {self.CONFIG_FILENAME} {repr(e)}")
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
        model: ProjectModel | None = dlg.get_input()

        if model is None:
            logger.info("New Project Cancelled")
            self.enable_file_menu()
            return

        logger.info(f"New ProjectModel: {model}")

        if not model.storage_dir:
            logger.info("New Project Cancelled, storage directory not set")
            messagebox.showerror(
                title=_("New Project Error"),
                message=_(f"Storage Directory not set, please set a valid directory in project settings."),
                parent=self,
            )
            self.enable_file_menu()
            return

        if os.path.exists(model.storage_dir):
            confirm = messagebox.askyesno(
                title=_("Confirm Overwrite"),
                message=_("The project directory already exists. Do you want to overwrite the existing project?"),
                parent=self,
            )
            if not confirm:
                logger.info("New Project Cancelled")
                self.enable_file_menu()
                return

        try:
            self.controller = ProjectController(model)
            if not self.controller:
                raise RuntimeError("Fatal Internal Error, Project Controller not created")

            self.controller.save_model()
            self.current_open_project_dir = self.controller.model.storage_dir

            if self.current_open_project_dir not in self.recent_project_dirs:
                self.recent_project_dirs.insert(0, self.current_open_project_dir)
                self.save_config()

        except Exception as e:
            logger.error(f"Error creating Project Controller: {str(e)}")
            messagebox.showerror(
                title=_("New Project Error"),
                message=_(f"Error creating Project Controller:\n\n{str(e)}"),
                parent=self,
            )
        finally:
            self._open_project()
            self.enable_file_menu()

    def open_project(self, project_dir: Path | None = None):
        self.disable_file_menu()

        logging.info(f"Open Project project_dir={project_dir}")

        if project_dir is None:
            selected_dir = filedialog.askdirectory(
                initialdir=ProjectModel.default_storage_dir(),
                title=_("Select Anonymizer Storage Directory"),
            )

            if not selected_dir:
                logger.info(f"Open Project Cancelled")
                self.enable_file_menu()
                return

            project_dir = Path(selected_dir)

        # Get project pkl filename from project directory
        project_model_path = Path(project_dir, ProjectController.PROJECT_MODEL_FILENAME)

        if os.path.exists(project_model_path):
            try:
                with open(project_model_path, "rb") as pkl_file:
                    file_model = pickle.load(pkl_file)
                    if not isinstance(file_model, ProjectModel):
                        raise TypeError("Corruption detected: Loaded model is not an instance of ProjectModel")
            except Exception as e:
                logger.error(f"Error loading Project Model: {str(e)}")
                # TODO: load from last backup
                messagebox.showerror(
                    title=_("Open Project Error"),
                    message=_(f"Error loading Project Model from data file: {project_model_path}\n\n{str(e)}"),
                    parent=self,
                )
                self.enable_file_menu()
                return

            logger.info(f"Project Model succesfully loaded from: {project_model_path}")

            if not hasattr(file_model, "version"):
                logger.error(f"Project Model missing version")
                messagebox.showerror(
                    title=_("Open Project Error"),
                    message=_(f"Project File corrupted, missing version information."),
                    parent=self,
                )
                self.enable_file_menu()
                return

            logger.info(f"Project Model loaded successfully, version: {file_model.version}")

            if file_model.version != ProjectModel.MODEL_VERSION:
                logger.info(
                    f"Project Model version mismatch: {file_model.version} != {ProjectModel.MODEL_VERSION} upgrading accordingly"
                )
                model = ProjectModel()  # new default model
                # TODO: Handle 2 level nested classes/dicts copying by attribute
                # to handle addition or nested fields and deletion of attributes in new model
                model = copy(file_model)  # copy over corresponding attributes from the old model
                model.version = ProjectModel.MODEL_VERSION  # update to latest version
            else:
                model = file_model

            try:
                self.controller = ProjectController(model)
                if file_model.version != ProjectModel.MODEL_VERSION:
                    self.controller.save_model()
                    logger.info(f"Project Model upgraded successfully to version: {self.controller.model.version}")
            except Exception as e:
                logger.error(f"Error creating Project Controller: {str(e)}")
                messagebox.showerror(
                    title=_("Open Project Error"),
                    message=_(f"Error creating Project Controller:\n\n{str(e)}"),
                    parent=self,
                )
                self.enable_file_menu()
                return

            logger.info(f"{self.controller}")
            if not project_dir in self.recent_project_dirs:
                self.recent_project_dirs.insert(0, project_dir)
            self.current_open_project_dir = project_dir
            self.save_config()
            self._open_project()
        else:
            messagebox.showerror(
                title=_("Open Project Error"),
                message=_(f"No Project file not found in: \n\n{project_dir}"),
                parent=self,
            )
            if project_dir in self.recent_project_dirs:
                self.recent_project_dirs.remove(project_dir)
            self.set_menu_project_closed()
            self.save_config()

        self.enable_file_menu()

    def _open_project_startup(self):
        if self.current_open_project_dir:
            self.open_project(self.current_open_project_dir)

    def _open_project(self):

        if not self.controller:
            logger.info(f"Open Project Cancelled, no controller")
            return

        try:
            self.controller.start_scp()
        except DICOMRuntimeError as e:
            messagebox.showerror(title=_("Local DICOM Server Error"), message=str(e), parent=self)

        self.title(
            f"{self.controller.model.project_name}[{self.controller.model.site_id}] => {self.controller.model.abridged_storage_dir()}"
        )

        self.welcome_view.destroy()
        self.dashboard = Dashboard(
            self, query_callback=self.query_retrieve, export_callback=self.export, controller=self.controller
        )
        self.protocol("WM_DELETE_WINDOW", self.close_project)
        self.set_menu_project_open()
        self.dashboard.focus_set()

    def close_project(self, event=None):
        logging.info("Close Project")
        if self.query_view and self.query_view.busy():
            logger.info(f"QueryView busy, cannot close project")
            messagebox.showerror(
                title=_("Query Busy"),
                message=_(f"Query is busy, please wait for query to complete before closing project."),
                parent=self,
            )
            return
        if self.export_view and self.export_view.busy():
            logger.info(f"ExportView busy, cannot close project")
            messagebox.showerror(
                title=_("Export Busy"),
                message=_(f"Export is busy, please wait for export to complete before closing project."),
                parent=self,
            )
            return
        if self.dashboard:
            self.dashboard.destroy()
            self.dashboard = None
        if self.controller:
            self.controller.shutdown()
            self.controller.save_model()
            self.controller.anonymizer.save_model()
            self.controller.anonymizer.stop()
            if self.query_view:
                self.query_view.destroy()
                self.query_view = None
            if self.export_view:
                self.export_view.destroy()
                self.export_view = None

            self.welcome_view = WelcomeView(self)
            self.protocol("WM_DELETE_WINDOW", self.quit)
            self.focus_force()

        self.current_open_project_dir = None
        self.controller = None
        self.set_menu_project_closed()
        self.title(self.TITLE)
        self.save_config()

    def clone_project(self, event=None):
        logging.info("Clone Project")

        if not self.controller:
            logger.info(f"Clone Project Cancelled, no project open")
            messagebox.showerror(
                title=_("Clone Project Error"),
                message=_(f"No project open to clone."),
                parent=self,
            )
            return

        current_project_dir = self.controller.model.storage_dir

        cloned_project_dir = Path(
            filedialog.askdirectory(
                initialdir=current_project_dir.parent,
                title=_("Select Directory for Cloned Project"),
                mustexist=False,
                parent=self,
            )
        )

        if not cloned_project_dir:
            logger.info(f"Clone Project Cancelled")
            return

        assert os.path.exists(cloned_project_dir)

        if cloned_project_dir == current_project_dir:
            logger.info(f"Clone Project Cancelled, cloned directory same as current project directory")
            messagebox.showerror(
                title=_("Clone Project Error"),
                message=_(f"Cloned directory cannot be the same as the current project directory."),
                parent=self,
            )
            return

        self.controller.save_model(cloned_project_dir)
        self.close_project()

        project_pkl_path = Path(cloned_project_dir, ProjectController.PROJECT_MODEL_FILENAME)

        with open(project_pkl_path, "rb") as pkl_file:
            self.controller.model = pickle.load(pkl_file)

        logger.info(f"Project Model loaded from: {project_pkl_path}")

        # Change storage directory and site_id of cloned model:
        self.controller.model.storage_dir = cloned_project_dir
        self.controller.model.regenerate_site_id()

        try:
            self.controller = ProjectController(self.controller.model)
            logger.info(f"{self.controller}")
        except Exception as e:
            logger.error(f"Error creating Project Controller: {str(e)}")
            messagebox.showerror(
                title=_("Clone Project Error"),
                message=_(f"Error creating Project Controller:\n\n{str(e)}"),
                parent=self,
            )
            return

        if not cloned_project_dir in self.recent_project_dirs:
            self.recent_project_dirs.insert(0, cloned_project_dir)
        self.current_open_project_dir = cloned_project_dir
        self.save_config()
        self._open_project()

    def import_files(self, event=None):
        logging.info("Import Files")

        if not self.controller:
            logger.error("Internal Error: no ProjectController")
            return

        self.disable_file_menu()

        file_extension_filters = [
            ("dcm Files", "*.dcm"),
            ("dicom Files", "*.dicom"),
            ("All Files", "*.*"),
        ]
        msg = _("Select DICOM Files to Import & Anonymize")
        file_paths = filedialog.askopenfilenames(
            title=msg,
            defaultextension=".dcm",
            filetypes=file_extension_filters,
            parent=self,
        )

        if not file_paths:
            logger.info(f"Import Files Cancelled")
            self.enable_file_menu()
            return

        dlg = ImportFilesDialog(
            self,
            self.controller.anonymizer,
            file_paths,
            title=_("Import Files"),
            sub_title=_(f"Importing {len(file_paths)} {'file' if len(file_paths) == 1 else 'files'}"),
        )
        dlg.get_input()
        self.enable_file_menu()

    def import_directory(self, event=None):
        logging.info("Import Directory")

        if not self.controller:
            logger.error("Internal Error: no ProjectController")
            return

        self.disable_file_menu()

        msg = _("Select DICOM Directory to Impport & Anonymize")
        root_dir = filedialog.askdirectory(
            title=msg,
            mustexist=True,
            parent=self,
        )
        logger.info(root_dir)

        if not root_dir:
            logger.info(f"Import Directory Cancelled")
            self.enable_file_menu()
            return

        file_paths = []
        # Handle reading DICOMDIR files in Media Storage Directory (eg. CD/DVD/USB Drive)
        dicomdir_file = os.path.join(root_dir, "DICOMDIR")
        if os.path.exists(dicomdir_file):
            try:
                ds = dcmread(fp=dicomdir_file)
                root_dir = Path(str(ds.filename)).resolve().parent
                logger.info(f"DICOM DIR Root directory: {root_dir}\n")

                # Iterate through the PATIENT records
                for patient in ds.patient_records:
                    logger.info(f"PATIENT: PatientID={patient.PatientID}, " f"PatientName={patient.PatientName}")

                    # Find all the STUDY records for the patient
                    studies = [ii for ii in patient.children if ii.DirectoryRecordType == "STUDY"]
                    for study in studies:
                        descr = study.StudyDescription or "(no value available)"
                        logging.info(
                            f"{'  ' * 1}STUDY: StudyID={study.StudyID}, "
                            f"StudyDate={study.StudyDate}, StudyDescription={descr}"
                        )

                        # Find all the SERIES records in the study
                        all_series = [ii for ii in study.children if ii.DirectoryRecordType == "SERIES"]
                        for series in all_series:
                            # Find all the IMAGE records in the series
                            images = [ii for ii in series.children if ii.DirectoryRecordType == "IMAGE"]
                            plural = ("", "s")[len(images) > 1]

                            descr = getattr(series, "SeriesDescription", "(no value available)")
                            logging.info(
                                f"{'  ' * 2}SERIES: SeriesNumber={series.SeriesNumber}, "
                                f"Modality={series.Modality}, SeriesDescription={descr} - "
                                f"{len(images)} SOP Instance{plural}"
                            )

                            # Get the absolute file path to each instance
                            # Each IMAGE contains a relative file path to the root directory
                            elems = [ii["ReferencedFileID"] for ii in images]
                            # Make sure the relative file path is always a list of str
                            paths = [[ee.value] if ee.VM == 1 else ee.value for ee in elems]
                            paths = [f"{root_dir}/{Path(*fp)}" for fp in paths]

                            # List the instance file paths for this series
                            for fp in paths:
                                logger.info(f"{'  ' * 3}IMAGE: Path={os.fspath(fp)}")

                            file_paths.extend(paths)

            except Exception as e:
                logger.error(f"Error reading DICOMDIR file: {dicomdir_file}, {str(e)}")
                messagebox.showerror(
                    title=_("Import Directory Error"),
                    message=_(f"Error reading DICOMDIR file: {dicomdir_file}, {str(e)}"),
                    parent=self,
                )
                return
        else:
            file_paths = [
                os.path.join(root, file)
                for root, _, files in os.walk(root_dir)
                for file in files
                if not file.startswith(".")
            ]

        if len(file_paths) == 0:
            logger.info(f"No DICOM files found in {root_dir}")
            messagebox.showerror(
                title=_("Import Directory Error"),
                message=f"No DICOM files found in {root_dir}",
                parent=self,
            )
            self.enable_file_menu()
            return

        logger.info(f"Importing {len(file_paths)} {'file' if len(file_paths) == 1 else 'files'}")

        # TODO: optimize "already imported" by detecting patient/study/series hierarchy
        # and using uid_lookup table and file counts to determine if already imported

        logging.info(f"File paths load complete, starting Import Files Dialog...")

        dlg = ImportFilesDialog(
            self,
            self.controller.anonymizer,
            sorted(file_paths),
            title=_("Import Directory"),
            sub_title=_(f"Import files from {root_dir}"),
        )
        dlg.get_input()
        self.enable_file_menu()

    def query_retrieve(self):
        logging.info("OPEN QueryView")

        if not self.controller:
            logger.error("Internal Error: no ProjectController")
            return

        if self.query_view and self.query_view.winfo_exists():
            logger.info(f"QueryView already OPEN")
            self.query_view.deiconify()
            self.query_view.focus_force()
            return

        if not self.dashboard:
            logger.error("Internal Error: no Dashboard")
            return

        self.query_view = QueryView(self.dashboard, self.controller)
        self.query_view.focus()

    def export(self):
        logging.info("OPEN ExportView")

        if not self.controller:
            logger.error("Internal Error: no ProjectController")
            return

        if self.export_view and self.export_view.winfo_exists():
            logger.info(f"ExportView already OPEN")
            self.export_view.deiconify()
            self.export_view.focus_force()
            return

        if not self.dashboard:
            logger.error("Internal Error: no Dashboard")
            return

        self.export_view = ExportView(self.dashboard, self.controller)
        self.export_view.focus()

    def settings(self):
        logging.info("Settings")

        if not self.controller:
            logger.error("Internal Error: no ProjectController")
            return

        if self.query_view and self.query_view.busy():
            logger.info(f"QueryView busy, cannot open SettingsDialog")
            messagebox.showerror(
                title=_("Query Busy"),
                message=_(f"Query is busy, please wait for query to complete before changing settings."),
                parent=self,
            )
            return

        if self.export_view and self.export_view.busy():
            logger.info(f"ExportView busy, cannot open SettingsDialog")
            messagebox.showerror(
                title=_("Export Busy"),
                message=_(f"Export is busy, please wait for export to complete before changing settings."),
                parent=self,
            )
            return

        dlg = SettingsDialog(self, self.controller.model, title=_("Project Settings"))
        edited_model = dlg.get_input()
        if edited_model is None:
            logger.info("Settings Cancelled")
            return

        logger.info(f"User Edited ProjectModel")

        self.controller.model = edited_model
        self.controller.model = self.controller.model
        self.controller._post_model_update()
        logger.info(f"{self.controller}")

    def instructions(self):
        logging.info("OPEN Instructions HTMLView")

        if self.instructions_view and self.instructions_view.winfo_exists():
            logger.info(f"Instructions HTMLView already OPEN")
            self.instructions_view.deiconify()
            return

        self.instructions_view = HTMLView(
            self,
            title=_(f"Instructions"),
            html_file_path="assets/html/instructions.html",
        )
        self.instructions_view.focus()

    def view_license(self):
        logging.info("OPEN License HTMLView")

        if self.license_view and self.license_view.winfo_exists():
            logger.info(f"License HTMLView already OPEN")
            self.license_view.deiconify()
            self.license_view.focus_force()
            return

        self.license_view = HTMLView(
            self,
            title=_(f"License"),
            html_file_path="assets/html/license.html",
        )
        self.license_view.focus()

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

        if self.recent_project_dirs:
            # Open Recent menu (cascaded)
            open_recent_menu = tk.Menu(file_menu, tearoff=0, name="open_recent_menu")
            file_menu.add_cascade(label=_("Open Recent"), menu=open_recent_menu)

            for directory in self.recent_project_dirs:
                open_recent_menu.add_command(
                    label=str(directory),
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
    init_logging(install_dir, run_as_exe)
    os.chdir(install_dir)

    logger = logging.getLogger()  # get root logger
    logger.info(f"cmd line args={args}")
    if run_as_exe:
        logger.info(f"Running as executable (PyInstaller)")
    logger.info(f"Python Optimization Level: {sys.flags.optimize}")
    logger.info(f"Starting ANONYMIZER GUI Version {__version__}")
    logger.info(f"Running from {os.getcwd()}")
    logger.info(f"Python Version: {sys.version_info.major}.{sys.version_info.minor}")
    logger.info(f"tkinter TkVersion: {tk.TkVersion} TclVersion: {tk.TclVersion}")
    logger.info(f"Customtkinter Version: {ctk.__version__}")
    logger.info(f"pydicom Version: {pydicom_version}, pynetdicom Version: {pynetdicom_version}")

    # GUI
    try:
        app = App()
        logger.info("ANONYMIZER GUI Initialised successfully.")
    except Exception as e:
        logger.exception(f"Error starting ANONYMIZER GUI, exit: {str(e)}")
        sys.exit(1)

    # Pyinstaller splash page on Windows close
    if sys.platform.startswith("win"):
        try:
            import pyi_splash  # type: ignore

            pyi_splash.close()  # type: ignore
        except Exception:
            pass

    app.mainloop()

    logger.info("ANONYMIZER GUI Stop.")


if __name__ == "__main__":
    main()
