import os
from pathlib import Path
import tkinter as tk
from tkinter import filedialog
from unittest.mock import DEFAULT
import customtkinter as ctk
from PIL import Image
import logging
from utils.translate import _
from utils.logging import init_logging
from __version__ import __version__
from pydicom._version import __version__ as pydicom_version
from pydicom import dcmread
from pynetdicom._version import __version__ as pynetdicom_version
from utils.ux_fields import validate_entry
from utils.storage import DEFAULT_LOCAL_STORAGE_DIR

# import view.select_local_files as select_local_files
import view.export as export
import view.query_retrieve_scp as query_retrieve_scp
import view.welcome as welcome

# To ensure DICOM C-STORE SCP is stopped and socket is closed on exit:
from controller.dicom_ae import DICOMNode
import controller.dicom_storage_scp as dicom_storage_scp
from controller.anonymize import init as init_anonymizer, anonymize_dataset_and_store

LOGS_DIR = "/logs/"
LOG_FILENAME = "anonymizer.log"
LOG_SIZE = 1024 * 1024
LOG_BACKUP_COUNT = 10
LOG_DEFAULT_LEVEL = logging.DEBUG
LOG_FORMAT = "{asctime} {levelname} {module}.{funcName}.{lineno} {message}"

logger = logging.getLogger()  # get root logger

APP_TITLE = _(DEFAULT_LOCAL_STORAGE_DIR)
APP_MIN_WIDTH = 1200
APP_MIN_HEIGHT = 800
LOGO_WIDTH = 75
LOGO_HEIGHT = 20
PAD = 10


class App(ctk.CTk):
    # File Menu when project is closed:
    def new_project(self, event=None):
        logging.info("New Project")

        self.set_menu_project_open()

    def open_project(self, event=None):
        logging.info("Open Project")
        path = filedialog.askdirectory(title=_("Select Anonymizer Project Directory"))
        self.set_menu_project_open()
        self.deiconify()

    # File Menu when project is open:
    def import_files(self, event=None):
        logging.info("Import Files")
        file_extension_filters = [
            ("dcm Files", "*.dcm"),
            ("dicom Files", "*.dicom"),
            ("All Files", "*.*"),
        ]
        paths = filedialog.askopenfilenames(filetypes=file_extension_filters)
        self.focus_force()
        if paths:
            for path in paths:
                ds = dcmread(path)
                anonymize_dataset_and_store(path, ds, DEFAULT_LOCAL_STORAGE_DIR)

    def import_directory(self, event=None):
        logging.info("Import Directory")
        path = filedialog.askdirectory(title=_("Select DICOM Directory"))
        self.focus_force()
        if path:
            # Recurse into subdirectories
            for root, dirs, files in os.walk(path):
                file_paths = [os.path.join(root, file) for file in files]
                for path in file_paths:
                    ds = dcmread(path)
                    anonymize_dataset_and_store(path, ds, DEFAULT_LOCAL_STORAGE_DIR)

    def query_retrieve(self, event=None):
        logging.info("Query & Retrieve")

        class ToplevelWindow(ctk.CTkToplevel):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.geometry(f"{1000}x{400}")
                self.validate_entry_cmd = self.register(validate_entry)
                self.title(_("Query & Import from Remote Storage Server"))
                self.rowconfigure(0, weight=1)
                self.columnconfigure(0, weight=1)
                self.qr_frame = ctk.CTkFrame(self)
                self.qr_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nswe")
                self.qr_view = query_retrieve_scp.create_view(self.qr_frame, PAD)

        if self.qr_window is None or not self.qr_window.winfo_exists():
            self.qr_window = ToplevelWindow(self)
        else:
            self.qr_window.focus_force()

    def hide_window(self):
        self.set_menu_project_closed()
        if self.qr_window:
            # self.qr_window.withdraw()  # Hide the query retrieve window
            self.qr_window.destroy()
            self.qr_window = None
        self.withdraw()  # Hide the main window

    def close_project(self, event=None):
        logging.info("Close Project")
        self.hide_window()

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
        pad,
    ):
        super().__init__()

        # Intercept the window close event
        self.protocol("WM_DELETE_WINDOW", self.hide_window)

        ctk.set_appearance_mode("System")  # Modes: "System" (standard), "Dark", "Light"
        # sets all colors and default font:
        ctk.set_default_color_theme(color_theme)

        self.validate_entry_cmd = self.register(validate_entry)
        self.geometry(f"{APP_MIN_WIDTH}x{APP_MIN_HEIGHT}")
        self.minsize(APP_MIN_WIDTH, APP_MIN_HEIGHT)  # width, height
        self.font = ctk.CTkFont()  # get default font as defined in json file
        self.title(title)
        self.title_height = self.font.metrics("linespace")
        # self.rowconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.menu_bar = None
        self.qr_window = None
        self.set_menu_project_open()

        # Bind keyboard shortcuts:
        # self.bind_all("<Command-n>", self.new_project)
        self.bind_all("<Command-o>", self.open_project)
        self.bind_all("<Command-p>", self.close_project)
        self.bind_all("<Command-f>", self.import_files)
        self.bind_all("<Command-d>", self.import_directory)
        self.bind_all("<Command-r>", self.query_retrieve)
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

        self.main_frame = ctk.CTkFrame(self)
        self.main_frame.grid(row=0, column=0, padx=pad, pady=pad, sticky="nswe")
        self.export_view = export.create_view(self.main_frame, pad)


def main():
    # TODO: handle command line arguments, implement command line interface
    install_dir = os.path.dirname(os.path.realpath(__file__))
    init_logging(install_dir)
    os.chdir(install_dir)

    logger = logging.getLogger()  # get root logger
    logger.info("Starting ANONYMIZER GUI Version %s", __version__)
    logger.info(f"Running from {os.getcwd()}")
    logger.info(
        f"pydicom Version: {pydicom_version}, pynetdicom Version: {pynetdicom_version}"
    )

    # Initialise controller.anonymize module:
    if not init_anonymizer():
        logger.error("Failed to initialise controller.anonymize module")
        return

    # Start DICOM C-STORE SCP:
    dicom_storage_scp.start(
        DICOMNode("127.0.0.1", 1045, "PYANON", True),
        DEFAULT_LOCAL_STORAGE_DIR,
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

    app.mainloop()

    # Ensure DICOM C-STORE SCP is stopped and socket is closed:
    if dicom_storage_scp.server_running():
        logger.info("Final shutdown: Stop DICOM C-STORE SCP and close socket")
        dicom_storage_scp.stop(True)

    logger.info("ANONYMIZER GUI Stop.")


if __name__ == "__main__":
    main()
