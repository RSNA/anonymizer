import faulthandler
import json
import logging
import os
import pickle
import platform
import shutil
import signal
import sys
import time
import tkinter as tk
from copy import copy
from pathlib import Path
from pprint import pformat
from tkinter import filedialog, messagebox, ttk

import click
import customtkinter as ctk
from customtkinter import ThemeManager
from pydicom import dcmread
from pydicom._version import __version__ as pydicom_version  # type: ignore
from pynetdicom._version import __version__ as pynetdicom_version  # type: ignore

from anonymizer.controller.project import ProjectController
from anonymizer.model.project import DICOMRuntimeError, ProjectModel
from anonymizer.utils.logging import init_logging
from anonymizer.utils.translate import (
    _,
    get_current_language,
    get_current_language_code,
    set_language,
)
from anonymizer.utils.version import get_version
from anonymizer.view.dashboard import Dashboard
from anonymizer.view.export import ExportView
from anonymizer.view.html_view import HTMLView
from anonymizer.view.import_files_dialog import ImportFilesDialog
from anonymizer.view.index import IndexView
from anonymizer.view.query_retrieve_import import QueryView
from anonymizer.view.settings.settings_dialog import SettingsDialog
from anonymizer.view.welcome import WelcomeView

faulthandler.enable()

logger = logging.getLogger()  # ROOT logger


class Anonymizer(ctk.CTk):
    THEME_FILE = "assets/themes/rsna_theme.json"

    project_open_startup_dwell_time = 100  # milliseconds
    metrics_loop_interval = 1000  # milliseconds

    def get_title(self) -> str:
        return _("RSNA DICOM Anonymizer Version").strip() + " " + get_version()

    def get_app_state_path(self) -> Path:
        return self.logs_dir / ".anonymizer_state.json"

    def __init__(self, logs_dir: Path):
        super().__init__()
        self.logs_dir: Path = logs_dir
        ctk.set_appearance_mode("System")  # Modes: "System" (standard), "Dark", "Light"
        theme = self.THEME_FILE
        if not os.path.exists(theme):
            logger.error(f"Theme file not found: {theme}, reverting to dark-blue theme")
            theme = "dark-blue"
        ctk.set_default_color_theme(theme)
        ctk.deactivate_automatic_dpi_awareness()  # TODO: implement dpi awareness for all views for Windows OS
        logging.info(f"ctk.ThemeManager.theme:\n{pformat(ThemeManager.theme)}")
        self.mono_font = self._init_mono_font()

        ctk.AppearanceModeTracker.add(self._appearance_mode_change)
        self._appearance_mode_change(ctk.get_appearance_mode())  # initialize non-ctk widget styles

        if sys.platform.startswith("win"):
            self.iconbitmap("assets\\icons\\rsna_icon.ico", default="assets\\icons\\rsna_icon.ico")

        self.recent_project_dirs: list[Path] = []
        self.current_open_project_dir: Path | None = None

        self.load_config()  # may set language
        self.controller: ProjectController | None = None
        self.welcome_view: WelcomeView = WelcomeView(self, self.change_language)
        self.welcome_view.focus()
        self.query_view: QueryView | None = None
        self.export_view: ExportView | None = None
        self.index_view: IndexView | None = None
        self.help_views = {}
        self.dashboard: Dashboard | None = None
        self.resizable(False, False)
        self.title(self.get_title())
        self.menu_bar = self.create_project_closed_menu_bar()
        self.after(self.project_open_startup_dwell_time, self._open_project_startup)

    def _init_mono_font(self) -> ctk.CTkFont:
        # Monospace font defaults:
        family = "Courier New"
        size = 12
        weight = "normal"
        if "Treeview" in ctk.ThemeManager.theme:
            os_map = {"Darwin": "macOS", "Windows": "Windows", "Linux": "Linux"}
            tv_theme = ctk.ThemeManager.theme["Treeview"]
            if platform.system() not in os_map:
                logger.error(f"Unsupported OS: {platform.system()}")
                return ctk.CTkFont(family, size, weight)
            if "font" in tv_theme:
                if os_map[platform.system()] not in tv_theme["font"]:
                    logger.error(f"invalid font OS specified for Treeview theme: {tv_theme}")
                    return ctk.CTkFont(family, size, weight)
                tv_theme_font = tv_theme["font"][os_map[platform.system()]]
                if "family" in tv_theme_font:
                    family = tv_theme_font["family"]
                if "size" in tv_theme_font:
                    size = tv_theme_font["size"]
                if "weight" in tv_theme_font:
                    weight = tv_theme_font["weight"]

        logger.info(f"Initialised Monospace Font: {family}, {size}, {weight}")
        return ctk.CTkFont(family, size, weight)

    def _appearance_mode_change(self, mode):
        logger.info(f"Appearance Mode Change: {mode}")
        # ttk Widgets, handling Light/Dark mode using ThemeManager
        # Treeview Customisation
        # Treeview defaults:
        bg_color = self._apply_appearance_mode(ctk.ThemeManager.theme["CTkFrame"]["fg_color"])
        text_color = self._apply_appearance_mode(ctk.ThemeManager.theme["CTkLabel"]["text_color"])
        selected_color = self._apply_appearance_mode(ctk.ThemeManager.theme["CTkButton"]["text_color"])
        selected_bg_color = self._apply_appearance_mode(ctk.ThemeManager.theme["CTkButton"]["fg_color"])
        # Treeview from ThemeManager:
        if "Treeview" in ctk.ThemeManager.theme:
            tv_theme = ctk.ThemeManager.theme["Treeview"]
            if "bg_color" in tv_theme:
                bg_color = self._apply_appearance_mode(tv_theme["bg_color"])
            if "text_color" in tv_theme:
                text_color = self._apply_appearance_mode(tv_theme["text_color"])
            if "selected_color" in tv_theme:
                selected_color = self._apply_appearance_mode(tv_theme["selected_color"])
            if "selected_bg_color" in tv_theme:
                selected_bg_color = self._apply_appearance_mode(tv_theme["selected_bg_color"])

        # Set ttk Style for Treeview components used in application:
        treestyle = ttk.Style()
        treestyle.configure(
            "Treeview.Heading",
            background=bg_color,
            foreground=text_color,
            font=str(self.mono_font),
        )
        treestyle.configure(
            "Treeview",
            background=bg_color,
            foreground=text_color,
            fieldbackground=bg_color,
            font=str(self.mono_font),
        )
        treestyle.map(
            "Treeview",
            background=[("selected", selected_bg_color)],
            foreground=[("selected", selected_color)],
            font=[("selected", str(self.mono_font))],
        )

    # Callback from WelcomeView
    def change_language(self, language):
        logger.info(f"Change Language to: {language}")
        set_language(language)
        self.help_views = {}
        self.title(self.get_title())
        self.recent_project_dirs = []
        self.menu_bar = self.create_project_closed_menu_bar()  # resets Help Menu
        self.save_config()
        self.welcome_view.destroy()
        self.welcome_view = WelcomeView(self, self.change_language)

    # Dashboard metrics updates from the main thread
    def metrics_loop(self):
        if not self.controller:
            logger.info("metrics_loop end, no controller")
            return

        # Update dashboard if anonymizer model has changed:
        if self.dashboard:
            self.dashboard.update_anonymizer_queues(*self.controller.anonymizer.queued())
            if self.controller.anonymizer.model_changed():
                self.dashboard.update_totals(self.controller.anonymizer.model.get_totals())

        self.after(self.metrics_loop_interval, self.metrics_loop)

    def load_config(self):
        logger.info(f"Load Config (App State): {self.get_app_state_path()}")
        try:
            with open(self.get_app_state_path().as_posix(), "r") as config_file:
                config_data = json.load(config_file)

                if "language" in config_data:
                    config_lang = config_data["language"]
                    set_language(config_lang)
                    logger.info(f"language: '{config_lang}' set from config file")
                else:
                    logger.info("language not found in config file, resort to default")

                self.recent_project_dirs = [Path(dir) for dir in config_data.get("recent_project_dirs", [])]
                for dir in self.recent_project_dirs:
                    if not dir.exists():
                        self.recent_project_dirs.remove(dir)
                self.current_open_project_dir = config_data.get("current_open_project_dir")
                if not os.path.exists(str(self.current_open_project_dir)):
                    self.current_open_project_dir = None
        except FileNotFoundError:
            warn_msg = (
                "Config file not found: "
                + str(self.get_app_state_path())
                + " default language set, recent project list or current project set"
            )
            logger.warning(warn_msg)

    def save_config(self):
        logger.info(f"Save Config (App State): {self.get_app_state_path()}")
        try:
            config_data = {
                "language": get_current_language(),
                "recent_project_dirs": [str(path) for path in self.recent_project_dirs],
                "current_open_project_dir": str(self.current_open_project_dir) or "",
            }
            app_state_path = self.get_app_state_path()
            app_state_path.parent.mkdir(parents=True, exist_ok=True)
            with open(app_state_path.as_posix(), "w") as config_file:
                json.dump(config_data, config_file, indent=2)

        except Exception as e:
            err_msg = _("Error writing json config file: ") + f"{str(app_state_path)} : {repr(e)}"
            logger.error(err_msg)
            messagebox.showerror(
                title=_("Configuration File Write Error"),
                message=err_msg,
                parent=self,
            )

    def is_recent_directory(self, dir: Path) -> bool:
        return any(str(dir) in str(path) for path in self.recent_project_dirs)

    def new_project(self):
        logging.info("New Project")
        self.disable_file_menu()

        dlg = SettingsDialog(
            parent=self,
            model=ProjectModel(),
            new_model=True,
            title=_("New Project Settings"),
        )
        model, java_phi_studies = dlg.get_input()

        if model is None:
            logger.info("New Project Cancelled")
            self.enable_file_menu()
            return

        logger.info(f"New ProjectModel: {model}")

        if not model.storage_dir:
            logger.info("New Project Cancelled, storage directory not set")
            messagebox.showerror(
                title=_("New Project Error"),
                message=_("Storage Directory not set, please set a valid directory in project settings."),
                parent=self,
            )
            self.enable_file_menu()
            return

        project_model_path = Path(model.storage_dir, ProjectController.PROJECT_MODEL_FILENAME_JSON)
        if model.storage_dir.exists() and model.storage_dir.is_dir() and project_model_path.exists():
            confirm = messagebox.askyesno(
                title=_("Confirm Overwrite"),
                message=_("The project directory already exists.")
                + "\n\n"
                + _("Do you want to delete the existing project and all its data?"),
                parent=self,
            )
            if not confirm:
                logger.info("New Project Cancelled")
                self.enable_file_menu()
                return

            # Delete contents of existing project directory:
            try:
                shutil.rmtree(model.storage_dir)
            except Exception as e:
                logger.error(f"Error deleting existing project directory: {model.storage_dir}, {str(e)}")
                messagebox.showerror(
                    title=_("New Project Error"),
                    message=_("Error deleting existing project directory") + f": {model.storage_dir}\n\n {str(e)}",
                    parent=self,
                )
                self.enable_file_menu()
                return

            logger.info(f"Deleted existing project directory: {model.storage_dir}")

        try:
            self.controller = ProjectController(model)
            if not self.controller:
                raise RuntimeError(_("Fatal Internal Error, Project Controller not created"))

            if java_phi_studies:
                self.controller.anonymizer.model.process_java_phi_studies(java_phi_studies)

            self.controller.save_model()

            logger.info(f"{self.controller}")

            self.current_open_project_dir = self.controller.model.storage_dir

            if self.current_open_project_dir and not self.is_recent_directory(self.current_open_project_dir):
                self.recent_project_dirs.insert(0, self.current_open_project_dir)
                self.save_config()

            self._open_project()

        except Exception as e:
            logger.error(f"Error creating Project Controller: {str(e)}")
            messagebox.showerror(
                title=_("New Project Error"),
                message=_("Error creating Project Controller" + f"\n\n{str(e)}"),
                parent=self,
            )
        finally:
            self.enable_file_menu()

    def open_project(self, project_dir: Path | None = None):
        logger.debug("open_project")

        self.disable_file_menu()  # TODO: use try finally to ensure self.enable_file_menu instead of all calls below

        logging.info(f"Open Project project_dir={project_dir}")

        if project_dir is None:
            selected_dir = filedialog.askdirectory(
                initialdir=ProjectModel.default_storage_dir(),
                title=_("Select Anonymizer Storage Directory"),
            )

            if not selected_dir:
                logger.info("Open Project Cancelled")
                self.enable_file_menu()
                return

            project_dir = Path(selected_dir)

        # For backward compatibilty load pickle file format of ProjectModel if it exists:
        # Get project pkl filename from project directory
        project_model_path = Path(project_dir, ProjectController.PROJECT_MODEL_FILENAME_PKL)
        if project_model_path.exists() and project_model_path.is_file():
            try:
                with open(project_model_path, "rb") as pkl_file:
                    logger.warning(f"Loading Project Model from legacy pickle file: {project_model_path}")
                    file_model = pickle.load(pkl_file)
                    # DELETE the pickle file after successful loading, saving will be in json from now on:
                    os.remove(project_model_path)
            except Exception as e:
                logger.error(f"Error loading Project Model: {str(e)}")
                messagebox.showerror(
                    title=_("Open Project Error"),
                    message=_("Error loading Project Model from legacy pickle data file")
                    + f": {project_model_path}\n\n{str(e)}",
                    parent=self,
                )
                self.enable_file_menu()
                return
        else:
            project_model_path = Path(project_dir, ProjectController.PROJECT_MODEL_FILENAME_JSON)
            if project_model_path.exists() and project_model_path.is_file():
                try:
                    file_model = load_model(project_model_path)
                except Exception as e:
                    logger.error(f"Error loading Project Model: {str(e)}")
                    messagebox.showerror(
                        title=_("Open Project Error"),
                        message=_("Error loading Project Model from data file") + f": {project_model_path}\n\n{str(e)}",
                        parent=self,
                    )
                    self.enable_file_menu()
                    return
            else:
                logger.error(f"No project file found in {project_dir}")
                messagebox.showerror(
                    title=_("Open Project Error"),
                    message=_("No Project file found in") + f":\n\n{project_dir}",
                    parent=self,
                )
                if self.is_recent_directory(project_dir):
                    self.recent_project_dirs.remove(project_dir)
                self.menu_bar = self.create_project_closed_menu_bar()
                self.save_config()
                self.enable_file_menu()
                return

        if not hasattr(file_model, "version"):
            logger.error("Project Model missing version")
            messagebox.showerror(
                title=_("Open Project Error"),
                message=_("Project File corrupted, missing version information."),
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
            model.__dict__.update(
                file_model.__dict__
            )  # copy over corresponding attributes from the old model (file_model)
            model.version = ProjectModel.MODEL_VERSION  # update to latest version
        else:
            model = file_model

        # Ensure Current Language matches Project Language:
        if model.language_code != get_current_language_code():
            logger.error(f"Project Model language mismatch {model.language_code} != {get_current_language_code()}")
            messagebox.showerror(
                title=_("Open Project Error"),
                message=_("Project language mismatch") + f": {model.language_code}",
                parent=self,
            )
            self.enable_file_menu()
            return

        try:
            self.controller = ProjectController(model)
            if not self.controller:
                raise RuntimeError(_("Fatal Internal Error, Project Controller not created"))

            if file_model.version != ProjectModel.MODEL_VERSION:
                logger.warning(f"Project Model upgraded successfully to version: {self.controller.model.version}")

            self.controller.save_model()
        except Exception as e:
            logger.error(f"Error creating Project Controller: {str(e)}")
            messagebox.showerror(
                title=_("Open Project Error"),
                message=_("Error creating Project Controller") + f"\n\n{str(e)}",
                parent=self,
            )
            self.enable_file_menu()
            return

        logger.info(f"{self.controller}")
        if not self.is_recent_directory(project_dir):
            self.recent_project_dirs.insert(0, project_dir)
        self.current_open_project_dir = project_dir
        self.save_config()
        self._open_project()
        self.enable_file_menu()

    def _open_project_startup(self):
        if self.current_open_project_dir:
            self.open_project(self.current_open_project_dir)

    def _open_project(self):
        logger.debug("_open_project")

        if not self.controller:
            logger.info("Open Project Cancelled, no controller")
            return

        # Set Engine Echo for SQL logging:
        self.controller.anonymizer.model.engine.echo = self.controller.model.logging_levels.sql

        try:
            self.controller.start_scp()
        except DICOMRuntimeError as e:
            messagebox.showerror(title=_("Local DICOM Server Error"), message=str(e), parent=self)

        self.title(
            f"{self.controller.model.project_name}[{self.controller.model.site_id}] => {self.controller.model.abridged_storage_dir()}"
        )

        self.welcome_view.destroy()
        self.protocol("WM_DELETE_WINDOW", self.close_project)
        self.menu_bar = self.create_project_open_menu_bar()

        self.dashboard = Dashboard(
            self,
            query_callback=self.query_retrieve,
            export_callback=self.export,
            view_callback=self.view,
            controller=self.controller,
        )

        if not self.dashboard:
            logger.error("Critical Internal Error creating Dashboard")
            return

        self.dashboard.update_totals(self.controller.anonymizer.model.get_totals())
        self.dashboard.focus_set()

        logger.info(f"metrics_loop start interval={self.metrics_loop_interval}ms")
        self.metrics_loop()

    def shutdown_controller(self):
        logger.info("shutdown_controller")

        if self.dashboard:
            self.dashboard.destroy()
            self.dashboard = None
        if self.controller:
            self.controller.stop_scp()
            self.controller.shutdown()
            self.controller.save_model()
            self.controller.anonymizer.stop()
            if self.query_view:
                self.query_view.destroy()
                self.query_view = None
            if self.export_view:
                self.export_view.destroy()
                self.export_view = None

    def close_project(self, event=None):
        logger.info("Close Project")
        if self.query_view and self.query_view.busy():
            logger.info("QueryView busy, cannot close project")
            messagebox.showerror(
                title=_("Query Busy"),
                message=_("Query is busy, please wait for query to complete before closing project."),
                parent=self,
            )
            return
        if self.export_view and self.export_view.busy():
            logger.info("ExportView busy, cannot close project")
            messagebox.showerror(
                title=_("Export Busy"),
                message=_("Export is busy, please wait for export to complete before closing project."),
                parent=self,
            )
            return

        if self.controller and not self.controller.anonymizer.idle():
            logger.info("Anonymizer busy, cannot close project")
            messagebox.showerror(
                title=_("Anonymizer Workers Busy"),
                message=_(
                    "Anonymizer queues are not empty, please wait for workers to process files before closing project."
                ),
                parent=self,
            )
            return

        # TODO: Do not allow project close if Import Files/Import Directory is busy
        # TODO: Shutdowncontroller asynchronously using Dashboard Status to provide shutdown updates (especially Anonymizer worker threads)
        self.shutdown_controller()

        self.welcome_view = WelcomeView(self, self.change_language)
        self.protocol("WM_DELETE_WINDOW", self.quit)
        self.focus_force()

        self.current_open_project_dir = None
        self.controller = None
        self.menu_bar = self.create_project_closed_menu_bar()
        self.title(self.get_title())
        self.save_config()

    def clone_project(self, event=None):
        logger.info("Clone Project")

        if not self.controller:
            logger.info("Clone Project Cancelled, no project open")
            messagebox.showerror(
                title=_("Clone Project Error"),
                message=_("No project open to clone."),
                parent=self,
            )
            return

        # Cloning only copies the project settings
        # Not the anonymized files or lookup tables (ie. AnonymizerModel)
        self.controller.anonymizer.stop()
        current_project_dir = self.controller.model.storage_dir

        clone_dir_str: str | None = filedialog.askdirectory(
            initialdir=current_project_dir.parent,
            title=_("Select Directory for Cloned Project"),
            mustexist=False,
            parent=None,
        )

        if not clone_dir_str:
            logger.info("Clone Project Cancelled")
            return

        cloned_project_dir = Path(clone_dir_str)

        if cloned_project_dir == current_project_dir:
            logger.info("Clone Project Cancelled, cloned directory same as current project directory")
            messagebox.showerror(
                title=_("Clone Project Error"),
                message=_("Cloned directory cannot be the same as the current project directory."),
                parent=self,
            )
            return

        # Change the storage directory to the cloned project directory
        # keep all other settings, including Site ID:
        cloned_model: ProjectModel = copy(self.controller.model)

        cloned_model.storage_dir = cloned_project_dir
        cloned_model.project_name = f"{cloned_model.project_name} (Clone)"

        dlg = SettingsDialog(self, cloned_model, new_model=True, title=_("Edit Cloned Project Settings"))
        (edited_model, null_java_phi) = dlg.get_input()
        if edited_model is None:
            logger.info("Edit Cloned Project Settings Cancelled")
            return
        else:
            logger.info("User Edited ClonedProjectModel")

        # Close current project
        self.close_project()
        time.sleep(1)  # wait for project to close

        try:
            # Create New Controller with cloned project model
            self.controller = ProjectController(
                cloned_model
            )  # this will recreate AnonymizerController and restart associated worker threads

            if not self.controller:
                raise RuntimeError(_("Fatal Internal Error, Project Controller not created"))

            self.controller.save_model()
            logger.info(f"Project cloned successfully: {self.controller}")
        except Exception as e:
            logger.error(f"Error creating Project Controller: {str(e)}")
            messagebox.showerror(
                title=_("Clone Project Error"),
                message=_("Error creating Project Controller") + f"\n\n{str(e)}",
                parent=self,
            )
            return

        if not self.is_recent_directory(cloned_project_dir):
            self.recent_project_dirs.insert(0, cloned_project_dir)

        logger.info(f"{self.controller}")
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
            logger.info("Import Files Cancelled")
            self.enable_file_menu()
            return

        dlg = ImportFilesDialog(self, self.controller.anonymizer, file_paths)
        dlg.get_input()
        self.enable_file_menu()

    def import_directory(self, event=None):
        logging.info("Import Directory")

        if not self.controller:
            logger.error("Internal Error: no ProjectController")
            return

        if not self.dashboard:
            logger.error("Internal Error: no Dashboard")
            return

        self.disable_file_menu()  # TODO: try finally to ensure self.enable_file_menu() is called

        msg = _("Select DICOM Directory to Import & Anonymize")
        root_dir = filedialog.askdirectory(
            title=msg,
            mustexist=True,
            parent=self,
        )
        logger.info(root_dir)

        if not root_dir:
            logger.info("Import Directory Cancelled")
            self.enable_file_menu()
            return

        file_paths = []
        # Handle reading DICOMDIR files in Media Storage Directory (eg. CD/DVD/USB Drive)
        dicomdir_file = os.path.join(root_dir, "DICOMDIR")
        if os.path.exists(dicomdir_file):
            try:
                ds = dcmread(fp=dicomdir_file)
                root_dir = Path(str(ds.filename)).resolve().parent
                msg = _("Reading DICOMDIR Root directory" + f": {Path(root_dir).stem}...")
                logger.info(msg)
                self.dashboard.set_status(msg)

                # Iterate through the PATIENT records
                for patient in ds.patient_records:
                    logger.info(f"PATIENT: PatientID={patient.PatientID}, PatientName={patient.PatientName}")

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
                msg_prefix = _("Error reading DICOMDIR file")
                msg_detail = f"{dicomdir_file}, {str(e)}"
                logger.error(msg_prefix + ": " + msg_detail)
                self.dashboard.set_status(msg_prefix)

                messagebox.showerror(
                    title=_("Import Directory Error"),
                    message=msg_prefix + "\n\n" + msg_detail,
                    parent=self,
                )
                self.enable_file_menu()
                return
        else:
            msg = _("Reading filenames from") + f" {Path(root_dir).stem}..."
            logger.info(msg)
            self.dashboard.set_status(msg)
            # TODO OPTIMIZE: use Python Generator to handle massive directory trees
            file_paths = [
                os.path.join(root, file)
                for root, _, files in os.walk(root_dir)
                for file in files
                if not file.startswith(".")
            ]

        if len(file_paths) == 0:
            msg = _("No files found in") + f" {root_dir}"
            logger.info(msg)
            messagebox.showerror(
                title=_("Import Directory Error"),
                message=msg,
                parent=self,
            )
            self.dashboard.set_status(msg)
            self.enable_file_menu()
            return

        msg = (
            f"{len(file_paths)} "
            + _("filenames read from")
            + f"\n\n{root_dir}\n\n"
            + _("Do you want to initiate import?")
        )
        if not messagebox.askyesno(
            title=_("Import Directory"),
            message=msg,
            parent=self,
        ):
            msg = _("Import Directory Cancelled")
            logger.info(msg)
            self.dashboard.set_status(msg)
            self.enable_file_menu()
            return

        msg = _("Importing") + f" {len(file_paths)} {_('file') if len(file_paths) == 1 else _('files')}"
        logger.info(msg)
        self.dashboard.set_status(msg)

        dlg = ImportFilesDialog(self, self.controller.anonymizer, sorted(file_paths))
        files_processed = dlg.get_input()
        msg = _("Files processed") + f": {files_processed}"
        logger.info(msg)
        self.dashboard.set_status(msg)
        self.enable_file_menu()

    def query_retrieve(self):
        logging.info("OPEN QueryView")

        if not self.controller:
            logger.error("Internal Error: no ProjectController")
            return

        if self.query_view and self.query_view.winfo_exists():
            logger.info("QueryView already OPEN")
            self.query_view.deiconify()
            self.query_view.focus_force()
            return

        if not self.dashboard:
            logger.error("Internal Error: no Dashboard")
            return

        if self.query_view:
            del self.query_view

        self.query_view = QueryView(self.dashboard, self.controller, self.mono_font)
        if not self.query_view:
            logger.error("Internal Error creating QueryView")
            return
        self.query_view.focus()

    def export(self):
        logging.info("OPEN ExportView")

        if not self.controller:
            logger.error("Internal Error: no ProjectController")
            return

        if self.export_view and self.export_view.winfo_exists():
            logger.info("ExportView already OPEN")
            self.export_view.deiconify()
            self.export_view.focus_force()
            return

        if not self.dashboard:
            logger.error("Internal Error: no Dashboard")
            return

        if self.export_view:
            del self.export_view

        self.export_view = ExportView(self.dashboard, self.controller, self.mono_font)
        if self.export_view is None:
            logger.error("Internal Error creating ExportView")
            return

        self.export_view.focus()

    def view(self):
        logging.info("OPEN IndexView")

        if not self.controller:
            logger.error("Internal Error: no ProjectController")
            return

        if self.index_view and self.index_view.winfo_exists():
            logger.info("IndexView already OPEN")
            self.index_view.deiconify()
            self.index_view.focus_force()
            return

        if not self.dashboard:
            logger.error("Internal Error: no Dashboard")
            return

        if self.index_view:
            del self.index_view

        self.index_view = IndexView(self.dashboard, self.controller, self.mono_font.measure("A"))
        if self.index_view is None:
            logger.error("Internal Error creating IndexView")
            return

        self.index_view.focus()

    def settings(self):
        logger.info("Settings")

        if not self.controller:
            logger.error("Internal Error: no ProjectController")
            return

        if self.query_view and self.query_view.busy():
            logger.info("QueryView busy, cannot open SettingsDialog")
            messagebox.showerror(
                title=_("Query Busy"),
                message=_("Query is busy, please wait for query to complete before changing settings."),
                parent=self,
            )
            return

        if self.export_view and self.export_view.busy():
            logger.info("ExportView busy, cannot open SettingsDialog")
            messagebox.showerror(
                title=_("Export Busy"),
                message=_("Export is busy, please wait for export to complete before changing settings."),
                parent=self,
            )
            return

        dlg = SettingsDialog(self, self.controller.model, title=_("Project Settings"))
        (edited_model, null_java_phi) = dlg.get_input()
        if edited_model is None:
            logger.info("Settings Cancelled")
            return

        logger.info("User Edited ProjectModel")

        # Some settings change require the project to be closed and re-opened:
        # TODO: elegantly open and close project, see clone project above
        if self.controller.model.remove_pixel_phi != edited_model.remove_pixel_phi:
            messagebox.showwarning(
                title=_("Project restart"),
                message=_("The settings change will take effect when the project is next opened."),
                parent=self,
            )

        self.controller.update_model(edited_model)

        logger.info(f"{self.controller}")

    def help_filename_to_title(self, filename):
        words = filename.stem.split("_")[1].split()
        return " ".join(word.capitalize() for word in words)

    def show_help_view(self, html_file_path):
        view_name = self.help_filename_to_title(html_file_path)

        if view_name in self.help_views:
            view = self.help_views[view_name]
            if view.winfo_exists():
                logger.info(f"{view.title} already OPEN")
                view.deiconify()
                return

        self.help_views[view_name] = HTMLView(self, title=view_name, html_file_path=html_file_path.as_posix())
        self.help_views[view_name].focus()

    def get_help_menu(self, menu_bar: tk.Menu):
        help_menu = tk.Menu(menu_bar, tearoff=0)
        # Get all html files in assets/locale/*/html/ directory
        # Sort by filename number prefix
        html_dir = Path("assets/locales/" + str(get_current_language_code() or "en_US") + "/html/")
        html_file_paths = sorted(html_dir.glob("*.html"), key=lambda path: int(path.stem.split("_")[0]))

        for __, html_file_path in enumerate(html_file_paths):
            label = self.help_filename_to_title(html_file_path)
            help_menu.add_command(
                label=label,
                command=lambda path=html_file_path: self.show_help_view(path),
            )

        return help_menu

    def create_project_closed_menu_bar(self) -> tk.Menu:
        logger.debug("create_project_closed_menu_bar")
        menu_bar = tk.Menu(master=self)

        # File Menu:
        file_menu = tk.Menu(self, tearoff=0)
        file_menu.add_command(label=_("New Project"), command=self.new_project)
        file_menu.add_command(label=_("Open Project"), command=self.open_project)
        if self.recent_project_dirs:
            # Open Recent Menu (cascaded)
            open_recent_menu = tk.Menu(file_menu, tearoff=0, name="open_recent_menu")
            file_menu.add_cascade(label=_("Open Recent"), menu=open_recent_menu)
            for directory in self.recent_project_dirs:
                open_recent_menu.add_command(
                    label=str(directory),
                    command=lambda dir=directory: self.open_project(dir),
                )

        file_menu.add_separator()

        file_menu.add_command(label=_("Exit"), command=self.quit)

        menu_bar.add_cascade(label=_("File"), menu=file_menu)

        # Help Menu:
        menu_bar.add_cascade(label=_("Help"), menu=self.get_help_menu(menu_bar))

        # Attach new menu bar:
        self.config(menu=menu_bar)
        return menu_bar

    def create_project_open_menu_bar(self) -> tk.Menu:
        logger.debug("create_project_open_menu_bar")
        menu_bar = tk.Menu(master=self)

        # File Menu:
        file_menu = tk.Menu(self, tearoff=0)
        file_menu.add_command(label=_("Import Files"), command=self.import_files)
        file_menu.add_command(label=_("Import Directory"), command=self.import_directory)

        file_menu.add_separator()

        file_menu.add_command(label=_("Clone Project"), command=self.clone_project)
        file_menu.add_command(label=_("Close Project"), command=self.close_project)

        file_menu.add_separator()
        file_menu.add_command(label=_("Exit"), command=self.quit)

        menu_bar.add_cascade(label=_("File"), menu=file_menu)

        # View Menu:
        view_menu = tk.Menu(self, tearoff=0)
        view_menu.add_command(label=_("Project"), command=self.settings)

        menu_bar.add_cascade(label=_("Settings"), menu=view_menu)

        # Help Menu:
        menu_bar.add_cascade(label=_("Help"), menu=self.get_help_menu(menu_bar))

        # Attach new menu bar:
        self.config(menu=menu_bar)
        return menu_bar

    def disable_file_menu(self):
        logger.debug("disable_file_menu")

        if self.menu_bar:
            self.menu_bar.entryconfig(_("File"), state="disabled")

    def enable_file_menu(self):
        logger.debug("enable_file_menu")

        if self.menu_bar:
            self.menu_bar.entryconfig(_("File"), state="normal")


def run_GUI(logs_dir):
    try:
        app = Anonymizer(Path(logs_dir))
        app.lift()
        app.focus_force()
        logger.info("ANONYMIZER GUI initialised successfully.")
    except Exception as e:
        logger.exception(f"Error initialising ANONYMIZER GUI, exiting: {str(e)}")
        sys.exit(1)

    logger.info("ANONYMIZER GUI MAINLOOP...")
    try:
        app.mainloop()
    except Exception as e:
        logger.exception(f"Error in ANONYMIZER GUI MAINLOOP: {str(e)}")
    finally:
        app.shutdown_controller()

    logger.info("ANONYMIZER GUI Stop.")


def signal_handler(signum, frame):
    """
    Handles signals to gracefully stop the application in headless mode.
    """
    global keep_running
    keep_running = False
    print("Signal received, shutting down...")


def load_model(json_filepath: Path) -> ProjectModel:
    try:
        with open(json_filepath, "r") as f:
            file_model = ProjectModel.from_json(f.read())  # type: ignore
        if not isinstance(file_model, ProjectModel):
            raise TypeError("Loaded object is not an instance of ProjectModel")
        logger.info(f"Project Model successfully loaded from: {json_filepath}")
        return file_model
    except Exception as e1:
        # Attempt to load backup file
        backup_filepath = str(json_filepath) + ".bak"
        if os.path.exists(backup_filepath):
            try:
                with open(backup_filepath, "r") as f:
                    file_model = ProjectModel.from_json(f.read())  # type: ignore
                if not isinstance(file_model, ProjectModel):
                    raise TypeError("Loaded backup object is not an instance of ProjectModel")
                logger.warning(f"Loaded Project Model from backup file: {backup_filepath}")
                return file_model
            except Exception as e2:
                logger.error(f"Backup Project Model datafile corrupt: {e2}")
                raise RuntimeError(f"Project datafile: {backup_filepath} and backup file corrupt\n\n{str(e2)}") from e2
        else:
            logger.error(f"Project Model datafile corrupt: {e1}")
            raise RuntimeError(f"Project Model datafile: {json_filepath} corrupt\n\n{str(e1)}") from e1


def run_HEADLESS(project_model_path: Path):
    if not project_model_path.exists():
        logger.error(_("Project Model file not found") + f": {project_model_path}")
        return

    if not project_model_path.is_file():
        logger.error(_("Project Model path is not a file") + f": {project_model_path}")
        return

    try:
        file_model = load_model(project_model_path)
    except Exception as e:
        logger.error(f"Error loading Project Model: {str(e)}")
        return

    logger.info(f"Project Model succesfully loaded from: {project_model_path}")

    if not hasattr(file_model, "version"):
        logger.error("Project Model missing version")
        return

    logger.info(_("Project Model loaded successfully, version") + f": {file_model.version}")

    if file_model.version != ProjectModel.MODEL_VERSION:
        logger.info(
            _("Project Model version mismatch")
            + f": {file_model.version} != {ProjectModel.MODEL_VERSION} "
            + _("upgrading accordingly")
        )
        model = ProjectModel()  # new default model
        # TODO: Handle 2 level nested classes/dicts copying by attribute
        # to handle addition or nested fields and deletion of attributes in new model
        model.__dict__.update(file_model.__dict__)  # copy over corresponding attributes from the old model (file_model)
        model.version = ProjectModel.MODEL_VERSION  # update to latest version
    else:
        model = file_model

    try:
        controller = ProjectController(model)
        if not controller:
            raise RuntimeError(_("Fatal Internal Error, Project Controller not created"))

        if file_model.version != ProjectModel.MODEL_VERSION:
            controller.save_model()
            logger.info(_("Project Model upgraded successfully to version" + f": {controller.model.version}"))

    except Exception as e:
        logger.error(f"Error creating Project Controller: {str(e)}")
        return

    logger.info(f"{controller}")

    try:
        controller.start_scp()
    except DICOMRuntimeError as e:
        logger.error(_("Local DICOM Server Error") + f": {e}")
        return

    logger.info(
        f"{controller.model.project_name}[{controller.model.site_id}] => {controller.model.abridged_storage_dir()}"
    )
    logger.info("ANONYMIZER HEADLESS MAINLOOP start...")
    logger.info("Press CTRL-C to shutdown server")

    global keep_running
    keep_running = True

    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)  # Handle Ctrl+C (SIGINT)
    signal.signal(signal.SIGTERM, signal_handler)  # Handle termination signal (SIGTERM)

    try:
        while keep_running:
            time.sleep(1)

    except KeyboardInterrupt:
        logger.info("Exiting from Keyboard Interrupt")

    logger.info("ANONYMIZER HEADLESS MAINLOOP end.")

    controller.stop_scp()
    controller.shutdown()
    controller.save_model()
    controller.anonymizer.stop()


@click.command()
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, readable=True, path_type=Path),
    help=_("Path to the configuration file. If not provided, the GUI will be launched."),
)
def main(config: Path | None = None):
    """
    This application reads a configuration file if provided and runs headless or launches a GUI.
    """
    install_dir = os.path.dirname(os.path.realpath(__file__))
    logs_dir = init_logging()
    os.chdir(install_dir)
    logger.info(f"Running from {install_dir}")
    logger.info(f"Python Optimization Level [0,1,2]: {sys.flags.optimize}")
    logger.info(f"Starting ANONYMIZER Version {get_version()}")
    logger.info(f"Running from {os.getcwd()}")
    logger.info(f"Python Version: {sys.version_info.major}.{sys.version_info.minor}")
    logger.info(f"tkinter TkVersion: {tk.TkVersion} TclVersion: {tk.TclVersion}")
    logger.info(f"Customtkinter Version: {ctk.__version__}")
    logger.info(f"pydicom Version: {pydicom_version}, pynetdicom Version: {pynetdicom_version}")

    ocr_model_dir = Path("assets/ocr/model")
    if not ocr_model_dir.exists():
        logger.warning("Downloading OCR models...")
        from easyocr import Reader

        Reader(
            lang_list=["en", "de", "fr", "es"],
            model_storage_directory=ocr_model_dir,
            verbose=True,
        )
    models = os.listdir(ocr_model_dir)
    if len(models) < 2:
        logger.error("Error downloading OCR detection and recognition models")
        ocr_model_dir.unlink()
    else:
        logger.info(f"OCR downloaded models: {models}")

    if config:
        run_HEADLESS(config)
    else:
        run_GUI(logs_dir)


if __name__ == "__main__":
    main()
