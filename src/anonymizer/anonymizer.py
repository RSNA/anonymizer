import contextlib
import ctypes
import faulthandler
import json
import logging
import os
import pickle
import shutil
import signal
import sys
import time
import tkinter as tk
import weakref
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

from anonymizer.controller.process_ctp_lookup import commit_ctp_lookup
from anonymizer.controller.project import ProjectController
from anonymizer.model.project import DICOMRuntimeError, ProjectModel
from anonymizer.utils.logging import init_logging
from anonymizer.utils.storage import is_hidden_path, list_import_directory_files
from anonymizer.utils.translate import (
    _,
    get_current_language,
    get_current_language_code,
    set_language,
)
from anonymizer.utils.version import get_version
from anonymizer.view.common.fonts import AppFonts, create_app_fonts
from anonymizer.view.common.help_docs import (
    license_html_path,
    open_help_page,
    open_tutorials_channel,
)
from anonymizer.view.common.html_view import HTMLView
from anonymizer.view.project.dataset import DatasetView
from anonymizer.view.project.export import ExportView
from anonymizer.view.project.import_files_dialog import ImportFilesDialog
from anonymizer.view.project.query_retrieve_import import QueryView
from anonymizer.view.settings.settings_dialog import SettingsDialog
from anonymizer.view.shell.dashboard import Dashboard
from anonymizer.view.shell.welcome import WelcomeView

faulthandler.enable()

logger = logging.getLogger()  # ROOT logger


def _cli_help() -> str:
    return _(
        "RSNA DICOM Anonymizer {version}\n\n"
        "This application reads a configuration file if provided and runs headless or launches a GUI."
    ).format(version=get_version())


class Anonymizer(ctk.CTk):
    THEME_FILE = "assets/themes/rsna_theme.json"

    project_open_startup_dwell_time = 100  # milliseconds
    metrics_loop_interval = 1000  # milliseconds
    welcome_guard_interval_ms = 500
    welcome_size_tolerance = 0.85  # re-apply when width falls below this fraction of target
    project_window_min_width = 900  # dashboard databoard (5 columns); independent of welcome width
    project_window_min_height = 320

    def get_title(self) -> str:
        return _("RSNA DICOM Anonymizer Version").strip() + " " + get_version()

    def get_app_state_path(self) -> Path:
        from anonymizer.utils.app_state import get_app_state_path

        return get_app_state_path()

    def __init__(self, logs_dir: Path):
        if sys.platform.startswith("win"):
            # Enable DPI awareness for Windows (improves scaling on high-DPI/4K monitors)
            # ctk.deactivate_automatic_dpi_awareness()  # TODO: implement dpi awareness for all views for Windows OS
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # type: ignore

        super().__init__()
        from anonymizer.view.common.ctk_safe import mark_ctk_window_alive

        mark_ctk_window_alive(self)
        self.logs_dir: Path = logs_dir
        ctk.set_appearance_mode("System")  # Modes: "System" (standard), "Dark", "Light"
        theme = self.THEME_FILE
        if not os.path.exists(theme):
            logger.error(f"Theme file not found: {theme}, reverting to dark-blue theme")
            theme = "dark-blue"
        ctk.set_default_color_theme(theme)

        logging.debug(f"ctk.ThemeManager.theme:\n{pformat(ThemeManager.theme)}")
        self.fonts: AppFonts = create_app_fonts()
        self.mono_font = self.fonts.mono

        ctk.AppearanceModeTracker.add(self._appearance_mode_change)
        self._appearance_mode_change(ctk.get_appearance_mode())  # initialize non-ctk widget styles

        if sys.platform.startswith("win"):
            self.iconbitmap("assets\\icons\\rsna_icon.ico", default="assets\\icons\\rsna_icon.ico")

        self.recent_project_dirs: list[Path] = []
        self.current_open_project_dir: Path | None = None
        self._shutting_down = False
        self._import_in_progress = False
        self._welcome_window_locked = False
        self._welcome_guard_after_id: str | None = None

        self.load_config()  # may set language
        self.controller: ProjectController | None = None
        self._attach_welcome_view()
        self.welcome_view.focus()
        self.query_view: QueryView | None = None
        self.export_view: ExportView | None = None
        self.dataset_view: DatasetView | None = None

        self.dashboard: Dashboard | None = None
        self.help_views: dict[str, HTMLView] = {}
        self._app_windows: list[weakref.ref] = []
        self._window_menu: tk.Menu | None = None
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.resizable(False, False)
        self.title(self.get_title())
        self.protocol("WM_DELETE_WINDOW", self.quit_app)
        if sys.platform == "darwin":
            self.createcommand("::tk::mac::Quit", self.quit_app)
        self.menu_bar = self.create_project_closed_menu_bar()
        self.after(self.project_open_startup_dwell_time, self._open_project_startup)

    def _set_scaling(self, new_widget_scaling, new_window_scaling):
        super()._set_scaling(new_widget_scaling, new_window_scaling)
        if self._welcome_window_locked:
            self.after_idle(self._apply_welcome_window_size)

    def _welcome_target_size(self) -> tuple[int, int]:
        """Welcome window size from current content (adapts to language/text length)."""
        welcome_view = getattr(self, "welcome_view", None)
        if welcome_view is None or not welcome_view.winfo_exists():
            return WelcomeView.WELCOME_WINDOW_WIDTH, WelcomeView.WELCOME_WINDOW_HEIGHT
        self.update_idletasks()
        # Convert requested pixel size to CTk window units.
        req_w = self._reverse_window_scaling(welcome_view.winfo_reqwidth())
        req_h = self._reverse_window_scaling(welcome_view.winfo_reqheight())
        # Small shell padding around welcome frame.
        return int(req_w + 20), int(req_h + 20)

    def _enter_welcome_window_phase(self) -> None:
        """Hold welcome dimensions until a project opens or the welcome view is torn down."""
        self._cancel_welcome_window_guard()
        self._welcome_window_locked = True
        self._block_update_dimensions_event = True
        self.resizable(False, False)

    def _apply_welcome_window_size(self, *, log: bool = False) -> None:
        if not self._welcome_window_locked:
            return
        welcome_view = getattr(self, "welcome_view", None)
        if welcome_view is None or not welcome_view.winfo_exists():
            return
        width, height = self._welcome_target_size()
        self.update_idletasks()
        self._current_width = width
        self._current_height = height
        self.minsize(width, height)
        self.maxsize(width, height)
        self.geometry(f"{width}x{height}")
        self.resizable(False, False)
        if log:
            self._log_welcome_window_state(width, height)

    def _log_welcome_window_state(self, target_w: int, target_h: int) -> None:
        try:
            widget_scaling = self._get_widget_scaling()
            window_scaling = self._get_window_scaling()
        except Exception:
            widget_scaling = window_scaling = "?"
        logger.info(
            "Welcome window: target=%sx%s current=%sx%s winfo=%sx%s scaling(widget=%s window=%s)",
            target_w,
            target_h,
            self._current_width,
            self._current_height,
            self.winfo_width(),
            self.winfo_height(),
            widget_scaling,
            window_scaling,
        )

    def _welcome_window_needs_reapply(self) -> bool:
        target_w, _target_h = self._welcome_target_size()
        min_w = int(target_w * self.welcome_size_tolerance)
        if self._current_width < min_w:
            return True
        if self.winfo_width() > 1:
            detected_w = self._reverse_window_scaling(self.winfo_width())
            if detected_w < min_w:
                return True
        return False

    def _welcome_window_guard(self) -> None:
        if self._shutting_down or not self._welcome_window_locked:
            return
        welcome_view = getattr(self, "welcome_view", None)
        if welcome_view is None or not welcome_view.winfo_exists():
            self._cancel_welcome_window_guard()
            return
        if self._welcome_window_needs_reapply():
            logger.debug("Welcome window guard: re-applying size after Configure/scaling drift")
            self._apply_welcome_window_size()
        self._welcome_guard_after_id = self.after(self.welcome_guard_interval_ms, self._welcome_window_guard)

    def _cancel_welcome_window_guard(self) -> None:
        if self._welcome_guard_after_id is not None:
            with contextlib.suppress(tk.TclError):
                self.after_cancel(self._welcome_guard_after_id)
            self._welcome_guard_after_id = None

    def _release_welcome_window_constraints(self) -> None:
        self._cancel_welcome_window_guard()
        self._welcome_window_locked = False
        if not self.winfo_exists():
            return
        self._block_update_dimensions_event = False
        self.maxsize(1_000_000, 1_000_000)
        self.minsize(0, 0)

    def _project_window_target_size(self) -> tuple[int, int]:
        """CTk window units for the project dashboard (not welcome dimensions)."""
        dashboard = self.dashboard
        if dashboard is None or not dashboard.winfo_exists():
            return self.project_window_min_width, self.project_window_min_height
        self.update_idletasks()
        content_width = self._reverse_window_scaling(dashboard.winfo_reqwidth())
        content_height = self._reverse_window_scaling(dashboard.winfo_reqheight())
        pad = Dashboard.PAD * 2
        width = max(content_width + pad, self.project_window_min_width)
        height = max(content_height + pad, self.project_window_min_height)
        return width, height

    def _apply_project_window_size(self, *, log: bool = False) -> None:
        """Resize the main window to fit the project dashboard after leaving welcome."""
        if self._welcome_window_locked or self.dashboard is None or not self.dashboard.winfo_exists():
            return
        from anonymizer.view.common.ctk_safe import pause_scaling_tracker_check, resume_scaling_tracker_check

        pause_scaling_tracker_check()
        try:
            width, height = self._project_window_target_size()
            self._current_width = width
            self._current_height = height
            self._block_update_dimensions_event = True
            self.minsize(width, height)
            self.maxsize(width, height)
            self.geometry(f"{width}x{height}")
            self.resizable(False, False)
            if log:
                logger.info(
                    "Project window: size=%sx%s (dashboard req=%sx%s)",
                    width,
                    height,
                    width - Dashboard.PAD * 2,
                    height - Dashboard.PAD * 2,
                )
        finally:
            self._block_update_dimensions_event = False
            self.after_idle(resume_scaling_tracker_check)

    def _finalize_welcome_window(self) -> None:
        if not hasattr(self, "welcome_view") or not self.welcome_view.winfo_exists():
            return
        self._apply_welcome_window_size(log=True)
        self._cancel_welcome_window_guard()
        self._welcome_window_guard()

    def _attach_welcome_view(self) -> None:
        self._enter_welcome_window_phase()
        self.welcome_view = WelcomeView(
            self,
            self.change_language,
            self.show_ai_features_setup_dialog,
            fonts=self.fonts,
        )
        # Fill the shell so Windows does not show a lighter CTk margin under the panel.
        self.welcome_view.grid(row=0, column=0, sticky="nsew")
        for delay_ms in (0, 50, 200, 400):
            self.after(delay_ms, self._apply_welcome_window_size)
        self.after(500, self._finalize_welcome_window)

    def _log_ctk_scaling(self) -> None:
        if sys.platform != "darwin":
            return
        try:
            widget_scaling = self._get_widget_scaling()
            window_scaling = self._get_window_scaling()
        except Exception:
            logger.debug("CustomTkinter scaling values unavailable", exc_info=True)
            return
        logger.info(
            "CustomTkinter scaling: widget=%s window=%s",
            widget_scaling,
            window_scaling,
        )

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

        self.title(self.get_title())
        self.recent_project_dirs = []
        self.menu_bar = self.create_project_closed_menu_bar()  # resets Help Menu
        self.save_config()
        self.welcome_view.release_images()
        self.welcome_view.destroy()
        self._attach_welcome_view()

    # Dashboard metrics updates from the main thread
    def metrics_loop(self):
        if not self.controller:
            logger.info("metrics_loop end, no controller")
            return

        # Update dashboard if anonymizer model has changed:
        if self.dashboard:
            self.dashboard.update_anonymizer_queues(self.controller.anonymizer.queued())
            if self.controller.anonymizer.model_changed():
                self.dashboard.update_totals(self.controller.anonymizer.model.get_totals())

        self.after(self.metrics_loop_interval, self.metrics_loop)

    def load_config(self):
        from anonymizer.controller.ai.tseg.config import apply_ai_features_preferences
        from anonymizer.utils.app_state import ai_features_from_state

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
                apply_ai_features_preferences(ai_features_from_state(config_data))
        except FileNotFoundError:
            warn_msg = (
                "Config file not found: "
                + str(self.get_app_state_path())
                + " default language set, recent project list or current project set"
            )
            logger.warning(warn_msg)

    def save_config(self):
        from anonymizer.controller.ai.tseg.config import merge_ai_features_into_state

        logger.info(f"Save Config (App State): {self.get_app_state_path()}")
        try:
            config_data = merge_ai_features_into_state(
                {
                    "language": get_current_language(),
                    "recent_project_dirs": [str(path) for path in self.recent_project_dirs],
                    "current_open_project_dir": str(self.current_open_project_dir) or "",
                }
            )
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
        model, java_phi_studies, ctp_lookup_preview = dlg.get_input()

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
                self.controller.import_java_phi_studies(java_phi_studies)

            if ctp_lookup_preview is not None:
                commit_ctp_lookup(self.controller, ctp_lookup_preview)

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

        from anonymizer.controller.ai.tseg.readiness import log_runtime_status

        self._release_welcome_window_constraints()
        self.welcome_view.release_images()
        self.welcome_view.destroy()
        from anonymizer.view.common.ctk_safe import purge_stale_scaling_windows

        purge_stale_scaling_windows()
        log_runtime_status()
        self.protocol("WM_DELETE_WINDOW", self.close_project)
        self.menu_bar = self.create_project_open_menu_bar()

        self.dashboard = Dashboard(
            self,
            query_callback=self.query_retrieve,
            export_callback=self.export,
            view_callback=self.view,
            controller=self.controller,
            fonts=self.fonts,
        )

        if not self.dashboard:
            logger.error("Critical Internal Error creating Dashboard")
            return

        from anonymizer.view.common.filesystem_drop import enable_filesystem_drops

        enable_filesystem_drops(self.dashboard, self.import_paths)

        self.dashboard.update_totals(self.controller.anonymizer.model.get_totals())
        self.dashboard.focus_set()
        self._apply_project_window_size()
        for delay_ms in (50, 200):
            self.after(delay_ms, self._apply_project_window_size)
        self.after(400, lambda: self._apply_project_window_size(log=True))

        logger.info(f"metrics_loop start interval={self.metrics_loop_interval}ms")
        self.metrics_loop()

    def _project_close_blocked(self) -> tuple[str, str] | None:
        """Return (title, message) when project shutdown must wait, else None."""
        if self.query_view and self.query_view.busy():
            return (
                _("Query Busy"),
                _("Query is busy, please wait for query to complete before closing project."),
            )
        if self.export_view and self.export_view.busy():
            return (
                _("Export Busy"),
                _("Export is busy, please wait for export to complete before closing project."),
            )
        if self.controller and not self.controller.anonymizer.idle():
            return (
                _("Anonymizer Workers Busy"),
                _("Anonymizer queues are not empty, please wait for workers to process files before closing project."),
            )
        return None

    def quit_app(self, event=None) -> None:
        """Gracefully stop workers and exit (File/Exit, Cmd-Q, signals)."""
        if self._shutting_down:
            return
        logger.info("quit_app")
        blocked = self._project_close_blocked()
        if blocked:
            title, message = blocked
            logger.info("%s, cannot quit application", title)
            messagebox.showerror(title=title, message=message, parent=self)
            return
        self._shutting_down = True
        try:
            if self.controller:
                self.shutdown_controller()
            self.save_config()
        except Exception:
            logger.exception("quit_app: shutdown failed; forcing process exit")
            os._exit(1)
        self.quit()

    def shutdown_controller(self):
        logger.info("shutdown_controller")

        if self.dashboard:
            with contextlib.suppress(Exception):
                self.dashboard.destroy()
            self.dashboard = None
        if not self.controller:
            return
        with contextlib.suppress(Exception):
            self.controller.stop_scp()
        with contextlib.suppress(Exception):
            self.controller.shutdown()
        with contextlib.suppress(Exception):
            self.controller.save_model()
        with contextlib.suppress(Exception):
            self.controller.anonymizer.stop()
        if self.query_view:
            with contextlib.suppress(Exception):
                self.query_view.destroy()
            self.query_view = None
        if self.export_view:
            with contextlib.suppress(Exception):
                self.export_view.destroy()
            self.export_view = None
        self.controller = None

    def close_project(self, event=None):
        logger.info("Close Project")
        blocked = self._project_close_blocked()
        if blocked:
            title, message = blocked
            logger.info("%s, cannot close project", title)
            messagebox.showerror(title=title, message=message, parent=self)
            return

        # TODO: Do not allow project close if Import Files/Import Directory is busy
        # TODO: Shutdowncontroller asynchronously using Dashboard Status to provide shutdown updates (especially Anonymizer worker threads)
        self.shutdown_controller()

        self._attach_welcome_view()
        self.protocol("WM_DELETE_WINDOW", self.quit_app)
        self.focus_force()

        self.current_open_project_dir = None
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
        edited_model, null_java_phi, ctp_lookup_preview = dlg.get_input()
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

            if ctp_lookup_preview is not None:
                commit_ctp_lookup(self.controller, ctp_lookup_preview)

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

        if not self._begin_import():
            return

        self.disable_file_menu()
        try:
            self.update_idletasks()

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
                return

            self._run_import_files_dialog(list(file_paths))
        finally:
            self._end_import()

    def import_directory(self, event=None):
        logging.info("Import Directory")

        if not self.controller:
            logger.error("Internal Error: no ProjectController")
            return

        if not self.dashboard:
            logger.error("Internal Error: no Dashboard")
            return

        if not self._begin_import():
            return

        self.disable_file_menu()
        try:
            self.update_idletasks()

            msg = _("Select DICOM Directory to Import & Anonymize")
            root_dir = filedialog.askdirectory(
                title=msg,
                mustexist=True,
                parent=self,
            )
            logger.info(root_dir)

            if not root_dir:
                logger.info("Import Directory Cancelled")
                return

            self._import_directory_path(root_dir)
        finally:
            self._end_import()

    def import_paths(self, paths: list[str]) -> None:
        """Import local files/folders from OS drag-and-drop (skips chooser dialogs)."""
        logging.info("Import Paths (drop): %s", paths)

        if not self.controller:
            logger.error("Internal Error: no ProjectController")
            return

        cleaned = [str(Path(p).expanduser()) for p in paths if str(p).strip()]
        if not cleaned:
            return

        if not self._begin_import():
            return

        self.disable_file_menu()
        try:
            self.update_idletasks()
            only_dirs = [p for p in cleaned if Path(p).is_dir()]
            only_files = [p for p in cleaned if Path(p).is_file()]
            other = [p for p in cleaned if not Path(p).exists()]
            if other:
                logger.warning("Ignoring missing drop paths: %s", other)

            if only_dirs and not only_files and len(only_dirs) == 1:
                self._import_directory_path(only_dirs[0])
                return

            file_paths: list[str] = list(only_files)
            for directory in only_dirs:
                expanded = self._collect_files_from_directory(directory)
                if expanded is None:
                    return
                file_paths.extend(expanded)

            if not file_paths:
                messagebox.showerror(
                    title=_("Import"),
                    message=_("No files found in the dropped items."),
                    parent=self,
                )
                return

            self._run_import_files_dialog(file_paths)
        finally:
            self._end_import()

    def _run_import_files_dialog(self, file_paths: list[str]) -> None:
        assert self.controller is not None
        dlg = ImportFilesDialog(self, self.controller.anonymizer, file_paths)
        dlg.get_input()

    def _collect_files_from_directory(self, root_dir: str) -> list[str] | None:
        """Expand a directory to file paths (DICOMDIR-aware). None on hard error."""
        if not self.dashboard:
            logger.error("Internal Error: no Dashboard")
            return None

        file_paths: list[str] = []
        dicomdir_file = os.path.join(root_dir, "DICOMDIR")
        if os.path.exists(dicomdir_file):
            try:
                ds = dcmread(fp=dicomdir_file)
                root_dir = str(Path(str(ds.filename)).resolve().parent)
                msg = _("Reading DICOMDIR Root directory" + f": {Path(root_dir).stem}...")
                logger.info(msg)
                self.dashboard.set_status(msg)

                for patient in ds.patient_records:
                    logger.info(f"PATIENT: PatientID={patient.PatientID}, PatientName={patient.PatientName}")
                    studies = [ii for ii in patient.children if ii.DirectoryRecordType == "STUDY"]
                    for study in studies:
                        descr = study.StudyDescription or "(no value available)"
                        logging.info(
                            f"{'  ' * 1}STUDY: StudyID={study.StudyID}, "
                            f"StudyDate={study.StudyDate}, StudyDescription={descr}"
                        )
                        all_series = [ii for ii in study.children if ii.DirectoryRecordType == "SERIES"]
                        for series in all_series:
                            images = [ii for ii in series.children if ii.DirectoryRecordType == "IMAGE"]
                            plural = ("", "s")[len(images) > 1]
                            descr = getattr(series, "SeriesDescription", "(no value available)")
                            logging.info(
                                f"{'  ' * 2}SERIES: SeriesNumber={series.SeriesNumber}, "
                                f"Modality={series.Modality}, SeriesDescription={descr} - "
                                f"{len(images)} SOP Instance{plural}"
                            )
                            elems = [ii["ReferencedFileID"] for ii in images]
                            paths = [[ee.value] if ee.VM == 1 else ee.value for ee in elems]
                            paths = [f"{root_dir}/{Path(*fp)}" for fp in paths]
                            for fp in paths:
                                if is_hidden_path(fp):
                                    continue
                                logger.info(f"{'  ' * 3}IMAGE: Path={os.fspath(fp)}")
                                file_paths.append(fp)
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
                return None
        else:
            msg = _("Reading filenames from") + f" {Path(root_dir).stem}..."
            logger.info(msg)
            self.dashboard.set_status(msg)
            file_paths = list_import_directory_files(root_dir)

        return file_paths

    def _import_directory_path(self, root_dir: str) -> None:
        """Import one directory with the same confirm UX as File → Import Directory."""
        if not self.dashboard:
            logger.error("Internal Error: no Dashboard")
            return

        file_paths = self._collect_files_from_directory(root_dir)
        if file_paths is None:
            return

        if len(file_paths) == 0:
            msg = _("No files found in") + f" {root_dir}"
            logger.info(msg)
            messagebox.showerror(
                title=_("Import Directory Error"),
                message=msg,
                parent=self,
            )
            self.dashboard.set_status(msg)
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
            return

        msg = _("Importing") + f" {len(file_paths)} {_('file') if len(file_paths) == 1 else _('files')}"
        logger.info(msg)
        self.dashboard.set_status(msg)

        assert self.controller is not None
        dlg = ImportFilesDialog(self, self.controller.anonymizer, sorted(file_paths))
        files_processed = dlg.get_input()
        msg = _("Files processed") + f": {files_processed}"
        logger.info(msg)
        self.dashboard.set_status(msg)

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

        self.query_view = QueryView(self.dashboard, self.controller, self.fonts)
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

        self.export_view = ExportView(self.dashboard, self.controller, self.fonts)
        if self.export_view is None:
            logger.error("Internal Error creating ExportView")
            return

        self.export_view.focus()

    def view(self):
        logging.info("OPEN DatasetView")

        if not self.controller:
            logger.error("Internal Error: no ProjectController")
            return

        if self.dataset_view and self.dataset_view.winfo_exists():
            logger.info("DatasetView already OPEN")
            self.dataset_view.deiconify()
            self.dataset_view.focus_force()
            return

        if not self.dashboard:
            logger.error("Internal Error: no Dashboard")
            return

        if self.dataset_view:
            del self.dataset_view

        self.dataset_view = DatasetView(self.dashboard, self.controller, self.fonts)
        if self.dataset_view is None:
            logger.error("Internal Error creating DatasetView")
            return

        self.dataset_view.focus()

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

        dlg = SettingsDialog(self, self.controller.model, title=_("Project Settings"), project_controller=self.controller)
        edited_model, null_java_phi, ctp_lookup_preview = dlg.get_input()
        if edited_model is None:
            logger.info("Settings Cancelled")
            return

        logger.info("User Edited ProjectModel")

        self.controller.update_model(edited_model)

        logger.info(f"{self.controller}")

    def show_ai_features_setup_dialog(self) -> None:
        from anonymizer.view.ai.ai_features_dialog import show_ai_features_setup_dialog

        def on_changed() -> None:
            if self.dataset_view is not None and self.dataset_view.winfo_exists():
                self.dataset_view.refresh_ai_feature_ui()

        show_ai_features_setup_dialog(self, on_changed=on_changed)

    def open_user_manual(self, slug: str = "") -> None:
        """Open the clinician user manual (browser, with local site/ fallback)."""
        if not open_help_page(slug):
            messagebox.showwarning(
                title=_("Help"),
                message=_("Could not open the user manual in a browser. Check your network or build docs locally (mkdocs serve)."),
                parent=self,
            )

    def open_tutorials(self) -> None:
        """Open the tutorials YouTube channel in the default browser."""
        if not open_tutorials_channel():
            messagebox.showwarning(
                title=_("Help"),
                message=_("Could not open the tutorials channel in a browser."),
                parent=self,
            )

    def show_help_view(self, html_file_path: Path, *, title: str | None = None) -> None:
        """Show an in-app HTML help page (e.g. License)."""
        view_name = title or html_file_path.stem
        existing = self.help_views.get(view_name)
        if existing is not None:
            with contextlib.suppress(tk.TclError):
                if existing.winfo_exists():
                    existing.deiconify()
                    existing.focus()
                    return
        self.help_views[view_name] = HTMLView(self, title=view_name, html_file_path=html_file_path.as_posix())
        self.help_views[view_name].focus()

    def open_license_help(self) -> None:
        """Open the bundled License HTML in an in-app HTMLView."""
        path = license_html_path()
        if path is None or not path.is_file():
            messagebox.showwarning(
                title=_("Help"),
                message=_("License help file was not found."),
                parent=self,
            )
            return
        self.show_help_view(path, title=_("License"))

    def get_help_menu(self, menu_bar: tk.Menu):
        help_menu = tk.Menu(menu_bar, tearoff=0)
        help_menu.add_command(label=_("User Manual"), command=lambda: self.open_user_manual(""))
        help_menu.add_command(label=_("Tutorials"), command=self.open_tutorials)
        help_menu.add_separator()
        help_menu.add_command(label=_("License"), command=self.open_license_help)
        return help_menu

    def _live_app_windows(self) -> list[tk.Misc]:
        live: list[tk.Misc] = []
        surviving: list[weakref.ref] = []
        for ref in self._app_windows:
            window = ref()
            if window is None:
                continue
            try:
                if not window.winfo_exists():
                    continue
            except tk.TclError:
                continue
            live.append(window)
            surviving.append(ref)
        self._app_windows = surviving
        return live

    def register_app_window(self, window: tk.Misc) -> None:
        for existing in self._live_app_windows():
            if existing is window:
                self._attach_menu_to_window(window)
                self.refresh_window_menu()
                return
        self._app_windows.append(weakref.ref(window))
        self._attach_menu_to_window(window)
        self.refresh_window_menu()

    def unregister_app_window(self, window: tk.Misc) -> None:
        self._app_windows = [ref for ref in self._app_windows if ref() is not None and ref() is not window]
        self.refresh_window_menu()

    def _attach_menu_to_window(self, window: tk.Misc) -> None:
        # Windows/Linux: menubar only on Welcome/Dashboard (this root). macOS: share
        # the system menubar while child windows are focused.
        from anonymizer.view.common.app_window import attach_menubar_to_toplevels

        if not attach_menubar_to_toplevels() or self.menu_bar is None:
            return
        try:
            window.configure(menu=self.menu_bar)
        except tk.TclError:
            logger.debug("Could not attach menu_bar to %s", window, exc_info=True)

    def _reattach_menu_to_registered_windows(self) -> None:
        for window in self._live_app_windows():
            self._attach_menu_to_window(window)

    def _focus_root_window(self) -> None:
        from anonymizer.view.common.app_window import focus_app_window

        focus_app_window(self)

    def refresh_window_menu(self) -> None:
        from anonymizer.view.common.app_window import focus_app_window, window_menu_label_for

        window_menu = self._window_menu
        if window_menu is None:
            return
        try:
            end = window_menu.index("end")
        except tk.TclError:
            return
        if end is not None:
            window_menu.delete(0, end)

        window_menu.add_command(label=_("Dashboard"), command=self._focus_root_window)
        for window in self._live_app_windows():
            label = window_menu_label_for(window)
            window_menu.add_command(
                label=label,
                command=lambda win=window: focus_app_window(win),
            )

    def _finalize_menu_bar(self, menu_bar: tk.Menu) -> tk.Menu:
        self.config(menu=menu_bar)
        self._reattach_menu_to_registered_windows()
        self.refresh_window_menu()
        return menu_bar

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

        file_menu.add_command(label=_("Exit"), command=self.quit_app)

        menu_bar.add_cascade(label=_("File"), menu=file_menu)

        window_menu = tk.Menu(menu_bar, tearoff=0)
        menu_bar.add_cascade(label=_("Window"), menu=window_menu)
        self._window_menu = window_menu

        # Help Menu:
        menu_bar.add_cascade(label=_("Help"), menu=self.get_help_menu(menu_bar))

        return self._finalize_menu_bar(menu_bar)

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
        file_menu.add_command(label=_("Exit"), command=self.quit_app)

        menu_bar.add_cascade(label=_("File"), menu=file_menu)

        # View Menu:
        view_menu = tk.Menu(self, tearoff=0)
        view_menu.add_command(label=_("Project"), command=self.settings)

        menu_bar.add_cascade(label=_("Settings"), menu=view_menu)

        window_menu = tk.Menu(menu_bar, tearoff=0)
        menu_bar.add_cascade(label=_("Window"), menu=window_menu)
        self._window_menu = window_menu

        # Help Menu:
        menu_bar.add_cascade(label=_("Help"), menu=self.get_help_menu(menu_bar))

        return self._finalize_menu_bar(menu_bar)

    def disable_file_menu(self):
        logger.debug("disable_file_menu")

        if self.menu_bar:
            self.menu_bar.entryconfig(_("File"), state="disabled")

    def enable_file_menu(self):
        logger.debug("enable_file_menu")

        if self.menu_bar:
            self.menu_bar.entryconfig(_("File"), state="normal")

    def _begin_import(self) -> bool:
        if self._import_in_progress:
            messagebox.showwarning(
                title=_("Import"),
                message=_("An import is already in progress."),
                parent=self,
            )
            return False
        self._import_in_progress = True
        return True

    def _end_import(self) -> None:
        self._import_in_progress = False
        self.enable_file_menu()


def run_GUI(logs_dir):
    from anonymizer.view.common.ctk_safe import install_safe_scaling_tracker, install_safe_tk_font_destructor

    install_safe_scaling_tracker()
    install_safe_tk_font_destructor()
    try:
        app = Anonymizer(Path(logs_dir))
        app._log_ctk_scaling()
        app.lift()
        app.focus_force()
        logger.info("ANONYMIZER GUI initialised successfully.")
    except Exception as e:
        logger.exception(f"Error initialising ANONYMIZER GUI, exiting: {str(e)}")
        sys.exit(1)

    _signal_quit_count = 0

    def _signal_quit(signum, _frame) -> None:
        nonlocal _signal_quit_count
        _signal_quit_count += 1
        if _signal_quit_count >= 2:
            # Second Ctrl-C / SIGTERM: do not wait for Tk teardown (can hang).
            logger.error("Signal %s received again - forcing immediate process exit", signum)
            os._exit(128 + int(signum))
        logger.info("Signal %s received, scheduling graceful quit", signum)
        if app.winfo_exists():
            app.after(0, app.quit_app)
        else:
            os._exit(128 + int(signum))

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(ValueError, OSError):
            signal.signal(sig, _signal_quit)

    logger.info("ANONYMIZER GUI MAINLOOP...")
    try:
        app.mainloop()
    except Exception as e:
        logger.exception(f"Error in ANONYMIZER GUI MAINLOOP: {str(e)}")
    finally:
        with contextlib.suppress(Exception):
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


def create_headless_controller(project_model_path: Path) -> ProjectController | None:
    if not project_model_path.exists():
        logger.error(_("Project Model file not found") + f": {project_model_path}")
        return None

    if not project_model_path.is_file():
        logger.error(_("Project Model path is not a file") + f": {project_model_path}")
        return None

    try:
        file_model = load_model(project_model_path)
    except Exception as e:
        logger.error(f"Error loading Project Model: {str(e)}")
        return None

    logger.info(f"Project Model succesfully loaded from: {project_model_path}")

    if not hasattr(file_model, "version"):
        logger.error("Project Model missing version")
        return None

    logger.info(_("Project Model loaded successfully, version") + f": {file_model.version}")

    if file_model.version != ProjectModel.MODEL_VERSION:
        logger.info(
            _("Project Model version mismatch")
            + f": {file_model.version} != {ProjectModel.MODEL_VERSION} "
            + _("upgrading accordingly")
        )
        model = ProjectModel()
        model.__dict__.update(file_model.__dict__)
        model.version = ProjectModel.MODEL_VERSION
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
        return None

    return controller


def run_HEADLESS_AI_BATCH(project_model_path: Path, ai_batch_path: Path) -> int:
    """Run one-shot AI batch for studies in a project, then exit."""
    from anonymizer.controller.ai_batch_config import (
        AiBatchConfig,
        AiBatchConfigError,
        resolve_ai_batch_studies,
        validate_ai_batch_config_gates,
    )
    from anonymizer.controller.ai_batch_process import format_ai_batch_completion_summary

    controller = create_headless_controller(project_model_path)
    if controller is None:
        return 1

    try:
        batch_config = AiBatchConfig.from_path(ai_batch_path)
        batch_config.apply_segmentation_modes()
        validate_ai_batch_config_gates(batch_config)
        studies = resolve_ai_batch_studies(
            batch_config,
            images_dir=controller.model.images_dir(),
            anon_model=controller.anonymizer.model,
        )
    except AiBatchConfigError as exc:
        logger.error("AI batch configuration error: %s", exc)
        controller.shutdown()
        controller.anonymizer.stop()
        return 1

    if not studies:
        logger.error("No studies resolved for AI batch")
        controller.shutdown()
        controller.anonymizer.stop()
        return 1

    logger.info(
        "AI batch starting: %d studies, algorithms=%s",
        len(studies),
        [algorithm.value for algorithm in batch_config.algorithms],
    )

    def on_log(message: str) -> None:
        print(message, flush=True)

    def on_progress(
        series_index: int,
        series_total: int,
        algorithm,
        algorithm_index: int,
        algorithms_total: int,
        detail: str,
        step_fraction: float,
    ) -> None:
        print(
            f"[{step_fraction * 100:.0f}%] {algorithm.value} ({algorithm_index}/{algorithms_total}) "
            f"series {series_index}/{series_total}: {detail}",
            flush=True,
        )

    summary = controller.ai_batch_process(
        list(studies),
        batch_config.to_options(),
        progress=on_progress,
        on_log=on_log,
    )
    print(format_ai_batch_completion_summary(summary), flush=True)

    controller.shutdown()
    controller.save_model()
    controller.anonymizer.stop()

    if summary.cancelled or summary.failed > 0:
        return 1
    return 0


def run_HEADLESS(project_model_path: Path):
    if not project_model_path.exists():
        logger.error(_("Project Model file not found") + f": {project_model_path}")
        return

    if not project_model_path.is_file():
        logger.error(_("Project Model path is not a file") + f": {project_model_path}")
        return

    controller = create_headless_controller(project_model_path)
    if controller is None:
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


@click.command(help=_cli_help())
@click.version_option(version=get_version(), prog_name="RSNA DICOM Anonymizer")
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, readable=True, path_type=Path),
    help=_("Path to the configuration file. If not provided, the GUI will be launched."),
)
@click.option(
    "--ai-batch",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, readable=True, path_type=Path),
    default=None,
    help=_("Path to AiBatchConfig.json for headless AI batch processing."),
)
@click.option(
    "--ai-batch-run",
    is_flag=True,
    default=False,
    help=_("Run AI batch once using --ai-batch, then exit (requires -c)."),
)
def main(config: Path | None = None, ai_batch: Path | None = None, ai_batch_run: bool = False):
    install_dir = os.path.dirname(os.path.realpath(__file__))
    logs_dir = init_logging()
    os.chdir(install_dir)
    # path[0]=="" resolves to install_dir and can shadow venv packages (e.g. totalsegmentator).
    if sys.path and sys.path[0] in ("", "."):
        sys.path.pop(0)
    from anonymizer.controller.ai.remove_pixel_phi import OCR_MODEL_DIR, OcrModelStatus, probe_ocr_models

    tseg_home = Path("assets/ai/tseg")
    tseg_weights = tseg_home / "nnunet" / "results"
    OCR_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    tseg_home.mkdir(parents=True, exist_ok=True)
    tseg_weights.mkdir(parents=True, exist_ok=True)
    os.environ["TOTALSEG_HOME_DIR"] = str(tseg_home.resolve())
    os.environ["TOTALSEG_WEIGHTS_PATH"] = str(tseg_weights.resolve())

    logger.info(f"Running from {install_dir}")
    logger.info(f"Python Optimization Level [0,1,2]: {sys.flags.optimize}")
    logger.info(f"Starting ANONYMIZER Version {get_version()}")
    logger.info(f"Running from {os.getcwd()}")
    logger.info(f"Python Version: {sys.version_info.major}.{sys.version_info.minor}")
    logger.info(f"tkinter TkVersion: {tk.TkVersion} TclVersion: {tk.TclVersion}")
    logger.info(f"Customtkinter Version: {ctk.__version__}")
    logger.info(f"pydicom Version: {pydicom_version}, pynetdicom Version: {pynetdicom_version}")

    # OCR models download on demand from AI Setup dialog.
    ocr_status, ocr_detail = probe_ocr_models()
    if ocr_status == OcrModelStatus.READY:
        try:
            file_count = len([p for p in OCR_MODEL_DIR.iterdir() if not p.name.startswith(".")])
        except OSError:
            file_count = 0
        logger.info("OCR models: downloaded (%d files)", file_count)
    else:
        logger.info(
            "OCR models: %s (enable Remove Pixel PHI in AI Features setup to download)",
            ocr_detail,
        )

    # TotalSegmentator runtime (Harmonize / Face Blur prerequisites and model cache).
    from anonymizer.controller.ai.tseg.readiness import log_runtime_status

    log_runtime_status()

    from anonymizer.controller.ai.tseg.config import apply_ai_features_preferences

    apply_ai_features_preferences()

    if ai_batch_run:
        if config is None or ai_batch is None:
            logger.error("--ai-batch-run requires both -c/--config and --ai-batch")
            sys.exit(2)
        sys.exit(run_HEADLESS_AI_BATCH(config, ai_batch))

    if config:
        run_HEADLESS(config)
    else:
        run_GUI(logs_dir)


if __name__ == "__main__":
    main()
