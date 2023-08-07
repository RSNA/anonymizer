import os
from pathlib import Path
import tkinter as tk
from tkinter import filedialog
import customtkinter as ctk
from PIL import Image
import logging
import logging.handlers
from utils.translate import _
from pydicom import config as pydicom_config
from __version__ import __version__

# All UX View Modules:
import view.new_open_project as new_open_project
import view.welcome as welcome
import view.help as help
import view.storage_dir as storage_dir
import view.storage_scp as storage_scp
import view.select_local_files as select_local_files
import view.query_retrieve_scp as query_retrieve_scp

# To ensure DICOM C-STORE SCP is stopped and socket is closed on exit:
import controller.dicom_storage_scp as dicom_storage_scp

LOGS_DIR = "/logs/"
LOG_FILENAME = "anonymizer.log"
LOG_SIZE = 1024 * 1024
LOG_BACKUP_COUNT = 10
LOG_DEFAULT_LEVEL = logging.DEBUG
LOG_FORMAT = "{asctime} {levelname} {module}.{funcName}.{lineno} {message}"

logger = logging.getLogger()  # get root logger

APP_TITLE = _("RSNA Anonymizer Version 17")
APP_MIN_WIDTH = 600
APP_MIN_HEIGHT = 250
LOGO_WIDTH = 75
LOGO_HEIGHT = 20
PAD = 10

# View Names:
WELCOME_VIEW = _("Welcome")
HELP_VIEW = _("Help")
SET_STORAGE_DIR_VIEW = _("Set Storage Directory")
CONFIGURE_STORAGE_SCP_VIEW = _("Configure Storage SCP")
ANONYMIZER_SCRIPT_VIEW = _("Anonymizer Script")
FILTER_SETTINGS_VIEW = _("Filter Settings")
SELECT_LOCAL_FILES_VIEW = _("Select Local Files")
QUERY_SCP_STORAGE_VIEW = _("Query SCP Storage")
PATIENT_INDEX_LIST_VIEW = _("Patient Index List")
EXPORT_TO_HTTPS_VIEW = _("Export to HTTPS")
EXPORT_TO_SCP_STORAGE_VIEW = _("Export to SCP Storage")
IMPORT_LOG_VIEW = _("Import Log")
EXPORT_LOG_VIEW = _("Export Log")

APP_TABS = {
    _("About"): [WELCOME_VIEW, HELP_VIEW],
    _("Storage"): [SET_STORAGE_DIR_VIEW, CONFIGURE_STORAGE_SCP_VIEW],
    _("Settings"): [ANONYMIZER_SCRIPT_VIEW, FILTER_SETTINGS_VIEW],
    _("Import"): [SELECT_LOCAL_FILES_VIEW, QUERY_SCP_STORAGE_VIEW],
    _("Verify"): [PATIENT_INDEX_LIST_VIEW],
    _("Export"): [EXPORT_TO_HTTPS_VIEW, EXPORT_TO_SCP_STORAGE_VIEW],
    _("Admin"): [IMPORT_LOG_VIEW, EXPORT_LOG_VIEW],
}


class TabViewNested(ctk.CTkTabview):
    def __init__(self, master, tabs, **kwargs):
        super().__init__(master, **kwargs)
        for tab in tabs:
            tabview = self.add(tab)

            # TODO: move all view modules in /views and import them here using importlib, move embedded tabs into APP_TABS with tuple of (view_module, view_name)
            # instead of calling create_view, automatically call the create_view function in the view module when initialised via importlib
            if tab == WELCOME_VIEW:
                welcome.create_view(tabview)
            # elif tab == HELP_VIEW:
            #     help.create_view(tabview)
            # elif tab == SET_STORAGE_DIR_VIEW:
            #     storage_dir.create_view(tabview, tab)
            # elif tab == CONFIGURE_STORAGE_SCP_VIEW:
            #     storage_scp.create_view(tabview)
            # elif tab == SELECT_LOCAL_FILES_VIEW:
            #     select_local_files.create_view(tabview)
            # elif tab == QUERY_SCP_STORAGE_VIEW:
            #     query_scp.create_view(tabview)


class TabViewMain(ctk.CTkTabview):
    def __init__(
        self,
        master,
        tabs,
        border_width,
        **kwargs,
    ):
        super().__init__(master, border_width=border_width, **kwargs)

        for main_tab, embedded_tabs in tabs.items():
            # Get the parent widget for the nested TabView
            parent = self.add(main_tab)

            # Configure the parent widget to distribute extra space to the nested TabView
            parent.rowconfigure(0, weight=1)
            parent.columnconfigure(0, weight=1)

            # Create and grid the nested TabViews
            tabview_nested = TabViewNested(master=parent, tabs=embedded_tabs)
            tabview_nested.grid(row=0, column=0, sticky="nswe")


class App(ctk.CTk):
    # File Menu when project is closed:
    # def new_project(self, event=None):
    #     logging.info("New Project")

    #     self.set_menu_project_open()

    def open_project(self, event=None):
        logging.info("Open Project")
        path = filedialog.askdirectory(title=_("Select Anonymizer Project Directory"))
        self.set_menu_project_open()

    # File Menu when project is open:
    def import_files(self, event=None):
        logging.info("Import Files")

    def import_directory(self, event=None):
        logging.info("Import Directory")

    def query_retrieve(self, event=None):
        logging.info("Query & Retrieve")

    def close_project(self, event=None):
        logging.info("Close Project")
        self.set_menu_project_closed()

    # View Menu:
    def settings(self, event=None):
        logging.info("Settings")

    def logs(self, event=None):
        logging.info("Logs")

    # Help Menu:
    def welcome(self):
        logging.info("Welcome")

    def instructions(self):
        logging.info("Instructions")

    def view_license(self):
        logging.info("View License")

    def get_help_menu(self):
        help_menu = tk.Menu(self.menu_bar, tearoff=0)
        help_menu.add_command(label=_("Welcome"), command=self.welcome)
        help_menu.add_command(label=_("Instructions"), command=self.instructions)
        help_menu.add_command(label=_("View License"), command=self.view_license)
        return help_menu

    def set_menu_project_closed(self):
        # Setup menu bar:
        if self.menu_bar is not None:
            self.menu_bar.destroy()
        self.menu_bar = tk.Menu(self)

        # File Menu:
        file_menu = tk.Menu(self, tearoff=0)
        # file_menu.add_command(
        #     label=_("New Project"), command=self.new_project, accelerator="Command+N"
        # )
        file_menu.add_command(
            label=_("Open Project"), command=self.open_project, accelerator="Command+O"
        )
        self.menu_bar.add_cascade(label=_("File"), menu=file_menu)

        # Help Menu:
        self.menu_bar.add_cascade(label=_("Help"), menu=self.get_help_menu())
        self.config(menu=self.menu_bar)

    def set_menu_project_open(self):
        # Setup menu bar:
        if self.menu_bar is not None:
            self.menu_bar.delete(0, tk.END)
        self.menu_bar = tk.Menu(self)

        # File Menu:
        file_menu = tk.Menu(self, tearoff=0)
        file_menu.add_command(
            label=_("Import Files"), command=self.import_files, accelerator="Command+F"
        )
        file_menu.add_command(
            label=_("Import Directory"),
            command=self.import_directory,
            accelerator="Command+D",
        )
        file_menu.add_command(
            label=_("Query & Retrieve"),
            command=self.query_retrieve,
            accelerator="Command+R",
        )
        file_menu.add_separator()
        file_menu.add_command(
            label=_("Close Project"),
            command=self.close_project,
            accelerator="Command+P",
        )
        self.menu_bar.add_cascade(label=_("File"), menu=file_menu)

        # View Menu:
        view_menu = tk.Menu(self, tearoff=0)
        view_menu.add_command(
            label=_("Settings"),
            # command=self.new_project,
            accelerator="Command+S",
        )
        view_menu.add_command(
            label=_("Logs"),
            command=self.logs,
            accelerator="Command+L",
        )
        self.menu_bar.add_cascade(label=_("View"), menu=view_menu)

        # Window Menu:
        window_menu = tk.Menu(self, tearoff=0)
        window_menu.add_command(label=_("Main Window"))
        self.menu_bar.add_cascade(label=_("Window"), menu=window_menu)

        # Help Menu:
        self.menu_bar.add_cascade(label=_("Help"), menu=self.get_help_menu())
        self.config(menu=self.menu_bar)

    def __init__(
        self,
        color_theme,
        title,
        logo_file,
        logo_width,
        logo_height,
        tabs,
        pad,
    ):
        super().__init__()

        ctk.set_appearance_mode("System")  # Modes: "System" (standard), "Dark", "Light"
        # sets all colors and default font:
        ctk.set_default_color_theme(color_theme)

        self.geometry(f"{APP_MIN_WIDTH}x{APP_MIN_HEIGHT}")
        # self.minsize(800, 600)  # width, height
        self.font = ctk.CTkFont()  # get default font as defined in json file
        self.title(title)
        self.title_height = self.font.metrics("linespace")
        # self.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        self.menu_bar = None
        self.set_menu_project_closed()

        # Bind keyboard shortcuts:
        # self.bind_all("<Command-n>", self.new_project)
        self.bind_all("<Command-o>", self.open_project)
        self.bind_all("<Command-p>", self.close_project)
        self.bind_all("<Command-f>", self.import_files)
        self.bind_all("<Command-d>", self.import_directory)
        self.bind_all("<Command-q>", self.query_retrieve)
        self.bind_all("<Command-s>", self.settings)
        self.bind_all("<Command-l>", self.logs)
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

        # Title:
        # self.title_label = ctk.CTkLabel(
        #     self,
        #     text=title,
        #     # font=self.font,
        # )
        # self.title_label.grid(
        #     row=0,
        #     column=0,
        #     pady=(logo_height + pad - self.title_height, 0),
        #     sticky="n",
        # )

        self.new_project_frame = ctk.CTkFrame(self)
        new_open_project.create_view(self.new_project_frame)
        self.new_project_frame.grid(row=0, column=0, padx=pad, pady=pad, sticky="nswe")

        # Content (TabView):
        # self.tab_view = TabViewMain(
        #     master=self,
        #     tabs=tabs,
        #     border_width=pad,
        # )
        # self.tab_view.grid(row=1, column=0, padx=pad, pady=(0, pad), sticky="nswe")


def setup_logging(logs_dir) -> None:
    # TODO: move logging to utils.logging and allow setup from config.json
    # TODO: provide UX to change log level
    os.makedirs(logs_dir, exist_ok=True)
    # Setup rotating log file:
    logFormatter = logging.Formatter(LOG_FORMAT, style="{")
    fileHandler = logging.handlers.RotatingFileHandler(
        logs_dir + LOG_FILENAME, maxBytes=LOG_SIZE, backupCount=LOG_BACKUP_COUNT
    )
    fileHandler.setFormatter(logFormatter)
    logger.addHandler(fileHandler)
    # Setup stderr console output:
    consoleHandler = logging.StreamHandler()
    consoleHandler.setFormatter(logFormatter)
    logger.addHandler(consoleHandler)
    logger.setLevel(LOG_DEFAULT_LEVEL)

    logging.captureWarnings(True)

    # pydicom specific:
    # TODO: ensure it reflects UX setting
    pydicom_config.debug(LOG_DEFAULT_LEVEL == logging.DEBUG)


def main():
    # TODO: handle command line arguments, implement command line interface
    install_dir = os.path.dirname(os.path.realpath(__file__))
    setup_logging(install_dir + LOGS_DIR)
    os.chdir(install_dir)

    logger.info("Starting ANONYMIZER GUI Version %s", __version__)
    logger.info(f"Running from {os.getcwd()}")

    # GUI
    app = App(
        color_theme=install_dir + "/assets/themes/rsna_color_scheme_font.json",
        title=APP_TITLE,
        logo_file=install_dir + "/assets/images/rsna_logo_alpha.png",
        logo_width=LOGO_WIDTH,
        logo_height=LOGO_HEIGHT,
        tabs=APP_TABS,
        pad=PAD,
    )

    app.mainloop()

    # Ensure DICOM C-STORE SCP is stopped and socket is closed:
    if dicom_storage_scp.server_running():
        logger.info("Final shutdown: Stop DICOM C-STORE SCP and close socket")
        dicom_storage_scp.stop(True)

    logger.info("ANONYMIZER GUI Stop.")


if __name__ == "__main__":
    main()
